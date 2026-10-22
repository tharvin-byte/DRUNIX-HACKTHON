package main

// advisory + decisionlog contracts (docs/M1_LEDGER.md §4.4). NOT YET COMPILED (no Go on the dev machine).

import (
	"encoding/json"
	"regexp"
	"sort"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"

	"queueshield/m1_ledger/chaincode/logic"
)

type Advisory struct {
	contractapi.Contract
}

type DecisionLog struct {
	contractapi.Contract
}

var (
	reAdvID    = regexp.MustCompile(`^adv-[0-9]{5}$`)
	reDecID    = regexp.MustCompile(`^dec-[0-9]{5}$`)
	reSegment  = regexp.MustCompile(`^(platform|psp|bank|route|switch):(P[1-3]|\*):(B[1-5]|\*)$`)
	reEvidence = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	advKinds   = map[string]bool{"SLOW_RETRIES": true, "DEFER_CHECKS": true, "DO_NOT_SHIFT": true, "PACE_PAYOUTS": true}
)

func (c *Advisory) IssueAdvisory(ctx contractapi.TransactionContextInterface, advisoryJSON string) (*logic.Advisory, error) {
	if err := requireAuthority(ctx); err != nil {
		return nil, err
	}
	var a logic.Advisory
	if err := json.Unmarshal([]byte(advisoryJSON), &a); err != nil {
		return nil, errBadArg("advisory JSON")
	}
	if !reAdvID.MatchString(a.ID) || !advKinds[a.Kind] || !reSegment.MatchString(a.SegmentID) ||
		!reEvidence.MatchString(a.EvidenceHash) || a.ValidForSec < 5 || a.ValidForSec > 3600 || len(a.Reason) > 200 ||
		a.DecisionID == "" {
		return nil, errBadArg("invalid advisory")
	}
	key := "ADV~" + a.ID
	if raw, err := ctx.GetStub().GetState(key); err != nil || raw != nil {
		return nil, errConflict("advisory %s exists", a.ID)
	}
	now, err := txSeconds(ctx)
	if err != nil {
		return nil, err
	}
	msp, _ := callerMSP(ctx)
	a.DocType, a.IssuedAt, a.ExpiresAt, a.Revoked, a.RevokedReason, a.IssuerMspID = "advisory", now, now+a.ValidForSec, false, nil, msp
	raw, _ := json.Marshal(a)
	if err := ctx.GetStub().PutState(key, raw); err != nil {
		return nil, errInternal("put advisory")
	}
	return &a, setEvent(ctx, "AdvisoryIssued", a)
}

func (c *Advisory) RevokeAdvisory(ctx contractapi.TransactionContextInterface, id, reason string) (*logic.Advisory, error) {
	if err := requireAuthority(ctx); err != nil {
		return nil, err
	}
	a, err := c.GetAdvisory(ctx, id)
	if err != nil {
		return nil, err
	}
	a.Revoked, a.RevokedReason = true, &reason
	raw, _ := json.Marshal(a)
	if err := ctx.GetStub().PutState("ADV~"+id, raw); err != nil {
		return nil, errInternal("put advisory")
	}
	ev := struct {
		ID     string `json:"id"`
		Reason string `json:"reason"`
	}{id, reason}
	return a, setEvent(ctx, "AdvisoryRevoked", ev)
}

func (c *Advisory) GetAdvisory(ctx contractapi.TransactionContextInterface, id string) (*logic.Advisory, error) {
	raw, err := ctx.GetStub().GetState("ADV~" + id)
	if err != nil {
		return nil, errInternal("get advisory")
	}
	if raw == nil {
		return nil, errNotFound("advisory %s", id)
	}
	var a logic.Advisory
	if err := json.Unmarshal(raw, &a); err != nil {
		return nil, errInternal("decode advisory")
	}
	return &a, nil
}

// ListActive uses a range query [VERIFY on the YugabyteDB state DB] and sorts by id for determinism.
func (c *Advisory) ListActive(ctx contractapi.TransactionContextInterface) ([]*logic.Advisory, error) {
	it, err := ctx.GetStub().GetStateByRange("ADV~", "ADV~￿")
	if err != nil {
		return nil, errInternal("range query")
	}
	defer it.Close()
	now, err := txSeconds(ctx)
	if err != nil {
		return nil, err
	}
	out := []*logic.Advisory{}
	for it.HasNext() {
		kv, err := it.Next()
		if err != nil {
			return nil, errInternal("range next")
		}
		var a logic.Advisory
		if json.Unmarshal(kv.Value, &a) == nil && !a.Revoked && a.ExpiresAt > now {
			out = append(out, &a)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

func (c *DecisionLog) RecordDecision(ctx contractapi.TransactionContextInterface, decisionJSON string) (*logic.Decision, error) {
	if err := requireAuthority(ctx); err != nil {
		return nil, err
	}
	var d logic.Decision
	if err := json.Unmarshal([]byte(decisionJSON), &d); err != nil || !reDecID.MatchString(d.ID) || d.RecID == "" || d.Operator == "" {
		return nil, errBadArg("invalid decision")
	}
	key := "DEC~" + d.ID
	if raw, err := ctx.GetStub().GetState(key); err != nil || raw != nil {
		return nil, errConflict("decision %s exists (append-only)", d.ID)
	}
	now, err := txSeconds(ctx)
	if err != nil {
		return nil, err
	}
	msp, _ := callerMSP(ctx)
	d.DocType, d.RecordedAt, d.RecorderMspID = "decision", now, msp
	raw, _ := json.Marshal(d)
	if err := ctx.GetStub().PutState(key, raw); err != nil {
		return nil, errInternal("put decision")
	}
	return &d, setEvent(ctx, "DecisionRecorded", d)
}

func (c *DecisionLog) GetDecision(ctx contractapi.TransactionContextInterface, id string) (*logic.Decision, error) {
	raw, err := ctx.GetStub().GetState("DEC~" + id)
	if err != nil {
		return nil, errInternal("get decision")
	}
	if raw == nil {
		return nil, errNotFound("decision %s", id)
	}
	var d logic.Decision
	if err := json.Unmarshal(raw, &d); err != nil {
		return nil, errInternal("decode decision")
	}
	return &d, nil
}

func requireAuthority(ctx contractapi.TransactionContextInterface) error {
	msp, err := callerMSP(ctx)
	if err != nil {
		return err
	}
	if msp != logic.AuthorityMSP {
		return errForbidden("only %s may write advisories and decisions", logic.AuthorityMSP)
	}
	return nil
}
