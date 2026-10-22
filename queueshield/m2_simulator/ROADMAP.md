# M2 Simulator — roadmap: what is left, what to add, in what order

Written 2026-10-20 after a full review of the code, the spec (`SPEC.md`), the IBM reference project and outside research
(`../docs/RESEARCH.md`). Read `CLAUDE.md` first for how to work; this file says **what** to work on.

**Deadlines:** pitch submission **Sun 25 Oct 2026** (tasks tagged **P0**) · build phase 10–22 Nov (**P1**) · grand finale 4 Dec (**P2** = stretch).

## 1. Where M2 stands

Working and tested (16 tests): deterministic engine with remitter + beneficiary legs, the switch status service and its
slowdown coupling, all five universes, scenarios S0–S8, an in-sim ledger model for U4, batch runner writing
`data/runs/<run_id>/*`, live runner + HTTP/SSE API. A 600 s S3 run takes 8.4 s.
**The one thing that blocks everyone:** calibration. At spec defaults *every* S4 trigger locks the whole network for the
rest of the run under U0 **and** U2, so there is no recover-vs-stick boundary for M3 to learn and the arena would show
nothing but collapse. Fix this first.

## 2. Who depends on you

| Consumer | Needs from M2 | Blocked today? |
|---|---|---|
| M3 | calibrated U0 runs of S4/S6 with ~50 % stuck, plus S1 surge runs | **yes** (forecaster training, D-4, tuning) |
| M3/M4 | lockstep arena calls (`/v1/batch/*`) | no — endpoints exist on their side |
| M1 | live U4 traffic through the gateway to prove the ledger path | **yes** (M2-T02) |
| M5 | `/v1/timeseries`, `/v1/results`, S6 U0 vs U4 runs for the split replay | partly (needs T01, T03) |

## 3. Tasks

Each card: **why** → **steps** → **done when** (an exact, runnable check). Do them in this order unless the team lead says otherwise.

### M2-T01 · Calibrate so short triggers recover and long ones stick [P0, ~1 day, critical path]
- **Why:** SPEC §8 gate G-SIM. Diagnosis from 2026-10-20: with 165 payments/s and a status capacity of ~80 checks/s
  (4 workers × 50 ms), once more than ~27 payments/s go unknown, npci_rule's 3 checks each exceed the switch; the
  slowdown reaches ×4 on *every* PSP and every leg, so all PSPs time out and the loop never ends. Even a 20 s / 50 %
  worker loss on P1 sticks (seed 5, 300 s runs).
- **Steps:**
  1. Write `scripts/calibrate.py`: `--scenario S4|S6`, grid of (trigger size × duration) from SPEC §8, `--seeds N`, runs
     `qsim.batch.run_one` in a `multiprocessing.Pool`, judges *stuck* = goodput over [end+60 s, end+120 s] < 50 % of the
     warm-up baseline (use `metrics.run_metrics` / `e.ts["goodput"]`), writes `data/calibration/<scenario>.json` and a
     heat map `data/figures/F1_<scenario>.png` (matplotlib optional; pin it if you add it).
  2. Sweep the levers in this order, one at a time, re-running a small grid (3 seeds) after each change:
     a. **switch capacity** `switch.status_workers` 4 → 8, 12 (capacity 160–240/s). Most likely fix: today the switch
        cannot absorb even one PSP's unknowns.
     b. **where slowdown applies**: try applying `switch_slowdown` to the bank legs only, not PSP processing
        (`engine._try_start` multiplies `t_psp` by `self.slowdown`). Keep the coupling — it is the April-2025 mechanism.
     c. `slowdown_alpha` 3.0 → 2.0, `slowdown_u0` 0.85 → 0.9.
     d. then SPEC §8 step 4 (client timeout, utilisation, naive check frequency, `q_max`).
  3. Accept (SPEC §8.3) when, for some trigger size, a short trigger recovers in ≥ 80 % of seeds, a long one sticks in
     ≥ 80 %, and **U2 sticks less often than U0** at the stuck setting. Same for S6 hold fraction × duration.
  4. Freeze `config/sim_default.yaml`, tag `sim-frozen`, append the chosen values and the reason to `../docs/DEVIATIONS.md`.
  5. If metastability never appears with honest settings: follow SPEC §8.6 — say "congestion", tell M3 (forecaster rename).
- **Done when:** `python scripts/calibrate.py --scenario S4 --seeds 20` prints an accepted boundary; the two heat maps exist;
  `make test` still passes (S-7 must still show U0 S6 slowdown > 2).
