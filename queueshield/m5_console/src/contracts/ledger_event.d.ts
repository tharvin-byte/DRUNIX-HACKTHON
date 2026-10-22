/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface LedgerEventOnGET8004V1StreamM1M2M4M5 {
  /**
   * <tx_id>:<name>
   */
  event_id: string;
  block_number: number;
  tx_id: string;
  chaincode: "queueshield";
  name: "PaymentUpdated" | "TATBreach" | "AdvisoryIssued" | "AdvisoryRevoked" | "DecisionRecorded";
  payload: {};
  received_wall_iso: string;
  mock?: boolean;
}
