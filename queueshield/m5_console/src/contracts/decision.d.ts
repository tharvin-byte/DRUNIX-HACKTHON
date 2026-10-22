/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface OperatorDecisionM5M4 {
  rec_id: string;
  decision: "APPROVE_ALL" | "APPROVE_SELECTED" | "REJECT";
  operator: string;
  actions_selected: (
    | "THROTTLE_RETRIES"
    | "SHED_EXPIRED"
    | "PRIORITIZE_FRESH"
    | "SHIFT_TRAFFIC"
    | "CHECK_BUDGET"
    | "DEFER_CHECKS"
    | "PACE_PAYOUTS"
    | "HOLD_MONITOR"
    | "ESCALATE_HUMAN"
    | "ROLLBACK"
  )[];
  note?: string;
}
