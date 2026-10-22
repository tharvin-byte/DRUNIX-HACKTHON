# M5 Console — status (updated 2026-10-20)

Legend: ✅ done and verified by a test/build that was run · 🟡 built, not verified in a browser · ⬜ not started.

## Done

| Item | State | Evidence |
|---|---|---|
| Vite + React + TS skeleton, dark theme, 4 tabs, 60/40 layout | 🟡 | `vite build` succeeds; not opened in a browser yet |
| Contract types generated from schemas (`npm run gen:types`) | ✅ | `tsc --noEmit` clean |
| Resilient SSE client (backoff, stale watchdog, browser Last-Event-ID resume) | 🟡 | backoff bounds tested; reconnect not exercised |
| Store with bounded rings and id de-duplication | ✅ | U-5 test (replayed ledger events add no rows) |
| HeatMap (3×5 routes coloured by d3_score, localizer primary outlined, click selects) | 🟡 | renders from ticks; not visually checked |
| RecommendationCard: approve all / selected / reject, operator dropdown, blocked actions locked | ✅ (logic) | U-4 test on the fixture (blocked SHIFT_TRAFFIC never sent) |
| DecisionLog ("recording on ledger…" until DecisionRecorded), DrunixPanel ("ledger offline" instead of numbers) | 🟡 | not visually checked |
| MOCK fallback from fixtures when M4 is unreachable | 🟡 | implemented in `connect.ts` |
| Claims lint over `text/claims.ts` and every `.tsx` | ✅ | U-8 test |
| `npm audit` clean | ✅ | Vite 7.3.7 / Vitest 4.1.12 (spec said Vite 5; see docs/DEVIATIONS.md) |

## Open items (summary — the detailed task cards are in `ROADMAP.md`), in day order (§10)

1. **Day 1–2:** open it in a browser against `make run-mock` services and against nothing (U-1: badges, no crash); Playwright snapshot of every panel on fixtures (U-2, not installed yet); U-3 approve flow against M4 mock ≤ 2 s with tx id shown.
2. Build the placeholder panels (each names its source and acceptance test in `src/panels/Placeholders.tsx`): MetricStrip (uPlot sparklines), DetectorRace, CascadeMap (needs M3's trained grid), VerificationPanel (M2 timeseries + M4 budget events), Header polling M2 `/v1/status`.
3. **Day 3:** root `docker-compose.yml` profiles `live` and `mock` (skeleton exists at the repo root, untested: Docker not installed on the dev machine); `scripts/integration_smoke.sh` per §6 — a Python version of this smoke already ran on 2026-10-20 (see root README).
4. **Day 4:** Arena tab (M2 `/v1/results`, U2 always next to U4, "simulation" labels), `scripts/record.ts` + `streams/replay.ts` (`?mode=replay&rec=`), April-2025 split replay (U-6); deck screenshots.
5. **Day 5:** polish, rehearse twice, backup video.

## Known issues
- `EventSource` cannot send headers, so a connection rebuilt after the browser gives up starts from "now" (the browser's own reconnects do resume with Last-Event-ID). Use a fetch-based SSE reader if full resume is needed.
- The API key for decisions comes from `VITE_QS_API_KEY` at build time — fine for a local demo, not for anything shared.

## Reused from the IBM project
Layout ideas only (heat map, detector race, arena tab, decision log). The IBM console was plain JS + canvas; nothing was copied.
