"""Tests for M2-T02 (Live/Mock HTTP LedgerBridge S-11) and M2-T03 (POST /v1/arena background jobs)."""
from __future__ import annotations

import os
import time
import urllib.parse
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qsim import config, scenarios
from qsim.api import create_app
from qsim.engine import Engine
from qsim.ledger_bridge import LedgerBridge


def _make_fake_m1_app() -> FastAPI:
    app = FastAPI()
    app.state.payments = {}
    app.state.attestations = []

    @app.post("/v1/payments", status_code=201)
    async def open_unknown(req: Request):
        body = await req.json()
        tref = body["txnRef"]
        rec = {
            "docType": "payment",
            "txnRef": tref,
            "idemKeyHash": body["idemKeyHash"],
            "payerPsp": body["payerPsp"],
            "remitterBank": body["remitterBank"],
            "beneficiaryBank": body["beneficiaryBank"],
            "runId": body["runId"],
            "state": "UNKNOWN",
            "openedAt": 1700000000,
            "openedSimMs": body["simMs"],
            "attestations": [],
            "version": 1,
        }
        app.state.payments[tref] = rec
        return {"record": rec, "tx_id": "tx-open", "block_number": 1}

    @app.post("/v1/payments/{txn_ref:path}/attest")
    async def attest(txn_ref: str, req: Request):
        tref = urllib.parse.unquote(txn_ref)
        body = await req.json()
        kind = body["kind"]
        rec = app.state.payments[tref]
        rec["attestations"].append({"kind": kind, "simMs": body["simMs"]})
        app.state.attestations.append((tref, kind))
        if kind == "DEBIT" and rec["state"] == "UNKNOWN":
            rec["state"] = "DEBITED"
        elif kind == "CREDIT":
            rec["state"] = "SUCCESS"
        elif kind == "FAILURE_REMITTER":
            rec["state"] = "FAILED_NO_DEBIT"
        elif kind == "FAILURE_BENEFICIARY":
            rec["state"] = "CREDIT_FAILED"
        elif kind == "REVERSAL":
            rec["state"] = "REVERSED"
        return {"record": rec, "tx_id": f"tx-{kind}", "block_number": 2, "noop": False}

    return app


def test_s11_live_ledger_bridge_opens_attests_and_resolves_only_on_terminal_state():
    fake_m1 = _make_fake_m1_app()
    client = TestClient(fake_m1)
    cfg = config.load()
    pins = {"bank": "B1", "onset": 5_000, "duration": 20_000, "hold_frac": 0.8, "resolve_after": 5_000}
    spec = scenarios.build("S6", 1, cfg, pins)
    rid = "r-S6-1-U4"
    bridge = LedgerBridge(rid, mode="mock", http_client=client, async_worker=False)
    e = Engine(cfg, spec, 1, "U4", rid, horizon_ms=45_000, ledger_bridge=bridge)
    for t in range(1_000, 46_000, 1_000):
        e.run_until(t)
        e.poll_ledger_bridge()
    assert len(fake_m1.state.payments) > 0
    assert len(fake_m1.state.attestations) > 0
    resolved_ev = [x for x in e.events if x["event_type"] == "LEDGER_RESOLVED"]
    assert len(resolved_ev) > 0
    for ev in resolved_ev:
        tref = f"{rid}:{ev['payment_id']}"
        assert tref in fake_m1.state.payments
        assert fake_m1.state.payments[tref]["state"] in ("SUCCESS", "REVERSED", "FAILED_NO_DEBIT")


def test_m2_t03_arena_background_job_writes_valid_results(tmp_path, monkeypatch):
    monkeypatch.setenv("QS_API_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/v1/arena",
            json={"scenario": "S0", "seeds": [1], "universes": ["U0", "U2"], "horizon_ms": 15_000},
            headers={"X-QS-Key": "test-key"},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        for _ in range(50):
            st = c.get(f"/v1/arena/{job_id}").json()
            if st["state"] in ("DONE", "FAILED"):
                break
            time.sleep(0.05)
        assert st["state"] == "DONE", st
        assert st["done"] == 2 and len(st["run_ids"]) == 2
        res_list = c.get("/v1/results").json()
        assert len(res_list) == 2
