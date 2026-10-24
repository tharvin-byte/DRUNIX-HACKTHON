"""Train the point-of-no-return grid from M2 batch runs (docs/M3_DETECTION.md §6.2-§6.4, M3-T01).

Offline only: this script MAY read ground_truth.json; the live pipeline never imports it (pitfall 4).
Labels: a run is *stuck* if goodput (closed CONFIRMED_SUCCESS per s) over [trigger end + 60 s, + 120 s] is below
50 % of the warm-up baseline. Samples: one per tick from trigger start to trigger end + 60 s for every PSP
(the switch couples PSPs). Features are recomputed with this module's own pipeline.

Splits by configuration (all ticks of a run in one split) into A/B/C by seed range:
- A (train): 1..999
- B (validation): 1000..1999
- C (test): 2000..2999
Fits with monotone=True and monotone=False, compares AUC and Brier on B, and writes `data/models/forecaster_grid.json`.
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
from qdet.pipeline import Pipeline  # noqa: E402

STUCK_FRAC = 0.5
JUDGE_FROM_S, JUDGE_TO_S, SAMPLE_TAIL_S = 60, 120, 60


def split_of_seed(seed: int) -> str:
    if 1 <= seed <= 999:
        return "A"
    if 1000 <= seed <= 1999:
        return "B"
    if 2000 <= seed <= 2999:
        return "C"
    return "A"


def split_of_run_id(run_id: str) -> str:
    parts = run_id.split("-")
    seed = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
    return split_of_seed(seed)


def split_runs(run_records: list[dict]) -> dict[str, list[dict]]:
    """Group run records into disjoint splits A, B, C by configuration (run_id)."""
    splits: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    for r in run_records:
        sp = split_of_run_id(r["run_id"])
        splits[sp].append(r)
    return splits


def brier_and_auc(grid: StuckGrid, samples: np.ndarray) -> tuple[float, float]:
    if samples.size == 0:
        return 0.0, 0.5
    preds = np.array([grid.predict(float(row[0]), float(row[1]))[0] for row in samples])
    y = samples[:, 2]
    brier = float(np.mean((preds - y) ** 2))
    pos = preds[y >= 0.5]
    neg = preds[y < 0.5]
    if len(pos) == 0 or len(neg) == 0:
        return round(brier, 4), 0.5
    # Mann-Whitney U statistic for ROC AUC
    comparisons = (pos[:, None] > neg[None, :]).astype(float) + 0.5 * (pos[:, None] == neg[None, :]).astype(float)
    auc = float(comparisons.mean())
    return round(brier, 4), round(auc, 4)


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
    warm_end = min(120, start_ms // 1000)
    warm_start = max(10, warm_end - 60)
    base = g[warm_start:warm_end].mean() if warm_end > warm_start else g[:60].mean()
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
        if t >= 60_000:
            label = 0.0 if t < start_ms else (stuck if t >= start_ms + 15_000 else None)
            if label is not None:
                for k in range(S.NP):
                    seg = next(s for s in p.last_snapshot["segments"] if s["segment_id"] == f"psp:{S.PSPS[k]}:*")
                    pp = seg.get("phase_point")
                    if pp:
                        out.append((pp["delay_frac"], pp["orbit_frac"], label))
        t += cfg.tick_ms
    return out, stuck


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="../data/runs")
    ap.add_argument("--out", default="../data/models/forecaster_grid.json")
    a = ap.parse_args()
    cfg = default_cfg()
    run_records = []
    for d in sorted(Path(a.runs).iterdir()):
        if (d / "events.jsonl").is_file() and d.name.endswith("-U0"):
            s, y = samples_for_run(d, cfg)
            if y is not None and s:
                run_records.append({"run_id": d.name, "samples": s, "stuck": y})
                print(f"{d.name} (split {split_of_run_id(d.name)}): {len(s)} samples, stuck={int(y)}")
    if not run_records:
        sys.exit("no U0 runs with incidents under --runs")

    splits = split_runs(run_records)
    train_rows = [row for r in splits["A"] for row in r["samples"]]
    val_rows = [row for r in splits["B"] for row in r["samples"]]
    if not train_rows:
        train_rows = [row for r in run_records for row in r["samples"]]
    if not val_rows:
        val_rows = train_rows

    fc = cfg.forecaster
    # Weak prior samples on bin centres prevent unobserved off-diagonal cells from defaulting to 0.5
    prior_rows = []
    de = np.linspace(0, fc.delay_max, fc.bins, endpoint=False) + fc.delay_max / (2 * fc.bins)
    oe = np.linspace(0, fc.orbit_max, fc.bins, endpoint=False) + fc.orbit_max / (2 * fc.bins)
    for d_c in de:
        for o_c in oe:
            y_c = 1.0 if (d_c / fc.delay_max + o_c / fc.orbit_max) >= 0.95 else 0.0
            prior_rows.append((float(d_c), float(o_c), y_c))
            prior_rows.append((float(d_c), float(o_c), y_c))

    x_train = np.array(train_rows + prior_rows)
    x_val = np.array(val_rows)
    g_mono = StuckGrid(fc.delay_max, fc.orbit_max, fc.bins, cfg.versions.forecaster).fit(
        x_train[:, 0], x_train[:, 1], x_train[:, 2], monotone=True
    )
    g_raw = StuckGrid(fc.delay_max, fc.orbit_max, fc.bins, cfg.versions.forecaster).fit(
        x_train[:, 0], x_train[:, 1], x_train[:, 2], monotone=False
    )
    brier_mono, auc_mono = brier_and_auc(g_mono, x_val)
    brier_raw, auc_raw = brier_and_auc(g_raw, x_val)

    g_final = g_mono if fc.monotone else g_raw
    payload = g_final.to_dict()
    payload["metrics_val_B"] = {
        "monotone": {"brier": brier_mono, "auc": auc_mono},
        "unsmoothed": {"brier": brier_raw, "auc": auc_raw},
        "train_runs": len(splits["A"]),
        "val_runs": len(splits["B"]),
        "test_runs": len(splits["C"]),
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"wrote {out}: train_samples={len(x_train)} val_samples={len(x_val)} "
        f"monotone(AUC={auc_mono}, Brier={brier_mono}) raw(AUC={auc_raw}, Brier={brier_raw})"
    )


if __name__ == "__main__":
    main()
