# M5 Console — instructions for whoever (human or AI agent) works in `m5_console/`

## Read in this order
1. `../AGENTS.md` — binding rules for every module.
2. This file.
3. `STATUS.md` — what exists and is verified.
4. `ROADMAP.md` — the task cards (M5-T01 …) with acceptance checks. **Pick work from here.**
5. `SPEC.md` — the module spec (working copy), esp. §2 layout, §3 panel table, §7 demo script.
   Shared: `../docs/00_PRODUCT.md` §8 (claims policy — binding on every UI string), `../docs/01_SYSTEM.md`,
   `../docs/90_PLAN_EVAL_RISKS.md` §4 (talk track), all of `../contracts/CONTRACTS.md`. Research: `../docs/RESEARCH.md`.

## How to work a task
1. Take the lowest-numbered open P0 card in `ROADMAP.md` unless the lead assigned another. Say which card you took.
2. Baseline: `npm test` (7 passing on 2026-10-20), `npx tsc --noEmit`, `npx vite build`.
3. Build every panel against fixtures (`../contracts/fixtures/`) or recordings first, then against live services.
   Pure logic goes in small `.ts` files with vitest tests (see `src/panels/decisionLogic.ts`).
4. Look at the result in a browser before calling a UI task done (and say if you could not).
5. Update `STATUS.md`, tick the card, log deviations, report in one paragraph with exact commands.

## Hard rules for this module
- Work only in `m5_console/` — plus the root `docker-compose.yml`, root `README.md` and the integration smoke, which
  M5 owns. `../contracts/` is read-only.
- Generate message types from the schemas (`npm run gen:types`); never hand-write a message type.
- No business logic and no metric computation in the UI: if a number is missing, ask the owning module for a field.
- Never fake a ledger number: when M1 is offline, show "ledger offline". Never mix mock and live data in one panel;
  mock data shows a MOCK badge.
- Ground-truth onset markers only in replay/arena views, never in the live view.
- Every user-visible sentence that states a result lives in `src/text/claims.ts`; outcome numbers carry "simulation";
  `tests/claims.test.ts` must pass. Blocked actions can never be selected or sent.
- Pin npm dependencies exactly, run `npm audit`, note new deps in `../docs/DEVIATIONS.md`.
- Commit messages start `M5: `; branch `m5/<short-name>`; do not commit unless asked.

## Environment
Node 24 + npm work on the dev machine; Docker does not (compose is untested). Run the cross-module smoke from the repo
root: `.venv/Scripts/python m5_console/scripts/integration_smoke.py --seconds 170`.

## Prompt to give a coding agent
```
You are the M5 Console agent for QueueShield. Work only in queueshield/m5_console/ (plus root docker-compose.yml and README.md).
Read ../AGENTS.md, CLAUDE.md, STATUS.md, ROADMAP.md and SPEC.md in full. Take card <M5-Txx> from ROADMAP.md.
Generate types from contracts; never hand-write one. Tests first; run npm test, npx tsc --noEmit, npx vite build.
Check the UI in a browser. Update STATUS.md and ROADMAP.md. Report honestly with exact commands.
```