- **Tip:** the CTMC models in *Formal Analysis of Metastable Failures* (arXiv 2510.03551) give a back-of-envelope check of
  where the bistable region is: unknowns/s × checks per unknown vs switch capacity.

### M2-T02 · Live ledger bridge, `LEDGER_MODE=mock|live` (S-11) [P0, ~1 day]
- **Why:** the demo's headline is "banks attest once, PSPs are pushed the answer". Today U4 live uses the in-sim model, so
  zero payments reach M1 (integration smoke check (e) is SKIPPED).
- **Steps:** in `qsim/ledger_bridge.py` implement a `LedgerBridge` with a background thread + bounded queue:
  `open(payment)` → `POST {LEDGER_URL}/v1/payments` (`ledger_open_request`: txnRef `<run_id>:<payment_id>`,
  `idemKeyHash` via `ids.idem_key_hash`, `simMs`), `attest(payment, kind)` → `POST /v1/payments/{txnRef}/attest` with the
  owning bank's kind; a subscriber thread on `GET {LEDGER_URL}/v1/stream` (httpx-sse, Last-Event-ID) that pushes terminal
  `PaymentUpdated` events back into the engine (thread-safe queue drained in `LiveRun._loop` under the engine lock).
  In the engine, replace the model hooks (`_h_ledger_open`, `_truth_changed`, `_h_ledger_resolve`) with calls through a
  small interface so `model` stays the batch default. Banks backfill legs that completed before the open (SPEC §5).
  Never drop a write silently: expose `ledger_backlog` in `/v1/status`; if the gateway is down fall back to `model`
  and report health `degraded` (SYSTEM §10).
- **Done when:** a new test runs the engine against an in-process fake gateway (or the real M1 mock started by the test)
  and asserts S-11: unknowns opened, attested, and **no payment resolved without a terminal ledger event**; the
  integration smoke reports (e) PASS.

### M2-T03 · Arena jobs + lockstep through M3/M4 (S-10) [P0, ~0.5 day]
- **Steps:** `POST /v1/arena` starts a background job over `batch.run_one` for scenario × seeds × universes (uses
  `DETECT_URL`/`CONTROL_URL` if set), `GET /v1/arena/{job_id}` reports progress. In `batch.py` forward the ledger-model
  events to M4 as `ledger_event` records in U4 (TODO marked in the code). Write `data/runs/<run_id>/ticks.jsonl`.
- **Done when:** `POST /v1/arena {"scenario":"S6","seeds":[1,2,3,4,5],"universes":["U0","U2","U4"]}` completes with M3
  and M4 running and every `result.json` validates (`contracts.validate("run_result", ...)`); M5 can list them via
  `/v1/results`. Label numbers "simulation, 5 seeds, preliminary".

### M2-T04 · Close the spec gaps in client behaviour [P0, ~0.5 day]
1. **`E_STATUS_STOP` codes** (SPEC §4 npci_rule "stop on E_STATUS_STOP codes"; NPCI OC-215 bars further checks after
   errors such as connection timeout / no route to host): today npci_rule clients keep checking after
   `E_STATUS_TIMEOUT`/`E_STATUS_OVERLOAD`. Add a configurable stop-code list in `profiles.yaml`; on a stop code go to
   ESCALATED_RECONCILE. Re-run S-6/S-7.
2. **SLOW_RETRIES advisory** (SPEC §4 ledger_first "also obeys SLOW_RETRIES advisory"): ledger_first clients should
   honour active SLOW_RETRIES advisories from the ledger stream in live mode / from M4's lockstep advisories in batch.
3. **PACE_PAYOUTS** enforcement (`apply_action` records it but nothing reads it): cap release rate of PAYOUT payments
   to that bank with a token bucket; test on S8.
- **Done when:** one test per item.

### M2-T05 · Decide and test the S-4 utilisation target [P0, 1 h]
- S0 utilisation is P1 ≈ 0.58, P2 ≈ 0.51, P3 ≈ 0.37 because every PSP has 40 workers. Ask the lead: per-PSP or platform?
  If per-PSP, make `psp.workers` a list proportional to `psp_shares`. Update `test_s4_utilisation_and_littles_law`.

