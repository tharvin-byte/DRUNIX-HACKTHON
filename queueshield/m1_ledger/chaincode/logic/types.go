// Package logic is the pure, Fabric-free core of the queueshield chaincode (docs/M1_LEDGER.md §4).
// It is tested against testdata/transitions.json, the same golden vectors the TypeScript mock uses.
package logic

// Organisation roles in the 2-org test network (§4.1). In the 3-org [STRETCH] AuthorityMSP becomes Org3MSP.
const (
	AuthorityMSP   = "Org1MSP"
	RemitterMSP    = "Org1MSP"
	BeneficiaryMSP = "Org2MSP"
)

// Payment states.
const (
	Unknown       = "UNKNOWN"
	Debited       = "DEBITED"
	Success       = "SUCCESS"
	FailedNoDebit = "FAILED_NO_DEBIT"
	CreditFailed  = "CREDIT_FAILED"
	Reversed      = "REVERSED"
	Disputed      = "DISPUTED"
)

// Attestation kinds.
const (
	KindDebit              = "DEBIT"
	KindCredit             = "CREDIT"
	KindFailureRemitter    = "FAILURE_REMITTER"
	KindFailureBeneficiary = "FAILURE_BENEFICIARY"
	KindReversal           = "REVERSAL"
)

// Attestation is one signed statement appended to a payment (fixed field order for deterministic JSON).
type Attestation struct {
	MspID      string  `json:"mspId"`
	Kind       string  `json:"kind"`
	At         int64   `json:"at"`
	SimMs      int64   `json:"simMs"`
	ReasonCode *string `json:"reasonCode"`
}

// Payment mirrors contracts/schemas/ledger_payment.schema.json (camelCase, fixed order).
type Payment struct {
	DocType         string        `json:"docType"`
	TxnRef          string        `json:"txnRef"`
	IdemKeyHash     string        `json:"idemKeyHash"`
	PayerPsp        string        `json:"payerPsp"`
	RemitterBank    string        `json:"remitterBank"`
	BeneficiaryBank string        `json:"beneficiaryBank"`
	RunID           string        `json:"runId"`
	State           string        `json:"state"`
	OpenedAt        int64         `json:"openedAt"`
	OpenedSimMs     int64         `json:"openedSimMs"`
	DebitAt         *int64        `json:"debitAt"`
	CreditAt        *int64        `json:"creditAt"`
	FailureAt       *int64        `json:"failureAt"`
	ReversalAt      *int64        `json:"reversalAt"`
	ReasonCode      *string       `json:"reasonCode"`
	DebitImplied    bool          `json:"debitImplied"`
	TatSeconds      int64         `json:"tatSeconds"`
	TatDeadline     *int64        `json:"tatDeadline"`
	TatBreached     bool          `json:"tatBreached"`
	Attestations    []Attestation `json:"attestations"`
	Version         int64         `json:"version"`
}

// Advisory mirrors contracts/schemas/advisory.schema.json.
type Advisory struct {
	DocType       string                 `json:"docType"`
	ID            string                 `json:"id"`
	Kind          string                 `json:"kind"`
	SegmentID     string                 `json:"segmentId"`
	Params        map[string]interface{} `json:"params"`
	Reason        string                 `json:"reason"`
	EvidenceHash  string                 `json:"evidenceHash"`
	DecisionID    string                 `json:"decisionId"`
	IssuedSimMs   int64                  `json:"issuedSimMs"`
	ValidForSec   int64                  `json:"validForSec"`
	IssuedAt      int64                  `json:"issuedAt"`
	ExpiresAt     int64                  `json:"expiresAt"`
	Revoked       bool                   `json:"revoked"`
	RevokedReason *string                `json:"revokedReason"`
	IssuerMspID   string                 `json:"issuerMspId"`
}

// Decision mirrors contracts/schemas/ledger_decision.schema.json.
type Decision struct {
	DocType         string                 `json:"docType"`
	ID              string                 `json:"id"`
	RecID           string                 `json:"recId"`
	Decision        string                 `json:"decision"`
	Operator        string                 `json:"operator"`
	ActionsApproved []string               `json:"actionsApproved"`
	ModelVersions   map[string]interface{} `json:"modelVersions"`
	FeaturesSha256  string                 `json:"featuresSha256"`
	DecidedSimMs    int64                  `json:"decidedSimMs"`
	RecordedAt      int64                  `json:"recordedAt"`
	RecorderMspID   string                 `json:"recorderMspId"`
}
