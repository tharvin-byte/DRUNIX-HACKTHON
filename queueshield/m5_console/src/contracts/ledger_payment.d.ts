/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface OnLedgerPaymentRecordChaincodePaystate {
  docType: "payment";
  txnRef: string;
  idemKeyHash: string;
  payerPsp: "P1" | "P2" | "P3";
  remitterBank: "B1" | "B2" | "B3" | "B4" | "B5";
  beneficiaryBank: "B1" | "B2" | "B3" | "B4" | "B5";
  runId: string;
  state: "UNKNOWN" | "DEBITED" | "SUCCESS" | "FAILED_NO_DEBIT" | "CREDIT_FAILED" | "REVERSED" | "DISPUTED";
  /**
   * unix seconds from tx timestamp
   */
  openedAt: number;
  openedSimMs: number;
  debitAt?: number | null;
  creditAt?: number | null;
  failureAt?: number | null;
  reversalAt?: number | null;
  reasonCode?: string | null;
  debitImplied: boolean;
  tatSeconds: number;
  tatDeadline?: number | null;
  tatBreached: boolean;
  attestations: {
    mspId: string;
    kind: "DEBIT" | "CREDIT" | "FAILURE_REMITTER" | "FAILURE_BENEFICIARY" | "REVERSAL";
    at: number;
    simMs: number;
    reasonCode?: string | null;
  }[];
  version: number;
}
