"""Deterministic policy: rule table -> eligible, bounded actions -> recommendation record (docs/M4_CONTROL.md §3-§5).

Ported from the IBM project's qs/core/policy.py (rule order, verdict gate, SHIFT checks returning the first failed
check), re-targeted to the QueueShield contract and with the rule table moved into config/policy.yaml.
Models detect; these rules decide what is eligible; humans decide what happens.
"""
from __future__ import annotations

from typing import Optional

PSPS = ("P1", "P2", "P3")
SHIFT_FORBIDDEN = ("BANK_SIDE", "SWITCH_STATUS_OVERLOAD", "MULTI_FAULT", "PLATFORM_WIDE")
NO_SIM_EFFECT = ("HOLD_MONITOR", "ESCALATE_HUMAN")


def _seg(snapshot: Optional[dict], segment_id: str) -> Optional[dict]:
    for s in (snapshot or {}).get("segments", []):
        if s["segment_id"] == segment_id:
            return s
    return None


def _parts(segment_id: str) -> tuple:
    level, p, b = segment_id.split(":")
    return level, (None if p == "*" else p), (None if b == "*" else b)


def context(incident: dict, snapshot: Optional[dict]) -> dict:
    """Derive the facts the rules need. Never reads simulator internals or ground truth."""
    loc = (snapshot or {}).get("localization", {})
    _, p, b = _parts(incident["segment_id"])
    cands = loc.get("candidates", [])
    if p is None:
        psps = [c for c in cands if c["segment_id"].startswith("psp:")]
        p = _parts(psps[0]["segment_id"])[1] if psps else None
    banks = [c for c in cands if c["segment_id"].startswith("bank:")]
    if b is None:
        prim = loc.get("primary_segment_id") or ""
        b = _parts(prim)[2] if prim.startswith(("bank:", "route:")) else (_parts(banks[0]["segment_id"])[2] if banks else None)
    lift = {(_parts(c["segment_id"])[2]): c.get("lift", 0.0) for c in banks}
    seg = _seg(snapshot, incident["segment_id"])
    degraded = (snapshot or {}).get("global_state") == "DEGRADED_MONITORING" or (
        seg is not None and seg["state"] == "DEGRADED_MONITORING")
    return {"psp": p, "bank": b, "bank_lift": lift.get(b, 0.0), "degraded": degraded,
            "surge": bool(seg and seg.get("surge")), "verdict": incident["verdict"], "severity": incident["severity"]}


def match_rule(policy: dict, ctx: dict) -> tuple:
    for r in policy["rules"]:
        w = r["when"]
        if "degraded" in w and ctx["degraded"] != w["degraded"]:
            continue
        if "surge" in w and ctx["surge"] != w["surge"]:
            continue
        if "severity" in w and ctx["severity"] != w["severity"]:
            continue
        if "verdict" in w and ctx["verdict"] not in w["verdict"]:
            continue
        return r["id"], r["actions"], r.get("note")
    return "FALLBACK", policy["fallback"], None


def scope_id(scope: str, incident: dict, ctx: dict) -> Optional[str]:
    p, b = ctx["psp"], ctx["bank"]
    return {"incident": incident["segment_id"], "switch": "switch:*:*", "platform": "platform:*:*",
            "psp": f"psp:{p}:*" if p else None, "bank": f"bank:*:{b}" if b else None,
            "route": f"route:{p}:{b}" if p and b else None}[scope]


def shift_block(cfg, ctx: dict, snapshot: Optional[dict], source_psp: Optional[str], route_bank: Optional[str]) -> Optional[str]:
    """None if every §4 check passes, else the first failed check (shown as blocked_by)."""
    sh = cfg.c.shift
    if ctx["verdict"] in SHIFT_FORBIDDEN:
        return f"{ctx['verdict']}: shifting traffic would spread the fault"
    if source_psp is None:
        return "no single source PSP"
    if route_bank is not None:     # R5: bank must be healthy via the other PSPs
        for q in PSPS:
            s = _seg(snapshot, f"route:{q}:{route_bank}")
            if q != source_psp and s and s["state"] in ("WARNING", "CRITICAL"):
                return f"bank {route_bank} is not healthy via {q}"
    src = _seg(snapshot, f"psp:{source_psp}:*")
    targets = [q for q in PSPS if q != source_psp]
    src_rate = (src or {}).get("features", {}).get("arrival_rate") or 0.0
    moved = src_rate * sh.max_step / len(targets)
    for q in targets:
        s = _seg(snapshot, f"psp:{q}:*")
        if s is None:
            return f"no data for target {q}"
        if s["state"] in ("WARNING", "CRITICAL") or s.get("forecast_state") in ("WATCH", "CRITICAL"):
            return f"target {q} is not calm"
        f = s["features"]
        arr, load = f.get("arrival_rate"), f.get("load_over_capacity")
        if not arr or not load:
            return f"capacity of target {q} unknown"
        cap = arr / load
        if 1.0 - (arr + moved) / cap < sh.target_min_spare:
            return f"target {q} would have < {int(sh.target_min_spare * 100)} % spare capacity"
    return None


