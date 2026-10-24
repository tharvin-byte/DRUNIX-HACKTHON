// Zustand store (docs/M5_CONSOLE.md §4). Keeps only what panels need, in bounded rings. No business logic here:
// every number shown comes from a stream or a results file.
import { useSyncExternalStore } from "react";
import { createStore } from "zustand/vanilla";
import { config } from "../config";
import type { LedgerEvent, PaymentEvent, Recommendation, RunResult, SegmentState } from "../contracts";

export type Source = "live" | "mock" | "offline";

export interface DecisionRow {
  rec_id: string;
  decision_id?: string;
  operator?: string;
  decision?: string;
  action_ids: string[];
  status: string;
  decided_sim_ms?: number;
  ledger_tx?: string | null;
  ledger_block?: number | null;
}

export interface SimStatus {
  state: string;
  run_id?: string | null;
  scenario?: string;
  seed?: number;
  universe?: string;
  sim_ms: number;
  speed?: number;
  events?: number;
  mode?: "live" | "mock" | "replay";
}

export interface TimeseriesPoint {
  sim_ms: number;
  goodput_per_s: number;
  psp_queue: number;
  switch_checks_per_s: number;
  switch_status_util: number;
  switch_slowdown: number;
  unknown_open: number;
  unknown_resolved_per_s: number;
}

export interface BudgetPoint {
  sim_ms: number;
  total_budget_per_s: number;
  by_psp?: Record<string, number>;
}

export interface ForecasterGridData {
  version: string;
  delay_bins: number[];
  orbit_bins: number[];
  p: number[][];
  contour_0_5: [number, number][];
}

export interface OperatorSweepRow {
  operator_delay_s: number;
  recovery_time_s: number;
  excess_retries: number;
  peak_queue: number;
  goodput_min_frac: number;
}

export interface QsState {
  sources: Record<"sim" | "detect" | "control" | "ledger", Source>;
  simStatus: SimStatus | null;
  ticks: SegmentState[];
  recs: Record<string, Recommendation>;
  decisions: DecisionRow[];
  ledgerEvents: LedgerEvent[];
  lastPaymentEvents: PaymentEvent[];
  timeseries: TimeseriesPoint[];
  budgets: BudgetPoint[];
  forecasterGrid: ForecasterGridData | null;
  groundTruthOnsetMs: number | null;
  arenaResults: RunResult[];
  arenaSeries: Record<string, TimeseriesPoint[]>;
  operatorSweep: OperatorSweepRow[];
  selectedSegment: string;
  seenIds: Set<string>;
  setSource(k: keyof QsState["sources"], s: Source): void;
  setSimStatus(st: SimStatus | null): void;
  addTick(t: SegmentState): void;
  upsertRec(r: Recommendation): void;
  addDecision(d: DecisionRow): void;
  addLedgerEvent(e: LedgerEvent): void;
  setTimeseries(pts: TimeseriesPoint[]): void;
  addBudget(b: BudgetPoint): void;
  setForecasterGrid(g: ForecasterGridData | null): void;
  setGroundTruthOnsetMs(ms: number | null): void;
  setArenaData(results: RunResult[], series?: Record<string, TimeseriesPoint[]>, sweep?: OperatorSweepRow[]): void;
  select(segmentId: string): void;
  resetForReplay(): void;
}

function pushRing<T>(arr: T[], x: T, n: number): T[] {
  const out = arr.length >= n ? arr.slice(arr.length - n + 1) : arr.slice();
  out.push(x);
  return out;
}

const qsStore = createStore<QsState>((set, get) => ({
  sources: { sim: "offline", detect: "offline", control: "offline", ledger: "offline" },
  simStatus: null,
  ticks: [],
  recs: {},
  decisions: [],
  ledgerEvents: [],
  lastPaymentEvents: [],
  timeseries: [],
  budgets: [],
  forecasterGrid: null,
  groundTruthOnsetMs: null,
  arenaResults: [],
  arenaSeries: {},
  operatorSweep: [],
  selectedSegment: "platform:*:*",
  seenIds: new Set(),
  setSource: (k, s) => set((st) => ({ sources: { ...st.sources, [k]: s } })),
  setSimStatus: (simStatus) => set({ simStatus }),
  addTick: (t) => {
    const key = `tick:${t.run_id}:${t.tick_sim_ms}`;
    if (get().seenIds.has(key)) return;                     // U-5: replayed messages never duplicate rows
    get().seenIds.add(key);
    set((st) => ({ ticks: pushRing(st.ticks, t, config.ring.ticks) }));
  },
  upsertRec: (r) => set((st) => ({ recs: { ...st.recs, [r.rec_id]: r } })),
  addDecision: (d) => set((st) => {
    const existing = st.decisions.find((x) => x.rec_id === d.rec_id);
    const merged: DecisionRow = existing
      ? {
          ...existing,
          ...d,
          ledger_tx: d.ledger_tx ?? existing.ledger_tx ?? null,
          ledger_block: d.ledger_block ?? existing.ledger_block ?? null,
        }
      : d;
    const rest = st.decisions.filter((x) => x.rec_id !== d.rec_id);
    return { decisions: [merged, ...rest] };
  }),
  addLedgerEvent: (e) => {
    if (get().seenIds.has(e.event_id)) return;
    get().seenIds.add(e.event_id);
    set((st) => {
      const payload = e.payload as { id?: string; recId?: string };
      const decisions = e.name === "DecisionRecorded"
        ? st.decisions.map((d) =>
            (d.decision_id && d.decision_id === payload.id) || (payload.recId && d.rec_id === payload.recId) || (!d.ledger_tx && st.decisions[0]?.rec_id === d.rec_id)
              ? { ...d, ledger_tx: e.tx_id, ledger_block: e.block_number }
              : d
          )
        : st.decisions;
      return { ledgerEvents: pushRing(st.ledgerEvents, e, config.ring.ledgerEvents), decisions };
    });
  },
  setTimeseries: (timeseries) => set({ timeseries }),
  addBudget: (b) => set((st) => ({ budgets: pushRing(st.budgets, b, config.ring.ticks) })),
  setForecasterGrid: (forecasterGrid) => set({ forecasterGrid }),
  setGroundTruthOnsetMs: (groundTruthOnsetMs) => set({ groundTruthOnsetMs }),
  setArenaData: (arenaResults, arenaSeries, operatorSweep) =>
    set((st) => ({
      arenaResults,
      arenaSeries: arenaSeries ?? st.arenaSeries,
      operatorSweep: operatorSweep ?? st.operatorSweep,
    })),
  select: (segmentId) => set({ selectedSegment: segmentId }),
  resetForReplay: () =>
    set({
      ticks: [],
      recs: {},
      decisions: [],
      ledgerEvents: [],
      timeseries: [],
      budgets: [],
      seenIds: new Set(),
    }),
}));

export const useQs = Object.assign(
  function useQsHook<T>(selector: (state: QsState) => T): T {
    return useSyncExternalStore(
      qsStore.subscribe,
      () => selector(qsStore.getState()),
      () => selector(qsStore.getState())
    );
  },
  {
    getState: qsStore.getState,
    setState: qsStore.setState,
    subscribe: qsStore.subscribe,
  }
);


