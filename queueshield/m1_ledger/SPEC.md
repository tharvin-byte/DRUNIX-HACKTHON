# M1 — Ledger: Drunix network, `queueshield` chaincode, gateway and mock

> **Working copy** of the QueueShield spec v1.0 (19 Oct 2026), moved next to the code on 2026-10-20. The original stays frozen in `Citibank/queueshield-spec/` (next to `queueshield/`); this copy is the one the team updates.
> Folder names in this repo: `ledger/` → `m1_ledger/`, `sim/` → `m2_simulator/`, `detect/` → `m3_detection/`, `control/` → `m4_control/`, `console/` → `m5_console/`. Shared docs: `docs/` at the repo root; module specs: `SPEC.md` inside each module folder.

**Owner folder:** `ledger/` · **Port:** 8004 · **Stack:** Go (chaincode), TypeScript on Node 20 (gateway), Bash (network scripts) · **Talks to:** M2 (writes payments/attestations, reads events), M4 (writes advisories/decisions, reads events), M5 (reads network info and events).

Your job: make Drunix carry exactly three kinds of shared truth — unknown payments with signed bank attestations and TAT clocks, network advisories, and operator decisions — and expose them through one REST + SSE gateway that every other module can use without knowing Fabric exists. A byte-identical **mock** of the gateway lets everyone else work before the network runs.

---

## 1. What we know about Drunix (verified vs to verify)

| Fact | Status | Source |
|---|---|---|
| Fork of Hyperledger Fabric, backward compatible with HLF v2.5.x, Apache-2.0, release v1.0.0 | Verified (docs) | npci/drunix README, release v1.0.0 |
| Peer split: **Lite Peer** (endorsement, chaincode simulation, stateless, horizontally scalable, relays CommitStatus to the Committing Peer) and **Committing Peer** (block sanity checks, coordinates Validation Service, MVCC, commits block + state) | Verified (docs) | docs/drunix-arch.md |
| **Stateless Validation Service** performs endorsement-policy and signature checks, round-robin from the Committing Peer | Verified (docs) | docs/drunix-arch.md |
| State DB **YugabyteDB** (SQL) in addition to LevelDB/CouchDB; **KeyDB** shared transient store per org for private data | Verified (docs) | docs/drunix-arch.md |
| Test network: 2 peer orgs, each 1 Committing Peer + 1 Lite Peer + 1 validation server; single-node Raft orderer; default DB `yugabyte`; default chaincode language `go`; supports `go`, `java`, `javascript`, `typescript`; `-ccep` endorsement policy and `-cccg` private-collection flags | Verified (docs) | drunix-network/test-network/README.md |
| Running network = **11 containers**: `orderer.example.com`, `lp1.org1`, `cp.org1`, `vs1.org1`, `lp1.org2`, `cp.org2`, `vs1.org2`, `yugabyte-org1`, `yugabyte-org2`, `hlf_keydb_org1msp`, `hlf_keydb_org2msp` | Verified by another team | settlemint-drunix docs/architecture.md |
| Lite Peer and Committing Peer use the same image `npcioss/drunix-peer:1.0.0`; role set by `CORE_PEER_LITEPEER_ENABLED=true`; **Lite Peers neither consume blocks nor commit**; both peers of an org share the org's YugabyteDB | Verified by another team (source-quoted) | same |
| In `envVar.sh`, peer index 0 = Lite Peer (`peer0.orgN`), index 1 = Committing Peer (`peer1.orgN`); lifecycle commands run against `peer0`; anchor peers are the Committing Peers | Verified by another team | same |
| State lands in YSQL as **schema per channel, table per chaincode** (`mychannel.<ccname>`), columns `block_number, transaction_number, key bytea, db_metadata bytea, db_value jsonb`; key = `0x64 'd' + <ccname> + 0x00 + <key>` | Verified by another team | same |
| Chaincode builder image is `npcioss/drunix-ccenv:1.0` (**tag 1.0, not 1.0.0**) and is not auto-pulled | Verified by another team | settlemint-drunix README |
| YugabyteDB cold start can exceed the script's 30 s sleep; peers then exit once with `connection refused` on 5433 and must be restarted | Verified by another team | same |
| Chaincode events are delivered by a peer that has the blocks → **use the Committing Peer for events** | [VERIFY] (inferred from "Lite Peers neither consume blocks") | — |
| Range queries (`GetStateByRange`) work on the SQL state DB | [VERIFY] | — |
| Host ports: `peer0.org1:7051`, `peer0.org2:9051`; Committing Peers on `706x` / `906x`; YSQL on 5433 per org | [VERIFY] read `compose/compose-test-net.yaml` | — |
| Go version inside `drunix-ccenv:1.0` | [VERIFY] `docker run --rm npcioss/drunix-ccenv:1.0 go version` | — |

