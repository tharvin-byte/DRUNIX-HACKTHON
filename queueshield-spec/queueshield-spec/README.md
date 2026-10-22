# QueueShield × Drunix — Agent Build Specification (v1.0, 19 Oct 2026)

This folder is the single source of truth for building QueueShield for the **Drunix Hackathon 2026 (NPCI × Citi), theme Real-Time Payments**. It is written for coding agents and for the five human owners who direct them. A person or an agent must be able to start work from this folder with no other context.

QueueShield detects a degrading bank or PSP route within seconds, forecasts whether retries and status checks will tip it into a self-sustaining storm, and resolves unknown-outcome payments from a shared Drunix ledger instead of polling the UPI switch, so the safety step can never become the outage. Every action is approved by a human, and every approval is recorded on the ledger.

## Reading order

| Reader | Read first | Then |
|---|---|---|
| Any agent | `AGENTS.md`, then `docs/00_PRODUCT.md` §1–§4 | Your module spec, then `contracts/CONTRACTS.md` |
| M1 Ledger owner / agent | `docs/M1_LEDGER.md` | `docs/01_SYSTEM.md` §4–§6, contracts `ledger_*`, `advisory`, `network_info` |
| M2 Simulator owner / agent | `docs/M2_SIMULATOR.md` | `docs/01_SYSTEM.md`, contracts `payment_event`, `action`, `scenario_command`, `run_result`, `lockstep` |
| M3 Detection owner / agent | `docs/M3_DETECTION.md` | contracts `payment_event`, `segment_state`, `incident`, `lockstep` |
| M4 Control owner / agent | `docs/M4_CONTROL.md` | contracts `segment_state`, `incident`, `recommendation`, `decision`, `action`, `advisory`, `ledger_*` |
| M5 Console owner / agent | `docs/M5_CONSOLE.md` | every contract (M5 reads every stream) |
| Team lead | `docs/90_PLAN_EVAL_RISKS.md` | everything else as needed |

## Folder map

```
queueshield-spec/
├── README.md                     this file
├── AGENTS.md                     rules every agent must follow (paste into the code repo root)
├── docs/
│   ├── 00_PRODUCT.md             problem, evidence, product scope, principles, claims policy, glossary
│   ├── 01_SYSTEM.md              architecture, module boundaries, ports, flows, run modes, ids, time
│   ├── M1_LEDGER.md              Drunix network, Go chaincode, TypeScript gateway, mock gateway
│   ├── M2_SIMULATOR.md           UPI-like reactive simulator, scenarios, universes, arena
│   ├── M3_DETECTION.md           features, detectors D0–D3, Fault Localizer, Cascade Forecaster
│   ├── M4_CONTROL.md             Verification Governor, policy engine, decisions, advisories
│   ├── M5_CONSOLE.md             operator console, replay, compose, demo, deck assets
│   └── 90_PLAN_EVAL_RISKS.md     5-day pitch plan, build plan, evaluation, risks, Q&A, sources
└── contracts/
    ├── CONTRACTS.md              every endpoint, every message, SSE rules, versioning
    ├── schemas/*.schema.json     JSON Schema (draft 2020-12), validated
    └── fixtures/*                recorded examples; every fixture validates against its schema
```

## Code repository layout this spec produces

```
queueshield/                      (the code repo — separate from this spec folder)
├── AGENTS.md                     copied from this spec
├── CODEOWNERS                    one owner per top-level folder
├── docker-compose.yml            owned by M5
├── README.md                     owned by M5
├── contracts/                    copied from this spec; changed only by the contract process
├── data/                         git-ignored: runs/, models/, recordings/ (shared files, never code)
├── ledger/                       M1 — Go chaincode, TypeScript gateway, network scripts
├── sim/                          M2 — Python simulator and arena
├── detect/                       M3 — Python detection service
├── control/                      M4 — Python control service
└── console/                      M5 — TypeScript/React console
```

## The five modules

| Module | Folder | Port | Language | One-line job |
|---|---|---|---|---|
| M1 Ledger | `ledger/` | 8004 | Go (chaincode), TypeScript (gateway) | Run Drunix and expose payment truth, advisories and decisions over REST + SSE |
| M2 Simulator | `sim/` | 8001 | Python 3.11 | Generate a reactive UPI-like network that responds to actions; run the arena |
| M3 Detection | `detect/` | 8002 | Python 3.11 | Turn payment events into per-segment state, incidents, verdicts and lock-in probability |
| M4 Control | `control/` | 8003 | Python 3.11 | Turn incidents into ranked, bounded recommendations; publish check budgets; write advisories and decisions to the ledger |
| M5 Console | `console/` | 8000 | TypeScript (React + Vite) | Let a human see, approve and replay; integrate everything; produce demo assets |

## Quick start (target state)

```bash
# 1. Drunix network (Linux or WSL2 only)
cd ledger && ./network/qs-net.sh bootstrap        # up -> channel -> deploy queueshield chaincode
# 2. Everything else, live
docker compose up --build                          # sim, detect, control, ledger-gateway, console
# 3. Everything else, without Drunix (mock ledger)
LEDGER_MODE=mock docker compose up --build
# 4. Open the console
open http://localhost:8000
```

## Status labels used in this spec

- **MUST / SHOULD / MAY** have their RFC 2119 meanings.
- **[VERIFY]** marks a fact about Drunix or a library that has not been confirmed on our machines; the first agent to touch it confirms it and records the result in `docs/DEVIATIONS.md` of the code repo.
- **[PITCH]** = required for the 24 Oct pitchable prototype. **[BUILD]** = 10–22 Nov build phase. **[STRETCH]** = only if everything else is green.
