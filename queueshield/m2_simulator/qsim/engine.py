"""Deterministic reactive discrete-event model of a small UPI-like network (docs/M2_SIMULATOR.md §2-§6, §11).

Ported core from the IBM project's qs/sim/engine.py: heapq loop on integer ms with a sequence counter for ties,
FIFO PSP queues with fresh/retry split, worker accounting with exact time integrals, server-side controls.
New for QueueShield: remitter + beneficiary legs per attempt, the switch status service whose utilisation slows
every leg (the April-2025 coupling), the S6 credit hold, universe client profiles, an in-sim ledger model (U4),
and contract-shaped events. Ground truth (debits, credits, reversals, duplicates) stays inside the engine.

Zombie work: a timed-out attempt is never cancelled; it keeps its PSP worker and may still debit and credit.
"""
from __future__ import annotations

import heapq
import math
from collections import deque
from typing import Callable, Optional

import numpy as np

from qsim import ids
from qsim.config import SimConfig
from qsim.scenarios import ScenarioSpec
from qsim.tape import Tape

(ARRIVAL, PSP_DONE, REM_DONE, BEN_DONE, CLIENT_TIMEOUT, RETRY_DUE, CHECK_DUE, STATUS_DONE, STATUS_TIMEOUT,
 STATUS_OVERLOAD, REVERSAL_DONE, HOLD_RELEASE, LEDGER_OPEN, LEDGER_RESOLVE, SNAPSHOT, TICK, REJECT_DONE,
 SHED_DONE) = range(18)

# attempt states (ground truth)
QUEUED, SERVICE, HELD, ENDED = 0, 1, 2, 3

UNIVERSE_PROFILES = {"U0": "naive", "U1": "naive", "U2": "npci_rule", "U3": "governed", "U4": "ledger_first"}
BUDGETED = ("governed", "ledger_first")


def lognorm(mean: float, cv: float) -> tuple:
    s2 = math.log(1.0 + cv * cv)
    return math.log(mean) - s2 / 2.0, math.sqrt(s2)


class Attempt:
    __slots__ = ("pay", "k", "psp", "t_send", "t_enq", "seq", "state", "waiting", "timed_out", "fresh",
                 "debited", "credited", "failed", "reversal_pending", "reversed")

    def __init__(self, pay: "Payment", k: int, psp: int, t: int) -> None:
        self.pay, self.k, self.psp, self.t_send, self.t_enq = pay, k, psp, t, t
        self.seq = 0
        self.state = QUEUED
        self.waiting = True          # the client is still waiting for this attempt's answer
        self.timed_out = False
        self.fresh = k == 0
        self.debited = self.credited = self.failed = self.reversal_pending = self.reversed = False


class Payment:
    __slots__ = ("n", "pid", "i", "home", "rem", "ben", "kind", "profile", "ik", "attempts", "closed",
                 "pending", "checks", "check_sched", "unknown_ms", "ledger_open", "ledger_resolving", "cap",
                 "t0", "resolved_ms")

    def __init__(self, n: int, i: int, home: int, rem: int, ben: int, kind: str, profile: str, cap: int,
                 t0: int) -> None:
        self.n, self.pid, self.i = n, ids.payment_id(n), i
        self.home, self.rem, self.ben, self.kind, self.profile, self.cap, self.t0 = home, rem, ben, kind, profile, cap, t0
        self.ik: Optional[str] = None
        self.attempts: list[Attempt] = []
        self.closed = False
        self.pending = False         # PENDING_UNKNOWN or STATUS_CHECKING (SI-1 gate)
        self.checks = 0
        self.check_sched = 0
        self.unknown_ms: Optional[int] = None
        self.ledger_open = False
        self.ledger_resolving = False
        self.resolved_ms: Optional[int] = None

    def truth(self) -> str:
        """SUCCESS if any attempt credited; IN_FLIGHT if any attempt may still commit or reverse; else FAILED."""
        if any(a.credited for a in self.attempts):
            return "SUCCESS"
        if any(a.state != ENDED or a.reversal_pending for a in self.attempts):
            return "IN_FLIGHT"
        return "FAILED"


class Psp:
    def __init__(self, idx: int, name: str, workers: int, q_max: int, budget) -> None:
        self.idx, self.name, self.workers, self.q_max = idx, name, workers, q_max
        self.busy = 0
        self.q_fresh: deque = deque()
        self.q_retry: deque = deque()
        self.weight = 1.0
        self.shed = False
        self.fresh_first = False
        self.throttle: Optional[dict] = None         # {"rate","tokens","last","retry_after":(lo,hi)}
        self.budget = dict(rate_per_s=budget.rate_per_s, burst=budget.burst,
                           first_check_delay_ms=budget.first_check_delay_ms, max_checks=budget.max_checks,
                           horizon_ms=budget.horizon_ms, ledger_wait_ms=budget.ledger_wait_ms)
        self.tokens = float(budget.burst)
        self.tok_last = 0
        self.check_wait: deque = deque()            # payments due for a budgeted check, oldest first
        self.last_t = 0
        self.q_int = 0.0
        self.busy_int = 0.0
        self.entered = 0
        self.wait_sum = 0.0

    def qlen(self) -> int:
        return len(self.q_fresh) + len(self.q_retry)

    def touch(self, now: int) -> None:
        dt = now - self.last_t
        if dt > 0:
            self.q_int += self.qlen() * dt
            self.busy_int += self.busy * dt
            self.last_t = now