The first agent to touch each [VERIFY] row records the answer in `docs/DEVIATIONS.md` and updates `ledger/README.md`.

## 2. Folder layout

```
ledger/
├── README.md
├── Makefile                   up, down, deploy, test, bench, run, run-mock
├── network/
│   ├── qs-net.sh              wrapper around drunix-network/test-network/network.sh
│   ├── qs-env.sh              exports PATH, FABRIC_CFG_PATH, peer addresses, crypto paths
│   └── collections.json       [BUILD] private data collection config
├── drunix/                    git-ignored clone of github.com/npci/drunix (never committed: contains generated keys)
├── chaincode/
│   ├── go.mod                 module github.com/<team>/queueshield/ledger/chaincode
│   ├── main.go                contractapi.NewChaincode(&PayState{}, &Advisory{}, &DecisionLog{})
│   ├── logic/                 pure Go: types, transitions, validation (no Fabric imports)
│   │   ├── types.go
│   │   ├── transitions.go
│   │   └── transitions_test.go
│   ├── paystate.go
│   ├── advisory.go
│   ├── decisionlog.go
│   └── errors.go
├── testdata/
│   └── transitions.json       golden vectors shared by Go tests and the TS mock
├── gateway/
│   ├── package.json           node 20, typescript, fastify, @hyperledger/fabric-gateway, @grpc/grpc-js, pg, ajv
│   ├── src/
│   │   ├── main.ts            mode switch live|mock
│   │   ├── config.ts
│   │   ├── fabric.ts          connections, identities, submit/evaluate with retries
│   │   ├── events.ts          chaincode event listener + checkpointer + SSE ring buffer
│   │   ├── readmodel.ts       YSQL queries (live) / memory (mock)
│   │   ├── tat.ts             TAT sweeper
│   │   ├── mock/ledger.ts     in-memory ledger with identical behaviour
│   │   ├── mock/transitions.ts  TS port of logic/transitions.go
│   │   ├── routes.ts          REST + SSE per contracts/CONTRACTS.md §4
│   │   └── validate.ts        ajv against contracts/schemas
│   └── test/
└── bench/
    └── bench.ts               P8 benchmark -> data/ledger_bench.json
```

## 3. Bringing the network up (`network/qs-net.sh`)

Prerequisites: Linux or WSL2 (Ubuntu 22.04+), Docker (Desktop with WSL2 backend on Windows), Go, jq, Node 20, bash 4+. Never run the network from Git-Bash on Windows; use a WSL2 shell (removes the MSYS path problems other teams hit).

| Command | Does |
|---|---|
| `doctor` | Checks docker, go, jq, node, bash ≥4, free RAM ≥ 6 GB, that `drunix/` exists; pulls `npcioss/drunix-ccenv:1.0` if missing; prints `go version` inside ccenv |
| `clone` | `git clone https://github.com/npci/drunix.git drunix` (pin the commit in `ledger/README.md` after the first success) |
| `build-tools` | Builds `peer`, `configtxgen`, `configtxlator`, `cryptogen`, `osnadmin` (`make` targets or `go install` fallback) into `drunix/drunix-network/bin` |
| `up` | `cd drunix/drunix-network/test-network && ./network.sh up -s yugabyte`; then poll `docker exec yugabyte-orgN yugabyted status` until YSQL is ready (timeout 300 s); restart any of `lp1.orgN`, `cp.orgN`, `vs1.orgN`, `orderer.example.com` that exited; print `docker ps` table; fail if fewer than 11 containers are running |
| `create-channel` | `./network.sh createChannel -c mychannel` |
| `deploy` | `./network.sh deployCC -c mychannel -ccn queueshield -ccp <abs path to ledger/chaincode> -ccl go -ccv <ver> -ccs <seq> -ccep "AND('Org1MSP.peer','Org2MSP.peer')"` |
| `upgrade` | Same as deploy with incremented `-ccv`/`-ccs` |
| `invoke <fn> <json-args>` / `query ...` | `./network.sh cc invoke|query -c mychannel -ccn queueshield -ccic|-ccqc '{"Args":[...]}'` |
| `sql "<query>"` | `docker exec -it yugabyte-org1 sh -c "PGPASSWORD=yugabyte ysqlsh -h \$(hostname) -U yugabyte -d yugabyte -c '<query>'"` (the `-h $(hostname)` form is required) |
| `status` | container table + grep logs for `panic|fatal|ERRO` |
| `down` | `./network.sh down` and remove the gateway checkpoint file |
| `bootstrap` | `doctor → up → create-channel → deploy` |

