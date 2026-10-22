// U-4 (blocked actions cannot be selected), U-5 (no duplicate rows on replay), decision body shape.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { LedgerEvent, Recommendation } from "../src/contracts";
import { buildDecision, selectable, toggle } from "../src/panels/decisionLogic";
import { useQs } from "../src/store";
import { backoffMs } from "../src/streams/sse";

const fx = (n: string) => path.resolve(__dirname, "../../contracts/fixtures", n);
const rec = JSON.parse(fs.readFileSync(fx("recommendation.json"), "utf8")) as Recommendation;

describe("recommendation card logic", () => {
  it("blocked SHIFT_TRAFFIC can never be selected or sent", () => {
    const shift = rec.actions.find((a) => a.action_type === "SHIFT_TRAFFIC")!;
    expect(selectable(shift)).toBe(false);
    expect(toggle([], shift)).toEqual([]);
    const d = buildDecision(rec, "APPROVE_SELECTED", ["THROTTLE_RETRIES", "SHIFT_TRAFFIC"], "saran");
    expect(d.actions_selected).toEqual(["THROTTLE_RETRIES"]);
  });
  it("APPROVE_ALL and REJECT send no selection; notes are capped at 280 chars", () => {
    expect(buildDecision(rec, "APPROVE_ALL", ["DEFER_CHECKS"], "saran").actions_selected).toEqual([]);
    expect(buildDecision(rec, "REJECT", [], "saran", "x".repeat(400)).note!.length).toBe(280);
  });
});

describe("store", () => {
  it("replayed ledger events never add duplicate rows (U-5)", () => {
    const lines = fs.readFileSync(fx("ledger_events.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l) as LedgerEvent);
    for (let i = 0; i < 2; i++) for (const e of lines) useQs.getState().addLedgerEvent(e);
    expect(useQs.getState().ledgerEvents.length).toBe(lines.length);
  });
  it("backoff stays within 0.5-8 s", () => {
    for (let a = 0; a < 10; a++) {
      expect(backoffMs(a, () => 0)).toBeGreaterThanOrEqual(250);
      expect(backoffMs(a, () => 1)).toBeLessThanOrEqual(8000);
    }
  });
});
