# M5 — Console (`m5_console/`, port 8000, TypeScript + React 18 + Vite) + integration + demo

**Owner:** _fill in_ · **Backup reviewer:** everyone · **Spec:** [`SPEC.md`](SPEC.md) · **Status:** [STATUS.md](STATUS.md) · **Roadmap:** [ROADMAP.md](ROADMAP.md) · **Agent instructions:** [CLAUDE.md](CLAUDE.md)

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

QueueShield is our Drunix Hackathon 2026 entry (NPCI × Citi, Real-Time Payments). When a UPI bank or PSP slows down, payments time out and become **unknown**; apps then hammer the NPCI switch with status checks and users retry, which slows everything further (the April 2025 UPI outages). QueueShield detects and localises the degrading segment and forecasts lock-in (M3), recommends bounded actions (M4) that **a human approves on your console**, and resolves unknown payments from a shared Drunix ledger where every decision is recorded (M1). Everything runs on a reactive simulator (M2). You also own the root `docker-compose.yml`, root `README.md`, the integration smoke test, the recordings/replay and the deck assets.

## Your module's job

One screen where a judge understands the story in four minutes and an operator can act in ten seconds; a replay mode
that never fails on stage. **No business logic**: every number shown comes from a stream or a results file.

```
┌ Header (run, sim time, global state, source badges, "simulation") ┐
├ ScenarioBar (Normal · Festive surge · Bank slowdown · Retry storm · April-2025 replay · Payout burst) ┤
├ left 60 %: HeatMap · MetricStrip · DetectorRace · CascadeMap │ right 40 %: RecommendationCard · DecisionLog · DrunixPanel · VerificationPanel ┤
Tabs: Live | Arena | April-2025 split replay | About & claims
```

## Interfaces (reads every stream; `contracts/CONTRACTS.md`)

| From | What |
|---|---|
| M2 :8001 | `POST /v1/scenario`, `GET /v1/status`, `/v1/timeseries`, `/v1/results` |
| M3 :8002 | SSE `tick`, `incident`; `GET /v1/forecaster/grid` |
| M4 :8003 | SSE `recommendation`, `budget`, `decision`; `POST /v1/decisions` |
| M1 :8004 | SSE `ledger_event`; `GET /v1/network`, `/v1/payments` |

## Code map

| Path | What |
|---|---|
| `src/contracts/` | TS types **generated** from `contracts/schemas` (`npm run gen:types`) — never hand-write a message type |
| `src/streams/sse.ts` | resilient SSE client: browser Last-Event-ID resume, 0.5–8 s backoff, 15 s stale watchdog |
| `src/store/` | zustand store, bounded rings, de-duplication by id |
| `src/connect.ts` | streams → store; MOCK fallback from `contracts/fixtures` with a visible badge; decision and scenario POSTs |
| `src/panels/` | `HeatMap`, `RecommendationCard` (+ pure `decisionLogic.ts`), `LedgerPanels` (DecisionLog, DrunixPanel), `Placeholders` (the rest) |
| `src/text/claims.ts` | every user-visible claim sentence + the forbidden-word list |
| `tests/` | vitest: claims lint (U-8), blocked actions (U-4), no duplicate rows (U-5), backoff bounds |

## Run and test

```bash
cd m5_console && npm install
npm test               # vitest
npx tsc --noEmit       # typecheck
npm run dev            # http://localhost:8000 ; with no services running, panels show MOCK/offline badges
VITE_QS_API_KEY=dev VITE_CONTROL_URL=http://localhost:8003 npm run dev   # point at live services
```
