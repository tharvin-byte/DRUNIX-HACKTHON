// Mock gateway acceptance tests L3-L8 (docs/M1_LEDGER.md §8) against contracts/schemas.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildApp } from "../src/routes.ts";
import { check } from "../src/validate.ts";

const KEY = "test-key";
const H = { "x-qs-key": KEY };
const RUN = "r-S6-1-U4";
const ref = (n: number) => `${RUN}:p-${String(n).padStart(7, "0")}`;
const open = (n: number) => ({ txnRef: ref(n), idemKeyHash: "sha256:" + "a".repeat(64), payerPsp: "P1",
  remitterBank: "B3", beneficiaryBank: "B1", runId: RUN, simMs: 123020 });

function setup() {
  return buildApp({ apiKey: KEY, latencyScale: 0.01, mode: "mock" });
}

function ledgerEvents(hub: { replay: (id?: string) => string[] }) {
  return hub.replay("0").map((s) => JSON.parse(s.split("data: ")[1]));
}

test("L3: open -> debit -> credit = SUCCESS with exactly 3 PaymentUpdated events (L8 schemas)", async () => {
  const { app, hub } = setup();
  const o = await app.inject({ method: "POST", url: "/v1/payments", headers: H, payload: open(1) });
  assert.equal(o.statusCode, 201);
  assert.equal(check("ledger_payment", o.json().record), null);
  const again = await app.inject({ method: "POST", url: "/v1/payments", headers: H, payload: open(1) });
  assert.equal(again.statusCode, 200);                                   // identical open is idempotent
  const diff = await app.inject({ method: "POST", url: "/v1/payments", headers: H,
    payload: { ...open(1), payerPsp: "P2" } });
  assert.equal(diff.statusCode, 409);
  for (const kind of ["DEBIT", "CREDIT"]) {
    const r = await app.inject({ method: "POST", url: `/v1/payments/${encodeURIComponent(ref(1))}/attest`, headers: H,
      payload: { kind, simMs: 124000 } });
    assert.equal(r.statusCode, 200, r.body);
  }
  const g = await app.inject({ method: "GET", url: `/v1/payments/${encodeURIComponent(ref(1))}` });
  assert.equal(g.json().state, "SUCCESS");
  assert.equal(check("ledger_payment", g.json()), null);
  const evs = ledgerEvents(hub);
  assert.deepEqual(evs.map((e) => e.name), ["PaymentUpdated", "PaymentUpdated", "PaymentUpdated"]);
  for (const e of evs) assert.equal(check("ledger_event", e), null);
  const net = await app.inject({ method: "GET", url: "/v1/network" });
  assert.equal(check("network_info", net.json()), null);
  assert.equal((await app.inject({ method: "POST", url: "/v1/payments", payload: open(2) })).statusCode, 401);
});

test("L4: concurrent DEBIT and CREDIT never lose an attestation", async () => {
  const { app, ledger } = setup();
  for (let n = 10; n < 110; n++) {
    await app.inject({ method: "POST", url: "/v1/payments", headers: H, payload: open(n) });
    const url = `/v1/payments/${encodeURIComponent(ref(n))}/attest`;
    await Promise.all(["CREDIT", "DEBIT"].map((kind) =>
      app.inject({ method: "POST", url, headers: H, payload: { kind, simMs: 1 } })));
    const p = ledger.getPayment(ref(n));
    assert.equal(p.state, "SUCCESS", `payment ${n}`);
    // CREDIT first leaves DEBIT a no-op on SUCCESS; DEBIT first records both. Never a lost write.
    assert.ok(p.attestations.length >= 1 && p.attestations.some((a) => a.kind === "CREDIT"));
  }
});

test("L5: advisory issue / list / revoke; non-authority gets 403", async () => {
  const { app } = setup();
  const adv = { id: "adv-00001", kind: "DO_NOT_SHIFT", segmentId: "bank:*:B3", params: {}, reason: "shared bank",
    evidenceHash: "sha256:" + "b".repeat(64), decisionId: "dec-00001", issuedSimMs: 260000, validForSec: 600 };
  const r = await app.inject({ method: "POST", url: "/v1/advisories", headers: H, payload: adv });
  assert.equal(r.statusCode, 201, r.body);
  assert.equal(check("advisory", r.json().advisory), null);
  assert.equal((await app.inject({ method: "GET", url: "/v1/advisories?active=true" })).json().length, 1);
  const forbidden = await app.inject({ method: "POST", url: "/v1/advisories",
    headers: { ...H, "x-qs-as-msp": "Org2MSP" }, payload: { ...adv, id: "adv-00002" } });
  assert.equal(forbidden.statusCode, 403);
  const del = await app.inject({ method: "DELETE", url: "/v1/advisories/adv-00001", headers: H, payload: { reason: "done" } });
  assert.equal(del.statusCode, 200);
  assert.equal((await app.inject({ method: "GET", url: "/v1/advisories?active=true" })).json().length, 0);
});

