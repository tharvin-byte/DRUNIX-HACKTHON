"""Payment state tracker for pending_count, orbit_proxy and ledger_unresolved (docs/M3_DETECTION.md §3).

Built only from observable events (never ground truth). A payment is pending from a CLIENT_TIMEOUT until a
confirming STATUS_CHECK_RESULT, LEDGER_RESOLVED or PAYMENT_CLOSED; it is attributed to the segments of its latest
attempt.
"""
from __future__ import annotations

import numpy as np

from qdet import segments as S


class PaymentTracker:
    def __init__(self, orbit_ms: int) -> None:
        self.orbit_ms = orbit_ms
        self.segs: dict = {}            # payment_id -> involved segment indices of the latest attempt
        self.pending: set = set()
        self.timeout_at: dict = {}      # payment_id -> last CLIENT_TIMEOUT sim_ms (until confirmed success)
        self.ledger_open: set = set()

    def apply(self, e: dict) -> None:
        pid = e.get("payment_id")
        if pid is None:
            return
        t = e["event_type"]
        if "psp" in e and "remitter_bank" in e:
            self.segs[pid] = S.involved(S.PSP_IDX[e["psp"]], S.BANK_IDX[e["remitter_bank"]],
                                        S.BANK_IDX[e["beneficiary_bank"]])
        if t == "ATTEMPT_OUTCOME":
            if e["status"] == "CLIENT_TIMEOUT":
                self.pending.add(pid)
                self.timeout_at[pid] = e["sim_ms"]
            elif e["status"] == "SUCCESS":
                self.timeout_at.pop(pid, None)
        elif t == "STATUS_CHECK_RESULT" and e["status"] in ("CONFIRMED_SUCCESS", "CONFIRMED_FAILED"):
            self.pending.discard(pid)
            if e["status"] == "CONFIRMED_SUCCESS":
                self.timeout_at.pop(pid, None)
        elif t == "LEDGER_OPENED":
            self.ledger_open.add(pid)
        elif t == "LEDGER_RESOLVED":
            self.ledger_open.discard(pid)
            self.pending.discard(pid)
            if e.get("ledger_state") == "SUCCESS":
                self.timeout_at.pop(pid, None)
        elif t == "PAYMENT_CLOSED":
            self.pending.discard(pid)
            if e.get("close_reason") == "CONFIRMED_SUCCESS":
                self.timeout_at.pop(pid, None)
            self.segs.pop(pid, None)

    def _count(self, ids) -> np.ndarray:
        out = np.zeros(S.N)
        for pid in ids:
            for s in self.segs.get(pid, ()):
                out[s] += 1
        return out

    def pending_by_segment(self) -> np.ndarray:
        return self._count(self.pending)

    def ledger_unresolved_by_segment(self) -> np.ndarray:
        return self._count(self.ledger_open)

    def orbit_by_segment(self, now_ms: int) -> np.ndarray:
        cut = now_ms - self.orbit_ms
        for pid in [p for p, t in self.timeout_at.items() if t < cut]:
            del self.timeout_at[pid]
        return self._count(self.timeout_at)