### M2-T06 · Tests for the untested paths [P0, ~0.5 day]
- U1 textbook failover moves weight and restores it; SHIFT_TRAFFIC, CHECK_BUDGET, DEFER_CHECKS, ROLLBACK each change
  behaviour; S1, S2, S5, S7 run and validate; mock mode serves fixtures (`SIM_MODE=mock` TestClient + stream read).

### M2-T07 · Missing metrics [P1]
- `tat_breaches` (debited, neither credited nor reversed within the TAT analogue; add `run.tat_analogue_ms` to config),
  `harmful_failovers` (arena: failover runs whose peak queue or recovery got worse than the paired U2 run).

### M2-T08 · Configuration sets A/B/C (`scripts/make_configs.py`) [P1]
- Disjoint seed ranges (A 1–999 train, B 1000–1999 validation, C 2000–2999 test) and parameter draws per SPEC §7; the
  IBM project's `scripts/make_configs.py` is a good template (`../../OldReferenceAnalagousProject/IBM/scripts/`).

### M2-T09 · Live pacing and demo traffic [P0, 2 h]
- The live runner reaches ~1.7× wall clock at speed 4 because each 100 ms step costs compute. Advance to a wall-clock
  target (`sim_target = t0_sim + (now - t0_wall) * speed`) instead of a fixed step, and report the achieved speed in
  `/v1/status`. Re-check `demo_rate_factor` against M1's measured throughput (`data/ledger_bench.json`).

### M2-T10 · Real NPCI decline rates [P1]
- Replace placeholder `bank.td_rate` with five banks' technical-decline percentages from NPCI's published statistics
  (E9); record bank names and month in `config/README.md`.

### M2-T11 · Remove the `default_budget` placeholder [P1]
- Governed clients currently use rate 10/s until M4 publishes. In lockstep, apply M4's first CHECK_BUDGET before the first
  unknown appears (M4 publishes on the first tick); keep the fallback only for M4-down live runs (SYSTEM §10).

## 4. Enhancements beyond the spec (pick after the P0s; each is a pitch talking point)

| Idea | Why it matters | Effort | Note |
|---|---|---|---|
| **Peak-hour demand curve** (10:00–13:00, 17:00–21:30 per NPCI) and a "non-customer-initiated APIs restricted at peak" client rule | Mirrors NPCI's 2025 peak-hour guidance; makes surge scenarios realistic | S | config only |
| **Revised first-check timer variant** (45–60 s instead of 90 s, per later NPCI communication) as a U2b universe | Shows QueueShield still helps under the newer rule | S | new universe id needs a contract proposal; or run as U2 with overrides |
| **Bank-side capacity** (finite bank workers, not just latency multipliers) | Makes S3/S8 bank overload emerge from load rather than be injected | M | recalibrate after |
| **Adaptive LIFO / CoDel at the PSP queue** as a new action | Facebook/HBase pattern: serve newest first under overload so fresh payments beat doomed ones | M | needs `ADAPTIVE_LIFO` in `action.schema.json` (contract proposal) and an M4 rule |
| **Per-client retry budget** (≤ 10 % retry ratio, Google SRE) as a governed-client feature | A standard, citable retry-storm mitigation to compare against | S | |
| **"Money is with …" custody field** on LEDGER events | Pulse (a competitor) shows custody to users; we can add it cheaply to our console | S | M1 already stores per-leg attestations |
| Numba/vectorised hot loop | only if arena runs at ≥ 20 configs per cell are too slow | M | measure first |

## 5. Open questions for the M2 owner / team
1. Per-PSP or platform-mean utilisation (M2-T05)?
2. After calibration, is the network-wide lock under U0 still the story we tell for S6 (April-2025 replay)? It should be — but U2 must recover more often than U0.
3. Will the demo show live U4 against real Drunix (needs M2-T02 + M1 live) or against the M1 mock? Decide by Thu.

## 6. This week (pitch sprint)

| Day | Do | Gate |
|---|---|---|
| Tue 20 | M2-T01 sweeps start (switch capacity first); M2-T05 decision | first stuck heat map |
| Wed 21 | finish M2-T01, freeze; hand M3 a batch of U0 S4/S6 runs | `sim-frozen` tag; M3 can train |
| Thu 22 | M2-T02 live ledger bridge against M1 mock; M2-T09 pacing | integration smoke (e) PASS |
| Fri 23 | M2-T03 arena U0/U2/U4 × S6 × 5 seeds; M2-T04; M2-T06 tests | preliminary arena numbers for M5 |
| Sat 24 | freeze; run the demo scenarios for M5's recordings | two clean rehearsals |
