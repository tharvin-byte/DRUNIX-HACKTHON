"""M2 acceptance tests S-1 .. S-7, S-9 (docs/M2_SIMULATOR.md §14). Shortened horizon (300 s) for speed."""
import hashlib
import json
from collections import Counter, defaultdict

import numpy as np

from conftest import HORIZON, make, run
from qsim import config
from qsim.tape import Tape


def digest(events) -> str:
    h = hashlib.sha256()
    for e in events:
        h.update(json.dumps(e, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


def test_s1_determinism():
    a, b = run("S4", 7, "U3", horizon=120_000), run("S4", 7, "U3", horizon=120_000)
    assert digest(a.drain_events()) == digest(b.drain_events())


def test_s2_conservation(s6_runs):
    for u, e in s6_runs.items():
        closed = Counter(x["payment_id"] for x in e.events if x["event_type"] == "PAYMENT_CLOSED")
        assert len(closed) == len(e.payments), u
        assert set(closed.values()) == {1}, u
        for p in e.payments:                      # every attempt reached exactly one terminal ground-truth state
            for a in p.attempts:
                assert a.state == 3 and not a.reversal_pending, (u, p.pid, a.k)


def test_s3_common_random_numbers():
    cfg = config.default()
    tapes = [Tape(3, cfg, HORIZON) for _ in range(2)]
    for name in ("arrivals", "psp", "rem", "ben", "z_rem", "z_ben", "u_td_ben"):
        assert np.array_equal(getattr(tapes[0], name)[:1000], getattr(tapes[1], name)[:1000]), name
    firsts = [[x["sim_ms"] for x in run("S0", 3, u, horizon=30_000).events
               if x["event_type"] == "PAYMENT_INITIATED"][:1000] for u in ("U0", "U2", "U4")]
    assert firsts[0] == firsts[1] == firsts[2]


def test_s4_utilisation_and_littles_law():
    e = run("S0", 2, "U0", drain=False)
    for p in e.ground_truth_stats()["per_psp"]:
        assert 0.45 <= p["utilisation"] <= 0.65, p
        lam = p["arrival_rate"] / 1000.0
        assert abs(p["mean_queue"] - lam * p["mean_wait_ms"]) <= 0.05 * max(1.0, p["mean_queue"]) + 0.05, p


def _si1_violations(events) -> int:
    """ATTEMPT_SENT while the payment is PENDING_UNKNOWN / STATUS_CHECKING (derived from the stream only)."""
    pending, bad = defaultdict(bool), 0
    for e in events:
        pid, t = e.get("payment_id"), e["event_type"]
        if t == "ATTEMPT_OUTCOME" and e["status"] == "CLIENT_TIMEOUT":
            pending[pid] = True
        elif t == "STATUS_CHECK_RESULT" and e["status"] in ("CONFIRMED_FAILED", "CONFIRMED_SUCCESS"):
            pending[pid] = False
        elif t == "LEDGER_RESOLVED":
            pending[pid] = False
        elif t == "ATTEMPT_SENT" and pending[pid]:
            bad += 1
    return bad


def test_s6_si1_never_violated_by_npci_rule_clients(s6_runs):
    assert _si1_violations(s6_runs["U2"].events) == 0
    assert _si1_violations(run("S4", 4, "U2").events) == 0
    for u in ("U2", "U4"):
        assert s6_runs[u].stats["si1_violations_governed"] == 0
    # naive clients (U0) do violate it: that is the duplicate-prone behaviour being modelled
    assert _si1_violations(s6_runs["U0"].events) > 0


def test_s7_switch_storm_under_u0_lower_under_u4(s6_runs):
    u0, u4 = s6_runs["U0"], s6_runs["U4"]
    snaps = [x for x in u0.events if x["event_type"] == "SWITCH_SNAPSHOT"]
    assert max(x["switch_slowdown_factor"] for x in snaps) > 2.0
    assert max(x["switch_status_active"] for x in snaps) / 4 > 0.95
    assert u4.ts["switch_checks"].max() < u0.ts["switch_checks"].max()
    assert u4.ground_truth_stats()["duplicate_commits"] < u0.ground_truth_stats()["duplicate_commits"]


def test_throttle_mechanism_rejects_over_budget_retries():
    pins = {"psp": "P1", "onset": 150_000, "duration": 80_000, "worker_loss": 0.65}
    e = make("S4", 5, "U0", overrides=pins)
    e.run_until(160_000)
    e.apply_action({"action_id": "act-00001", "action_type": "THROTTLE_RETRIES", "scope": {"psp": "P1"},
                    "params": {"rate_fraction": 0.1, "retry_after_ms": [2000, 8000]}})
    e.run_until(200_000)
    later = [x for x in e.events if x["event_type"] == "ATTEMPT_OUTCOME" and x["status"] == "RETRY_LATER"]
    assert later and all(x["psp"] == "P1" and x["retry_count"] > 0 for x in later)


def test_s9_throttle_lowers_excess_retries():
    pins = {"psp": "P1", "onset": 150_000, "duration": 80_000, "worker_loss": 0.65}
    base = run("S4", 5, "U0", overrides=pins)
    acted = make("S4", 5, "U0", overrides=pins)
    acted.run_until(160_000)
    acted.apply_action({"action_id": "act-00001", "action_type": "THROTTLE_RETRIES", "scope": {"psp": "P1"},
                        "params": {"rate_fraction": 0.1, "retry_after_ms": [2000, 8000]}})
    acted.run_to_completion()

    def excess(e):
        return e.ground_truth_stats()["attempts"] - len(e.payments)
    assert excess(acted) < excess(base)


def test_ledger_model_resolves_unknowns_in_u4(s6_runs):
    e = s6_runs["U4"]
    assert e.stats["ledger_opened"] > 0 and e.stats["ledger_resolved"] > 0
    opened = {x["payment_id"] for x in e.events if x["event_type"] == "LEDGER_OPENED"}
    resolved = {x["payment_id"] for x in e.events if x["event_type"] == "LEDGER_RESOLVED"}
    assert resolved <= opened


def test_m2_t04_e_status_stop_escalates_reconcile():
    cfg = config.load(overrides={"switch": {"status_q_max": 0}})
    from qsim import scenarios
    from qsim.engine import Engine
    pins = {"bank": "B1", "onset": 10_000, "duration": 60_000, "hold_frac": 0.9, "resolve_after": 120_000}
    e = Engine(cfg, scenarios.build("S6", 1, cfg, pins), 1, "U2", horizon_ms=40_000)
    e.run_until(40_000)
    overloads = [x for x in e.events if x["event_type"] == "STATUS_CHECK_RESULT" and x.get("error_code") == "E_STATUS_OVERLOAD"]
    assert len(overloads) > 0
    pid = overloads[0]["payment_id"]
    checks_for_pid = [x for x in e.events if x["event_type"] == "STATUS_CHECK_SENT" and x["payment_id"] == pid]
    closed_for_pid = [x for x in e.events if x["event_type"] == "PAYMENT_CLOSED" and x["payment_id"] == pid]
    assert len(checks_for_pid) == 1
    assert len(closed_for_pid) == 1 and closed_for_pid[0]["close_reason"] == "ESCALATED_RECONCILE"


def test_m2_t04_slow_retries_advisory_in_u4():
    cfg = config.load(overrides={"bank": {"td_rate": [0.95, 0.95, 0.95, 0.95, 0.95]}, "client": {"naive_share_governed_universes": 0.0}})
    from qsim import scenarios
    from qsim.engine import Engine
    e_no_adv = Engine(cfg, scenarios.build("S0", 11, cfg), 11, "U4", horizon_ms=20_000)
    e_no_adv.run_until(20_000)
    e_adv = Engine(cfg, scenarios.build("S0", 11, cfg), 11, "U4", horizon_ms=20_000)
    e_adv.apply_advisory({
        "id": "adv-00001", "kind": "SLOW_RETRIES", "segmentId": "psp:P1:*",
        "params": {"retry_after_ms": [5000, 8000]}, "reason": "test",
        "evidenceHash": "sha256:" + "0" * 64, "decisionId": "dec-00001",
        "issuedSimMs": 0, "validForSec": 300,
    })
    e_adv.run_until(20_000)
    delays_base = [x["delay_ms"] for x in e_no_adv.events if x["event_type"] == "RETRY_SCHEDULED" and x["psp"] == "P1"]
    delays_adv = [x["delay_ms"] for x in e_adv.events if x["event_type"] == "RETRY_SCHEDULED" and x["psp"] == "P1"]
    assert delays_base and delays_adv
    assert min(delays_adv) >= 5000
    assert np.mean(delays_adv) > np.mean(delays_base)


def test_m2_t04_pace_payouts_token_bucket_on_s8():
    pins = {"bank": "B1", "onset": 10_000, "batch_n": 200}
    base = make("S8", 3, "U0", horizon=80_000, overrides=pins)
    base.run_until(80_000)
    paced = make("S8", 3, "U0", horizon=80_000, overrides=pins)
    paced.run_until(35_000)
    paced.apply_action({"action_id": "act-00001", "action_type": "PACE_PAYOUTS", "scope": {"bank": "B1"},
                        "params": {"max_rate_per_s": 2.0}})
    paced.run_until(80_000)
    sent_base = [x["sim_ms"] for x in base.events if x["event_type"] == "ATTEMPT_SENT" and x["kind"] == "PAYOUT" and x["attempt_no"] == 0]
    sent_paced = [x["sim_ms"] for x in paced.events if x["event_type"] == "ATTEMPT_SENT" and x["kind"] == "PAYOUT" and x["attempt_no"] == 0]
    in_window_base = sum(1 for t in sent_base if 40_000 <= t < 60_000)
    in_window_paced = sum(1 for t in sent_paced if 40_000 <= t < 60_000)
    assert in_window_base > 150
    assert in_window_paced <= 45


def test_m2_t06_u1_textbook_failover_moves_and_restores_weight():
    pins = {"psp": "P1", "onset": 15_000, "duration": 25_000, "worker_loss": 0.85}
    e = make("S4", 2, "U1", horizon=90_000, overrides=pins)
    moved_seen = False
    restored_seen = False
    for t in range(5_000, 90_000, 5_000):
        e.run_until(t)
        if e.psps[0].weight == 0.0:
            moved_seen = True
        elif moved_seen and e.psps[0].weight == 1.0:
            restored_seen = True
    assert moved_seen, "U1 textbook failover should move P1 weight to 0.0 during outage"
    assert restored_seen, "U1 textbook failover should restore P1 weight to 1.0 after recovery"


def test_m2_t06_actions_change_engine_behaviour():
    e = make("S0", 4, "U3", horizon=30_000)
    e.run_until(5_000)
    assert e.apply_action({"action_id": "act-00001", "action_type": "SHIFT_TRAFFIC", "scope": {"psp": "P1"},
                           "params": {"fraction": 0.25}}) == "APPLIED"
    assert abs(e.psps[0].weight - 0.75) < 1e-6
    assert e.apply_action({"action_id": "act-00002", "action_type": "CHECK_BUDGET", "scope": {"psp": "P1"},
                           "params": {"rate_per_s": 4.0, "burst": 8, "first_check_delay_ms": 15_000}}) == "APPLIED"
    assert e.psps[0].budget["rate_per_s"] == 4.0 and e.psps[0].budget["first_check_delay_ms"] == 15_000
    assert e.apply_action({"action_id": "act-00003", "action_type": "DEFER_CHECKS", "scope": {"bank": "B1"},
                           "params": {"budget_multiplier": 0.4, "first_check_delay_multiplier": 2.0}}) == "APPLIED"
    assert e.defer[0] == (0.4, 2.0)
    p_b1 = next(p for p in e.payments if p.profile in ("governed", "ledger_first") and (p.rem == 0 or p.ben == 0) and p.home == 0)
    assert e._first_check_delay(p_b1) == 30_000
    assert e.apply_action({"action_id": "act-00004", "action_type": "ROLLBACK", "scope": {"psp": "P1"},
                           "params": {"action_id": "act-00001"}}) == "APPLIED"
    assert abs(e.psps[0].weight - 1.0) < 1e-6
    assert e.apply_action({"action_id": "act-00005", "action_type": "ROLLBACK", "scope": {"bank": "B1"},
                           "params": {"action_id": "act-00003"}}) == "APPLIED"
    assert 0 not in e.defer


def test_m2_t06_scenarios_s1_s2_s5_s7_run_and_validate():
    from qsim import contracts
    for sc in ("S1", "S2", "S5", "S7"):
        e = run(sc, 1, "U0", horizon=30_000, drain=False)
        assert len(e.events) > 0
        for ev in e.events[::25]:
            contracts.validate("payment_event", ev)

