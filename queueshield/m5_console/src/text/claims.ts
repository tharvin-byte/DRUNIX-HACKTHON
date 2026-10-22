// Every user-visible sentence that states a result or describes the system (docs/M5_CONSOLE.md §1, U-8).
// Checked by tests/claims.test.ts against the forbidden list from docs/00_PRODUCT.md §8. Edit text here only.
export const FORBIDDEN = [
  "prevents outage", "prevent outage", "production-ready", "production ready", "npci-approved", "npci approved",
  "citi integration", "integrated with citi", "guarantee", "predicts outages", "real transaction data",
  "scales to upi", "nobody has done", "duplicate payments are impossible",
];
// Words that are allowed but need a second human reviewer (00_PRODUCT §8); the test lists them, it does not fail.
export const REVIEW_WORDS = ["production", "prevent", "savings", "approved", "real-time at upi scale"];

export const TEXT = {
  simulationLabel: "simulation",
  analogueLabel: "analogue",
  reasonsCaveat: "Supporting signals, not proof of cause",
  countdownCaveat: "rough estimate",
  forecastClaim: "Forecasts whether a degradation will lock in if nothing changes",
  contourLabel: "point of no return (p_stuck = 0.5)",
  ledgerOffline: "ledger offline",
  recordingOnLedger: "recording on ledger…",
  onsetUnknown: "onset unknown",
  splitReplayLabel: "replay of simulation runs",
  arenaLabel: "simulation, 5 seeds, preliminary",
  about: [
    "Real: a local Drunix test network running the queueshield chaincode (when the ledger badge says live).",
    "Simulated: all payment traffic, banks, PSPs and the switch; all data is synthetic.",
    "Follows the principle of NPCI's April 2025 circulars in a scaled analogue.",
    "Same design principle as Citi Token Services' pushed status notifications; this build has no connection to Citi systems.",
    "Every outcome number is from our simulator and is labelled simulation.",
  ],
} as const;
