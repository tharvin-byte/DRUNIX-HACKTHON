# M5 Console — roadmap: what is left, what to add, in what order

Written 2026-10-20 after reviewing the code, `SPEC.md`, competitor demos and outside research (`../docs/RESEARCH.md`).
Read `CLAUDE.md` first for how to work; this file says **what** to work on. M5 also owns integration (compose,
smoke test), recordings/replay, the demo and the deck assets.

**Deadlines:** pitch **Sun 25 Oct** (**P0**) · build 10–22 Nov (**P1**) · finale 4 Dec (**P2**).

## 1. Where M5 stands

Built (7 tests, typecheck + build clean): React 18 skeleton with 4 tabs and the 60/40 layout, contract types generated
from the schemas, SSE client with backoff/stale watchdog, zustand store with de-duplication, HeatMap,
RecommendationCard (approve/reject, blocked actions locked), DecisionLog, DrunixPanel, MOCK fallback, claims lint.
**Never opened in a browser yet.** Placeholders: MetricStrip, DetectorRace, CascadeMap, VerificationPanel, Arena tab,
split replay. Integration smoke exists as `scripts/integration_smoke.py` (checks a–d PASS on 2026-10-20 before the
folder move; e is SKIPPED until M2-T02).

## 2. What you depend on

| Panel | Needs | Status of the dependency |
|---|---|---|
| DecisionLog tx id | M4 publishes ledger tx/block on `decision` | M4-T01 |
| CascadeMap | M3 `/v1/forecaster/grid` + per-PSP `phase_point` | M3-T01 (grid after M2 calibration) |
| VerificationPanel, split replay | M2 `/v1/timeseries`, S6 U0 + U4 runs | available; needs calibrated runs |
| Arena tab | M2 `/v1/results` from the arena | M2-T03 |
| DrunixPanel live | M1 live `/v1/network` | M1-T03/T06 |

Do not wait: build every panel against fixtures and recorded files first.

## 3. Tasks

### M5-T01 · Open it in a browser and make the basics solid (U-1, U-2) [P0, Day 1]
- `npm run dev` with **no** services: every panel renders, badges say MOCK/offline, no console errors (U-1).
- `npm run dev` against `make run-mock` of M1–M4: ticks, the fixture recommendation and ledger events appear.
- Add Playwright (pin exactly, `npm audit`) with one snapshot per panel on fixtures (U-2).
- Fix the Header: poll M2 `/v1/status` every 1 s (scenario, seed, universe, sim time, speed) and every `/v1/health`.

### M5-T02 · Approve flow end to end (U-3, U-4) [P0, ~0.5 day]
- Against M4 (mock or live): approve → DecisionLog row ≤ 2 s → "recording on ledger…" → tx id + block when M4
  re-publishes (M4-T01). Operator names from `config.ts` must match M4's `operators.yaml`.
- Keyboard: `A` approve all, `S` approve selected, `R` reject (operator speed is the dominant factor in the IBM sweep).

### M5-T03 · VerificationPanel + MetricStrip with uPlot [P0, ~0.5 day]
- VerificationPanel: switch checks/s vs summed budget (M4 `budget` events), switch utilisation with the 0.85 knee,
  unknown open vs resolved — from M2 `/v1/timeseries` polled every 1 s. S6 must spike under U0 and stay flat under U4.
- MetricStrip: 5 sparklines (timeout %, near-timeout %, p95, RAF, queue) for the selected segment with a baseline band
  (`z`/features from ticks).

### M5-T04 · DetectorRace and CascadeMap [P0, ~0.5 day]
- DetectorRace: 4 lanes D0–D3 with a flag at `first_alert_sim_ms`; onset marker **only** in replay/arena (ground truth);
  live shows "onset unknown".
- CascadeMap: grid heat background from `/v1/forecaster/grid`, the 0.5 contour labelled "point of no return", a 60 s
  trail per PSP from `phase_point`, countdown labelled "rough estimate". Until the grid exists, draw axes + trails only.

### M5-T05 · Recorder + replay mode (U-6) — the stage safety net [P0, ~0.5 day]
- `scripts/record.ts` (or `.mjs`): subscribe to all four streams during a live run and write
  `data/recordings/<name>.jsonl` lines `{"stream","sim_ms","data"}`.
- `src/streams/replay.ts`: `?mode=replay&rec=<name>&speed=1|2|4` feeds the same store; same final panel state at 1× and 4×.

### M5-T06 · April-2025 split replay + Arena tab [P0, Day 4]
- Split replay: two recordings (S6 U0 and U4, same seed) side by side, synchronised clock, label "replay of simulation runs".
- Arena tab: per scenario U0 / U2 / U4 lines (goodput, queue, switch checks) on shared axes + a metrics table with medians,
  labelled "simulation, 5 seeds, preliminary"; U2 always shown next to U4 (honest baseline).

### M5-T07 · Integration: compose + smoke (U-7) [P0]
- Run `../.venv/Scripts/python m5_console/scripts/integration_smoke.py` (from the repo root) twice in a row; fix what breaks.
- On a machine with Docker: `LEDGER_MODE=mock docker compose up --build`; fix the Dockerfiles (written untested).

### M5-T08 · Demo script, rehearsal, backup video, deck assets [P0, Day 4–5]
- Follow `SPEC.md` §7 (4-minute script) and `../docs/90_PLAN_EVAL_RISKS.md` §4 (talk track). Screenshots at 1920×1080
  with the "simulation" label visible (SPEC §8 list). Claims review by a second person for any sentence with
  production / guarantee / prevent / savings / approved.

## 4. Enhancements beyond the spec

| Idea | Why | Effort |
|---|---|---|
| **Guided demo mode** (`?demo=1`): a step overlay that matches the talk track and arms the right scenario button | removes stage fumbles; judges follow the story | S |
| **"Money is with …" custody chip** on unknown payments (from M1 attestations) | competitor Pulse's strongest UX; we can match it and then go beyond (network view) | S (needs M1 custody query or derive from events) |
| **Regulator view tab**: read-only TAT breaches, advisories, decisions with tx ids | the spec's regulator observer; parity with Pulse/Axis regulator desks | S |
| **Competitor/positioning slide** generated from `../docs/RESEARCH.md` | spec risk "seen as another stuck-payment ledger" | S |
| **Timeline scrubber in replay** | lets judges jump to the storm | M |
| Fetch-based SSE reader with `Last-Event-ID` on rebuilt connections | full resume after long outages (EventSource cannot set headers) | S |

## 5. Open questions
1. Live demo against real Drunix or the mock? (Depends on M1-T01..T04 by Thu.)
2. Who records the backup video, on which machine (1080p screen)?

## 6. This week

| Day | Do | Gate |
|---|---|---|
| Tue 20 | M5-T01 browser pass, Header polling | U-1 |
| Wed 21 | M5-T02, M5-T03 | U-3, U-4 |
| Thu 22 | M5-T04, M5-T07 smoke twice; first live compose if Docker available | U-5, U-7 |
| Fri 23 | M5-T05 recorder/replay, M5-T06 arena + split replay; deck screenshots | U-6 |
| Sat 24 | M5-T08 polish, claims lint, two rehearsals, backup video | U-8; submit Sun 25 with buffer |
