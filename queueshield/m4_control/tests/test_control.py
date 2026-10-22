"""M4 acceptance tests (docs/M4_CONTROL.md §11)."""
import numpy as np
import pytest

from conftest import BANKS, PSPS, incident, snapshot
from qctl import contracts, governor, policy
from qctl.config import default as cfg_default
from qctl.controller import Conflict, RunControl
from qctl.ledger import LedgerUnavailable, ModelLedger

CFG = cfg_default()
VERDICTS = ["PSP_SIDE", "BANK_SIDE", "ROUTE_SPECIFIC", "SWITCH_STATUS_OVERLOAD", "MULTI_FAULT", "PLATFORM_WIDE",
            "INSUFFICIENT_EVIDENCE"]


def types(actions):
    return [a["action_type"] for a in actions]


# ---------------------------------------------------------------- C-1: one test per rule row
@pytest.mark.parametrize("inc,snap_kw,rule,expected", [
    (incident(), {"global_state": "DEGRADED_MONITORING"}, "R0", ["HOLD_MONITOR", "ESCALATE_HUMAN"]),
    (incident("switch:*:*", "SWITCH_STATUS_OVERLOAD", "WARNING"), {"verdict": "SWITCH_STATUS_OVERLOAD"}, "R1",
     ["DEFER_CHECKS", "THROTTLE_RETRIES", "HOLD_MONITOR"]),
    (incident("psp:P2:*", "PSP_SIDE"), {"verdict": "PSP_SIDE", "primary": "psp:P2:*"}, "R2",
     ["SHED_EXPIRED", "THROTTLE_RETRIES", "DEFER_CHECKS", "PRIORITIZE_FRESH", "SHIFT_TRAFFIC"]),
    (incident(), {}, "R3", ["THROTTLE_RETRIES", "DEFER_CHECKS", "SHED_EXPIRED", "PRIORITIZE_FRESH", "SHIFT_TRAFFIC"]),
    (incident(severity="WARNING"), {}, "R4", ["DEFER_CHECKS", "THROTTLE_RETRIES", "HOLD_MONITOR"]),
    (incident("route:P1:B3", "ROUTE_SPECIFIC"), {"verdict": "ROUTE_SPECIFIC", "primary": "route:P1:B3"}, "R5",
     ["THROTTLE_RETRIES", "DEFER_CHECKS", "SHIFT_TRAFFIC"]),
    (incident("platform:*:*", "PLATFORM_WIDE"), {"verdict": "PLATFORM_WIDE", "primary": None}, "R6",
     ["THROTTLE_RETRIES", "DEFER_CHECKS", "ESCALATE_HUMAN"]),
])
def test_c1_rule_table(inc, snap_kw, rule, expected):
    snap = snapshot(**snap_kw)
    rid, _, acts = policy.build_actions(CFG, inc, snap)
    assert rid == rule and types(acts) == expected


def test_c1_r7_surge_annotation():
    inc = incident("psp:P1:*", "INSUFFICIENT_EVIDENCE", "WARNING")
    rid, _, acts = policy.build_actions(CFG, inc, snapshot(surge=("psp:P1:*",)))
    # R4 (WARNING) precedes R7 in the spec's order; R7 applies to surge-annotated CRITICAL-free states
    assert rid in ("R4", "R7")
    inc = incident("psp:P1:*", "INSUFFICIENT_EVIDENCE", "CRITICAL")
    rid, note, acts = policy.build_actions(CFG, inc, snapshot(surge=("psp:P1:*",), verdict="INSUFFICIENT_EVIDENCE"))
    assert rid == "R7" and types(acts) == ["HOLD_MONITOR"] and "surge" in note


