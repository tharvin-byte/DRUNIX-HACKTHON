// JSON-Schema validation against contracts/schemas (draft 2020-12) (AGENTS.md rules 4-5).
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { config } from "./config.ts";

const require = createRequire(import.meta.url);
const Ajv2020 = require("ajv/dist/2020").default;
const addFormats = require("ajv-formats").default;

const ajv = new Ajv2020({ allErrors: false, strict: false });
addFormats(ajv);
const dir = path.join(config.contractsDir, "schemas");
for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".schema.json")).sort()) {
  ajv.addSchema(JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")));
}

export const metrics = { rejectedMessagesTotal: 0 };

/** null if valid, else the first error as text (counts toward rejected_messages_total). */
export function check(schema: string, obj: unknown): string | null {
  const v = ajv.getSchema(`https://queueshield.local/schemas/${schema}.schema.json`);
  if (!v) throw new Error(`unknown schema ${schema}`);
  if (v(obj)) return null;
  metrics.rejectedMessagesTotal += 1;
  const e = v.errors?.[0];
  return `${e?.instancePath || "<root>"} ${e?.message ?? "invalid"}`;
}
