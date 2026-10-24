"""M3 acceptance tests (docs/M3_DETECTION.md §9)."""
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import RUN, Stream, drive
from qdet import contracts
from qdet import segments as S
from qdet.config import default as cfg_default
from qdet.features import FI, FeatureEngine
from qdet.forecast.grid import StuckGrid
from qdet.localizer import raw_verdict
from qdet.pipeline import Pipeline
from qdet.tracker import PaymentTracker

CFG = cfg_default()
DATA = Path(__file__).resolve().parents[2] / "data" / "runs"


def test_d1_features_match_hand_computed():
    s = Stream()
    s.snapshots(0)
    # 8 fresh + 2 retries on route P1->B1/B2 in [0, 10 s); 2 of the 10 time out, 1 is near-timeout
    for k in range(8):
        s.attempt(100 + k * 500, "P1", "B1", "B2", rt=300)
    s.attempt(5000, "P1", "B1", "B2", status="CLIENT_TIMEOUT", retry=1)
    s.attempt(6000, "P1", "B1", "B2", status="CLIENT_TIMEOUT", retry=1)
    fe = FeatureEngine(CFG, PaymentTracker(15000))
    for e in s.sorted():
        if e["sim_ms"] < 10_000:
            fe.ingest(e)
    ft = fe.tick(10_000)
    i = S.INDEX["psp:P1:*"]
    f = ft.F[i]
    assert f[FI["arrival_rate"]] == pytest.approx(1.0)
    assert f[FI["fresh_rate"]] == pytest.approx(0.8)
    assert f[FI["raf"]] == pytest.approx(2 / 8 + 1)
    assert f[FI["timeout_ratio"]] == pytest.approx(0.2)        # 2 of 10 outcomes
    assert f[FI["near_timeout_ratio"]] == pytest.approx(0.2)   # timeouts are >= 0.8 x timeout
    assert f[FI["pending_count"]] == 2
    assert math.isnan(f[FI["p95_ms"]])                          # 8 completions < 20 samples -> null, not 0
    # bank involvement: B1 (remitter) and B2 (beneficiary) both see the attempt
    for b in ("bank:*:B1", "bank:*:B2", "route:P1:B1", "route:P1:B2"):
        assert ft.F[S.INDEX[b], FI["arrival_rate"]] == pytest.approx(1.0)
    assert ft.F[S.INDEX["bank:*:B3"], FI["arrival_rate"]] == 0


def test_d2_bucket_edge():
    s = Stream()
    s.attempt(5000, "P2", "B3", "B3", rt=100)      # sent exactly on the boundary
    fe = FeatureEngine(CFG, PaymentTracker(15000))
    for e in s.sorted():
        fe.ingest(e)
    a = fe.tick(5000).sent[S.INDEX["psp:P2:*"]]
    b = fe.tick(10_000).sent[S.INDEX["psp:P2:*"]]
    assert (a, b) == (0, 1)                        # window [T - W, T): lands in exactly one tick's window
    assert fe.tick(10_000).sent[S.INDEX["bank:*:B3"]] == 1   # remitter == beneficiary counted once


def test_d3_baseline_freezes_while_incident_open():
    fe = FeatureEngine(CFG, PaymentTracker(15000))
    fe.bl.mean[:] = 1.0
    fe.bl.n[:] = 5
    fe.set_frozen({"psp:P1:*"})
    x = np.full_like(fe.bl.mean, 9.0)
    fe.bl.update(x, np.ones(S.N, dtype=bool))
    assert (fe.bl.mean[S.INDEX["psp:P1:*"]] == 1.0).all()
    assert (fe.bl.mean[S.INDEX["psp:P2:*"]] > 1.0).all()


def _faulty(t0, t1, statuses):
    def bad(t, p, r, b):
        if t0 <= t < t1:
            return statuses(p, r, b)
        return None
    return bad


def test_d5_one_noisy_tick_never_warns():
    # every event of the burst falls in one 1 s bucket, so it is inside exactly two 10 s tick windows
    noise = _faulty(201_000, 201_900, lambda p, r, b: "CLIENT_TIMEOUT" if p == "P1" else None)
    ev = Stream().traffic(0, 260_000, 60, noise).sorted()
    snaps = drive(Pipeline(RUN, "U0", CFG, grid=None), ev, 260_000)
    assert all(s["global_state"] in ("MONITORING", "RECOVERING") for s in snaps)


def test_d3_warns_on_sustained_bank_fault_and_names_the_bank():
    fault = _faulty(200_000, 300_000, lambda p, r, b: "CLIENT_TIMEOUT" if "B4" in (r, b) else None)
    ev = Stream().traffic(0, 300_000, 80, fault).sorted()
    snaps = drive(Pipeline(RUN, "U0", CFG, grid=None), ev, 300_000)
    warned = [s for s in snaps if s["global_state"] in ("WARNING", "CRITICAL")]
    assert warned and warned[0]["tick_sim_ms"] <= 230_000
    assert any(s["localization"]["verdict"] == "BANK_SIDE"
               and s["localization"]["primary_segment_id"] == "bank:*:B4" for s in snaps)
    first_inc = next(i for s in snaps for i in s["incidents"])
    assert first_inc["segment_id"] == "bank:*:B4"