# ---------------------------------------------------------------- C-2: safety invariants, 5 000 random states
def test_c2_safety_invariants_property():
    rng = np.random.default_rng(2)
    allowed_types = {"THROTTLE_RETRIES", "SHED_EXPIRED", "PRIORITIZE_FRESH", "SHIFT_TRAFFIC", "CHECK_BUDGET",
                     "DEFER_CHECKS", "PACE_PAYOUTS", "HOLD_MONITOR", "ESCALATE_HUMAN", "ROLLBACK"}
    for _ in range(5000):
        v = VERDICTS[rng.integers(len(VERDICTS))]
        sev = ["WARNING", "CRITICAL"][rng.integers(2)]
        seg = rng.choice(["platform:*:*", "switch:*:*"] + [f"psp:{p}:*" for p in PSPS] + [f"bank:*:{b}" for b in BANKS]
                         + [f"route:{p}:{b}" for p in PSPS for b in BANKS])
        gstate = ["MONITORING", "WARNING", "CRITICAL", "DEGRADED_MONITORING"][rng.integers(4)]
        states = {f"psp:{p}:*": ["MONITORING", "WARNING"][rng.integers(2)] for p in PSPS}
        snap = snapshot(verdict=v, global_state=gstate, states=states, load=float(rng.uniform(0.2, 0.95)),
                        status_rate=float(rng.uniform(0, 200)))
        _, _, acts = policy.build_actions(CFG, incident(str(seg), v, sev), snap)
        assert set(types(acts)) <= allowed_types                              # SI-1: nothing creates attempts
        for a in acts:
            if a["action_type"] == "SHIFT_TRAFFIC" and a["eligible"]:         # SI-2
                assert v not in policy.SHIFT_FORBIDDEN
            if a["action_type"] == "SHIFT_TRAFFIC" and v in policy.SHIFT_FORBIDDEN:
                assert not a["eligible"]
        if gstate == "DEGRADED_MONITORING":                                   # SI-4
            assert set(types(acts)) <= {"HOLD_MONITOR", "ESCALATE_HUMAN"}
        b = governor.compute_budgets(CFG, snap)                               # SI-5
        cap = CFG.c.governor.default_capacity_per_s
        for p, x in b.items():
            assert CFG.c.governor.r_min <= x["rate_per_s"] <= max(CFG.c.governor.r_min, CFG.c.governor.r_max_frac * cap)


# ---------------------------------------------------------------- C-3
def test_c3_bank_side_blocks_shift_and_maps_to_do_not_shift():
    _, _, acts = policy.build_actions(CFG, incident(), snapshot())
    shift = next(a for a in acts if a["action_type"] == "SHIFT_TRAFFIC")
    assert not shift["eligible"] and "shared bank B3" in shift["blocked_by"]
    assert shift["advisory_kind"] == "DO_NOT_SHIFT"


# ---------------------------------------------------------------- C-4 / C-6: decision flow, schemas, 409
def _run(ledger=None, mode="human", delay=None):
    r = RunControl(CFG, "r-S3-1-U4", ledger or ModelLedger(), mode, delay)
    return r


def test_c4_decision_flow_writes_decision_and_advisories():
    led = ModelLedger()
    r = _run(led)
    r.on_tick(snapshot(incidents=[incident()]))
    rec = r.pending()[0]
    res = r.decide({"rec_id": rec["rec_id"], "decision": "APPROVE_SELECTED", "operator": "saran",
                    "actions_selected": ["THROTTLE_RETRIES", "DEFER_CHECKS"]})
    assert res["resp"]["status"] == "PARTIAL" and len(res["resp"]["action_ids"]) == 2
    names = [e["name"] for e in led.drain()]
    assert names[0] == "DecisionRecorded"
    kinds = [a["kind"] for a in res["advisories"]]
    assert kinds == ["SLOW_RETRIES", "DEFER_CHECKS", "DO_NOT_SHIFT"]       # blocked shift -> DO_NOT_SHIFT
    for a in res["advisories"]:
        assert a["decisionId"] == r.decisions[rec["rec_id"]]["decision_id"]   # SI-9
    for a in res["actions"]:
        assert a["origin"] == "OPERATOR_APPROVED" and a["rec_id"] == rec["rec_id"]   # SI-3
        assert contracts.errors("action", a) == []
    r.mark_applied(res["actions"][0]["action_id"], {"sim_ms": 260000, "result": "APPLIED", "detail": ""})


