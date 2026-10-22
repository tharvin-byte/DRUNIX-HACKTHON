// In-memory ledger with the chaincode's behaviour (docs/M1_LEDGER.md §6): same records, same errors, same event
// names; every event carries `mock: true`. Commit latency is lognormal (p50 120 ms, p95 400 ms) from a seeded
// generator; block numbers advance once per 50 ms window. Advisory expiry and TAT use wall-clock seconds like
// the chaincode's tx timestamp.
import crypto from "node:crypto";
import { config } from "../config.ts";
import type { SseHub } from "../sse.ts";
import { AUTHORITY_MSP, QsError, REMITTER_MSP, REQUIRED_MSP, apply, checkTat } from "./transitions.ts";
import type { Kind, Payment } from "./transitions.ts";

export interface Advisory {
  docType: "advisory"; id: string; kind: string; segmentId: string; params: Record<string, unknown>; reason: string;
  evidenceHash: string; decisionId: string; issuedSimMs: number; validForSec: number; issuedAt: number;
  expiresAt: number; revoked: boolean; revokedReason: string | null; issuerMspId: string;
}

export interface Decision {
  docType: "decision"; id: string; recId: string; decision: string; operator: string; actionsApproved: string[];
  modelVersions: Record<string, unknown>; featuresSha256: string; decidedSimMs: number; recordedAt: number;
  recorderMspId: string;
}

export interface TxResult<T> { record: T; tx_id: string; block_number: number; noop?: boolean }

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const nowSeconds = () => Math.floor(Date.now() / 1000);

export class MockLedger {
  payments = new Map<string, Payment>();
  advisories = new Map<string, Advisory>();
  decisions = new Map<string, Decision>();
  latencies: number[] = [];
  errorsByCode: Record<string, number> = {};
  private rng = mulberry32(config.mock.seed);
  private start = Date.now();
  private txCounter = 0;
  private locks = new Map<string, Promise<unknown>>();
  private hub: SseHub;
  private latencyScale: number;
  private tatTimer: NodeJS.Timeout | null = null;

  constructor(hub: SseHub, opts: { latencyScale?: number } = {}) {
    this.hub = hub;
    this.latencyScale = opts.latencyScale ?? 1;
  }

  startTatSweeper(): void {
    this.tatTimer = setInterval(() => this.sweepTat(), config.mock.tatSweepMs);
    this.tatTimer.unref();
  }

  stop(): void {
    if (this.tatTimer) clearInterval(this.tatTimer);
  }

  reset(): void {
    this.payments.clear();
    this.advisories.clear();
    this.decisions.clear();
  }

  height(): number {
    return Math.floor((Date.now() - this.start) / config.mock.blockWindowMs) + 1;
  }

  private commitDelayMs(): number {
    const mu = Math.log(config.mock.commitP50Ms);
    const sigma = Math.log(config.mock.commitP95Ms / config.mock.commitP50Ms) / 1.645;
    const u1 = Math.max(this.rng(), 1e-12), u2 = this.rng();
    const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    return Math.exp(mu + sigma * z) * this.latencyScale;
  }

  /** Serialise writes per key (gateway keyed mutex, §5.2) and simulate commit latency. */
  private async tx<T>(key: string, fn: () => T): Promise<{ value: T; tx_id: string; block_number: number }> {
    const prev = this.locks.get(key) ?? Promise.resolve();
    let release!: () => void;
    const mine = new Promise<void>((r) => (release = r));
    const chain = prev.then(() => mine);
    this.locks.set(key, chain);
    await prev;
    const t0 = Date.now();
    try {
      await new Promise((r) => setTimeout(r, this.commitDelayMs()));
      const value = fn();
      this.txCounter += 1;
      const tx_id = crypto.createHash("sha256").update(`${this.txCounter}:${key}`).digest("hex").slice(0, 16);
      this.latencies.push(Date.now() - t0);
      if (this.latencies.length > 10_000) this.latencies.shift();
      return { value, tx_id, block_number: this.height() };
    } catch (e) {
      const code = e instanceof QsError ? e.code : "INTERNAL";
      this.errorsByCode[code] = (this.errorsByCode[code] ?? 0) + 1;
      throw e;
    } finally {
      release();
      if (this.locks.get(key) === chain) this.locks.delete(key);
    }
  }

