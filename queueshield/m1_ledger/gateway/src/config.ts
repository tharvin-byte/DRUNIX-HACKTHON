// Gateway configuration (docs/M1_LEDGER.md §5, §6). All tunables here, frozen (AGENTS.md rule 16).
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export const config = Object.freeze({
  port: Number(process.env.PORT ?? 8004),
  mode: (process.env.LEDGER_MODE ?? "mock") as "live" | "mock",
  apiKey: process.env.QS_API_KEY ?? "",
  contractsDir: process.env.CONTRACTS_DIR ?? path.resolve(here, "../../../contracts"),
  dataDir: process.env.DATA_DIR ?? path.resolve(here, "../../../data"),
  channel: process.env.CHANNEL ?? "mychannel",
  chaincode: process.env.CHAINCODE ?? "queueshield",
  tatSeconds: Number(process.env.TAT_SECONDS ?? 120),
  sseRing: 50_000,
  heartbeatMs: 5_000,
  mock: Object.freeze({
    // simulated commit latency, lognormal (replace with data/ledger_bench.json once measured)
    commitP50Ms: 120,
    commitP95Ms: 400,
    blockWindowMs: 50,
    tatSweepMs: 1_000,
    seed: 42,
  }),
});
