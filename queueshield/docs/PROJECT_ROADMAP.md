# QueueShield — project roadmap across all five modules (written 2026-10-20)

Per-module detail lives next to the code: `m1_ledger/ROADMAP.md` … `m5_console/ROADMAP.md` (task ids `M1-T01` …).
This file is the team lead's view: what "done" means for the pitch, the critical path, who waits for whom, the daily
gates and the build-phase plan. Background: `00_PRODUCT.md`, `01_SYSTEM.md`, `90_PLAN_EVAL_RISKS.md`, `RESEARCH.md`.

**Dates:** today Tue 20 Oct · pitch prototype frozen **Sat 24 Oct**, submitted **Sun 25 Oct** · build 10–22 Nov · finale 4 Dec.

## 1. Pitch Definition of Done (from `90_PLAN_EVAL_RISKS.md` §2) — where each item stands

| # | Item | Status 2026-10-20 | Tasks that finish it |
|---|---|---|---|
| 1 | A real Drunix network running `queueshield` | ✗ not started (no Docker/Go on dev machine) | M1-T01, M1-T02, M1-T03 |
| 2 | S6 end to end in U4 with ledger push resolution visible in the console | ◐ chain works on the M1 *mock* with the in-sim ledger *model*; payments never reach M1 | M2-T02, M1-T03/T04, M5-T03 |
| 3 | S3 with blocked failover and a DO_NOT_SHIFT advisory on the ledger | ◐ works on the mock (smoke 2026-10-20); console view unverified in a browser | M3-T02, M4-T01, M5-T01/T02 |
| 4 | S4 cascade map crossing the 0.5 contour | ✗ needs calibrated runs → trained grid → map | **M2-T01** → M3-T01 → M5-T04 |
| 5 | Preliminary arena chart U0 vs U2 vs U4, "simulation, 5 seeds, preliminary" | ✗ | M2-T01 → M2-T03 → M5-T06 |
| 6 | Replay mode and a backup video | ✗ | M5-T05, M5-T08 |

**Never cut** (spec): real Drunix + S6 end to end + claims policy.
**Cut order if a day slips** (spec, top first): IsolationForest → arena (keep split replay) → `decisionlog` contract
(anchor the decision hash inside the advisory) → S4/cascade map (keep S6 and S3).

## 2. Critical path and dependencies

```
M2-T01 calibration ──▶ M3-T01 train grid ──▶ M5-T04 cascade map
        │          └──▶ M3-T03/T04 tuning ──▶ detector race on the demo
        └──▶ M2-T03 arena (with M3/M4 lockstep) ──▶ M5-T06 arena tab + split replay
M1-T01 network up ──▶ M1-T02 compile ──▶ M1-T03 live writes ──▶ M1-T04 events ──▶ M2-T02 bridge against live ──▶ DoD #1, #2
M4-T01 ledger tx on decision stream ──▶ M5-T02 approve flow (U-3)
M5-T05 recorder/replay ──▶ backup demo (independent of everything live)
```
The two long poles are **M2-T01** (blocks the analytics story) and **M1-T01** (blocks the "real Drunix" claim). Start
both on Tue morning. Nobody else waits: M3/M4/M5 keep working on fixtures, mocks and today's runs.

## 3. Day-by-day for the whole team

| Day | M1 Ledger | M2 Simulator | M3 Detection | M4 Control | M5 Console | Gate (end of day) |
|---|---|---|---|---|---|---|
| **Tue 20** | T01 doctor/clone/up/channel on a Linux/WSL2 box; resolve `[VERIFY]`s | T01 sweeps (switch capacity first); T05 decision | T02 one incident per bank fault; T06 tests | T01 tx on decision stream; T02 quieter budgets | T01 browser pass, header polling | `basic` chaincode round-trips; first stuck heat map; console renders with badges |
| **Wed 21** | T02 compile + Go tests; deploy `queueshield`; T03 write path | finish T01, freeze `sim-frozen`; batch runs for M3 | T03 rough tuning; training pipeline ready | T03 rollback proposals | T02 approve flow; T03 verification + metric strip | L2 (Go) + L3 live; M3 has calibrated runs |
| **Thu 22** | T04 events + checkpoint; T05 MVCC; T06 network info | T02 live ledger bridge (mock, then live); T09 pacing | T01 train grid; grid endpoint | live with M1 live; T04 if needed | T04 race + cascade; T07 smoke twice | **S6 end to end on real Drunix** (spec gate) |
| **Fri 23** | T07 quick bench 10/25/50 tx/s; screenshots | T03 arena U0/U2/U4 × S6 × 5 seeds; T04; T06 | T04 surge gate; T05 race data | T05 operator-delay sweep | T05 recorder/replay; T06 arena + split replay; deck screenshots | full demo once end to end; preliminary arena labelled preliminary |
| **Sat 24** | rehearse bring-up from scratch twice | freeze; run demo scenarios for recordings | freeze configs; record ticks | freeze `policy.yaml` | T08 polish, claims lint, 2 rehearsals, backup video | two clean rehearsals; deck final |
| **Sun 25** | — | — | — | — | submit with buffer | **submitted** |

