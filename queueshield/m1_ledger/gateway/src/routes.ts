// REST + SSE routes per contracts/CONTRACTS.md §4 (M1 gateway, :8004). Mock and live share these routes;
// only the ledger implementation differs. Chaincode error codes map to HTTP 400/403/404/409/500.
import crypto from "node:crypto";
import Fastify from "fastify";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { config } from "./config.ts";
import { MockLedger } from "./mock/ledger.ts";
import { QsError } from "./mock/transitions.ts";
import type { Kind } from "./mock/transitions.ts";
import { SseHub } from "./sse.ts";
import { check, metrics } from "./validate.ts";

const HTTP: Record<string, [number, string]> = {
  BAD_ARG: [400, "BAD_REQUEST"], FORBIDDEN: [403, "LEDGER_ERROR"], NOT_FOUND: [404, "NOT_FOUND"],
  CONFLICT: [409, "CONFLICT"], INTERNAL: [500, "INTERNAL"],
};

function fail(reply: FastifyReply, status: number, error: string, detail: string) {
  return reply.code(status).send({ error, detail });
}

function pct(xs: number[], q: number): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

export interface AppOptions { apiKey?: string; latencyScale?: number; mode?: "mock" | "live" }

export function buildApp(opts: AppOptions = {}): { app: FastifyInstance; ledger: MockLedger; hub: SseHub } {
  const mode = opts.mode ?? config.mode;
  if (mode === "live") {
    // TODO(M1, Day 2-3): live Fabric/Drunix implementation (src/live/). Until then refuse to fake a ledger.
    throw new Error("LEDGER_MODE=live is not implemented yet (see m1_ledger/STATUS.md); use LEDGER_MODE=mock");
  }
  const apiKey = opts.apiKey ?? config.apiKey;
  const hub = new SseHub();
  const ledger = new MockLedger(hub, { latencyScale: opts.latencyScale });
  const app = Fastify({ logger: false, bodyLimit: 1_000_000 });

  const writeGuard = async (req: FastifyRequest, reply: FastifyReply) => {
    const key = req.headers["x-qs-key"];
    const ok = typeof key === "string" && apiKey.length > 0 && key.length === apiKey.length
      && crypto.timingSafeEqual(Buffer.from(key), Buffer.from(apiKey));
    if (!ok) return fail(reply, 401, "UNAUTHORIZED", "missing or wrong X-QS-Key");
  };
  // Mock only: lets tests act as another organisation (L5 403 path). The live gateway picks identities itself.
  const asMsp = (req: FastifyRequest): string | undefined => {
    const h = req.headers["x-qs-as-msp"];
    return typeof h === "string" ? h : undefined;
  };
  const run = async (reply: FastifyReply, fn: () => Promise<unknown> | unknown, status = 200) => {
    try {
      return reply.code(status).send(await fn());
    } catch (e) {
      if (e instanceof QsError) {
        const [code, err] = HTTP[e.code] ?? [500, "INTERNAL"];
        return fail(reply, code, err, e.message);
      }
      return fail(reply, 500, "INTERNAL", (e as Error).message);
    }
  };

  app.get("/v1/health", async () => ({ status: "ok", module: "m1", mode, version: process.env.GIT_SHA ?? "dev",
    peers_reachable: {}, rejected_messages_total: metrics.rejectedMessagesTotal }));

  app.get("/v1/network", async () => {
    const lat = ledger.latencies;
    return {
      mode, channel: config.channel, chaincode: { name: config.chaincode, version: "mock", sequence: 1 },
      height: ledger.height(),
      orgs: [
        { mspId: "Org1MSP", role: "PAYER_SIDE_AND_AUTHORITY", litePeers: ["peer0.org1.example.com"],
          committingPeers: ["peer1.org1.example.com"], validationServices: ["vs1.org1"], stateDb: "yugabyte-org1",
          transientStore: "hlf_keydb_org1msp" },
        { mspId: "Org2MSP", role: "PAYEE_SIDE", litePeers: ["peer0.org2.example.com"],
          committingPeers: ["peer1.org2.example.com"], validationServices: ["vs1.org2"], stateDb: "yugabyte-org2",
          transientStore: "hlf_keydb_org2msp" },
      ],
      orderers: ["orderer.example.com"],
      submitLatencyMs: { p50: pct(lat, 0.5), p95: pct(lat, 0.95), p99: pct(lat, 0.99) },
      updated_wall_iso: new Date().toISOString(),
    };
  });

  app.post("/v1/payments", { preHandler: writeGuard }, async (req, reply) => {
    const err = check("ledger_open_request", req.body);
    if (err) return fail(reply, 400, "SCHEMA_INVALID", err);
    try {
      const r = await ledger.openUnknown(req.body as never, asMsp(req));
      return reply.code(r.created ? 201 : 200).send({ record: r.record, tx_id: r.tx_id, block_number: r.block_number });
    } catch (e) {
      return run(reply, () => { throw e; });
    }
  });

  app.post<{ Params: { txnRef: string } }>("/v1/payments/:txnRef/attest", { preHandler: writeGuard }, async (req, reply) => {
    const err = check("ledger_attest_request", req.body);
    if (err) return fail(reply, 400, "SCHEMA_INVALID", err);
    const b = req.body as { kind: Kind; simMs: number; reasonCode?: string | null };
    return run(reply, () => ledger.attest(req.params.txnRef, b.kind, b.simMs, b.reasonCode ?? null, asMsp(req)));
  });

  app.get<{ Params: { txnRef: string } }>("/v1/payments/:txnRef", async (req, reply) =>
    run(reply, () => ledger.getPayment(req.params.txnRef)));

  app.get<{ Querystring: { run_id?: string; state?: string; limit?: string } }>("/v1/payments", async (req) =>
    ledger.listPayments(req.query.run_id, req.query.state, req.query.limit ? Number(req.query.limit) : 100));

  app.post("/v1/advisories", { preHandler: writeGuard }, async (req, reply) => {
    const err = check("advisory", req.body);
    if (err) return fail(reply, 400, "SCHEMA_INVALID", err);
    const r = await ledger.issueAdvisory(req.body as never, asMsp(req)).catch((e) => e);
    if (r instanceof Error) return run(reply, () => { throw r; });
    return reply.code(201).send({ advisory: r.record, tx_id: r.tx_id });
  });

  app.delete<{ Params: { id: string } }>("/v1/advisories/:id", { preHandler: writeGuard }, async (req, reply) => {
    const reason = (req.body as { reason?: string } | undefined)?.reason ?? "";
    return run(reply, async () => {
      const r = await ledger.revokeAdvisory(req.params.id, reason, asMsp(req));
      return { advisory: r.record, tx_id: r.tx_id };
    });
  });

  app.get<{ Querystring: { active?: string } }>("/v1/advisories", async (req) =>
    ledger.listAdvisories(req.query.active === "true"));

  app.post("/v1/decisions", { preHandler: writeGuard }, async (req, reply) => {
    const err = check("ledger_decision", req.body);
    if (err) return fail(reply, 400, "SCHEMA_INVALID", err);
    const r = await ledger.recordDecision(req.body as never, asMsp(req)).catch((e) => e);
    if (r instanceof Error) return run(reply, () => { throw r; });
    return reply.code(201).send({ decision: r.record, tx_id: r.tx_id });
  });

  app.get<{ Params: { id: string } }>("/v1/decisions/:id", async (req, reply) =>
    run(reply, () => ledger.getDecision(req.params.id)));

  app.get("/v1/stream", (req, reply) => {
    reply.hijack();
    const last = req.headers["last-event-id"];
    hub.attach(reply.raw, typeof last === "string" ? last : undefined);
  });

  app.get("/v1/metrics", async () => {
    const lat = ledger.latencies;
    return { submit_ms: { p50: pct(lat, 0.5), p95: pct(lat, 0.95), p99: pct(lat, 0.99), n: lat.length },
      evaluate_ms: { p50: 0, p95: 0, p99: 0, n: 0 }, mvcc_retries: 0, errors_by_code: ledger.errorsByCode,
      rejected_messages_total: metrics.rejectedMessagesTotal };
  });

  app.post("/v1/admin/reset", { preHandler: writeGuard }, async () => {
    ledger.reset();
    return { status: "reset" };
  });

  return { app, ledger, hub };
}
