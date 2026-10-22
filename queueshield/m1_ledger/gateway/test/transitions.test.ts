// L2 (TypeScript side): every golden vector in m1_ledger/testdata/transitions.json.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { QsError, apply, checkTat } from "../src/mock/transitions.ts";
import type { Kind, Payment, State } from "../src/mock/transitions.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const vectors = JSON.parse(fs.readFileSync(path.resolve(here, "../../testdata/transitions.json"), "utf8"));

function payment(state: State): Payment {
  return { docType: "payment", txnRef: "r-S6-1-U4:p-0000001", idemKeyHash: "sha256:" + "0".repeat(64), payerPsp: "P1",
    remitterBank: "B1", beneficiaryBank: "B2", runId: "r-S6-1-U4", state, openedAt: 900, openedSimMs: 0, debitAt: null,
    creditAt: null, failureAt: null, reversalAt: null, reasonCode: null, debitImplied: false, tatSeconds: 120,
    tatDeadline: null, tatBreached: false, attestations: [], version: 3 };
}

test("golden vectors: every cell and wrong-MSP case", () => {
  assert.ok(vectors.cases.length >= 70);
  for (const [i, c] of vectors.cases.entries()) {
    const p = payment(c.from);
    if (c.expect_error) {
      assert.throws(() => apply(p, c.kind as Kind, c.mspId, 1000, 5000), (e: unknown) =>
        e instanceof QsError && e.message.startsWith(c.expect_error), `case ${i}`);
      continue;
    }
    const r = apply(p, c.kind as Kind, c.mspId, 1000, 5000);
    assert.equal(r.payment.state, c.expect_state, `case ${i} state`);
    assert.equal(r.noop, c.noop, `case ${i} noop`);
    assert.equal(r.payment.version - 3, c.version_increment, `case ${i} version`);
    assert.equal(r.event, c.event ?? null, `case ${i} event`);
    assert.equal(r.disputedReason, c.disputed_reason ?? "", `case ${i} disputed reason`);
    if (c.debit_implied) assert.equal(r.payment.debitImplied, true, `case ${i} debitImplied`);
    if (c.sets_tat_deadline) assert.equal(r.payment.tatDeadline, 1120, `case ${i} tatDeadline`);
    assert.equal(p.version, 3, `case ${i} input not mutated`);
  }
});

test("TAT breach recorded once, only after the deadline", () => {
  const p = { ...payment("DEBITED"), tatDeadline: 100 };
  assert.equal(checkTat(p, 100).noop, true);
  const r = checkTat(p, 101);
  assert.equal(r.event, "TATBreach");
  assert.equal(checkTat(r.payment, 500).noop, true);
});
