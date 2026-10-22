"""Verification Governor (docs/M4_CONTROL.md §2): per-PSP check budgets, never the checks themselves.

The IBM project's governor scheduled every check itself; here M2's governed clients run the token bucket and
M4 only publishes its parameters, so high-rate check traffic never crosses module boundaries.

    spare  = max(0, C_status * knee - used)
    rate_p = clamp(spare_share * spare * share_p, r_min, r_max_frac * C_status * share_p)
    burst_p = ceil(burst_mult * rate_p)
DEFER_CHECKS (approved, per bank or switch) is applied by M2 per payment; the Governor does not rescale here.
"""
from __future__ import annotations

import math
from typing import Optional

PSPS = ("P1", "P2", "P3")


def _feat(snapshot: dict, segment_id: str, name: str) -> Optional[float]:
    for s in snapshot.get("segments", []):
        if s["segment_id"] == segment_id:
            return s["features"].get(name)
    return None


def compute_budgets(cfg, snapshot: dict) -> dict:
    """{psp: {rate_per_s, burst, first_check_delay_ms, max_checks, horizon_ms, ledger_wait_ms}}"""
    g = cfg.c.governor
    cap = g.default_capacity_per_s
    used = _feat(snapshot, "switch:*:*", "status_check_rate") or 0.0
    spare = max(0.0, cap * g.knee - used)
    fresh = {p: _feat(snapshot, f"psp:{p}:*", "fresh_rate") for p in PSPS}
    total = sum(v for v in fresh.values() if v)
    out = {}
    for p in PSPS:
        share = (fresh[p] / total) if total and fresh[p] else 1.0 / len(PSPS)
        r_max = max(g.r_min, g.r_max_frac * cap * share)
        rate = min(r_max, max(g.r_min, g.spare_share * spare * share))
        out[p] = {"rate_per_s": round(rate, 4), "burst": int(math.ceil(g.burst_mult * rate)),
                  "first_check_delay_ms": g.first_check_delay_ms, "max_checks": g.max_checks,
                  "horizon_ms": g.horizon_ms, "ledger_wait_ms": g.ledger_wait_ms}
    return out


def changed(cfg, old: Optional[dict], new: dict) -> bool:
    if old is None:
        return True
    for k, v in new.items():
        o = old.get(k)
        if o is None or (o == 0 and v != 0) or (o and abs(v - o) / abs(o) > cfg.c.governor.publish_change):
            return True
    return False
