/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export type SimulatorControlM5M2 = {
  [k: string]: unknown;
} & {
  command: "START" | "PAUSE" | "RESUME" | "RESET" | "SPEED";
  scenario?: "S0" | "S1" | "S2" | "S3" | "S4" | "S5" | "S6" | "S7" | "S8";
  seed?: number;
  universe?: "U0" | "U1" | "U2" | "U3" | "U4";
  speed?: 1 | 2 | 4;
  overrides?: {};
};
