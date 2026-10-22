# M1 Ledger — roadmap: what is left, what to add, in what order

Written 2026-10-20 after reviewing the code, `SPEC.md`, the public Drunix repository, three competing Drunix hackathon
projects and outside research (`../docs/RESEARCH.md`). Read `CLAUDE.md` first for how to work; this file says **what**.

**Deadlines:** pitch **Sun 25 Oct** (**P0**) · build 10–22 Nov (**P1**) · finale 4 Dec (**P2**).

## 1. Where M1 stands

Done and tested: the **mock gateway** (every route in CONTRACTS §4, SSE ring with Last-Event-ID, keyed mutex, lognormal
commit latency, TAT sweep) passes all 70 golden vectors and L3–L8 (mock). M4 used it live in the 2026-10-20 smoke.
Written but **never compiled or run** (no Go/Docker on the dev machine): Go `logic/` + golden-vector test, the three Go
contracts, `network/qs-net.sh`. **Not started:** the live Fabric/Drunix gateway (`gateway/src/live/`), benchmark.
**The pitch's Definition of Done needs "a real Drunix network running queueshield"** — this is the module with the
highest infrastructure risk (spec risk register: "Drunix will not start: High likelihood, High impact").

## 2. Facts to keep in mind (from research, 2026-10-20)

- The public `npci/drunix` repo had **no published release** and 9 open issues when checked; the architecture doc does
  **not** describe client-facing chaincode events, range queries on the SQL state DB, or Gateway behaviour. Every
  `[VERIFY]` in `SPEC.md` §1 is still open — expect surprises and record each answer in `../docs/DEVIATIONS.md`.
- The architecture doc confirms: Lite Peers are stateless endorsers that relay CommitStatus to the Committing Peer; the
  Committing Peer validates via the stateless Validation Service (round-robin) and commits to the state DB
  (YugabyteDB supported); private data lives in the per-org KeyDB transient store. Lite Peers and Validation Services
  scale horizontally — a benchmark of Lite Peer scale-out is a legitimate contribution.
- Competitor **Pulse** (cs25b1074-stack/citi) already does per-bank signed payment transitions with SLA → STUCK, a
  regulator org (Org3) and WebSocket push with `lastSeq` replay. Our ledger must therefore not be pitched as "a stuck
  payment ledger" — the differentiator is the network level (advisories, decisions, check budgets) on the same chain.

## 3. Tasks

### M1-T01 · Bring the Drunix network up (L1) [P0, Day 1–2, highest risk]
- **Where:** a teammate's Linux or WSL2 machine with ≥ 16 GB RAM, Docker, Go, jq, Node 20+ (never Git-Bash).
- **Steps:** `./network/qs-net.sh doctor` → `clone` (pin the commit in `README.md`) → `build-tools` if needed → `up`
  (waits for YugabyteDB, restarts exited peers, fails if < 11 containers) → `create-channel` → deploy the sample `basic`
  chaincode first. Record every `[VERIFY]` answer (Go version in `npcioss/drunix-ccenv:1.0`, host ports for
  `peer0/peer1.orgN`, YSQL port) in `../docs/DEVIATIONS.md`.
- **Done when:** 11 containers healthy; `basic` invoke/query round-trips; screenshot of `docker ps` saved for the deck.
- **Fallback (spec risk register):** keep everyone on the mock; ask the organisers; apply the known fixes (ccenv tag 1.0,
  YugabyteDB wait).

### M1-T02 · Compile and test the chaincode (L2 Go side) [P0, ~0.5 day] ✅ done 2026-10-21
- Set `go.mod`'s Go version and `fabric-contract-api-go` (v1.2.x for Go ≥ 1.20, v2 for ≥ 1.21) to match the ccenv Go;
  `go mod tidy && go mod vendor`; `go test ./logic/...` must pass every golden vector (the TS port already does).
  Fix whatever the compiler finds in `paystate.go` / `advisory.go` (they were written blind).
- **Done when:** `go test ./logic/...` green; `go vet ./...` clean; deterministic checklist (SPEC §4.5) reviewed.

### M1-T03 · Deploy `queueshield` and the live write path (L3) [P0, ~1 day]
- `qs-net.sh deploy` with `-ccep "AND('Org1MSP.peer','Org2MSP.peer')"`. Then implement `gateway/src/live/`
  (plan in `gateway/src/live/README.md`): `fabric.ts` (grpc clients to the Lite Peers, `User1@orgN` identities,
  submit/evaluate with deadlines), and a `LiveLedger` class with the **same methods as `mock/ledger.ts`** so
  `routes.ts` only switches implementations. Pin `@hyperledger/fabric-gateway`, `@grpc/grpc-js`,
  `@hyperledger/fabric-protos` exactly; `npm audit`.
