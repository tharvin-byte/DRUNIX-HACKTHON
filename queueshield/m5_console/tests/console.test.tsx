// Acceptance tests U-1..U-6 for M5 Console panels, store correlation, and replay parity (docs/M5_CONSOLE.md §9).
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import { loadMockFixtures } from "../src/connect";
import { HeatMap } from "../src/panels/HeatMap";
import { DecisionLog, DrunixPanel } from "../src/panels/LedgerPanels";
import {
  About,
  ArenaTab,
  CascadeMap,
  DetectorRace,
  MetricStrip,
  SplitReplay,
  VerificationPanel,
} from "../src/panels/Placeholders";
import { RecommendationCard } from "../src/panels/RecommendationCard";
import { useQs } from "../src/store";
import { getBuiltInRecording, parseRecording, runReplayAtSpeed } from "../src/streams/replay";

describe("M5 Console panels & acceptance checks (U-1..U-6)", () => {
  beforeEach(() => {
    useQs.getState().resetForReplay();
  });

  it("U-1: renders offline state honestly when all services are down (never fakes ledger numbers)", () => {
    const st = useQs.getState();
    st.setSource("sim", "offline");
    st.setSource("detect", "offline");
    st.setSource("control", "offline");
    st.setSource("ledger", "offline");

    const drunixHtml = renderToStaticMarkup(<DrunixPanel />);
    expect(drunixHtml).toContain("ledger offline");
    expect(drunixHtml).toContain("TAT breaches: —");
  });

  it("U-2: every panel renders from fixtures with simulation labels", () => {
    loadMockFixtures("S4");

    const heatHtml = renderToStaticMarkup(<HeatMap />);
    expect(heatHtml).toContain("Heat map");
    expect(heatHtml).toContain("verdict:");

    const metricHtml = renderToStaticMarkup(<MetricStrip />);
    expect(metricHtml).toContain("Metric strip");
    expect(metricHtml).toContain("Timeout rate");
    expect(metricHtml).toContain("simulation");

    const raceHtml = renderToStaticMarkup(<DetectorRace />);
    expect(raceHtml).toContain("Detector race");
    expect(raceHtml).toContain("onset unknown"); // Pitfall 2: live mode hides ground-truth onset
    expect(raceHtml).toContain("D3");

    const cascadeHtml = renderToStaticMarkup(<CascadeMap />);
    expect(cascadeHtml).toContain("Cascade map");
    expect(cascadeHtml).toContain("point of no return (p_stuck = 0.5)");
    expect(cascadeHtml).toContain("rough estimate");

    const recHtml = renderToStaticMarkup(<RecommendationCard />);
    expect(recHtml).toContain("Supporting signals, not proof of cause");
    expect(recHtml).toContain("SHIFT_TRAFFIC");

    const verHtml = renderToStaticMarkup(<VerificationPanel />);
    expect(verHtml).toContain("Verification");
    expect(verHtml).toContain("Switch checks/s");

    const arenaHtml = renderToStaticMarkup(<ArenaTab />);
    expect(arenaHtml).toContain("U0 · Unprotected");
    expect(arenaHtml).toContain("U2 · Tuned static baseline");
    expect(arenaHtml).toContain("U4 · QueueShield + Drunix");
    expect(arenaHtml).toContain("simulation, 5 seeds, preliminary");

    const splitHtml = renderToStaticMarkup(<SplitReplay />);
    expect(splitHtml).toContain("replay of simulation runs");
    expect(splitHtml).toContain("U0 — Unprotected");
    expect(splitHtml).toContain("U4 — QueueShield + Drunix");

    const aboutHtml = renderToStaticMarkup(<About />);
    expect(aboutHtml).toContain("About &amp; claims");
  });

  it("U-3: DecisionLog transitions from 'recording on ledger…' to tx id + block when DecisionRecorded arrives", () => {
    const st = useQs.getState();
    st.addDecision({
      rec_id: "rec-0001",
      decision_id: "dec-00001",
      operator: "saran",
      decision: "APPROVE_SELECTED",
      action_ids: ["act-0001"],
      status: "PARTIAL",
      ledger_tx: null,
      ledger_block: null,
    });

    const beforeHtml = renderToStaticMarkup(<DecisionLog />);
    expect(beforeHtml).toContain("recording on ledger…");

    st.addLedgerEvent({
      event_id: "abcdef1234567890:DecisionRecorded",
      name: "DecisionRecorded",
      tx_id: "abcdef1234567890",
      block_number: 48,
      chaincode: "queueshield",
      received_wall_iso: "2026-10-20T12:00:00Z",
      payload: { id: "dec-00001", recId: "rec-0001" },
    });

    const afterHtml = renderToStaticMarkup(<DecisionLog />);
    expect(afterHtml).toContain("tx abcdef12");
    expect(afterHtml).toContain("block 48");
  });

  it("U-6: replay of s6_u4 recording reproduces the exact same final state at 1x and 4x", async () => {
    const recPath = path.resolve(__dirname, "../../data/recordings/s6_u4.jsonl");
    const lines = fs.existsSync(recPath)
      ? parseRecording(fs.readFileSync(recPath, "utf8"))
      : getBuiltInRecording("s6_u4");

    await runReplayAtSpeed(lines, 1, 0);
    const snap1x = {
      ticks: useQs.getState().ticks.length,
      recs: Object.keys(useQs.getState().recs),
      onset: useQs.getState().groundTruthOnsetMs,
    };
    const html1x = renderToStaticMarkup(
      <div>
        <HeatMap />
        <DetectorRace />
        <CascadeMap />
        <VerificationPanel />
      </div>
    );

    await runReplayAtSpeed(lines, 4, 0);
    const snap4x = {
      ticks: useQs.getState().ticks.length,
      recs: Object.keys(useQs.getState().recs),
      onset: useQs.getState().groundTruthOnsetMs,
    };
    const html4x = renderToStaticMarkup(
      <div>
        <HeatMap />
        <DetectorRace />
        <CascadeMap />
        <VerificationPanel />
      </div>
    );

    expect(snap1x).toEqual(snap4x);
    expect(html1x).toEqual(html4x);
    // In replay mode, ground-truth onset is known and displayed on DetectorRace
    expect(html1x).toContain("ground-truth onset: 60s (replay)");
  });
});