test("L6: decision record is immutable", async () => {
  const { app } = setup();
  const dec = { id: "dec-00001", recId: "rec-0007", decision: "APPROVE_SELECTED", operator: "saran",
    actionsApproved: ["THROTTLE_RETRIES"], modelVersions: {}, featuresSha256: "0".repeat(64), decidedSimMs: 260000 };
  assert.equal((await app.inject({ method: "POST", url: "/v1/decisions", headers: H, payload: dec })).statusCode, 201);
  assert.equal((await app.inject({ method: "POST", url: "/v1/decisions", headers: H, payload: dec })).statusCode, 409);
  const g = await app.inject({ method: "GET", url: "/v1/decisions/dec-00001" });
  assert.equal(check("ledger_decision", g.json()), null);
});

test("L7 (mock part): Last-Event-ID replays only missed events", async () => {
  const { app, hub } = setup();
  for (const n of [1, 2, 3]) await app.inject({ method: "POST", url: "/v1/payments", headers: H, payload: open(n) });
  const all = hub.replay("0");
  assert.equal(all.length, 3);
  assert.equal(hub.replay("2").length, 1);
  assert.equal(hub.replay("3").length, 0);
});

test("L4/L7 (live adapter): MVCC retry with jitter + file checkpointer dedupes events across restarts", async () => {
  const fs = await import("node:fs");
  const cpPath = "/tmp/test_ledger_cp_" + Date.now() + ".json";
  let calls = 0;
  const transport = {
    async submit(_c: string, _fn: string, args: string[]) {
      calls += 1;
      if (calls <= 2) throw new Error("MVCC_READ_CONFLICT: simulated conflict");
      const rec = {
        docType: "payment",
        txnRef: args[0],
        idemKeyHash: args[1],
        payerPsp: args[2],
        remitterBank: args[3],
        beneficiaryBank: args[4],
        runId: args[5],
        state: "UNKNOWN",
        openedAt: 1700000000,
        openedSimMs: Number(args[6]),
        debitAt: null,
        creditAt: null,
        failureAt: null,
        reversalAt: null,
        reasonCode: null,
        debitImplied: false,
        tatSeconds: 20,
        tatDeadline: null,
        tatBreached: false,
        attestations: [],
        version: 1,
      };
      return {
        payload: JSON.stringify(rec),
        tx_id: "tx-live-0001",
        block_number: 42,
        event: {
          name: "PaymentUpdated",
          payload: {
            txnRef: rec.txnRef,
            state: "UNKNOWN",
            prevState: null,
            kind: "OPEN",
            runId: rec.runId,
            payerPsp: rec.payerPsp,
            remitterBank: rec.remitterBank,
            beneficiaryBank: rec.beneficiaryBank,
            simMs: rec.openedSimMs,
            debitImplied: false,
          },
        },
      };
    },
    async evaluate() {
      return "{}";
    },
  };
  const { app, hub } = buildApp({
    apiKey: KEY,
    mode: "live",
    transport,
    checkpointPath: cpPath,
    jitterMinMs: 1,
    jitterMaxMs: 2,
  });
  const o = await app.inject({ method: "POST", url: "/v1/payments", headers: H, payload: open(77) });
  assert.equal(o.statusCode, 201);
  const m = (await app.inject({ method: "GET", url: "/v1/metrics" })).json();
  assert.equal(m.mvcc_retries, 2);
  assert.equal(hub.replay("0").length, 1);

  // Restart gateway with same checkpoint file and re-ingest duplicate chaincode event -> deduped
  const { ledger: ledger2, hub: hub2 } = buildApp({
    apiKey: KEY,
    mode: "live",
    transport,
    checkpointPath: cpPath,
    jitterMinMs: 1,
    jitterMaxMs: 2,
  });
  if ("ingestChaincodeEvent" in ledger2) {
    ledger2.ingestChaincodeEvent("PaymentUpdated", {}, "tx-live-0001", 42, 10);
  }
  assert.equal(hub2.replay("0").length, 0);
  try {
    fs.unlinkSync(cpPath);
  } catch {}
});

