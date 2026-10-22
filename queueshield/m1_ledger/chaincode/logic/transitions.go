package logic

import "fmt"

// Rule is one cell of the payment state machine (docs/M1_LEDGER.md §4.3, testdata/transitions.json).
type Rule struct {
	To             string
	Noop           bool
	DisputedReason string
	SetsTat        bool
	DebitImplied   bool
	AppendOnly     bool // DISPUTED: append the attestation, bump version, emit no event
}

// RequiredMSP is the only organisation allowed to submit each attestation kind.
var RequiredMSP = map[string]string{
	KindDebit: RemitterMSP, KindFailureRemitter: RemitterMSP,
	KindCredit: BeneficiaryMSP, KindFailureBeneficiary: BeneficiaryMSP, KindReversal: BeneficiaryMSP,
}

func d(reason string) Rule { return Rule{To: Disputed, DisputedReason: reason} }

func noop(state string) Rule { return Rule{To: state, Noop: true} }

// Table is keyed by [from][kind]. Looked up, never iterated to build outputs (determinism checklist §4.5).
var Table = map[string]map[string]Rule{
	Unknown: {
		KindDebit:              {To: Debited, SetsTat: true},
		KindCredit:             {To: Success, DebitImplied: true},
		KindFailureRemitter:    {To: FailedNoDebit},
		KindFailureBeneficiary: {To: CreditFailed, DebitImplied: true, SetsTat: true},
		KindReversal:           {To: Reversed, DebitImplied: true},
	},
	Debited: {
		KindDebit:              noop(Debited),
		KindCredit:             {To: Success},
		KindFailureRemitter:    d("debit then remitter failure"),
		KindFailureBeneficiary: {To: CreditFailed, SetsTat: true},
		KindReversal:           {To: Reversed},
	},
	CreditFailed: {
		KindDebit:              noop(CreditFailed),
		KindCredit:             d("credit after credit failure"),
		KindFailureRemitter:    d("remitter failure after credit failure"),
		KindFailureBeneficiary: noop(CreditFailed),
		KindReversal:           {To: Reversed},
	},
	Success: {
		KindDebit:              noop(Success),
		KindCredit:             noop(Success),
		KindFailureRemitter:    d("remitter failure after success"),
		KindFailureBeneficiary: d("beneficiary failure after success"),
		KindReversal:           d("reversal after success"),
	},
	FailedNoDebit: {
		KindDebit:              d("debit after failure"),
		KindCredit:             d("credit after failure"),
		KindFailureRemitter:    noop(FailedNoDebit),
		KindFailureBeneficiary: d("beneficiary failure after no-debit failure"),
		KindReversal:           d("reversal after no-debit failure"),
	},
	Reversed: {
		KindDebit:              d("debit after reversal"),
		KindCredit:             d("credit after reversal"),
		KindFailureRemitter:    d("remitter failure after reversal"),
		KindFailureBeneficiary: noop(Reversed),
		KindReversal:           noop(Reversed),
	},
	Disputed: {
		KindDebit:              {To: Disputed, AppendOnly: true},
		KindCredit:             {To: Disputed, AppendOnly: true},
		KindFailureRemitter:    {To: Disputed, AppendOnly: true},
		KindFailureBeneficiary: {To: Disputed, AppendOnly: true},
		KindReversal:           {To: Disputed, AppendOnly: true},
	},
}

// Result of applying one attestation. DisputedReason is not part of the stored record (the schema has no
// such field); it travels in the PaymentUpdated event payload only.
type Result struct {
	Payment        *Payment
	Noop           bool
	Event          string // "PaymentUpdated", "TATBreach" or "" (no event)
	DisputedReason string
}

// Apply returns the next record (a copy) or an error "QS_ERR_<CODE>: ...". txSeconds comes from GetTxTimestamp.
func Apply(p *Payment, kind, mspID string, txSeconds, simMs int64, reasonCode *string) (Result, error) {
	need, ok := RequiredMSP[kind]
	if !ok {
		return Result{}, fmt.Errorf("QS_ERR_BAD_ARG: unknown kind %s", kind)
	}
	if mspID != need {
		return Result{}, fmt.Errorf("QS_ERR_FORBIDDEN: %s may not attest %s", mspID, kind)
	}
	row, ok := Table[p.State]
	if !ok {
		return Result{}, fmt.Errorf("QS_ERR_INTERNAL: unknown state %s", p.State)
	}
	r := row[kind]
	if r.Noop {
		return Result{Payment: p, Noop: true}, nil
	}
	next := *p
	next.Attestations = append(append([]Attestation{}, p.Attestations...),
		Attestation{MspID: mspID, Kind: kind, At: txSeconds, SimMs: simMs, ReasonCode: reasonCode})
	next.Version = p.Version + 1
	if r.AppendOnly {
		return Result{Payment: &next}, nil
	}
	next.State = r.To
	t := txSeconds
	switch kind {
	case KindDebit:
		next.DebitAt = &t
	case KindCredit:
		next.CreditAt = &t
	case KindFailureRemitter, KindFailureBeneficiary:
		next.FailureAt = &t
		next.ReasonCode = reasonCode
	case KindReversal:
		next.ReversalAt = &t
	}
	if r.DebitImplied {
		next.DebitImplied = true
	}
	if r.SetsTat {
		deadline := t + p.TatSeconds
		next.TatDeadline = &deadline
	}
	return Result{Payment: &next, Event: "PaymentUpdated", DisputedReason: r.DisputedReason}, nil
}

// CheckTAT marks a breach once if the payment is debited but neither credited nor reversed past its deadline.
func CheckTAT(p *Payment, txSeconds int64) (Result, error) {
	if (p.State != Debited && p.State != CreditFailed) || p.TatBreached || p.TatDeadline == nil || txSeconds <= *p.TatDeadline {
		return Result{Payment: p, Noop: true}, nil
	}
	next := *p
	next.TatBreached = true
	next.Version = p.Version + 1
	return Result{Payment: &next, Event: "TATBreach"}, nil
}
