package logic

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

type goldenCase struct {
	From             string  `json:"from"`
	Kind             string  `json:"kind"`
	MspID            string  `json:"mspId"`
	ExpectState      string  `json:"expect_state"`
	ExpectError      string  `json:"expect_error"`
	Noop             bool    `json:"noop"`
	VersionIncrement int64   `json:"version_increment"`
	Event            *string `json:"event"`
	DisputedReason   string  `json:"disputed_reason"`
	DebitImplied     bool    `json:"debit_implied"`
	SetsTatDeadline  bool    `json:"sets_tat_deadline"`
}

// L2: every cell of table 4.3 plus wrong-MSP cases, from the vectors shared with the TypeScript mock.
func TestGoldenVectors(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/transitions.json")
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Cases []goldenCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Cases) < 70 {
		t.Fatalf("expected >= 70 cases, got %d", len(doc.Cases))
	}
	for i, c := range doc.Cases {
		p := &Payment{DocType: "payment", State: c.From, Version: 3, TatSeconds: 120}
		res, err := Apply(p, c.Kind, c.MspID, 1000, 5000, nil)
		if c.ExpectError != "" {
			if err == nil || !strings.HasPrefix(err.Error(), c.ExpectError) {
				t.Errorf("case %d %+v: want error %s, got %v", i, c, c.ExpectError, err)
			}
			continue
		}
		if err != nil {
			t.Errorf("case %d: unexpected error %v", i, err)
			continue
		}
		if res.Payment.State != c.ExpectState || res.Noop != c.Noop || res.Payment.Version-3 != c.VersionIncrement {
			t.Errorf("case %d %+v: got state=%s noop=%v version+%d", i, c, res.Payment.State, res.Noop, res.Payment.Version-3)
		}
		want := ""
		if c.Event != nil {
			want = *c.Event
		}
		if res.Event != want {
			t.Errorf("case %d: event %q, want %q", i, res.Event, want)
		}
		if res.DisputedReason != c.DisputedReason {
			t.Errorf("case %d: disputed reason %q, want %q", i, res.DisputedReason, c.DisputedReason)
		}
		if c.DebitImplied && !res.Payment.DebitImplied {
			t.Errorf("case %d: debitImplied not set", i)
		}
		if c.SetsTatDeadline && (res.Payment.TatDeadline == nil || *res.Payment.TatDeadline != 1120) {
			t.Errorf("case %d: tatDeadline %v, want 1120", i, res.Payment.TatDeadline)
		}
		if p.Version != 3 || p.State != c.From {
			t.Errorf("case %d: input record mutated", i)
		}
	}
}

func TestCheckTAT(t *testing.T) {
	dl := int64(100)
	p := &Payment{State: Debited, TatDeadline: &dl, Version: 2}
	if r, _ := CheckTAT(p, 100); !r.Noop {
		t.Fatal("no breach at the deadline itself")
	}
	r, _ := CheckTAT(p, 101)
	if r.Noop || !r.Payment.TatBreached || r.Event != "TATBreach" || r.Payment.Version != 3 {
		t.Fatalf("breach not recorded: %+v", r)
	}
	if r2, _ := CheckTAT(r.Payment, 500); !r2.Noop {
		t.Fatal("a breach is recorded once")
	}
}
