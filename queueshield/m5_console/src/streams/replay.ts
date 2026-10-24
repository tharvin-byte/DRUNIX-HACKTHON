// Replay mode (docs/M5_CONSOLE.md §4, M5-T05, U-6).
// Plays recordings `{"stream","sim_ms","data"}` at 1x/2x/4x into the same Zustand store.
// Replaying at 1x and 4x applies the exact same sequence of events and yields identical final store state (U-6).
import type { DecisionRow, BudgetPoint, TimeseriesPoint } from "../store";
import { useQs } from "../store";
import type { LedgerEvent, Recommendation, SegmentState } from "../contracts";
import {
  buildScenarioBudgets,
  buildScenarioRec,
  buildScenarioTicks,
  buildScenarioTimeseries,
} from "../mockData";
import ledgerEventsFx from "../../../contracts/fixtures/ledger_events.jsonl?raw";

export interface ReplayLine {
  stream: "tick" | "recommendation" | "decision" | "ledger_event" | "timeseries" | "budget" | "ground_truth";
  sim_ms: number;
  data: unknown;
}

export function parseRecording(jsonl: string): ReplayLine[] {
  return jsonl
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l) as ReplayLine)
    .sort((a, b) => a.sim_ms - b.sim_ms);
}

export function buildRecordingForScenario(
  scenario: string,
  universe: "U0" | "U2" | "U4" = "U4",
  seed = 1
): ReplayLine[] {
  const lines: ReplayLine[] = [];
  if (scenario !== "S0" && scenario !== "S1") {
    lines.push({
      stream: "ground_truth",
      sim_ms: 0,
      data: { onset_ms: 120_000, scenario, universe },
    });
  }
  const ticks = buildScenarioTicks(scenario, seed, universe);
  for (const t of ticks) {
    lines.push({ stream: "tick", sim_ms: t.tick_sim_ms, data: t });
  }
  const ts = buildScenarioTimeseries(scenario, universe);
  lines.push({ stream: "timeseries", sim_ms: 180_000, data: ts });

  const budgets = buildScenarioBudgets(scenario);
  for (const b of budgets) {
    lines.push({ stream: "budget", sim_ms: b.sim_ms, data: b });
  }

  const rec = buildScenarioRec(scenario, seed);
  if (rec) {
    lines.push({ stream: "recommendation", sim_ms: rec.created_sim_ms, data: rec });
  }

  const fxEvents = ledgerEventsFx
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l) as LedgerEvent);
  fxEvents.forEach((ev, idx) => {
    lines.push({ stream: "ledger_event", sim_ms: 120_000 + idx * 5_000, data: ev });
  });

  return lines.sort((a, b) => a.sim_ms - b.sim_ms);
}

export function getBuiltInRecording(name: string): ReplayLine[] {
  const norm = name.toLowerCase();
  if (norm.includes("s6") && norm.includes("u0")) return buildRecordingForScenario("S6", "U0", 1);
  if (norm.includes("s6")) return buildRecordingForScenario("S6", "U4", 1);
  if (norm.includes("s3")) return buildRecordingForScenario("S3", "U4", 1);
  if (norm.includes("s1")) return buildRecordingForScenario("S1", "U4", 1);
  if (norm.includes("s0")) return buildRecordingForScenario("S0", "U4", 1);
  if (norm.includes("s8")) return buildRecordingForScenario("S8", "U4", 1);
  return buildRecordingForScenario("S4", "U4", 1);
}

export function applyReplayLine(line: ReplayLine): void {
  const st = useQs.getState();
  switch (line.stream) {
    case "ground_truth": {
      const gt = line.data as { onset_ms?: number; onset_sim_ms?: number };
      st.setGroundTruthOnsetMs(gt.onset_ms ?? gt.onset_sim_ms ?? null);
      break;
    }
    case "tick": {
      const t = line.data as SegmentState;
      st.addTick(t);
      const parts = t.run_id.split("-");
      st.setSimStatus({
        state: "RUNNING",
        run_id: t.run_id,
        scenario: parts[1] ?? "S4",
        seed: Number(parts[2] ?? 1),
        universe: t.universe,
        sim_ms: t.tick_sim_ms,
        mode: "replay",
      });
      break;
    }
    case "recommendation":
      st.upsertRec(line.data as Recommendation);
      break;
    case "decision":
      st.addDecision(line.data as DecisionRow);
      break;
    case "ledger_event":
      st.addLedgerEvent(line.data as LedgerEvent);
      break;
    case "timeseries":
      st.setTimeseries(line.data as TimeseriesPoint[]);
      break;
    case "budget":
      st.addBudget(line.data as BudgetPoint);
      break;
  }
}

export async function runReplayAtSpeed(lines: ReplayLine[], speed: 1 | 2 | 4 = 1, maxStepDelayMs = 4): Promise<void> {
  const st = useQs.getState();
  st.resetForReplay();
  st.setGroundTruthOnsetMs(null);
  const ordered = [...lines].sort((a, b) => a.sim_ms - b.sim_ms);
  for (let i = 0; i < ordered.length; i++) {
    applyReplayLine(ordered[i]);
    if (maxStepDelayMs > 0) {
      const wait = Math.max(0, Math.round(maxStepDelayMs / speed));
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }
  }
}

export interface ReplayHandle {
  pause(): void;
  resume(): void;
  setSpeed(s: 1 | 2 | 4): void;
  close(): void;
}

export function startReplayStream(lines: ReplayLine[], initialSpeed: 1 | 2 | 4 = 1): ReplayHandle {
  const st = useQs.getState();
  st.resetForReplay();
  st.setSource("sim", "mock");
  st.setSource("detect", "mock");
  st.setSource("control", "mock");
  st.setSource("ledger", "mock");

  const ordered = [...lines].sort((a, b) => a.sim_ms - b.sim_ms);
  let idx = 0;
  let paused = false;
  let speed: 1 | 2 | 4 = initialSpeed;
  let timer: ReturnType<typeof setTimeout> | null = null;

  // Apply initial burst up to first 5 ticks immediately so panels render right away
  let tickCount = 0;
  while (idx < ordered.length && tickCount < 5) {
    if (ordered[idx].stream === "tick") tickCount++;
    applyReplayLine(ordered[idx]);
    idx++;
  }

  const step = () => {
    if (paused || idx >= ordered.length) return;
    const currentSimMs = ordered[idx].sim_ms;
    while (idx < ordered.length && ordered[idx].sim_ms <= currentSimMs) {
      applyReplayLine(ordered[idx]);
      idx++;
    }
    if (idx < ordered.length) {
      const delay = Math.max(40, Math.round(320 / speed));
      timer = setTimeout(step, delay);
    }
  };

  timer = setTimeout(step, Math.round(250 / speed));

  return {
    pause() {
      paused = true;
      if (timer) clearTimeout(timer);
    },
    resume() {
      if (!paused) return;
      paused = false;
      step();
    },
    setSpeed(s: 1 | 2 | 4) {
      speed = s;
      const cur = useQs.getState().simStatus;
      if (cur) useQs.getState().setSimStatus({ ...cur, speed: s });
    },
    close() {
      paused = true;
      if (timer) clearTimeout(timer);
    },
  };
}
