"""API + contract tests (contracts/CONTRACTS.md §3)."""
import json
import os

from fastapi.testclient import TestClient

os.environ.setdefault("QS_API_KEY", "test-key")
os.environ["CONTROL_MODE"] = "mock"
os.environ.pop("LEDGER_URL", None)
from qctl import contracts  # noqa: E402
from qctl.api import create_app  # noqa: E402

KEY = {"X-QS-Key": os.environ["QS_API_KEY"]}


def test_mock_mode_serves_fixture_recommendation_and_decides():
    with TestClient(create_app()) as c:
        assert c.get("/v1/health").json()["module"] == "m4"
        recs = c.get("/v1/recommendations", params={"status": "PENDING"}).json()
        assert len(recs) == 1 and contracts.errors("recommendation", recs[0]) == []
        fx = json.loads((contracts.contracts_dir() / "fixtures" / "decision.json").read_text())
        fx["rec_id"] = recs[0]["rec_id"]
        assert c.post("/v1/decisions", json=fx).status_code == 401
        r = c.post("/v1/decisions", json=fx, headers=KEY)
        assert r.status_code == 200 and r.json()["status"] == "PARTIAL"
        assert r.json()["ledger"]["decision_tx"]
        assert c.post("/v1/decisions", json=fx, headers=KEY).status_code == 409
        acts = c.get("/v1/actions/pending", params={"run_id": recs[0]["run_id"]}).json()
        assert acts and all(contracts.errors("action", a) == [] for a in acts)


def test_fixtures_parse():
    for name in ("recommendation", "decision", "action", "incident"):
        doc = json.loads((contracts.contracts_dir() / "fixtures" / f"{name}.json").read_text())
        assert contracts.errors(name, doc) == [], name
