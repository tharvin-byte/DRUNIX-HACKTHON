# M5 — Console and story: operator UI, replay, integration, demo assets

> **Working copy** of the QueueShield spec v1.0 (19 Oct 2026), moved next to the code on 2026-10-20. The original stays frozen in `Citibank/queueshield-spec/` (next to `queueshield/`); this copy is the one the team updates.
> Folder names in this repo: `ledger/` → `m1_ledger/`, `sim/` → `m2_simulator/`, `detect/` → `m3_detection/`, `control/` → `m4_control/`, `console/` → `m5_console/`. Shared docs: `docs/` at the repo root; module specs: `SPEC.md` inside each module folder.

**Owner folder:** `console/` (+ root `docker-compose.yml`, root `README.md`) · **Port:** 8000 · **Stack:** TypeScript, React 18, Vite 5, uPlot (time series), hand-drawn SVG (heat map, cascade map, detector race), Zustand (state), Playwright (UI tests) · **Reads:** every stream · **Writes:** decisions to M4, scenario commands to M2.

Your job: one screen where a judge understands the story in four minutes and an operator can act in ten seconds; a replay mode that never fails on stage; the compose file that starts everything; and the visual assets for the deck. You own no business logic: every number you show comes from a stream or a results file.

---

## 1. Folder layout

```
console/
├── package.json  vite.config.ts  tsconfig.json
├── src/
│   ├── main.tsx  App.tsx
│   ├── config.ts                  URLs from env (VITE_SIM_URL, ...)
│   ├── contracts/                 TS types generated from contracts/schemas (json-schema-to-typescript)
│   ├── streams/sse.ts             resilient SSE client (Last-Event-ID, backoff, heartbeat watchdog)
│   ├── streams/replay.ts          plays data/recordings/*.jsonl at 1x/2x/4x with the same store API
│   ├── store/                     zustand slices: sim, detect, control, ledger, ui
│   ├── panels/                    Header, ScenarioBar, HeatMap, MetricStrip, DetectorRace,
│   │                              CascadeMap, RecommendationCard, DecisionLog, DrunixPanel,
│   │                              VerificationPanel, ArenaTab, SplitReplay
│   ├── charts/                    uPlot wrappers
│   └── text/claims.ts             every user-visible sentence that states a result (claims-policy checked)
├── public/
└── tests/ (vitest unit + playwright e2e against mock services)
```

## 2. Screen layout (1920×1080, no scrolling, dark theme, large type for video)

```
┌ Header: scenario · seed · universe · sim time · global state · events/s · [LIVE|MOCK|REPLAY] · ledger: live/mock/offline ┐
├ ScenarioBar: Normal · Festive surge · Bank slowdown · Retry storm · April-2025 replay · Payout burst │ speed 1x/2x/4x │ pause │ reset ┤
├──────────── left 60% ─────────────────────────────┬──────────── right 40% ────────────────────────────┤
│ HeatMap: 3 PSP × 5 bank grid + row/col totals      │ RecommendationCard (pending package, Approve all /  │
│ (colour = D3 score; outline = localizer primary)   │   Approve selected / Reject, blocked reasons)        │
│ MetricStrip (selected segment, last 5 min):        │ DecisionLog (newest first, ledger tx status)         │
│   timeout%, near-timeout%, p95, RAF, queue, pending│ DrunixPanel: orgs, LP/CP/VS chips, block height,     │
│ DetectorRace: D0/D1/D2/D3 timelines, onset marker  │   unknowns by state, TAT breaches, active advisories │
│ CascadeMap: phase plane + 0.5 contour + PSP trails │ VerificationPanel: switch checks/s vs budget,        │
│                                                    │   switch util & slowdown, unknown open/resolved      │
└────────────────────────────────────────────────────┴──────────────────────────────────────────────────────┘
Tabs: [Live] [Arena] [April-2025 split replay] [About & claims]
```

## 3. Panels: data source, rendering, acceptance

