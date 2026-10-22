# M3 Detection — roadmap: what is left, what to add, in what order

Written 2026-10-20 after reviewing the code, `SPEC.md`, the IBM reference results and outside research
(`../docs/RESEARCH.md`). Read `CLAUDE.md` first for how to work; this file says **what** to work on.

**Deadlines:** pitch **Sun 25 Oct** (**P0**) · build 10–22 Nov (**P1**) · finale 4 Dec (**P2**).

## 1. Where M3 stands

Working and tested (18 tests): ingest → windows → 23 features → baselines → D0/D1/D2/D3 → surge gate → persistence →
involvement-lift localizer → incident lifecycle → schema-valid `segment_state` ticks and `incident` events, in live
(SSE from M2), mock and batch modes. On a recorded S3 run D3 alerted before D0 and named the right bank; on S6 the
storm folds into one incident that moves PLATFORM_WIDE → SWITCH_STATUS_OVERLOAD.
**Missing for the pitch:** a trained forecaster grid (so incidents can go CRITICAL and the cascade map can draw the
point-of-no-return line), rough threshold tuning, and live-rate behaviour fixes seen in the integration smoke.

## 2. Who depends on you

| Consumer | Needs | Blocked today? |
|---|---|---|
| M4 | incidents with the right segment + verdict; severity CRITICAL from p_stuck | partly (no p_stuck) |
| M5 | `tick` stream, `detector_alerts` for the detector race, `/v1/forecaster/grid` + `phase_point` for the cascade map | grid endpoint returns 503 |
| M2 (arena) | `/v1/batch/*` | no |

You depend on **M2-T01 calibration** for training data. Until it lands, build the training pipeline on today's runs and
re-run it when M2 freezes.

## 3. Tasks

### M3-T01 · Train the forecaster grid end to end [P0, ~1 day; data after M2-T01]
- **Why:** SPEC §6; severity CRITICAL (§4.3 step 6), the cascade map and the countdown all depend on it.
- **Steps:** extend `scripts/train_forecaster.py`:
  1. read every `data/runs/*-U0` with an incident; label stuck by the SPEC §6.2 rule (already implemented);
  2. split **by configuration** (all ticks of a run in one split) into A/B/C by seed range (A 1–999, B 1000–1999,
     C 2000–2999) — the split integrity check is part of D-7;
  3. aim for 40–60 % stuck runs (oversample near the boundary M2 found);
  4. fit with `monotone` on *and* off; report AUC and Brier on B for both (IBM saw monotone smoothing drop AUC
     0.80 → 0.66–0.71); keep the spec's monotone grid unless the gap is large — record the numbers in `../docs/DEVIATIONS.md`;
  5. tune WATCH/CRITICAL thresholds on B for best lead time at ≤ 1 false CRITICAL per simulated hour on S1/S5 runs;
  6. write `data/models/forecaster_grid.json`; check `GET /v1/forecaster/grid` returns it and validates in shape.
- **Done when:** a test that trains on a small synthetic dataset asserts the A/B/C split has no overlap; the real grid
  file exists; `make test` passes; a short note with AUC/Brier/lead time on B is in `STATUS.md`.
- **Honesty:** the IBM forecaster had **no positive lead time against collapse**. Measure lead time to the stuck-judging
  window as well as to collapse, and say which one you report.

### M3-T02 · Live-rate incident behaviour [P0, ~0.5 day]
- **Seen in the 2026-10-20 smoke (S3, bank B1 slowed, ~25 payments/s demo rate):** two incidents opened on
  `route:P1:B1` and `route:P2:B1` before `bank:*:B1` warned, so M4 built two packages for one fault; small extra
  incidents appeared in the recovery tail.
- **Steps:** add a regression test that replays a recorded live-rate stream (record one with
  `python -m qsim.batch` and `demo_rate_factor` applied, or capture from the smoke). Options to evaluate:
  (a) when the localizer says BANK_SIDE(b) for ≥ 1 tick, route warnings `route:*:b` join the bank incident even if the
  bank segment has not warned yet; (b) raise `eligibility.route_min_attempts` at low rates; (c) require 2 signals on
  routes. Pick the one that keeps D-5/D-6/D-10 green.
- **Done when:** the regression test shows exactly one incident for a single-bank fault at demo rate.

### M3-T03 · Rough threshold tuning (D-11 lite) and `detectors_frozen.yaml` [P0, ~0.5 day]
- Bisect θ0 (D0), D1 `sensitivity`, D2 `h`, D3 `tau` on validation runs (S0 + S1 + pre-incident ticks) to ≤ 1 false
  alert group per simulated hour; write `config/detectors_frozen.yaml` (loaded automatically by `qdet/config.py`).
  Detector-delay comparisons are only valid at this matched budget — the detector race on the demo depends on it.
