"""Fabricated M3 snapshots and incidents (schema-valid) so M4 tests never need M3 running."""
import copy
import json

from qctl import contracts

PSPS = ("P1", "P2", "P3")
BANKS = ("B1", "B2", "B3", "B4", "B5")
SEGMENTS = (["platform:*:*"] + [f"psp:{p}:*" for p in PSPS] + [f"bank:*:{b}" for b in BANKS]
            + [f"route:{p}:{b}" for p in PSPS for b in BANKS] + ["switch:*:*"])
FEATURES = ["arrival_rate", "fresh_rate", "raf", "success_ratio", "timeout_ratio", "near_timeout_ratio",
            "reject_ratio", "p50_ms", "p95_ms", "p99_ms", "latency_ratio", "pending_count", "pending_frac",
            "queue_depth", "queue_growth", "utilisation", "queue_delay_est_ms", "orbit_proxy", "status_check_rate",
            "switch_status_util", "load_over_capacity", "ledger_open_rate", "ledger_unresolved"]
RUN = "r-S3-1-U4"


def fixture_incident() -> dict:
    return json.loads((contracts.contracts_dir() / "fixtures" / "incident.json").read_text(encoding="utf-8"))


def snapshot(t=260_000, verdict="BANK_SIDE", primary="bank:*:B3", global_state="CRITICAL", states=None,
             status_rate=10.0, fresh=(60.0, 50.0, 40.0), load=0.5, surge=(), forecast=None, incidents=()) -> dict:
    states = states or {}
    segs = []
    for s in SEGMENTS:
        f = dict.fromkeys(FEATURES)
        if s.startswith("psp:"):
            i = PSPS.index(s.split(":")[1])
            f.update(arrival_rate=fresh[i], fresh_rate=fresh[i], load_over_capacity=load)
        if s == "switch:*:*":
            f.update(status_check_rate=status_rate)
        row = {"segment_id": s, "eligible": True, "flags": [], "features": f, "z": dict.fromkeys(FEATURES),
               "signals": dict.fromkeys(["lat", "to", "near_to", "q", "raf", "rej"], False),
               "surge": s in surge, "d0_alert": False, "d3_score": 0.1, "state": states.get(s, "MONITORING")}
        if s.startswith("psp:"):
            row.update(p_stuck=None, forecast_state=(forecast or {}).get(s), phase_point=None,
                       countdown_s_estimate=None)
        segs.append(row)
    snap = {"schema_version": 1, "run_id": RUN, "universe": "U4", "tick_sim_ms": t, "global_state": global_state,
            "segments": segs,
            "localization": {"verdict": verdict, "primary_segment_id": primary,
                             "candidates": [{"segment_id": "bank:*:B3", "share": 0.8, "lift": 0.6},
                                            {"segment_id": "psp:P1:*", "share": 0.4, "lift": 0.0}],
                             "confidence": 0.8, "total_excess": 120.0},
            "detector_alerts": [], "incidents": list(incidents)}
    assert contracts.errors("segment_state", snap) == [], contracts.errors("segment_state", snap)[:2]
    return snap


def incident(segment="bank:*:B3", verdict="BANK_SIDE", severity="CRITICAL", state="OPEN", inc_id="inc-0003",
             confidence=0.81) -> dict:
    inc = copy.deepcopy(fixture_incident())
    inc.update(segment_id=segment, verdict=verdict, severity=severity, state=state, incident_id=inc_id,
               confidence=confidence)
    return inc