  private emit(name: string, payload: unknown, tx_id: string, block_number: number): void {
    this.hub.publish("ledger_event", {
      event_id: `${tx_id}:${name}`, block_number, tx_id, chaincode: "queueshield", name, payload,
      received_wall_iso: new Date().toISOString(), mock: true,
    });
  }

  private paymentEvent(p: Payment, prev: string | null, kind: string, simMs: number, disputedReason: string) {
    const ev: Record<string, unknown> = {
      txnRef: p.txnRef, state: p.state, prevState: prev, kind, runId: p.runId, payerPsp: p.payerPsp,
      remitterBank: p.remitterBank, beneficiaryBank: p.beneficiaryBank, simMs, debitImplied: p.debitImplied,
    };
    if (disputedReason) ev.disputedReason = disputedReason;
    return ev;
  }

  // ---------------------------------------------------------------- paystate
  async openUnknown(body: { txnRef: string; idemKeyHash: string; payerPsp: string; remitterBank: string;
    beneficiaryBank: string; runId: string; simMs: number }, mspId = REMITTER_MSP): Promise<TxResult<Payment> & { created: boolean }> {
    let created = false;
    const r = await this.tx(`PAY~${body.txnRef}`, () => {
      if (mspId !== REMITTER_MSP) throw new QsError("FORBIDDEN", `only ${REMITTER_MSP} opens unknown payments`);
      if (!body.txnRef.startsWith(`${body.runId}:`)) throw new QsError("BAD_ARG", "txnRef must be <runId>:<paymentId>");
      const ex = this.payments.get(body.txnRef);
      if (ex) {
        const same = ex.idemKeyHash === body.idemKeyHash && ex.payerPsp === body.payerPsp
          && ex.remitterBank === body.remitterBank && ex.beneficiaryBank === body.beneficiaryBank && ex.runId === body.runId;
        if (!same) throw new QsError("CONFLICT", `payment ${body.txnRef} exists with different fields`);
        return ex;
      }
      const p: Payment = {
        docType: "payment", txnRef: body.txnRef, idemKeyHash: body.idemKeyHash, payerPsp: body.payerPsp,
        remitterBank: body.remitterBank, beneficiaryBank: body.beneficiaryBank, runId: body.runId, state: "UNKNOWN",
        openedAt: nowSeconds(), openedSimMs: body.simMs, debitAt: null, creditAt: null, failureAt: null,
        reversalAt: null, reasonCode: null, debitImplied: false, tatSeconds: config.tatSeconds, tatDeadline: null,
        tatBreached: false, attestations: [], version: 1,
      };
      this.payments.set(p.txnRef, p);
      created = true;
      return p;
    });
    if (created) this.emit("PaymentUpdated", this.paymentEvent(r.value, null, "OPEN", body.simMs, ""), r.tx_id, r.block_number);
    return { record: r.value, tx_id: r.tx_id, block_number: r.block_number, created };
  }

  async attest(txnRef: string, kind: Kind, simMs: number, reasonCode: string | null, mspId?: string): Promise<TxResult<Payment>> {
    const msp = mspId ?? REQUIRED_MSP[kind];
    let prev = "", event: string | null = null, disputed = "", noop = false;
    const r = await this.tx(`PAY~${txnRef}`, () => {
      const p = this.payments.get(txnRef);
      if (!p) throw new QsError("NOT_FOUND", `payment ${txnRef}`);
      prev = p.state;
      const res = apply(p, kind, msp, nowSeconds(), simMs, reasonCode);
      noop = res.noop;
      event = res.event;
      disputed = res.disputedReason;
      if (!res.noop) this.payments.set(txnRef, res.payment);
      return res.payment;
    });
    if (event) this.emit(event, this.paymentEvent(r.value, prev, kind, simMs, disputed), r.tx_id, r.block_number);
    return { record: r.value, tx_id: r.tx_id, block_number: r.block_number, noop };
  }

  getPayment(txnRef: string): Payment {
    const p = this.payments.get(txnRef);
    if (!p) throw new QsError("NOT_FOUND", `payment ${txnRef}`);
    return p;
  }