| Panel | Source | Rendering | Acceptance |
|---|---|---|---|
| Header | M2 `/v1/status` (poll 1 s), M3 tick `global_state`, all `/v1/health` | text + coloured state pill; mode badge | shows scenario within 1 s of START |
| ScenarioBar | `POST sim/v1/scenario` | buttons map to S0, S1, S3, S4, S6, S8 with fixed demo seeds from `config.ts` | button → run starts; disabled while starting |
| HeatMap | M3 `tick.segments` (route + psp + bank) | 3×5 SVG cells coloured by `d3_score` (sequential scale), row/col totals, localizer primary outlined, verdict label beside the grid | S3 lights one bank column across all PSPs |
| MetricStrip | M3 ticks for selected segment (click a cell) | 5 uPlot sparklines with baseline band | updates every tick |
| DetectorRace | M3 `detector_alerts` + incident onset marker (from M2 ground truth **only in replay/arena**; live shows "onset unknown") | 4 horizontal lanes, flag at first alert with delay text | S4: four distinct flags |
| CascadeMap | M3 `/v1/forecaster/grid` (once) + per-tick `phase_point` per PSP | heat background, 0.5 contour labelled "point of no return", 60 s trail per PSP, countdown text labelled "rough estimate" | S4 trail crosses contour; S1 stays below |
| RecommendationCard | M4 stream `recommendation` | severity, verdict, confidence, p_stuck, countdown, reasons ("supporting signals, not proof of cause"), actions with checkboxes, side effects, blocked reason in red with a lock icon | blocked SHIFT_TRAFFIC cannot be ticked |
| DecisionLog | M4 `decision` + M1 `DecisionRecorded` | rows: time, operator, rec, decision, actions, ledger status (pending → tx id + block) | row appears ≤ 2 s after approve; ledger tx id shown when committed |
| DrunixPanel | M1 `/v1/network` (poll 5 s) + `ledger_event` stream + `GET /v1/payments` counts | org boxes with LP/CP/VS chips, block height ticker, counts per payment state, TAT breach counter, active advisories list with expiry | never shows numbers when ledger offline; shows "offline" instead |
| VerificationPanel | M2 `/v1/timeseries` + M4 `budget` events | switch checks/s line vs summed budget, switch util line with 0.85 knee, unknown open vs resolved | S6 shows spike under U0 replay, flat under U4 |
| Arena tab | `data/runs/*/result.json` + `timeseries.json` via M2 `/v1/results` | per scenario: U0/U2/U4 lines on shared axes (goodput, queue, switch checks), metric table with medians and "simulation" label | U2 always shown next to U4 |
| April-2025 split replay | two recorded runs (U0 and U4, same seed) | side-by-side VerificationPanel + goodput, synchronised clock | labelled "replay of simulation runs" |
| About & claims | static | what is real (Drunix network, chaincode), what is simulated, claims policy summary | reviewed by lead |

Colour and type: dark background, one accent colour for "attention", status colours (good/warning/critical) used only for meaning; minimum 14 px text at 1080p.

## 4. Streams and state

- `sse.ts`: EventSource wrapper with `Last-Event-ID`, exponential backoff 0.5–8 s, watchdog that marks a stream stale if no heartbeat for 15 s, and a schema check (ajv) on every message in dev builds.
- Store slices keep only what panels need (ring buffers: 300 ticks, 500 ledger events, 200 recommendations).
- **Replay mode** (`?mode=replay&rec=<name>`): `replay.ts` feeds the same store from `data/recordings/<name>.jsonl` (`{"stream","sim_ms","data"}` per line) at the chosen speed. Recordings are produced by `console/scripts/record.ts`, which subscribes to all streams during a live run.
- **Mock mode**: if a service is unreachable, panels fall back to fixtures from `contracts/fixtures/` with a visible MOCK badge. Never silently mix mock and live data in one panel.

## 5. Decision flow (UI)

1. A new PENDING recommendation slides in; header turns warning/critical.
2. Operator ticks actions (eligible only), optional note (≤ 280 chars), presses Approve selected / Approve all / Reject.
3. `POST control/v1/decisions` with operator from a dropdown (`operators.yaml` names); disable buttons until response.
4. Card moves to "Approved — applying"; DecisionLog row shows "recording on ledger…" until `DecisionRecorded` arrives with tx id and block number.
5. `ACTION_APPLIED` events (from M2 stream) tick the applied actions; incident state shows MITIGATING → RECOVERING → CLOSED.

## 6. Integration ownership

