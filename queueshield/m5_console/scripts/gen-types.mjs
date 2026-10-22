// Generate TypeScript types from contracts/schemas (docs/M5_CONSOLE.md §12: never hand-write a message type).
//   npm run gen:types   -> src/contracts/<name>.d.ts
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const schemas = path.resolve(here, "../../contracts/schemas");
const out = path.resolve(here, "../src/contracts");
fs.mkdirSync(out, { recursive: true });

const byId = {};
for (const f of fs.readdirSync(schemas).filter((x) => x.endsWith(".schema.json"))) {
  const s = JSON.parse(fs.readFileSync(path.join(schemas, f), "utf8"));
  byId[s.$id] = s;
}
const resolver = {
  order: 1,
  canRead: /^https:\/\/queueshield\.local\//,
  read: (file) => JSON.stringify(byId[file.url.split("#")[0]]),
};

const names = ["payment_event", "segment_state", "incident", "recommendation", "decision", "action", "advisory",
  "ledger_event", "ledger_payment", "ledger_decision", "network_info", "run_result", "scenario_command"];
const index = [];
for (const name of names) {
  const schema = byId[`https://queueshield.local/schemas/${name}.schema.json`];
  const ts = await compile(schema, name, {
    cwd: schemas, bannerComment: "/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */",
    $refOptions: { resolve: { http: resolver } }, additionalProperties: false, strictIndexSignatures: false,
  });
  fs.writeFileSync(path.join(out, `${name}.d.ts`), ts);
  // re-export only the top-level type under a friendly name (sub-types such as Reason repeat across files)
  const top = ts.match(/export (?:interface|type) (\w+)/)[1];
  const friendly = name.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join("");
  index.push(`export type { ${top} as ${friendly} } from "./${name}";`);
}
fs.writeFileSync(path.join(out, "index.d.ts"), index.join("\n") + "\n");
console.log(`generated ${names.length} type files in src/contracts/`);
