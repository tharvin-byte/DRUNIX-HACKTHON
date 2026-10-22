/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface IncidentM3M4M5 {
  incident_id: string;
  run_id: string;
  segment_id: string;
  state: "OPEN" | "MITIGATING" | "RECOVERING" | "CLOSED";
  severity: "WARNING" | "CRITICAL";
  opened_sim_ms: number;
  updated_sim_ms: number;
  closed_sim_ms?: number | null;
  verdict:
    | "PSP_SIDE"
    | "BANK_SIDE"
    | "ROUTE_SPECIFIC"
    | "SWITCH_STATUS_OVERLOAD"
    | "MULTI_FAULT"
    | "PLATFORM_WIDE"
    | "INSUFFICIENT_EVIDENCE";
  p_stuck?: number | null;
  countdown_s_estimate?: number | null;
  reasons: Reason[];
  confidence: number;
  model_versions: ModelVersions;
  features_sha256: string;
}
export interface Reason {
  code:
    | "TIMEOUT_UP"
    | "NEAR_TIMEOUT_UP"
    | "LATENCY_UP"
    | "RAF_UP"
    | "QUEUE_GROWING"
    | "REJECTS_UP"
    | "PENDING_BACKLOG"
    | "SWITCH_STATUS_SATURATED"
    | "LEDGER_UNRESOLVED_UP";
  observed?: number;
  baseline?: number;
  z?: number;
}
export interface ModelVersions {
  detector?: string;
  forecaster?: string;
  localizer?: string;
  policy?: string;
}
