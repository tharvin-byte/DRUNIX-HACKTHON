# M2 — Simulator (`m2_simulator/`, port 8001, Python 3.11)

**Owner:** _fill in_ · **Backup reviewer:** M3 owner · **Spec:** [`SPEC.md`](SPEC.md) · **Status:** [STATUS.md](STATUS.md) · **Roadmap:** [ROADMAP.md](ROADMAP.md) · **Agent instructions:** [CLAUDE.md](CLAUDE.md)

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

QueueShield is our Drunix Hackathon 2026 entry (NPCI × Citi, theme Real-Time Payments). When a UPI bank or PSP slows down, payments time out and their outcome becomes **unknown**; apps then hammer the NPCI switch with status checks and users retry, which slows everything further. That loop caused the UPI outages of 26 Mar, 2 Apr and 12 Apr 2025. QueueShield:

1. **detects and localises** the degrading segment (PSP, bank, route or switch) within seconds (M3),
2. **forecasts** whether it will lock into a self-sustaining storm if nothing changes (M3),
3. **recommends bounded actions** and publishes check budgets so verification never becomes load; a **human approves** (M4, M5),
4. resolves unknown payments from a **shared Drunix ledger** (banks attest once, everyone is pushed the answer) instead of polling the switch, and records every advisory and decision on-chain (M1).

Everything is evaluated in this simulator. Five universes replay the same random tape: U0 naive, U1 textbook failover, U2 NPCI-rule baseline, U3 QueueShield without ledger, U4 QueueShield + Drunix.

## Your module's job

A deterministic discrete-event model of a small UPI-like network (3 PSPs, 5 banks, 1 switch) in which **actions really change what happens next**. It must reproduce the April-2025 loop (timeouts → status checks + retries → switch saturation → slower payments). It owns ground truth, batch runs and the arena. It never does detection, recommendation or UI.

```
client ─▶ PSP queue/workers ─▶ remitter leg (debit) ─▶ beneficiary leg (credit) ─▶ outcome
   │ timeout (3 s) = UNKNOWN, attempt keeps running (zombie work)
   ├─ status checks ─▶ switch status service (4 workers ≈ 80/s) ─▶ slowdown factor on EVERY leg
   └─ U4: ledger model opens unknowns, banks attest, PSP gets a pushed resolution
```

## Interfaces (only these; see `contracts/CONTRACTS.md` §1)

| Direction | What | Contract |
|---|---|---|
| out → M3, M5 | `GET /v1/stream` SSE `payment_event` | `payment_event.schema.json` |
| in ← M5 | `POST /v1/scenario` START/PAUSE/RESUME/RESET/SPEED | `scenario_command.schema.json` |
| in ← M4 | polls `GET control/v1/actions/pending`, acks `/applied` | `action.schema.json` |
| out → M3/M4 (batch) | `/v1/batch/reset`, `/v1/batch/tick` lockstep | `lockstep.schema.json` |
| out → M1 (U4 live) | `POST ledger/v1/payments`, `/attest` — **not built yet** | `ledger_open_request`, `ledger_attest_request` |
| files | `data/runs/<run_id>/{events.jsonl,ground_truth.json,result.json,timeseries.json,ticks.jsonl}` | `run_result.schema.json` |

## Code map

| File | What |
|---|---|
| `qsim/engine.py` | the event loop, PSPs, legs, switch, clients, ledger model, actions, ground truth |
| `qsim/tape.py` | common random numbers (named PCG64 streams; draws indexed by payment, attempt) |
| `qsim/scenarios.py` | S0–S8 configurations and ground-truth rows |
| `qsim/config.py` + `config/*.yaml` | every tunable number (frozen dataclasses) |
| `qsim/metrics.py` | `result.json` metrics and time series |
| `qsim/batch.py` | batch / lockstep runner (`python -m qsim.batch`) |
| `qsim/live.py`, `qsim/api.py` | wall-clock runner, action polling, HTTP/SSE routes |
| `qsim/ledger_bridge.py` | placeholder for the live/mock HTTP ledger bridge |
| `qsim/contracts.py`, `jsonlog.py`, `sse.py` | schema validation, JSON logs, SSE ring (module-local copies) |

## Run and test

```bash
cd m2_simulator
python -m venv .venv && .venv/Scripts/pip install -e ".[test]"   # or reuse ../.venv
make test                       # or: ../.venv/Scripts/python -m pytest -q
make run-mock                   # replays contracts/fixtures/payment_events.jsonl on :8001
make run                        # live mode; POST /v1/scenario to start a run
python -m qsim.batch --scenario S6 --seeds 1 2 3 --universes U0 U2 U4 --out ../data/runs
```
Corporate TLS interception on the dev machine: add `--trusted-host pypi.org --trusted-host files.pythonhosted.org` to pip.
