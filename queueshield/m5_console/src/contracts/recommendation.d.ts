/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface RecommendationPackageM4M5 {
  rec_id: string;
  incident_id: string;
  run_id: string;
  created_sim_ms: number;
  segment_id: string;
  severity: "WARNING" | "CRITICAL";
  verdict:
    | "PSP_SIDE"
    | "BANK_SIDE"
    | "ROUTE_SPECIFIC"
    | "SWITCH_STATUS_OVERLOAD"
    | "MULTI_FAULT"
    | "PLATFORM_WIDE"
    | "INSUFFICIENT_EVIDENCE";
  p_stuck?: number | null;
  confidence: number;
  countdown_s_estimate?: number | null;
  /**
   * @minItems 1
   */
  actions: [
    {
      action_type:
        | "THROTTLE_RETRIES"
        | "SHED_EXPIRED"
        | "PRIORITIZE_FRESH"
        | "SHIFT_TRAFFIC"
        | "CHECK_BUDGET"
        | "DEFER_CHECKS"
        | "PACE_PAYOUTS"
        | "HOLD_MONITOR"
        | "ESCALATE_HUMAN"
        | "ROLLBACK";
      params: {};
      scope_segment_id: string;
      eligible: boolean;
      blocked_by?: string | null;
      advisory_kind?: "SLOW_RETRIES" | "DEFER_CHECKS" | "DO_NOT_SHIFT" | "PACE_PAYOUTS" | null;
      side_effect: string;
      rollback_condition: string;
    },
    ...{
      action_type:
        | "THROTTLE_RETRIES"
        | "SHED_EXPIRED"
        | "PRIORITIZE_FRESH"
        | "SHIFT_TRAFFIC"
        | "CHECK_BUDGET"
        | "DEFER_CHECKS"
        | "PACE_PAYOUTS"
        | "HOLD_MONITOR"
        | "ESCALATE_HUMAN"
        | "ROLLBACK";
      params: {};
      scope_segment_id: string;
      eligible: boolean;
      blocked_by?: string | null;
      advisory_kind?: "SLOW_RETRIES" | "DEFER_CHECKS" | "DO_NOT_SHIFT" | "PACE_PAYOUTS" | null;
      side_effect: string;
      rollback_condition: string;
    }[]
  ];
  reasons: Reason[];
  status: "PENDING" | "APPROVED" | "PARTIAL" | "REJECTED" | "EXPIRED" | "SUPERSEDED";
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
