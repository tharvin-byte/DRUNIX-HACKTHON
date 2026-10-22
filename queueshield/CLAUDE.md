# QueueShield × Drunix — project instructions

Drunix Hackathon 2026 (NPCI × Citi). Five independent modules, one per owner, one folder each.
**If you were asked to work on one module, go to that folder and follow its `CLAUDE.md`; stay inside the folder.**

## Where everything is
| Need | File |
|---|---|
| Binding rules for every person/agent | `AGENTS.md` |
| A module's whole picture | `m?_*/README.md` → `STATUS.md` → `ROADMAP.md` → `CLAUDE.md` → `SPEC.md` |
| Team plan, Definition of Done, critical path, daily gates | `docs/PROJECT_ROADMAP.md` |
| Product, system architecture, plan/evaluation | `docs/00_PRODUCT.md`, `docs/01_SYSTEM.md`, `docs/90_PLAN_EVAL_RISKS.md` (working copies) |
| Outside research (NPCI rules, Drunix, competitors, papers) | `docs/RESEARCH.md` |
| Interfaces | `contracts/CONTRACTS.md` + `contracts/schemas/` (read-only; changes via `contracts/PROPOSALS/`) |
| Deviations and resolved `[VERIFY]`s | `docs/DEVIATIONS.md` (append one line) |
| What came from the IBM project | `docs/REUSE_MAP.md`; the old code `../OldReferenceAnalagousProject/` is reference only |
| The frozen original spec v1.0 | `../queueshield-spec/queueshield-spec/` (do not edit) |

## Module map
| Module | Folder | Package | Test (from the module folder) |
|---|---|---|---|
| M1 Ledger | `m1_ledger/` | Go `chaincode/`, TS `gateway/` | `cd gateway && npm test` (Go: `cd chaincode && go test ./logic/...`) |
| M2 Simulator | `m2_simulator/` | `qsim` | `../.venv/Scripts/python -m pytest -q` |
| M3 Detection | `m3_detection/` | `qdet` | `../.venv/Scripts/python -m pytest -q` |
| M4 Control | `m4_control/` | `qctl` | `../.venv/Scripts/python -m pytest -q` |
| M5 Console | `m5_console/` | React app | `npm test && npx tsc --noEmit` |
Cross-module: `.venv/Scripts/python m5_console/scripts/integration_smoke.py` from the repo root.

## Working agreements
- Pick work from the module's `ROADMAP.md` card list; when done update `STATUS.md` and tick the card.
- Tests first; never claim a test passed unless it was run; report deviations.
- Do not commit or push unless asked. Commit messages start with the module id (`M3: ...`); branches `m<N>/<short-name>`.

## Environment notes (Windows dev machine)
- Shared venv `.venv` (Python 3.11). TLS interception: pip needs `--trusted-host pypi.org --trusted-host files.pythonhosted.org`.
- Node 24 runs the gateway's `.ts` directly. `make`, Go and Docker are not installed: run Makefile lines by hand;
  Drunix/Go work happens on a teammate's Linux/WSL2 machine.
- Bash heredocs have failed in this shell; write multi-line files with the editor tool. Python file edits: `encoding="utf-8"`.

## Current state (2026-10-20)
All module tests green (67). Highest-priority risks: M2 calibration (every S4 trigger locks the network; blocks the
forecaster, cascade map and arena) and bringing up the real Drunix network (M1-T01). See `docs/PROJECT_ROADMAP.md`.
