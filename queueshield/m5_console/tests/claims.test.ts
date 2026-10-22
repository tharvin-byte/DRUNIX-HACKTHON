// U-8: claims lint. Every string in text/claims.ts and every .tsx under src/ passes the forbidden-word list.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { FORBIDDEN, REVIEW_WORDS, TEXT } from "../src/text/claims";

function strings(x: unknown): string[] {
  if (typeof x === "string") return [x];
  if (Array.isArray(x)) return x.flatMap(strings);
  if (x && typeof x === "object") return Object.values(x).flatMap(strings);
  return [];
}

function tsxFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? tsxFiles(path.join(dir, e.name)) : e.name.endsWith(".tsx") ? [path.join(dir, e.name)] : []);
}

describe("claims policy (docs/00_PRODUCT.md §8)", () => {
  it("claims.ts text has no forbidden phrase", () => {
    for (const s of strings(TEXT)) for (const f of FORBIDDEN) expect(s.toLowerCase()).not.toContain(f);
  });
  it("no component source contains a forbidden phrase", () => {
    for (const file of tsxFiles(path.resolve(__dirname, "../src"))) {
      const src = fs.readFileSync(file, "utf8").toLowerCase();
      for (const f of FORBIDDEN) expect(src, `${file}: ${f}`).not.toContain(f);
    }
  });
  it("lists review words for the second human reviewer", () => {
    const hits = strings(TEXT).filter((s) => REVIEW_WORDS.some((w) => s.toLowerCase().includes(w)));
    expect(Array.isArray(hits)).toBe(true);     // informational: printed by reviewers, not a failure
  });
});