class Engine:
    def __init__(self, cfg: SimConfig, spec: ScenarioSpec, seed: int, universe: str, run_id: Optional[str] = None,
                 horizon_ms: Optional[int] = None, emit: Optional[Callable[[dict], None]] = None) -> None:
        self.cfg, self.spec, self.seed, self.universe = cfg, spec, int(seed), universe
        self.run_id = run_id or ids.run_id(spec.scenario, seed, universe)
        self.horizon = int(horizon_ms if horizon_ms is not None else cfg.run.length_ms)
        self.tape = Tape(seed, cfg, self.horizon, spec.rate_fn, spec.rate_max_mult, spec.extra_payments)
        self.psp_names, self.bank_names = cfg.topology.psps, cfg.topology.banks
        self.psps = [
            Psp(
                i,
                n,
                int(cfg.psp.workers[i] if isinstance(cfg.psp.workers, (tuple, list)) else cfg.psp.workers),
                cfg.psp.q_max,
                cfg.default_budget,
            )
            for i, n in enumerate(self.psp_names)
        ]
        self.mods = list(spec.modifiers)
        self.profile_main = UNIVERSE_PROFILES[universe]
        self.naive_share = cfg.client.naive_share_governed_universes if universe in ("U3", "U4") else 0.0
        self.eids = ids.EventIds(self.run_id)
        self._emit_cb = emit
        self.events: list = []
        self.now = 0
        self._heap: list = []
        self._seq = 0
        self._qseq = 0
        self._n_pay = 0
        self.payments: list[Payment] = []
        self._mu_psp = lognorm(cfg.psp.t_psp_mean_ms, cfg.psp.t_psp_cv)
        self._mu_leg = lognorm(cfg.bank.leg_mean_ms, cfg.bank.leg_cv)
        self._mu_status = lognorm(cfg.switch.status_mean_ms, cfg.switch.status_cv)
        lm = cfg.ledger_model
        self._mu_ledger = (math.log(lm.submit_p50_ms), max(1e-6, math.log(lm.submit_p95_ms / lm.submit_p50_ms) / 1.645))
        # switch status service
        self.st_queue: deque = deque()
        self.st_busy = 0
        self.st_busy_int = 0.0
        self.st_last_t = 0
        self.st_last_snap_int = 0.0
        self.slowdown = 1.0
        self.status_debt: list = [deque() for _ in self.bank_names]     # served-check times per beneficiary bank
        # deferral (DEFER_CHECKS) per bank: (budget_multiplier, first_check_delay_multiplier)
        self.defer: dict = {}
        self.pace: dict = {}
        self.advisories: dict = {}
        self.actions_applied: dict = {}
        # observed counters for throttles / failover (1 s buckets, 10 s ring)
        nb = 10
        self._fresh_psp = np.zeros((len(self.psps), nb))
        self._fresh_bank = np.zeros((len(self.bank_names), nb))
        self._out_psp = np.zeros((len(self.psps), nb))
        self._succ_psp = np.zeros((len(self.psps), nb))
        self._failover = {"bad": [0] * len(self.psps), "good": [0] * len(self.psps), "moved": [False] * len(self.psps)}
        # time series (1 s buckets) and ground-truth stats
        n_sec = (self.horizon + cfg.run.drain_ms) // 1000 + 2
        self.ts = {"goodput": np.zeros(n_sec), "queue": np.zeros((len(self.psps), n_sec)),
                   "switch_checks": np.zeros(n_sec), "unknown_open": np.zeros(n_sec)}
        self.stats = {"attempts": 0, "switch_checks": 0, "unknowns": 0, "escalated": 0, "abandoned": 0,
                      "ledger_opened": 0, "ledger_resolved": 0, "si1_violations_governed": 0}
        self._unknown_open = 0
        self._handlers = [self._h_arrival, self._h_psp_done, self._h_rem_done, self._h_ben_done,
                          self._h_client_timeout, self._h_retry_due, self._h_check_due, self._h_status_done,
                          self._h_status_timeout, self._h_status_overload, self._h_reversal_done,
                          self._h_hold_release, self._h_ledger_open, self._h_ledger_resolve, self._h_snapshot,
                          self._h_tick, self._h_reject_done, self._h_shed_done]
        if self.tape.n:
            self._push(int(self.tape.arrivals[0]), ARRIVAL, 0)
        self._push(0, SNAPSHOT, None)
        self._push(cfg.run.tick_ms, TICK, None)

    # ------------------------------------------------------------------ plumbing
    def _push(self, t: int, kind: int, obj) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (int(t), self._seq, kind, obj))

    def run_until(self, t_end: int) -> None:
        h, hs = self._heap, self._handlers
        while h and h[0][0] <= t_end:
            t, _, kind, obj = heapq.heappop(h)
            self.now = t
            hs[kind](obj)
        self.now = max(self.now, int(t_end))

    def run_to_completion(self) -> None:
        """Run the horizon, then drain (no new arrivals or snapshots) until every payment is closed."""
        self.run_until(self.horizon + self.cfg.run.drain_ms)

    def drain_events(self) -> list:
        ev, self.events = self.events, []
        return ev

    def _ev(self, etype: str, **f) -> dict:
        e = {"schema_version": 1, "event_id": self.eids.next(), "run_id": self.run_id, "universe": self.universe,
             "event_type": etype, "sim_ms": int(self.now)}
        e.update(f)
        self.events.append(e)
        if self._emit_cb is not None:
            self._emit_cb(e)
        return e

    def _pay_fields(self, p: Payment, psp: Optional[int] = None) -> dict:
        return {"payment_id": p.pid, "psp": self.psp_names[p.home if psp is None else psp],
                "remitter_bank": self.bank_names[p.rem], "beneficiary_bank": self.bank_names[p.ben]}

    def _att_fields(self, a: Attempt) -> dict:
        p = a.pay
        f = self._pay_fields(p, a.psp)
        f.update(attempt_id=ids.attempt_id(p.pid, a.k), attempt_no=a.k, is_retry=a.k > 0, retry_count=a.k)
        if p.ik:
            f["idempotency_key"] = p.ik
        return f

    # ------------------------------------------------------------------ multipliers
    def _mult(self, kind: str, t: int, psp: Optional[str] = None, bank: Optional[str] = None) -> float:
        m = 1.0
        for mod in self.mods:
            if mod.kind == kind and mod.active(t) and mod.psp in (None, psp) and mod.bank in (None, bank):
                m *= mod.value(t)
        return m

    def _eff_workers(self, g: Psp) -> int:
        return max(1, int(round(g.workers * self._mult("capacity", self.now, psp=g.name))))

    def _hold(self, bank: str):
        for mod in self.mods:
            if mod.kind == "credit_hold" and mod.active(self.now) and mod.bank == bank:
                return mod
        return None

    def _leg_ms(self, a: Attempt, bank_idx: int, z: float) -> int:
        bank = self.bank_names[bank_idx]
        psp = self.psp_names[a.psp]
        t = math.exp(self._mu_leg[0] + self._mu_leg[1] * z)
        t *= self._mult("bank_latency", self.now, bank=bank) * self._mult("route_latency", self.now, psp=psp, bank=bank)
        t *= self.slowdown
        dq = self.status_debt[bank_idx]
        while dq and dq[0] < self.now - 1000:
            dq.popleft()
        t += len(dq) * self.cfg.switch.status_bank_cost_ms
        return max(1, round(t))

    # ------------------------------------------------------------------ arrivals and attempts
    def _profile_for(self, i: int) -> str:
        if self.naive_share and self.tape.u_profile[i] < self.naive_share:
            return "naive"
        return self.profile_main

    def _h_arrival(self, i: int) -> None:
        tp = self.tape
        prof = self._profile_for(i)
        spec = self.cfg.profiles[prof]
        self._n_pay += 1
        p = Payment(self._n_pay, i, int(tp.psp[i]), int(tp.rem[i]), int(tp.ben[i]), str(tp.kind[i]), prof,
                    min(spec["attempt_cap"], tp.max_attempts), self.now)
        if spec.get("idempotency"):
            p.ik = ids.idempotency_key(p.n)
        self.payments.append(p)
        if i + 1 < tp.n:
            self._push(int(tp.arrivals[i + 1]), ARRIVAL, i + 1)
        self._ev("PAYMENT_INITIATED", kind=p.kind, **self._pay_fields(p))
        self._pace_or_send(p)

    def _pace_or_send(self, p: Payment) -> None:
        bank = self.bank_names[p.ben]
        pb = self.pace.get(bank) if p.kind == "PAYOUT" else None
        if pb is not None and self.now < self.horizon:
            pb["tokens"] = min(pb["burst"], pb["tokens"] + pb["rate"] * (self.now - pb["last"]) / 1000.0)
            pb["last"] = self.now
            if pb["tokens"] >= 1.0:
                pb["tokens"] -= 1.0
                self._send(p, 0)
            else:
                wait_ms = max(1, int(math.ceil((1.0 - pb["tokens"]) * 1000.0 / pb["rate"])))
                pb["tokens"] -= 1.0
                t_send = min(self.horizon + self.cfg.run.drain_ms // 2, self.now + wait_ms)
                self._push(t_send, RETRY_DUE, (p, 0, False))
            return
        self._send(p, 0)

    def apply_advisory(self, adv: dict) -> None:
        if isinstance(adv, dict) and "id" in adv:
            self.advisories[adv["id"]] = dict(adv)

    def revoke_advisory(self, adv_id: str) -> None:
        if adv_id in self.advisories:
            self.advisories[adv_id]["revoked"] = True

    def _active_slow_retries_advisory(self, p: Payment) -> Optional[dict]:
        psp_name = self.psp_names[p.home]
        rem_name, ben_name = self.bank_names[p.rem], self.bank_names[p.ben]
        for adv in self.advisories.values():
            if adv.get("kind") != "SLOW_RETRIES" or adv.get("revoked"):
                continue
            issued = int(adv.get("issuedSimMs", 0))
            valid_ms = int(adv.get("validForSec", 300)) * 1000
            if valid_ms > 0 and self.now > issued + valid_ms:
                continue
            seg = str(adv.get("segmentId", "*:*:*"))
            parts = seg.split(":")
            if len(parts) == 3:
                _, p_seg, b_seg = parts
                if p_seg not in ("*", psp_name):
                    continue
                if b_seg not in ("*", rem_name, ben_name):
                    continue
            return adv
        return None

    def _route(self, p: Payment, k: int) -> int:
        w = [g.weight for g in self.psps]
        if self.tape.u_route[p.i, k] < w[p.home]:
            return p.home
        others = [j for j in range(len(self.psps)) if j != p.home]
        shares = np.array([self.cfg.topology.psp_shares[j] * w[j] for j in others])
        if shares.sum() <= 0:
            return p.home
        u = (self.tape.u_route[p.i, k] - w[p.home]) / max(1e-9, 1.0 - w[p.home])
        c = np.cumsum(shares / shares.sum())
        return others[int(min(len(others) - 1, np.searchsorted(c, u, side="right")))]

    def _send(self, p: Payment, k: int) -> None:
        if p.pending and p.profile != "naive":
            self.stats["si1_violations_governed"] += 1       # must stay 0 (SI-1, test S-6)
            return
        gi = self._route(p, k)
        a = Attempt(p, k, gi, self.now)
        p.attempts.append(a)
        self.stats["attempts"] += 1
        g = self.psps[gi]
        sec = (self.now // 1000) % 10
        if k == 0:
            self._fresh_psp[gi, sec] += 1
            self._fresh_bank[p.rem, sec] += 1
            if p.ben != p.rem:
                self._fresh_bank[p.ben, sec] += 1
        self._ev("ATTEMPT_SENT", kind=p.kind, **self._att_fields(a))
        if k > 0 and g.throttle is not None and not self._take_retry_token(g):
            a.state, a.waiting = ENDED, False
            self._push(self.now + 1, REJECT_DONE, (a, "RETRY_LATER", "E_RETRY_LATER"))
            return
        if g.qlen() >= g.q_max:
            a.state, a.waiting = ENDED, False
            self._push(self.now + self.cfg.psp.reject_ms, REJECT_DONE, (a, "REJECTED_OVERLOAD", "E_OVERLOAD"))
            return
        g.touch(self.now)
        self._qseq += 1
        a.seq, a.t_enq = self._qseq, self.now
        (g.q_fresh if a.fresh else g.q_retry).append(a)
        g.entered += 1
        self._push(self.now + self.cfg.client.timeout_ms, CLIENT_TIMEOUT, a)
        self._try_start(g)

    def _take_retry_token(self, g: Psp) -> bool:
        th = g.throttle
        th["tokens"] = min(th["burst"], th["tokens"] + th["rate"] * (self.now - th["last"]) / 1000.0)
        th["last"] = self.now
        if th["tokens"] >= 1.0:
            th["tokens"] -= 1.0
            return True
        return False

    def _pop(self, g: Psp) -> Optional[Attempt]:
        qf, qr = g.q_fresh, g.q_retry
        if not qf and not qr:
            return None
        if g.fresh_first:
            if qr and (not qf or self.now - qr[0].t_enq > self.cfg.psp.starvation_guard_ms):
                return qr.popleft()
            return qf.popleft()
        if qf and qr:
            return qf.popleft() if qf[0].seq < qr[0].seq else qr.popleft()
        return qf.popleft() if qf else qr.popleft()

    def _try_start(self, g: Psp) -> None:
        cap = self._eff_workers(g)
        while g.busy < cap:
            a = self._pop(g)
            if a is None:
                return
            g.touch(self.now)
            g.wait_sum += self.now - a.t_enq
            if g.shed and a.timed_out:
                a.state = ENDED          # dropped at dequeue: a definitive non-commit
                g.busy += 1
                self._push(self.now + self.cfg.psp.shed_cost_ms, SHED_DONE, a)
                continue
            g.busy += 1
            a.state = SERVICE
            p = a.pay
            if p.ik and any(x.credited for x in p.attempts):
                # deduplicated retry: the PSP recognises the key and reports the original success
                self._push(self.now + 1, BEN_DONE, (a, "DEDUP"))
                continue
            z = self.tape.z_psp[p.i, a.k]
            t = math.exp(self._mu_psp[0] + self._mu_psp[1] * z) * self._mult("psp_service", self.now, psp=g.name)
            self._push(self.now + max(1, round(t * self.slowdown)), PSP_DONE, a)

    def _release(self, g: Psp) -> None:
        g.touch(self.now)
        g.busy -= 1
        self._try_start(g)

    def _h_shed_done(self, a: Attempt) -> None:
        self._release(self.psps[a.psp])
        self._truth_changed(a.pay)

    def _h_psp_done(self, a: Attempt) -> None:
        self._push(self.now + self._leg_ms(a, a.pay.rem, self.tape.z_rem[a.pay.i, a.k]), REM_DONE, a)

    def _h_rem_done(self, a: Attempt) -> None:
        p, tp, bc = a.pay, self.tape, self.cfg.bank
        if tp.u_bd[p.i, a.k] < bc.bd_rate:
            self._end(a, "DECLINED", "E_DECLINED")
            return
        if tp.u_td_rem[p.i, a.k] < bc.td_rate[p.rem]:
            a.failed = True
            self._end(a, "TECH_FAILED", "E_TD_REMITTER")
            return
        a.debited = True
        self._push(self.now + self._leg_ms(a, p.ben, tp.z_ben[p.i, a.k]), BEN_DONE, (a, None))

    def _h_ben_done(self, obj) -> None:
        a, flag = obj
        p, tp = a.pay, self.tape
        if flag == "DEDUP":
            self._end(a, "SUCCESS", None)
            return
        hold = self._hold(self.bank_names[p.ben])
        if hold is not None and tp.u_hold[p.i, a.k] < hold.v0:
            a.state = HELD                         # credit held at the beneficiary bank (S6 black hole)
            self._release(self.psps[a.psp])
            self._push(max(self.now, hold.resolve_ms), HOLD_RELEASE, a)
            return
        if tp.u_td_ben[p.i, a.k] < self.cfg.bank.td_rate[p.ben]:
            self._credit_failed(a)
            self._end(a, "TECH_FAILED", "E_TD_BENEFICIARY")
            return
        a.credited = True
        self._end(a, "SUCCESS", None)

    def _credit_failed(self, a: Attempt) -> None:
        a.failed = True
        a.reversal_pending = True
        self._push(self.now + self.cfg.bank.reversal_delay_ms, REVERSAL_DONE, a)

    def _h_hold_release(self, a: Attempt) -> None:
        p = a.pay
        a.state = ENDED
        prob = self.spec.params.get("resolve_credit_prob", 1.0)
        if self.tape.u_hold_outcome[p.i, a.k] < prob:
            a.credited = True
        else:
            self._credit_failed(a)
        self._truth_changed(p)

    def _h_reversal_done(self, a: Attempt) -> None:
        a.reversal_pending = False
        a.reversed = True
        self._truth_changed(a.pay)

    def _end(self, a: Attempt, status: str, err: Optional[str]) -> None:
        """Server-side completion: free the worker, then answer the client if it is still waiting."""
        a.state = ENDED
        g = self.psps[a.psp]
        sec = (self.now // 1000) % 10
        self._out_psp[a.psp, sec] += 1
        if status == "SUCCESS":
            self._succ_psp[a.psp, sec] += 1
        self._release(g)
        p = a.pay
        self._truth_changed(p)
        if not a.waiting or p.closed:
            return
        a.waiting = False
        f = dict(status=status, response_time_ms=self.now - a.t_send, client_timeout_ms=self.cfg.client.timeout_ms)
        if err:
            f["error_code"] = err
        self._ev("ATTEMPT_OUTCOME", kind=p.kind, **self._att_fields(a), **f)
        if status == "SUCCESS":
            self._close(p, "CONFIRMED_SUCCESS")
        elif status == "DECLINED":
            self._close(p, "DECLINED")
        elif not p.pending:                         # a naive retry failing while polling: the polls decide
            self._retry_or_close(p, a.k)

    def _h_reject_done(self, obj) -> None:
        a, status, err = obj
        p = a.pay
        sec = (self.now // 1000) % 10
        self._out_psp[a.psp, sec] += 1
        if p.closed:
            return
        self._ev("ATTEMPT_OUTCOME", kind=p.kind, **self._att_fields(a), status=status, error_code=err,
                 response_time_ms=self.now - a.t_send, client_timeout_ms=self.cfg.client.timeout_ms)
        retry_after = None
        g = self.psps[a.psp]
        if status == "RETRY_LATER" and g.throttle is not None:
            retry_after = g.throttle["retry_after"]
        if not p.pending:
            self._retry_or_close(p, a.k, retry_after)

    def _h_client_timeout(self, a: Attempt) -> None:
        p = a.pay
        if not a.waiting or p.closed:
            return
        a.waiting = False
        a.timed_out = True
        self._ev("ATTEMPT_OUTCOME", kind=p.kind, **self._att_fields(a), status="CLIENT_TIMEOUT",
                 error_code="E_CLIENT_TIMEOUT", response_time_ms=self.cfg.client.timeout_ms,
                 client_timeout_ms=self.cfg.client.timeout_ms)
        if p.pending:
            return
        p.pending = True
        self._unknown_open += 1
        if p.unknown_ms is None:
            p.unknown_ms = self.now
            self.stats["unknowns"] += 1
        spec = self.cfg.profiles[p.profile]
        if p.profile == "naive":
            self._push(self.now + spec["check_every_ms"], CHECK_DUE, p)
            k = a.k
            if k + 1 < p.cap and self.tape.u_retry[p.i, k] < spec["retry_on_timeout_prob"]:
                lo, hi = spec["retry_on_timeout_delay_ms"]
                d = int(lo + self.tape.u_delay[p.i, k] * (hi - lo))
                self._ev("RETRY_SCHEDULED", **self._att_next(p, k + 1), delay_ms=d)
                self._push(self.now + d, RETRY_DUE, (p, k + 1, True))
            return
        delay = self._first_check_delay(p)
        if p.profile == "ledger_first":
            self._push(self.now + self._ledger_latency(p, 0), LEDGER_OPEN, p)
            delay = self.psps[p.home].budget["ledger_wait_ms"]
        self._push(self.now + delay, CHECK_DUE, p)

    def _first_check_delay(self, p: Payment) -> int:
        if p.profile in BUDGETED:
            d = self.psps[p.home].budget["first_check_delay_ms"]
            mult = max(self.defer.get(p.rem, (1.0, 1.0))[1], self.defer.get(p.ben, (1.0, 1.0))[1])
            return int(d * mult)
        return self.cfg.profiles[p.profile]["check_schedule_ms"][0]

    def _att_next(self, p: Payment, k: int) -> dict:
        f = self._pay_fields(p)
        f.update(attempt_id=ids.attempt_id(p.pid, k), attempt_no=k, is_retry=True, retry_count=k)
        if p.ik:
            f["idempotency_key"] = p.ik
        return f

    def _retry_or_close(self, p: Payment, k: int, retry_after=None) -> None:
        if p.closed:
            return
        spec = self.cfg.profiles[p.profile]
        if k + 1 >= p.cap:
            self._close(p, "CONFIRMED_FAILED_FINAL")
            return
        u = self.tape.u_delay[p.i, k]
        if p.profile == "naive":
            lo, hi = spec["retry_on_failure_delay_ms"]
            d = int(lo + u * (hi - lo))
        else:
            d = int(u * min(spec["retry_backoff_cap_ms"], spec["retry_backoff_base_ms"] * 2 ** k))   # full jitter
        if retry_after is not None and self.tape.u_honour[p.i, k] < self.cfg.profiles["retry_after_honour_frac"]:
            lo, hi = retry_after
            d = max(d, int(lo + self.tape.u_delay[p.i, (k + 1) % self.tape.max_attempts] * (hi - lo)))
        if p.profile == "ledger_first":
            adv = self._active_slow_retries_advisory(p)
            if adv is not None:
                prm = adv.get("params", {})
                ra = prm.get("retry_after_ms", (2000, 8000))
                lo, hi = int(ra[0]), int(ra[1])
                d = max(d, int(lo + self.tape.u_delay[p.i, (k + 1) % self.tape.max_attempts] * (hi - lo)))
                if "backoff_multiplier" in prm:
                    d = int(d * float(prm["backoff_multiplier"]))
        self._ev("RETRY_SCHEDULED", **self._att_next(p, k + 1), delay_ms=d)
        self._push(self.now + d, RETRY_DUE, (p, k + 1, False))

    def _h_retry_due(self, obj) -> None:
        p, k, during_unknown = obj
        if p.closed:
            return
        self._send(p, k)

    def _close(self, p: Payment, reason: str) -> None:
        if p.closed:
            return
        p.closed = True
        if p.pending:
            self._unknown_open -= 1
            p.pending = False
        p.resolved_ms = self.now
        if reason == "CONFIRMED_SUCCESS" and self.now - p.t0 <= self.cfg.run.goodput_deadline_ms:
            sec = self.now // 1000
            if sec < len(self.ts["goodput"]):
                self.ts["goodput"][sec] += 1
        if reason == "ESCALATED_RECONCILE":
            self.stats["escalated"] += 1
        elif reason == "ABANDONED":
            self.stats["abandoned"] += 1
        self._ev("PAYMENT_CLOSED", kind=p.kind, close_reason=reason, **self._pay_fields(p))

    # ------------------------------------------------------------------ status checks (switch)
    def _h_check_due(self, p: Payment) -> None:
        if p.closed or not p.pending:
            return
        if p.profile in BUDGETED:
            self.psps[p.home].check_wait.append(p)
            self._release_checks(self.psps[p.home])
        else:
            self._send_check(p)

    def _release_checks(self, g: Psp) -> None:
        b = g.budget
        g.tokens = min(b["burst"], g.tokens + b["rate_per_s"] * (self.now - g.tok_last) / 1000.0)
        g.tok_last = self.now
        while g.check_wait:
            p = g.check_wait[0]
            if p.closed or not p.pending:
                g.check_wait.popleft()
                continue
            mult = min(self.defer.get(p.rem, (1.0, 1.0))[0], self.defer.get(p.ben, (1.0, 1.0))[0])
            cost = 1.0 / max(mult, 1e-6)
            if g.tokens < cost:
                return
            g.tokens -= cost
            g.check_wait.popleft()
            self._send_check(p)

    def _send_check(self, p: Payment) -> None:
        p.checks += 1
        self.stats["switch_checks"] += 1
        sec = self.now // 1000
        if sec < len(self.ts["switch_checks"]):
            self.ts["switch_checks"][sec] += 1
        no = p.checks
        self._ev("STATUS_CHECK_SENT", check_no=no, **self._pay_fields(p))
        sw = self.cfg.switch
        chk = {"p": p, "no": no, "t": self.now, "done": False}
        if len(self.st_queue) >= sw.status_q_max:
            self._push(self.now + sw.overload_reply_ms, STATUS_OVERLOAD, chk)
            return
        self.st_queue.append(chk)
        self._push(self.now + sw.status_timeout_ms, STATUS_TIMEOUT, chk)
        self._st_try_start()

    def _st_touch(self) -> None:
        dt = self.now - self.st_last_t
        if dt > 0:
            self.st_busy_int += self.st_busy * dt
            self.st_last_t = self.now

    def _st_try_start(self) -> None:
        while self.st_busy < self.cfg.switch.status_workers and self.st_queue:
            chk = self.st_queue.popleft()
            self._st_touch()
            self.st_busy += 1
            p = chk["p"]
            z = self.tape.z_status[p.i, min(chk["no"] - 1, self.tape.z_status.shape[1] - 1)]
            t = math.exp(self._mu_status[0] + self._mu_status[1] * z)
            self._push(self.now + max(1, round(t)), STATUS_DONE, chk)

    def _h_status_done(self, chk: dict) -> None:
        self._st_touch()
        self.st_busy -= 1
        p = chk["p"]
        self.status_debt[p.ben].append(self.now)
        self._st_try_start()
        if chk["done"]:
            return                                      # answer arrived after the status timeout (zombie check)
        chk["done"] = True
        tr = p.truth()
        res = {"SUCCESS": "CONFIRMED_SUCCESS", "FAILED": "CONFIRMED_FAILED"}.get(tr, "UNKNOWN")
        self._status_result(chk, res, None)

    def _h_status_timeout(self, chk: dict) -> None:
        if chk["done"]:
            return
        chk["done"] = True
        self._status_result(chk, "UNKNOWN", "E_STATUS_TIMEOUT")

    def _h_status_overload(self, chk: dict) -> None:
        chk["done"] = True
        self._status_result(chk, "UNKNOWN", "E_STATUS_OVERLOAD")

    def _status_result(self, chk: dict, res: str, err: Optional[str]) -> None:
        p = chk["p"]
        f = dict(check_no=chk["no"], status=res, response_time_ms=self.now - chk["t"])
        if err:
            f["error_code"] = err
        self._ev("STATUS_CHECK_RESULT", **f, **self._pay_fields(p))
        if p.closed or not p.pending:
            return
        if res == "CONFIRMED_SUCCESS":
            self._close(p, "CONFIRMED_SUCCESS")
            return
        if res == "CONFIRMED_FAILED":
            self._unknown_open -= 1
            p.pending = False
            self._retry_or_close(p, p.attempts[-1].k)
            return
        spec = self.cfg.profiles[p.profile]
        if p.profile == "naive":
            if p.checks >= spec["max_checks"]:
                self._close(p, "ABANDONED")
            else:
                self._push(self.now + spec["check_every_ms"], CHECK_DUE, p)
            return
        if err and err in spec.get("stop_codes", ()):
            self._close(p, "ESCALATED_RECONCILE")
            return
        sched = spec["check_schedule_ms"]
        max_checks = self.psps[p.home].budget["max_checks"] if p.profile in BUDGETED else len(sched)
        horizon = self.psps[p.home].budget["horizon_ms"] if p.profile in BUDGETED else spec["horizon_ms"]
        if p.checks >= max_checks or self.now - (p.unknown_ms or self.now) >= horizon:
            self._close(p, "ESCALATED_RECONCILE")
            return
        gap = sched[min(p.checks, len(sched) - 1)]
        self._push(self.now + gap, CHECK_DUE, p)

    # ------------------------------------------------------------------ ledger model (U4, LEDGER_MODE=model)
    def _ledger_latency(self, p: Payment, j: int) -> int:
        z = self.tape.z_ledger[p.i, j % self.tape.z_ledger.shape[1]]
        submit = math.exp(self._mu_ledger[0] + self._mu_ledger[1] * z)
        return max(1, round(submit + self.cfg.ledger_model.event_lag_p50_ms))

    def _h_ledger_open(self, p: Payment) -> None:
        if p.ledger_open:
            return
        p.ledger_open = True
        self.stats["ledger_opened"] += 1
        self._ev("LEDGER_OPENED", ledger_state="UNKNOWN", **self._pay_fields(p))
        self._truth_changed(p)

    def _truth_changed(self, p: Payment) -> None:
        """Banks attest legs of unknown payments; schedule the pushed resolution once the truth is terminal."""
        if not p.ledger_open or p.ledger_resolving or p.closed:
            return
        if p.truth() == "IN_FLIGHT":
            return
        p.ledger_resolving = True
        self._push(self.now + self._ledger_latency(p, 1), LEDGER_RESOLVE, p)

    def _h_ledger_resolve(self, p: Payment) -> None:
        tr = p.truth()
        state = "SUCCESS" if tr == "SUCCESS" else ("REVERSED" if any(a.reversed for a in p.attempts) else "FAILED_NO_DEBIT")
        self.stats["ledger_resolved"] += 1
        self._ev("LEDGER_RESOLVED", ledger_state=state, **self._pay_fields(p))
        if p.closed or not p.pending:
            return
        if state == "SUCCESS":
            self._close(p, "CONFIRMED_SUCCESS")
        else:
            self._unknown_open -= 1
            p.pending = False
            self._retry_or_close(p, p.attempts[-1].k)

    # ------------------------------------------------------------------ snapshots, ticks, actions
    def _h_snapshot(self, _obj) -> None:
        sw = self.cfg.switch
        self._st_touch()
        dt = self.cfg.run.snapshot_ms
        u = (self.st_busy_int - self.st_last_snap_int) / (sw.status_workers * dt)
        self.st_last_snap_int = self.st_busy_int
        self.slowdown = 1.0 + sw.slowdown_alpha * max(0.0, u - sw.slowdown_u0) / (1.0 - sw.slowdown_u0)
        sec = self.now // 1000
        for g in self.psps:
            g.touch(self.now)
            if sec < self.ts["queue"].shape[1]:
                self.ts["queue"][g.idx, sec] = g.qlen()
            self._ev("PSP_SNAPSHOT", psp=g.name, queue_depth=g.qlen(), active_workers=g.busy,
                     workers=self._eff_workers(g))
            self._release_checks(g)
            self._try_start(g)                    # capacity may have come back
        self._ev("SWITCH_SNAPSHOT", switch_status_queue=len(self.st_queue), switch_status_active=self.st_busy,
                 switch_status_capacity_per_s=round(sw.status_workers * 1000.0 / sw.status_mean_ms, 3),
                 switch_slowdown_factor=round(self.slowdown, 4))
        if sec < len(self.ts["unknown_open"]):
            self.ts["unknown_open"][sec] = self._unknown_open
        nxt = (sec + 1) % 10
        for arr in (self._fresh_psp, self._fresh_bank, self._out_psp, self._succ_psp):
            arr[:, nxt] = 0
        if self.now + dt <= self.horizon + self.cfg.run.drain_ms:     # keep budgets refilling while draining
            self._push(self.now + dt, SNAPSHOT, None)

    def _h_tick(self, _obj) -> None:
        if self.universe == "U1":
            self._textbook_failover()
        if self.now + self.cfg.run.tick_ms <= self.horizon:
            self._push(self.now + self.cfg.run.tick_ms, TICK, None)

    def _textbook_failover(self) -> None:
        """U1: if a PSP's 10 s success ratio < 0.90 for 2 ticks move its weight to the others; restore > 0.97 x3."""
        fo = self._failover
        for g in self.psps:
            out, ok = self._out_psp[g.idx].sum(), self._succ_psp[g.idx].sum()
            ratio = ok / out if out > 0 else 1.0
            if not fo["moved"][g.idx]:
                fo["bad"][g.idx] = fo["bad"][g.idx] + 1 if ratio < 0.90 else 0
                if fo["bad"][g.idx] >= 2:
                    g.weight, fo["moved"][g.idx], fo["good"][g.idx] = 0.0, True, 0
            else:
                fo["good"][g.idx] = fo["good"][g.idx] + 1 if ratio > 0.97 else 0
                if fo["good"][g.idx] >= 3:
                    g.weight, fo["moved"][g.idx], fo["bad"][g.idx] = 1.0, False, 0

    def fresh_rate(self, psp: Optional[str] = None, bank: Optional[str] = None) -> float:
        if psp is not None:
            return float(self._fresh_psp[self.psp_names.index(psp)].sum()) / 10.0
        if bank is not None:
            return float(self._fresh_bank[self.bank_names.index(bank)].sum()) / 10.0
        return float(self._fresh_psp.sum()) / 10.0

    def apply_action(self, action: dict, rollback: bool = False) -> str:
        """Apply an `action.schema.json` record now (docs/M2_SIMULATOR.md §6). Returns APPLIED or REJECTED."""
        t = action["action_type"]
        scope, prm = action.get("scope", {}), action.get("params", {})
        targets = [g for g in self.psps if scope.get("psp") in (None, g.name)]
        result = "APPLIED"
        if t == "ROLLBACK":
            orig = self.actions_applied.get(prm.get("action_id"))
            if orig is None:
                result = "REJECTED"
            else:
                self.apply_action(orig, rollback=True)
        elif t == "THROTTLE_RETRIES":
            for g in targets:
                if rollback:
                    g.throttle = None
                else:
                    rate = max(0.1, float(prm.get("rate_fraction", 0.1)) *
                               self.fresh_rate(psp=g.name if "psp" in scope else None, bank=scope.get("bank")))
                    ra = prm.get("retry_after_ms", [2000, 8000])
                    g.throttle = {"rate": rate, "burst": max(1.0, 2 * rate), "tokens": max(1.0, 2 * rate),
                                  "last": self.now, "retry_after": tuple(ra)}
        elif t == "SHED_EXPIRED":
            for g in targets:
                g.shed = not rollback
        elif t == "PRIORITIZE_FRESH":
            for g in targets:
                g.fresh_first = not rollback
        elif t == "SHIFT_TRAFFIC":
            for g in targets:
                g.weight = 1.0 if rollback else max(0.05, g.weight - min(0.25, float(prm.get("fraction", 0.25))))
        elif t == "CHECK_BUDGET":
            for g in targets:
                if not rollback:
                    g.budget.update({k: prm[k] for k in g.budget if k in prm})
        elif t == "DEFER_CHECKS":
            banks = [self.bank_names.index(scope["bank"])] if "bank" in scope else range(len(self.bank_names))
            for b in banks:
                if rollback:
                    self.defer.pop(b, None)
                else:
                    self.defer[b] = (float(prm.get("budget_multiplier", 0.5)),
                                     float(prm.get("first_check_delay_multiplier", 1.5)))
        elif t == "PACE_PAYOUTS":
            if "bank" in scope:
                if rollback:
                    self.pace.pop(scope["bank"], None)
                else:
                    rate = max(0.1, float(prm.get("max_rate_per_s", 5.0)))
                    self.pace[scope["bank"]] = {"rate": rate, "burst": max(1.0, rate), "tokens": 1.0, "last": self.now}
        elif t in ("HOLD_MONITOR", "ESCALATE_HUMAN"):
            pass
        else:
            result = "REJECTED"
        if not rollback and result == "APPLIED" and t != "ROLLBACK":
            self.actions_applied[action["action_id"]] = action
        if not rollback:
            self._ev("ACTION_APPLIED", action_id=action["action_id"], action_type=t, params=prm)
            for g in self.psps:
                self._try_start(g)
        return result

    # ------------------------------------------------------------------ ground truth (evaluator only)
    def ground_truth_stats(self) -> dict:
        for g in self.psps:
            g.touch(self.now)
        T = max(1, self.now)
        dup = sum(max(0, sum(1 for a in p.attempts if a.credited) - 1) for p in self.payments)
        return {
            "payments": len(self.payments), "attempts": self.stats["attempts"], "duplicate_commits": dup,
            "closed": sum(1 for p in self.payments if p.closed), **self.stats,
            "per_psp": [{"psp": g.name, "utilisation": g.busy_int / (g.workers * T), "mean_queue": g.q_int / T,
                         "arrival_rate": g.entered / (T / 1000.0),
                         "mean_wait_ms": g.wait_sum / max(1, g.entered)} for g in self.psps],
        }
