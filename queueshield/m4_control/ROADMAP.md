# M4 Control — roadmap: what is left, what to add, in what order

Written 2026-10-20 after reviewing the code, `SPEC.md`, the IBM reference results and outside research
(`../docs/RESEARCH.md`). Read `CLAUDE.md` first for how to work; this file says **what** to work on.

**Deadlines:** pitch **Sun 25 Oct** (**P0**) · build 10–22 Nov (**P1**) · finale 4 Dec (**P2**).

## 1. Where M4 stands

Working and tested (19 tests): rules R0–R7 as YAML data, SHIFT_TRAFFIC eligibility with the first failed check, BANK_SIDE →
blocked shift + DO_NOT_SHIFT advisory, safety invariants SI-1/2/3/4/5/9 (property-tested over 5 000 states), governor
budgets, decisions → actions → ledger writes with retry/queue on outage, simulated operator, live/mock/batch API.
In the 2026-10-20 smoke the auto operator approved a BANK_SIDE package and the decision + advisories landed on the M1 mock.
**Missing for the pitch:** the console needs the ledger tx id on the `decision` stream; budget publications are too
chatty; rollback proposals (nice for the demo's "recovery" beat).

## 2. Who depends on you

| Consumer | Needs | Blocked today? |
|---|---|---|
| M5 | `recommendation`, `decision` (with ledger tx + block when committed), `budget` events | tx id not on the stream (M4-T01) |
| M2 | `/v1/actions/pending` in id order, ack endpoint; lockstep responses | no |
| M1 | well-formed `ledger_decision` / `advisory` writes | no |

## 3. Tasks

### M4-T01 · Ledger status on the decision stream (U-3) [P0, 2 h]
- **Why:** M5's DecisionLog must switch from "recording on ledger…" to "tx … · block …" within ≤ 2 s of the
  `DecisionRecorded` event.
- **Steps:** in `RunControl.on_ledger_event`, when a `DecisionRecorded`/`AdvisoryIssued` arrives, publish
  `event: decision` again with `{rec_id, decision_id, ledger: {decision_tx, block_number, advisory_txs}}`; also include
  `decision_id` and `block_number` in the synchronous `POST /v1/decisions` response when the write succeeded.
- **Done when:** a test feeds a fixture `DecisionRecorded` and asserts the published payload; M5 shows the tx id.

### M4-T02 · Quieter budget publication [P0, 1 h]
- **Seen:** 29 CHECK_BUDGET actions in 137 sim s at demo rate — noisy for M2's queue and the console.
- **Steps:** add `governor.min_publish_interval_s` (e.g. 30) and keep the > 10 % change rule; always publish on the first
  tick and when a DEFER_CHECKS is approved/rolled back. SI-5 test must stay green; C-7 unchanged.

### M4-T03 · Rollback proposals and advisory revocation (C-9) [P0 for the demo's recovery beat, ~0.5 day]
- **Steps:** track applied actions (from `/applied` acks or ACTION_APPLIED in ticks); after
  `rollback.clean_ticks` (6) clean ticks on the action's scope, create a recommendation with a single `ROLLBACK` action
  (`params.action_id`), status PENDING; on approval enqueue the ROLLBACK action for M2 and `DELETE /v1/advisories/{id}` for
  each advisory that action produced. The IBM `ActionManager.tick` (`../../OldReferenceAnalagousProject/IBM/qs/core/actions.py`)
  is the model; avoid its bug of proposals for incidents that already closed.
- **Done when:** C-9 test: proposal appears after 6 clean ticks, approval revokes the advisory (ModelLedger records it).

### M4-T04 · Merge packages for one fault [P0, 2 h; coordinate with M3-T02]
- If M3 still emits two incidents for one bank fault, M4 should not show two packages: when two PENDING recommendations
  share verdict BANK_SIDE and the same bank, supersede the older one into the newer. Keep "at most one PENDING per
  incident" (SPEC pitfall 3). Drop this task if M3-T02 fixes the source.

### M4-T05 · Operator-delay sweep support [P0 for the arena, 1 h]
- Lockstep `ResetRequest.operator_delay_s` already flows through; add a script `scripts/operator_sweep.py` that asks M2
  for S4 arena runs at delays 5/15/30/60/120 s and tabulates recovery. The IBM sweep found approval delay was the
  dominant factor (0 s recovery at ≤ 15 s delay vs 64 s at 120 s) — a strong demo/QA point.

### M4-T06 · PACE_PAYOUTS for S8 [P1]
- R3 adds PACE_PAYOUTS(b) when PAYOUT traffic to b is > 10 % of b's arrivals. M3 does not expose payout share yet: write a
  contract proposal `../contracts/PROPOSALS/<date>-m4-payout-share.md` (additive optional feature `payout_share` on bank
  segments), then implement `max_rate_per_s = 0.5 × spare, min 5/s` (`control.yaml pace`).

### M4-T07 · Switch capacity input [P1]
- The governor uses `default_capacity_per_s = 80`. After M2 calibration changes switch capacity, propose an optional
  `switch_status_capacity_per_s` feature on the switch segment so budgets follow the real capacity (pitfall 2: budgets
  must be load-aware).

### M4-T08 · Regulator observer feed [P1]
- Read-only stream/endpoint of decisions, advisories and TAT breaches for M5's regulator view (SPEC actors table).

## 4. Enhancements beyond the spec

| Idea | Why | Effort |
|---|---|---|
| **Approval SLA timer + escalation** (e.g. CRITICAL unanswered for 30 s → ESCALATE_HUMAN to a second operator) | IBM sweep: the human is the bottleneck; turns that finding into a feature | S |
| **Two-person rule for SHIFT_TRAFFIC** (maker–checker, as Project Axis does for large transfers) | routing changes are the riskiest action; maker–checker is familiar to bank judges | S |
| **Expected-effect ranking**: order actions by an estimate from arena runs (e.g. median recovery gain for this verdict) | turns "ranked" into evidence-backed; uses M2's arena data | M |
| **Retry budget action** (cap retries at ~10 % of fresh traffic, Google SRE) as a gentler first step than THROTTLE_RETRIES | standard, citable mitigation | S (needs M2 support) |
| **On-chain check policy** (`checkpolicy` contract, SPEC BUILD P0 for M1) so the budget itself is a signed advisory banks can audit | makes NPCI-rule compliance provable, not self-reported | M (with M1) |

## 5. Open questions
1. Should rejected packages also write DO_NOT_SHIFT? (Spec: advisories only for an approved package.)
2. Operators list in `config/operators.yaml` — fill in real team names before the demo.

## 6. This week

| Day | Do | Gate |
|---|---|---|
| Tue 20 | M4-T01, M4-T02 | DecisionLog shows tx ids |
| Wed 21 | M4-T03 rollback | C-9 green |
| Thu 22 | live inputs against M1 live (if up) or mock; M4-T04 if still needed | one package per fault |
| Fri 23 | M4-T05 operator sweep with M2's arena | sweep table for the deck |
| Sat 24 | freeze `policy.yaml`; rehearse S3 and S6 decision flows | — |
