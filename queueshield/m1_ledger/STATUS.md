# M1 Ledger — status (updated 2026-10-20)

Legend: ✅ done and verified by a test that was run · 🟡 built, not verified · ⬜ not started.

## Done

| Item | State | Evidence |
|---|---|---|
| Golden vectors copied to `testdata/transitions.json` (70 cases) | ✅ | |
| TS state machine (mock) passes every vector | ✅ | `npm test` → golden vectors |
| **Mock gateway shipped** (Day-1 gate): every route in CONTRACTS §4, same codes, `mock: true` on events | ✅ | `npm test`: L3, L4, L5, L6, L7 (mock part), L8 |
| SSE ring + Last-Event-ID replay + `reset` + heartbeat | ✅ | L7 mock part |
| Keyed mutex per key (no lost attestations under concurrency) | ✅ | L4: 100 concurrent DEBIT+CREDIT pairs |
| Mock TAT sweeper (every 1 s) | 🟡 | logic tested (`checkTat`); sweeper loop not tested |
| Used by M4 live | ✅ | integration smoke 2026-10-20: advisories and decisions written by the auto operator |
| Go `logic/` state machine + golden-vector test | 🟡 | written; **not run — Go is not installed on the dev machine** |
| Go contracts `paystate`, `advisory`, `decisionlog` | 🟡 | written to §4.4; **not compiled** |
| `network/qs-net.sh` (doctor/clone/up/create-channel/deploy/sql/status/down/bootstrap) | 🟡 | written to §3; **not run** (needs WSL2 + Docker) |
| Gateway typecheck (`tsc --noEmit`), `npm audit` clean | ✅ | fastify 5.12.7, ajv 8.20.0 |

## Open items (summary — the detailed task cards are in `ROADMAP.md`), in day order (§9)

1. **Day 1:** on a WSL2 machine with ≥ 16 GB: `qs-net.sh doctor` → `clone` → `up` → `create-channel`; deploy the sample `basic` (L1). Resolve every `[VERIFY]` in §1 and append to `../docs/DEVIATIONS.md`: Go version in `drunix-ccenv:1.0` (then pick `fabric-contract-api-go` v1.2.x or v2 in `go.mod`, `go mod vendor`), host ports, events on the Committing Peer, range queries on YugabyteDB.
2. Run `go test ./logic/...` (L2 Go side) and fix whatever the compiler finds in the contract files.
3. **Day 2:** deploy `queueshield`; live gateway write path (`src/live/fabric.ts`), events (`events.ts` with file checkpointer), L3 live.
4. **Day 3:** MVCC retries (5×, 50–400 ms jitter) + metrics, `/v1/network` from `qscc:GetChainInfo`, YSQL read model, L4/L7 live.
5. **Day 4:** `bench/bench.ts` at 10/25/50 tx/s → `data/ledger_bench.json` (L10; M2's ledger model reads it); screenshots of 11 containers + a YSQL query.
6. L9 TAT live (needs `tat.ts` sweeper calling `paystate:CheckTAT`).
7. [STRETCH] private data collection `payPrivate` (L11), Org3 authority.

## Known issues / decisions
- `disputedReason` is not a field of the stored payment record (schema has `additionalProperties: false`); it travels only in the `PaymentUpdated` event payload. DISPUTED append-only transitions emit no event (golden vectors), although spec §4.3 rule 1 says every non-no-op emits one — the vectors win.
- Mock-only header `X-QS-As-Msp` lets tests act as another org (403 paths). The live gateway picks identities itself and must ignore it.
- `routes.ts` refuses `LEDGER_MODE=live` until `src/live/` exists — it never fakes a ledger.

## Reused from the IBM project
Nothing — the IBM project had no ledger. Everything here is new.
