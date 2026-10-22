"""Run metrics for `result.json` (docs/M2_SIMULATOR.md §13). Evaluator-side: may read ground truth."""
from __future__ import annotations

import numpy as np

from qsim.engine import Engine


def _nan_none(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def run_metrics(e: Engine) -> dict:
    gt = e.ground_truth_stats()
    h = e.horizon // 1000
    goodput = e.ts["goodput"][:h]
    warm = e.cfg.run.warmup_ms // 1000
    base = float(goodput[warm // 2:warm].mean()) if warm > 2 else float(goodput.mean())
    # 10 s goodput windows after warm-up, relative to the warm-up baseline
    roll = np.convolve(goodput, np.ones(10) / 10, mode="valid")[warm:] if len(goodput) > warm + 10 else np.array([])
    goodput_min_frac = float(roll.min() / base) if base > 0 and roll.size else None
    recovery = None
    ends = [t["end_ms"] for t in e.spec.truth if t["is_incident"]]
    if ends and base > 0:
        end_s = max(ends) // 1000
        ok = goodput >= 0.95 * base
        run = 0
        for s in range(end_s, len(ok)):
            run = run + 1 if ok[s] else 0
            if run >= 30:
                recovery = float(s - 29 - end_s)
                break
    resolve = [(p.resolved_ms - p.unknown_ms) / 1000.0 for p in e.payments
               if p.unknown_ms is not None and p.resolved_ms is not None]
    unknowns = gt["unknowns"]
    unique_success = sum(1 for p in e.payments if any(a.credited for a in p.attempts)
                         and p.resolved_ms is not None and p.resolved_ms - p.t0 <= e.cfg.run.goodput_deadline_ms)
    return {
        "peak_queue": float(e.ts["queue"].sum(axis=0).max()),
        "excess_retries": float(gt["attempts"] - gt["payments"]),
        "recovery_time_s": recovery,
        "unique_success": float(unique_success),
        "duplicate_commits": float(gt["duplicate_commits"]),
        "peak_switch_checks_per_s": float(e.ts["switch_checks"].max()),
        "switch_checks_total": float(gt["switch_checks"]),
        "switch_checks_per_unknown": float(gt["switch_checks"] / unknowns) if unknowns else None,
        "unknowns_total": float(unknowns),
        "median_resolve_s": _nan_none(float(np.median(resolve))) if resolve else None,
        "p95_resolve_s": _nan_none(float(np.percentile(resolve, 95))) if resolve else None,
        "escalated": float(gt["escalated"]),
        "harmful_failovers": None,      # computed by the arena against the paired U2 run (BUILD)
        "tat_breaches": None,           # TODO(M2): debited and neither credited nor reversed within the TAT analogue
        "goodput_min_frac": goodput_min_frac,
    }


def timeseries(e: Engine, from_ms: int = 0) -> dict:
    n = max(1, min(len(e.ts["goodput"]), e.now // 1000 + 1))
    s = max(0, from_ms // 1000)
    return {"t": list(range(s, n)), "goodput": e.ts["goodput"][s:n].tolist(),
            "queue": {g.name: e.ts["queue"][g.idx, s:n].tolist() for g in e.psps},
            "switch_checks_per_s": e.ts["switch_checks"][s:n].tolist(),
            "unknown_open": e.ts["unknown_open"][s:n].tolist()}
