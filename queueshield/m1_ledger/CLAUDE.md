# M1 Ledger — instructions for whoever (human or AI agent) works in `m1_ledger/`

## Read in this order
1. `../AGENTS.md` — binding rules for every module.
2. This file.
3. `STATUS.md` — what exists and is verified (and what was written but never compiled).
4. `ROADMAP.md` — the task cards (M1-T01 …) with acceptance checks. **Pick work from here.**
5. `SPEC.md` — the module spec (working copy), esp. §1 (what is verified about Drunix vs `[VERIFY]`), §3, §4, §10 pitfalls.
   Shared: `../docs/01_SYSTEM.md` §4–§6, `../contracts/CONTRACTS.md` §4–§6. Research: `../docs/RESEARCH.md`.

## How to work a task
1. Take the lowest-numbered open P0 card in `ROADMAP.md` unless the lead assigned another. Say which card you took.
2. Baseline: `cd gateway && npm test` (7 passing on 2026-10-20) and `npx tsc --noEmit`; with Go installed also
   `cd chaincode && go test ./logic/...`.
3. Tests first. The state machine has **one** source of truth: `testdata/transitions.json`. Change
   `chaincode/logic/transitions.go` and `gateway/src/mock/transitions.ts` together; both suites must pass.
4. For live work, keep the mock byte-compatible: the live implementation must expose the same methods as
   `gateway/src/mock/ledger.ts` so `routes.ts` only switches implementations and the same route tests run against both.
5. Update `STATUS.md`, tick the card, record every resolved `[VERIFY]` as one line in `../docs/DEVIATIONS.md`, report in
   one paragraph with exact commands. Never claim a test or a network step worked unless you ran it.

## Hard rules for this module
- Stay inside `m1_ledger/` (plus one line in `../docs/DEVIATIONS.md` or a file in `../contracts/PROPOSALS/`).
- Chaincode determinism checklist before every deploy (SPEC §4.5): no `time.Now()` (use `GetTxTimestamp`), no randomness,
  no goroutines, no network/file access, no Go-map iteration to build outputs, one `SetEvent` per path, deterministic errors.
- Network work in a **WSL2 or Linux shell, never Git-Bash**. YugabyteDB starts slowly: `qs-net.sh up` waits and restarts exited peers.
- **Never commit** `drunix/` or anything under `organizations/` (private keys; git-ignored). The ccenv image tag is `1.0`, not `1.0.0`.
- Never fake ledger data: if live is down, `/v1/health` says degraded and consumers say "ledger offline".
- Pin every npm/Go dependency exactly; run `npm audit` after installs; note new deps in `../docs/DEVIATIONS.md`.
- No amounts, account numbers, VPAs or names in any record, event or log (schemas enforce it).
- Report Drunix numbers as "local Drunix test network on <machine>", never as production capacity.
- Commit messages start `M1: `; branch `m1/<short-name>`; do not commit unless asked.

## Environment
The Windows dev machine has Node 24 (runs the gateway's `.ts` directly) but **no Go and no Docker**: the network and
chaincode tasks (M1-T01..T06) must run on a teammate's Linux/WSL2 machine with ≥ 16 GB RAM.

## Prompt to give a coding agent
```
You are the M1 Ledger agent for QueueShield. Work only in queueshield/m1_ledger/.
Read ../AGENTS.md, CLAUDE.md, STATUS.md, ROADMAP.md and SPEC.md in full. Take card <M1-Txx> from ROADMAP.md.
Tests first (golden vectors, contract tests). Respect the determinism checklist (SPEC §4.5).
For every [VERIFY] you resolve, append one line to ../docs/DEVIATIONS.md. Run npm test (and go test ./logic/...)
before and after; update STATUS.md and ROADMAP.md; report results honestly with exact commands.
```
