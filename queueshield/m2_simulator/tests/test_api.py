import os

from fastapi.testclient import TestClient

os.environ.setdefault("QS_API_KEY", "test-key")
from qsim.api import create_app  # noqa: E402

KEY = {"X-QS-Key": os.environ["QS_API_KEY"]}


def test_health_auth_and_scenario_lifecycle():
    with TestClient(create_app()) as c:
        h = c.get("/v1/health").json()
        assert h["module"] == "m2" and h["status"] in ("ok", "degraded")
        body = {"command": "START", "scenario": "S0", "seed": 1, "universe": "U0"}
        assert c.post("/v1/scenario", json=body).status_code == 401
        assert c.post("/v1/scenario", json={"command": "NOPE"}, headers=KEY).status_code == 400
        r = c.post("/v1/scenario", json=body, headers=KEY)
        assert r.status_code == 202 and r.json()["run_id"] == "r-S0-1-U0-live"
        assert c.get("/v1/status").json()["state"] in ("RUNNING", "DONE")
        assert c.post("/v1/scenario", json={"command": "RESET"}, headers=KEY).status_code == 202
        assert c.get("/v1/status").json()["state"] == "IDLE"


def test_d1_generated_api_key_is_never_logged(monkeypatch, capsys):
    monkeypatch.delenv("QS_API_KEY", raising=False)
    app = create_app()
    generated_key = app.state.qs.key
    captured = capsys.readouterr().out
    assert "QS_API_KEY not set; generated a key for this process" in captured
    assert generated_key not in captured


def test_d2_run_id_validation_blocks_traversal():
    with TestClient(create_app()) as c:
        for bad_id in ("../config", "..%2F..%2Fetc%2Fpasswd", "not-a-valid-run-id", "r-S9-1-U0"):
            r1 = c.get("/v1/timeseries", params={"run_id": bad_id})
            assert r1.status_code == 400 and r1.json()["error"] == "BAD_REQUEST"
        r2 = c.get("/v1/results/not-a-valid-run-id")
        assert r2.status_code == 400 and r2.json()["error"] == "BAD_REQUEST"
        # Valid run_id format that does not exist on disk returns 404 NOT_FOUND
        r3 = c.get("/v1/results/r-S0-999-U0")
        assert r3.status_code == 404 and r3.json()["error"] == "NOT_FOUND"
        r4 = c.get("/v1/timeseries", params={"run_id": "r-S0-999-U0"})
        assert r4.status_code == 404 and r4.json()["error"] == "NOT_FOUND"


def test_m2_t06_mock_mode_serves_fixtures(monkeypatch):
    import asyncio
    import json
    import qsim.api as api_mod
    monkeypatch.setenv("SIM_MODE", "mock")
    monkeypatch.setattr(api_mod, "MOCK_STEP_S", 0.005)
    app = create_app()
    with TestClient(app) as c:
        h = c.get("/v1/health").json()
        assert h["mode"] == "mock" and h["status"] == "ok"
        r = c.post("/v1/scenario", json={"command": "START", "scenario": "S6", "seed": 1, "universe": "U4"}, headers=KEY)
        assert r.status_code == 202 and r.json()["run_id"] == "r-S6-1-U4"

        async def read_one():
            gen = app.state.qs.hub.stream(None)
            return await asyncio.wait_for(gen.__anext__(), timeout=2.0)

        chunk = asyncio.run(read_one())
        assert "event: payment_event" in chunk
        payload = json.loads(chunk.split("data: ", 1)[1])
        assert payload["schema_version"] == 1


def test_m2_t09_live_pacing_reports_achieved_speed():
    import time
    with TestClient(create_app()) as c:
        body = {"command": "START", "scenario": "S0", "seed": 1, "universe": "U0", "speed": 4}
        assert c.post("/v1/scenario", json=body, headers=KEY).status_code == 202
        time.sleep(0.35)
        st = c.get("/v1/status").json()
        assert "achieved_speed" in st and st["achieved_speed"] > 2.0
        assert st["sim_ms"] >= 800
        c.post("/v1/scenario", json={"command": "RESET"}, headers=KEY)


