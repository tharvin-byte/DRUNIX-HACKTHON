# M4 — Control: Verification Governor, policy engine, decisions and advisories

> **Working copy** of the QueueShield spec v1.0 (19 Oct 2026), moved next to the code on 2026-10-20. The original stays frozen in `Citibank/queueshield-spec/` (next to `queueshield/`); this copy is the one the team updates.
> Folder names in this repo: `ledger/` → `m1_ledger/`, `sim/` → `m2_simulator/`, `detect/` → `m3_detection/`, `control/` → `m4_control/`, `console/` → `m5_console/`. Shared docs: `docs/` at the repo root; module specs: `SPEC.md` inside each module folder.

**Owner folder:** `control/` · **Port:** 8003 · **Stack:** Python 3.11, FastAPI, sse-starlette, httpx, httpx-sse, pydantic v2, jsonschema · **Reads:** M3 stream (`tick`, `incident`), M1 stream (`ledger_event`) · **Writes:** recommendations (to M5), actions (to M2), advisories and decisions (to M1).

Your job: turn evidence into a short, ranked, bounded set of actions that a human can approve in seconds; publish the check budget that keeps verification from becoming load; and make every approval durable and shared by writing it to the ledger. Models detect; **your rules decide what is eligible**; humans decide what happens.

---

## 1. Folder layout

```
control/
├── config/{control.yaml, policy.yaml, operators.yaml}
├── qctl/
│   ├── schema.py
│   ├── inputs.py          SSE clients for M3 and M1 (Last-Event-ID resume)
│   ├── governor.py        §2 check budgets
│   ├── rules.py           §3 rule table
│   ├── eligibility.py     §4 checks (SHIFT_TRAFFIC etc.)
│   ├── recommend.py       build recommendation records §5
│   ├── decisions.py       §6 decision handling + ledger writes
│   ├── actions.py         action queue, ids, rollback proposals §7
│   ├── operator_sim.py    §8 simulated operator (batch / auto mode)
│   ├── invariants.py      §9 runtime guards
│   └── api.py
└── tests/
```

## 2. Verification Governor (check budgets)

The Governor does not send checks. It publishes, per PSP, the parameters of the token bucket that M2's governed/ledger_first clients use to release switch status checks. High-rate check traffic never crosses module boundaries.

**Default budget (origin `POLICY_DEFAULT`, no approval needed — it is the configured NPCI-rule analogue):**
`first_check_delay_ms = 10 000`, `max_checks = 3`, `horizon_ms = 120 000`, `ledger_wait_ms = 10 000`, `rate_per_s` and `burst` from the formula below.

**Adaptive formula (every tick):**
```
C_status   = switch capacity per s (from SWITCH_SNAPSHOT via M3 switch segment features; default 80)
used       = switch status_check_rate (M3 switch features)
spare      = max(0, C_status * 0.85 - used)            # keep the switch below the slowdown knee u0 = 0.85
share_p    = PSP p's fresh-traffic share (M3 psp features, Wl)
rate_p     = clamp(0.5 * spare * share_p, r_min = 1.0, r_max = 0.3 * C_status * share_p)
burst_p    = ceil(2 * rate_p)
```
**Tightened budget (only under an approved DEFER_CHECKS for a bank or the switch):** multiply `rate_p` by `budget_multiplier` (default 0.5) and `first_check_delay_ms` by `first_check_delay_multiplier` (default 1.5), scoped to payments involving that bank (M2 applies per-bank scaling).

Publish a `CHECK_BUDGET` action per PSP when any value changes by > 10% from the last published one, at most once per tick; also stream `event: budget` for the console. In U4 the ledger usually resolves unknowns before `ledger_wait_ms`, so the budget mostly governs the residual.

## 3. Rule table (evaluated in order; first match gives the base list)

