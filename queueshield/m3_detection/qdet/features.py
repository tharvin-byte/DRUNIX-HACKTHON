"""Feature engine: one row per segment every tick (docs/M3_DETECTION.md §3).

Ported from the IBM project's qs/core/features.py. Names match `segment_state.schema.json`. NaN means
"no information" and is serialised as null, never as 0.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from qdet import segments as S
from qdet import windows as W
from qdet.baselines import Baselines
from qdet.tracker import PaymentTracker

FEATURES = ["arrival_rate", "fresh_rate", "raf", "success_ratio", "timeout_ratio", "near_timeout_ratio",
            "reject_ratio", "p50_ms", "p95_ms", "p99_ms", "latency_ratio", "pending_count", "pending_frac",
            "queue_depth", "queue_growth", "utilisation", "queue_delay_est_ms", "orbit_proxy", "status_check_rate",
            "switch_status_util", "load_over_capacity", "ledger_open_rate", "ledger_unresolved"]
FI = {f: i for i, f in enumerate(FEATURES)}
QUEUE_DELAY_CAP_MS = 60_000.0
MIN_COMPLETIONS_PER_S = 0.1


@dataclass
class FeatureTick:
    tick_ms: int
    F: np.ndarray            # (N, n_features)
    Z: np.ndarray
    B: np.ndarray            # baseline means before this tick
    spread: np.ndarray
    flags: list              # list[list[str]] per segment
    eligible: np.ndarray
    workers: np.ndarray      # per PSP, mean over Ws (NaN if no snapshots)
    sent: np.ndarray         # attempts per segment in Ws


def _mean_last(series: np.ndarray, n: int) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # all-NaN slice -> NaN is the intended result
        return np.nanmean(series[..., -n:], axis=-1)


class FeatureEngine:
    def __init__(self, cfg, tracker: PaymentTracker) -> None:
        self.cfg = cfg
        self.w = W.Windows(cfg)
        self.tracker = tracker
        warm = max(1, cfg.baselines.warmup_s * 1000 // cfg.tick_ms)
        self.bl = Baselines(FEATURES, S.N, cfg.baselines.alpha, warm, cfg.baselines.z_clip,
                            dict(cfg.baselines.spread_floor))

    def ingest(self, e: dict) -> None:
        self.w.add(e)
        self.tracker.apply(e)

    def set_frozen(self, segment_ids: set) -> None:
        rows = np.zeros(S.N, dtype=bool)
        for s in segment_ids:
            rows[S.INDEX[s]] = True
        self.bl.set_frozen(rows)

    def tick(self, now_ms: int) -> FeatureTick:
        c, w = self.cfg, self.w
        end = now_ms // 1000
        w.advance(end - 1)
        Ws, Wl, Wq = c.windows.short_s, c.windows.long_s, c.windows.queue_growth_s
        g = lambda k, win=Ws: w.sum(k, end, win)      # noqa: E731
        sent, fresh, retry, out = g(W.SENT), g(W.FRESH), g(W.RETRY), g(W.OUTCOME)
        succ_l, out_l = g(W.SUCCESS, Wl), g(W.OUTCOME, Wl)
        tmo, rej, near, comp = g(W.TIMEOUT), g(W.REJECT), g(W.NEAR), g(W.COMPLETED)
        nan = np.nan
        with np.errstate(invalid="ignore", divide="ignore"):
            arrival, fresh_rate = sent / Ws, fresh / Ws
            raf = np.where(fresh > 0, retry / np.maximum(fresh, 1) + 1.0, 1.0)
            success_ratio = np.where(out_l > 0, succ_l / np.maximum(out_l, 1), nan)
            timeout_ratio = np.where(out > 0, tmo / np.maximum(out, 1), nan)
            near_ratio = np.where(out > 0, near / np.maximum(out, 1), nan)
            reject_ratio = np.where(out > 0, rej / np.maximum(out, 1), nan)
        p50, p95, p99 = w.quantiles(w.hist_sum(end, Ws), (0.5, 0.95, 0.99), c.eligibility.latency_min_samples)
        B0 = self.bl.base()
        with np.errstate(invalid="ignore", divide="ignore"):
            latency_ratio = p95 / B0[:, FI["p95_ms"]]
        pending = self.tracker.pending_by_segment()
        with np.errstate(invalid="ignore", divide="ignore"):
            pending_frac = np.where(arrival > 0, pending / (arrival * 60.0), nan)

        # PSP snapshots mapped to segments: platform = sum, psp = own, route = its psp, bank = traffic-weighted
        ps = w.psp_series(end, Wq)                      # (3, NP, Wq)
        R = sent[S.ROUTE0:S.ROUTE0 + S.NP * S.NB].reshape(S.NP, S.NB)
        M = np.zeros((S.N, S.NP))
        M[S.PLATFORM] = 1.0
        for p in range(S.NP):
            M[S.PSP0 + p, p] = 1.0
            for b in range(S.NB):
                M[S.route_index(p, b), p] = 1.0
        for b in range(S.NB):
            col = R[:, b]
            M[S.BANK0 + b] = col / col.sum() if col.sum() > 0 else 1.0 / S.NP
        q_series = M @ np.nan_to_num(ps[0])            # (N, Wq)
        sw = w.switch_series(end, Wq)                   # (4, Wq)
        q_series[S.SWITCH] = np.nan_to_num(sw[0])
        queue_depth = q_series[:, -Ws:].mean(axis=1)
        x = np.arange(Wq, dtype=float) - (Wq - 1) / 2.0
        queue_growth = ((q_series - q_series.mean(axis=1, keepdims=True)) * x).sum(axis=1) / (x @ x)
        act, workers = _mean_last(ps[1], Ws), _mean_last(ps[2], Ws)
        Mu = M.copy()
        Mu[S.PLATFORM] = 1.0
        with np.errstate(invalid="ignore", divide="ignore"):
            utilisation = (Mu @ np.nan_to_num(act)) / (Mu @ np.nan_to_num(workers))
            cps = np.maximum(comp / Ws, MIN_COMPLETIONS_PER_S)
            queue_delay = np.minimum(queue_depth / cps * 1000.0, QUEUE_DELAY_CAP_MS)
        # switch utilisation from contract fields only: served checks / capacity, or 1 while a queue persists
        cap_s = _mean_last(sw[2:3], Ws)[0]
        sq = _mean_last(sw[0:1], Ws)[0]
        served = g(W.STATUS_OK)[S.SWITCH] / Ws
        sw_util = nan if np.isnan(cap_s) else float(min(1.0, max(served / cap_s if cap_s > 0 else 0.0,
                                                                   1.0 if sq >= 1.0 else 0.0)))
        switch_util = np.full(S.N, nan)
        switch_util[S.SWITCH] = sw_util
        utilisation[S.SWITCH] = sw_util
        orbit = self.tracker.orbit_by_segment(now_ms)
        status_rate = g(W.STATUS) / Ws
        # capacity: workers / baseline median service time (s); banks/routes apportioned by observed shares
        svc_s = B0[S.PSP0:S.PSP0 + S.NP, FI["p50_ms"]] / 1000.0
        with np.errstate(invalid="ignore", divide="ignore"):
            cap_p = np.nan_to_num(workers) / svc_s
            share = np.where(R.sum(axis=1, keepdims=True) > 0, R / np.maximum(R.sum(axis=1, keepdims=True), 1), 0.0)
            cap_route = cap_p[:, None] * share
            cap = np.concatenate([[np.nansum(cap_p)], cap_p, np.nansum(cap_route, axis=0), cap_route.ravel(), [nan]])
            load = np.where(cap > 0, arrival / np.where(cap > 0, cap, 1), nan)
        ledger_rate = g(W.LEDGER_OPEN) / Ws
        ledger_unres = self.tracker.ledger_unresolved_by_segment()

        F = np.full((S.N, len(FEATURES)), nan)
        for name, arr in (("arrival_rate", arrival), ("fresh_rate", fresh_rate), ("raf", raf),
                          ("success_ratio", success_ratio), ("timeout_ratio", timeout_ratio),
                          ("near_timeout_ratio", near_ratio), ("reject_ratio", reject_ratio), ("p50_ms", p50),
                          ("p95_ms", p95), ("p99_ms", p99), ("latency_ratio", latency_ratio),
                          ("pending_count", pending), ("pending_frac", pending_frac), ("queue_depth", queue_depth),
                          ("queue_growth", queue_growth), ("utilisation", utilisation),
                          ("queue_delay_est_ms", queue_delay), ("orbit_proxy", orbit),
                          ("status_check_rate", status_rate), ("switch_status_util", switch_util),
                          ("load_over_capacity", load), ("ledger_open_rate", ledger_rate),
                          ("ledger_unresolved", ledger_unres)):
            F[:, FI[name]] = arr
        # the switch segment carries only switch-level information
        for name in ("raf", "success_ratio", "timeout_ratio", "near_timeout_ratio", "reject_ratio",
                     "load_over_capacity", "arrival_rate", "fresh_rate"):
            F[S.SWITCH, FI[name]] = nan

        no_data = (sent == 0) & (out == 0)
        no_data[S.SWITCH] = bool(np.isnan(cap_s))
        low_vol = np.zeros(S.N, dtype=bool)
        low_vol[S.ROUTE0:S.SWITCH] = sent[S.ROUTE0:S.SWITCH] < c.eligibility.route_min_attempts
        warming = self.bl.warming_up()
        Z = self.bl.z(F)
        B = self.bl.base()
        spread = self.bl.eff_spread()
        self.bl.update(F, ~no_data)
        flags = []
        for i in range(S.N):
            f = [n for n, on in (("warming_up", warming[i]), ("low_volume", low_vol[i]), ("no_data", no_data[i]),
                                 ("baseline_frozen", self.bl.frozen[i])) if on]
            flags.append(f)
        eligible = ~(warming | no_data | low_vol)
        return FeatureTick(now_ms, F, Z, B, spread, flags, eligible, workers, sent)
