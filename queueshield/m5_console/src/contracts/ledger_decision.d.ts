/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface DecisionRecordM4M1 {
  docType?: "decision";
  id: string;
  recId: string;
  decision: "APPROVE_ALL" | "APPROVE_SELECTED" | "REJECT";
  operator: string;
  actionsApproved: string[];
  modelVersions: {};
  featuresSha256: string;
  decidedSimMs: number;
  recordedAt?: number;
  recorderMspId?: string;
}
