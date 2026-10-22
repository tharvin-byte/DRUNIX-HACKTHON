"""FastAPI routes per contracts/CONTRACTS.md §1 (M2 Simulator, :8001).

    SIM_MODE=live (default) | mock      mock replays contracts/fixtures/payment_events.jsonl in a loop
    uvicorn --factory qsim.api:create_app --port 8001
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import secrets
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from qsim import contracts, jsonlog, ledger_bridge, metrics
from qsim.live import LiveRun
from qsim.sse import SseHub

MAX_BODY = 1_000_000
MOCK_STEP_S = 0.5
RUN_ID_RE = re.compile(r"^r-S[0-8]-[0-9]+-U[0-4](?:-[a-z0-9]+)?$")


def _safe_run_file(data_dir: Path, run_id: str, filename: str) -> Optional[Path]:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        return None
    runs_dir = (data_dir / "runs").resolve()
    candidate = (runs_dir / run_id / filename).resolve()
    if not candidate.is_relative_to(runs_dir):
        return None
    return candidate


def git_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or "dev"
    except (OSError, subprocess.CalledProcessError):
        return "dev"


def err(status: int, code: str, detail: str = "") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


async def body_json(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return None
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return None


class State:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.hub = SseHub()
        self.run: Optional[LiveRun] = None
        self.key = os.environ.get("QS_API_KEY") or secrets.token_urlsafe(16)
        if not os.environ.get("QS_API_KEY"):
            jsonlog.warn("QS_API_KEY not set; generated a key for this process")
        self.ledger_mode = os.environ.get("LEDGER_MODE", "model")
        self.data_dir = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
        self.version = git_version()


async def mock_replay(st: State) -> None:
    """Loop the fixture stream, re-stamping ids and sim time so consumers see a monotonic stream."""
    path = contracts.contracts_dir() / "fixtures" / "payment_events.jsonl"
    base = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    span = max(e["sim_ms"] for e in base) - min(e["sim_ms"] for e in base) + 5000
    t0 = min(e["sim_ms"] for e in base)
    loop, n = 0, 0
    while True:
        for e in base:
            n += 1
            m = copy.deepcopy(e)
            m["event_id"] = f"{m['run_id']}-{n:08d}"
            m["sim_ms"] = e["sim_ms"] - t0 + loop * span
            if contracts.accept("payment_event", m):
                st.hub.publish("payment_event", m)
            await asyncio.sleep(MOCK_STEP_S)
        loop += 1


def create_app() -> FastAPI:
    st = State(os.environ.get("SIM_MODE", "live"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(mock_replay(st)) if st.mode == "mock" else None
        jsonlog.info("m2 started", mode=st.mode, ledger_mode=st.ledger_mode)
        yield
        if task:
            task.cancel()
        if st.run:
            st.run.stop()

    app = FastAPI(title="QueueShield M2 Simulator", version="1", lifespan=lifespan)
    app.state.qs = st

    def authorised(key: Optional[str]) -> bool:
        return bool(key) and secrets.compare_digest(key, st.key)

    @app.get("/v1/health")
    def health():
        degraded = st.mode == "live" and not ledger_bridge.mode_supported(st.ledger_mode)
        return {"status": "degraded" if degraded else "ok", "module": "m2",
                "mode": "mock" if st.mode == "mock" else "live", "version": st.version}

    @app.post("/v1/scenario", status_code=202)
    async def scenario(request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request)
        if body is None or contracts.errors("scenario_command", body):
            return err(400, "SCHEMA_INVALID", "; ".join(contracts.errors("scenario_command", body))[:300]
                       if body is not None else "invalid JSON")
        cmd = body["command"]
        if st.mode == "mock":
            return {"run_id": "r-S6-1-U4"}
        if cmd == "START":
            if st.run:
                st.run.stop()
            st.run = LiveRun(st.hub, body["scenario"], body["seed"], body["universe"], body.get("speed", 1),
                             body.get("overrides"), os.environ.get("CONTROL_URL"))
            st.run.start()
            return {"run_id": st.run.run_id}
        if st.run is None:
            return err(409, "CONFLICT", "no run")
        if cmd == "PAUSE":
            st.run.pause()
        elif cmd == "RESUME":
            st.run.resume()
        elif cmd == "SPEED":
            st.run.speed = body.get("speed", 1)
        elif cmd == "RESET":
            st.run.stop()
            st.run = None
            return {"run_id": None}
        return {"run_id": st.run.run_id}

    @app.get("/v1/status")
    def status():
        r = st.run
        if r is None:
            return {"run_id": None, "scenario": None, "seed": None, "universe": None, "sim_ms": 0, "speed": 1,
                    "achieved_speed": 0.0, "state": "IDLE", "ledger_mode": st.ledger_mode}
        out = {"run_id": r.run_id, "scenario": r.scenario, "seed": r.seed, "universe": r.universe,
               "sim_ms": r.sim_ms, "speed": r.speed, "achieved_speed": r.achieved_speed, "state": r.state,
               "ledger_mode": st.ledger_mode}
        if r.error:
            out["error"] = r.error
        return out

    @app.get("/v1/stream")
    async def stream(request: Request, types: Optional[str] = None,
                     last_event_id: Optional[str] = Header(default=None)):
        wanted = None
        if types:
            # `types` filters payment event types; run_started / run_done always pass
            allowed = set(types.split(","))
            hub_stream = st.hub.stream(last_event_id)

            async def filtered():
                async for chunk in hub_stream:
                    if "event: payment_event" in chunk:
                        try:
                            data = json.loads(chunk.split("data: ", 1)[1])
                        except (IndexError, ValueError):
                            continue
                        if data.get("event_type") not in allowed:
                            continue
                    yield chunk
            return StreamingResponse(filtered(), media_type="text/event-stream")
        return StreamingResponse(st.hub.stream(last_event_id, wanted), media_type="text/event-stream")

    @app.get("/v1/timeseries")
    def timeseries(run_id: Optional[str] = None, from_ms: int = 0):
        r = st.run
        if r is not None and run_id in (None, r.run_id):
            return metrics.timeseries(r.engine, from_ms)
        if run_id:
            f = _safe_run_file(st.data_dir, run_id, "timeseries.json")
            if f is None:
                return err(400, "BAD_REQUEST", "invalid run_id")
            if f.is_file():
                return json.loads(f.read_text(encoding="utf-8"))
        return err(404, "NOT_FOUND", "unknown run")

    @app.get("/v1/results")
    def results():
        out = []
        for f in sorted((st.data_dir / "runs").glob("*/result.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({k: d[k] for k in ("run_id", "scenario", "seed", "universe", "metrics")})
        return out

    @app.get("/v1/results/{run_id}")
    def result(run_id: str):
        f = _safe_run_file(st.data_dir, run_id, "result.json")
        if f is None:
            return err(400, "BAD_REQUEST", "invalid run_id")
        if not f.is_file():
            return err(404, "NOT_FOUND", run_id)
        return json.loads(f.read_text(encoding="utf-8"))

    @app.post("/v1/arena")
    async def arena(x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        # TODO(M2, Day 4): background job over qsim.batch.run_one; until then run `python -m qsim.batch`.
        return err(503, "UNAVAILABLE", "arena jobs not implemented yet; use python -m qsim.batch")

    @app.get("/v1/arena/{job_id}")
    def arena_job(job_id: str):
        return err(404, "NOT_FOUND", job_id)

    return app