  listPayments(runId?: string, state?: string, limit = 100): Payment[] {
    return [...this.payments.values()].filter((p) => (!runId || p.runId === runId) && (!state || p.state === state))
      .sort((a, b) => a.txnRef.localeCompare(b.txnRef)).slice(0, limit);
  }

  sweepTat(): void {
    const now = nowSeconds();
    for (const p of this.payments.values()) {
      const res = checkTat(p, now);
      if (res.noop) continue;
      void this.tx(`PAY~${p.txnRef}`, () => {
        const cur = this.payments.get(p.txnRef)!;
        const again = checkTat(cur, nowSeconds());          // re-check inside the "transaction"
        if (!again.noop) this.payments.set(cur.txnRef, again.payment);
        return again;
      }).then((r) => {
        if (!r.value.noop) {
          const q = r.value.payment;
          this.emit("TATBreach", { txnRef: q.txnRef, state: q.state, tatDeadline: q.tatDeadline, runId: q.runId,
            beneficiaryBank: q.beneficiaryBank }, r.tx_id, r.block_number);
        }
      });
    }
  }

  // ---------------------------------------------------------------- advisory
  async issueAdvisory(body: Omit<Advisory, "docType" | "issuedAt" | "expiresAt" | "revoked" | "revokedReason" | "issuerMspId">,
    mspId = AUTHORITY_MSP): Promise<TxResult<Advisory>> {
    const r = await this.tx(`ADV~${body.id}`, () => {
      if (mspId !== AUTHORITY_MSP) throw new QsError("FORBIDDEN", `only ${AUTHORITY_MSP} issues advisories`);
      if (this.advisories.has(body.id)) throw new QsError("CONFLICT", `advisory ${body.id} exists`);
      const now = nowSeconds();
      const a: Advisory = { docType: "advisory", ...body, issuedAt: now, expiresAt: now + body.validForSec, revoked: false,
        revokedReason: null, issuerMspId: mspId };
      this.advisories.set(a.id, a);
      return a;
    });
    this.emit("AdvisoryIssued", r.value, r.tx_id, r.block_number);
    return { record: r.value, tx_id: r.tx_id, block_number: r.block_number };
  }

  async revokeAdvisory(id: string, reason: string, mspId = AUTHORITY_MSP): Promise<TxResult<Advisory>> {
    const r = await this.tx(`ADV~${id}`, () => {
      if (mspId !== AUTHORITY_MSP) throw new QsError("FORBIDDEN", `only ${AUTHORITY_MSP} revokes advisories`);
      const a = this.advisories.get(id);
      if (!a) throw new QsError("NOT_FOUND", `advisory ${id}`);
      const next = { ...a, revoked: true, revokedReason: reason };
      this.advisories.set(id, next);
      return next;
    });
    this.emit("AdvisoryRevoked", { id, reason }, r.tx_id, r.block_number);
    return { record: r.value, tx_id: r.tx_id, block_number: r.block_number };
  }

  listAdvisories(activeOnly: boolean): Advisory[] {
    const now = nowSeconds();
    return [...this.advisories.values()].filter((a) => !activeOnly || (!a.revoked && a.expiresAt > now))
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  // ---------------------------------------------------------------- decisionlog
  async recordDecision(body: Omit<Decision, "docType" | "recordedAt" | "recorderMspId">, mspId = AUTHORITY_MSP): Promise<TxResult<Decision>> {
    const r = await this.tx(`DEC~${body.id}`, () => {
      if (mspId !== AUTHORITY_MSP) throw new QsError("FORBIDDEN", `only ${AUTHORITY_MSP} records decisions`);
      if (this.decisions.has(body.id)) throw new QsError("CONFLICT", `decision ${body.id} exists (append-only)`);
      const dec: Decision = { docType: "decision", ...body, recordedAt: nowSeconds(), recorderMspId: mspId };
      this.decisions.set(dec.id, dec);
      return dec;
    });
    this.emit("DecisionRecorded", r.value, r.tx_id, r.block_number);
    return { record: r.value, tx_id: r.tx_id, block_number: r.block_number };
  }

  getDecision(id: string): Decision {
    const d = this.decisions.get(id);
    if (!d) throw new QsError("NOT_FOUND", `decision ${id}`);
    return d;
  }
}
