# M3 — Detection: features, detectors, Fault Localizer, Cascade Forecaster

> **Working copy** of the QueueShield spec v1.0 (19 Oct 2026), moved next to the code on 2026-10-20. The original stays frozen in `Citibank/queueshield-spec/` (next to `queueshield/`); this copy is the one the team updates.
> Folder names in this repo: `ledger/` → `m1_ledger/`, `sim/` → `m2_simulator/`, `detect/` → `m3_detection/`, `control/` → `m4_control/`, `console/` → `m5_console/`. Shared docs: `docs/` at the repo root; module specs: `SPEC.md` inside each module folder.

**Owner folder:** `detect/` · **Port:** 8002 · **Stack:** Python 3.11, NumPy, SciPy (optional), scikit-learn (IsolationForest, HistGradientBoosting), FastAPI, sse-starlette, httpx-sse · **Reads:** M2 stream (live) or lockstep ticks (batch); `data/runs/` for training · **Publishes:** per-tick `segment_state`, `incident` events, forecaster grid.

Your job: turn the payment-event stream into, every 5 000 sim ms, (a) a per-segment health picture, (b) four detectors' alerts, (c) a localisation verdict, (d) a lock-in probability per PSP, and (e) incidents with reasons. You never take actions and never touch the ledger.

---

## 1. Folder layout

```
detect/
├── config/detect.yaml           every number in this spec
├── qdet/
│   ├── schema.py                pydantic models from contracts
│   ├── ingest.py                validation, dedupe (LRU 200k event_ids), 2 000 ms watermark ordering
│   ├── segments.py              segment registry + involvement mapping §2
│   ├── windows.py               ring buffers of 1 s buckets, latency histograms
│   ├── features.py              §3
│   ├── baselines.py             EWMA mean/MAD per segment per feature, freeze rule
│   ├── detectors/{d0.py,d1.py,d2_cusum.py,d3.py,iforest.py,persistence.py,surge.py}
│   ├── localizer.py             §5
│   ├── forecast/{dataset.py,grid.py,ensemble.py,runtime.py}  §6
│   ├── lifecycle.py             incidents §7
│   ├── pipeline.py              Pipeline.ingest(events) / Pipeline.tick(now_ms) -> SegmentState
│   └── api.py
├── scripts/{train_forecaster.py, train_iforest.py, eval_detect.py}
└── tests/
```

## 2. Segments and involvement

Segments per tick: `platform:*:*` (1), `psp:Pk:*` (3), `bank:*:Bj` (5), `route:Pk:Bj` (15), `switch:*:*` (1) = **25**.

An attempt-level event (ATTEMPT_SENT, ATTEMPT_OUTCOME, STATUS_*, LEDGER_*) is counted in: platform; its psp; `bank` for the remitter **and** the beneficiary (once if equal); `route:psp:remitter` **and** `route:psp:beneficiary` (once if equal). STATUS_* events also count in `switch`. PSP_SNAPSHOT feeds psp (and routes/banks by traffic-weighted inheritance); SWITCH_SNAPSHOT feeds switch.

Minimum samples: a route with < 30 attempts in the short window is `low_volume` (no alerts on its own); latency quantiles with < 20 completions are `null`; a normally-busy segment with no events in the short window is `no_data` → DEGRADED_MONITORING.

## 3. Windows and features

Tick = 5 000 sim ms. Short window **Ws = 10 s**, long window **Wl = 60 s**, 1 s buckets in a ring of 120 per segment (NumPy arrays shaped `(25, 120, n_counters)`), latency as 64 log-spaced bins 10 ms–60 s per bucket. Late events beyond the 2 s watermark update their bucket if still in the ring, else increment `late_dropped`.

