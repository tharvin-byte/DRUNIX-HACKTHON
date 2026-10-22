/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface ActionToApplyInTheSimulatorM4M2 {
  action_id: string;
  rec_id?: string | null;
  run_id: string;
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
  scope: {
    psp?: "P1" | "P2" | "P3";
    bank?: "B1" | "B2" | "B3" | "B4" | "B5";
  };
  params: {};
  effective_from_sim_ms: number;
  expires_sim_ms?: number | null;
  origin: "POLICY_DEFAULT" | "OPERATOR_APPROVED" | "ROLLBACK";
}
