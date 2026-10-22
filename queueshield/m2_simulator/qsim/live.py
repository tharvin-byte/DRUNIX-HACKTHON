"""Live runner (docs/M2_SIMULATOR.md §12): the engine advanced by wall clock x speed in a thread, events published
on the SSE hub, approved actions polled from M4 every `live.action_poll_s` and acknowledged.

Ledger: only LEDGER_MODE=model is implemented here (the in-sim latency model). LEDGER_MODE=live|mock (HTTP to the
M1 gateway, docs/01_SYSTEM.md §5) is a TODO in ledger_bridge.py; until then health reports `degraded`.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from typing import Optional

import httpx

from qsim import config as config_mod
from qsim import contracts, ids, jsonlog, scenarios
from qsim.engine import Engine
from qsim.sse import SseHub

STEP_WALL_S = 0.1


class LiveRun:
    def __init__(self, hub: SseHub, scenario: str, seed: int, universe: str, speed: int = 1,
                 overrides: Optional[dict] = None, control_url: Optional[str] = None) -> None:
        base = config_mod.load(overrides=(overrides or {}).get("config"))
        cfg = replace(base, fresh_rate_per_s=base.fresh_rate_per_s * base.live.demo_rate_factor)
        self.cfg = cfg
        self.spec = scenarios.build(scenario, seed, cfg, (overrides or {}).get("scenario"))
        self.run_id = ids.run_id(scenario, seed, universe, suffix="live")
        self.scenario, self.seed, self.universe, self.speed = scenario, seed, universe, speed
        self.hub = hub
        self.engine = Engine(cfg, self.spec, seed, universe, self.run_id, emit=None)
        self.state = "IDLE"
        self.achieved_speed = float(speed)
        self.control_url = control_url
        self.last_action: Optional[str] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.error: Optional[str] = None

    @property
    def sim_ms(self) -> int:
        return self.engine.now

    def start(self) -> None:
        self.state = "RUNNING"
        self.hub.publish("run_started", {"run_id": self.run_id})
        self._thread = threading.Thread(target=self._loop, name=f"live-{self.run_id}", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()
        self.state = "PAUSED"

    def resume(self) -> None:
        self._paused.clear()
        self.state = "RUNNING"

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _publish(self, events: list) -> None:
        for e in events:
            if contracts.accept("payment_event", e):
                self.hub.publish("payment_event", e)
            else:
                jsonlog.error("dropped invalid outgoing event", run_id=self.run_id, event_id=e.get("event_id"))

    def _poll_actions(self, http: httpx.Client) -> None:
        if not self.control_url:
            return
        try:
            params = {"run_id": self.run_id}
            if self.last_action:
                params["since"] = self.last_action
            r = http.get(f"{self.control_url}/v1/actions/pending", params=params)
            r.raise_for_status()
            for a in r.json():
                if not contracts.accept("action", a):
                    continue
                with self._lock:
                    res = self.engine.apply_action(a)
                self.last_action = a["action_id"]
                http.post(f"{self.control_url}/v1/actions/{a['action_id']}/applied",
                          json={"sim_ms": self.engine.now, "result": res, "detail": ""})
        except httpx.HTTPError as exc:
            jsonlog.warn("action poll failed", run_id=self.run_id, err=type(exc).__name__)

    def _loop(self) -> None:
        http = httpx.Client(timeout=5.0, headers={"X-QS-Key": os.environ.get("QS_API_KEY", "")})
        last_poll = 0.0
        try:
            end = self.engine.horizon
            t0_wall = time.monotonic()
            t0_sim = self.engine.now
            last_speed = self.speed
            was_paused = False
            while not self._stop.is_set() and self.engine.now < end:
                time.sleep(STEP_WALL_S)
                if self._paused.is_set():
                    was_paused = True
                    continue
                now_wall = time.monotonic()
                if was_paused or self.speed != last_speed:
                    t0_wall = now_wall
                    t0_sim = self.engine.now
                    last_speed = self.speed
                    was_paused = False
                    continue
                sim_target = min(end, t0_sim + max(1, int((now_wall - t0_wall) * 1000.0 * self.speed)))
                with self._lock:
                    self.engine.run_until(sim_target)
                    ev = self.engine.drain_events()
                elapsed = max(1e-3, time.monotonic() - t0_wall)
                self.achieved_speed = round(((self.engine.now - t0_sim) / 1000.0) / elapsed, 2)
                self._publish(ev)
                if time.monotonic() - last_poll >= self.cfg.live.action_poll_s:
                    last_poll = time.monotonic()
                    self._poll_actions(http)
            self.state = "DONE"
            self.hub.publish("run_done", {"run_id": self.run_id})
        except Exception as exc:  # surface crashes in /v1/status instead of dying silently
            self.error = f"{type(exc).__name__}: {exc}"
            self.state = "DONE"
            jsonlog.error("live run crashed", run_id=self.run_id, err=self.error)
        finally:
            http.close()
