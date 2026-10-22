# CONTRACTS — the only shared interface between modules (v1)

Everything here is binding. JSON Schemas live in `schemas/`; examples in `fixtures/` validate against them (checked with `jsonschema` draft 2020-12 on 19 Oct 2026). All bodies are `application/json`; all streams are SSE per `docs/01_SYSTEM.md` §9. All write endpoints require `X-QS-Key`.

Error body for every non-2xx: `{"error": "<CODE>", "detail": "<human text>"}` with codes `BAD_REQUEST`, `SCHEMA_INVALID`, `NOT_FOUND`, `CONFLICT`, `UNAUTHORIZED`, `UNAVAILABLE`, `LEDGER_ERROR`, `INTERNAL`.

## 1. M2 Simulator — :8001

| Method & path | Body / query | Response | Notes |
|---|---|---|---|
| `GET /v1/health` | — | health object | |
| `POST /v1/scenario` | `scenario_command.schema.json` | `202 {"run_id"}` | START creates a new run; RESET stops and clears |
| `GET /v1/status` | — | `{"run_id","scenario","seed","universe","sim_ms","speed","state":"IDLE|RUNNING|PAUSED|DONE","ledger_mode"}` | |
| `GET /v1/stream` | `?types=ATTEMPT_OUTCOME,...` optional filter | SSE, `event: payment_event`, data = `payment_event.schema.json` | Also `event: run_started`, `event: run_done` with `{"run_id"}` |
| `GET /v1/timeseries` | `?run_id=&from_ms=` | `{"t":[...],"goodput":[...],"queue":{"P1":[...]...},"switch_checks_per_s":[...],"unknown_open":[...]}` | 1 s buckets, for console charts |
| `GET /v1/results` | — | `[run_result summary]` | lists `data/runs/*/result.json` |
| `GET /v1/results/{run_id}` | — | `run_result.schema.json` | |
| `POST /v1/arena` | `{"scenario","seeds":[..],"universes":[..],"overrides":{}}` | `202 {"job_id"}` | batch lockstep; writes `data/runs/` |
| `GET /v1/arena/{job_id}` | — | `{"state","done","total","run_ids":[...]}` | |

## 2. M3 Detection — :8002

| Method & path | Body | Response | Notes |
|---|---|---|---|
| `GET /v1/health` | | | |
| `GET /v1/stream` | | SSE `event: tick` data = `segment_state.schema.json`; `event: incident` data = `incident.schema.json` (on open/update/close) | one `tick` per 5 000 sim ms |
| `GET /v1/state` | | latest `segment_state` | |
| `GET /v1/incidents` | `?state=OPEN` | `[incident]` | |
| `GET /v1/forecaster/grid` | | `{"version","delay_bins":[...21 edges],"orbit_bins":[...21 edges],"p":[[20x20]],"contour_0_5":[[x,y],...]}` | for the cascade map |
| `POST /v1/batch/reset` | `lockstep#/$defs/ResetRequest` | `200` | |
| `POST /v1/batch/tick` | `lockstep#/$defs/DetectTickRequest` | `segment_state` | |

## 3. M4 Control — :8003

| Method & path | Body | Response | Notes |
|---|---|---|---|
| `GET /v1/health` | | | |
| `GET /v1/stream` | | SSE `event: recommendation` (`recommendation.schema.json`, on create and status change); `event: budget` (`{"psp","rate_per_s","burst","first_check_delay_ms","ledger_wait_ms","origin"}`); `event: decision` (decision + resulting action ids) | |
| `GET /v1/recommendations` | `?status=PENDING` | `[recommendation]` | |
| `POST /v1/decisions` | `decision.schema.json` | `200 {"rec_id","status","action_ids":[...],"ledger":{"decision_tx":"...","advisory_txs":[...]}}` | idempotent per rec_id; second decision on a decided rec → `409` |
| `GET /v1/actions/pending` | `?run_id=&since=<action_id>` | `[action.schema.json]` | M2 polls every 1 s wall in live mode |
| `POST /v1/actions/{action_id}/applied` | `{"sim_ms","result":"APPLIED|REJECTED","detail"}` | `200` | M2 acknowledges |
| `POST /v1/batch/reset` | `lockstep#/$defs/ResetRequest` | `200` | |
| `POST /v1/batch/tick` | `lockstep#/$defs/ControlTickRequest` | `lockstep#/$defs/ControlTickResponse` | |

## 4. M1 Ledger gateway — :8004

