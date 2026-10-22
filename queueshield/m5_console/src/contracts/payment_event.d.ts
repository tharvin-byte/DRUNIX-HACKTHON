/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export type PaymentEventM2M3M5NeverContainsAmountsAccountsVPAsOrNames = {
  [k: string]: unknown;
} & {
  schema_version: 1;
  /**
   * <run_id>-<8-digit counter>, unique, deterministic
   */
  event_id: string;
  run_id: string;
  universe: "U0" | "U1" | "U2" | "U3" | "U4";
  event_type:
    | "PAYMENT_INITIATED"
    | "ATTEMPT_SENT"
    | "ATTEMPT_OUTCOME"
    | "RETRY_SCHEDULED"
    | "STATUS_CHECK_SENT"
    | "STATUS_CHECK_RESULT"
    | "LEDGER_OPENED"
    | "LEDGER_RESOLVED"
    | "PSP_SNAPSHOT"
    | "SWITCH_SNAPSHOT"
    | "ACTION_APPLIED"
    | "PAYMENT_CLOSED";
  sim_ms: number;
  payment_id?: string;
  attempt_id?: string;
  attempt_no?: number;
  is_retry?: boolean;
  retry_count?: number;
  idempotency_key?: string;
  psp?: "P1" | "P2" | "P3";
  remitter_bank?: "B1" | "B2" | "B3" | "B4" | "B5";
  beneficiary_bank?: "B1" | "B2" | "B3" | "B4" | "B5";
  kind?: "P2P" | "P2M" | "PAYOUT";
  response_time_ms?: number;
  status?:
    | "SUCCESS"
    | "DECLINED"
    | "TECH_FAILED"
    | "REJECTED_OVERLOAD"
    | "RETRY_LATER"
    | "CLIENT_TIMEOUT"
    | "PENDING_UNKNOWN"
    | "CONFIRMED_SUCCESS"
    | "CONFIRMED_FAILED"
    | "UNKNOWN";
  error_code?: string;
  client_timeout_ms?: number;
  delay_ms?: number;
  queue_depth?: number;
  active_workers?: number;
  workers?: number;
  switch_status_queue?: number;
  switch_status_active?: number;
  switch_status_capacity_per_s?: number;
  switch_slowdown_factor?: number;
  check_no?: number;
  ledger_state?: "UNKNOWN" | "DEBITED" | "SUCCESS" | "FAILED_NO_DEBIT" | "CREDIT_FAILED" | "REVERSED" | "DISPUTED";
  action_id?: string;
  action_type?: string;
  params?: {};
  close_reason?: "CONFIRMED_SUCCESS" | "CONFIRMED_FAILED_FINAL" | "ABANDONED" | "ESCALATED_RECONCILE" | "DECLINED";
};