Acceptance: `bootstrap` on a clean machine ends with 11 running containers, `queueshield` committed on `mychannel`, and `invoke paystate:OpenUnknown` + `query paystate:GetStatus` round-tripping a record; the row is visible with `sql "select encode(key,'escape'), db_value from mychannel.queueshield limit 5;"`.

Security: `drunix/` contains generated private keys under `test-network/organizations` — it is git-ignored and never copied into images except as a read-only mount into the gateway.

## 4. Chaincode `queueshield`

### 4.1 Packaging

- One chaincode, three contracts registered with names `paystate`, `advisory`, `decisionlog`: `contractapi.NewChaincode(&PayState{Contract: contractapi.Contract{Name: "paystate"}}, &Advisory{...Name: "advisory"}, &DecisionLog{...Name: "decisionlog"})`. Functions are invoked as `paystate:OpenUnknown`.
- One chaincode means one YSQL table: `mychannel.queueshield`.
- Library: `github.com/hyperledger/fabric-contract-api-go` (v1.2.x for Go ≥1.20, or v2 if ccenv Go ≥1.21) [VERIFY against ccenv Go]. Pin in `go.mod`, run `go mod vendor` so the build needs no network inside ccenv.
- Constants (in `logic/types.go`): `AuthorityMSP = "Org1MSP"`, `RemitterMSP = "Org1MSP"`, `BeneficiaryMSP = "Org2MSP"`. In the 3-org [STRETCH] these become `Org3MSP` for authority.

### 4.2 Keys and documents

| Key | Document | Notes |
|---|---|---|
| `PAY~<txnRef>` | `ledger_payment.schema.json`, `docType:"payment"` | txnRef = `<run_id>:<payment_id>` |
| `ADV~<id>` | `advisory.schema.json`, `docType:"advisory"` | |
| `DEC~<id>` | `ledger_decision.schema.json`, `docType:"decision"` | append-only |

Store JSON with Go structs (fixed field order). Field names are camelCase exactly as in the schemas. Integers are unix seconds from `GetTxTimestamp()` (`.Seconds`), plus the caller's `simMs` where the schema says so.

### 4.3 Payment state machine (single source of truth; mirrored in `testdata/transitions.json`)

| From \ Input | DEBIT (Org1) | CREDIT (Org2) | FAILURE_REMITTER (Org1) | FAILURE_BENEFICIARY (Org2) | REVERSAL (Org2) |
|---|---|---|---|---|---|
| UNKNOWN | DEBITED; set debitAt, tatDeadline = debitAt + tatSeconds | SUCCESS; debitImplied = true, creditAt | FAILED_NO_DEBIT (terminal) | CREDIT_FAILED; debitImplied = true, tatDeadline set | REVERSED; debitImplied = true |
| DEBITED | no-op (duplicate) | SUCCESS (terminal) | DISPUTED("debit then remitter failure") | CREDIT_FAILED | REVERSED (terminal) |
| CREDIT_FAILED | no-op | DISPUTED("credit after credit failure") | DISPUTED | no-op | REVERSED (terminal) |
| SUCCESS | no-op | no-op | DISPUTED | DISPUTED | DISPUTED("reversal after success") |
| FAILED_NO_DEBIT | DISPUTED("debit after failure") | DISPUTED | no-op | DISPUTED | DISPUTED |
| REVERSED | DISPUTED | DISPUTED("credit after reversal") | DISPUTED | no-op | no-op |
| DISPUTED | no-op (appends attestation) | no-op (appends) | no-op (appends) | no-op (appends) | no-op (appends) |

