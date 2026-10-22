# M2 — Simulator: reactive UPI-like network, scenarios, universes and arena

**Owner folder:** `sim/` · **Port:** 8001 · **Stack:** Python 3.11, NumPy, FastAPI, uvicorn, sse-starlette, httpx, pydantic v2, jsonschema · **Talks to:** M3 (its stream is read by M3; drives M3 in lockstep), M4 (polls actions; drives M4 in lockstep), M1 (opens unknowns and attests in live U4), M5 (scenario commands, stream, results).

Your job: a deterministic discrete-event model of a small UPI-like network in which **actions really change what happens next**. It must reproduce the April 2025 failure loop (timeouts → status checks and retries → switch saturation → slower payments → more timeouts) and let us replay the same random tape under five universes. It owns ground truth and the arena.

This is a qualitative model for comparing policies on identical traffic, calibrated to public NPCI figures. Every report and UI label says so.

---

## 1. Folder layout

```
sim/
├── Makefile                 run, run-mock, test, calibrate, arena-small
├── pyproject.toml           pinned deps
├── config/
│   ├── sim_default.yaml     §9 defaults; frozen after calibration (tag sim-frozen)
│   ├── profiles.yaml        client profiles §4
│   └── scenarios.yaml       §7 parameter ranges
├── qsim/
│   ├── schema.py            pydantic models generated from contracts/schemas (do not hand-edit enums)
│   ├── engine.py            heapq event loop
│   ├── tape.py              random tape (common random numbers)
│   ├── entities.py          Psp, Bank, Switch, Payment, Attempt
│   ├── clients.py           client profiles and retry/check logic
│   ├── banks.py             legs, declines, black holes, attestations
│   ├── switch.py            status service + slowdown coupling
│   ├── controls.py          action application
│   ├── ledger_bridge.py     live (HTTP to M1), model (in-sim latency model)
│   ├── scenarios.py         S0–S8 triggers
│   ├── metrics.py           run metrics, time series, duplicates
│   ├── emit.py              event construction + schema validation + SSE ring
│   ├── live.py              wall-clock runner, action polling
│   ├── batch.py             lockstep runner and arena
│   └── api.py               FastAPI routes per CONTRACTS §1
├── scripts/
│   ├── calibrate.py         metastability sweeps §8
│   └── make_configs.py      configuration sets A/B/C
└── tests/
```

## 2. Topology and entities

| Entity | Count | Key state |
|---|---|---|
| PSP (payer PSP route) | P1, P2, P3 | `workers` c, `active`, FIFO queue (bounded `q_max`), routing weight, controls (throttle bucket, shed_expired, fresh_first), per-PSP check token bucket |
| Bank | B1–B5 | traffic shares, latency multiplier per leg, technical-decline rate, black-hole state (S6), attestation behaviour |
| Switch | 1 | status service: `status_workers`, status queue (bounded), service time; **slowdown factor** applied to every payment leg |
| Payment | many | payer PSP, remitter bank, beneficiary bank, kind (P2P/P2M/PAYOUT), idempotency key, attempts, platform state, ground truth (debited? credited? reversed?) |
| Attempt | per payment | attempt_no, enqueue time, service start, legs, outcome, whether client still waiting |
| Client | one per payment | profile, timers, pending status checks, retry count |

### 2.1 Service path of one attempt

