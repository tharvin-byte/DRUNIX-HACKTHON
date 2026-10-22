// Service URLs and demo constants (docs/M5_CONSOLE.md §1). Tunables live here, frozen.
export const config = Object.freeze({
  simUrl: import.meta.env.VITE_SIM_URL ?? "http://localhost:8001",
  detectUrl: import.meta.env.VITE_DETECT_URL ?? "http://localhost:8002",
  controlUrl: import.meta.env.VITE_CONTROL_URL ?? "http://localhost:8003",
  ledgerUrl: import.meta.env.VITE_LEDGER_URL ?? "http://localhost:8004",
  apiKey: import.meta.env.VITE_QS_API_KEY ?? "",
  statusPollMs: 1000,
  networkPollMs: 5000,
  staleAfterMs: 15000,
  backoffMinMs: 500,
  backoffMaxMs: 8000,
  ring: { ticks: 300, ledgerEvents: 500, recommendations: 200 },
  // ScenarioBar buttons -> fixed demo seeds (docs/M5_CONSOLE.md §3)
  scenarios: [
    { id: "S0", label: "Normal", seed: 1 },
    { id: "S1", label: "Festive surge", seed: 1 },
    { id: "S3", label: "Bank slowdown", seed: 1 },
    { id: "S4", label: "Retry storm", seed: 1 },
    { id: "S6", label: "April-2025 replay", seed: 1 },
    { id: "S8", label: "Payout burst", seed: 1 },
  ],
  operators: ["saran", "operator_one", "operator_two"],
});
