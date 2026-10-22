/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface AdvisoryM4M1ReadByM2AndM5 {
  docType?: "advisory";
  id: string;
  kind: "SLOW_RETRIES" | "DEFER_CHECKS" | "DO_NOT_SHIFT" | "PACE_PAYOUTS";
  segmentId: string;
  params: {};
  reason: string;
  evidenceHash: string;
  decisionId: string;
  issuedSimMs: number;
  validForSec: number;
  issuedAt?: number;
  expiresAt?: number;
  revoked?: boolean;
  revokedReason?: string | null;
  issuerMspId?: string;
}
