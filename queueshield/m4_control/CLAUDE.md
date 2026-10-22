# M4 Control — instructions for whoever (human or AI agent) works in `m4_control/`

## Read in this order
1. `../AGENTS.md` — binding rules for every module.
2. This file.
3. `STATUS.md` — what exists and is verified.
4. `ROADMAP.md` — the task cards (M4-T01 …) with acceptance checks. **Pick work from here.**
5. `SPEC.md` — the module spec (working copy). Shared: `../docs/00_PRODUCT.md`, `../docs/01_SYSTEM.md`,
   `../contracts/CONTRACTS.md` §3–§5. Research: `../docs/RESEARCH.md`.

## How to work a task
1. Take the lowest-numbered open P0 card in `ROADMAP.md` unless the lead assigned another. Say which card you took.
2. Run `../.venv/Scripts/python -m pytest -q` first (19 passing on 2026-10-20).
3. Write the test for the card's **Done when** (fabricate snapshots with `tests/conftest.py::snapshot()` /
   `incident()` so M3 is not needed), then the code. For ledger behaviour use `ModelLedger` or a fake like `FlakyLedger`.
4. Run the full suite and the card's check. Update `STATUS.md`, tick the card, log deviations, report in one paragraph.

## Hard rules for this module
- Stay inside `m4_control/` (plus one line in `../docs/DEVIATIONS.md` or a file in `../contracts/PROPOSALS/`).
  Never import `qsim`/`qdet` or other modules' code (`tests/test_isolation.py`).
- The safety invariants are the point of this module; keep them property-tested (SPEC §9):
  SI-1 never request an attempt for an unknown payment · SI-2 SHIFT_TRAFFIC eligible only if every §4 check passes,
  blocked actions can never be approved · SI-3 no OPERATOR_APPROVED action without a recorded decision ·
  SI-4 degraded monitoring → only HOLD_MONITOR / ESCALATE_HUMAN · SI-5 budgets within [r_min, r_max] ·
  SI-8 every applied action has a rollback condition · SI-9 no advisory without a decision id ·
  SI-10 no amounts/accounts/VPAs/names in any ledger payload.
- Never recommend failover on a bank-side fault. Budgets are load-aware, never from configured capacity alone.
- Use the sim clock of the latest tick for every sim-time field, never wall time. Ledger latency never blocks the operator.
- Rules are data in `config/policy.yaml` with a `rules_version`; change the YAML, not code, to change behaviour, and
  bump `rules_version`.
- Commit messages start `M4: `; branch `m4/<short-name>`; do not commit unless asked.

## Environment
Shared venv `../.venv`; pip needs `--trusted-host …`; no `make`. Live inputs: `DETECT_URL`, `LEDGER_URL`
(M1 mock: `cd ../m1_ledger/gateway && QS_API_KEY=dev LEDGER_MODE=mock node src/main.ts`).

## Prompt to give a coding agent
```
You are the M4 Control agent for QueueShield. Work only in queueshield/m4_control/.
Read ../AGENTS.md, CLAUDE.md, STATUS.md, ROADMAP.md and SPEC.md in full. Take card <M4-Txx> from ROADMAP.md.
Tests first, especially the safety invariants. Run ../.venv/Scripts/python -m pytest -q before and after.
Update STATUS.md and ROADMAP.md. Report results with the exact command, deviations, open questions.
```
