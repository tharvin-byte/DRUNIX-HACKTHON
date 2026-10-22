package main

import (
	"strings"
	"testing"

	"github.com/hyperledger/fabric-chaincode-go/pkg/cid"
	"github.com/hyperledger/fabric-chaincode-go/shim"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type stubbedCtx struct {
	stub *fakeStub
	cid  *fakeCID
}

func (c *stubbedCtx) GetStub() shim.ChaincodeStubInterface  { return c.stub }
func (c *stubbedCtx) GetClientIdentity() cid.ClientIdentity { return c.cid }

type fakeCID struct {
	cid.ClientIdentity
	msp string
}

func (f *fakeCID) GetMSPID() (string, error) { return f.msp, nil }

type fakeStub struct {
	shim.ChaincodeStubInterface
	state     map[string][]byte
	txSec     int64
	events    int
	lastEvent string
}

func newCtx(msp string, txSec int64) *stubbedCtx {
	return &stubbedCtx{
		stub: &fakeStub{state: map[string][]byte{}, txSec: txSec},
		cid:  &fakeCID{msp: msp},
	}
}

func (s *fakeStub) GetState(key string) ([]byte, error) {
	return s.state[key], nil
}

func (s *fakeStub) PutState(key string, value []byte) error {
	cp := append([]byte{}, value...)
	s.state[key] = cp
	return nil
}

func (s *fakeStub) GetTxTimestamp() (*timestamppb.Timestamp, error) {
	return &timestamppb.Timestamp{Seconds: s.txSec}, nil
}

func (s *fakeStub) SetEvent(name string, payload []byte) error {
	s.events++
	s.lastEvent = name
	return nil
}

func TestOpenUnknownValidationAndIdempotency(t *testing.T) {
	ps := &PayState{}
	ctx := newCtx("Org1MSP", 1000)
	hash1 := "sha256:" + strings.Repeat("a", 64)
	hash2 := "sha256:" + strings.Repeat("b", 64)

	// SPEC §4.8 item 2: format validation for every argument (bad txnRef, bad bank, tatSeconds out of range)
	if _, err := ps.OpenUnknown(ctx, "bad ref!", hash1, "P1", "B1", "B2", "r-S6-1-U4", 5000, 120); err == nil || !strings.HasPrefix(err.Error(), "QS_ERR_BAD_ARG") {
		t.Fatalf("expected BAD_ARG for bad txnRef, got %v", err)
	}
	if _, err := ps.OpenUnknown(ctx, "r-S6-1-U4:p-0000001", hash1, "P1", "B9", "B2", "r-S6-1-U4", 5000, 120); err == nil || !strings.HasPrefix(err.Error(), "QS_ERR_BAD_ARG") {
		t.Fatalf("expected BAD_ARG for bad bank, got %v", err)
	}
	if _, err := ps.OpenUnknown(ctx, "r-S6-1-U4:p-0000001", hash1, "P1", "B1", "B2", "r-S6-1-U4", 5000, 3); err == nil || !strings.HasPrefix(err.Error(), "QS_ERR_BAD_ARG") {
		t.Fatalf("expected BAD_ARG for tatSeconds < 10, got %v", err)
	}

	// SPEC §4.8 item 3: OpenUnknown twice identical -> one write; with different idemKeyHash -> CONFLICT
	p1, err := ps.OpenUnknown(ctx, "r-S6-1-U4:p-0000001", hash1, "P1", "B1", "B2", "r-S6-1-U4", 5000, 120)
	if err != nil || p1.State != "UNKNOWN" || ctx.stub.events != 1 {
		t.Fatalf("first OpenUnknown failed: %v, events=%d", err, ctx.stub.events)
	}
	p2, err := ps.OpenUnknown(ctx, "r-S6-1-U4:p-0000001", hash1, "P1", "B1", "B2", "r-S6-1-U4", 5000, 120)
	if err != nil || p2.Version != p1.Version || ctx.stub.events != 1 {
		t.Fatalf("identical OpenUnknown must be idempotent noop: err=%v events=%d", err, ctx.stub.events)
	}
	if _, err := ps.OpenUnknown(ctx, "r-S6-1-U4:p-0000001", hash2, "P1", "B1", "B2", "r-S6-1-U4", 5000, 120); err == nil || !strings.HasPrefix(err.Error(), "QS_ERR_CONFLICT") {
		t.Fatalf("different idemKeyHash must return QS_ERR_CONFLICT, got %v", err)
	}
}

func TestAdvisoryAndDecisionLogContracts(t *testing.T) {
	adv := &Advisory{}
	dec := &DecisionLog{}
	ctxOrg1 := newCtx("Org1MSP", 2000)
	ctxOrg2 := newCtx("Org2MSP", 2000)
	evHash := "sha256:" + strings.Repeat("c", 64)

	advJSON := `{"id":"adv-00001","kind":"DO_NOT_SHIFT","segmentId":"bank:*:B1","params":{},"reason":"shared bank","evidenceHash":"` + evHash + `","decisionId":"dec-00001","issuedSimMs":10000,"validForSec":60}`
	if _, err := adv.IssueAdvisory(ctxOrg2, advJSON); err == nil || !strings.HasPrefix(err.Error(), "QS_ERR_FORBIDDEN") {
		t.Fatalf("expected FORBIDDEN from Org2MSP, got %v", err)
	}
	a, err := adv.IssueAdvisory(ctxOrg1, advJSON)
	if err != nil || a.ExpiresAt != 2060 || a.Revoked {
		t.Fatalf("IssueAdvisory failed: %v %+v", err, a)
	}
	r, err := adv.RevokeAdvisory(ctxOrg1, "adv-00001", "recovered")
	if err != nil || !r.Revoked || r.RevokedReason == nil || *r.RevokedReason != "recovered" {
		t.Fatalf("RevokeAdvisory failed: %v %+v", err, r)
	}

	decJSON := `{"id":"dec-00001","recId":"rec-0001","decision":"APPROVE_ALL","operator":"saran","actionsApproved":["THROTTLE_RETRIES"],"modelVersions":{"rules":"1"},"featuresSha256":"` + strings.Repeat("d", 64) + `","decidedSimMs":10000}`
	d, err := dec.RecordDecision(ctxOrg1, decJSON)
	if err != nil || d.RecorderMspID != "Org1MSP" {
		t.Fatalf("RecordDecision failed: %v %+v", err, d)
	}
	if _, err := dec.RecordDecision(ctxOrg1, decJSON); err == nil || !strings.HasPrefix(err.Error(), "QS_ERR_CONFLICT") {
		t.Fatalf("duplicate RecordDecision must return CONFLICT, got %v", err)
	}
}
