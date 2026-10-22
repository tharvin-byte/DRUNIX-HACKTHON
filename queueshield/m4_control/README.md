# M4 — Control (`m4_control/`, port 8003, Python 3.11)

**Owner:** _fill in_ · **Backup reviewer:** M1 owner · **Spec:** [`SPEC.md`](SPEC.md) · **Status:** [STATUS.md](STATUS.md) · **Roadmap:** [ROADMAP.md](ROADMAP.md) · **Agent instructions:** [CLAUDE.md](CLAUDE.md)

## Documents in this folder

| File | Read it for |
|---|---|
| `README.md` | the whole idea, this module's job, interfaces, how to run (this file) |
| `STATUS.md` | what exists today and how it was verified |
| `ROADMAP.md` | everything left to do: task cards with acceptance checks, enhancements, this week's plan |
| `CLAUDE.md` | instructions for you or your AI agent: reading order, workflow, hard rules, a ready prompt |
| `SPEC.md` | the full module specification (working copy) |
Shared across modules: `../AGENTS.md`, `../contracts/`, `../docs/` (product, system, plan, research, deviations).

## The whole project in one minute

QueueShield is our Drunix Hackathon 2026 entry (NPCI × Citi, Real-Time Payments). When a UPI bank or PSP slows down, payments time out and become **unknown**; apps then hammer the NPCI switch with status checks and users retry, which slows everything further (the April 2025 UPI outages). QueueShield **detects and localises** the degrading segment and **forecasts** lock-in (M3), **recommends bounded actions that a human approves** (you, M4, with the console M5), and resolves unknown payments from a **shared Drunix ledger** where every advisory and operator decision is also recorded (M1). Everything is evaluated in a reactive simulator (M2).

## Your module's job

Turn evidence into a short, ranked, bounded set of actions an operator can approve in seconds; publish the
**check budget** that keeps verification from becoming load; make every approval durable by writing the
decision and its advisories to the ledger. Models detect; **your rules decide what is eligible**; humans decide.

```
M3 tick + incidents ─▶ rules R0–R7 (config/policy.yaml) ─▶ eligibility (SHIFT_TRAFFIC checks) ─▶ recommendation
operator decision (M5) ─▶ actions for M2 ─▶ decision + advisories on the ledger (M1) ─▶ SSE to M5
every tick ─▶ Verification Governor ─▶ CHECK_BUDGET per PSP (origin POLICY_DEFAULT, no approval needed)
```

## Interfaces (`contracts/CONTRACTS.md` §3)

| Direction | What | Contract |
|---|---|---|
| in ← M3 | `GET DETECT_URL/v1/stream` (`tick` with incidents) or `POST /v1/batch/tick` | `segment_state`, `incident`, `lockstep#ControlTickRequest` |
| in ← M1 | `GET LEDGER_URL/v1/stream` `ledger_event` | `ledger_event` |
| out → M5 | `GET /v1/stream` `recommendation`, `budget`, `decision`; `GET /v1/recommendations` | `recommendation` |
| in ← M5 | `POST /v1/decisions` (409 on a second decision or a blocked action) | `decision` |
| out → M2 | `GET /v1/actions/pending?run_id&since`, `POST /v1/actions/{id}/applied` | `action` |
| out → M1 | `POST LEDGER_URL/v1/decisions`, `/v1/advisories` (retry, then queue; never blocks actions) | `ledger_decision`, `advisory` |

## Code map

| File | What |
|---|---|
| `config/policy.yaml` | the rule table R0–R7 as data, advisory mapping, side-effect and rollback texts |
| `config/control.yaml`, `operators.yaml` | governor constants, throttle/defer/shift params, expiry, ledger retry, operators |
| `qctl/policy.py` | rule matching, scopes, SHIFT_TRAFFIC eligibility (§4), recommendation records (§5) |
| `qctl/governor.py` | per-PSP budget formula (§2) |
| `qctl/controller.py` | per-run state machine: recommendations, decisions → actions → ledger, simulated operator (§8), action queue |
| `qctl/ledger.py` | `HttpLedger` (M1 gateway) and `ModelLedger` (batch) |
| `qctl/api.py` | live / mock / batch HTTP + SSE |

## Run and test

```bash
cd m4_control
make test                    # or ../.venv/Scripts/python -m pytest -q
make run-mock                # serves a recommendation built from contracts/fixtures/incident.json
DETECT_URL=http://localhost:8002 LEDGER_URL=http://localhost:8004 make run        # live, human operator
OPERATOR_MODE=auto OPERATOR_DELAY_S=20 ... make run                                # simulated operator
```
Without `LEDGER_URL` decisions go to the in-process `ModelLedger` (no M1 needed).
