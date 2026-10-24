"""Pipeline.ingest(events) / Pipeline.tick(now_ms) -> segment_state (docs/M3_DETECTION.md §1, §8).

The same object serves live (SSE from M2), mock (fixtures) and batch (lockstep, one Pipeline per run_id).
Never reads ground truth (pitfall 4): training scripts live in scripts/ and are not imported here.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Optional

from qdet import segments as S
from qdet.config import default as default_cfg
from qdet.detectors.baseline_detectors import D0, D1, D2
from qdet.detectors.d3 import D3, SIGNALS
from qdet.features import FEATURES, FI, FeatureEngine
from qdet.forecast.runtime import ForecastRuntime, load_grid
from qdet.ingest import Ingestor
from qdet.lifecycle import Lifecycle, related
from qdet.localizer import Localizer
from qdet.tracker import PaymentTracker


NETWORK_ANCHOR = {"PLATFORM_WIDE": "platform:*:*", "MULTI_FAULT": "platform:*:*",
                  "SWITCH_STATUS_OVERLOAD": "switch:*:*"}


def num(x) -> Optional[float]:
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, 6)


class Pipeline:
    def __init__(self, run_id: str, universe: str, cfg=None, validate: bool = True, grid=None) -> None:
        self.cfg = cfg or default_cfg()
        self.run_id, self.universe = run_id, universe
        c = self.cfg
        self.tracker = PaymentTracker(c.windows.orbit_s * 1000)
        self.fe = FeatureEngine(c, self.tracker)
        self.localizer = Localizer(c)
        self.ingestor = Ingestor(self._on_event, c.windows.dedupe_capacity, c.windows.watermark_ms, validate)
        self.d0, self.d1, self.d2, self.d3 = D0(c), D1(c), D2(c), D3(c)
        self.forecast = ForecastRuntime(c, grid if grid is not None else load_grid(c))
        self.lifecycle = Lifecycle(c)
        self.client_timeout_ms = 3000.0          # replaced by the first observed client_timeout_ms
        self.last_event_ms: Optional[int] = None
        self.first_alert: dict = {}              # (detector, segment_id) -> first alert sim_ms while active
        self.last_tick_ms = 0
        self.incident_updates: list = []
        self.last_snapshot: Optional[dict] = None
        self._slow_model_ticks = 0
        self.model_degraded = False

    # ------------------------------------------------------------------ events
    def ingest(self, events) -> None:
        self.ingestor.ingest(events)

    def _on_event(self, e: dict, late: bool) -> None:
        self.fe.ingest(e)
        self.last_event_ms = e["sim_ms"] if self.last_event_ms is None else max(self.last_event_ms, e["sim_ms"])
        t = e["event_type"]
        if t == "ATTEMPT_OUTCOME":
            self.client_timeout_ms = float(e["client_timeout_ms"])
            self.localizer.on_outcome(e)
        elif t == "ACTION_APPLIED":
            for i in self.lifecycle.on_action_applied(e["sim_ms"], None):
                self.incident_updates.append(i)

    def ready_to_tick(self, t_ms: int) -> bool:
        """Live mode: tick once the event-time watermark has crossed the boundary."""
        return self.ingestor.max_ms - self.cfg.windows.watermark_ms >= t_ms

    # ------------------------------------------------------------------ tick
    def tick(self, now_ms: int) -> dict:
        c = self.cfg
        self.ingestor.release_until(now_ms - 1)
        ft = self.fe.tick(now_ms)
        degraded = self.last_event_ms is None or now_ms - self.last_event_ms >= c.eligibility.no_data_after_s * 1000
        d0 = self.d0.update(ft)
        d1 = self.d1.update(ft)
        d2 = self.d2.update(ft)
        d3 = self.d3.update(ft)
        t0_fc = time.perf_counter()
        fc = self.forecast.update(ft, self.client_timeout_ms)
        fc_ms = (time.perf_counter() - t0_fc) * 1000.0
        if fc_ms > c.d3.model_budget_ms:
            self._slow_model_ticks += 1
            if self._slow_model_ticks >= 2:
                self.model_degraded = True
        else:
            self._slow_model_ticks = 0
        sw_util = ft.F[S.SWITCH, FI["switch_status_util"]]
        loc = self.localizer.localize(now_ms // 1000, sw_util)

        def p_stuck_for(seg_id: str) -> Optional[float]:
            vals = [fc[S.PSP_IDX[p]]["p_stuck"] for p in S.psps_of(seg_id)]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else None

        severity = {}
        for i, r in enumerate(d3):
            if not r.warning:
                continue
            sid = S.SEGMENTS[i]
            ps = p_stuck_for(sid)
            crit = (ps is not None and ps >= c.d3.critical_p_stuck) or (
                i == S.SWITCH and not math.isnan(sw_util) and sw_util >= c.d3.critical_switch_util)
            severity[sid] = "CRITICAL" if crit else "WARNING"

        # incidents (D0 platform alerts are reported separately, never merged)
        updates, self.incident_updates = list(self.incident_updates), []
        # a network-wide verdict folds every warning into one incident, so the operator gets one package
        anchor = NETWORK_ANCHOR.get(loc.verdict)
        # M3-T02: when localizer says BANK_SIDE(b) or PSP_SIDE(p), route warnings route:*:b join the bank/psp incident
        # even if the bank/psp segment has not warned yet, provided at least one overlapping segment is warning now.
        primary = None
        if loc.primary_segment_id is not None:
            if loc.primary_segment_id in severity:
                primary = loc.primary_segment_id
            elif loc.verdict in ("BANK_SIDE", "PSP_SIDE") and any(related(s, loc.primary_segment_id) for s in severity):
                primary = loc.primary_segment_id
        # Also if two route warnings share the same bank (e.g. route:P1:B1 and route:P2:B1) on the same tick before
        # localizer hysteresis finishes, fold them into bank:*:b so M4 does not build two packages for one bank fault.
        if primary is None and anchor is None:
            route_banks = [s.split(":")[2] for s in severity if s.startswith("route:")]
            candidates = [
                b for b in S.BANKS
                if route_banks.count(b) >= 2 or (f"bank:*:{b}" in severity and route_banks.count(b) >= 1)
            ]
            if candidates:
                best_b = max(candidates, key=lambda b: d3[S.INDEX[f"bank:*:{b}"]].score)
                primary = f"bank:*:{best_b}"

        for sid, sev in severity.items():
            if sid == "platform:*:*" and len(severity) > 1 and anchor is None:
                continue
            inc, changed = self.lifecycle.on_warning(now_ms, sid, sev, anchor or primary,
                                                     force=anchor is not None)
            i = S.INDEX[sid]
            new_verdict = loc.verdict if (loc.primary_segment_id is None or related(inc.segment_id, loc.primary_segment_id)) else inc.verdict
            if new_verdict == "INSUFFICIENT_EVIDENCE" and inc.segment_id.startswith("bank:"):
                new_verdict = "BANK_SIDE"
            if changed or new_verdict != inc.verdict:
                inc.verdict, inc.updated_ms = new_verdict, now_ms
                inc.reasons, inc.confidence = d3[i].reasons, d3[i].confidence
                inc.features_sha256 = self._features_hash(ft, [i])
                updates.append(inc)
            inc.p_stuck = p_stuck_for(inc.segment_id)
            inc.countdown = max((fc[S.PSP_IDX[p]]["countdown_s_estimate"] or 0) for p in S.psps_of(inc.segment_id)) or None
        updates += self.lifecycle.tick(now_ms, set(severity))
        self.fe.set_frozen(self.lifecycle.open_segments())          # D-3: freeze baselines during incidents
        if not severity and not self.lifecycle.live():
            bad, _, n = self.localizer.window(now_ms // 1000)
            route_p95 = ft.B[S.ROUTE0:S.SWITCH, FI["p95_ms"]].reshape(S.NP, S.NB)
            self.localizer.learn(bad, n, route_p95, calm=True)

        # detector_alerts: first alert time while each detector's alert stays active
        active = {("D0", "platform:*:*")} if d0 else set()
        for i in range(S.N):
            if d1[i]:
                active.add(("D1", S.SEGMENTS[i]))
            if d2[i]:
                active.add(("D2", S.SEGMENTS[i]))
            if d3[i].warning:
                active.add(("D3", S.SEGMENTS[i]))
        self.first_alert = {k: self.first_alert.get(k, now_ms) for k in active}

        recovering = {i.segment_id for i in self.lifecycle.live() if i.state == "RECOVERING"}
        segs = []
        for i, sid in enumerate(S.SEGMENTS):
            flags = list(ft.flags[i])
            if self.model_degraded and sid.startswith("psp:"):
                flags.append("model_degraded")
            busy = not math.isnan(ft.B[i, FI["arrival_rate"]]) and ft.B[i, FI["arrival_rate"]] > 0
            seg_degraded = degraded or self.model_degraded or ("no_data" in flags and busy and "warming_up" not in flags)
            state = ("DEGRADED_MONITORING" if seg_degraded else severity.get(sid)
                     or ("RECOVERING" if sid in recovering else "MONITORING"))
            row = {"segment_id": sid, "eligible": bool(ft.eligible[i]), "flags": flags,
                   "features": {f: num(ft.F[i, j]) for j, f in enumerate(FEATURES)},
                   "z": {f: num(ft.Z[i, j]) for j, f in enumerate(FEATURES)},
                   "signals": {k: bool(d3[i].signals[k]) for k in SIGNALS}, "surge": d3[i].surge,
                   "d0_alert": bool(d0) if i == S.PLATFORM else False, "d3_score": round(float(d3[i].score), 6),
                   "state": state}
            level = sid.split(":")[0]
            if level == "psp":
                f = fc[i - S.PSP0]
                row.update(p_stuck=f["p_stuck"], forecast_state=f["state"], phase_point=f["phase_point"],
                           countdown_s_estimate=f["countdown_s_estimate"])
            segs.append(row)
        states = {s["state"] for s in segs}
        global_state = ("DEGRADED_MONITORING" if (degraded or self.model_degraded) else "CRITICAL" if "CRITICAL" in states
                        else "WARNING" if "WARNING" in states else "RECOVERING" if recovering else "MONITORING")
        self.last_tick_ms = now_ms
        uniq = {i.incident_id: i for i in updates if i.incident_id in self.lifecycle.incidents}
        self.last_snapshot = {"schema_version": 1, "run_id": self.run_id, "universe": self.universe, "tick_sim_ms": int(now_ms),
                "global_state": global_state, "segments": segs, "localization": loc.to_dict(),
                "detector_alerts": [{"detector": d, "segment_id": s, "first_alert_sim_ms": int(t)}
                                    for (d, s), t in sorted(self.first_alert.items())],
                "incidents": [self.incident_dict(i) for i in uniq.values()]}
        return self.last_snapshot

    def _features_hash(self, ft, rows: list) -> str:
        blob = json.dumps([[S.SEGMENTS[i], [num(x) for x in ft.F[i]]] for i in rows], sort_keys=True,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def incident_dict(self, i) -> dict:
        v = self.cfg.versions
        return {"incident_id": i.incident_id, "run_id": self.run_id, "segment_id": i.segment_id, "state": i.state,
                "severity": i.severity, "opened_sim_ms": int(i.opened_ms), "updated_sim_ms": int(i.updated_ms),
                "closed_sim_ms": None if i.closed_ms is None else int(i.closed_ms), "verdict": i.verdict,
                "p_stuck": i.p_stuck, "countdown_s_estimate": i.countdown, "reasons": i.reasons,
                "confidence": float(min(1.0, max(0.0, i.confidence))),
                "model_versions": {"detector": v.detector, "forecaster": v.forecaster, "localizer": v.localizer},
                "features_sha256": i.features_sha256}

    def incidents(self, state: Optional[str] = None) -> list:
        return [self.incident_dict(i) for i in self.lifecycle.incidents.values() if state in (None, i.state)]
