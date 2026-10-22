# Live (Drunix) implementation: not started

Files to add here, per docs/M1_LEDGER.md §5 (spec folder):

| File | Job |
|---|---|
| `fabric.ts` | gRPC clients to `peer0.org1` / `peer0.org2` (Lite Peers), identities `User1@orgN`, submit/evaluate with deadlines (evaluate 5 s, endorse 15 s, submit 5 s, commitStatus 60 s); MVCC retry up to 5x with 50-400 ms jitter |
| `events.ts` | `network.getChaincodeEvents('queueshield', {checkpoint})` from the **Committing Peer** [VERIFY], file checkpointer `/data/ledger_checkpoint.json`, publish `ledger_event` on the shared `SseHub` |
| `readmodel.ts` | YSQL read model (`pg` to `localhost:5433` [VERIFY]) for `GET /v1/payments`, TAT candidates and counts |
| `tat.ts` | every 5 s: TAT-candidate query -> `paystate:CheckTAT` submit |
| `ledger.ts` | a class with the same methods as `mock/ledger.ts` so `routes.ts` can switch on `LEDGER_MODE` |

Dependencies to add then (pin exact versions, note in docs/DEVIATIONS.md): `@hyperledger/fabric-gateway`,
`@grpc/grpc-js`, `@hyperledger/fabric-protos`, `pg`.

Until this exists `routes.ts` refuses `LEDGER_MODE=live` instead of faking a ledger (docs/01_SYSTEM.md §10).
