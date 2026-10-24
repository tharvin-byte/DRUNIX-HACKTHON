"""M4-T05 Operator-delay sweep script (docs/M4_CONTROL.md §8).

Sweeps simulated operator approval delays [5, 15, 30, 60, 120] seconds on S4 and tabulates recovery time and
excess retries, writing `data/arena/operator_sweep.json`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "m2_simulator"))

from qsim import config as config_mod  # noqa: E402
from qsim import metrics, scenarios  # noqa: E402
from qsim.engine import Engine  # noqa: E402

DELAYS_S = [5, 15, 30, 60, 120]


def run_sweep(seed: int = 5) -> dict:
    cfg = config_mod.load()
    pins = {"psp": "P1", "onset": 60_000, "duration": 65_000, "worker_loss": 0.65}
    spec = scenarios.build("S4", seed, cfg, pins)
    rows = []
    for delay_s in DELAYS_S:
        e = Engine(cfg, spec, seed, "U4", horizon_ms=260_000)
        apply_ms = pins["onset"] + 10_000 + int(delay_s * 1000)
        e.run_until(apply_ms)
        e.apply_action({
            "action_id": f"act-delay-{delay_s}",
            "action_type": "THROTTLE_RETRIES",
            "scope": {"psp": "P1"},
            "params": {"rate_fraction": 0.10, "retry_after_ms": [2000, 8000]},
        })
        e.apply_action({
            "action_id": f"act-shed-{delay_s}",
            "action_type": "SHED_EXPIRED",
            "scope": {"psp": "P1"},
            "params": {},
        })
        e.run_to_completion()
        m = metrics.run_metrics(e)
        rows.append({
            "operator_delay_s": delay_s,
            "recovery_time_s": m["recovery_time_s"],
            "excess_retries": m["excess_retries"],
            "peak_queue": m["peak_queue"],
            "goodput_min_frac": round(m["goodput_min_frac"] or 0.0, 3),
        })
    out = {
        "label": "simulation",
        "scenario": "S4",
        "seed": seed,
        "delays_s": DELAYS_S,
        "rows": rows,
    }
    target = ROOT_DIR / "data" / "arena" / "operator_sweep.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {target}: {json.dumps(rows)}")
    return out


if __name__ == "__main__":
    run_sweep()
