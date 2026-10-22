"""Train the point-of-no-return grid from M2 batch runs (docs/M3_DETECTION.md §6.2-§6.4).

Offline only: this script MAY read ground_truth.json; the live pipeline never imports it (pitfall 4).
Labels: a run is *stuck* if goodput (closed CONFIRMED_SUCCESS per s) over [trigger end + 60 s, + 120 s] is below
50 % of the warm-up baseline. Samples: one per tick from trigger start to trigger end + 60 s for every PSP
(the switch couples PSPs). Features are recomputed with this module's own pipeline.

    python scripts/train_forecaster.py --runs ../data/runs --out ../data/models/forecaster_grid.json
TODO(M3): split by configuration into sets A/B/C (§6.3), oversample near the boundary, report AUC/Brier on B.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdet import segments as S  # noqa: E402
from qdet.config import default as default_cfg  # noqa: E402
from qdet.forecast.grid import StuckGrid  # noqa: E402
from qdet.forecast.runtime import phase_point  # noqa: E402
from qdet.pipeline import Pipeline  # noqa: E402

STUCK_FRAC = 0.5
JUDGE_FROM_S, JUDGE_TO_S, SAMPLE_TAIL_S = 60, 120, 60


def goodput_per_s(events: list, n_s: int) -> np.ndarray:
    g = np.zeros(n_s + 1)
    for e in events:
        if e["event_type"] == "PAYMENT_CLOSED" and e["close_reason"] == "CONFIRMED_SUCCESS":
            s = e["sim_ms"] // 1000
            if s <= n_s:
                g[s] += 1
    return g


def samples_for_run(d: Path, cfg) -> tuple:
    gt = [t for t in json.loads((d / "ground_truth.json").read_text()) if t["is_incident"]]
    if not gt:
        return [], None
    events = [json.loads(x) for x in (d / "events.jsonl").open(encoding="utf-8")]
    end_ms = max(t["end_ms"] for t in gt)
    start_ms = min(t["onset_ms"] for t in gt)
    horizon_s = max(e["sim_ms"] for e in events) // 1000
    g = goodput_per_s(events, horizon_s)
    base = g[60:120].mean()
    judge = g[end_ms // 1000 + JUDGE_FROM_S:end_ms // 1000 + JUDGE_TO_S]
    if base <= 0 or judge.size == 0:
        return [], None
    stuck = float(judge.mean() < STUCK_FRAC * base)
    rid = d.name
    p = Pipeline(rid, rid.split("-")[3], cfg, validate=False, grid=None)
    out, i, t = [], 0, cfg.tick_ms
    while t <= end_ms + SAMPLE_TAIL_S * 1000:
        j = i
        while j < len(events) and events[j]["sim_ms"] < t:
            j += 1
        p.ingest(events[i:j])
        i = j
        p.tick(t)
        if t >= start_ms:
            for k in range(S.NP):
                seg = next(s for s in p.last_snapshot["segments"] if s["segment_id"] == f"psp:{S.PSPS[k]}:*")
                pp = seg.get("phase_point")
                if pp:
                    out.append((pp["delay_frac"], pp["orbit_frac"], stuck))
        t += cfg.tick_ms
    return out, stuck


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="../data/runs")
    ap.add_argument("--out", default="../data/models/forecaster_grid.json")
    a = ap.parse_args()
    cfg = default_cfg()
    rows, labels = [], []
    for d in sorted(Path(a.runs).iterdir()):
        if (d / "events.jsonl").is_file() and d.name.endswith("-U0"):
            s, y = samples_for_run(d, cfg)
            rows += s
            if y is not None:
                labels.append(y)
                print(f"{d.name}: {len(s)} samples, stuck={int(y)}")
    if not rows:
        sys.exit("no U0 runs with incidents under --runs")
    x = np.array(rows)
    fc = cfg.forecaster
    g = StuckGrid(fc.delay_max, fc.orbit_max, fc.bins, cfg.versions.forecaster).fit(x[:, 0], x[:, 1], x[:, 2],
                                                                                    monotone=fc.monotone)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(g.to_dict()), encoding="utf-8")
    print(f"wrote {out}: {len(rows)} samples from {len(labels)} runs ({int(sum(labels))} stuck)")


if __name__ == "__main__":
    main()
