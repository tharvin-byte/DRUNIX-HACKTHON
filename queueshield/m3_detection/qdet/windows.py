"""1 s bucket ring buffers per segment plus a log-spaced latency histogram (docs/M3_DETECTION.md §3).

Ported from the IBM project's qs/core/windows.py; re-keyed to the 25 QueueShield segments and extended with
near-timeout, tech-failure, ledger and switch-snapshot counters. A window of W s ending at tick time T covers
event times in [T - W s, T).
"""
from __future__ import annotations

import math

import numpy as np

from qdet import segments as S

(SENT, FRESH, RETRY, OUTCOME, SUCCESS, DECLINED, TIMEOUT, REJECT, TECH, NEAR, STATUS, STATUS_OK, LEDGER_OPEN,
 LEDGER_RES, COMPLETED) = range(15)
N_COUNTERS = 15
# PSP snapshot fields: queue, active, workers, count ; switch snapshot fields: queue, active, cap/s, slowdown, count
PSN, SWN = 4, 5

BAD_STATUSES = ("CLIENT_TIMEOUT", "REJECTED_OVERLOAD", "RETRY_LATER", "TECH_FAILED")


class Windows:
    def __init__(self, cfg) -> None:
        w = cfg.windows
        self.nb = w.ring_buckets
        self.near_frac = w.near_timeout_frac
        self.n_bins = w.latency_bins
        self.lo, self.hi = w.latency_lo_ms, w.latency_hi_ms
        self.log_span = math.log(self.hi / self.lo)
        edges = self.lo * np.exp(self.log_span * np.arange(self.n_bins + 1) / self.n_bins)
        self.bin_mid = np.sqrt(edges[:-1] * edges[1:])
        self.c = np.zeros((N_COUNTERS, S.N, self.nb), dtype=np.int32)
        self.hist = np.zeros((S.N, self.nb, self.n_bins), dtype=np.int32)
        self.psp_snap = np.zeros((PSN, S.NP, self.nb))
        self.sw_snap = np.zeros((SWN, self.nb))
        self.cur = -1
        self.late_dropped = 0
        self.last_event_ms = None

    def lat_bin(self, ms: float) -> int:
        if ms <= self.lo:
            return 0
        b = int(self.n_bins * math.log(ms / self.lo) / self.log_span)
        return min(self.n_bins - 1, b)

    def advance(self, sec: int) -> None:
        if sec <= self.cur:
            return
        for s in range(max(self.cur + 1, sec - self.nb + 1), sec + 1):
            b = s % self.nb
            self.c[:, :, b] = 0
            self.hist[:, b, :] = 0
            self.psp_snap[:, :, b] = 0
            self.sw_snap[:, b] = 0
        self.cur = sec

    def add(self, e: dict) -> None:
        sec = e["sim_ms"] // 1000
        if sec > self.cur:
            self.advance(sec)
        elif self.cur - sec >= self.nb:
            self.late_dropped += 1
            return
        self.last_event_ms = e["sim_ms"] if self.last_event_ms is None else max(self.last_event_ms, e["sim_ms"])
        b = sec % self.nb
        t = e["event_type"]
        c = self.c
        if t == "PSP_SNAPSHOT":
            p = S.PSP_IDX[e["psp"]]
            self.psp_snap[:, p, b] += (e["queue_depth"], e["active_workers"], e["workers"], 1)
            return
        if t == "SWITCH_SNAPSHOT":
            self.sw_snap[:, b] += (e["switch_status_queue"], e["switch_status_active"],
                                   e["switch_status_capacity_per_s"], e["switch_slowdown_factor"], 1)
            return
        if "psp" not in e or "remitter_bank" not in e:
            return
        segs = S.involved(S.PSP_IDX[e["psp"]], S.BANK_IDX[e["remitter_bank"]], S.BANK_IDX[e["beneficiary_bank"]],
                          status=t.startswith("STATUS_"))
        if t == "ATTEMPT_SENT":
            kind = RETRY if e["retry_count"] > 0 else FRESH
            for s in segs:
                c[SENT, s, b] += 1
                c[kind, s, b] += 1
        elif t == "ATTEMPT_OUTCOME":
            st = e["status"]
            col = {"SUCCESS": SUCCESS, "DECLINED": DECLINED, "CLIENT_TIMEOUT": TIMEOUT, "REJECTED_OVERLOAD": REJECT,
                   "RETRY_LATER": REJECT, "TECH_FAILED": TECH}.get(st)
            if col is None:
                return
            rt = e["response_time_ms"]
            near = rt >= self.near_frac * e["client_timeout_ms"]
            completed = st in ("SUCCESS", "DECLINED", "TECH_FAILED")
            lb = self.lat_bin(rt) if completed else -1
            for s in segs:
                c[OUTCOME, s, b] += 1
                c[col, s, b] += 1
                if near:
                    c[NEAR, s, b] += 1
                if completed:
                    c[COMPLETED, s, b] += 1
                    self.hist[s, b, lb] += 1
        elif t == "STATUS_CHECK_SENT":
            for s in segs:
                c[STATUS, s, b] += 1
        elif t == "STATUS_CHECK_RESULT":
            if "error_code" not in e:
                for s in segs:
                    c[STATUS_OK, s, b] += 1
        elif t == "LEDGER_OPENED":
            for s in segs:
                c[LEDGER_OPEN, s, b] += 1
        elif t == "LEDGER_RESOLVED":
            for s in segs:
                c[LEDGER_RES, s, b] += 1

    # -- window reads (call advance(T // 1000) first; windows end at second `end`, exclusive)
    def idx(self, end: int, w: int) -> np.ndarray:
        return np.arange(end - w, end) % self.nb

    def sum(self, counter: int, end: int, w: int) -> np.ndarray:
        return self.c[counter][:, self.idx(end, w)].sum(axis=1).astype(float)

    def hist_sum(self, end: int, w: int) -> np.ndarray:
        return self.hist[:, self.idx(end, w), :].sum(axis=1)

    def psp_series(self, end: int, w: int) -> np.ndarray:
        """Per-second mean PSP snapshot (queue, active, workers), shape (3, NP, w); NaN where no snapshot."""
        ix = self.idx(end, w)
        cnt = self.psp_snap[3][:, ix]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cnt > 0, self.psp_snap[:3][:, :, ix] / np.where(cnt > 0, cnt, 1), np.nan)

    def switch_series(self, end: int, w: int) -> np.ndarray:
        """Per-second mean switch snapshot (queue, active, cap/s, slowdown), shape (4, w)."""
        ix = self.idx(end, w)
        cnt = self.sw_snap[4][ix]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(cnt > 0, self.sw_snap[:4][:, ix] / np.where(cnt > 0, cnt, 1), np.nan)

    def quantiles(self, h: np.ndarray, qs: tuple, min_samples: int) -> list:
        cum = np.cumsum(h, axis=1)
        total = cum[:, -1]
        out = []
        for q in qs:
            k = (cum >= q * total[:, None]).argmax(axis=1)
            v = self.bin_mid[k].astype(float)
            v[total < min_samples] = np.nan
            out.append(v)
        return out
