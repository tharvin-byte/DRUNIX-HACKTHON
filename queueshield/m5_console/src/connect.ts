// Wires streams to the store, with MOCK fallback from contracts/fixtures when a service is unreachable
// (docs/M5_CONSOLE.md §4). A panel never mixes mock and live data: each source has one badge.
import { config } from "./config";
import type { Decision, LedgerEvent, Recommendation, SegmentState } from "./contracts";
import { useQs } from "./store";
import { openStream } from "./streams/sse";
import recommendationFx from "../../contracts/fixtures/recommendation.json";
import ledgerEventsFx from "../../contracts/fixtures/ledger_events.jsonl?raw";

const s = () => useQs.getState();

export function loadMockFixtures(): void {
  s().upsertRec(recommendationFx as unknown as Recommendation);
  for (const line of ledgerEventsFx.split("\n").filter(Boolean)) s().addLedgerEvent(JSON.parse(line) as LedgerEvent);
  s().setSource("control", "mock");
  s().setSource("ledger", "mock");
}

export function connectAll(): () => void {
  const handles = [
    openStream(`${config.detectUrl}/v1/stream`, ["tick"], (_e, d) => s().addTick(d as SegmentState),
      (st) => s().setSource("detect", st === "live" ? "live" : "offline")),
    openStream(`${config.controlUrl}/v1/stream`, ["recommendation", "decision"], (e, d) => {
      if (e === "recommendation") s().upsertRec(d as Recommendation);
      else s().addDecision(d as never);
    }, (st) => s().setSource("control", st === "live" ? "live" : s().sources.control === "mock" ? "mock" : "offline")),
    openStream(`${config.ledgerUrl}/v1/stream`, ["ledger_event"], (_e, d) => s().addLedgerEvent(d as LedgerEvent),
      (st) => s().setSource("ledger", st === "live" ? "live" : s().sources.ledger === "mock" ? "mock" : "offline")),
  ];
  // if control is unreachable at start, show the fixture recommendation with a MOCK badge
  const t = setTimeout(() => { if (s().sources.control === "offline") loadMockFixtures(); }, 3000);
  return () => { clearTimeout(t); handles.forEach((h) => h.close()); };
}

export async function postDecision(d: Decision): Promise<{ ok: boolean; body: unknown }> {
  if (s().sources.control === "mock") {
    return { ok: true, body: { rec_id: d.rec_id, status: "APPROVED", action_ids: [], ledger: { decision_tx: null } } };
  }
  const r = await fetch(`${config.controlUrl}/v1/decisions`, {
    method: "POST", headers: { "content-type": "application/json", "x-qs-key": config.apiKey }, body: JSON.stringify(d),
  });
  return { ok: r.ok, body: await r.json() };
}

export async function startScenario(scenario: string, seed: number, universe = "U4", speed = 1): Promise<boolean> {
  const r = await fetch(`${config.simUrl}/v1/scenario`, {
    method: "POST", headers: { "content-type": "application/json", "x-qs-key": config.apiKey },
    body: JSON.stringify({ command: "START", scenario, seed, universe, speed }),
  }).catch(() => null);
  return !!r && r.ok;
}