| Feature | Definition | Window |
|---|---|---|
| arrival_rate | ATTEMPT_SENT / s | Ws |
| fresh_rate | ATTEMPT_SENT with retry_count = 0 / s | Ws |
| raf | (retry attempts / fresh attempts) + 1; 1.0 if no fresh | Ws |
| success_ratio | SUCCESS / terminal outcomes | Wl |
| timeout_ratio | CLIENT_TIMEOUT / outcomes | Ws |
| near_timeout_ratio | outcomes with response_time_ms ≥ 0.8 × client_timeout_ms / outcomes (OC-214 leading indicator) | Ws |
| reject_ratio | (REJECTED_OVERLOAD + RETRY_LATER) / outcomes | Ws |
| p50_ms, p95_ms, p99_ms | completed-attempt response time quantiles | Ws |
| latency_ratio | p95 / baseline p95 | Ws |
| pending_count | payments currently PENDING_UNKNOWN or STATUS_CHECKING attributed to the segment of their latest attempt (maintained from events) | instant |
| pending_frac | pending_count / (arrival_rate × 60) | instant |
| queue_depth | mean PSP_SNAPSHOT queue (psp level; banks/routes inherit traffic-weighted) | Ws |
| queue_growth | least-squares slope of queue_depth over last 30 s, per s | 30 s |
| utilisation | active_workers / workers | Ws |
| queue_delay_est_ms | queue_depth / completions per s × 1 000 (Little's law) | Ws |
| orbit_proxy | payments with a CLIENT_TIMEOUT in the last 15 s not yet confirmed successful | 15 s |
| status_check_rate | STATUS_CHECK_SENT / s | Ws |
| switch_status_util | from SWITCH_SNAPSHOT: active / workers (switch level; others null) | Ws |
| load_over_capacity | arrival_rate / (workers / baseline mean service s) | Ws |
| ledger_open_rate | LEDGER_OPENED / s | Ws |
| ledger_unresolved | LEDGER_OPENED not yet LEDGER_RESOLVED | instant |

All ratios ∈ [0,1] except raf ≥ 1. NaN/None means "no information" and MUST NOT be treated as zero.

## 4. Baselines and detectors

### 4.1 Baselines
Per segment, per feature: EWMA mean (α = 0.02 per tick) and EWMA mean absolute deviation, floored per feature (`spread_floor` in config). Warm-up: first 120 s → `warming_up`, no alerts. **Freeze** while an incident is open on that segment (flag `baseline_frozen`). z = clip((x − mean)/spread, −6, 6).

### 4.2 Detectors (all run every tick)
| ID | Rule | Tuned knob |
|---|---|---|
| D0 | platform success_ratio(Wl) < θ0 for 2 consecutive ticks (mirrors typical dashboards) | θ0 |
| D1 | segment timeout_ratio > a or success_ratio < b for 2 ticks | one sensitivity scalar s scaling (a, b) |
| D2 | per-segment CUSUM on timeout_ratio and log(latency_ratio) vs own EWMA baseline | h |
| D3 | §4.3 | τ |

Fairness rule: each detector's knob is bisected on validation runs (S0 + S1 + pre-incident ticks) to **≤ 1 false alert per simulated hour** across all segments, frozen in `config/detectors_frozen.yaml` before any test run. Delay comparisons are only valid at this matched budget.

### 4.3 D3 pipeline
1. Eligibility: skip `warming_up`, `no_data`, `low_volume`.
2. Signals (booleans): `lat`: z(latency_ratio) ≥ 2.5 · `to`: timeout_ratio ≥ mean + 3·spread and ≥ 0.02 abs · `near_to`: near_timeout_ratio ≥ mean + 3·spread and ≥ 0.05 abs · `q`: queue_growth > 0 and queue_delay_est ≥ 1.5 × baseline · `raf`: raf ≥ 1.25 × baseline · `rej`: reject_ratio ≥ mean + 3·spread and ≥ 0.01.
3. **Surge gate:** SURGE (annotation, no alert) if z(arrival_rate) ≥ 2.5 and ≤ 1 signal true and queue_growth not > 0 for 2 consecutive ticks.
4. Score: **[PITCH]** rule score = (number of true signals)/6 mapped through a fixed logistic; **[BUILD]** IsolationForest (200 trees, max_samples 256) on the 8-feature vector `[log(arrival/baseline), timeout_ratio, near_timeout_ratio, reject_ratio, log(latency_ratio), raf, queue_growth/capacity, queue_delay_est/timeout]`, trained on normal windows only, score → empirical CDF of training scores.
5. Persistence: WARNING when score ≥ τ in 3 of last 4 ticks **and** ≥ 2 signals; fast path score ≥ 0.999 with ≥ 3 signals for 2 ticks.
6. Severity: CRITICAL when WARNING and the PSP's (or, for bank/route, the max over involved PSPs) forecaster p_stuck ≥ 0.5, or switch_status_util ≥ 0.95 for the switch segment.
7. Confidence = 0.4·score + 0.3·signals/6 + 0.2·persistence_fraction + 0.1·min(1, samples/200).
8. Reasons: top features by |z| → codes `TIMEOUT_UP, NEAR_TIMEOUT_UP, LATENCY_UP, RAF_UP, QUEUE_GROWING, REJECTS_UP, PENDING_BACKLOG, SWITCH_STATUS_SATURATED, LEDGER_UNRESOLVED_UP` with observed/baseline/z. Reasons are supporting evidence, not proof of cause; the UI says so.
9. Model failure or > 50 ms scoring twice → `model_degraded`, rule signals only, segment state DEGRADED_MONITORING.

## 5. Fault Localizer (involvement lift)

Inputs per tick over Ws: for every attempt outcome, `bad = 1` if CLIENT_TIMEOUT, REJECTED_OVERLOAD, RETRY_LATER, TECH_FAILED, or response > 1.5 × its route's baseline p95; `exp` = its route's baseline bad rate (floor 0.005).

```
N_bad  = Σ bad ;  N_exp = Σ exp ;  N_ex = max(0, N_bad − N_exp)
if N_ex < 20: INSUFFICIENT_EVIDENCE
# PSP dimension (each attempt belongs to exactly one PSP; shares sum to 1)
EP_psp[p]  = max(0, bad_p − exp_p) / Σ_p max(0, bad_p − exp_p)
# Bank dimension (an attempt involves 1 or 2 banks; use involvement, not shares)
IB[b]      = clip( max(0, bad_inv_b − exp_inv_b) / N_ex , 0, 1 )   # fraction of excess-bad attempts that involve b
base_inv[b]= baseline fraction of attempts involving b
lift[b]    = IB[b] − base_inv[b]
cell[p,b]  = max(0, bad_pb − exp_pb) / Σ cells       # route cells with the union rule
```

| Verdict | Condition (starting values; tune on validation) | Typical scenario |
|---|---|---|
| SWITCH_STATUS_OVERLOAD | switch_status_util ≥ 0.9 for 2 ticks and max EP_psp < 0.6 and max lift < 0.4 | S6 (switch loop), late S4 |
| BANK_SIDE(b*) | IB[b*] ≥ 0.75, lift[b*] ≥ 0.4, every other IB ≤ 0.5, max EP_psp < 0.6 | S3, S6 (early), S8 |
| PSP_SIDE(p*) | EP_psp[p*] ≥ 0.67, max lift < 0.3 | S2, S4 |
| ROUTE_SPECIFIC(p*, b*) | EP_psp[p*] ≥ 0.67, IB[b*] ≥ 0.75, cell[p*,b*] ≥ 0.4 | S7 |
| MULTI_FAULT | two banks with IB ≥ 0.6, or two PSPs with EP ≥ 0.35 and lift pattern not single | S5 |
| PLATFORM_WIDE | otherwise, with N_ex ≥ 20 | S1 overload, global |

Hysteresis: publish a new verdict only after it repeats on 2 consecutive ticks. Confidence = top score × min(1, N_ex/100). Candidates list: top 3 by share/lift with values. Runtime < 1 ms per tick.

## 6. Cascade Forecaster

### 6.1 Purpose and claim
Every tick, for each PSP: probability that the PSP's queue + retry backlog locks into a self-sustaining collapse **if nothing changes**, learned from simulation. It forecasts the cascade, not the onset, and never triggers actions; it raises severity, orders recommendations and draws the point-of-no-return map.

### 6.2 Labels (from M2 batch runs, U0, no actions)
- Stuck run: goodput over [trigger end + 60 s, + 120 s] < 50% of baseline.
- Collapse time t_c: first tick where queue_delay_est ≥ client timeout for 3 ticks.
- Samples: one per tick from trigger start to trigger end + 60 s, for the affected PSP (and every PSP in S6, where the switch couples them).

### 6.3 Dataset (`scripts/train_forecaster.py`)
Read `data/runs/*/events.jsonl` and `ground_truth.json` (training only). Recompute features with this module's own `features.py` (never trust M2's internals). Features: `delay_frac = queue_delay_est/timeout`, `orbit_frac = orbit_proxy/(capacity per s)`, `q_frac = queue_depth/q_max`, `load_ratio`, `raf`, `timeout_ratio`, `near_timeout_ratio`, `d_q`, `d_orbit` (15 s change), `switch_status_util`. Target 40–60% stuck runs by oversampling near the calibrated boundary. Split **by configuration** (all ticks of a run in one split): set A train, B validation, C test.

