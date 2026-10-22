"""Fault Localizer by involvement lift (docs/M3_DETECTION.md §5).

Keeps the IBM localizer's structure (pure verdict function on count matrices, hysteresis wrapper, candidate
list) but the math is new: a bank is counted in BOTH roles (remitter, beneficiary) and judged by its lift over its
baseline involvement, and the switch has its own verdict. Input cells are indexed [psp, remitter, beneficiary].
Runtime is a handful of numpy reductions (< 1 ms per tick).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from qdet import segments as S


@dataclass
class Localization:
    verdict: str
    primary_segment_id: Optional[str] = None
    candidates: list = field(default_factory=list)
    confidence: float = 0.0
    total_excess: float = 0.0

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "primary_segment_id": self.primary_segment_id,
                "candidates": self.candidates, "confidence": round(self.confidence, 4),
                "total_excess": round(self.total_excess, 3)}


def _inv(a: np.ndarray) -> np.ndarray:
    """Per bank b: sum over cells where b is the remitter OR the beneficiary (counted once). a: (P, R, B)."""
    rem = a.sum(axis=(0, 2))
    ben = a.sum(axis=(0, 1))
    same = np.einsum("pbb->b", a)
    return rem + ben - same


def _inv_by_psp(a: np.ndarray) -> np.ndarray:
    """Route union per (psp, bank): cells of psp p where b is remitter or beneficiary. Shape (P, B)."""
    return a.sum(axis=2) + a.sum(axis=1) - np.einsum("pbb->pb", a)


def raw_verdict(bad: np.ndarray, exp: np.ndarray, base_inv: np.ndarray, switch_hot: bool, cfg) -> Localization:
    """Stateless verdict for one tick. bad/exp: (NP, NB, NB) counts over Ws; base_inv: baseline involvement (NB)."""
    c = cfg.localizer
    bad, exp = np.asarray(bad, float), np.asarray(exp, float)
    n_ex = max(0.0, float(bad.sum() - exp.sum()))
    if n_ex < c.min_excess:
        return Localization("INSUFFICIENT_EVIDENCE", total_excess=n_ex)
    bp, ep_ = bad.sum(axis=(1, 2)), exp.sum(axis=(1, 2))
    ex_p = np.maximum(0.0, bp - ep_)
    EP = ex_p / ex_p.sum() if ex_p.sum() > 0 else np.zeros_like(ex_p)
    IB = np.clip(np.maximum(0.0, _inv(bad) - _inv(exp)) / n_ex, 0.0, 1.0)
    lift = IB - np.asarray(base_inv, float)
    cells = np.maximum(0.0, _inv_by_psp(bad) - _inv_by_psp(exp))
    cell = cells / cells.sum() if cells.sum() > 0 else np.zeros_like(cells)
    pi, bi = int(EP.argmax()), int(IB.argmax())
    others_ib = np.delete(IB, bi)
    cands = sorted([{"segment_id": f"psp:{S.PSPS[p]}:*", "share": round(float(EP[p]), 4), "lift": 0.0}
                    for p in range(S.NP)] +
                   [{"segment_id": f"bank:*:{S.BANKS[b]}", "share": round(float(IB[b]), 4),
                     "lift": round(float(lift[b]), 4)} for b in range(S.NB)],
                   key=lambda x: -max(x["share"], x["lift"]))[:3]
    conf = min(1.0, n_ex / c.confidence_excess)
    if switch_hot and EP.max() < c.switch_max_ep and lift.max() < c.switch_max_lift:
        return Localization("SWITCH_STATUS_OVERLOAD", "switch:*:*", cands, conf, n_ex)
    if EP[pi] >= c.route_ep and IB[bi] >= c.route_ib and cell[pi, bi] >= c.route_cell:
        rc = [{"segment_id": f"route:{S.PSPS[pi]}:{S.BANKS[bi]}", "share": round(float(cell[pi, bi]), 4),
               "lift": round(float(lift[bi]), 4)}] + cands[:2]
        return Localization("ROUTE_SPECIFIC", f"route:{S.PSPS[pi]}:{S.BANKS[bi]}", rc, float(cell[pi, bi]) * conf, n_ex)
    if IB[bi] >= c.bank_ib and lift[bi] >= c.bank_lift and (others_ib <= c.bank_other_ib_max).all() \
            and EP.max() < c.bank_max_ep:
        return Localization("BANK_SIDE", f"bank:*:{S.BANKS[bi]}", cands, float(IB[bi]) * conf, n_ex)
    if EP[pi] >= c.psp_ep and lift.max() < c.psp_max_lift:
        return Localization("PSP_SIDE", f"psp:{S.PSPS[pi]}:*", cands, float(EP[pi]) * conf, n_ex)
    # PSP concentration relative to expected traffic: a flat fault gives EP ~= traffic share, which is not MULTI
    psp_lift = EP - (ep_ / ep_.sum() if ep_.sum() > 0 else 0.0)
    if (IB >= c.multi_bank_ib).sum() >= 2 or ((EP >= c.multi_psp_ep) & (psp_lift >= c.multi_psp_lift)).sum() >= 2:
        return Localization("MULTI_FAULT", None, cands, float(max(EP.max(), IB.max())) * conf, n_ex)
    return Localization("PLATFORM_WIDE", None, cands, conf * 0.5, n_ex)


class Localizer:
    """Accumulates per-outcome bad/expected cells in 1 s buckets and publishes verdicts with hysteresis."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        nb = cfg.windows.ring_buckets
        self.bad = np.zeros((nb, S.NP, S.NB, S.NB))
        self.exp = np.zeros((nb, S.NP, S.NB, S.NB))
        self.n = np.zeros((nb, S.NP, S.NB, S.NB))
        self.cur = -1
        self.route_bad_rate = np.full((S.NP, S.NB), cfg.localizer.exp_floor)
        self.route_p95 = np.full((S.NP, S.NB), np.nan)
        self.base_inv = np.full(S.NB, np.nan)
        self._switch_run = 0
        self._published: Optional[Localization] = None
        self._pending: Optional[str] = None
        self._pending_n = 0

    def _advance(self, sec: int) -> None:
        nb = self.bad.shape[0]
        for s in range(max(self.cur + 1, sec - nb + 1), sec + 1):
            b = s % nb
            self.bad[b] = self.exp[b] = self.n[b] = 0
        self.cur = max(self.cur, sec)

    def on_outcome(self, e: dict) -> None:
        sec = e["sim_ms"] // 1000
        if sec > self.cur:
            self._advance(sec)
        elif self.cur - sec >= self.bad.shape[0]:
            return
        p, r, b = S.PSP_IDX[e["psp"]], S.BANK_IDX[e["remitter_bank"]], S.BANK_IDX[e["beneficiary_bank"]]
        st, rt = e["status"], e["response_time_ms"]
        p95 = np.nanmax([self.route_p95[p, r], self.route_p95[p, b]]) if not (
            np.isnan(self.route_p95[p, r]) and np.isnan(self.route_p95[p, b])) else np.nan
        slow = (not np.isnan(p95)) and rt > self.cfg.localizer.bad_latency_mult * p95
        is_bad = st in ("CLIENT_TIMEOUT", "REJECTED_OVERLOAD", "RETRY_LATER", "TECH_FAILED") or slow
        k = sec % self.bad.shape[0]
        self.bad[k, p, r, b] += is_bad
        self.exp[k, p, r, b] += max(self.cfg.localizer.exp_floor, max(self.route_bad_rate[p, r], self.route_bad_rate[p, b]))
        self.n[k, p, r, b] += 1

    def window(self, end_sec: int) -> tuple:
        w = self.cfg.windows.short_s
        ix = np.arange(end_sec - w, end_sec) % self.bad.shape[0]
        return self.bad[ix].sum(axis=0), self.exp[ix].sum(axis=0), self.n[ix].sum(axis=0)

    def learn(self, bad: np.ndarray, n: np.ndarray, route_p95: np.ndarray, calm: bool) -> None:
        """Update route baselines and baseline involvement only in calm ticks (frozen during incidents)."""
        if not calm or n.sum() <= 0:
            return
        a = self.cfg.localizer.base_alpha
        rb, rn = _inv_by_psp(bad), _inv_by_psp(n)
        with np.errstate(invalid="ignore", divide="ignore"):
            rate = np.where(rn > 0, rb / np.maximum(rn, 1), np.nan)
        ok = ~np.isnan(rate)
        self.route_bad_rate[ok] = (1 - a) * self.route_bad_rate[ok] + a * np.maximum(rate[ok], self.cfg.localizer.exp_floor)
        upd = ~np.isnan(route_p95)
        self.route_p95[upd] = np.where(np.isnan(self.route_p95[upd]), route_p95[upd],
                                       (1 - a) * self.route_p95[upd] + a * route_p95[upd])
        inv = _inv(n) / n.sum()
        self.base_inv = np.where(np.isnan(self.base_inv), inv, (1 - a) * self.base_inv + a * inv)

    def localize(self, end_sec: int, switch_util: float) -> Localization:
        bad, exp, n = self.window(end_sec)
        hot = (not np.isnan(switch_util)) and switch_util >= self.cfg.localizer.switch_util
        self._switch_run = self._switch_run + 1 if hot else 0
        base = np.nan_to_num(self.base_inv, nan=0.0)
        r = raw_verdict(bad, exp, base, self._switch_run >= self.cfg.localizer.switch_ticks, self.cfg)
        return self._hysteresis(r)

    def _hysteresis(self, r: Localization) -> Localization:
        pub = self._published
        if pub is None or (r.verdict == pub.verdict and r.primary_segment_id == pub.primary_segment_id):
            self._published, self._pending, self._pending_n = r, None, 0
            return r
        key = f"{r.verdict}|{r.primary_segment_id}"
        self._pending_n = self._pending_n + 1 if self._pending == key else 1
        self._pending = key
        if self._pending_n >= self.cfg.localizer.hysteresis_ticks:
            self._published, self._pending, self._pending_n = r, None, 0
            return r
        held = Localization(pub.verdict, pub.primary_segment_id, r.candidates, r.confidence, r.total_excess)
        self._published = held
        return held
