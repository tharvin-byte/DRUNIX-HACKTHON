"""Per-run control state machine shared by live, mock and batch (docs/M4_CONTROL.md §5-§9).

Inputs: M3 ticks (with incidents) and M1 ledger events. Outputs: recommendations (to M5), actions (to M2),
decisions and advisories (to M1). Every sim-time field uses the latest tick's clock, never wall time.
Safety invariants are enforced here and property-tested in tests/: SI-2 (blocked never approved),
SI-3 (no OPERATOR_APPROVED action without a decision), SI-5 (budget bounds), SI-9 (no advisory without decision).
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Callable, Optional

from qctl import contracts, governor, jsonlog, policy
from qctl.ledger import LedgerUnavailable


class Conflict(Exception):
    pass


class BadRequest(Exception):
    pass


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scope_of(segment_id: str) -> dict:
    _, p, b = segment_id.split(":")
    out = {}
    if p != "*":
        out["psp"] = p
    if b != "*":
        out["bank"] = b
    return out


class RunControl:
    def __init__(self, cfg, run_id: str, ledger, operator_mode: str = "human",
                 operator_delay_s: Optional[float] = None, publish: Optional[Callable[[str, dict], None]] = None) -> None:
        self.cfg, self.run_id, self.ledger = cfg, run_id, ledger
        self.operator_mode = operator_mode
        self.operator_delay_ms = int(1000 * (operator_delay_s if operator_delay_s is not None
                                             else cfg.c.operator.delay_s))
        self.publish = publish or (lambda ev, data: None)
        self.lock = threading.RLock()
        self.now_ms = 0
        self.snapshot: Optional[dict] = None
        self.incidents: dict = {}
        self.recs: dict = {}
        self.rec_of_incident: dict = {}
        self.last_key: dict = {}                 # incident_id -> (severity, verdict) of its last recommendation
        self.actions: list = []
        self.applied: dict = {}
        self.decisions: dict = {}                # rec_id -> response
        self.budgets: dict = {}
        self.ledger_pending: list = []           # (kind, body, owner) awaiting a successful write
        self.ledger_status: dict = {}            # decision/advisory id -> {"tx_id", "block_number"} or pending
        self._n = {"rec": 0, "act": 0, "adv": 0, "dec": 0}

    def _id(self, kind: str, width: int) -> str:
        self._n[kind] += 1
        return f"{kind}-{self._n[kind]:0{width}d}"

    # ------------------------------------------------------------------ inputs
    def on_tick(self, snapshot: dict) -> dict:
        """Process one M3 tick. Returns what changed (used by the batch response)."""
        with self.lock:
            self.snapshot = snapshot
            self.now_ms = snapshot["tick_sim_ms"]
            new_recs, new_actions, new_adv = [], [], []
            for inc in snapshot.get("incidents", []):
                r = self.on_incident(inc)
                if r:
                    new_recs.append(r)
            self._expire()
            new_actions += self._budgets()
            if self.operator_mode == "auto":
                for res in self._auto_operator():
                    new_actions += res["actions"]
                    new_adv += res["advisories"]
            self.retry_ledger()
            return {"recommendations": new_recs, "actions": new_actions, "advisories": new_adv}

    def on_incident(self, inc: dict) -> Optional[dict]:
        if not contracts.accept("incident", inc):
            return None
        self.incidents[inc["incident_id"]] = inc
        old_id = self.rec_of_incident.get(inc["incident_id"])
        old = self.recs.get(old_id) if old_id else None
        if inc["state"] == "CLOSED":
            if old and old["status"] == "PENDING":          # IBM bug: recs stayed approvable after close
                self._set_status(old, "EXPIRED")
            return None
        key = (inc["severity"], inc["verdict"])
        if old and old["status"] == "PENDING" and self.last_key.get(inc["incident_id"]) == key:
            return None
        if old and old["status"] == "PENDING":
            self._set_status(old, "SUPERSEDED")
        if old and old["status"] != "PENDING" and self.last_key.get(inc["incident_id"]) == key:
            return None                                      # already decided for this severity/verdict
        rec = policy.recommendation(self.cfg, self._id("rec", 4), inc, self.snapshot, self.now_ms)
        contracts.validate("recommendation", rec)
        self.recs[rec["rec_id"]] = rec
        self.rec_of_incident[inc["incident_id"]] = rec["rec_id"]
        self.last_key[inc["incident_id"]] = key
        self.publish("recommendation", rec)
        return rec

    def on_ledger_event(self, ev: dict) -> None:
        if not contracts.accept("ledger_event", ev):
            return
        p = ev["payload"]
        if ev["name"] in ("DecisionRecorded", "AdvisoryIssued") and "id" in p:
            self.ledger_status[p["id"]] = {"tx_id": ev["tx_id"], "block_number": ev["block_number"]}

    # ------------------------------------------------------------------ recommendations
    def _set_status(self, rec: dict, status: str) -> None:
        rec["status"] = status
        self.publish("recommendation", rec)

    def _expire(self) -> None:
        ttl = self.cfg.c.recommendations.expiry_sim_s * 1000
        for rec in self.recs.values():
            if rec["status"] == "PENDING" and self.now_ms - rec["created_sim_ms"] >= ttl:
                self._set_status(rec, "EXPIRED")
                self.last_key.pop(rec["incident_id"], None)        # rebuilt next tick if the incident persists

    def pending(self) -> list:
        return [r for r in self.recs.values() if r["status"] == "PENDING"]

    # ------------------------------------------------------------------ governor
    def _budgets(self) -> list:
        if self.snapshot is None:
            return []
        out = []
        for psp, b in governor.compute_budgets(self.cfg, self.snapshot).items():
            if not governor.changed(self.cfg, self.budgets.get(psp), b):
                continue
            self.budgets[psp] = b
            a = self._new_action("CHECK_BUDGET", {"psp": psp}, b, None, "POLICY_DEFAULT")
            out.append(a)
            self.publish("budget", {"psp": psp, "rate_per_s": b["rate_per_s"], "burst": b["burst"],
                                    "first_check_delay_ms": b["first_check_delay_ms"],
                                    "ledger_wait_ms": b["ledger_wait_ms"], "origin": "POLICY_DEFAULT"})
        return out

    # ------------------------------------------------------------------ decisions
    def _new_action(self, atype: str, scope: dict, params: dict, rec_id: Optional[str], origin: str) -> dict:
        a = {"action_id": self._id("act", 5), "rec_id": rec_id, "run_id": self.run_id, "action_type": atype,
             "scope": scope, "params": params, "effective_from_sim_ms": int(self.now_ms), "expires_sim_ms": None,
             "origin": origin}
        contracts.validate("action", a)
        self.actions.append(a)
        return a

    def decide(self, d: dict) -> dict:
        """POST /v1/decisions. Raises BadRequest (400) or Conflict (409)."""
        errs = contracts.errors("decision", d)
        if errs:
            raise BadRequest(errs[0])
        with self.lock:
            if d["operator"] not in self.cfg.operators:
                raise BadRequest(f"unknown operator {d['operator']}")
            rec = self.recs.get(d["rec_id"])
            if rec is None:
                raise BadRequest(f"unknown recommendation {d['rec_id']}")
            if rec["status"] != "PENDING":
                raise Conflict(f"{d['rec_id']} is {rec['status']}")
            if d["decision"] == "REJECT":
                chosen = []
            elif d["decision"] == "APPROVE_ALL":
                chosen = [a for a in rec["actions"] if a["eligible"]]
            else:
                want = set(d["actions_selected"])
                blocked = [a["action_type"] for a in rec["actions"] if a["action_type"] in want and not a["eligible"]]
                if blocked:
                    raise Conflict(f"blocked actions cannot be approved (SI-2): {blocked}")
                missing = want - {a["action_type"] for a in rec["actions"]}
                if missing:
                    raise BadRequest(f"not in the recommendation: {sorted(missing)}")
                chosen = [a for a in rec["actions"] if a["action_type"] in want]
            n_eligible = sum(1 for a in rec["actions"] if a["eligible"])
            status = "REJECTED" if not chosen else ("APPROVED" if len(chosen) == n_eligible else "PARTIAL")
            # 1. decision record first (SI-3: an OPERATOR_APPROVED action always has a decision)
            dec_id = self._id("dec", 5)
            dec_body = {"id": dec_id, "recId": rec["rec_id"], "decision": d["decision"], "operator": d["operator"],
                        "actionsApproved": [a["action_type"] for a in chosen],
                        "modelVersions": rec["model_versions"], "featuresSha256": rec["features_sha256"],
                        "decidedSimMs": int(self.now_ms)}
            contracts.validate("ledger_decision", dec_body)
            self._set_status(rec, status)
            # 2. actions for M2 (HOLD_MONITOR / ESCALATE_HUMAN have no simulator effect)
            actions = [self._new_action(a["action_type"], scope_of(a["scope_segment_id"]), a["params"],
                                        rec["rec_id"], "OPERATOR_APPROVED")
                       for a in chosen if a["action_type"] not in policy.NO_SIM_EFFECT]
            # 3-4. ledger: decision, then advisories (SI-9: each carries the decision id)
            advisories = []
            evidence = "sha256:" + canonical_sha256(rec)
            for a in rec["actions"]:
                is_chosen = a in chosen
                blocked_shift = a["action_type"] == "SHIFT_TRAFFIC" and not a["eligible"] and chosen
                if not a.get("advisory_kind") or not (is_chosen or blocked_shift):
                    continue
                adv = {"id": self._id("adv", 5), "kind": a["advisory_kind"], "segmentId": a["scope_segment_id"],
                       "params": a["params"], "reason": (a.get("blocked_by") or a["side_effect"])[:200],
                       "evidenceHash": evidence, "decisionId": dec_id, "issuedSimMs": int(self.now_ms),
                       "validForSec": (self.cfg.c.ledger.do_not_shift_valid_s if a["advisory_kind"] == "DO_NOT_SHIFT"
                                       else self.cfg.c.ledger.advisory_valid_s)}
                contracts.validate("advisory", adv)
                advisories.append(adv)
            ledger = {"decision_tx": None, "advisory_txs": [], "pending": False}
            for kind, body in [("decisions", dec_body)] + [("advisories", a) for a in advisories]:
                tx = self._ledger_write(kind, body)
                if tx is None:
                    ledger["pending"] = True
                elif kind == "decisions":
                    ledger["decision_tx"] = tx
                else:
                    ledger["advisory_txs"].append(tx)
            resp = {"rec_id": rec["rec_id"], "status": status, "action_ids": [a["action_id"] for a in actions],
                    "ledger": ledger}
            self.decisions[rec["rec_id"]] = {**resp, "decision": d, "decision_id": dec_id}
            self.publish("decision", {**resp, "decision_id": dec_id, "operator": d["operator"],
                                      "decision": d["decision"], "decided_sim_ms": int(self.now_ms)})
            return {"resp": resp, "actions": actions, "advisories": advisories}

    def _ledger_write(self, kind: str, body: dict) -> Optional[str]:
        try:
            r = self.ledger.write(kind, body)
            self.ledger_status[body["id"]] = {"tx_id": r.get("tx_id"), "block_number": r.get("block_number")}
            return r.get("tx_id")
        except LedgerUnavailable as exc:
            jsonlog.warn("ledger write failed; queued", run_id=self.run_id, id=body["id"], err=str(exc))
            self.ledger_pending.append((kind, body))
            self.ledger_status[body["id"]] = {"pending": True}
            return None

    def retry_ledger(self) -> None:
        """Retry queued writes (called every tick and by the live retry timer every pending_retry_s)."""
        queue, self.ledger_pending = self.ledger_pending, []
        for kind, body in queue:
            self._ledger_write(kind, body)

    # ------------------------------------------------------------------ simulated operator (§8)
    def _auto_operator(self) -> list:
        out = []
        for rec in list(self.pending()):
            if self.now_ms - rec["created_sim_ms"] < self.operator_delay_ms:
                continue
            if rec["confidence"] < self.cfg.c.recommendations.min_confidence_auto:
                continue                                         # waits and re-checks next tick
            res = self.decide({"rec_id": rec["rec_id"], "decision": "APPROVE_ALL", "operator": "auto_operator",
                               "actions_selected": []})
            out.append(res)
        return out

    # ------------------------------------------------------------------ action queue (§7)
    def pending_actions(self, since: Optional[str]) -> list:
        with self.lock:
            return [a for a in self.actions if since is None or a["action_id"] > since]

    def mark_applied(self, action_id: str, body: dict) -> None:
        with self.lock:
            if not any(a["action_id"] == action_id for a in self.actions):
                raise BadRequest(f"unknown action {action_id}")
            self.applied[action_id] = body