| Method & path | Body | Response | Chaincode call | Identity |
|---|---|---|---|---|
| `GET /v1/health` | | `{"status","mode","peers_reachable":{...}}` | | |
| `GET /v1/network` | | `network_info.schema.json` | qscc `GetChainInfo` (evaluate) | Org1 |
| `POST /v1/payments` | `ledger_open_request.schema.json` | `201` new / `200` identical exists: `{"record": ledger_payment, "tx_id", "block_number"}`; `409 CONFLICT` if same txnRef with different fields | `paystate:OpenUnknown` (submit) | Org1 (payer side) |
| `POST /v1/payments/{txnRef}/attest` | `ledger_attest_request.schema.json` | `200 {"record","tx_id","block_number","noop":bool}`; `409` illegal transition is NOT an error: the record moves to DISPUTED and returns 200 | `paystate:AttestDebit|AttestCredit|AttestFailure|AttestReversal` | DEBIT, FAILURE_REMITTER → Org1; CREDIT, FAILURE_BENEFICIARY, REVERSAL → Org2 |
| `GET /v1/payments/{txnRef}` | | `ledger_payment.schema.json` | `paystate:GetStatus` (evaluate on Lite Peer) | Org1 |
| `GET /v1/payments` | `?run_id=&state=&limit=` | `[ledger_payment]` | YSQL read model (live) / memory (mock) | — |
| `POST /v1/advisories` | `advisory.schema.json` (without issuedAt/expiresAt/revoked/issuerMspId) | `201 {"advisory","tx_id"}` | `advisory:IssueAdvisory` | Org1 (authority role) |
| `DELETE /v1/advisories/{id}` | `{"reason"}` | `200 {"advisory","tx_id"}` | `advisory:RevokeAdvisory` | Org1 |
| `GET /v1/advisories` | `?active=true` | `[advisory]` | `advisory:ListActive` (evaluate) | Org1 |
| `POST /v1/decisions` | `ledger_decision.schema.json` (without recordedAt/recorderMspId) | `201 {"decision","tx_id"}` | `decisionlog:RecordDecision` | Org1 |
| `GET /v1/decisions/{id}` | | ledger_decision | `decisionlog:GetDecision` | Org1 |
| `GET /v1/stream` | `?from_block=` | SSE `event: ledger_event`, data = `ledger_event.schema.json` | chaincode events via Committing Peer, checkpointed | Org1 |
| `GET /v1/metrics` | | `{"submit_ms":{"p50","p95","p99","n"},"evaluate_ms":{...},"mvcc_retries","errors_by_code":{...}}` | | |
| `POST /v1/admin/reset` | | `200` | mock only; live returns `400` | |

## 5. Event names on the ledger stream

| name | When | payload |
|---|---|---|
| `PaymentUpdated` | any paystate write that changes state (including OPEN) | `{"txnRef","state","prevState","kind":"OPEN|DEBIT|CREDIT|FAILURE_REMITTER|FAILURE_BENEFICIARY|REVERSAL","runId","payerPsp","remitterBank","beneficiaryBank","simMs","debitImplied","disputedReason"?}` |
| `TATBreach` | `paystate:CheckTAT` finds a breach | `{"txnRef","state","tatDeadline","runId","beneficiaryBank"}` |
| `AdvisoryIssued` | `advisory:IssueAdvisory` | advisory record |
| `AdvisoryRevoked` | `advisory:RevokeAdvisory` | `{"id","reason"}` |
| `DecisionRecorded` | `decisionlog:RecordDecision` | decision record |

Fabric allows **one chaincode event per transaction** (the last `SetEvent` wins). Each chaincode function therefore emits at most one event, listed above.

## 6. Shared files (batch only; never code)

| Path | Writer | Readers | Format |
|---|---|---|---|
| `data/runs/<run_id>/events.jsonl` | M2 | M3 (training), M5 (replay) | one `payment_event` per line |
| `data/runs/<run_id>/ground_truth.json` | M2 | M3 (training/eval only) | `run_result.ground_truth` |
| `data/runs/<run_id>/ticks.jsonl` | M2 (stores M3 snapshots received in lockstep) | M5 (arena replay) | one `segment_state` per line |
| `data/runs/<run_id>/result.json` | M2 | M5, report | `run_result.schema.json` |
| `data/runs/<run_id>/timeseries.json` | M2 | M5 | as `GET /v1/timeseries` |
| `data/models/forecaster_grid.json` | M3 | M3, M5 | as `GET /v1/forecaster/grid` |
| `data/ledger_bench.json` | M1 | M2 (ledger model), report | `{"submit_ms":{"p50","p95","p99"},"evaluate_ms":{...},"event_lag_ms":{...},"max_tps_sustained","peers":{...},"measured_wall_iso"}` |
| `data/recordings/<name>.jsonl` | M5 | M5 replay | `{"stream","sim_ms","data"}` per line |

## 7. Versioning and change process

1. `schema_version` is 1 for every streamed message; schemas live at `$id` `https://queueshield.local/schemas/<file>`.
2. A change is proposed in `contracts/PROPOSALS/`. Additive optional fields: approval of the affected owners. Anything else: all five owners, plus regenerated fixtures and a version bump.
3. After the change merges, every affected module updates and its contract tests pass before the next integration run.
4. Contract tests: each module has `tests/contract/` that validates (a) every outgoing message against the schema, (b) its parser against every fixture in `contracts/fixtures/`.
