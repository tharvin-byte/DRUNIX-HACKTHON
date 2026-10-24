// Wires streams to the store, with MOCK fallback from contracts/fixtures when a service is unreachable
// (docs/M5_CONSOLE.md §4). A panel never mixes mock and live data: each source has one badge.
import { config } from "./config";
import type { Decision, LedgerEvent, Recommendation, RunResult, SegmentState } from "./contracts";
import {
  buildMockArenaData,
  buildMockForecasterGrid,
  buildScenarioBudgets,
  buildScenarioTicks,
  buildScenarioTimeseries,
} from "./mockData";
import type { BudgetPoint, DecisionRow, ForecasterGridData, SimStatus, TimeseriesPoint } from "./store";
import { useQs } from "./store";
import {
  buildRecordingForScenario,
  getBuiltInRecording,
  type ReplayHandle,
  startReplayStream,
} from "./streams/replay";
import { openStream } from "./streams/sse";
import recommendationFx from "../../contracts/fixtures/recommendation.json";
import ledgerEventsFx from "../../contracts/fixtures/ledger_events.jsonl?raw";

const s = () => useQs.getState();

let activeReplay: ReplayHandle | null = null;
let mockDecCounter = 10;

export function loadMockFixtures(scenario = "S3"): void {
  const st = s();
  st.setForecasterGrid(buildMockForecasterGrid());
  const arena = buildMockArenaData();
  st.setArenaData(arena.results, arena.series, arena.sweep);

  const ticks = buildScenarioTicks(scenario, 1, "U4");
  for (const t of ticks) st.addTick(t);
  st.setTimeseries(buildScenarioTimeseries(scenario, "U4"));
  for (const b of buildScenarioBudgets(scenario)) st.addBudget(b);

  st.upsertRec(recommendationFx as unknown as Recommendation);
  for (const line of ledgerEventsFx.split("\n").filter(Boolean)) {
    st.addLedgerEvent(JSON.parse(line) as LedgerEvent);
  }
  const lastTick = ticks[ticks.length - 1];
  st.setSimStatus({
    state: "RUNNING",
    run_id: lastTick?.run_id ?? "r-S3-1-U4",
    scenario,
    seed: 1,
    universe: "U4",
    sim_ms: lastTick?.tick_sim_ms ?? 180_000,
    speed: 1,
    mode: "mock",
  });
  st.setGroundTruthOnsetMs(null); // Live/mock live tab keeps onset unknown per Pitfall 2
  st.setSource("sim", "mock");
  st.setSource("detect", "mock");
  st.setSource("control", "mock");
  // Keep ledger source honest: mock if fixtures loaded, or offline if explicitly tested offline
  st.setSource("ledger", "mock");
}

