"""API + contract tests: health, batch lockstep endpoints, schema validation of responses."""
import json
import os

from fastapi.testclient import TestClient

os.environ.setdefault("QS_API_KEY", "test-key")
os.environ["DETECT_MODE"] = "batch"
from qdet import contracts  # noqa: E402
from qdet.api import create_app  # noqa: E402

KEY = {"X-QS-Key": os.environ["QS_API_KEY"]}


def test_health_and_batch_lockstep():
    with TestClient(create_app()) as c:
        h = c.get("/v1/health").json()
        assert h["module"] == "m3" and h["status"] in ("ok", "degraded")
        assert c.post("/v1/batch/reset", json={"run_id": "r-S6-1-U4", "mode": "batch"}).status_code == 401
        assert c.post("/v1/batch/reset", json={"run_id": "r-S6-1-U4", "mode": "batch"}, headers=KEY).status_code == 200
        ev = [json.loads(x) for x in (contracts.contracts_dir() / "fixtures" / "payment_events.jsonl")
              .read_text().splitlines()]
        req = {"run_id": "r-S6-1-U4", "universe": "U4", "tick_sim_ms": 125000, "events": ev}
        assert contracts.errors("lockstep", req, "DetectTickRequest") == []
        snap = c.post("/v1/batch/tick", json=req, headers=KEY).json()
        assert contracts.errors("segment_state", snap) == []
        assert c.get("/v1/forecaster/grid").status_code in (200, 503)
