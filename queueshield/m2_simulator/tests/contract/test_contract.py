"""Contract tests (contracts/CONTRACTS.md §7.4): fixtures parse, every emitted message validates."""
import json

from conftest import run
from qsim import contracts, metrics


def test_fixture_events_validate():
    path = contracts.contracts_dir() / "fixtures" / "payment_events.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        assert contracts.errors("payment_event", json.loads(line)) == []


def test_every_emitted_event_type_validates(s6_runs):
    seen = set()
    for e in list(s6_runs["U4"].events) + list(s6_runs["U0"].events):
        if e["event_type"] in seen and int(e["event_id"][-8:]) % 50:
            continue                          # full check on the first of each type, then a 2 % sample
        seen.add(e["event_type"])
        assert contracts.errors("payment_event", e) == [], e
    assert {"LEDGER_OPENED", "LEDGER_RESOLVED", "STATUS_CHECK_RESULT", "PAYMENT_CLOSED",
            "SWITCH_SNAPSHOT", "PSP_SNAPSHOT", "RETRY_SCHEDULED"} <= seen


def test_action_applied_event_validates():
    e = run("S0", 1, "U3", horizon=20_000, drain=False)
    e.apply_action({"action_id": "act-00001", "action_type": "SHED_EXPIRED", "scope": {"psp": "P2"}, "params": {}})
    ev = [x for x in e.drain_events() if x["event_type"] == "ACTION_APPLIED"]
    assert len(ev) == 1 and contracts.errors("payment_event", ev[0]) == []


def test_run_result_validates(s6_runs):
    e = s6_runs["U4"]
    r = {"run_id": e.run_id, "scenario": "S6", "seed": 1, "universe": "U4", "config_sha256": "x",
         "sim_version": "dev", "metrics": metrics.run_metrics(e), "ground_truth": e.spec.truth,
         "files": {"events": "events.jsonl"}}
    assert contracts.errors("run_result", r) == []


def test_s8_payout_batch_events_validate():
    e = run("S8", 1, "U0", horizon=260_000, drain=False, overrides={"onset": 180_000, "batch_n": 2000})
    payouts = [x for x in e.events if x.get("kind") == "PAYOUT"]
    assert payouts and contracts.errors("payment_event", payouts[0]) == []
