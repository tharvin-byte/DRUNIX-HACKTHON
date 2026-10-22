"""Segment registry and involvement mapping (docs/M3_DETECTION.md §2).

Order (25): platform, psp P1-P3, bank B1-B5, route Pk:Bj (15), switch. An attempt-level event counts in platform,
its PSP, the remitter AND beneficiary bank (once if equal) and both routes psp:remitter, psp:beneficiary (once if
equal). STATUS_* events also count in switch. Bank involvement double-counts by design (pitfall 2).
"""
from __future__ import annotations

PSPS = ("P1", "P2", "P3")
BANKS = ("B1", "B2", "B3", "B4", "B5")
NP, NB = len(PSPS), len(BANKS)

SEGMENTS: tuple = (("platform:*:*",) + tuple(f"psp:{p}:*" for p in PSPS) + tuple(f"bank:*:{b}" for b in BANKS)
                   + tuple(f"route:{p}:{b}" for p in PSPS for b in BANKS) + ("switch:*:*",))
N = len(SEGMENTS)
INDEX = {s: i for i, s in enumerate(SEGMENTS)}
PLATFORM, PSP0, BANK0, ROUTE0, SWITCH = 0, 1, 1 + NP, 1 + NP + NB, N - 1
PSP_IDX = {p: i for i, p in enumerate(PSPS)}
BANK_IDX = {b: i for i, b in enumerate(BANKS)}


def route_index(p: int, b: int) -> int:
    return ROUTE0 + p * NB + b


def _involve(p: int, r: int, b: int) -> tuple:
    segs = {PLATFORM, PSP0 + p, BANK0 + r, BANK0 + b, route_index(p, r), route_index(p, b)}
    return tuple(sorted(segs))


_INVOLVE = [[[_involve(p, r, b) for b in range(NB)] for r in range(NB)] for p in range(NP)]


def involved(p: int, r: int, b: int, status: bool = False) -> tuple:
    segs = _INVOLVE[p][r][b]
    return segs + (SWITCH,) if status else segs


def parse(segment_id: str) -> tuple:
    level, psp, bank = segment_id.split(":")
    return level, psp, bank


def within(a: str, b: str) -> bool:
    """True if segment a is contained in segment b (b's parts are '*' or equal to a's).

    Used instead of symmetric wildcard overlap, which in the IBM project let a bank alert be rewritten to an
    unrelated PSP primary (OldReference docs/DEVIATIONS WP-11 follow-up)."""
    la, pa, ba = parse(a)
    lb, pb, bb = parse(b)
    if lb == "platform":
        return True
    if lb == "switch" or la == "switch":
        return la == lb
    return pb in ("*", pa) and bb in ("*", ba)


def overlaps(a: str, b: str) -> bool:
    """Wildcard-compatible segments (spec §7 merge rule). The switch only overlaps platform and itself."""
    la, pa, ba = parse(a)
    lb, pb, bb = parse(b)
    if "switch" in (la, lb):
        return la == lb or "platform" in (la, lb)
    return (pa == pb or "*" in (pa, pb)) and (ba == bb or "*" in (ba, bb))


def psps_of(segment_id: str) -> tuple:
    """PSPs a segment involves (all PSPs for bank/platform/switch segments)."""
    _, p, _ = parse(segment_id)
    return PSPS if p == "*" else (p,)