- Root `docker-compose.yml` per `docs/01_SYSTEM.md` §11, with profiles `live` (gateway in live mode) and `mock`.
- Root `README.md`: quick start, architecture image, what is real vs simulated, how to run the demo and replay.
- `scripts/integration_smoke.sh`: starts all services in mock ledger mode, runs S6 U4 for 120 sim s at 4x, asserts (a) M3 published ≥ 20 ticks, (b) an incident opened, (c) a recommendation arrived, (d) an auto-approved decision produced a `DecisionRecorded` event, (e) at least one `PaymentUpdated` SUCCESS event.

## 7. Demo script (4 minutes; full narrative in docs/90 §4)

| Time | Screen | Click |
|---|---|---|
| 0:00–0:20 | Live tab, normal traffic | — |
| 0:20–0:40 | DrunixPanel close-up: real network, block height moving | — |
| 0:40–1:00 | Festive surge: quiet, zero alerts | Festive surge |
| 1:00–1:45 | Bank slowdown: column lights, failover blocked, approve → DO_NOT_SHIFT on ledger | Bank slowdown, Approve selected |
| 1:45–2:45 | April-2025 split replay: U0 floods the switch, U4 resolves by ledger push | Split replay tab |
| 2:45–3:30 | Retry storm: detector race, cascade map crosses line, approve all, arena | Retry storm, Approve all, Arena |
| 3:30–4:00 | Results with "simulation" labels; close | — |

Backup: the same sequence entirely in replay mode from recordings made on Day 4, plus a screen-recorded video.

## 8. Deck assets (owned by M5, content from every owner)

- Screenshots at 1920×1080: Live tab during S3 (blocked failover), CascadeMap on S4, split replay at the S6 peak, DrunixPanel with real block height, DecisionLog with a committed tx id, Arena chart.
- Terminal screenshot from M1: 11 Drunix containers running + a YSQL query on `mychannel.queueshield`.
- Exported diagrams: architecture, module map, the loop (slow bank → timeouts → unknowns → checks/retries → switch load → slower payments).
- Every screenshot with a number has the "simulation" label visible.

## 9. Acceptance tests

| ID | Test | Tag |
|---|---|---|
| U-1 | Loads with all services down and shows MOCK/offline badges, no crash | PITCH |
| U-2 | Every panel renders from fixtures (Playwright snapshot) | PITCH |
| U-3 | Approve flow against M4 mock writes a DecisionLog row ≤ 2 s and shows ledger tx when the mock emits DecisionRecorded | PITCH |
| U-4 | Blocked actions cannot be selected | PITCH |
| U-5 | SSE reconnect resumes without duplicate rows | PITCH |
| U-6 | Replay of a recording reproduces the same final panel state at 1x and 4x | PITCH |
| U-7 | `integration_smoke.sh` passes twice in a row | PITCH |
| U-8 | Claims lint: every string in `text/claims.ts` passes the forbidden-word list | PITCH |

## 10. Day-by-day (pitch sprint)

| Day | Tasks | Gate |
|---|---|---|
| 1 | Vite + React skeleton; generated contract types; SSE client; all panels on fixtures; compose skeleton | U-1, U-2 |
| 2 | HeatMap, DetectorRace, CascadeMap, RecommendationCard, DecisionLog with real mock services | U-3, U-4 |
| 3 | First live integration via compose; DrunixPanel against live gateway; integration smoke | U-5, U-7 |
| 4 | Arena tab, split replay, recordings; deck screenshots; deck assembly starts | U-6 |
| 5 | Polish, claims lint, rehearse twice, record backup video | U-8 |

## 11. Pitfalls

1. Never fake a ledger number: when M1 is offline, say so.
2. Ground-truth onset markers appear only in replay/arena views, never in the live view.
3. Keep the live view legible at 0.5× zoom on a projector.
4. Do not compute metrics in the UI; ask the owner module to add a field instead.

## 12. Agent prompt template

```
You are the M5 Console agent for QueueShield. Read AGENTS.md, docs/00_PRODUCT.md (esp. §8 claims policy),
docs/01_SYSTEM.md, contracts/CONTRACTS.md (all) and docs/M5_CONSOLE.md in full. Work only in console/
(plus root docker-compose.yml and README.md). Task: <row of §10 or acceptance test of §9>.
Generate TS types from contracts/schemas; never hand-write a message type. Tests first. Report results honestly.
```