# ---------------------------------------------------------------- D-6 localizer on synthetic matrices
BASE_INV = np.array([0.5, 0.45, 0.4, 0.3, 0.2])


def _matrices(rng, hot=None, n=40.0, rate=0.01):
    exp = np.full((S.NP, S.NB, S.NB), n * rate)
    bad = rng.poisson(exp).astype(float)
    if hot is not None:
        bad += hot
    return bad, exp


def _hot_psp(p=1, k=8.0):
    h = np.zeros((S.NP, S.NB, S.NB))
    h[p] = k
    return h


def _hot_bank(b=2, k=8.0, role="ben"):
    h = np.zeros((S.NP, S.NB, S.NB))
    if role == "ben":
        h[:, :, b] = k
    else:
        h[:, b, :] = k
    return h


def _hot_cell(p=0, b=3, k=25.0):
    h = np.zeros((S.NP, S.NB, S.NB))
    h[p, :, b] = k
    return h


@pytest.mark.parametrize("hot,switch,expect,primary", [
    (_hot_psp(1), False, "PSP_SIDE", "psp:P2:*"),
    (_hot_bank(2, role="ben"), False, "BANK_SIDE", "bank:*:B3"),
    (_hot_bank(2, role="rem"), False, "BANK_SIDE", "bank:*:B3"),
    (_hot_cell(0, 3), False, "ROUTE_SPECIFIC", "route:P1:B4"),
    (np.full((S.NP, S.NB, S.NB), 2.0), True, "SWITCH_STATUS_OVERLOAD", "switch:*:*"),
    (np.full((S.NP, S.NB, S.NB), 2.0), False, "PLATFORM_WIDE", None),
])
def test_d6_localizer_verdicts_and_noise_robustness(hot, switch, expect, primary):
    rng = np.random.default_rng(6)
    ok = 0
    for _ in range(1000):
        bad, exp = _matrices(rng, hot)
        v = raw_verdict(bad, exp, BASE_INV, switch, CFG)
        ok += v.verdict == expect and v.primary_segment_id == primary
    assert ok >= 950, (expect, ok)


def test_d6_insufficient_evidence_when_flat():
    rng = np.random.default_rng(1)
    bad, exp = _matrices(rng)
    assert raw_verdict(bad, exp, BASE_INV, False, CFG).verdict == "INSUFFICIENT_EVIDENCE"


def test_d7_grid_monotone_and_fast():
    rng = np.random.default_rng(7)
    d, o = rng.uniform(0, 2, 5000), rng.uniform(0, 3, 5000)
    y = (rng.uniform(size=5000) < 1 / (1 + np.exp(-(3 * d + o - 4)))).astype(float)
    g = StuckGrid().fit(d, o, y, monotone=True)
    assert (np.diff(g.p, axis=0) >= 0).all() and (np.diff(g.p, axis=1) >= 0).all()
    t = time.perf_counter()
    for _ in range(1000):
        g.predict(1.1, 0.7)
    assert (time.perf_counter() - t) / 1000 < 1e-3
    out = g.to_dict()
    assert len(out["delay_bins"]) == 21 and len(out["orbit_bins"]) == 21 and np.array(out["p"]).shape == (20, 20)
    assert StuckGrid.from_dict(out).predict(1.1, 0.7)[0] == pytest.approx(g.predict(1.1, 0.7)[0], abs=1e-6)


def test_d8_every_published_message_validates():
    fault = _faulty(200_000, 260_000, lambda p, r, b: "CLIENT_TIMEOUT" if p == "P3" else None)
    ev = Stream().traffic(0, 260_000, 60, fault).sorted()
    snaps = drive(Pipeline(RUN, "U0", CFG, grid=None), ev, 260_000)
    for s in snaps[::5] + snaps[-6:]:
        assert contracts.errors("segment_state", s) == []
        for inc in s["incidents"]:
            assert contracts.errors("incident", inc) == []
    fx = json.loads((contracts.contracts_dir() / "fixtures" / "incident.json").read_text())
    assert contracts.errors("incident", fx) == []


def test_d9_input_cut_degrades_within_one_tick():
    ev = [e for e in Stream().traffic(0, 200_000, 40).sorted() if e["sim_ms"] < 188_000]
    snaps = drive(Pipeline(RUN, "U0", CFG, grid=None), ev, 200_000)
    by_t = {s["tick_sim_ms"]: s["global_state"] for s in snaps}
    assert by_t[185_000] != "DEGRADED_MONITORING"
    assert by_t[200_000] == "DEGRADED_MONITORING"       # 12 s after the last event, at the next tick


