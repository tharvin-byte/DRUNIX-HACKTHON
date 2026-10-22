"""FastAPI routes per contracts/CONTRACTS.md §3 (M4 Control, :8003).

    CONTROL_MODE=live (default): subscribe to DETECT_URL/v1/stream (tick, incident) and LEDGER_URL/v1/stream
    CONTROL_MODE=mock          : serve a recommendation built from contracts/fixtures/incident.json
    LEDGER_URL unset           : decisions/advisories go to the in-process ModelLedger (no Drunix, no M1 mock)
    OPERATOR_MODE=human|auto, OPERATOR_DELAY_S
    uvicorn --factory qctl.api:create_app --port 8003
"""
from __future__ import annotations

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

from qctl import contracts, jsonlog
from qctl.config import default as default_cfg
from qctl.controller import BadRequest, Conflict, RunControl
from qctl.ledger import HttpLedger, ModelLedger
from qctl.sse import SseHub

MAX_BODY = 5_000_000


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
        self.key = os.environ.get("QS_API_KEY") or secrets.token_urlsafe(16)
        self.version = git_version()
        self.operator_mode = os.environ.get("OPERATOR_MODE", "human")
        delay = os.environ.get("OPERATOR_DELAY_S")
        self.operator_delay = float(delay) if delay else None
        self.ledger_url = os.environ.get("LEDGER_URL")
        self.runs: dict = {}                 # run_id -> RunControl (live/mock: usually one; batch: many)
        self.current: Optional[str] = None
        self.inputs_ok = {"detect": mode != "live", "ledger": True}
        self.stop = threading.Event()

    def ledger(self):
        return HttpLedger(self.ledger_url, self.cfg) if self.ledger_url else ModelLedger()

    def run(self, run_id: str, operator_mode: Optional[str] = None, delay: Optional[float] = None) -> RunControl:
        if run_id not in self.runs:
            self.runs[run_id] = RunControl(self.cfg, run_id, self.ledger(), operator_mode or self.operator_mode,
                                           delay if delay is not None else self.operator_delay,
                                           publish=self.hub.publish)
        self.current = run_id
        return self.runs[run_id]


def _sse_loop(st: State, url: str, name: str, handle) -> None:
    from httpx_sse import connect_sse
    last_id, backoff = None, 0.5
    while not st.stop.is_set():
        try:
            headers = {"Last-Event-ID": last_id} if last_id else {}
            with httpx.Client(timeout=httpx.Timeout(10.0, read=30.0)) as c, \
                    connect_sse(c, "GET", f"{url.rstrip('/')}/v1/stream", headers=headers) as es:
                st.inputs_ok[name], backoff = True, 0.5
                for sse in es.iter_sse():
                    if st.stop.is_set():
                        return
                    last_id = sse.id or last_id
                    if sse.data:
                        handle(sse.event, json.loads(sse.data))
        except (httpx.HTTPError, OSError, ValueError) as exc:
            st.inputs_ok[name] = False
            jsonlog.warn(f"{name} stream dropped", err=type(exc).__name__)
        time.sleep(backoff)
        backoff = min(8.0, backoff * 2)


