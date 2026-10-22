# QueueShield × Drunix — Upgrade Plan (`upgrade/argon`)

## Read-Only Pre-Check Verification

1. **`AGENTS.md`, `CLAUDE.md`, and `docs/DEVIATIONS.md` Compliance:**
   - **Zero cross-module imports (`AGENTS.md:8`):** Modules communicate exclusively over HTTP/SSE (`contracts/CONTRACTS.md`) or batch files under `data/`. Each Python module enforces this via `tests/test_isolation.py`.
   - **Read-only contracts & frozen v1.0 spec (`AGENTS.md:7`, `CLAUDE.md:17`):** `queueshield/contracts/` (schemas and fixtures) and `queueshield-spec/` are never edited directly; any proposed contract change goes into `queueshield/contracts/PROPOSALS/<date>-<module>-<slug>.md` while code uses existing schemas.
   - **Determinism & Safety Invariants (`AGENTS.md:16-24`):** All simulation/decision clocks use `sim_ms`; randomness uses seeded `PCG64` streams (`qsim/tape.py`); Go chaincode uses `GetTxTimestamp` and sorted keys (`advisory.go:114`); no PII/amounts/VPAs; claims policy enforced (`tests/claims.test.ts`).
   - **Deviation logging (`AGENTS.md:3, 15, 20`):** Every new pinned dependency or spec deviation is appended as a single line to `queueshield/docs/DEVIATIONS.md`.
2. **`m5_console/vite.config.ts` Dev Proxy Check:**
   - Inspected `queueshield/m5_console/vite.config.ts:1-9`:
     ```ts
     export default defineConfig({
       plugins: [react()],
       server: { port: 8000, host: "127.0.0.1", fs: { allow: [".."] } },
       test: { environment: "node", include: ["tests/**/*.test.ts"] },
     });
     ```
   - There is **no `server.proxy`** configured in `vite.config.ts`, and `m5_console/src/config.ts:3-6` connects directly from `:8000` to `http://localhost:8001` (M2), `http://localhost:8002` (M3), `http://localhost:8003` (M4), and `http://localhost:8004` (M1), while none of M1–M4 set `Access-Control-Allow-Origin` or `Access-Control-Allow-Headers: X-QS-Key, Content-Type, Last-Event-ID`. To keep changes minimal and confined to `m5_console/` (or via CORS middleware if preferred), this can be solved either by adding a Vite dev/preview proxy in `m5_console/vite.config.ts` or adding CORS headers on M1–M4.

---

## 1. Upgrade Inventory

