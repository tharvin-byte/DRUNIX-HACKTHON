// Line-by-line port of chaincode/logic/transitions.go (docs/M1_LEDGER.md §6). Both are tested against
// m1_ledger/testdata/transitions.json; change them together or the golden-vector tests fail.

export type State = "UNKNOWN" | "DEBITED" | "SUCCESS" | "FAILED_NO_DEBIT" | "CREDIT_FAILED" | "REVERSED" | "DISPUTED";
export type Kind = "DEBIT" | "CREDIT" | "FAILURE_REMITTER" | "FAILURE_BENEFICIARY" | "REVERSAL";

export interface Attestation { mspId: string; kind: Kind; at: number; simMs: number; reasonCode: string | null }

export interface Payment {
  docType: "payment"; txnRef: string; idemKeyHash: string; payerPsp: string; remitterBank: string;
  beneficiaryBank: string; runId: string; state: State; openedAt: number; openedSimMs: number;
  debitAt: number | null; creditAt: number | null; failureAt: number | null; reversalAt: number | null;
  reasonCode: string | null; debitImplied: boolean; tatSeconds: number; tatDeadline: number | null;
  tatBreached: boolean; attestations: Attestation[]; version: number;
}

interface Rule { to: State; noop?: boolean; disputedReason?: string; setsTat?: boolean; debitImplied?: boolean; appendOnly?: boolean }

export const AUTHORITY_MSP = "Org1MSP";
export const REMITTER_MSP = "Org1MSP";
export const BENEFICIARY_MSP = "Org2MSP";

export const REQUIRED_MSP: Record<Kind, string> = {
  DEBIT: REMITTER_MSP, FAILURE_REMITTER: REMITTER_MSP,
  CREDIT: BENEFICIARY_MSP, FAILURE_BENEFICIARY: BENEFICIARY_MSP, REVERSAL: BENEFICIARY_MSP,
};

const d = (reason: string): Rule => ({ to: "DISPUTED", disputedReason: reason });
const noop = (s: State): Rule => ({ to: s, noop: true });
const append: Rule = { to: "DISPUTED", appendOnly: true };

export const TABLE: Record<State, Record<Kind, Rule>> = {
  UNKNOWN: {
    DEBIT: { to: "DEBITED", setsTat: true },
    CREDIT: { to: "SUCCESS", debitImplied: true },
    FAILURE_REMITTER: { to: "FAILED_NO_DEBIT" },
    FAILURE_BENEFICIARY: { to: "CREDIT_FAILED", debitImplied: true, setsTat: true },
    REVERSAL: { to: "REVERSED", debitImplied: true },
  },
  DEBITED: {
    DEBIT: noop("DEBITED"),
    CREDIT: { to: "SUCCESS" },
    FAILURE_REMITTER: d("debit then remitter failure"),
    FAILURE_BENEFICIARY: { to: "CREDIT_FAILED", setsTat: true },
    REVERSAL: { to: "REVERSED" },
  },
  CREDIT_FAILED: {
    DEBIT: noop("CREDIT_FAILED"),
    CREDIT: d("credit after credit failure"),
    FAILURE_REMITTER: d("remitter failure after credit failure"),
    FAILURE_BENEFICIARY: noop("CREDIT_FAILED"),
    REVERSAL: { to: "REVERSED" },
  },
  SUCCESS: {
    DEBIT: noop("SUCCESS"),
    CREDIT: noop("SUCCESS"),
    FAILURE_REMITTER: d("remitter failure after success"),
    FAILURE_BENEFICIARY: d("beneficiary failure after success"),
    REVERSAL: d("reversal after success"),
  },
  FAILED_NO_DEBIT: {
    DEBIT: d("debit after failure"),
    CREDIT: d("credit after failure"),
    FAILURE_REMITTER: noop("FAILED_NO_DEBIT"),
    FAILURE_BENEFICIARY: d("beneficiary failure after no-debit failure"),
    REVERSAL: d("reversal after no-debit failure"),
  },
  REVERSED: {
    DEBIT: d("debit after reversal"),
    CREDIT: d("credit after reversal"),
    FAILURE_REMITTER: d("remitter failure after reversal"),
    FAILURE_BENEFICIARY: noop("REVERSED"),
    REVERSAL: noop("REVERSED"),
  },
  DISPUTED: { DEBIT: append, CREDIT: append, FAILURE_REMITTER: append, FAILURE_BENEFICIARY: append, REVERSAL: append },
};

export class QsError extends Error {
  code: string;
  constructor(code: string, detail: string) {
    super(`QS_ERR_${code}: ${detail}`);
    this.code = code;
  }
}

export interface Result { payment: Payment; noop: boolean; event: "PaymentUpdated" | "TATBreach" | null; disputedReason: string }

export function apply(p: Payment, kind: Kind, mspId: string, txSeconds: number, simMs: number,
  reasonCode: string | null = null): Result {
  const need = REQUIRED_MSP[kind];
  if (!need) throw new QsError("BAD_ARG", `unknown kind ${kind}`);
  if (mspId !== need) throw new QsError("FORBIDDEN", `${mspId} may not attest ${kind}`);
  const r = TABLE[p.state]?.[kind];
  if (!r) throw new QsError("INTERNAL", `unknown state ${p.state}`);
  if (r.noop) return { payment: p, noop: true, event: null, disputedReason: "" };
  const next: Payment = { ...p, attestations: [...p.attestations, { mspId, kind, at: txSeconds, simMs, reasonCode }],
    version: p.version + 1 };
  if (r.appendOnly) return { payment: next, noop: false, event: null, disputedReason: "" };
  next.state = r.to;
  if (kind === "DEBIT") next.debitAt = txSeconds;
  else if (kind === "CREDIT") next.creditAt = txSeconds;
  else if (kind === "FAILURE_REMITTER" || kind === "FAILURE_BENEFICIARY") { next.failureAt = txSeconds; next.reasonCode = reasonCode; }
  else if (kind === "REVERSAL") next.reversalAt = txSeconds;
  if (r.debitImplied) next.debitImplied = true;
  if (r.setsTat) next.tatDeadline = txSeconds + p.tatSeconds;
  return { payment: next, noop: false, event: "PaymentUpdated", disputedReason: r.disputedReason ?? "" };
}

export function checkTat(p: Payment, txSeconds: number): Result {
  if ((p.state !== "DEBITED" && p.state !== "CREDIT_FAILED") || p.tatBreached || p.tatDeadline === null
    || txSeconds <= p.tatDeadline) return { payment: p, noop: true, event: null, disputedReason: "" };
  return { payment: { ...p, tatBreached: true, version: p.version + 1 }, noop: false, event: "TATBreach", disputedReason: "" };
}