- **Done when:** L3 live: open → debit → credit returns SUCCESS and exactly 3 `PaymentUpdated` events on `/v1/stream`;
  the same route tests pass against live with a `LEDGER_TEST_URL` switch.

### M1-T04 · Chaincode events with a checkpointer (L7 live) [P0, ~0.5 day]
- `events.ts`: `network.getChaincodeEvents('queueshield', {checkpoint})` from the **Committing Peer** (try the Lite
  Peer if events do not arrive; record which works); file checkpointer `/data/ledger_checkpoint.json`; publish through the
  existing `SseHub`. Measure event lag (commit → SSE) and expose it in `/v1/metrics`.
- **Done when:** restart the gateway mid-stream and it resumes from the checkpoint without duplicates (L7).

### M1-T05 · Concurrency and MVCC (L4 live) [P0, 2 h]
- Keep the keyed mutex; retry `MVCC_READ_CONFLICT` up to 5× with 50–400 ms jitter; count retries in `/v1/metrics`.
- **Done when:** 100 concurrent DEBIT+CREDIT pairs end SUCCESS with no lost attestation on the live network.

### M1-T06 · `/v1/network` from the chain + YSQL read model [P0, ~0.5 day]
- Block height via `qscc:GetChainInfo` (fallback: last event block); `readmodel.ts` with `pg` against Org1's YSQL for
  `GET /v1/payments` and counts (queries in SPEC §5.4; read-only, outside consensus).
- **Done when:** M5's DrunixPanel shows the real block height; a YSQL query screenshot on `mychannel.queueshield` saved.

### M1-T07 · Quick benchmark (L10 first run) [P0 nice-to-have, Day 4]
- `bench/bench.ts`: workloads open-only, open+debit+credit, GetStatus; offered 10/25/50 tx/s, 60 s each; p50/p95/p99
  submit, evaluate, event lag, MVCC retries; write `data/ledger_bench.json` (schema in CONTRACTS §6) with machine specs.
  M2's ledger model and live demo rate read it.

### M1-T08 · TAT sweeper live (L9) [P1]
- Every 5 s: TAT-candidate YSQL query → `paystate:CheckTAT` submit; chaincode re-checks with its own tx time.

### M1-T09 · Full benchmark P8 incl. Lite Peer scale-out [P1]
- 10–200 tx/s × 3 repetitions; second Lite Peer per org via a compose override (`CORE_PEER_LITEPEER_ENABLED=true`).
  Report as "local Drunix test network on <machine>", never as production capacity.

### M1-T10 · `checkpolicy` contract [P1, from the spec's build plan]
- Put the active check budget per PSP on-chain as a signed policy (M4 writes it), so NPCI-rule compliance is provable.

### M1-T11 · Private data `payPrivate` (L11) and Org3 authority [P2]
- Collection config in `network/collections.json`; public record keeps hashes only; demonstrates the KeyDB transient
  store. Org3 as the authority/regulator (Pulse already has a regulator org — parity).

## 4. Enhancements beyond the spec

| Idea | Why | Effort |
|---|---|---|
| **`AttestBatch`** (one transaction attests N legs) | throughput: unknowns arrive in bursts during a storm; fewer tx → fewer MVCC conflicts | M |
| **Custody query** ("money is with remitter / beneficiary / reversed") derived from attestations | Pulse's best UX idea; one evaluate function, great console chip | S |
| **Compensation counter** (count of TAT-breach days per bank, the RBI Rs 100/day analogue, no money shown) | makes the RBI TAT angle concrete for judges; claims-safe | S |
| **Advisory signature check by PSPs** (M2 verifies `issuerMspId` = authority before obeying) | demonstrates *why* the advisory is on a ledger | S (with M2) |
| **Upstream contribution**: YugabyteDB readiness fix for `network.sh` (poll instead of sleep), sample chaincode with golden vectors | the hackathon encourages contributions; low effort once M1-T01 works | S |

## 5. Open questions
1. Which teammate's machine hosts Drunix for the demo (≥ 16 GB, WSL2/Linux)? Decide today.
2. If live events from the Committing Peer fail, is the spec's fallback (gateway polls `GetStatus` for open unknowns at a low rate) acceptable for the pitch? (Spec says yes, documented.)

## 6. This week

| Day | Do | Gate |
|---|---|---|
| Tue 20 | M1-T01 doctor/clone/up/channel + `basic`; resolve `[VERIFY]`s | L1 with `basic` |
| Wed 21 | M1-T02, deploy `queueshield`, M1-T03 write path | L2 (Go), L3 live |
| Thu 22 | M1-T04 events, M1-T05 MVCC, M1-T06 network info; M2 live bridge against **live** | **S6 end-to-end on real Drunix** (spec gate) |
| Fri 23 | M1-T07 quick bench; screenshots | first `ledger_bench.json` |
| Sat 24 | rehearse bring-up from scratch twice (< 10 min); record a terminal video as backup | — |
