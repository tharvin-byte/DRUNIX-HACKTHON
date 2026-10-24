"""Run metrics for `result.json` (docs/M2_SIMULATOR.md §13). Evaluator-side: may read ground truth."""
from __future__ import annotations

import numpy as np

from qsim.engine import Engine


def _nan_none(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else float(x)


def run_metrics(e: Engine, paired_u2_metrics: dict | None = None) -> dict:
    gt = e.ground_truth_stats()
    h = e.horizon // 1000
    goodput = e.ts["goodput"][:h]
    warm = min(len(goodput), e.cfg.run.warmup_ms // 1000)
    base = float(goodput[warm // 2:warm].mean()) if warm > 2 else (float(goodput.mean()) if len(goodput) else 0.0)
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
    # TAT breaches: debited attempt that was neither credited nor reversed within the TAT analogue (reversal_delay_ms)
    tat_ms = e.cfg.bank.reversal_delay_ms
    tat_breaches = 0
    for p in e.payments:
        if any(a.credited for a in p.attempts):
            continue
        for a in p.attempts:
            if a.debited and (not a.reversed or (p.resolved_ms is not None and p.resolved_ms - a.t_send > tat_ms)):
                tat_breaches += 1
                break

    peak_q = float(e.ts["queue"].sum(axis=0).max())
    harmful_failovers: float | None = 0.0
    if paired_u2_metrics is not None:
        u2_q = paired_u2_metrics.get("peak_queue") or 0.0
        u2_rec = paired_u2_metrics.get("recovery_time_s")
        worse_q = peak_q > u2_q * 1.05
        worse_rec = (recovery is None and u2_rec is not None) or (
            recovery is not None and u2_rec is not None and recovery > u2_rec + 5.0
        )
        harmful_failovers = 1.0 if (worse_q or worse_rec) else 0.0

    return {
        "peak_queue": peak_q,
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
        "harmful_failovers": harmful_failovers,
        "tat_breaches": float(tat_breaches),
        "goodput_min_frac": goodput_min_frac,
    }


def timeseries(e: Engine, from_ms: int = 0) -> dict:
    n = max(1, min(len(e.ts["goodput"]), e.now // 1000 + 1))
    s = max(0, from_ms // 1000)
    return {"t": list(range(s, n)), "goodput": e.ts["goodput"][s:n].tolist(),
            "queue": {g.name: e.ts["queue"][g.idx, s:n].tolist() for g in e.psps},
            "switch_checks_per_s": e.ts["switch_checks"][s:n].tolist(),
            "unknown_open": e.ts["unknown_open"][s:n].tolist()}