export function connectAll(): () => void {
  // Check URL query params for replay mode (?mode=replay&rec=<name>&speed=1|2|4)
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") === "replay") {
      const recName = params.get("rec") ?? "s6_u4";
      const rawSpeed = Number(params.get("speed") ?? "1");
      const speed: 1 | 2 | 4 = rawSpeed === 4 ? 4 : rawSpeed === 2 ? 2 : 1;
      s().setForecasterGrid(buildMockForecasterGrid());
      const arena = buildMockArenaData();
      s().setArenaData(arena.results, arena.series, arena.sweep);
      const lines = getBuiltInRecording(recName);
      activeReplay = startReplayStream(lines, speed);
      return () => {
        activeReplay?.close();
        activeReplay = null;
      };
    }

    const wantLive =
      params.get("mode") === "live" ||
      (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_LIVE_SERVICES === "1";

    if (!wantLive) {
      loadMockFixtures("S3");
      return () => {
        activeReplay?.close();
        activeReplay = null;
      };
    }
  }

  // Load forecaster grid and arena results immediately from mock, then upgrade if live endpoints answer
  s().setForecasterGrid(buildMockForecasterGrid());
  const mockArena = buildMockArenaData();
  s().setArenaData(mockArena.results, mockArena.series, mockArena.sweep);

  fetch(`${config.detectUrl}/v1/forecaster/grid`)
    .then((r) => (r.ok ? r.json() : null))
    .then((g: ForecasterGridData | null) => {
      if (g && Array.isArray(g.p)) s().setForecasterGrid(g);
    })
    .catch(() => {});

  fetch(`${config.simUrl}/v1/results`)
    .then((r) => (r.ok ? r.json() : null))
    .then((res: RunResult[] | null) => {
      if (res && Array.isArray(res) && res.length > 0) {
        s().setArenaData(res);
      }
    })
    .catch(() => {});

  const handles = [
    openStream(
      `${config.detectUrl}/v1/stream`,
      ["tick"],
      (_e, d) => {
        s().setGroundTruthOnsetMs(null);
        s().addTick(d as SegmentState);
      },
      (st) => s().setSource("detect", st === "live" ? "live" : s().sources.detect === "mock" ? "mock" : "offline")
    ),
    openStream(
      `${config.controlUrl}/v1/stream`,
      ["recommendation", "decision", "budget"],
      (e, d) => {
        if (e === "recommendation") s().upsertRec(d as Recommendation);
        else if (e === "budget") {
          const b = d as { sim_ms?: number; total_budget_per_s?: number; budgets?: Record<string, number> };
          const total =
            b.total_budget_per_s ??
            Object.values(b.budgets ?? {}).reduce((acc, v) => acc + Number(v || 0), 0);
          s().addBudget({
            sim_ms: b.sim_ms ?? s().simStatus?.sim_ms ?? 120_000,
            total_budget_per_s: total,
            by_psp: b.budgets,
          } as BudgetPoint);
        } else {
          const raw = d as {
            rec_id: string;
            decision_id?: string;
            operator?: string;
            decision?: string;
            action_ids?: string[];
            status?: string;
            decided_sim_ms?: number;
            ledger?: { decision_tx?: string | null; block_number?: number | null };
          };
          const row: DecisionRow = {
            rec_id: raw.rec_id,
            decision_id: raw.decision_id,
            operator: raw.operator,
            decision: raw.decision,
            action_ids: raw.action_ids ?? [],
            status: raw.status ?? "APPROVED",
            decided_sim_ms: raw.decided_sim_ms,
            ledger_tx: raw.ledger?.decision_tx ?? null,
            ledger_block: raw.ledger?.block_number ?? null,
          };
          s().addDecision(row);
        }
      },
      (st) => s().setSource("control", st === "live" ? "live" : s().sources.control === "mock" ? "mock" : "offline")
    ),
    openStream(
      `${config.ledgerUrl}/v1/stream`,
      ["ledger_event"],
      (_e, d) => s().addLedgerEvent(d as LedgerEvent),
      (st) => s().setSource("ledger", st === "live" ? "live" : s().sources.ledger === "mock" ? "mock" : "offline")
    ),
  ];

  // Poll M2 /v1/status & /v1/timeseries and all /v1/health every 1 s (M5-T01, M5-T03)
  const pollStatusAndTimeseries = () => {
    fetch(`${config.simUrl}/v1/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((st: SimStatus | null) => {
        if (st && typeof st.sim_ms === "number") {
          s().setSource("sim", "live");
          s().setSimStatus({ ...st, mode: "live" });
        }
      })
      .catch(() => {
        if (s().sources.sim !== "mock") s().setSource("sim", "offline");
      });

    fetch(`${config.simUrl}/v1/timeseries`)
      .then((r) => (r.ok ? r.json() : null))
      .then((ts: TimeseriesPoint[] | { points?: TimeseriesPoint[] } | null) => {
        if (!ts) return;
        const arr = Array.isArray(ts) ? ts : ts.points;
        if (Array.isArray(arr) && arr.length > 0) {
          s().setTimeseries(arr);
        }
      })
      .catch(() => {});
  };

  pollStatusAndTimeseries();
  const pollTimer = setInterval(pollStatusAndTimeseries, config.statusPollMs);

  // If backend services are unreachable, load mock fixtures immediately so the console is rich and interactive
  const t = setTimeout(() => {
    if (s().sources.control === "offline" && s().ticks.length === 0) {
      loadMockFixtures("S3");
    }
  }, 600);

  return () => {
    clearTimeout(t);
    clearInterval(pollTimer);
    activeReplay?.close();
    activeReplay = null;
    handles.forEach((h) => h.close());
  };
}

export async function postDecision(d: Decision): Promise<{ ok: boolean; body: unknown }> {
  if (s().sources.control === "mock" || s().sources.control === "offline") {
    const decId = `dec-000${++mockDecCounter}`;
    const actionIds =
      d.decision === "REJECT"
        ? []
        : d.decision === "APPROVE_SELECTED"
        ? d.actions_selected.map((_, i) => `act-${i + 1}`)
        : ["act-1", "act-2"];
    const status = d.decision === "REJECT" ? "REJECTED" : d.decision === "APPROVE_SELECTED" ? "PARTIAL" : "APPROVED";

    // Emit DecisionRecorded ledger event shortly after so U-3 ("recording on ledger…" -> tx + block) is visible
    setTimeout(() => {
      const txHash = `9f8a7b6c${decId.replace(/\D/g, "")}e4d3c2b1a09876543210`;
      s().addLedgerEvent({
        event_id: `${txHash}:DecisionRecorded`,
        name: "DecisionRecorded",
        tx_id: txHash,
        block_number: 40 + mockDecCounter,
        chaincode: "queueshield",
        received_wall_iso: new Date().toISOString(),
        payload: { id: decId, recId: d.rec_id, operator: d.operator, decision: d.decision },
      });
    }, 350);

    return {
      ok: true,
      body: {
        rec_id: d.rec_id,
        decision_id: decId,
        status,
        action_ids: actionIds,
        ledger: { decision_tx: null, block_number: null },
      },
    };
  }
  const r = await fetch(`${config.controlUrl}/v1/decisions`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-qs-key": config.apiKey },
    body: JSON.stringify(d),
  });
  return { ok: r.ok, body: await r.json() };
}

export async function startScenario(
  scenario: string,
  seed: number,
  universe: "U0" | "U2" | "U4" = "U4",
  speed: 1 | 2 | 4 = 1
): Promise<boolean> {
  if (s().sources.sim === "live") {
    const r = await fetch(`${config.simUrl}/v1/scenario`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-qs-key": config.apiKey },
      body: JSON.stringify({ command: "START", scenario, seed, universe, speed }),
    }).catch(() => null);
    if (r && r.ok) return true;
  }

  // Fallback to interactive mock playback when simulator backend is not running
  activeReplay?.close();
  const lines = buildRecordingForScenario(scenario, universe, seed);
  // Keep onset unknown on Live tab unless URL explicitly requested replay mode
  const filteredLines = lines.filter((l) => l.stream !== "ground_truth");
  activeReplay = startReplayStream(filteredLines, speed);
  s().setSimStatus({
    state: "RUNNING",
    run_id: `r-${scenario}-${seed}-${universe}`,
    scenario,
    seed,
    universe,
    sim_ms: 120_000,
    speed,
    mode: "mock",
  });
  return true;
}

export async function controlScenario(command: "PAUSE" | "RESUME" | "RESET", speed?: 1 | 2 | 4): Promise<void> {
  if (s().sources.sim === "live") {
    const r = await fetch(`${config.simUrl}/v1/scenario`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-qs-key": config.apiKey },
      body: JSON.stringify({ command, ...(speed ? { speed } : {}) }),
    }).catch(() => null);
    if (r && r.ok) return;
  }

  if (command === "PAUSE") {
    activeReplay?.pause();
    const cur = s().simStatus;
    if (cur) s().setSimStatus({ ...cur, state: "PAUSED" });
  } else if (command === "RESUME") {
    activeReplay?.resume();
    const cur = s().simStatus;
    if (cur) s().setSimStatus({ ...cur, state: "RUNNING" });
  } else if (command === "RESET") {
    activeReplay?.close();
    activeReplay = null;
    loadMockFixtures("S0");
  }
}

export function changeReplaySpeed(speed: 1 | 2 | 4): void {
  activeReplay?.setSpeed(speed);
  const cur = s().simStatus;
  if (cur) s().setSimStatus({ ...cur, speed });
}