Rules:
1. Every non-no-op transition appends `{mspId, kind, at, simMs, reasonCode}` to `attestations`, increments `version`, and emits **one** `PaymentUpdated` event.
2. A **no-op** writes nothing and emits nothing; the function returns the current record with `noop=true` (the gateway reports it).
3. Wrong MSP for the input kind → error `QS_ERR_FORBIDDEN` (no state change).
4. Terminal states: SUCCESS, FAILED_NO_DEBIT, REVERSED. DISPUTED is terminal for automation and flagged for humans.
5. `CREDIT` from UNKNOWN is accepted (a credit cannot exist without a debit) to avoid deadlock when attestations from two orgs race; `debitImplied` records it.

### 4.4 Functions

```go
// paystate
func (c *PayState) OpenUnknown(ctx contractapi.TransactionContextInterface,
    txnRef, idemKeyHash, payerPsp, remitterBank, beneficiaryBank, runId string,
    simMs int64, tatSeconds int64) (*logic.Payment, error)
// - caller MSP must be RemitterMSP (payer side)
// - validate formats (regex as in schema), banks B1..B5, psp P1..P3, tatSeconds in [10, 86400]
// - if PAY~txnRef exists: identical (idemKeyHash, parties, runId) -> return existing, no write;
//   different -> QS_ERR_CONFLICT
// - else write state UNKNOWN, openedAt = txTimestamp, version 1; SetEvent("PaymentUpdated", {kind:"OPEN", ...})

func (c *PayState) AttestDebit(ctx, txnRef string, simMs int64) (*logic.Payment, error)
func (c *PayState) AttestCredit(ctx, txnRef string, simMs int64) (*logic.Payment, error)
func (c *PayState) AttestFailure(ctx, txnRef, leg, reasonCode string, simMs int64) (*logic.Payment, error) // leg: REMITTER|BENEFICIARY
func (c *PayState) AttestReversal(ctx, txnRef string, simMs int64) (*logic.Payment, error)
// - load PAY~txnRef or QS_ERR_NOT_FOUND
// - check MSP for the kind (table 4.3)
// - next, noop, disputedReason := logic.Apply(record, kind, mspId, txSeconds, simMs, reasonCode)
// - if !noop: PutState, SetEvent("PaymentUpdated", payload)

func (c *PayState) GetStatus(ctx, txnRef string) (*logic.Payment, error)          // evaluate only
func (c *PayState) CheckTAT(ctx, txnRef string) (*logic.Payment, error)
// - if state in {DEBITED, CREDIT_FAILED} && !tatBreached && txSeconds > tatDeadline:
//     tatBreached = true; version++; SetEvent("TATBreach", {...}); else no-op

// advisory
func (c *Advisory) IssueAdvisory(ctx, advisoryJSON string) (*logic.Advisory, error)
// - caller MSP must be AuthorityMSP; parse and validate (kind enum, segmentId regex, validForSec in [5,3600], evidenceHash format)
// - ADV~id must not exist -> else QS_ERR_CONFLICT
// - issuedAt = txSeconds; expiresAt = issuedAt + validForSec; revoked=false; issuerMspId = caller
// - SetEvent("AdvisoryIssued", record)
func (c *Advisory) RevokeAdvisory(ctx, id, reason string) (*logic.Advisory, error)  // authority only; sets revoked
func (c *Advisory) GetAdvisory(ctx, id string) (*logic.Advisory, error)
func (c *Advisory) ListActive(ctx) ([]*logic.Advisory, error)
// - GetStateByRange("ADV~", "ADV~\uffff") [VERIFY on SQL state DB]; filter !revoked && expiresAt > txSeconds
//   (evaluate-only: txSeconds = proposal timestamp); sort by id for determinism

// decisionlog
func (c *DecisionLog) RecordDecision(ctx, decisionJSON string) (*logic.Decision, error)  // authority only; DEC~id unique
func (c *DecisionLog) GetDecision(ctx, id string) (*logic.Decision, error)
```