### 6.4 Models
1. **Grid (always first, [PITCH])**: 20×20 bins over delay_frac ∈ [0, 2] × orbit_frac ∈ [0, 3]; cell p = (stuck + 1)/(n + 2) (Beta(1,1)); enforce monotone non-decreasing along both axes by isotonic passes; export `data/models/forecaster_grid.json` with bin edges, matrix and the 0.5 contour polyline. Inference = two lookups.
2. **Ensemble ([BUILD])**: HistGradientBoostingClassifier (max_depth 6, ≤ 200 iterations) on all features, isotonic calibration on B. Keep only if it beats the grid on B in Brier score **and** AUC; the grid stays as explanation and fallback.

### 6.5 Runtime
EMA smoothing (weight 0.5) of p_stuck. States: CALM < 0.3 ≤ WATCH < 0.5 ≤ CRITICAL (thresholds tuned on B for best lead time at ≤ 1 false CRITICAL per simulated hour on S1, S5 and short non-sticking triggers). Countdown: when WATCH/CRITICAL, linear extrapolation of delay_frac over the last 4 ticks to 1.0 → `countdown_s_estimate`, labelled "rough estimate".

### 6.6 Fallback
If M2 reports that metastability did not reproduce, relabel to "queue delay ≥ timeout within the next 60 s", rename to **congestion forecaster** in code, API version string and UI text; the method stays.