- Reuse the IBM evaluation approach (`../../OldReferenceAnalagousProject/IBM/scripts/tune_detectors.py`,
  `qs/eval/detection.py`: merged alert groups, overlapping segments within 30 s).

### M3-T04 · D-4 surge gate on S1 [P0, 2 h; needs M2 S1 runs]
- Measure the share of S1 surge ticks labelled SURGE (target ≥ 95 %). The IBM gate missed the 30–40 s after the flash
  because a real transient queue formed; M2 caps the flash at ρ ≤ 0.95 for that reason. Record the result honestly.

### M3-T05 · Detector race + recorded tick streams for the demo [P0, 2 h]
- Confirm `detector_alerts` carries D0–D3 first-alert times on S4 and S6 runs (M5's race needs four distinct flags on S4).
- Save tick streams of the demo runs to `data/recordings/` in M5's format (`{"stream":"detect","sim_ms","data"}`) or
  hand M5 the batch `ticks.jsonl` files.

### M3-T06 · Robustness items [P0, 2 h]
- Late-event test for the watermark (an event older than 2 s is delivered with `late=True`, counted, and still lands
  in its bucket if inside the ring); dedupe test (same `event_id` twice → once).
- `model_degraded`: wrap scoring with a timer; > 50 ms twice → flag + DEGRADED_MONITORING (SPEC §4.3 step 9). Cheap now,
  needed once a model exists.

### M3-T07 · Matched-budget evaluation + ablations (D-11 full) [P1]
- Full bisection on set B, frozen before set C runs once; ablations R (rules) / M (model) / RM; report missed incidents
  beside every delay (P1 hypothesis, `../docs/90_PLAN_EVAL_RISKS.md` §6).

### M3-T08 · IsolationForest score [P1, only if it earns its place]
- SPEC §4.3 step 4 [BUILD]: 200 trees, 8-feature vector, trained on normal windows, score → empirical CDF.
- **IBM evidence:** rules-only raised **fewer** false alerts than rules + IsolationForest on two held-out sets (4.24 vs
  1.61 and 5.95 vs 2.52 per hour) for ~5 s less delay. Ship the model only if it beats rules at the matched budget.

### M3-T09 · Ensemble forecaster [P1]
- HistGradientBoosting (depth ≤ 6, ≤ 200 iterations) + isotonic calibration on B; keep only if it beats the grid on
  Brier **and** AUC; the grid stays as the explanation (IBM: ensemble AUC 0.914 vs grid 0.773, but 3.2 ms vs < 1 ms).

## 4. Enhancements beyond the spec

| Idea | Why | Effort |
|---|---|---|
| **Analytic (CTMC/fluid) lock-in check** next to the learned grid: compare unknown inflow × checks/unknown with switch capacity and retry inflow with PSP capacity | an explainable second opinion grounded in recent work (arXiv 2510.03551 CTMC retry-storm models; Isaacs et al., HotOS 2025 combining queueing models + simulators); great judge answer to "why should we trust p_stuck?" | M |
| **Conformal interval on p_stuck** (split-conformal on set B) | show uncertainty instead of a bare number; cheap | S |
| **Onset estimate by change-point (CUSUM backtrack or BOCPD)** | better "detected N s after onset" numbers in the detector race without ground truth at runtime | S |
| **Ledger-aware signals** (`ledger_unresolved`, attestation lag per bank) feeding the localizer in U4 | the ledger tells you which bank has not attested — strong BANK_SIDE evidence unique to our design | M |
| **Per-bank forecaster for S6/S8** (credit holds at a beneficiary bank) | the spec forecaster is per PSP; S6's cause is a bank | M |
| **Plain-language incident summary** (template, no LLM) e.g. "Bank B1 slow on all PSPs; 3 signals; failover would spread it" | judges and operators read it in 2 s; keep claims-safe wording | S |

## 5. Open questions
1. Monotone vs unsmoothed grid if the AUC gap is large (spec says monotone)?
2. Should INSUFFICIENT_EVIDENCE bypass hysteresis (IBM did) — talk to M4 about stale accusations.
3. Rename to "congestion forecaster" if M2 cannot reproduce metastability honestly (SPEC §6.6).

## 6. This week

| Day | Do | Gate |
|---|---|---|
| Tue 20 | M3-T02 regression + fix; M3-T06 tests; pipeline for M3-T01 on current runs | one incident per bank fault at demo rate |
| Wed 21 | M3-T03 rough tuning on whatever runs exist | `detectors_frozen.yaml` v0 |
| Thu 22 | M3-T01 on M2's frozen runs; grid endpoint live | CascadeMap has data |
| Fri 23 | M3-T04, M3-T05; re-tune if M2 changed | detector race shows 4 flags on S4 |
| Sat 24 | freeze configs; record tick streams | — |