1. **Routing:** pick a PSP by current routing weights (default: the payment's home PSP drawn at arrival by PSP shares; SHIFT_TRAFFIC changes weights for *new attempts only*).
2. **PSP queue:** if the queue is full → `REJECTED_OVERLOAD` after 5 ms. Otherwise wait for a worker (FIFO; `fresh_first` gives fresh attempts priority with a 2 s starvation guard; `shed_expired` drops a queued attempt whose client already timed out, costing 1 ms, ending as a definitive non-commit).
3. **PSP processing:** `t_psp ~ LogNormal(mean 60 ms, CV 0.5) × psp_multiplier(t) × switch_slowdown(t)`.
4. **Remitter leg (debit):** `t_rem ~ LogNormal(150 ms, 0.6) × bank_mult[remitter](t) × switch_slowdown(t)`. At its end: business decline with prob `bd_rate` (2%) → `DECLINED` (no debit); technical decline with prob `td_rate[remitter]` → `TECH_FAILED` (no debit); otherwise **debit committed** (ground truth).
5. **Beneficiary leg (credit):** `t_ben ~ LogNormal(150 ms, 0.6) × bank_mult[beneficiary](t) × switch_slowdown(t)`. At its end: technical decline with prob `td_rate[beneficiary]` → credit fails, **auto-reversal** scheduled after `reversal_delay_ms` (default 20 000); black-hole (S6) → credit **held** until the scenario's resolve time, then credit (70%) or failure + reversal (30%); otherwise **credit committed** → payment succeeded.
6. The PSP worker is held for the whole path (steps 3–5). This is how a slow bank produces PSP-side symptoms on every PSP that routes to it.
7. **Client timeout** `T = 3 000 ms` from send: if the outcome has not reached the client, the client records `CLIENT_TIMEOUT` and the platform state becomes UNKNOWN. The attempt is **not cancelled**: it continues (zombie work) and may still debit and credit later.

### 2.2 Switch status service and the slowdown coupling (the April 2025 mechanism)

- Status checks queue at the switch: `status_workers = 4`, service time `LogNormal(50 ms, 0.4)`, so capacity ≈ 80 checks/s; queue bound 2 000 (overflow → check returns `UNKNOWN` with error `E_STATUS_OVERLOAD` after 5 ms).
- Each check, when served, also adds `status_bank_cost_ms = 20` of latency debt to the involved beneficiary bank's next 1 s of legs (status lookups hit the bank too).
- Switch utilisation `u_s` = busy status workers / workers, smoothed over 1 s. **Slowdown factor** applied to all legs and PSP processing:

  `switch_slowdown(t) = 1 + α · max(0, u_s(t) − u0) / (1 − u0)`, with `α = 3.0`, `u0 = 0.85`.

  At full status saturation every payment slows ×4. This modelling assumption is what lets a status storm become network-wide, as NPCI described. It is a parameter; the calibration in §8 must show the loop exists, and the report must state the assumption.
- A status check answers from ground truth: `CONFIRMED_SUCCESS` if credited; `CONFIRMED_FAILED` if no debit, or debit reversed; `UNKNOWN` if any attempt is still in flight, held, or awaiting reversal. Response is subject to a 2 000 ms status timeout (OC-214 analogue): if not served by then → `UNKNOWN` with `E_STATUS_TIMEOUT`.

## 3. Platform payment state (what M3 can observe)

`INITIATED → IN_FLIGHT → {CONFIRMED_SUCCESS | CONFIRMED_FAILED | PENDING_UNKNOWN}`; `PENDING_UNKNOWN → STATUS_CHECKING → {CONFIRMED_SUCCESS | CONFIRMED_FAILED | PENDING_UNKNOWN | ESCALATED_RECONCILE}`; in U4 also `PENDING_UNKNOWN → LEDGER_RESOLVED(...)`. `CONFIRMED_FAILED` may lead to a retry (new attempt, same idempotency key) within the attempt cap, otherwise `ABANDONED`. `PAYMENT_CLOSED` is emitted exactly once per payment.

**Duplicate commit (ground truth, evaluator only):** a payment with more than one attempt that was both debited and credited. Count = attempts credited − 1 when > 0.

**SI-1 (enforced in governed profiles, measured in naive ones):** no new attempt while the payment is PENDING_UNKNOWN, STATUS_CHECKING or ESCALATED_RECONCILE.

## 4. Client profiles

| Profile | Universe | On CLIENT_TIMEOUT | Status checks | Retries | Idempotency |
|---|---|---|---|---|---|
| `naive` | U0, U1 | user retries with prob 0.5 after U(2 000, 6 000) ms **without waiting for status** (duplicate-prone); app also polls | every 2 000 ms until resolved, max 30 | on any non-success, U(500, 2 000) ms, cap 3 attempts | none (gateway cannot dedupe) |
| `npci_rule` | U2 | wait | first at 10 000 ms, then +15 000, +25 000 (≤3 within 120 000 ms); stop on `E_STATUS_STOP` codes; then ESCALATED_RECONCILE | only after CONFIRMED_FAILED, full-jitter exponential (base 1 000, cap 16 000), cap 3 | key reused; PSP dedupes |
| `governed` | U3 | wait | as npci_rule **but released by the per-PSP CHECK_BUDGET token bucket** from M4 (oldest first) | as npci_rule; also obeys THROTTLE_RETRIES | key reused |
| `ledger_first` | U4 | open on ledger (`POST /v1/payments` or model), subscribe | only if no ledger resolution within `ledger_wait_ms` (default 10 000), then as governed | as governed; also obeys SLOW_RETRIES advisory | key reused |

In U1 the population is naive and a **textbook failover** rule runs inside M2: if a PSP's 10 s success ratio < 0.90 for 2 ticks, move its weight evenly to the others; restore when > 0.97 for 3 ticks.

In U3 and U4 the client population is **70% governed/ledger_first and 30% naive**: operators cannot rewrite every app (configurable `naive_share`).

## 5. Banks and attestations (U4)

When `LEDGER_MODE` is `live` or `mock` (live run) or `model` (batch), banks attest the legs of **unknown** payments only (payments that never became unknown never touch the ledger):

| Ground-truth event on an unknown payment | Attestation | Submitted as |
|---|---|---|
| Debit committed | DEBIT | remitter side (Org1) |
| Remitter business/technical decline | FAILURE_REMITTER | Org1 |
| Credit committed | CREDIT | payee side (Org2) |
| Credit failed | FAILURE_BENEFICIARY | Org2 |
| Reversal completed | REVERSAL | Org2 |

If a leg completed **before** the payment became unknown, the attestation is sent immediately after OpenUnknown (banks backfill). Attestation submission latency: live = real gateway; model = `LogNormal` fitted to `data/ledger_bench.json` (default p50 120 ms, p95 400 ms) plus event lag (default p50 50 ms). The PSP client resolves the payment when it receives a `PaymentUpdated` event with a terminal state (SUCCESS → CONFIRMED_SUCCESS; FAILED_NO_DEBIT or REVERSED → CONFIRMED_FAILED; DISPUTED → ESCALATED_RECONCILE) and emits `LEDGER_RESOLVED`.

## 6. Actions the simulator applies (from M4 `/v1/actions/pending` or lockstep)

| action_type | Scope | Params | Effect in the simulator |
|---|---|---|---|
| THROTTLE_RETRIES | psp or bank | `rate_fraction` (of the segment's fresh rate), `retry_after_ms:[lo,hi]` | token bucket on attempts with retry_count > 0 in scope; over-budget retries get `RETRY_LATER` immediately; 70% of clients honour a jittered Retry-After |
| SHED_EXPIRED | psp | — | queued attempts whose client already timed out are dropped at dequeue |
| PRIORITIZE_FRESH | psp | `starvation_guard_ms` | strict priority to fresh attempts |
| SHIFT_TRAFFIC | psp | `fraction` ≤ 0.25, `ramp_ms` | lowers that PSP's weight in steps, keeps a 5% trickle; only new attempts |
| CHECK_BUDGET | psp | `rate_per_s`, `burst`, `first_check_delay_ms`, `max_checks`, `horizon_ms`, `ledger_wait_ms` | replaces the PSP's check token bucket parameters for governed/ledger_first clients |
| DEFER_CHECKS | bank | `budget_multiplier`, `first_check_delay_multiplier` | scales check budgets for payments involving that bank |
| PACE_PAYOUTS | bank | `max_rate_per_s` | caps the release rate of PAYOUT-kind payments to that beneficiary bank (S8) |
| ROLLBACK | any | `action_id` | reverts the named action |

Every applied action emits `ACTION_APPLIED` and is acknowledged with `POST control/v1/actions/{id}/applied` in live mode. Actions with unknown types are rejected and acknowledged as REJECTED.

## 7. Scenarios (all times in sim ms; run length 600 000; warm-up 120 000)

| ID | Trigger | Parameters (drawn per configuration) | Ground-truth label |
|---|---|---|---|
| S0 | none | — | no incident |
| S1 | arrivals ×m for d, plus flash ×2.5 for 20 s at its midpoint | m ∈ [1.4, 1.8], d ∈ [120 000, 200 000], onset ∈ [180 000, 260 000] | `is_incident:false`, kind `surge` |
| S2 | one PSP's `t_psp` × m | m ∈ [1.6, 3.0], d ∈ [100 000, 150 000] | psp level |
| S3 | one bank's legs (both roles) × m | m ∈ [4, 8], d ∈ [100 000, 150 000] | bank level |
| S4 | one PSP loses fraction f of workers | f ∈ [0.5, 0.7], d ∈ [40 000, 90 000] | psp level, kind `retry_storm` |
| S5 | S1 on all + S2 on one PSP, overlapping | as S1 and S2 | psp level (inside surge) |
| S6 | one beneficiary bank holds fraction h of credit legs for d; held credits resolve r later | h ∈ [0.3, 0.5], d ∈ [45 000, 75 000], r ∈ [60 000, 120 000] | bank level, kind `verification_storm` |
| S7 | one route's legs ramp ×1 → ×2.2 over 120 000 | onset when multiplier first reaches ×1.3 | route level |
| S8 | beneficiary bank × 3 slow from t0; at t0+30 000 a PAYOUT batch of n payments from P1 to that bank is released over 20 000 | n ∈ [2 000, 4 000] | bank level, kind `payout_burst` |

Each run writes `ground_truth.json` with `{incident_id, onset_ms, end_ms, level, psp, bank, kind, magnitude, is_incident}`.

## 8. Calibration (gate G-SIM; must pass before any dataset or arena result)

1. `scripts/calibrate.py --scenario S4`: sweep worker-loss f ∈ {0.5, 0.6, 0.7} × duration d ∈ {20, 40, 60, 90, 120} s, naive profile (U0), ≥20 seeds each. A run is **stuck** if goodput over [end+60 s, end+120 s] < 50% of baseline goodput.
2. `--scenario S6`: sweep hold fraction h ∈ {0.2, 0.3, 0.4, 0.5} × d ∈ {30, 45, 60, 75} s under U0, same stuck rule.
3. **Accept** if for some f (and some h) a short trigger recovers in ≥80% of seeds and a longer trigger sticks in ≥80% of seeds, and U2 at the stuck setting is stuck less often than U0.
4. If not accepted, adjust in this order: lower client timeout to 2 500; raise baseline utilisation to 0.6–0.65; raise `naive` check frequency; raise `α`; raise `q_max`. Time-box 3 hours.
5. Freeze `config/sim_default.yaml`, save the two stuck-probability heat maps (`data/figures/F1_s4.png`, `F1_s6.png`), tag `sim-frozen`. Any later dynamics change regenerates every dataset.
6. Fallback if metastability never appears: say "congestion" not "metastable" everywhere and tell M3 to switch the forecaster label (M3 §6.6).

## 9. Default parameters (`config/sim_default.yaml`)

```yaml
topology: {psps: [P1, P2, P3], psp_shares: [0.40, 0.35, 0.25], banks: [B1, B2, B3, B4, B5], bank_shares: [0.30, 0.25, 0.20, 0.15, 0.10]}
kinds: {P2P: 0.45, P2M: 0.55}                 # PAYOUT only in S8
psp: {workers: 40, q_max: 400, t_psp_mean_ms: 60, t_psp_cv: 0.5}
bank: {leg_mean_ms: 150, leg_cv: 0.6, bd_rate: 0.02, td_rate: [0.004, 0.006, 0.008, 0.010, 0.012], reversal_delay_ms: 20000}
switch: {status_workers: 4, status_mean_ms: 50, status_cv: 0.4, status_q_max: 2000, status_timeout_ms: 2000, status_bank_cost_ms: 20, slowdown_alpha: 3.0, slowdown_u0: 0.85}
demand: {fresh_rate_per_s: 165}               # baseline PSP utilisation ~0.5-0.55
client: {timeout_ms: 3000, naive_share_governed_universes: 0.30}
run: {length_ms: 600000, warmup_ms: 120000, tick_ms: 5000, snapshot_ms: 1000}
ledger_model: {submit_p50_ms: 120, submit_p95_ms: 400, event_lag_p50_ms: 50}
```

`td_rate` values are placeholders; replace with the latest NPCI bank-wise technical-decline percentages for five representative banks (E9) and record which banks and month in `config/README.md`.

## 10. Random tape (common random numbers)

For each seed generate once, before simulation, with `numpy.random.Generator(PCG64(seed))` split into named streams (`arrivals`, `routing`, `service`, `declines`, `clients`, `banks`, `status`):
- Arrival times (thinned non-homogeneous Poisson from the scenario rate function).
- Per payment: home PSP, remitter, beneficiary, kind, bd/td uniforms per leg, client p_retry and delay uniforms, Retry-After compliance flag, and for each possible attempt (up to 6) three service quantiles (psp, remitter, beneficiary).
- Service time = `F⁻¹(quantile) × multiplier(t)`: policies change *when* and *how much* an attempt is scaled, never the underlying draw.
Test: first 1 000 arrivals and bank draws identical across all five universes for a seed.

## 11. Engine

- `heapq` of `(t_ms, seq, kind, payload)`; integer ms; `seq` breaks ties deterministically.
- Event kinds: `ARRIVAL, ATTEMPT_ARRIVE, PSP_DONE, REM_DONE, BEN_DONE, CLIENT_TIMEOUT, RETRY_DUE, STATUS_ARRIVE, STATUS_DONE, STATUS_TIMEOUT, REVERSAL_DONE, HOLD_RELEASE, LEDGER_RESOLVE, TICK, SNAPSHOT, ACTION_APPLY, TRIGGER_START, TRIGGER_END`.
- Emitted stream contains only what a real platform could observe (no ground truth). `PSP_SNAPSHOT` per PSP and `SWITCH_SNAPSHOT` every 1 000 ms.
- Performance target: S0 600 s run in < 10 s wall in batch on a laptop core (≈100k payments). Avoid per-event pydantic validation in batch (validate a 1% sample + all in tests).

## 12. Run modes

| Mode | Entry | Behaviour |
|---|---|---|
| live | `POST /v1/scenario START` | wall clock × speed; SSE stream; polls `control/v1/actions/pending` every 1 s wall; U4 uses `LEDGER_URL` (mock or live); demo traffic scale `demo_rate_factor = 0.15` (≈25 payments/s) so a laptop Drunix network keeps up [tune after M1's benchmark] |
| mock | `make run-mock` | replays `contracts/fixtures/payment_events.jsonl` (looped, re-stamped) on the SSE stream; no M3/M4/M1 needed |
| batch | `POST /v1/arena` or `python -m qsim.batch` | lockstep per `docs/01_SYSTEM.md` §4.1; `LEDGER_MODE=model`; parallel processes (one run per core; M3/M4 batch endpoints must be started with matching worker counts or runs serialised) |

## 13. Metrics (`result.json`)

| Metric | Definition |
|---|---|
| peak_queue | max over time of summed PSP queue depth |
| excess_retries | attempts − payments |
| recovery_time_s | from trigger end until goodput ≥ 95% of baseline for 30 s (null if never) |
| unique_success | payments credited within 30 s of initiation (retries never counted as new customers) |
| duplicate_commits | Σ max(0, credited attempts − 1) |
| peak_switch_checks_per_s / switch_checks_total / switch_checks_per_unknown | from status service |
| unknowns_total, median_resolve_s, p95_resolve_s | time from first CLIENT_TIMEOUT to resolution |
| escalated | payments ending ESCALATED_RECONCILE |
| harmful_failovers | failovers after which peak queue or recovery time increased vs the paired U2 run (computed by the arena) |
| tat_breaches | payments debited and neither credited nor reversed within the TAT analogue |
| goodput_min_frac | min 10 s goodput / baseline |

## 14. Acceptance tests

| ID | Test | Tag |
|---|---|---|
| S-1 | Determinism: same seed + universe → identical event-stream SHA-256 | PITCH |
| S-2 | Conservation: every attempt has exactly one terminal outcome; every payment exactly one PAYMENT_CLOSED | PITCH |
| S-3 | Common random numbers across U0–U4 (§10) | PITCH |
| S-4 | S0 PSP utilisation 0.50–0.60; Little's law within 5% | PITCH |
| S-5 | Every emitted event validates against `payment_event.schema.json` (full validation in tests) | PITCH |
| S-6 | SI-1 never violated for governed/ledger_first clients (property test over random scenarios) | PITCH |
| S-7 | S6 under U0 shows switch utilisation > 0.95 and slowdown > 2 at peak; under U4 the switch peak is lower | PITCH |
| S-8 | Calibration acceptance §8 | PITCH (S4 and S6 small sweeps) / BUILD (full) |
| S-9 | Actions change outcomes: THROTTLE_RETRIES on S4 lowers excess retries vs no action, same seed | PITCH |
| S-10 | Lockstep arena runs U0, U2, U4 for S6 on 5 seeds and writes valid `result.json` | PITCH |
| S-11 | Live mode with M1 mock: unknowns opened, attested and resolved; no payment resolved without a terminal ledger event | PITCH |

## 15. Day-by-day (pitch sprint)

| Day | Tasks | Gate |
|---|---|---|
| 1 | schema models from contracts; engine skeleton; tape; S0; mock stream endpoint; `POST /v1/scenario` stub | `make run-mock` serves fixtures; S-1, S-2 on S0 |
| 2 | legs, declines, switch + slowdown, naive & npci_rule profiles, S4, S6; quick calibration sweeps | S-4, S-7; first stuck heat map |
| 3 | ledger_first via M1 mock then live; actions; live runner; integrate with M3/M4 | S-11, S-9 |
| 4 | S1, S3 (+S8 if time); lockstep arena U0/U2/U4 on S6, 5 seeds; time series endpoint for M5 | S-10 |
| 5 | Freeze `sim_default.yaml`; record demo runs to `data/recordings/` for M5 | tag `sim-frozen` |

## 16. Pitfalls

1. Do not let ground truth leak into the stream (e.g. a status field that reveals a hidden commit).
2. Zombie work must keep holding the worker, or metastability disappears.
3. Status checks must consume a shared resource, or the April 2025 loop disappears.
4. Retries reuse the idempotency key in governed profiles; naive retries do not.
5. Keep live demo traffic within the measured ledger capacity; never drop ledger writes silently — if the gateway is saturated, queue and report backlog.
6. Batch speed: avoid Python objects per event in hot loops; preallocate arrays for snapshots.

## 17. Agent prompt template

```
You are the M2 Simulator agent for QueueShield. Read AGENTS.md, docs/00_PRODUCT.md, docs/01_SYSTEM.md,
contracts/CONTRACTS.md §1, §4.1, §6 and docs/M2_SIMULATOR.md in full. Work only in sim/.
Task: <one row of §15 or one acceptance test of §14>.
Tests first. Determinism is mandatory: all randomness through qsim/tape.py streams.
Never emit ground truth. Report what passed, with the command you ran.
```
