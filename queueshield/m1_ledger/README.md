# M1 — Ledger (`m1_ledger/`, port 8004, Go chaincode + TypeScript gateway)

**Owner:** _fill in_ · **Backup reviewer:** M4 owner · **Spec:** [`SPEC.md`](SPEC.md) · **Status:** [STATUS.md](STATUS.md) · **Roadmap:** [ROADMAP.md](ROADMAP.md) · **Agent instructions:** [CLAUDE.md](CLAUDE.md)

## Documents in this folder

| File | Read it for |
|---|---|
| `README.md` | the whole idea, this module's job, interfaces, how to run (this file) |
| `STATUS.md` | what exists today and how it was verified |
| `ROADMAP.md` | everything left to do: task cards with acceptance checks, enhancements, this week's plan |
| `CLAUDE.md` | instructions for you or your AI agent: reading order, workflow, hard rules, a ready prompt |
| `SPEC.md` | the full module specification (working copy) |
Shared across modules: `../AGENTS.md`, `../contracts/`, `../docs/` (product, system, plan, research, deviations).

## The whole project in one minute

QueueShield is our Drunix Hackathon 2026 entry (NPCI × Citi, Real-Time Payments). When a UPI bank or PSP slows down, payments time out and become **unknown**; apps then hammer the NPCI switch with status checks and users retry, which slows everything further (the April 2025 UPI outages). QueueShield detects and localises the degrading segment and forecasts lock-in (M3), recommends bounded actions a human approves (M4, M5), and — your part — resolves unknown payments from a **shared Drunix ledger**: the bank that knows the outcome attests it once and everyone is **pushed** the answer, so status checks stop being load. Every advisory and operator decision is recorded on the same ledger. Everything else runs in a simulator (M2).

## Your module's job

Make Drunix (NPCI's fork of Hyperledger Fabric 2.5) carry exactly three kinds of shared truth, and expose them through
one REST + SSE gateway so no other module needs to know Fabric exists:

| Contract | Keys | What |
|---|---|---|
| `paystate` | `PAY~<run_id>:<payment_id>` | unknown payments, signed bank attestations (DEBIT/CREDIT/FAILURE_*/REVERSAL), state machine, RBI TAT clock |
| `advisory` | `ADV~adv-NNNNN` | signed, time-boxed network advisories (SLOW_RETRIES, DEFER_CHECKS, DO_NOT_SHIFT, PACE_PAYOUTS) |
| `decisionlog` | `DEC~dec-NNNNN` | append-only operator decisions |

A byte-compatible **mock gateway** (`LEDGER_MODE=mock`) lets everyone work before the network runs. It is built and tested.

## Interfaces (`contracts/CONTRACTS.md` §4–§5)

| Route | Who calls | Chaincode |
|---|---|---|
| `POST /v1/payments`, `POST /v1/payments/{txnRef}/attest`, `GET /v1/payments[/{txnRef}]` | M2 (U4) | `paystate:*` |
| `POST/DELETE/GET /v1/advisories`, `POST/GET /v1/decisions` | M4 | `advisory:*`, `decisionlog:*` |
| `GET /v1/stream` SSE `ledger_event` (PaymentUpdated, TATBreach, AdvisoryIssued, AdvisoryRevoked, DecisionRecorded) | M2, M4, M5 | chaincode events |
| `GET /v1/network`, `/v1/metrics`, `/v1/health`, `POST /v1/admin/reset` (mock) | M5 | qscc |

## Code map

| Path | What |
|---|---|
| `testdata/transitions.json` | 70 golden vectors — the single source of truth for the state machine (Go and TS both test against it) |
| `chaincode/logic/` | pure Go state machine (`transitions.go`), types, golden-vector tests — no Fabric imports |
| `chaincode/{main,paystate,advisory,errors}.go` | contract layer (`contractapi`) — **written, not yet compiled** |
| `gateway/src/mock/` | `transitions.ts` (line-by-line port), `ledger.ts` (in-memory ledger, keyed mutex, latency model, TAT sweep) |
| `gateway/src/routes.ts`, `sse.ts`, `validate.ts`, `config.ts`, `main.ts` | REST + SSE per contract, ajv schema checks, config |
| `gateway/src/live/README.md` | the plan for the live Fabric gateway (fabric.ts, events.ts, readmodel.ts, tat.ts) |
| `network/qs-net.sh` | Drunix test-network wrapper: doctor, clone, up (waits for YugabyteDB), create-channel, deploy, sql, status, down |

## Run and test

```bash
cd m1_ledger/gateway && npm install
npm test                         # golden vectors (TS) + L3-L8 route tests
npx tsc --noEmit                 # typecheck
QS_API_KEY=dev LEDGER_MODE=mock node src/main.ts      # mock gateway on :8004 (Node >= 22.6 runs .ts directly)
# Go side (needs Go):  cd m1_ledger/chaincode && go test ./logic/...
# Network (WSL2/Linux + Docker, never Git-Bash):  ./network/qs-net.sh bootstrap
```
Never commit `m1_ledger/drunix/` or anything under `organizations/` — it holds private keys (git-ignored).
