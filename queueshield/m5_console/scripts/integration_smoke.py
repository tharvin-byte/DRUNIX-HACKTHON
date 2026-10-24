"""Cross-module integration smoke (docs: m5_console/SPEC.md §6, acceptance U-7). Owned by M5.

Starts M1 (mock gateway), M2 (live), M3 (live), M4 (live, simulated operator) on localhost, runs S3/U4 with a pinned
B1 slowdown, and checks the end-to-end chain. Uses only HTTP — it imports no module code.

    ../.venv/Scripts/python m5_console/scripts/integration_smoke.py --seconds 170      (from the repo root)

Checks (spec §6): (a) M3 published ticks, (b) an incident opened, (c) a recommendation arrived, (d) the auto-approved
decision was recorded on the ledger, (e) at least one PaymentUpdated SUCCESS event — (e) needs M2's live ledger bridge
(m2_simulator ROADMAP M2-T02) and is reported as SKIPPED until then.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
KEY = "smoke-key"
PORTS = {"m1": 8004, "m2": 8001, "m3": 8002, "m4": 8003}


def start(name: str, cmd: list, cwd: str, extra: dict, logdir: Path):
    log = open(logdir / f"smoke_{name}.log", "w", encoding="utf-8")
    env = {**os.environ, "QS_API_KEY": KEY, "PYTHONUNBUFFERED": "1", **extra}
    return subprocess.Popen(cmd, cwd=ROOT / cwd, env=env, stdout=log, stderr=subprocess.STDOUT), log.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=170, help="wall seconds to let the scenario run")
    ap.add_argument("--logdir", default=str(ROOT / "data" / "smoke"))
    a = ap.parse_args()
    logdir = Path(a.logdir)
    logdir.mkdir(parents=True, exist_ok=True)
    uv = [PY, "-m", "uvicorn", "--factory"]
    procs = [
        start("m1", ["node", "src/main.ts"], "m1_ledger/gateway", {"LEDGER_MODE": "mock", "PORT": "8004"}, logdir),
        start("m2", uv + ["qsim.api:create_app", "--port", "8001"], "m2_simulator",
              {"SIM_MODE": "live", "CONTROL_URL": "http://127.0.0.1:8003", "LEDGER_MODE": "mock",
               "LEDGER_URL": "http://127.0.0.1:8004"}, logdir),
        start("m3", uv + ["qdet.api:create_app", "--port", "8002"], "m3_detection",
              {"DETECT_MODE": "live", "SIM_URL": "http://127.0.0.1:8001"}, logdir),
        start("m4", uv + ["qctl.api:create_app", "--port", "8003"], "m4_control",
              {"CONTROL_MODE": "live", "DETECT_URL": "http://127.0.0.1:8002", "LEDGER_URL": "http://127.0.0.1:8004",
               "OPERATOR_MODE": "auto", "OPERATOR_DELAY_S": "5"}, logdir),
    ]
    checks: dict = {}
    try:
        c = httpx.Client(timeout=10)
        for name, port in PORTS.items():
            for _ in range(60):
                try:
                    c.get(f"http://127.0.0.1:{port}/v1/health").raise_for_status()
                    break
                except httpx.HTTPError:
                    time.sleep(0.5)
            else:
                print(f"FAIL: {name} never became healthy")
                return 1
        time.sleep(2)
        r = c.post("http://127.0.0.1:8001/v1/scenario", headers={"X-QS-Key": KEY},
                   json={"command": "START", "scenario": "S3", "seed": 1, "universe": "U4", "speed": 4,
                         "overrides": {"scenario": {"onset": 130000, "duration": 100000, "mult": 8.0, "bank": "B1"}}})
        print("start", r.status_code, r.json())
        deadline = time.time() + a.seconds
        while time.time() < deadline:
            time.sleep(10)
            st = c.get("http://127.0.0.1:8001/v1/status").json()
            recs = c.get("http://127.0.0.1:8003/v1/recommendations").json()
            print(f"sim_ms={st['sim_ms']} recs={[(x['rec_id'], x['verdict'], x['status']) for x in recs]}")
        incidents = c.get("http://127.0.0.1:8002/v1/incidents").json()
        recs = c.get("http://127.0.0.1:8003/v1/recommendations").json()
        decided = [x for x in recs if x["status"] in ("APPROVED", "PARTIAL", "REJECTED")]
        ledger_decisions = [c.get(f"http://127.0.0.1:8004/v1/decisions/dec-{i:05d}").status_code
                            for i in range(1, len(decided) + 1)]
        payments = c.get("http://127.0.0.1:8004/v1/payments?limit=1000").json()
        checks = {
            "a_m3_ticks": c.get("http://127.0.0.1:8002/v1/state").status_code == 200,
            "b_incident_opened": len(incidents) > 0,
            "c_recommendation_arrived": len(recs) > 0,
            "d_decision_on_ledger": bool(ledger_decisions) and all(s == 200 for s in ledger_decisions),
            "e_payment_success_on_ledger": any(p["state"] == "SUCCESS" for p in payments) if payments else None,
        }
    finally:
        for p, _ in procs:
            p.terminate()
    for k, v in checks.items():
        print(f"{k}: {'PASS' if v else 'SKIPPED (M2 live ledger bridge not built)' if v is None else 'FAIL'}")
    errors = 0
    for _, path in procs:
        errors += sum(1 for line in open(path, encoding="utf-8", errors="replace")
                      if '"level":"error"' in line or "Traceback" in line)
    print("error lines in service logs:", errors, f"(logs in {logdir})")
    return 0 if all(v is not False for v in checks.values()) and errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
