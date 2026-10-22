"""FastAPI routes per contracts/CONTRACTS.md §2 (M3 Detection, :8002).

    DETECT_MODE=live (default): subscribe to SIM_URL/v1/stream, tick on each 5 000 ms event-time boundary
    DETECT_MODE=mock          : loop contracts/fixtures/payment_events.jsonl through a pipeline and publish ticks
    uvicorn --factory qdet.api:create_app --port 8002
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from qdet import contracts, jsonlog
from qdet.config import default as default_cfg
from qdet.forecast.runtime import load_grid
from qdet.pipeline import Pipeline
from qdet.sse import SseHub

MAX_BODY = 5_000_000
MOCK_TICK_WALL_S = 1.0


def git_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or "dev"
    except (OSError, subprocess.CalledProcessError):
        return "dev"


def err(status: int, code: str, detail: str = "") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


class State:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.cfg = default_cfg()
        self.hub = SseHub()
        self.pipe: Optional[Pipeline] = None
        self.latest: Optional[dict] = None
        self.batch: dict = {}                      # run_id -> Pipeline (batch lockstep)
        self.lock = threading.Lock()
        self.key = os.environ.get("QS_API_KEY") or secrets.token_urlsafe(16)
        self.version = git_version()
        self.stream_ok = mode == "mock"
        self.stop = threading.Event()

    def publish(self, snap: dict) -> None:
        if not contracts.accept("segment_state", snap):
            jsonlog.error("dropped invalid outgoing tick", run_id=snap.get("run_id"))
            return
        self.latest = snap
        self.hub.publish("tick", snap)
        for inc in snap.get("incidents", []):
            self.hub.publish("incident", inc)


def live_loop(st: State, sim_url: str) -> None:
    """Subscribe to M2 with Last-Event-ID resume and exponential backoff (docs/01_SYSTEM.md §9)."""
    from httpx_sse import connect_sse
    last_id, backoff, next_tick = None, 0.5, None
    while not st.stop.is_set():
        try:
            headers = {"Last-Event-ID": last_id} if last_id else {}
            with httpx.Client(timeout=httpx.Timeout(10.0, read=30.0)) as c, \
                    connect_sse(c, "GET", f"{sim_url.rstrip('/')}/v1/stream", headers=headers) as es:
                st.stream_ok, backoff = True, 0.5
                for sse in es.iter_sse():
                    if st.stop.is_set():
                        return
                    last_id = sse.id or last_id
                    if sse.event == "run_started":
                        rid = json.loads(sse.data)["run_id"]
                        with st.lock:
                            st.pipe = Pipeline(rid, rid.split("-")[3], st.cfg)
                            next_tick = st.cfg.tick_ms
                        continue
                    if sse.event != "payment_event":
                        continue
                    e = json.loads(sse.data)
                    with st.lock:
                        if st.pipe is None or st.pipe.run_id != e["run_id"]:
                            st.pipe = Pipeline(e["run_id"], e["universe"], st.cfg)
                            next_tick = (e["sim_ms"] // st.cfg.tick_ms + 1) * st.cfg.tick_ms
                        st.pipe.ingest([e])
                        while st.pipe.ready_to_tick(next_tick):
                            st.publish(st.pipe.tick(next_tick))
                            next_tick += st.cfg.tick_ms
        except (httpx.HTTPError, OSError) as exc:
            st.stream_ok = False
            jsonlog.warn("sim stream dropped", err=type(exc).__name__)
        time.sleep(backoff)
        backoff = min(8.0, backoff * 2)


async def mock_loop(st: State) -> None:
    path = contracts.contracts_dir() / "fixtures" / "payment_events.jsonl"
    base = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    t0 = min(e["sim_ms"] for e in base)
    st.pipe = Pipeline(base[0]["run_id"], base[0]["universe"], st.cfg)
    n, t = 0, st.cfg.tick_ms
    while True:
        batch = []
        for e in base:
            n += 1
            m = copy.deepcopy(e)
            m["event_id"] = f"{m['run_id']}-{n:08d}"
            m["sim_ms"] = t - st.cfg.tick_ms + (e["sim_ms"] - t0) % st.cfg.tick_ms
            batch.append(m)
        st.pipe.ingest(batch)
        st.publish(st.pipe.tick(t))
        t += st.cfg.tick_ms
        await asyncio.sleep(MOCK_TICK_WALL_S)


def create_app() -> FastAPI:
    st = State(os.environ.get("DETECT_MODE", "live"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = None
        if st.mode == "mock":
            task = asyncio.create_task(mock_loop(st))
        elif os.environ.get("SIM_URL"):
            threading.Thread(target=live_loop, args=(st, os.environ["SIM_URL"]), daemon=True).start()
        jsonlog.info("m3 started", mode=st.mode)
        yield
        st.stop.set()
        if task:
            task.cancel()

    app = FastAPI(title="QueueShield M3 Detection", version="1", lifespan=lifespan)
    app.state.qs = st

    def authorised(key: Optional[str]) -> bool:
        return bool(key) and secrets.compare_digest(key, st.key)

    async def body_json(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return None
        try:
            return json.loads(raw or b"null")
        except ValueError:
            return None

    @app.get("/v1/health")
    def health():
        ok = st.stream_ok or st.mode == "batch"
        return {"status": "ok" if ok else "degraded", "module": "m3", "mode": st.mode, "version": st.version,
                "rejected_messages_total": contracts.REJECTED.total}

    @app.get("/v1/stream")
    async def stream(last_event_id: Optional[str] = Header(default=None)):
        return StreamingResponse(st.hub.stream(last_event_id), media_type="text/event-stream")

    @app.get("/v1/state")
    def state():
        return st.latest if st.latest is not None else err(404, "NOT_FOUND", "no tick yet")

    @app.get("/v1/incidents")
    def incidents(state: Optional[str] = None):
        return st.pipe.incidents(state) if st.pipe else []

    @app.get("/v1/forecaster/grid")
    def grid():
        g = load_grid(st.cfg)
        return g.to_dict() if g else err(503, "UNAVAILABLE", "no trained grid in MODEL_DIR (run scripts/train_forecaster.py)")

    @app.post("/v1/batch/reset")
    async def batch_reset(request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request)
        if body is None or contracts.errors("lockstep", body, "ResetRequest"):
            return err(400, "SCHEMA_INVALID", "ResetRequest")
        rid = body["run_id"]
        st.batch[rid] = Pipeline(rid, rid.split("-")[3], st.cfg, validate=False)
        return {"run_id": rid}

    @app.post("/v1/batch/tick")
    async def batch_tick(request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request)
        if body is None or not isinstance(body, dict) or "run_id" not in body:
            return err(400, "SCHEMA_INVALID", "DetectTickRequest")
        p = st.batch.get(body["run_id"])
        if p is None:
            return err(404, "NOT_FOUND", "reset the run first")
        p.ingest(body.get("events", []))
        snap = p.tick(int(body["tick_sim_ms"]))
        contracts.validate("segment_state", snap)
        return snap

    return app