def test_c6_double_decision_conflicts_and_blocked_cannot_be_approved():
    r = _run()
    r.on_tick(snapshot(incidents=[incident()]))
    rec = r.pending()[0]
    assert contracts.errors("recommendation", rec) == []
    with pytest.raises(Conflict):
        r.decide({"rec_id": rec["rec_id"], "decision": "APPROVE_SELECTED", "operator": "saran",
                  "actions_selected": ["SHIFT_TRAFFIC"]})
    r.decide({"rec_id": rec["rec_id"], "decision": "REJECT", "operator": "saran", "actions_selected": []})
    with pytest.raises(Conflict):
        r.decide({"rec_id": rec["rec_id"], "decision": "APPROVE_ALL", "operator": "saran", "actions_selected": []})


def test_one_pending_recommendation_per_incident_and_expiry_on_close():
    r = _run()
    r.on_tick(snapshot(incidents=[incident(severity="WARNING")]))
    r.on_tick(snapshot(t=265_000, incidents=[incident(severity="CRITICAL")]))
    assert len(r.pending()) == 1 and [x["status"] for x in r.recs.values()] == ["SUPERSEDED", "PENDING"]
    r.on_tick(snapshot(t=270_000, incidents=[incident(state="CLOSED")]))
    assert r.pending() == []


# ---------------------------------------------------------------- C-5: ledger outage
class FlakyLedger(ModelLedger):
    def __init__(self, fail_times):
        super().__init__()
        self.fail = fail_times

    def write(self, kind, body):
        if self.fail > 0:
            self.fail -= 1
            raise LedgerUnavailable("down")
        return super().write(kind, body)


def test_c5_ledger_outage_does_not_block_actions():
    led = FlakyLedger(fail_times=100)
    r = _run(led)
    r.on_tick(snapshot(incidents=[incident()]))
    res = r.decide({"rec_id": r.pending()[0]["rec_id"], "decision": "APPROVE_ALL", "operator": "saran",
                    "actions_selected": []})
    assert res["actions"] and res["resp"]["ledger"]["pending"] is True
    led.fail = 0
    r.on_tick(snapshot(t=270_000))
    assert r.ledger_pending == [] and {e["name"] for e in led.drain()} == {"DecisionRecorded", "AdvisoryIssued"}


# ---------------------------------------------------------------- C-7: budget formula
def test_c7_budget_bounds_and_monotonic():
    g = CFG.c.governor
    full = governor.compute_budgets(CFG, snapshot(status_rate=1000.0))
    assert all(x["rate_per_s"] == g.r_min for x in full.values())
    rates = [governor.compute_budgets(CFG, snapshot(status_rate=u))["P1"]["rate_per_s"] for u in range(0, 80, 5)]
    assert all(a >= b for a, b in zip(rates, rates[1:]))
    b = governor.compute_budgets(CFG, snapshot(status_rate=0.0))["P1"]
    assert b["burst"] == int(np.ceil(2 * b["rate_per_s"]))


# ---------------------------------------------------------------- C-8: simulated operator
def test_c8_simulated_operator_delay_and_never_blocked():
    r = _run(mode="auto", delay=20)
    r.on_tick(snapshot(t=260_000, incidents=[incident()]))
    assert r.pending()
    r.on_tick(snapshot(t=275_000))
    assert r.pending()                                         # 15 s < 20 s delay
    out = r.on_tick(snapshot(t=280_000))
    assert not r.pending() and out["actions"]
    approved = {a["action_type"] for a in out["actions"] if a["origin"] == "OPERATOR_APPROVED"}
    assert "SHIFT_TRAFFIC" not in approved
    low = _run(mode="auto", delay=0)
    low.on_tick(snapshot(incidents=[incident(confidence=0.4)]))
    low.on_tick(snapshot(t=300_000))
    assert low.pending()                                       # confidence < 0.6 waits