Items are grouped into:
- **Group A:** P0 / Pitch Definition of Done (actionable now without Docker/live Drunix)
- **Group B:** P1 / P2 Build-Phase & Stretch (deferred per author's roadmap)
- **Group C:** Blocked (requires Docker/Drunix hardware) or Needs Author Decision
- **Group D:** Security & Integration Defect Fixes (optional cross-cutting work)

---

### Group A — P0 / Definition of Done Upgrades

#### A1. `M1-T02` — Compile, Vet, and Test Go Chaincode (`L2` Go Side)
- **Description:** Populate `go.sum` (`go mod tidy` / `go mod vendor` if needed) in `queueshield/m1_ledger/chaincode`, compile `paystate.go`, `advisory.go`, `errors.go`, `main.go` and `logic/`, run `go vet ./...`, run `go test ./...` against `testdata/transitions.json` (660 lines of golden vectors), and verify the determinism checklist (`m1_ledger/SPEC.md §4.5`).
- **Source & Quoted Acceptance Criteria (`queueshield/m1_ledger/ROADMAP.md:42-46`):**
  > "Set `go.mod`'s Go version and `fabric-contract-api-go` (v1.2.x for Go ≥ 1.20, v2 for ≥ 1.21) to match the ccenv Go; `go mod tidy && go mod vendor`; `go test ./logic/...` must pass every golden vector (the TS port already does). Fix whatever the compiler finds in `paystate.go` / `advisory.go` (they were written blind)."
  > "**Done when:** `go test ./logic/...` green; `go vet ./...` clean; deterministic checklist (SPEC §4.5) reviewed."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m1_ledger/chaincode/{go.mod, go.sum, paystate.go, advisory.go}`, `queueshield/m1_ledger/{STATUS.md, ROADMAP.md}`, `queueshield/docs/DEVIATIONS.md`.
- **Risk:** Low
- **Breaking-Change Impact:** None (preserves all contract function signatures and golden-vector transitions).
- **Test Strategy:** Run `go build ./...`, `go vet ./...`, `go test -v ./...` using `~/go-toolchain/bin/go`.
- **Effort Estimate:** S (~1 hour)

#### A2. `M2-T01` — Simulator Calibration (`scripts/calibrate.py` + `config/sim_default.yaml`)
- **Description:** Build `queueshield/m2_simulator/scripts/calibrate.py` to sweep S4 (`trigger size × duration`) and S6 (`hold fraction × duration`) across seeds in parallel (`multiprocessing.Pool`), evaluate the stuck criterion, tune `config/sim_default.yaml` levers in the author's prescribed order (`switch.status_workers` 4 → 8, 12; slowdown target leg vs PSP; `slowdown_alpha` 3.0 → 2.0; `slowdown_u0` 0.85 → 0.90), write `data/calibration/<scenario>.json` and heat maps `data/figures/F1_<scenario>.png` (or JSON/SVG if matplotlib is omitted), and log chosen parameters in `docs/DEVIATIONS.md`.
- **Source & Quoted Acceptance Criteria (`queueshield/m2_simulator/ROADMAP.md:30-52`, `SPEC.md §8.3`):**
  > "1. Write `scripts/calibrate.py`: `--scenario S4|S6`, grid of (trigger size × duration) from SPEC §8, `--seeds N`, runs `qsim.batch.run_one` in a `multiprocessing.Pool`, judges *stuck* = goodput over [end+60 s, end+120 s] < 50 % of the warm-up baseline (use `metrics.run_metrics` / `e.ts["goodput"]`), writes `data/calibration/<scenario>.json` and a heat map `data/figures/F1_<scenario>.png` (matplotlib optional; pin it if you add it)."
  > "3. Accept (SPEC §8.3) when, for some trigger size, a short trigger recovers in ≥ 80 % of seeds, a long one sticks in ≥ 80 %, and **U2 sticks less often than U0** at the stuck setting. Same for S6 hold fraction × duration."
  > "**Done when:** `python scripts/calibrate.py --scenario S4 --seeds 20` prints an accepted boundary; the two heat maps exist; `make test` still passes (S-7 must still show U0 S6 slowdown > 2)."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m2_simulator/scripts/calibrate.py` (new), `queueshield/m2_simulator/config/sim_default.yaml`, `queueshield/m2_simulator/qsim/engine.py` (if leg-only slowdown lever is required per step 2b), `queueshield/m2_simulator/{STATUS.md, ROADMAP.md}`, `queueshield/docs/DEVIATIONS.md`.
- **Risk:** Medium (changing `sim_default.yaml` affects simulation dynamics; all 16 existing M2 tests including S-4 and S-7 `slowdown > 2, util > 0.95` must continue to pass).
- **Breaking-Change Impact:** None to HTTP/JSON contracts; changes default simulation parameters in `config/sim_default.yaml` as explicitly required by `M2-T01`.
- **Test Strategy:** Unit test for calibration boundary judgement + run `calibrate.py --scenario S4 --seeds 20` and `--scenario S6 --seeds 20` + full M2 pytest suite.
- **Effort Estimate:** M (~3–4 hours)

#### A3. `M2-T02` — Live/Mock HTTP Ledger Bridge (`qsim/ledger_bridge.py`, Test `S-11`)
- **Description:** Implement `LedgerBridge` in `queueshield/m2_simulator/qsim/ledger_bridge.py` with a background worker thread, bounded queue, and `GET {LEDGER_URL}/v1/stream` subscriber (`Last-Event-ID`). Open unknowns via `POST {LEDGER_URL}/v1/payments`, attest legs via `POST /v1/payments/{txnRef}/attest` (backfilling legs that finished prior to open), and resolve payments in `U4` only when a terminal `PaymentUpdated` SSE event arrives. Expose `ledger_backlog` in `/v1/status` and fall back to `model` with `status: "degraded"` in `/v1/health` if the gateway is unreachable. Add `httpx-sse==0.4.3` to `m2_simulator/pyproject.toml` (already pinned in M3/M4) and log in `docs/DEVIATIONS.md`.
- **Source & Quoted Acceptance Criteria (`queueshield/m2_simulator/ROADMAP.md:56-70`, `SPEC.md §5, §12 S-11`):**
  > "in `qsim/ledger_bridge.py` implement a `LedgerBridge` with a background thread + bounded queue: `open(payment)` → `POST {LEDGER_URL}/v1/payments` (`ledger_open_request`: txnRef `<run_id>:<payment_id>`, `idemKeyHash` via `ids.idem_key_hash`, `simMs`), `attest(payment, kind)` → `POST /v1/payments/{txnRef}/attest` with the owning bank's kind; a subscriber thread on `GET {LEDGER_URL}/v1/stream` (httpx-sse, Last-Event-ID) that pushes terminal `PaymentUpdated` events back into the engine (thread-safe queue drained in `LiveRun._loop` under the engine lock)... Never drop a write silently: expose `ledger_backlog` in `/v1/status`; if the gateway is down fall back to `model` and report health `degraded` (SYSTEM §10)."
  > "**Done when:** a new test runs the engine against an in-process fake gateway (or the real M1 mock started by the test) and asserts S-11: unknowns opened, attested, and **no payment resolved without a terminal ledger event**; the integration smoke reports (e) PASS."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m2_simulator/qsim/{ledger_bridge.py, engine.py, live.py, api.py}`, `queueshield/m2_simulator/pyproject.toml`, `queueshield/m2_simulator/tests/test_ledger_bridge.py`, `queueshield/m2_simulator/{STATUS.md, ROADMAP.md}`, `queueshield/docs/DEVIATIONS.md`.
- **Risk:** Medium (concurrent HTTP/SSE thread interacting with `LiveRun._loop`; mitigated by draining terminal events under `LiveRun`'s lock).
- **Breaking-Change Impact:** None (`model` remains the default `LEDGER_MODE` for batch runs; `/v1/status` adds `ledger_backlog` only if allowed or internal to status object—note `CONTRACTS.md §1` does not forbid extra status fields as `/v1/status` has no strict schema file).
- **Test Strategy:** Add `test_s11_live_ledger_bridge` against M1 mock gateway + run `integration_smoke.py` verifying check `e_payment_success_on_ledger: PASS`.
- **Effort Estimate:** M (~3 hours)

#### A4. `M2-T03` — Arena Background Jobs + Lockstep Ledger Events (`S-10`)
- **Description:** Implement `POST /v1/arena` and `GET /v1/arena/{job_id}` in `queueshield/m2_simulator/qsim/api.py` to run background batch jobs across `scenario × seeds × universes` (using `DETECT_URL` and `CONTROL_URL` when set), forward `U4` in-sim ledger-model events (`PaymentUpdated`, etc.) to M4 in `qsim/batch.py:92` as `ledger_event` records, and write `data/runs/<run_id>/ticks.jsonl`.
- **Source & Quoted Acceptance Criteria (`queueshield/m2_simulator/ROADMAP.md:72-78`):**
  > "`POST /v1/arena` starts a background job over `batch.run_one` for scenario × seeds × universes (uses `DETECT_URL`/`CONTROL_URL` if set), `GET /v1/arena/{job_id}` reports progress. In `batch.py` forward the ledger-model events to M4 as `ledger_event` records in U4 (TODO marked in the code). Write `data/runs/<run_id>/ticks.jsonl`."
  > "**Done when:** `POST /v1/arena {"scenario":"S6","seeds":[1,2,3,4,5],"universes":["U0","U2","U4"]}` completes with M3 and M4 running and every `result.json` validates (`contracts.validate("run_result", ...)`); M5 can list them via `/v1/results`. Label numbers 'simulation, 5 seeds, preliminary'."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m2_simulator/qsim/{api.py, batch.py, engine.py}`, `queueshield/m2_simulator/tests/test_api.py`, `queueshield/m2_simulator/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low
- **Breaking-Change Impact:** None (replaces `503 UNAVAILABLE` stub on `POST /v1/arena` and `404` stub on `GET /v1/arena/{job_id}` with the contract-specified `202 {"job_id"}` and `{"state","done","total","run_ids":[...]}`).
- **Test Strategy:** API test for `POST /v1/arena` and `GET /v1/arena/{job_id}` + lockstep U4 ledger event forwarding test + schema validation on `result.json` and `ticks.jsonl`.
- **Effort Estimate:** S–M (~2 hours)

#### A5. `M2-T04` — Client & Engine Spec Gaps (`E_STATUS_STOP`, `SLOW_RETRIES` Advisory, `PACE_PAYOUTS`)
- **Description:**
  1. Add configurable `stop_codes: [E_STATUS_TIMEOUT, E_STATUS_OVERLOAD]` (or per `profiles.yaml`) for `npci_rule` clients so a status check returning a stop code transitions the payment to `ESCALATED_RECONCILE` instead of continuing status checks (`SPEC.md §4`).
  2. Make `ledger_first` (`U4`) clients obey active `SLOW_RETRIES` advisories (from the ledger stream in live mode / M4 lockstep advisories in batch).
  3. Enforce `PACE_PAYOUTS` in `qsim/engine.py:805` using a token bucket capping release rate of `PAYOUT` payments to `scope.bank` (`params.max_rate_per_s`).
- **Source & Quoted Acceptance Criteria (`queueshield/m2_simulator/ROADMAP.md:80-89`):**
  > "1. **`E_STATUS_STOP` codes** (SPEC §4 npci_rule 'stop on E_STATUS_STOP codes'; NPCI OC-215 bars further checks after errors such as connection timeout / no route to host): today npci_rule clients keep checking after `E_STATUS_TIMEOUT`/`E_STATUS_OVERLOAD`. Add a configurable stop-code list in `profiles.yaml`; on a stop code go to ESCALATED_RECONCILE. Re-run S-6/S-7."
  > "2. **SLOW_RETRIES advisory** (SPEC §4 ledger_first 'also obeys SLOW_RETRIES advisory'): ledger_first clients should honour active SLOW_RETRIES advisories from the ledger stream in live mode / from M4's lockstep advisories in batch."
  > "3. **PACE_PAYOUTS** enforcement (`apply_action` records it but nothing reads it): cap release rate of PAYOUT payments to that bank with a token bucket; test on S8."
  > "**Done when:** one test per item."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m2_simulator/config/profiles.yaml`, `queueshield/m2_simulator/qsim/{config.py, engine.py}`, `queueshield/m2_simulator/tests/test_engine.py`, `queueshield/m2_simulator/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low–Medium (must ensure `test_s6_si1_never_violated_by_npci_rule_clients` and `test_s7_switch_storm_under_u0_lower_under_u4` remain green).
- **Breaking-Change Impact:** None.
- **Test Strategy:** 3 dedicated unit tests in `tests/test_engine.py` (one per item) + re-run S-6 and S-7.
- **Effort Estimate:** S–M (~2 hours)

#### A6. `M2-T06` — Tests for Untested Simulator Paths
- **Description:** Add unit/integration tests covering: (1) `U1` textbook failover moving weight away from a degraded route and restoring it; (2) `SHIFT_TRAFFIC`, `CHECK_BUDGET`, `DEFER_CHECKS`, and `ROLLBACK` actions each changing engine behavior; (3) scenarios `S1, S2, S5, S7` running and emitting schema-valid events; (4) `SIM_MODE=mock` serving fixtures over `/v1/stream`.
- **Source & Quoted Acceptance Criteria (`queueshield/m2_simulator/ROADMAP.md:95-97`):**
  > "U1 textbook failover moves weight and restores it; SHIFT_TRAFFIC, CHECK_BUDGET, DEFER_CHECKS, ROLLBACK each change behaviour; S1, S2, S5, S7 run and validate; mock mode serves fixtures (`SIM_MODE=mock` TestClient + stream read)."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m2_simulator/tests/{test_engine.py, test_api.py}`, `queueshield/m2_simulator/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low (test-only additions unless a latent bug is uncovered).
- **Breaking-Change Impact:** None.
- **Test Strategy:** Run `.venv/bin/python -m pytest -q` in `m2_simulator`.
- **Effort Estimate:** S (~1.5 hours)

#### A7. `M2-T09` — Live Runner Wall-Clock Target Pacing
- **Description:** Update `LiveRun._loop` in `queueshield/m2_simulator/qsim/live.py` to advance simulation time toward `sim_target = t0_sim + (now - t0_wall) * speed` rather than a fixed 100 ms step per sleep, and report achieved speed in `/v1/status`.
- **Source & Quoted Acceptance Criteria (`queueshield/m2_simulator/ROADMAP.md:107-110`):**
  > "The live runner reaches ~1.7× wall clock at speed 4 because each 100 ms step costs compute. Advance to a wall-clock target (`sim_target = t0_sim + (now - t0_wall) * speed`) instead of a fixed step, and report the achieved speed in `/v1/status`."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m2_simulator/qsim/{live.py, api.py}`, `queueshield/m2_simulator/tests/test_api.py`, `queueshield/m2_simulator/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low
- **Breaking-Change Impact:** None.
- **Test Strategy:** Unit test verifying `LiveRun` advances to target sim time at `speed=4` and reports achieved speed in `/v1/status`.
- **Effort Estimate:** S (~1 hour)

#### A8. `M3-T01` — Train Forecaster Grid End-to-End (`scripts/train_forecaster.py` + `data/models/forecaster_grid.json`)
- **Description:** Extend `queueshield/m3_detection/scripts/train_forecaster.py` to split runs by configuration into disjoint seed sets `A` (1–999), `B` (1000–1999), and `C` (2000–2999), oversample near the stuck boundary to target 40–60% stuck runs, fit the 20×20 grid with both `monotone=True` and `monotone=False`, report AUC and Brier score on `B`, tune `WATCH`/`CRITICAL` thresholds on `B` for best lead time at `≤ 1` false CRITICAL per simulated hour on S1/S5 runs, and write `data/models/forecaster_grid.json` so `GET /v1/forecaster/grid` returns `200` and validates.
- **Source & Quoted Acceptance Criteria (`queueshield/m3_detection/ROADMAP.md:30-44`):**
  > "1. read every `data/runs/*-U0` with an incident; label stuck by the SPEC §6.2 rule (already implemented);
  > 2. split **by configuration** (all ticks of a run in one split) into A/B/C by seed range (A 1–999, B 1000–1999, C 2000–2999) — the split integrity check is part of D-7;
  > 3. aim for 40–60 % stuck runs (oversample near the boundary M2 found);
  > 4. fit with `monotone` on *and* off; report AUC and Brier on B for both...
  > 5. tune WATCH/CRITICAL thresholds on B for best lead time at ≤ 1 false CRITICAL per simulated hour on S1/S5 runs;
  > 6. write `data/models/forecaster_grid.json`; check `GET /v1/forecaster/grid` returns it and validates in shape.
  > **Done when:** a test that trains on a small synthetic dataset asserts the A/B/C split has no overlap; the real grid file exists; `make test` passes; a short note with AUC/Brier/lead time on B is in `STATUS.md`."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m3_detection/scripts/train_forecaster.py`, `queueshield/m3_detection/tests/test_detection.py`, `queueshield/m3_detection/{STATUS.md, ROADMAP.md}`, `queueshield/docs/DEVIATIONS.md`.
- **Risk:** Low
- **Breaking-Change Impact:** None (`GET /v1/forecaster/grid` transitions from `503` when untrained to `200` with schema-valid grid when `data/models/forecaster_grid.json` is present).
- **Test Strategy:** Unit test asserting A/B/C split integrity (`set(A) & set(B) == ∅`, etc.), monotonicity, and `/v1/forecaster/grid` response validation.
- **Effort Estimate:** M (~2.5 hours, runs after `M2-T01`)

#### A9. `M3-T02` — Single Incident per Bank Fault at Demo Rate
- **Description:** Fix incident lifecycle merging in `queueshield/m3_detection/qdet/lifecycle.py` (and/or `config/detect.yaml`) so that when the localizer verdict is `BANK_SIDE(b)` (or route warnings `route:*:b` open on a single bank fault at ~25 payments/s demo rate), route warnings `route:*:b` fold into a single `bank:*:b` incident instead of opening two separate route incidents and trailing recovery incidents (which we saw in the Phase 2 baseline smoke test: `rec-0001` through `rec-0005`).
- **Source & Quoted Acceptance Criteria (`queueshield/m3_detection/ROADMAP.md:46-55`):**
  > "**Seen in the 2026-10-20 smoke (S3, bank B1 slowed, ~25 payments/s demo rate):** two incidents opened on `route:P1:B1` and `route:P2:B1` before `bank:*:B1` warned, so M4 built two packages for one fault; small extra incidents appeared in the recovery tail.
  > **Steps:** add a regression test that replays a recorded live-rate stream... Options to evaluate: (a) when the localizer says BANK_SIDE(b) for ≥ 1 tick, route warnings `route:*:b` join the bank incident even if the bank segment has not warned yet; (b) raise `eligibility.route_min_attempts` at low rates; (c) require 2 signals on routes. Pick the one that keeps D-5/D-6/D-10 green.
  > **Done when:** the regression test shows exactly one incident for a single-bank fault at demo rate."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m3_detection/qdet/lifecycle.py`, `queueshield/m3_detection/config/detect.yaml`, `queueshield/m3_detection/tests/test_detection.py`, `queueshield/m3_detection/{STATUS.md, ROADMAP.md}`, `queueshield/docs/DEVIATIONS.md`.
- **Risk:** Low–Medium (must keep existing tests `D-5`, `D-6`, `D-10` green).
- **Breaking-Change Impact:** None.
- **Test Strategy:** Add demo-rate S3 single-bank fault regression test asserting `len(incidents) == 1` + run full M3 pytest suite + verify `integration_smoke.py`.
- **Effort Estimate:** S–M (~2 hours)

#### A10. `M3-T03`, `M3-T04`, `M3-T05`, `M3-T06` — M3 Threshold Tuning, Surge Gate Check, Detector Race, and Robustness Tests
- **Description:**
  - `M3-T03`: Add `scripts/tune_detectors.py` to bisect `D0` (`theta0`), `D1` (`sensitivity`), `D2` (`h`), and `D3` (`tau`) on validation runs (`S0 + S1 + pre-incident ticks`) to `≤ 1` false alert group per simulated hour and write `config/detectors_frozen.yaml`.
  - `M3-T04`: Measure share of S1 surge ticks labelled `SURGE` (target `≥ 95 %`) and record the honest figure in `m3_detection/STATUS.md` and `docs/DEVIATIONS.md`.
  - `M3-T05`: Verify `detector_alerts` carries distinct `D0–D3` `first_alert_sim_ms` on S4 and S6 runs.
  - `M3-T06`: Add watermark late-event test (event older than `2 s` delivered with `late=True`, counted, and placed in bucket if inside ring), duplicate `event_id` deduplication test, and `model_degraded` timing guard (`> 50 ms` twice sets `model_degraded` + `DEGRADED_MONITORING`, `SPEC.md §4.3 step 9`).
- **Source & Quoted Acceptance Criteria (`queueshield/m3_detection/ROADMAP.md:57-77`):**
  > `M3-T03`: "Bisect θ0 (D0), D1 `sensitivity`, D2 `h`, D3 `tau` on validation runs (S0 + S1 + pre-incident ticks) to ≤ 1 false alert group per simulated hour; write `config/detectors_frozen.yaml` (loaded automatically by `qdet/config.py`)."
  > `M3-T04`: "Measure the share of S1 surge ticks labelled SURGE (target ≥ 95 %)... Record the result honestly."
  > `M3-T05`: "Confirm `detector_alerts` carries D0–D3 first-alert times on S4 and S6 runs (M5's race needs four distinct flags on S4)."
  > `M3-T06`: "Late-event test for the watermark (an event older than 2 s is delivered with `late=True`, counted, and still lands in its bucket if inside the ring); dedupe test (same `event_id` twice → once). `model_degraded`: wrap scoring with a timer; > 50 ms twice → flag + DEGRADED_MONITORING (SPEC §4.3 step 9)."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m3_detection/qdet/pipeline.py`, `queueshield/m3_detection/scripts/tune_detectors.py` (new), `queueshield/m3_detection/config/detectors_frozen.yaml` (new), `queueshield/m3_detection/tests/test_detection.py`, `queueshield/m3_detection/{STATUS.md, ROADMAP.md}`, `queueshield/docs/DEVIATIONS.md`.
- **Risk:** Low
- **Breaking-Change Impact:** None.
- **Test Strategy:** Unit tests for late watermark, deduplication, `model_degraded` (>50 ms twice), and detector tuning script.
- **Effort Estimate:** M (~2.5 hours)

#### A11. `M4-T01` — Publish Ledger Tx & Block Number on M4 Decision Stream (`U-3`)
- **Description:** In `queueshield/m4_control/qctl/controller.py`, update `RunControl.on_ledger_event` so that when `DecisionRecorded` or `AdvisoryIssued` arrives from M1, M4 re-publishes `event: decision` on its SSE hub with `{rec_id, decision_id, ledger: {decision_tx, block_number, advisory_txs}}`, and include `decision_id` and `block_number` in the synchronous `POST /v1/decisions` response when the write succeeds immediately.
- **Source & Quoted Acceptance Criteria (`queueshield/m4_control/ROADMAP.md:27-33`):**
  > "**Why:** M5's DecisionLog must switch from 'recording on ledger…' to 'tx … · block …' within ≤ 2 s of the `DecisionRecorded` event.
  > **Steps:** in `RunControl.on_ledger_event`, when a `DecisionRecorded`/`AdvisoryIssued` arrives, publish `event: decision` again with `{rec_id, decision_id, ledger: {decision_tx, block_number, advisory_txs}}`; also include `decision_id` and `block_number` in the synchronous `POST /v1/decisions` response when the write succeeded.
  > **Done when:** a test feeds a fixture `DecisionRecorded` and asserts the published payload; M5 shows the tx id."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m4_control/qctl/{controller.py, ledger.py}`, `queueshield/m4_control/tests/test_control.py`, `queueshield/m4_control/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low
- **Breaking-Change Impact:** Additive fields (`decision_id`, `ledger.block_number`) on M4's `/v1/decisions` response and `decision` SSE event (which has no strict JSON Schema blocking those fields in `CONTRACTS.md §3`).
- **Test Strategy:** Unit test feeding a fixture `DecisionRecorded` event into `on_ledger_event` and asserting the published SSE `decision` payload contains `decision_tx` and `block_number`.
- **Effort Estimate:** S (~1 hour)

#### A12. `M4-T02` — Quieter Verification Budget Publication
- **Description:** Add `min_publish_interval_s: 30` under `governor` in `queueshield/m4_control/config/control.yaml` and `qctl/governor.py` / `qctl/controller.py` so `CHECK_BUDGET` actions are only emitted on the first tick, when `DEFER_CHECKS` is approved/rolled back, or when both `> 10 %` rate change AND `≥ min_publish_interval_s` have elapsed.
- **Source & Quoted Acceptance Criteria (`queueshield/m4_control/ROADMAP.md:35-38`):**
  > "**Seen:** 29 CHECK_BUDGET actions in 137 sim s at demo rate — noisy for M2's queue and the console.
  > **Steps:** add `governor.min_publish_interval_s` (e.g. 30) and keep the > 10 % change rule; always publish on the first tick and when a DEFER_CHECKS is approved/rolled back. SI-5 test must stay green; C-7 unchanged."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m4_control/config/control.yaml`, `queueshield/m4_control/qctl/{config.py, controller.py, governor.py}`, `queueshield/m4_control/tests/test_control.py`, `queueshield/m4_control/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low
- **Breaking-Change Impact:** None.
- **Test Strategy:** Unit test verifying budget publication interval gating + existing `test_c7_budget_bounds_and_monotonic` and `test_c2_safety_invariants_property`.
- **Effort Estimate:** S (~1 hour)

#### A13. `M4-T03`, `M4-T04`, `M4-T05` — Rollback Proposals & Advisory Revocation (`C-9`), Package Deduplication, and Operator Sweep Script
- **Description:**
  - `M4-T03`: Track applied actions in `RunControl`; after `rollback.clean_ticks` (`6`) consecutive clean (`NORMAL`) ticks on an applied action's scope while the incident is not already closed, emit a `PENDING` recommendation containing a single `ROLLBACK` action (`params.action_id`); when approved, enqueue `ROLLBACK` for M2 and call `DELETE /v1/advisories/{id}` (`ledger.revoke_advisory`) for each advisory produced by that action.
  - `M4-T04`: Defensive guard in `RunControl.on_incident`: if a new `BANK_SIDE` incident arrives for the same bank as an existing `PENDING` `BANK_SIDE` recommendation, supersede the older `PENDING` recommendation so the operator never sees two concurrent `PENDING` packages for the same bank fault.
  - `M4-T05`: Add `queueshield/m4_control/scripts/operator_sweep.py` to run S4 across operator approval delays `5, 15, 30, 60, 120 s` and print a recovery comparison table.
- **Source & Quoted Acceptance Criteria (`queueshield/m4_control/ROADMAP.md:40-56`):**
  > `M4-T03`: "track applied actions (from `/applied` acks or ACTION_APPLIED in ticks); after `rollback.clean_ticks` (6) clean ticks on the action's scope, create a recommendation with a single `ROLLBACK` action (`params.action_id`), status PENDING; on approval enqueue the ROLLBACK action for M2 and `DELETE /v1/advisories/{id}` for each advisory that action produced... **Done when:** C-9 test: proposal appears after 6 clean ticks, approval revokes the advisory (ModelLedger records it)."
  > `M4-T04`: "when two PENDING recommendations share verdict BANK_SIDE and the same bank, supersede the older one into the newer. Keep 'at most one PENDING per incident' (SPEC pitfall 3)."
  > `M4-T05`: "add a script `scripts/operator_sweep.py` that asks M2 for S4 arena runs at delays 5/15/30/60/120 s and tabulates recovery."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m4_control/qctl/{controller.py, ledger.py}`, `queueshield/m4_control/scripts/operator_sweep.py` (new), `queueshield/m4_control/tests/test_control.py`, `queueshield/m4_control/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low–Medium (must ensure `ROLLBACK` recommendation validates against `recommendation.schema.json` and `action.schema.json`).
- **Breaking-Change Impact:** None.
- **Test Strategy:** Add `test_c9_rollback_proposal_and_advisory_revocation` and `test_bank_side_supersedes_duplicate_pending` in `tests/test_control.py`.
- **Effort Estimate:** M (~2.5 hours)

#### A14. `M5-T01` & `M5-T02` — Console Header Status/Health Polling, Dev Proxy, and End-to-End Approve Flow (`U-1..U-4`)
- **Description:**
  - `M5-T01`: Poll M2 `/v1/status` every `1 s` (showing `scenario`, `seed`, `universe`, `sim_ms`, `speed`, `state`) and all four `/v1/health` endpoints in `m5_console/src/connect.ts` & `App.tsx`; add speed (`1x`/`2x`/`4x`), pause/resume, and reset controls in `ScenarioBar` (`SPEC.md §2`); configure Vite server proxy (or CORS) so browser requests succeed cleanly; verify `U-1` (loads with all services down showing `MOCK`/`offline` badges and zero console errors).
  - `M5-T02`: Update `DecisionLog` and `RecommendationCard` so approving a recommendation shows the row within `≤ 2 s` as `"recording on ledger…"` and updates to `"tx <id> · block <n>"` when M4 publishes the updated `decision` event (`M4-T01`) or `DecisionRecorded` arrives; add keyboard shortcuts `A` (approve all), `S` (approve selected), `R` (reject) when not typing in an input; ensure `config.ts` operators match `m4_control/config/operators.yaml`.
- **Source & Quoted Acceptance Criteria (`queueshield/m5_console/ROADMAP.md:32-42`, `SPEC.md §9`):**
  > `M5-T01`: "`npm run dev` with **no** services: every panel renders, badges say MOCK/offline, no console errors (U-1). `npm run dev` against `make run-mock` of M1–M4: ticks, the fixture recommendation and ledger events appear... Fix the Header: poll M2 `/v1/status` every 1 s (scenario, seed, universe, sim time, speed) and every `/v1/health`."
  > `M5-T02`: "Against M4 (mock or live): approve → DecisionLog row ≤ 2 s → 'recording on ledger…' → tx id + block when M4 re-publishes (M4-T01). Operator names from `config.ts` must match M4's `operators.yaml`. Keyboard: `A` approve all, `S` approve selected, `R` reject."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m5_console/src/{App.tsx, connect.ts, config.ts}`, `queueshield/m5_console/src/store/index.ts`, `queueshield/m5_console/src/panels/{RecommendationCard.tsx, LedgerPanels.tsx, decisionLogic.ts}`, `queueshield/m5_console/tests/decision.test.ts`, `queueshield/m5_console/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low
- **Breaking-Change Impact:** None.
- **Test Strategy:** Vitest unit tests (`tests/decision.test.ts`, `tests/claims.test.ts`), `npx tsc --noEmit`, `npm run build`.
- **Effort Estimate:** M (~2.5 hours)

#### A15. `M5-T03`, `M5-T04`, `M5-T05`, `M5-T06`, `M5-T07` — Replace Console Placeholder Panels (`MetricStrip`, `VerificationPanel`, `DetectorRace`, `CascadeMap`, `ArenaTab`, `SplitReplay`), Add Recorder/Replay (`U-6`), and Fix Smoke Port (`U-7`)
- **Description:**
  - `M5-T03`: Build `MetricStrip` (5 sparklines: `timeout_rate`, `near_timeout_rate`, `lat_p95_ms`, `raf`, `queue_len` for the selected segment with baseline band) and `VerificationPanel` (switch checks/s vs summed M4 `budget`, switch utilisation with `0.85` knee, unknown open vs resolved from M2 `/v1/timeseries` polled every `1 s`).
  - `M5-T04`: Build `DetectorRace` (4 horizontal lanes `D0–D3` with flags at `first_alert_sim_ms`; onset marker shown only in replay/arena mode, live shows `"onset unknown"`) and `CascadeMap` (20×20 heat background from `/v1/forecaster/grid`, `0.5` contour labelled `"point of no return"`, 60 s `phase_point` trail per PSP, countdown labelled `"rough estimate"`, falling back to axes + trails when grid is 503).
  - `M5-T05`: Implement `m5_console/scripts/record.mjs` (subscribes to all 4 streams and writes `data/recordings/<name>.jsonl` lines `{"stream","sim_ms","data"}`) and `m5_console/src/streams/replay.ts` (`?mode=replay&rec=<name>&speed=1|2|4` feeding the Zustand store deterministically so 1× and 4× produce the exact same final state, `U-6`).
  - `M5-T06`: Build `ArenaTab` (renders M2 `/v1/results` & timeseries for `U0 / U2 / U4` on shared axes + median metrics table labelled `"simulation, 5 seeds, preliminary"`, always showing `U2` next to `U4`) and `SplitReplay` (side-by-side S6 `U0` vs `U4` synchronised replay labelled `"replay of simulation runs"`).
  - `M5-T07`: Pass `"PORT": "8004"` explicitly in `m5_console/scripts/integration_smoke.py:44` (fixing the environment `PORT` collision discovered in Phase 2) and pass `"LEDGER_MODE": "mock"` / `"LEDGER_URL": "http://127.0.0.1:8004"` to M2 so check `(e)` runs end-to-end; verify `integration_smoke.py` passes twice in a row (`U-7`).
- **Source & Quoted Acceptance Criteria (`queueshield/m5_console/ROADMAP.md:43-68`, `SPEC.md §3, §9`):**
  > `M5-T03`: "VerificationPanel: switch checks/s vs summed budget (M4 `budget` events), switch utilisation with the 0.85 knee, unknown open vs resolved — from M2 `/v1/timeseries` polled every 1 s. S6 must spike under U0 and stay flat under U4. MetricStrip: 5 sparklines (timeout %, near-timeout %, p95, RAF, queue) for the selected segment with a baseline band (`z`/features from ticks)."
  > `M5-T04`: "DetectorRace: 4 lanes D0–D3 with a flag at `first_alert_sim_ms`; onset marker **only** in replay/arena (ground truth); live shows 'onset unknown'. CascadeMap: grid heat background from `/v1/forecaster/grid`, the 0.5 contour labelled 'point of no return', a 60 s trail per PSP from `phase_point`, countdown labelled 'rough estimate'. Until the grid exists, draw axes + trails only."
  > `M5-T05`: "`scripts/record.ts` (or `.mjs`): subscribe to all four streams during a live run and write `data/recordings/<name>.jsonl` lines `{"stream","sim_ms","data"}`. `src/streams/replay.ts`: `?mode=replay&rec=<name>&speed=1|2|4` feeds the same store; same final panel state at 1× and 4×."
  > `M5-T06`: "Split replay: two recordings (S6 U0 and U4, same seed) side by side, synchronised clock, label 'replay of simulation runs'. Arena tab: per scenario U0 / U2 / U4 lines (goodput, queue, switch checks) on shared axes + a metrics table with medians, labelled 'simulation, 5 seeds, preliminary'; U2 always shown next to U4 (honest baseline)."
  > `M5-T07`: "Run `../.venv/Scripts/python m5_console/scripts/integration_smoke.py` (from the repo root) twice in a row; fix what breaks."
- **Confidence:** High
- **Files & Modules Affected:** `queueshield/m5_console/src/panels/Placeholders.tsx` (or dedicated panel files imported into `App.tsx`), `queueshield/m5_console/src/streams/replay.ts` (new), `queueshield/m5_console/scripts/record.mjs` (new), `queueshield/m5_console/scripts/integration_smoke.py`, `queueshield/m5_console/tests/{replay.test.ts, claims.test.ts}`, `queueshield/m5_console/{STATUS.md, ROADMAP.md}`.
- **Risk:** Low–Medium (must ensure every new UI string passes `tests/claims.test.ts` forbidden-phrase lint).
- **Breaking-Change Impact:** None.
- **Test Strategy:** Unit test for `replay.ts` verifying identical final store state at `speed=1` and `speed=4` (`U-6`), claims lint test (`U-8`), `tsc --noEmit`, `vite build`, and running `integration_smoke.py` twice in a row (`U-7`).
- **Effort Estimate:** M–L (~4 hours)

---

### Group B — P1 / P2 Deferred Upgrades (Build Phase 10–22 Nov & Finale 4 Dec)

These tasks are explicitly tagged `[P1]` or `[P2]` in the module `ROADMAP.md` files for the post-pitch November build phase:

| Item | Task ID & Source | Description & Quoted Acceptance Target | Why Deferred |
|---|---|---|---|
| **B1** | `M2-T07` (`m2_simulator/ROADMAP.md:99-101`) | Compute `tat_breaches` ("debited, neither credited nor reversed within the TAT analogue; add `run.tat_analogue_ms` to config") and `harmful_failovers` ("arena: failover runs whose peak queue or recovery got worse than the paired U2 run"). | Tagged `[P1]` (Build phase). Can be included if requested. |
| **B2** | `M2-T08` (`m2_simulator/ROADMAP.md:103-105`) | Write `m2_simulator/scripts/make_configs.py` for disjoint seed sets A (1–999), B (1000–1999), C (2000–2999). | Tagged `[P1]`. |
| **B3** | `M2-T10` (`m2_simulator/ROADMAP.md:112-114`) | Replace placeholder `bank.td_rate` with five banks' technical-decline percentages from NPCI statistics and record month in `config/README.md`. | Tagged `[P1]`; requires external NPCI table lookup. |
| **B4** | `M2-T11` (`m2_simulator/ROADMAP.md:116-118`) | In lockstep, apply M4's first `CHECK_BUDGET` before the first unknown appears; keep `default_budget` only for M4-down live runs. | Tagged `[P1]`. |
| **B5** | `M3-T07` (`m3_detection/ROADMAP.md:79-81`) | Full matched-budget evaluation on set B, frozen before set C runs once; ablations R / M / RM. | Tagged `[P1]`. |
| **B6** | `M3-T08` (`m3_detection/ROADMAP.md:83-86`) | IsolationForest score (`qdet/detectors/iforest.py`): "200 trees, 8-feature vector... Ship the model only if it beats rules at the matched budget." | Tagged `[P1]`, first item on the spec's cut list (`PROJECT_ROADMAP.md:21`). |
| **B7** | `M3-T09` (`m3_detection/ROADMAP.md:88-90`) | `HistGradientBoosting` (depth ≤ 6, ≤ 200 iterations) + isotonic calibration ensemble forecaster. | Tagged `[P1]`. |
| **B8** | `M4-T06` & `M4-T07` (`m4_control/ROADMAP.md:58-66`) | Write contract proposals in `contracts/PROPOSALS/` for optional `payout_share` and `switch_status_capacity_per_s` segment features, then wire R3 `PACE_PAYOUTS` (`max_rate_per_s = 0.5 × spare, min 5/s`) and dynamic governor capacity. | Tagged `[P1]`; requires cross-owner contract change proposals (`AGENTS.md:7`). |
| **B9** | `M4-T08` (`m4_control/ROADMAP.md:68-69`) | Read-only regulator observer feed of decisions, advisories, and TAT breaches. | Tagged `[P1]`. |
| **B10** | `M1-T08..T11` (`m1_ledger/ROADMAP.md:77-90`) | Live YSQL TAT sweeper (`M1-T08`), Lite Peer scale-out benchmark (`M1-T09`), `checkpolicy` contract (`M1-T10`), private data `payPrivate` & Org3 (`M1-T11`). | Tagged `[P1]`/`[P2]` and require live Drunix Docker network. |

---

### Group C — Blocked or Needs Author Decision

| Item | Task ID & Source | Description & Quoted Criteria | Blocker / Decision Needed |
|---|---|---|---|
| **C1** | `M1-T01`, `M1-T03..T07` (`m1_ledger/ROADMAP.md:32-75`) | Bring up 11-container Drunix / Hyperledger Fabric + YugabyteDB network via `qs-net.sh`, implement `gateway/src/live/{fabric,events,readmodel,tat,ledger}.ts`, and run live benchmark (`bench/bench.ts`). | **Skipped per user instruction & author fallback (`PROJECT_ROADMAP.md:91`):** No Docker installed; stay on the deterministic M1 mock gateway (`LEDGER_MODE=mock`). |
| **C2** | `M2-T05` (`m2_simulator/ROADMAP.md:91-93, 133`, `DEVIATIONS.md:12`) | **S-4 Utilisation Target Decision:** *"S0 utilisation is P1 ≈ 0.58, P2 ≈ 0.51, P3 ≈ 0.37 because every PSP has 40 workers. Ask the lead: per-PSP or platform? If per-PSP, make `psp.workers` a list proportional to `psp_shares`. Update `test_s4_utilisation_and_littles_law`."* | **Needs Author Decision (see Open Question Q1):** Whether `0.50–0.60` normal utilisation in `SPEC.md §12 S-4` is per-PSP (workers `[46, 40, 29]` proportional to shares `0.40 / 0.35 / 0.25`) or platform mean (`~0.49–0.55`). |
| **C3** | `M5-T08` (`m5_console/ROADMAP.md:69-72`) | Record live stage rehearsal backup video and assemble pitch slide deck screenshots. | Human presenter task / external video capture. |

---

### Group D — Security & Cross-Cutting Defect Fixes (Optional, Separate from Author Roadmap)

#### D1. Remove Plaintext API Key from M2 Startup Log
- **Description:** In `queueshield/m2_simulator/qsim/api.py:58`, `jsonlog.warn("QS_API_KEY not set; generated a key for this process", key=self.key)` writes the generated secret API key in plaintext to stdout logs. Remove `key=self.key` so it matches `m3_detection/qdet/api.py:55` and `m4_control/qctl/api.py:50` (which never log `self.key`).
- **Files Affected:** `queueshield/m2_simulator/qsim/api.py:58`, `queueshield/m2_simulator/tests/test_api.py`.
- **Risk:** Low · **Effort:** XS (10 min).

#### D2. Validate `run_id` Against Path Traversal in M2 File Endpoints
- **Description:** In `queueshield/m2_simulator/qsim/api.py:180` (`GET /v1/timeseries?run_id=...`) and `qsim/api.py:194` (`GET /v1/results/{run_id}`), validate `run_id` against a strict regex (`^r-S[0-8]-[0-9]+-U[0-4](-[a-z0-9]+)?$`) and confirm `f.resolve().is_relative_to((st.data_dir / "runs").resolve())` before reading files from disk, returning `400 BAD_REQUEST` / `404 NOT_FOUND` on invalid input.
- **Files Affected:** `queueshield/m2_simulator/qsim/api.py:175-199`, `queueshield/m2_simulator/tests/test_api.py`.
- **Risk:** Low · **Effort:** XS (15 min).

#### D3. Cross-Origin Resource Sharing (CORS) / Vite Proxy for M5 Browser Console
- **Description:** Enable CORS headers on M1 (`m1_ledger/gateway/src/routes.ts`) and M2/M3/M4 (`qsim/api.py`, `qdet/api.py`, `qctl/api.py`) for `http://localhost:8000` and `http://127.0.0.1:8000` (allowing headers `X-QS-Key, Content-Type, Last-Event-ID` and methods `GET, POST, DELETE, OPTIONS`) so `m5_console` in a real browser can call `:8001–8004` directly without CORS errors.
- **Files Affected:** `m1_ledger/gateway/src/routes.ts`, `m2_simulator/qsim/api.py`, `m3_detection/qdet/api.py`, `m4_control/qctl/api.py`.
- **Risk:** Low · **Effort:** S (20 min).

---

## 2. Open Questions

1. **Q1 (`M2-T05` — S-4 Utilisation Target):** In `m2_simulator/config/sim_default.yaml`, all three PSPs currently have `40` workers despite traffic shares `[0.40, 0.35, 0.25]`, giving S0 utilisation `P1 ≈ 0.58, P2 ≈ 0.51, P3 ≈ 0.37`. Should we make `psp.workers` proportional to `psp_shares` (e.g., `[46, 40, 29]` so every PSP sits in `0.50–0.60` in S0 and `test_s4_utilisation_and_littles_law` asserts all 3 PSPs), or keep `workers: 40` as-is?
   - **Recommended Default:** Make `psp.workers` support a per-PSP list `[46, 40, 29]` proportional to `psp_shares` so all three PSPs satisfy the `0.50–0.60` S-4 spec target, and document it in `docs/DEVIATIONS.md`.
2. **Q2 (`M5-T01` — Playwright Dependency):** `m5_console/ROADMAP.md:35` mentions adding Playwright for panel snapshots (`U-2`), which requires downloading browser binaries and adding `@playwright/test` to `m5_console/package.json`. Should we keep `m5_console/package.json` free of new dependencies and test all panels via Vitest component/render tests, or add `@playwright/test`?
   - **Recommended Default:** Keep `m5_console/package.json` dependencies unchanged and test all panels and `U-1..U-8` invariants with Vitest tests (avoiding multi-hundred-MB browser downloads unless you want `@playwright/test` added).
3. **Q3 (`M4-T04` — Rejected Package Advisories):** `m4_control/ROADMAP.md:82` asks whether rejected packages should also write a `DO_NOT_SHIFT` advisory.
   - **Recommended Default:** Follow `m4_control/SPEC.md` (advisories are written only when a package is approved/partially approved, never on `REJECT`).

---

## 3. Recommended Execution Order (Group A + Approved D Items)

This sequence respects module dependencies (`PROJECT_ROADMAP.md:26-33`) and keeps all build, typecheck, and test suites green after every commit:

1. **Step 1 — Security & Hygiene Fixes (`D1`, `D2`, `D3`)** *(Python/TS — Low risk)*
   - Fix M2 API key logging (`D1`), `run_id` path validation (`D2`), and CORS headers (`D3`).
2. **Step 2 — Go Chaincode Verification (`A1 / M1-T02`)** *(Go — Low risk, independent)*
   - Run `go mod tidy` in `m1_ledger/chaincode`, fix any compiler/vet issues, verify `go build ./...`, `go vet ./...`, and `go test ./...`.
3. **Step 3 — M2 Client/Engine Spec Gaps, Pacing & Path Tests (`A5 / M2-T04`, `A7 / M2-T09`, `A6 / M2-T06`, plus `C2 / M2-T05` if approved)** *(Python `m2_simulator` — Low/Med risk)*
   - Implement `E_STATUS_STOP`, `SLOW_RETRIES` advisory handling in `U4`, and `PACE_PAYOUTS` token bucket (`M2-T04`), wall-clock target pacing (`M2-T09`), and tests for `U1`, all actions, scenarios `S1/S2/S5/S7`, and `SIM_MODE=mock` (`M2-T06`) before freezing calibration.
4. **Step 4 — M2 Calibration (`A2 / M2-T01`)** *(Python `m2_simulator` — Critical path for M3/M5)*
   - Build `scripts/calibrate.py`, sweep S4 and S6, update `config/sim_default.yaml` so short triggers recover `≥ 80%`, long triggers stick `≥ 80%`, and `U2` sticks less often than `U0`, while keeping all M2 tests (`S-1..S-9`) green.
5. **Step 5 — M2 Live/Mock HTTP Ledger Bridge & Arena (`A3 / M2-T02`, `A4 / M2-T03`)** *(Python `m2_simulator` — Enables DoD #2 and #5)*
   - Implement `LedgerBridge` (`S-11`) and `POST /v1/arena` + lockstep U4 ledger event forwarding (`S-10`).
6. **Step 6 — M3 Incident Lifecycle Fix, Robustness, Tuning & Forecaster Grid (`A9 / M3-T02`, `A10 / M3-T06,T03,T04,T05`, `A8 / M3-T01`)** *(Python `m3_detection` — Depends on Step 4)*
   - Fix single-bank fault route-incident splitting (`M3-T02`), add watermark/dedupe/`model_degraded` guard (`M3-T06`), run threshold tuning (`M3-T03`) & surge gate measurement (`M3-T04`), and train the forecaster grid (`M3-T01`) producing `data/models/forecaster_grid.json`.
7. **Step 7 — M4 Decision Stream Tx Status, Quieter Budgets & Rollback Proposals (`A11 / M4-T01`, `A12 / M4-T02`, `A13 / M4-T03,T04,T05`)** *(Python `m4_control`)*
   - Publish ledger `decision_tx` and `block_number` on M4's `decision` stream (`M4-T01`), add `min_publish_interval_s` (`M4-T02`), implement `ROLLBACK` proposals + advisory revocation after 6 clean ticks (`M4-T03`), duplicate `BANK_SIDE` package superseding (`M4-T04`), and `scripts/operator_sweep.py` (`M4-T05`).
8. **Step 8 — M5 Console Panels, Approve Flow, Recorder/Replay & End-to-End Smoke (`A14 / M5-T01,T02`, `A15 / M5-T03..T07`)** *(TypeScript `m5_console` — Depends on Steps 5, 6, 7)*
   - Update `Header` polling and `ScenarioBar`, wire `DecisionLog` tx/block updates and keyboard shortcuts `A/S/R` (`M5-T01, T02`), replace all 6 placeholder panels in `Placeholders.tsx` (`MetricStrip`, `VerificationPanel`, `DetectorRace`, `CascadeMap`, `ArenaTab`, `SplitReplay`), add `scripts/record.mjs` and `src/streams/replay.ts` (`M5-T05`), and run `integration_smoke.py` twice in a row with all checks `(a)–(e)` passing (`M5-T07`).

---

## 4. Rollback Strategy

- Every approved upgrade item (or tightly coupled sub-task) will be committed as its own atomic commit on `upgrade/argon` with a conventional commit message (`feat(m2): ...`, `fix(m3): ...`, etc.) after its module test suite passes.
- Any individual upgrade can be reverted cleanly via `git revert <commit-sha>` without affecting earlier steps.

---

## 5. What I Will NOT Do (and Why)

1. **Will NOT install Docker or run live Hyperledger Fabric / Drunix (`M1-T01, M1-T03..T07`):** Per your explicit instruction and the author's documented fallback (`PROJECT_ROADMAP.md:91`), all work stays on `LEDGER_MODE=mock`.
2. **Will NOT edit `requires-python` in any `pyproject.toml`:** Python 3.11.17 is installed in user space via `uv` with per-module `.venv` environments.
3. **Will NOT modify `queueshield/contracts/` schemas/fixtures or `queueshield-spec/`:** Both are read-only/frozen (`AGENTS.md:7`, `CLAUDE.md:17`).
4. **Will NOT introduce cross-module imports:** Preserves `AGENTS.md:8` and keeps `tests/test_isolation.py` green across M2, M3, and M4.
5. **Will NOT implement P1/P2 deferred items (`Group B`) unless you explicitly select them now.**
