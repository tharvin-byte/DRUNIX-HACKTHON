# QueueShield × Drunix

Drunix Hackathon 2026 (NPCI × Citi), theme Real-Time Payments. All data is synthetic; every outcome number comes from
our simulator and is labelled **simulation**.

**The problem.** When a UPI bank or PSP route slows down, payments time out and their outcome becomes *unknown*. Apps then
ask the NPCI switch for the status again and again and users retry; that load slows the switch, which creates more
timeouts. NPCI attributed the outages of 26 Mar, 2 Apr and 12 Apr 2025 to exactly this (high Check Transaction Status
traffic) and answered with per-bank timers.

**What QueueShield does.** It detects and localises the degrading segment within seconds, forecasts whether it will
lock into a self-sustaining storm if nothing changes, recommends bounded actions (slow retries, defer checks, never
fail over across a shared bank) that **a human approves**, publishes check budgets so verification is never the outage,
and resolves unknown payments from a **shared Drunix ledger**: the bank that knows the outcome attests it once and
every PSP is pushed the answer. Advisories and operator decisions are recorded on the same ledger.

## Open the folder: five systems, one folder each

```
queueshield/
├── m1_ledger/      M1 Ledger      :8004  Go chaincode + TypeScript gateway (Drunix)
├── m2_simulator/   M2 Simulator   :8001  Python — reactive UPI-like network, scenarios, arena
├── m3_detection/   M3 Detection   :8002  Python — features, detectors, localizer, forecaster, incidents
├── m4_control/     M4 Control     :8003  Python — rules, check budgets, decisions, advisories
├── m5_console/     M5 Console     :8000  React/TypeScript — operator UI, replay, integration, demo
├── contracts/      the only shared interface (JSON Schemas + fixtures); read-only, change via contracts/PROPOSALS/
├── docs/           shared docs: product, system, plan, PROJECT_ROADMAP, RESEARCH, DEVIATIONS, REUSE_MAP
├── data/           git-ignored runs, models, recordings
└── AGENTS.md       binding rules for every person and agent
```

Every module folder carries its own documents, so its owner never has to look elsewhere to start:

| File (in each module) | What it is |
|---|---|
| `README.md` | the whole idea in one minute, this module's job, interfaces, code map, how to run |
| `STATUS.md` | what exists today and how it was verified |
| `ROADMAP.md` | **everything left**: task cards (`M2-T01` …) with steps and acceptance checks, enhancements, this week's plan |
| `CLAUDE.md` | instructions for the owner's AI agent: reading order, workflow, hard rules, a ready-to-paste prompt |
| `SPEC.md` | the full module specification (working copy of the v1.0 spec) |

| Module | Owner | Start here |
|---|---|---|
| M1 Ledger | _fill in_ | [README](m1_ledger/README.md) · [STATUS](m1_ledger/STATUS.md) · [ROADMAP](m1_ledger/ROADMAP.md) · [CLAUDE](m1_ledger/CLAUDE.md) · [SPEC](m1_ledger/SPEC.md) |
| M2 Simulator | _fill in_ | [README](m2_simulator/README.md) · [STATUS](m2_simulator/STATUS.md) · [ROADMAP](m2_simulator/ROADMAP.md) · [CLAUDE](m2_simulator/CLAUDE.md) · [SPEC](m2_simulator/SPEC.md) |
| M3 Detection | _fill in_ | [README](m3_detection/README.md) · [STATUS](m3_detection/STATUS.md) · [ROADMAP](m3_detection/ROADMAP.md) · [CLAUDE](m3_detection/CLAUDE.md) · [SPEC](m3_detection/SPEC.md) |
| M4 Control | _fill in_ | [README](m4_control/README.md) · [STATUS](m4_control/STATUS.md) · [ROADMAP](m4_control/ROADMAP.md) · [CLAUDE](m4_control/CLAUDE.md) · [SPEC](m4_control/SPEC.md) |
| M5 Console | _fill in_ | [README](m5_console/README.md) · [STATUS](m5_console/STATUS.md) · [ROADMAP](m5_console/ROADMAP.md) · [CLAUDE](m5_console/CLAUDE.md) · [SPEC](m5_console/SPEC.md) |

Team lead: [`docs/PROJECT_ROADMAP.md`](docs/PROJECT_ROADMAP.md) (Definition of Done, critical path, day-by-day, gates)
and [`docs/RESEARCH.md`](docs/RESEARCH.md) (NPCI rules, Drunix facts, competitors, metastability research).