Errors are returned as `fmt.Errorf("QS_ERR_<CODE>: %s", detail)` with codes `BAD_ARG`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `INTERNAL`. The gateway maps them to HTTP 400, 403, 404, 409, 500.

### 4.5 Determinism checklist (reviewed before every deploy)

- [ ] No `time.Now()`; only `ctx.GetStub().GetTxTimestamp()`.
- [ ] No randomness, no goroutines, no network or file access.
- [ ] No iteration over Go maps when building outputs or events.
- [ ] One `SetEvent` per transaction path.
- [ ] Errors do not include non-deterministic data.

### 4.6 Endorsement and identity

- Chaincode endorsement policy `AND('Org1MSP.peer','Org2MSP.peer')`: both orgs' Lite Peers simulate every write, so neither org can write a fact the other's peer did not compute. The Fabric Gateway collects both endorsements automatically.
- Caller authorisation is inside chaincode via `ctx.GetClientIdentity().GetMSPID()` (who **submitted**), per table 4.3.
- [BUILD] State-based endorsement on `PAY~` keys so a CREDIT attestation additionally requires Org2's peer endorsement only; not needed for the pitch.

### 4.7 Private data [BUILD]

Collection `payPrivate` (`policy: OR('Org1MSP.member','Org2MSP.member')`, `requiredPeerCount: 0`, `maxPeerCount: 1`, `blockToLive: 0`, `memberOnlyRead: true`) holding `{txnRef, payerRef, payeeRef}` synthetic references passed via transient data; the public record keeps only hashes. Deploy with `-cccg network/collections.json`. Demonstrates KeyDB transient store use. Not needed for the pitch.

### 4.8 Chaincode tests

1. `logic/transitions_test.go` iterates `testdata/transitions.json` (every cell of table 4.3, plus wrong-MSP cases) and asserts next state, noop flag, disputed reason, version increment.
2. Format validation tests for every argument (bad txnRef, bad bank, tatSeconds out of range).
3. Idempotency: OpenUnknown twice identical → one write; with different idemKeyHash → CONFLICT.
4. Live smoke (`make smoke`, network up): open → debit → credit → GetStatus = SUCCESS; advisory issue → ListActive contains it; revoke → absent; decision record → get.

## 5. Gateway service (`gateway/`, TypeScript)

### 5.1 Connections

| Purpose | Peer | Identity | Notes |
|---|---|---|---|
| Submit/evaluate as payer side + authority | `peer0.org1` (Lite Peer) | `User1@org1.example.com` | TLS CA from `organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt`; `grpc.ssl_target_name_override = peer0.org1.example.com` |
| Submit as payee side | `peer0.org2` (Lite Peer) | `User1@org2.example.com` | same pattern for org2 |
| Chaincode events | `peer1.org1` (Committing Peer) [VERIFY]; fallback `peer0.org1` | Org1 user | if events fail on peer1 gateway, try peer0; record which works |

Identity material: cert `users/User1@orgN.example.com/msp/signcerts/*.pem`, key `.../msp/keystore/*_sk`. Use `signers.newPrivateKeySigner(crypto.createPrivateKey(pem))`, `hash.sha256`. One `grpc.Client` per endpoint, shared by Gateway connections. Gateway options: `evaluateOptions: deadline 5 s`, `endorseOptions: 15 s`, `submitOptions: 5 s`, `commitStatusOptions: 60 s`.

### 5.2 Write path

1. Validate the HTTP body against its schema (ajv, strict). Reject with 400 `SCHEMA_INVALID`.
2. Serialize writes per key in-process: a keyed async mutex on `txnRef` (and on `ADV~id`, `DEC~id`) so two attestations for the same payment never race inside the gateway.
3. `contract.submitAsync('paystate:AttestCredit', {arguments: [...]})`, then `await commit.getStatus()`.
4. If `status.code === StatusCode.MVCC_READ_CONFLICT` (or the error is an `EndorseError` mentioning MVCC), retry up to 5 times with jittered backoff 50–400 ms. Count retries in metrics.
5. On success, parse the returned record; respond with record, `tx_id`, `block_number`, `noop`.
6. Map chaincode error prefixes to HTTP codes (§4.4).

### 5.3 Event path

