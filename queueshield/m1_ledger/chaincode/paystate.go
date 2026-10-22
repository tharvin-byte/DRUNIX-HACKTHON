package main

// paystate: unknown payments, bank attestations and TAT (docs/M1_LEDGER.md §4.4).
// NOT YET COMPILED: Go is not installed on the dev machine; see m1_ledger/STATUS.md.

import (
	"encoding/json"

	"regexp"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"

	"queueshield/m1_ledger/chaincode/logic"
)

type PayState struct {
	contractapi.Contract
}

var (
	reTxnRef = regexp.MustCompile(`^r-S[0-8]-[0-9]+-U[0-4](-[a-z0-9]+)?:p-[0-9]{7}$`)
	reRunID  = regexp.MustCompile(`^r-S[0-8]-[0-9]+-U[0-4](-[a-z0-9]+)?$`)
	reIdem   = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	rePsp    = regexp.MustCompile(`^P[1-3]$`)
	reBank   = regexp.MustCompile(`^B[1-5]$`)
)

func payKey(txnRef string) string { return "PAY~" + txnRef }

func (c *PayState) OpenUnknown(ctx contractapi.TransactionContextInterface, txnRef, idemKeyHash, payerPsp,
	remitterBank, beneficiaryBank, runID string, simMs int64, tatSeconds int64) (*logic.Payment, error) {
	msp, err := callerMSP(ctx)
	if err != nil {
		return nil, err
	}
	if msp != logic.RemitterMSP {
		return nil, errForbidden("only %s opens unknown payments", logic.RemitterMSP)
	}
	if !reTxnRef.MatchString(txnRef) || !reIdem.MatchString(idemKeyHash) || !rePsp.MatchString(payerPsp) ||
		!reBank.MatchString(remitterBank) || !reBank.MatchString(beneficiaryBank) || !reRunID.MatchString(runID) {
		return nil, errBadArg("invalid argument format")
	}
	if tatSeconds < 10 || tatSeconds > 86400 || simMs < 0 {
		return nil, errBadArg("tatSeconds must be in [10, 86400]")
	}
	existing, err := getPayment(ctx, txnRef)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		if existing.IdemKeyHash == idemKeyHash && existing.PayerPsp == payerPsp && existing.RemitterBank == remitterBank &&
			existing.BeneficiaryBank == beneficiaryBank && existing.RunID == runID {
			return existing, nil // idempotent: identical open, no write
		}
		return nil, errConflict("payment %s exists with different fields", txnRef)
	}
	now, err := txSeconds(ctx)
	if err != nil {
		return nil, err
	}
	p := &logic.Payment{DocType: "payment", TxnRef: txnRef, IdemKeyHash: idemKeyHash, PayerPsp: payerPsp,
		RemitterBank: remitterBank, BeneficiaryBank: beneficiaryBank, RunID: runID, State: logic.Unknown,
		OpenedAt: now, OpenedSimMs: simMs, TatSeconds: tatSeconds, Attestations: []logic.Attestation{}, Version: 1}
	if err := putPayment(ctx, p); err != nil {
		return nil, err
	}
	return p, emitPayment(ctx, p, nil, "OPEN", simMs, "")
}

func (c *PayState) attest(ctx contractapi.TransactionContextInterface, txnRef, kind string, simMs int64,
	reasonCode *string) (*logic.Payment, error) {
	msp, err := callerMSP(ctx)
	if err != nil {
		return nil, err
	}
	p, err := getPayment(ctx, txnRef)
	if err != nil {
		return nil, err
	}
	if p == nil {
		return nil, errNotFound("payment %s", txnRef)
	}
	now, err := txSeconds(ctx)
	if err != nil {
		return nil, err
	}
	res, err := logic.Apply(p, kind, msp, now, simMs, reasonCode)
	if err != nil {
		return nil, err
	}
	if res.Noop {
		return res.Payment, nil // no write, no event; the gateway reports noop=true
	}
	if err := putPayment(ctx, res.Payment); err != nil {
		return nil, err
	}
	if res.Event == "" {
		return res.Payment, nil // DISPUTED append-only
	}
	prev := p.State
	return res.Payment, emitPayment(ctx, res.Payment, &prev, kind, simMs, res.DisputedReason)
}

func (c *PayState) AttestDebit(ctx contractapi.TransactionContextInterface, txnRef string, simMs int64) (*logic.Payment, error) {
	return c.attest(ctx, txnRef, logic.KindDebit, simMs, nil)
}

func (c *PayState) AttestCredit(ctx contractapi.TransactionContextInterface, txnRef string, simMs int64) (*logic.Payment, error) {
	return c.attest(ctx, txnRef, logic.KindCredit, simMs, nil)
}