| # | Condition | Recommended list (priority order) |
|---|---|---|
| R0 | global or segment DEGRADED_MONITORING | HOLD_MONITOR, ESCALATE_HUMAN |
| R1 | verdict SWITCH_STATUS_OVERLOAD (any severity) | DEFER_CHECKS (switch scope), THROTTLE_RETRIES (platform, light), HOLD_MONITOR |
| R2 | CRITICAL + PSP_SIDE(p) | SHED_EXPIRED(p), THROTTLE_RETRIES(p), DEFER_CHECKS(p's top bank if lift>0.2 else none), PRIORITIZE_FRESH(p), SHIFT_TRAFFIC(p) if §4 passes |
| R3 | CRITICAL + BANK_SIDE(b) | THROTTLE_RETRIES(bank b), DEFER_CHECKS(b), SHED_EXPIRED(every PSP), PRIORITIZE_FRESH(every PSP); SHIFT_TRAFFIC shown **blocked**: "shared bank b is slow on every PSP" → advisory DO_NOT_SHIFT; PACE_PAYOUTS(b) if PAYOUT traffic to b is > 10% of b's arrivals |
| R4 | WARNING (not critical) | DEFER_CHECKS (scope = incident segment), THROTTLE_RETRIES light (rate_fraction 0.2), HOLD_MONITOR |
| R5 | ROUTE_SPECIFIC(p, b) | THROTTLE_RETRIES(route), DEFER_CHECKS(b), SHIFT_TRAFFIC for that route only if b is healthy via the other PSPs (lift on other routes < 0.2) |
| R6 | MULTI_FAULT or PLATFORM_WIDE | THROTTLE_RETRIES(platform), DEFER_CHECKS(platform), ESCALATE_HUMAN |
| R7 | SURGE annotation only | HOLD_MONITOR with note "demand surge, queue draining, no action" |

Rules live in `config/policy.yaml` as data, with a `rules_version` string written into every recommendation.

## 4. Eligibility checks

**SHIFT_TRAFFIC** is eligible only if **all** hold; otherwise it is shown with `eligible:false` and `blocked_by` naming the first failed check:
1. Verdict is not BANK_SIDE, SWITCH_STATUS_OVERLOAD, MULTI_FAULT or PLATFORM_WIDE.
2. Each target PSP has spare ≥ 30% after receiving its share: `1 − (arrival + moved)/capacity ≥ 0.3`.
3. No target has an open WARNING/CRITICAL incident or forecaster state WATCH/CRITICAL.
4. Step ≤ 0.25 of the source weight, source keeps ≥ 5% trickle, steps ≥ 10 s apart with jitter.
5. In-flight and unknown payments are never moved (M2 enforces; M4 states it in `side_effect`).

**THROTTLE_RETRIES**: `rate_fraction` default 0.10 (critical) / 0.20 (warning) of the segment's fresh rate; `retry_after_ms: [2000, 8000]`.
**PACE_PAYOUTS**: `max_rate_per_s = 0.5 ×` the bank's estimated spare capacity, min 5/s.

## 5. Recommendation records

- Built when an incident opens or its severity/verdict changes; at most one PENDING recommendation per incident (a new one supersedes the old: status `SUPERSEDED`).
- Fields per `recommendation.schema.json`; every action has `side_effect` (what could go wrong) and `rollback_condition` (when to propose undoing it).
- Advisory mapping: THROTTLE_RETRIES → SLOW_RETRIES; DEFER_CHECKS → DEFER_CHECKS; blocked SHIFT_TRAFFIC → DO_NOT_SHIFT; PACE_PAYOUTS → PACE_PAYOUTS; others none.
- `confidence` = incident confidence; `p_stuck`, `countdown_s_estimate` copied from the incident; `model_versions` from M3 plus `policy: rules_version`.
- Expiry: PENDING recommendations expire after 120 sim s without a decision (`EXPIRED`), and are rebuilt if the incident persists.

## 6. Decisions → actions → ledger

On `POST /v1/decisions` (validate; operator must be in `operators.yaml`; `409` if the recommendation is not PENDING):

1. Status → APPROVED / PARTIAL / REJECTED.
2. For each approved **eligible** action: create `action` records (`act-NNNNN`, origin `OPERATOR_APPROVED`, `effective_from_sim_ms` = current sim time), enqueue for M2. Blocked actions can never be approved (SI-2).
3. Write the decision to the ledger: `POST LEDGER_URL/v1/decisions` with `id = dec-NNNNN`, `recId`, `decision`, `operator`, `actionsApproved`, `modelVersions`, `featuresSha256`, `decidedSimMs`.
4. For each approved action with an advisory mapping, and for every blocked SHIFT_TRAFFIC in an approved package: `POST LEDGER_URL/v1/advisories` with `id = adv-NNNNN`, `kind`, `segmentId` (scope), `params`, `reason` (≤ 200 chars, from the rule), `evidenceHash = "sha256:" + sha256(canonical JSON of the recommendation)`, `decisionId`, `issuedSimMs`, `validForSec` (default 300; `DO_NOT_SHIFT` 600).
5. Ledger write failures do **not** block actions: retry 3 times with backoff, then mark `ledger.pending=true` in the response and stream, retry every 10 s until success. M5 shows "recording on ledger…" until a `DecisionRecorded` event arrives.
6. Stream `event: decision` and the updated recommendation.

Rejection writes a decision record too (accountability for "do nothing").

## 7. Action queue and rollback

- `/v1/actions/pending?run_id=&since=` returns actions after `since` in id order; M2 acknowledges via `/applied`.
- Rollback proposals: when an action's `rollback_condition` is met (e.g. segment clean for 6 ticks), create a new recommendation with a single `ROLLBACK` action referencing the original `action_id`; the operator approves like any other. Advisories are revoked (`DELETE /v1/advisories/{id}`) when their action is rolled back, or allowed to expire.

## 8. Simulated operator (batch and `OPERATOR_MODE=auto`)

Approves a PENDING recommendation `operator_delay_s` (default 20; sweep 5, 15, 30, 60, 120) after creation if confidence ≥ 0.6 (else waits one more tick and re-checks); approves all **eligible** actions; operator name `auto_operator`. Never approves blocked actions. Writes decisions/advisories exactly like a human (to the ledger model in batch: returns synthetic tx ids and emits the corresponding ledger events back in the lockstep response).

## 9. Safety invariants (enforced in code, property-tested)

| ID | Invariant | Where |
|---|---|---|
| SI-1 | No action ever requests a new attempt for an unknown/checking/escalated payment | M4 never emits such an action; M2 enforces |
| SI-2 | SHIFT_TRAFFIC is never eligible unless all §4 checks pass; blocked actions cannot be approved | eligibility.py, decisions.py |
| SI-3 | No action with origin OPERATOR_APPROVED exists without a recorded decision (who, when, which rec) | decisions.py |
| SI-4 | In DEGRADED_MONITORING only HOLD_MONITOR and ESCALATE_HUMAN are recommended | rules.py R0 |
| SI-5 | Check budgets never exceed `r_max` and never drop below `r_min` | governor.py |
| SI-6 | Every recommendation and decision stores model versions, features hash, reasons and confidence | recommend.py |
| SI-8 | Every applied action has a rollback condition; proposals are generated when met | actions.py |
| SI-9 | No advisory reaches the ledger without a recorded decision id | decisions.py |
| SI-10 | No ledger payload contains amounts, accounts, VPAs or names (schema-enforced) | schema validation |

## 10. API and modes

CONTRACTS §3. Live: subscribe to M3 and M1 streams; `OPERATOR_MODE=human` by default. Mock: read `contracts/fixtures/incident.json` (and recorded ticks if present) and serve recommendations; ledger calls go to M1 mock. Batch: `/v1/batch/reset` and `/v1/batch/tick` per lockstep schema; one state machine per run_id.

## 11. Acceptance tests

| ID | Test | Tag |
|---|---|---|
| C-1 | Rule table: one unit test per row R0–R7 with fabricated snapshots | PITCH |
| C-2 | SI-1, SI-2, SI-4, SI-5 property tests over 5 000 random states | PITCH |
| C-3 | BANK_SIDE recommendation shows SHIFT_TRAFFIC blocked with the shared-bank reason and maps to DO_NOT_SHIFT | PITCH |
| C-4 | Decision flow against M1 mock: decision + advisories written, ledger events received, actions queued, M2 ack recorded | PITCH |
| C-5 | Ledger outage: actions still applied, ledger writes retried and eventually recorded | PITCH |
| C-6 | Every message validates against its schema; double decision → 409 | PITCH |
| C-7 | Budget formula: spare 0 → r_min; increasing switch use lowers rates monotonically | PITCH |
| C-8 | Simulated operator: delay honoured; never approves blocked actions | PITCH |
| C-9 | Rollback proposal appears after 6 clean ticks and revokes the advisory on approval | BUILD |

## 12. Day-by-day (pitch sprint)

| Day | Tasks | Gate |
|---|---|---|
| 1 | schema models; serve recommendations from fixture incident; decisions endpoint against M1 mock | mock end-to-end with fixtures |
| 2 | rules + eligibility + governor; budgets stream; action queue | C-1, C-2, C-3, C-7 |
| 3 | live inputs from M3 and M1; ledger writes live; M2 polling | C-4, C-6 |
| 4 | simulated operator + batch endpoints for the arena; ledger outage handling | C-5, C-8 |
| 5 | freeze `policy.yaml`; rehearse decision flow on S3 and S6 | — |

## 13. Pitfalls

1. Do not recommend failover on bank-side faults — the whole point of the localizer.
2. Budgets are load-aware: never compute them from configured capacity alone.
3. Keep at most one PENDING recommendation per incident or the console floods.
4. Ledger latency is seconds in live mode; never block the operator on it.
5. Use the sim clock from the latest tick for every sim-time field; never wall time.

## 14. Agent prompt template

```
You are the M4 Control agent for QueueShield. Read AGENTS.md, docs/00_PRODUCT.md, docs/01_SYSTEM.md,
contracts/CONTRACTS.md §3–§5 and docs/M4_CONTROL.md in full. Work only in control/.
Task: <row of §12 or acceptance test of §11>. Tests first, especially the safety invariants in §9.
All thresholds come from config/*.yaml. Report results with the exact command run.
```