```ts
const checkpointer = await checkpointers.file('/data/ledger_checkpoint.json');
while (running) {
  const events = await network.getChaincodeEvents('queueshield', { checkpoint: checkpointer, startBlock: BigInt(0) });
  try {
    for await (const ev of events) {
      const msg = toLedgerEvent(ev);           // ledger_event.schema.json; event_id = `${ev.transactionId}:${ev.eventName}`
      ring.push(msg); sse.broadcast('ledger_event', msg);
      readModel.apply(msg);                    // live: optional cache; mock: the store
      await checkpointer.checkpointChaincodeEvent(ev);
    }
  } catch (e) { log.warn('event stream dropped', e); await sleep(backoff()); } finally { events.close(); }
}
```

Event lag (commit → SSE) is measured and reported in `/v1/metrics` and the benchmark.

### 5.4 Read model

- **Live:** `pg` client to Org1's YSQL [VERIFY host/port; default `localhost:5433`, user/password `yugabyte`]. Example queries:
  - `select db_value from mychannel.queueshield where db_value->>'docType'='payment' and db_value->>'runId'=$1 and db_value->>'state'=$2 limit $3;`
  - TAT candidates: `select db_value->>'txnRef' from mychannel.queueshield where db_value->>'docType'='payment' and db_value->>'state' in ('DEBITED','CREDIT_FAILED') and (db_value->>'tatBreached')::boolean = false and (db_value->>'tatDeadline')::bigint < extract(epoch from now());`
  - Counts for the console: `select db_value->>'state' s, count(*) from mychannel.queueshield where db_value->>'docType'='payment' and db_value->>'runId'=$1 group by 1;`
  - These queries are **read-only** and outside consensus; any decision that matters still goes through chaincode.
- **Fallback (and mock):** in-memory maps updated from the event stream.

### 5.5 TAT sweeper

Every 5 s (live): run the TAT-candidate query; for each txnRef call `paystate:CheckTAT` (submit). The chaincode re-checks against its own tx timestamp, so a stale query can never cause a false breach. Disabled in mock (the mock checks deadlines itself every 1 s).

### 5.6 Network info

`/v1/network` returns static topology from config (peers, orderer, state DB names) plus `height` from `qscc:GetChainInfo` (evaluate, decode `common.BlockchainInfo` with `@hyperledger/fabric-protos`) [VERIFY qscc available through Gateway on Drunix; fallback: last seen block number from events], plus submit latency percentiles from metrics.

## 6. Mock gateway (`LEDGER_MODE=mock`) — ship on Day 1

- Same routes, same schemas, same status codes, same event names; every ledger event carries `"mock": true`.
- `mock/transitions.ts` is a line-by-line port of `logic/transitions.go`, tested against the same `testdata/transitions.json`.
- Simulated commit latency: lognormal with p50 120 ms, p95 400 ms (replace with measured values from `data/ledger_bench.json` once available). Block numbers increase by one per 50 ms batch window.
- Advisory expiry and TAT deadlines use wall-clock seconds exactly like the chaincode.
- `POST /v1/admin/reset` clears state (mock only).

## 7. Benchmark (hypothesis P8) — `bench/bench.ts`

| Step | Detail |
|---|---|
| Workloads | (a) OpenUnknown only; (b) Open + Debit + Credit per payment; (c) GetStatus evaluate |
| Offered rates | 10, 25, 50, 100, 200 tx/s, 60 s each, 10 s warm-up, 3 repetitions |
| Measures | submit latency p50/p95/p99, evaluate latency, event lag, MVCC retries, error counts, highest rate with p99 submit < 2 s and no growing backlog |
| Variants | [STRETCH] a second Lite Peer per org (compose override cloning `lp1.orgN`, `CORE_PEER_LITEPEER_ENABLED=true`) to show read scale-out |
| Output | `data/ledger_bench.json` (schema in CONTRACTS §6), plus a CSV for the report; machine spec recorded (CPU, RAM, OS, Docker version) |

Report the numbers as "local Drunix test network on <machine>", never as production capacity.

## 8. Acceptance tests (Definition of Done)