How the split stays clean: modules talk **only** over HTTP/SSE (live) or files in `data/` (batch) as
[`contracts/CONTRACTS.md`](contracts/CONTRACTS.md) defines; every message is validated against `contracts/schemas/`;
no module imports another (each Python module has a `tests/test_isolation.py` that fails on a cross-module import);
every module runs alone against `contracts/fixtures/`.

```
M2 sim ──SSE payment events──▶ M3 detect ──SSE ticks/incidents──▶ M4 control ──SSE recommendations──▶ M5 console
  ▲  ◀──actions (poll)──────────────────────────────────────────── M4 ◀──decisions──────────────────── M5
  └──open/attest unknowns──▶ M1 ledger gateway ◀──decisions, advisories── M4      (all read the M1 event stream)
```

## Status (2026-10-20)

| Module | State | Top next task |
|---|---|---|
| M1 | Mock gateway complete and tested; Go chaincode + `qs-net.sh` written, **not compiled or run** (no Go/Docker on the dev machine); live Drunix gateway not started | M1-T01 bring Drunix up on a Linux/WSL2 box |
| M2 | Engine, all universes, S0–S8, ledger *model*, batch runner, live API; **calibration fails** (every S4 trigger locks the whole network); live HTTP ledger bridge not built | M2-T01 calibrate (critical path) |
| M3 | Full rule pipeline, localizer, lifecycle, live/mock/batch; right bank named on a recorded S3 run; forecaster grid untrained | M3-T02 one incident per bank fault at demo rate |
| M4 | Rules R0–R7, eligibility, governor, decisions → actions → ledger, simulated operator; no rollback proposals yet | M4-T01 ledger tx on the decision stream |
| M5 | Skeleton, generated types, SSE client, core panels; **not yet opened in a browser**; integration smoke in `m5_console/scripts/` | M5-T01 browser pass |

Live integration smoke (M1 mock + M2 + M3 + M4 with the simulated operator, S3/U4): M3 raised BANK_SIDE incidents,
M4's package was auto-approved, the decision and advisories landed on the M1 mock ledger, M2 applied the actions and the
incidents closed; no error lines in any log. Payments are not opened on the ledger yet (M2-T02).

## Verification (2026-10-20)

| Module | Command (from the module folder) | Result |
|---|---|---|
| M1 gateway | `npm test` · `npx tsc --noEmit` · `npm audit` | 7/7 pass (incl. 70 golden vectors) · clean · 0 vulnerabilities |
| M1 chaincode | `go test ./logic/...` | **not run** (Go not installed) |
| M2 | `../.venv/Scripts/python -m pytest -q` | 16/16 pass |
| M3 | `../.venv/Scripts/python -m pytest -q` | 18/18 pass |
| M4 | `../.venv/Scripts/python -m pytest -q` | 19/19 pass |
| M5 | `npm test` · `npx tsc --noEmit` · `npx vite build` · `npm audit` | 7/7 pass · clean · builds · 0 vulnerabilities |
| Integration | `.venv/Scripts/python m5_console/scripts/integration_smoke.py` (repo root) | checks a–d; e needs M2-T02 |
| compose / Dockerfiles | `docker compose up --build` | **not run** (Docker not installed) |
| browser | open the console | **not done yet** |

## Quick start (dev machine, no Docker)

```bash
python -m venv .venv && .venv/Scripts/pip install -e "m2_simulator[test]" -e "m3_detection[test]" -e "m4_control[test]"
#   behind TLS interception add: --trusted-host pypi.org --trusted-host files.pythonhosted.org
(cd m1_ledger/gateway && npm install) && (cd m5_console && npm install)
# five terminals:
(cd m1_ledger/gateway && QS_API_KEY=dev LEDGER_MODE=mock node src/main.ts)
(cd m2_simulator && QS_API_KEY=dev CONTROL_URL=http://localhost:8003 SIM_MODE=live ../.venv/Scripts/python -m uvicorn --factory qsim.api:create_app --port 8001)
(cd m3_detection && QS_API_KEY=dev SIM_URL=http://localhost:8001 ../.venv/Scripts/python -m uvicorn --factory qdet.api:create_app --port 8002)
(cd m4_control && QS_API_KEY=dev DETECT_URL=http://localhost:8002 LEDGER_URL=http://localhost:8004 ../.venv/Scripts/python -m uvicorn --factory qctl.api:create_app --port 8003)
(cd m5_console && VITE_QS_API_KEY=dev npm run dev)          # http://localhost:8000
```

## Claims policy (binding, `docs/00_PRODUCT.md` §8)
Say "in our simulator, on held-out configurations, X compared with Y". Never say "prevents outages", "predicts outages",
"production-ready", "NPCI-approved", "Citi integration", "guaranteed", or "scales to UPI volumes" without measurement.