## 7. Incident lifecycle

| State | Enter | Leave |
|---|---|---|
| OPEN | WARNING on a segment with no open incident | decision recorded (via M4 → visible as ACTION_APPLIED events) → MITIGATING; or severity rises |
| MITIGATING | first ACTION_APPLIED in scope | indicators improving 3 ticks → RECOVERING |
| RECOVERING | improving | 6 clean ticks → CLOSED; deterioration → MITIGATING |
| CLOSED | 6 clean ticks | new WARNING on same segment within 60 s reopens the same id |

Overlapping segments warned within 30 s merge into one incident; its primary segment comes from the localizer. D0 platform alerts are reported separately, never merged. Incident ids `inc-0001…` per run. `features_sha256` = SHA-256 of the canonical JSON of the triggering feature rows.

## 8. API (CONTRACTS §2) and modes

- Live: subscribe to `SIM_URL/v1/stream` (httpx-sse, `Last-Event-ID` resume); tick on event-time watermark crossing each 5 000 ms boundary; publish `tick` and `incident` SSE.
- Mock: replay `contracts/fixtures/payment_events.jsonl` + a recorded S3/S6 run when available; or serve recorded `ticks.jsonl` directly so M4/M5 can work on Day 1.
- Batch: `/v1/batch/reset`, `/v1/batch/tick` (stateless per run_id; keep one Pipeline per run_id, evict after reset).

## 9. Acceptance tests

| ID | Test | Tag |
|---|---|---|
| D-1 | Hand-built micro-streams: every feature equals the hand-computed value | PITCH |
| D-2 | Bucket edge: an event at an exact boundary lands in one bucket | PITCH |
| D-3 | Baseline freezes while an incident is open | PITCH |
| D-4 | Surge gate labels ≥ 95% of S1 surge ticks as SURGE on validation | PITCH |
| D-5 | One noisy tick never raises a WARNING | PITCH |
| D-6 | Localizer synthetic matrices: one hot PSP → PSP_SIDE; one hot bank (involved as remitter or beneficiary) → BANK_SIDE; one hot cell → ROUTE_SPECIFIC; switch util high + flat → SWITCH_STATUS_OVERLOAD; flat → PLATFORM_WIDE; Poisson noise does not flip a verdict in ≥ 95% of 1 000 trials | PITCH |
| D-7 | Grid monotone along both axes; inference < 1 ms; split integrity (no config in two splits) | PITCH |
| D-8 | Every published message validates against its schema | PITCH |
| D-9 | Cutting the input stream 12 s → DEGRADED_MONITORING within one tick | PITCH |
| D-10 | On S3 and S6 recorded runs, D3 alerts before D0 and names the right bank | PITCH (demo) |
| D-11 | Matched-budget tuning written to `detectors_frozen.yaml`; ablations R / M / RM | BUILD |

## 10. Day-by-day (pitch sprint)

| Day | Tasks | Gate |
|---|---|---|
| 1 | schema, ingest, segments, windows; mock tick stream from fixtures | `make run-mock` serves valid ticks |
| 2 | features + baselines + D0 + D3 rules + surge gate; localizer on synthetic matrices | D-1…D-6 |
| 3 | live subscription to M2; incidents; first grid trained on M2's quick S4/S6 runs | D-7, D-9; incidents flow to M4 |
| 4 | tune thresholds roughly on a few validation runs; `GET /v1/forecaster/grid`; detector race data for M5 | D-10 |
| 5 | freeze configs; record tick streams for the demo | — |

## 11. Pitfalls

1. Never treat a missing latency quantile as 0.
2. Bank involvement double-counts by design; never normalise IB to sum to 1.
3. Freeze baselines during incidents or the system learns the outage as normal.
4. Training reads ground truth; the live pipeline must not import anything from `scripts/`.
5. The forecaster is per PSP; S6 couples PSPs through the switch, so evaluate p_stuck for all PSPs there.

## 12. Agent prompt template

```
You are the M3 Detection agent for QueueShield. Read AGENTS.md, docs/00_PRODUCT.md, docs/01_SYSTEM.md,
contracts/CONTRACTS.md §2, §6 and docs/M3_DETECTION.md in full. Work only in detect/.
Task: <row of §10 or acceptance test of §9>. Tests first. Every threshold comes from config/detect.yaml.
No ground truth at inference. Report test results with the exact command.
```