func (c *PayState) AttestFailure(ctx contractapi.TransactionContextInterface, txnRef, leg, reasonCode string, simMs int64) (*logic.Payment, error) {
	kind := map[string]string{"REMITTER": logic.KindFailureRemitter, "BENEFICIARY": logic.KindFailureBeneficiary}[leg]
	if kind == "" {
		return nil, errBadArg("leg must be REMITTER or BENEFICIARY")
	}
	return c.attest(ctx, txnRef, kind, simMs, &reasonCode)
}

func (c *PayState) AttestReversal(ctx contractapi.TransactionContextInterface, txnRef string, simMs int64) (*logic.Payment, error) {
	return c.attest(ctx, txnRef, logic.KindReversal, simMs, nil)
}

func (c *PayState) GetStatus(ctx contractapi.TransactionContextInterface, txnRef string) (*logic.Payment, error) {
	p, err := getPayment(ctx, txnRef)
	if err != nil {
		return nil, err
	}
	if p == nil {
		return nil, errNotFound("payment %s", txnRef)
	}
	return p, nil
}

func (c *PayState) CheckTAT(ctx contractapi.TransactionContextInterface, txnRef string) (*logic.Payment, error) {
	p, err := c.GetStatus(ctx, txnRef)
	if err != nil {
		return nil, err
	}
	now, err := txSeconds(ctx)
	if err != nil {
		return nil, err
	}
	res, _ := logic.CheckTAT(p, now)
	if res.Noop {
		return p, nil
	}
	if err := putPayment(ctx, res.Payment); err != nil {
		return nil, err
	}
	ev := struct {
		TxnRef          string `json:"txnRef"`
		State           string `json:"state"`
		TatDeadline     *int64 `json:"tatDeadline"`
		RunID           string `json:"runId"`
		BeneficiaryBank string `json:"beneficiaryBank"`
	}{p.TxnRef, res.Payment.State, p.TatDeadline, p.RunID, p.BeneficiaryBank}
	return res.Payment, setEvent(ctx, "TATBreach", ev)
}

// ---------------------------------------------------------------- helpers

func getPayment(ctx contractapi.TransactionContextInterface, txnRef string) (*logic.Payment, error) {
	raw, err := ctx.GetStub().GetState(payKey(txnRef))
	if err != nil {
		return nil, errInternal("get state")
	}
	if raw == nil {
		return nil, nil
	}
	var p logic.Payment
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, errInternal("decode payment")
	}
	return &p, nil
}

func putPayment(ctx contractapi.TransactionContextInterface, p *logic.Payment) error {
	raw, err := json.Marshal(p)
	if err != nil {
		return errInternal("encode payment")
	}
	return ctx.GetStub().PutState(payKey(p.TxnRef), raw)
}

// emitPayment sets the single PaymentUpdated event of this transaction (CONTRACTS §5).
func emitPayment(ctx contractapi.TransactionContextInterface, p *logic.Payment, prev *string, kind string,
	simMs int64, disputedReason string) error {
	ev := struct {
		TxnRef          string  `json:"txnRef"`
		State           string  `json:"state"`
		PrevState       *string `json:"prevState"`
		Kind            string  `json:"kind"`
		RunID           string  `json:"runId"`
		PayerPsp        string  `json:"payerPsp"`
		RemitterBank    string  `json:"remitterBank"`
		BeneficiaryBank string  `json:"beneficiaryBank"`
		SimMs           int64   `json:"simMs"`
		DebitImplied    bool    `json:"debitImplied"`
		DisputedReason  string  `json:"disputedReason,omitempty"`
	}{p.TxnRef, p.State, prev, kind, p.RunID, p.PayerPsp, p.RemitterBank, p.BeneficiaryBank, simMs, p.DebitImplied, disputedReason}
	return setEvent(ctx, "PaymentUpdated", ev)
}

func setEvent(ctx contractapi.TransactionContextInterface, name string, payload interface{}) error {
	raw, err := json.Marshal(payload)
	if err != nil {
		return errInternal("encode event")
	}
	return ctx.GetStub().SetEvent(name, raw)
}

func callerMSP(ctx contractapi.TransactionContextInterface) (string, error) {
	id, err := ctx.GetClientIdentity().GetMSPID()
	if err != nil {
		return "", errInternal("client identity")
	}
	return id, nil
}

func txSeconds(ctx contractapi.TransactionContextInterface) (int64, error) {
	ts, err := ctx.GetStub().GetTxTimestamp() // never time.Now() (determinism checklist §4.5)
	if err != nil {
		return 0, errInternal("tx timestamp")
	}
	return ts.GetSeconds(), nil
}
