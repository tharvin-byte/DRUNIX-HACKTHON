"""Synthetic, contract-valid event streams so M3 tests never need M2 running (AGENTS.md rule 6)."""
import numpy as np

from qdet import segments as S

RUN = "r-S0-1-U0"


class Stream:
    def __init__(self, seed: int = 1) -> None:
        self.rng = np.random.default_rng(seed)
        self.n = 0
        self.pay = 0
        self.events: list = []

    def _ev(self, t: int, etype: str, **f) -> dict:
        self.n += 1
        e = {"schema_version": 1, "event_id": f"{RUN}-{self.n:08d}", "run_id": RUN, "universe": "U0",
             "event_type": etype, "sim_ms": int(t), **f}
        self.events.append(e)
        return e

    def attempt(self, t: int, psp: str, rem: str, ben: str, status: str = "SUCCESS", rt: int = 300,
                retry: int = 0) -> None:
        self.pay += 1
        pid = f"p-{self.pay:07d}"
        base = dict(payment_id=pid, attempt_id=f"{pid}-a{retry}", attempt_no=retry, is_retry=retry > 0,
                    retry_count=retry, psp=psp, remitter_bank=rem, beneficiary_bank=ben)
        self._ev(t, "ATTEMPT_SENT", **base)
        rt = 3000 if status == "CLIENT_TIMEOUT" else rt
        self._ev(t + rt, "ATTEMPT_OUTCOME", status=status, response_time_ms=rt, client_timeout_ms=3000, **base)

    def snapshots(self, t: int, queue: int = 5, active: int = 20, sw_queue: int = 0, sw_active: int = 1) -> None:
        for p in S.PSPS:
            self._ev(t, "PSP_SNAPSHOT", psp=p, queue_depth=queue, active_workers=active, workers=40)
        self._ev(t, "SWITCH_SNAPSHOT", switch_status_queue=sw_queue, switch_status_active=sw_active,
                 switch_status_capacity_per_s=80.0, switch_slowdown_factor=1.0)

    def traffic(self, t0: int, t1: int, rate_per_s: float, bad=None) -> "Stream":
        """Uniform traffic over all routes; `bad(t, psp, rem, ben) -> status or None` injects faults."""
        for sec in range(t0 // 1000, t1 // 1000):
            self.snapshots(sec * 1000)
            k = self.rng.poisson(rate_per_s)
            for _ in range(k):
                t = sec * 1000 + int(self.rng.integers(0, 1000))
                p = S.PSPS[int(self.rng.integers(S.NP))]
                r, b = (S.BANKS[int(self.rng.integers(S.NB))] for _ in range(2))
                st = bad(t, p, r, b) if bad else None
                self.attempt(t, p, r, b, st or "SUCCESS", int(self.rng.integers(150, 450)))
        return self

    def sorted(self) -> list:
        return sorted(self.events, key=lambda e: (e["sim_ms"], e["event_id"]))


def drive(pipe, events, t_end: int, tick: int = 5000) -> list:
    """Feed events tick by tick (lockstep style) and return the snapshots."""
    snaps, i, t = [], 0, tick
    while t <= t_end:
        j = i
        while j < len(events) and events[j]["sim_ms"] < t:
            j += 1
        pipe.ingest(events[i:j])
        i = j
        snaps.append(pipe.tick(t))
        t += tick
    return snaps