def params_for(cfg, atype: str, spec: dict, ctx: dict) -> dict:
    c = cfg.c
    if atype == "THROTTLE_RETRIES":
        frac = c.throttle.warning_rate_fraction if (spec.get("light") or ctx["severity"] == "WARNING") \
            else c.throttle.critical_rate_fraction
        return {"rate_fraction": frac, "retry_after_ms": list(c.throttle.retry_after_ms)}
    if atype == "DEFER_CHECKS":
        return {"budget_multiplier": c.defer.budget_multiplier,
                "first_check_delay_multiplier": c.defer.first_check_delay_multiplier}
    if atype == "SHIFT_TRAFFIC":
        return {"fraction": c.shift.max_step, "ramp_ms": c.shift.ramp_ms}
    if atype == "ESCALATE_HUMAN":
        return {"reason": ctx["verdict"]}
    return {}


def build_actions(cfg, incident: dict, snapshot: Optional[dict]) -> tuple:
    """(rule_id, note, [recommendation action dicts]). SI-2 and SI-4 hold by construction."""
    ctx = context(incident, snapshot)
    rule_id, specs, note = match_rule(cfg.policy, ctx)
    text, amap = cfg.policy["text"], cfg.policy["advisory_map"]
    out = []
    for spec in specs:
        t = spec["type"]
        if "if_bank_lift_above" in spec and ctx["bank_lift"] <= spec["if_bank_lift_above"]:
            continue
        sid = scope_id(spec["scope"], incident, ctx) or incident["segment_id"]
        blocked = None
        if t == "SHIFT_TRAFFIC":
            if spec.get("blocked_reason"):
                blocked = spec["blocked_reason"].format(bank=ctx["bank"] or "?")
            else:
                route_bank = ctx["bank"] if spec["scope"] == "route" else None
                blocked = shift_block(cfg, ctx, snapshot, ctx["psp"], route_bank)
        if ctx["degraded"] and t not in NO_SIM_EFFECT:
            blocked = "degraded monitoring"                                      # SI-4 safety net
        adv = amap.get("SHIFT_TRAFFIC_BLOCKED") if (t == "SHIFT_TRAFFIC" and blocked) else amap.get(t)
        out.append({"action_type": t, "params": params_for(cfg, t, spec, ctx), "scope_segment_id": sid,
                    "eligible": blocked is None, "blocked_by": blocked, "advisory_kind": adv,
                    "side_effect": text["side_effect"][t] + ("; in-flight and unknown payments are never moved"
                                                            if t == "SHIFT_TRAFFIC" else ""),
                    "rollback_condition": text["rollback_condition"][t]})
    return rule_id, note, out


def recommendation(cfg, rec_id: str, incident: dict, snapshot: Optional[dict], now_ms: int) -> dict:
    rule_id, note, actions = build_actions(cfg, incident, snapshot)
    mv = dict(incident.get("model_versions", {}))
    mv["policy"] = cfg.policy["rules_version"]
    return {"rec_id": rec_id, "incident_id": incident["incident_id"], "run_id": incident["run_id"],
            "created_sim_ms": int(now_ms), "segment_id": incident["segment_id"], "severity": incident["severity"],
            "verdict": incident["verdict"], "p_stuck": incident.get("p_stuck"), "confidence": incident["confidence"],
            "countdown_s_estimate": incident.get("countdown_s_estimate"), "actions": actions,
            "reasons": incident.get("reasons", []), "status": "PENDING", "model_versions": mv,
            "features_sha256": incident["features_sha256"]}