@pytest.mark.skipif(not list(DATA.glob("r-S3-*-U0/events.jsonl")), reason="needs an M2 S3 run in data/runs")
def test_d10_s3_recorded_run_d3_before_d0_and_right_bank():
    d = sorted(DATA.glob("r-S3-*-U0"))[0]
    truth = json.loads((d / "ground_truth.json").read_text())[0]
    ev = [json.loads(x) for x in (d / "events.jsonl").open(encoding="utf-8")]
    snaps = drive(Pipeline(d.name, "U0", CFG, validate=False, grid=None), ev, truth["end_ms"])
    d3 = [a for s in snaps for a in s["detector_alerts"] if a["detector"] == "D3"]
    d0 = [a for s in snaps for a in s["detector_alerts"] if a["detector"] == "D0"]
    assert d3
    assert not d0 or min(a["first_alert_sim_ms"] for a in d3) < min(a["first_alert_sim_ms"] for a in d0)
    incs = [i for s in snaps for i in s["incidents"]]
    assert incs[0]["segment_id"] == f"bank:*:{truth['bank']}" and incs[0]["verdict"] == "BANK_SIDE"


def test_m3_t01_split_integrity_and_forecaster_evaluation():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import train_forecaster as tf
    fake_runs = [
        {"run_id": "r-S4-1-U0", "samples": [(0.2, 0.3, 0.0)], "stuck": 0.0},
        {"run_id": "r-S4-2-U0", "samples": [(1.5, 2.2, 1.0)], "stuck": 1.0},
        {"run_id": "r-S4-1001-U0", "samples": [(0.3, 0.4, 0.0)], "stuck": 0.0},
        {"run_id": "r-S4-1002-U0", "samples": [(1.6, 2.4, 1.0)], "stuck": 1.0},
        {"run_id": "r-S4-2001-U0", "samples": [(0.4, 0.5, 0.0)], "stuck": 0.0},
    ]
    splits = tf.split_runs(fake_runs)
    ids_a = {r["run_id"] for r in splits["A"]}
    ids_b = {r["run_id"] for r in splits["B"]}
    ids_c = {r["run_id"] for r in splits["C"]}
    assert ids_a == {"r-S4-1-U0", "r-S4-2-U0"}
    assert ids_b == {"r-S4-1001-U0", "r-S4-1002-U0"}
    assert ids_c == {"r-S4-2001-U0"}
    assert not (ids_a & ids_b) and not (ids_b & ids_c) and not (ids_a & ids_c)


def test_m3_t02_single_bank_fault_at_demo_rate_opens_one_incident():
    fault = _faulty(150_000, 220_000, lambda p, r, b: "CLIENT_TIMEOUT" if b == "B1" else None)
    ev = Stream().traffic(0, 230_000, 25, fault).sorted()
    pipe = Pipeline(RUN, "U0", CFG, grid=None)
    snaps = drive(pipe, ev, 230_000)
    live_ids = {inc["incident_id"] for s in snaps for inc in s["incidents"]}
    assert len(live_ids) == 1
    assert list(pipe.lifecycle.incidents.values())[0].segment_id == "bank:*:B1"


def test_m3_t06_watermark_late_events_and_dedupe():
    s = Stream()
    s.attempt(10_000, "P1", "B1", "B2", rt=100)
    s.attempt(15_000, "P1", "B1", "B2", rt=100)
    ev_list = s.sorted()
    dup = dict(ev_list[0])
    # Late event: arrives after sim_ms=15_000 with timestamp 11_000 (watermark is 2_000 ms, so 15_000 - 11_000 = 4_000 > 2_000)
    s2 = Stream()
    s2.attempt(11_000, "P1", "B1", "B2", rt=100)
    late_ev = s2.sorted()[0]
    late_ev["event_id"] = f"{RUN}-00999999"

    pipe = Pipeline(RUN, "U0", CFG, validate=False, grid=None)
    pipe.ingest([ev_list[0], dup, ev_list[-1]])
    assert pipe.ingestor.metrics["duplicates"] == 1
    pipe.ingest([late_ev])
    assert pipe.ingestor.metrics["late"] == 1


def test_m3_t06_model_degraded_after_two_slow_ticks(monkeypatch):
    s = Stream().traffic(0, 20_000, 30).sorted()
    pipe = Pipeline(RUN, "U0", CFG, validate=False, grid=None)
    pipe.ingest([e for e in s if e["sim_ms"] < 15_000])
    orig_update = pipe.forecast.update

    def slow_update(ft, timeout_ms):
        time.sleep(0.055)
        return orig_update(ft, timeout_ms)

    monkeypatch.setattr(pipe.forecast, "update", slow_update)
    snap1 = pipe.tick(5_000)
    assert snap1["global_state"] != "DEGRADED_MONITORING"
    snap2 = pipe.tick(10_000)
    assert pipe.model_degraded is True
    assert snap2["global_state"] == "DEGRADED_MONITORING"
    p1_seg = next(seg for seg in snap2["segments"] if seg["segment_id"] == "psp:P1:*")
    assert "model_degraded" in p1_seg["flags"]