def create_app() -> FastAPI:
    st = State(os.environ.get("CONTROL_MODE", "live"))

    def on_detect(event: str, data: dict) -> None:
        if event == "tick" and contracts.accept("segment_state", data):
            st.run(data["run_id"]).on_tick(data)

    def on_ledger(event: str, data: dict) -> None:
        if event == "ledger_event" and st.current:
            st.runs[st.current].on_ledger_event(data)

    def retry_timer() -> None:
        while not st.stop.wait(st.cfg.c.ledger.pending_retry_s):
            for r in list(st.runs.values()):
                with r.lock:
                    r.retry_ledger()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if st.mode == "mock":
            inc = json.loads((contracts.contracts_dir() / "fixtures" / "incident.json").read_text(encoding="utf-8"))
            r = st.run(inc["run_id"])
            r.now_ms = inc["updated_sim_ms"]
            r.on_incident(inc)
        elif st.mode == "live":
            if os.environ.get("DETECT_URL"):
                threading.Thread(target=_sse_loop, args=(st, os.environ["DETECT_URL"], "detect", on_detect),
                                 daemon=True).start()
            if st.ledger_url:
                threading.Thread(target=_sse_loop, args=(st, st.ledger_url, "ledger", on_ledger), daemon=True).start()
        threading.Thread(target=retry_timer, daemon=True).start()
        jsonlog.info("m4 started", mode=st.mode, operator_mode=st.operator_mode, ledger=st.ledger_url or "model")
        yield
        st.stop.set()

    app = FastAPI(title="QueueShield M4 Control", version="1", lifespan=lifespan)
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
        ok = all(st.inputs_ok.values())
        return {"status": "ok" if ok else "degraded", "module": "m4", "mode": st.mode, "version": st.version,
                "rejected_messages_total": contracts.REJECTED.total}

    @app.get("/v1/stream")
    async def stream(last_event_id: Optional[str] = Header(default=None)):
        return StreamingResponse(st.hub.stream(last_event_id), media_type="text/event-stream")

    @app.get("/v1/recommendations")
    def recommendations(status: Optional[str] = None, run_id: Optional[str] = None):
        r = st.runs.get(run_id or st.current or "")
        return [x for x in (r.recs.values() if r else []) if status in (None, x["status"])]

    @app.post("/v1/decisions")
    async def decisions(request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request)
        if not isinstance(body, dict):
            return err(400, "BAD_REQUEST", "invalid JSON")
        run = next((r for r in st.runs.values() if body.get("rec_id") in r.recs), None)
        if run is None:
            return err(404, "NOT_FOUND", f"unknown recommendation {body.get('rec_id')}")
        try:
            return run.decide(body)["resp"]
        except Conflict as exc:
            return err(409, "CONFLICT", str(exc))
        except BadRequest as exc:
            return err(400, "SCHEMA_INVALID", str(exc))

    @app.get("/v1/actions/pending")
    def actions_pending(run_id: Optional[str] = None, since: Optional[str] = None,
                        x_qs_key: Optional[str] = Header(default=None)):
        r = st.runs.get(run_id or st.current or "")
        return r.pending_actions(since) if r else []

    @app.post("/v1/actions/{action_id}/applied")
    async def applied(action_id: str, request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request) or {}
        for r in st.runs.values():
            try:
                r.mark_applied(action_id, body)
                return {"action_id": action_id}
            except BadRequest:
                continue
        return err(404, "NOT_FOUND", action_id)

    @app.post("/v1/batch/reset")
    async def batch_reset(request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request)
        if body is None or contracts.errors("lockstep", body, "ResetRequest"):
            return err(400, "SCHEMA_INVALID", "ResetRequest")
        st.runs.pop(body["run_id"], None)
        r = RunControl(st.cfg, body["run_id"], ModelLedger(), body.get("operator_mode", "auto"),
                       body.get("operator_delay_s"))
        st.runs[body["run_id"]] = r
        return {"run_id": body["run_id"]}

    @app.post("/v1/batch/tick")
    async def batch_tick(request: Request, x_qs_key: Optional[str] = Header(default=None)):
        if not authorised(x_qs_key):
            return err(401, "UNAUTHORIZED", "missing or wrong X-QS-Key")
        body = await body_json(request)
        if body is None or not isinstance(body, dict) or body.get("run_id") not in st.runs:
            return err(404, "NOT_FOUND", "reset the run first")
        r = st.runs[body["run_id"]]
        for ev in body.get("ledger_events", []):
            r.on_ledger_event(ev)
        out = r.on_tick(body["snapshot"])
        contracts.validate("lockstep", out, "ControlTickResponse")
        return out

    return app