Daily: 10-minute stand-up; each owner updates their `STATUS.md`; merge to `main` only with green module tests
(`AGENTS.md` rule 19); run `m5_console/scripts/integration_smoke.py` after merging.

## 4. Integration checks you can run any time

| Check | Command (repo root) | Expect today |
|---|---|---|
| All module tests | see the table in `../README.md` | all green (67 Python/JS tests) |
| Cross-module smoke | `.venv/Scripts/python m5_console/scripts/integration_smoke.py --seconds 170` | a–d PASS, e SKIPPED until M2-T02 |
| Contract fixtures valid | each module's `tests/contract/` | green |

## 5. Contract changes that are likely (write proposals early — `contracts/PROPOSALS/`)

| Proposal | Proposed by | Affects | Why |
|---|---|---|---|
| optional `payout_share` feature on bank segments | M4 (M4-T06) | M3, M4, M5 | R3 PACE_PAYOUTS rule needs it |
| optional `switch_status_capacity_per_s` on the switch segment | M4 (M4-T07) | M3, M4 | governor must follow calibrated capacity |
| `ADAPTIVE_LIFO` action type | M2/M4 (enhancement) | M2, M4, M5 | adaptive LIFO + CoDel overload control |
| custody (`moneyWith`) on ledger events or a query route | M1 (enhancement) | M1, M5 | "money is with …" chip |
Additive optional fields need only the affected owners; anything else needs all five and a version bump (CONTRACTS §7).

## 6. Build phase (10–22 Nov) — the evaluation the finale will judge

Pre-registered hypotheses (`90_PLAN_EVAL_RISKS.md` §6) and the tasks that produce them:

| Hyp. | Claim tested | Produced by |
|---|---|---|
| P1, P2 | D3 earlier than D0–D2 at ≤ 1 false alert/h; quiet on surges | M3-T07, M3-T08 on M2-T08 config sets |
| P3 | U4 recovers faster, fewer wasted retries than U0/U1/U2 (S4) | M2-T03 at ≥ 20 configs, M2 bootstrap CIs |
| P4 | localisation prevents harmful failover (S3, U1 vs U4) | M2-T07 `harmful_failovers` |
| P5 | governed checks lower the switch peak (S6, U0 vs U3) | M2 arena |
| P6 | forecaster lead time with few false criticals | M3-T01/T09 |
| P7 | ledger-first removes most residual switch checks, zero duplicates | M2-T02, M1 live |
| P8 | Drunix carries the exception path at measured rates | M1-T07, M1-T09 |

Method: disjoint config sets A/B/C (+ a confirmation set D, as the IBM project did); freeze thresholds and tag
`eval-freeze` before set C runs once; paired by seed; medians, IQR, 95 % bootstrap CIs; **report negative results**.
The IBM project's honest write-up (`../OldReferenceAnalagousProject/IBM/docs/RESULTS.md`) is the model.

## 7. Risks to watch this week

| Risk | Signal | Response |
|---|---|---|
| Drunix will not start | M1-T01 fails Tue | WSL2 only, known fixes (ccenv `1.0`, YugabyteDB wait), ask organisers; team stays on the mock |
| Calibration does not converge | no recover/stick boundary by Wed noon | SPEC §8.6 fallback: "congestion" wording, forecaster renamed; keep S6 and S3 |
| Live events from the Committing Peer fail | L3/L7 fail Thu | spec fallback: gateway polls `GetStatus` for open unknowns at a low rate (documented) |
| Live demo fails on stage | rehearsal failure | replay mode + video (M5-T05, T08) |
| "Just another stuck-payment ledger" (Pulse exists) | judge questions | lead with the network-level storm; competitor slide from `RESEARCH.md` §4 |
| Over-claiming | forbidden words in slides | claims lint + second reviewer |
| Reuse of the IBM entry | hackathon rules | disclose using `REUSE_MAP.md`; emphasise new Drunix/UPI work |
