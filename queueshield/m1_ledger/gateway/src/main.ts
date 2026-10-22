// M1 gateway entry point. LEDGER_MODE=mock (default until live is implemented) | live.
//   QS_API_KEY=... LEDGER_MODE=mock node src/main.ts
import { config } from "./config.ts";
import { buildApp } from "./routes.ts";

const { app, ledger } = buildApp();
ledger.startTatSweeper();
app.listen({ port: config.port, host: "0.0.0.0" }).then(() => {
  process.stdout.write(JSON.stringify({ ts: new Date().toISOString(), module: "m1", level: "info",
    msg: "gateway listening", mode: config.mode, port: config.port }) + "\n");
});
