# M3 — Detection (`m3_detection/`, port 8002, Python 3.11)

**Owner:** _fill in_ · **Backup reviewer:** M2 owner · **Spec:** [`SPEC.md`](SPEC.md) · **Status:** [STATUS.md](STATUS.md) · **Roadmap:** [ROADMAP.md](ROADMAP.md) · **Agent instructions:** [CLAUDE.md](CLAUDE.md)

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

QueueShield is our Drunix Hackathon 2026 entry (NPCI × Citi, Real-Time Payments). When a UPI bank or PSP slows down, payments time out and become **unknown**; apps then hammer the NPCI switch with status checks and users retry, which slows everything further (the April 2025 UPI outages). QueueShield **detects and localises** the degrading segment (you, M3), **forecasts** whether it will lock in if nothing changes (you), **recommends bounded actions** that a human approves (M4, M5), and resolves unknown payments from a **shared Drunix ledger** instead of polling the switch (M1). Everything is evaluated in a reactive simulator (M2) across five universes on the same random tape.

## Your module's job

Every 5 000 sim ms turn the payment-event stream into:
(a) per-segment features for 25 segments (platform, 3 PSPs, 5 banks, 15 routes, switch),
(b) four detectors' alerts (D0 platform dashboard, D1 thresholds, D2 CUSUM, D3 QueueShield rules),
(c) a localisation verdict (PSP_SIDE, BANK_SIDE, ROUTE_SPECIFIC, SWITCH_STATUS_OVERLOAD, MULTI_FAULT, PLATFORM_WIDE),
(d) a lock-in probability `p_stuck` per PSP (Cascade Forecaster), and
(e) incidents with reasons. You never take actions and never touch the ledger.

```
events ─▶ ingest (validate, dedupe, 2 s watermark) ─▶ windows (1 s buckets) ─▶ features + EWMA baselines
       ─▶ D0..D3 + surge gate + persistence ─▶ localizer (involvement lift) ─▶ forecaster grid ─▶ incidents
       ─▶ segment_state tick (SSE `tick`) + `incident` events
```

## Interfaces (`contracts/CONTRACTS.md` §2)

| Direction | What | Contract |
|---|---|---|
| in ← M2 | `GET SIM_URL/v1/stream` (live) or `POST /v1/batch/tick` (lockstep) | `payment_event`, `lockstep#DetectTickRequest` |
| out → M4, M5 | `GET /v1/stream` SSE `tick`, `incident`; `GET /v1/state`, `/v1/incidents` | `segment_state`, `incident` |
| out → M5 | `GET /v1/forecaster/grid` | grid JSON (CONTRACTS §2) |
| files | reads `data/runs/*` **only in scripts/** (training); writes `data/models/forecaster_grid.json` | |

## Code map

| File | What |
|---|---|
| `qdet/segments.py` | the 25 segments, involvement mapping (a bank counts as remitter AND beneficiary), overlap rules |
| `qdet/ingest.py`, `windows.py`, `tracker.py` | validation + dedupe + watermark; 1 s ring buffers + latency histograms; pending/orbit/ledger counts |
| `qdet/features.py`, `baselines.py` | the 23 schema features; EWMA mean/MAD baselines with freeze |
| `qdet/detectors/d3.py`, `baseline_detectors.py` | D3 signals, surge gate, rule score, persistence, reasons; D0, D1, D2 |
| `qdet/localizer.py` | involvement-lift verdicts (pure `raw_verdict` + hysteresis wrapper) |
| `qdet/forecast/grid.py`, `runtime.py` | 20×20 stuck grid; per-PSP p_stuck, EMA, state, countdown |
| `qdet/lifecycle.py` | incident lifecycle OPEN → MITIGATING → RECOVERING → CLOSED, merge rule |
| `qdet/pipeline.py` | `Pipeline.ingest(events)` / `Pipeline.tick(now_ms)` → `segment_state` |
| `qdet/api.py` | live / mock / batch HTTP + SSE |
| `scripts/train_forecaster.py` | offline grid training from M2 batch runs (may read ground truth) |
| `config/detect.yaml` | every threshold in the spec (+ IBM-derived floors, marked) |

## Run and test

```bash
cd m3_detection
make test                    # or ../.venv/Scripts/python -m pytest -q
make run-mock                # ticks from contracts/fixtures on :8002
SIM_URL=http://localhost:8001 make run          # live, subscribes to M2
make train-forecaster        # needs U0 runs with incidents under ../data/runs (python -m qsim.batch in ../m2_simulator/)
```
