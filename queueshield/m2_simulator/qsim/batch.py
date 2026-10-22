"""Batch (lockstep) runner and arena (docs/01_SYSTEM.md §4.1, docs/M2_SIMULATOR.md §12).

For each 5 000 ms tick: advance the engine, POST the new events to detect `/v1/batch/tick`, POST the snapshot to
control `/v1/batch/tick`, apply returned actions whose effective time is before the next tick. U0-U2 skip the
QueueShield steps; U3 sends no ledger events. Without DETECT_URL/CONTROL_URL the run is open-loop (no actions),
which is what U0-U2 need anyway and lets M2 produce datasets alone.

    python -m qsim.batch --scenario S6 --seeds 1 2 3 --universes U0 U2 U4 --out ../data/runs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx

from qsim import config as config_mod
from qsim import contracts, ids, jsonlog, metrics, scenarios
from qsim.engine import Engine

GOVERNED = ("U3", "U4")


def sim_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or "dev"
    except (OSError, subprocess.CalledProcessError):
        return "dev"


def config_sha256(cfg) -> str:
    return hashlib.sha256(repr(cfg).encode()).hexdigest()


class Lockstep:
    """HTTP client for the M3/M4 batch endpoints."""

    def __init__(self, detect_url: str, control_url: str, operator_delay_s: Optional[float]) -> None:
        self.detect_url, self.control_url = detect_url.rstrip("/"), control_url.rstrip("/")
        self.delay = operator_delay_s
        self.http = httpx.Client(timeout=30.0, headers={"X-QS-Key": os.environ.get("QS_API_KEY", "")})

    def reset(self, run_id: str) -> None:
        body = {"run_id": run_id, "mode": "batch", "operator_mode": "auto"}
        if self.delay is not None:
            body["operator_delay_s"] = self.delay
        contracts.validate("lockstep", body, "ResetRequest")
        for url in (self.detect_url, self.control_url):
            self.http.post(f"{url}/v1/batch/reset", json=body).raise_for_status()

    def tick(self, run_id: str, universe: str, t: int, events: list, ledger_events: list) -> tuple:
        req = {"run_id": run_id, "universe": universe, "tick_sim_ms": t, "events": events}
        snap = self.http.post(f"{self.detect_url}/v1/batch/tick", json=req).json()
        if not contracts.accept("segment_state", snap):
            return snap, {"recommendations": [], "actions": [], "advisories": []}
        creq = {"run_id": run_id, "tick_sim_ms": t, "snapshot": snap, "ledger_events": ledger_events}
        resp = self.http.post(f"{self.control_url}/v1/batch/tick", json=creq).json()
        if not contracts.accept("lockstep", resp, "ControlTickResponse"):
            resp = {"recommendations": [], "actions": [], "advisories": []}
        return snap, resp


def run_one(scenario: str, seed: int, universe: str, out_dir: Optional[Path] = None,
            lockstep: Optional[Lockstep] = None, overrides: Optional[dict] = None,
            horizon_ms: Optional[int] = None) -> dict:
    cfg = config_mod.load(overrides=(overrides or {}).get("config"))
    spec = scenarios.build(scenario, seed, cfg, (overrides or {}).get("scenario"))
    rid = ids.run_id(scenario, seed, universe)
    e = Engine(cfg, spec, seed, universe, rid, horizon_ms=horizon_ms)
    all_events: list = []
    ticks: list = []
    use_qs = lockstep is not None and universe in GOVERNED
    if use_qs:
        lockstep.reset(rid)
    tick = cfg.run.tick_ms
    pending_actions: list = []
    t = tick
    while t <= e.horizon:
        e.run_until(t)
        for a in [a for a in pending_actions if a["effective_from_sim_ms"] <= t]:
            e.apply_action(a)
            pending_actions.remove(a)
        ev = e.drain_events()
        all_events.extend(ev)
        if use_qs:
            # TODO(M2): U4 should forward the ledger-model events (PaymentUpdated etc.) as ledger_event records.
            snap, resp = lockstep.tick(rid, universe, t, ev, [])
            ticks.append(snap)
            pending_actions.extend(resp.get("actions", []))
        t += tick
    e.run_to_completion()
    all_events.extend(e.drain_events())
    result = {"run_id": rid, "scenario": scenario, "seed": int(seed), "universe": universe,
              "config_sha256": config_sha256(cfg), "sim_version": sim_version(),
              "metrics": metrics.run_metrics(e), "ground_truth": spec.truth, "files": {"events": "events.jsonl"}}
    if out_dir is not None:
        d = Path(out_dir) / rid
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "events.jsonl", "w", encoding="utf-8") as f:
            for x in all_events:
                f.write(json.dumps(x, separators=(",", ":")) + "\n")
        (d / "ground_truth.json").write_text(json.dumps(spec.truth, indent=1), encoding="utf-8")
        (d / "timeseries.json").write_text(json.dumps(metrics.timeseries(e)), encoding="utf-8")
        result["files"].update(ground_truth="ground_truth.json", timeseries="timeseries.json")
        if ticks:
            with open(d / "ticks.jsonl", "w", encoding="utf-8") as f:
                for x in ticks:
                    f.write(json.dumps(x, separators=(",", ":")) + "\n")
            result["files"]["ticks"] = "ticks.jsonl"
        contracts.validate("run_result", result)
        (d / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    jsonlog.info("run done", run_id=rid, events=len(all_events))
    return result


def main(argv: Optional[list] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--universes", nargs="+", default=["U0", "U2", "U4"])
    ap.add_argument("--out", default=os.environ.get("DATA_DIR", "../data") + "/runs")
    ap.add_argument("--operator-delay-s", type=float, default=None)
    a = ap.parse_args(argv)
    ls = None
    if os.environ.get("DETECT_URL") and os.environ.get("CONTROL_URL"):
        ls = Lockstep(os.environ["DETECT_URL"], os.environ["CONTROL_URL"], a.operator_delay_s)
    for seed in a.seeds:
        for u in a.universes:
            run_one(a.scenario, seed, u, Path(a.out), ls)


if __name__ == "__main__":
    main()