| ID | Test | [PITCH] / [BUILD] |
|---|---|---|
| L1 | `qs-net.sh bootstrap` reaches 11 healthy containers and a committed `queueshield` | PITCH |
| L2 | All golden transition vectors pass in Go and in the TS mock | PITCH |
| L3 | Gateway live: open → debit → credit returns SUCCESS and emits exactly 3 `PaymentUpdated` events on `/v1/stream` | PITCH |
| L4 | Concurrent DEBIT and CREDIT on one txnRef (fired together 100 times) never lose an attestation; final state SUCCESS; MVCC retries counted | PITCH |
| L5 | Advisory issue/list/revoke round trip; non-authority MSP gets 403 | PITCH |
| L6 | Decision record is immutable (second write same id → 409) | PITCH |
| L7 | SSE resume with `Last-Event-ID` replays missed events; restart of the gateway resumes from the file checkpoint without duplicates | PITCH |
| L8 | Every response validates against its schema (contract tests) | PITCH |
| L9 | TAT: a DEBITED payment with tatSeconds=20 and no credit emits `TATBreach` within 30 s | BUILD |
| L10 | Benchmark writes `data/ledger_bench.json` | BUILD (a first quick run is PITCH-nice-to-have) |
| L11 | Private collection deployed; public record holds hashes only | STRETCH |

## 9. Day-by-day (pitch sprint)

| Day | Tasks | Gate |
|---|---|---|
| 1 (Tue 20) | `doctor`, `clone`, `up`, `create-channel`, deploy the sample `basic`; resolve every [VERIFY] you can; write `logic/` + golden vectors; **ship the mock gateway** with all routes | L1 with `basic`; mock passes contract tests |
| 2 (Wed 21) | Chaincode paystate/advisory/decisionlog; deploy; gateway live write path + events | L2, L3, L5, L6 |
| 3 (Thu 22) | Integration with M2 and M4; keyed mutex + MVCC retries; `/v1/network`; event checkpointing | L4, L7, L8 |
| 4 (Fri 23) | Quick benchmark at 10/25/50 tx/s for the deck; screenshots of `docker ps`, a YSQL query, and events | first `ledger_bench.json` |
| 5 (Sat 24) | Freeze; rehearse network bring-up from scratch twice; record a terminal video as backup | bring-up < 10 min |

## 10. Pitfalls (each one has bitten someone)

1. `npcioss/drunix-ccenv:1.0` must be pulled manually; tag `1.0`, not `1.0.0`.
2. YugabyteDB slow start → peers exit with `connection refused 5433`; wait for `yugabyted status`, then restart the exited containers.
3. On Windows use a WSL2 shell, not Git-Bash; otherwise `MSYS_NO_PATHCONV` tricks are needed for `up/down` and must be unset for every other command.
4. Lite Peers do not commit blocks: do not read events from them unless verified.
5. Only one chaincode event per transaction survives.
6. Concurrent writes to one key fail MVCC at commit: serialise per key in the gateway and retry.
7. Never commit `drunix/` or anything under `organizations/` — it holds private keys.
8. Chaincode `go.mod` Go version must not exceed the ccenv Go version; vendor dependencies.
9. Chaincode name becomes the YSQL table name: keep it lower-case `queueshield`.
10. Upgrading chaincode needs a new sequence number; keep `-ccs` in `Makefile` state.

## 11. Contribution back to Drunix (optional, encouraged by the hackathon)

- A sample `asset-transfer`-style chaincode for **attested multi-party payment state** with golden vectors.
- A documented fix for the YugabyteDB readiness race in `network.sh` (poll instead of fixed sleep).
- A Lite Peer scale-out benchmark script.
Propose through the repository's CONTRIBUTING guidelines; list links in the README.

## 12. Agent prompt template

```
You are the M1 Ledger agent for QueueShield. Read AGENTS.md, docs/00_PRODUCT.md §1–4, docs/01_SYSTEM.md,
contracts/CONTRACTS.md §4–§6 and docs/M1_LEDGER.md in full. Work only in ledger/.
Task: <one row from §9 or one acceptance test from §8>.
Write tests first (golden vectors, contract tests), then code. Respect the determinism checklist §4.5.
For every [VERIFY] you resolve, append one line to docs/DEVIATIONS.md.
Finish by running `make test` (and `make smoke` if the network is up) and report results honestly.
```
