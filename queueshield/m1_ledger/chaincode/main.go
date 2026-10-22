package main

// One chaincode, three contracts: paystate, advisory, decisionlog (docs/M1_LEDGER.md §4.1).
// Functions are invoked as e.g. "paystate:OpenUnknown". One chaincode = one YSQL table mychannel.queueshield.

import (
	"log"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

func main() {
	cc, err := contractapi.NewChaincode(
		&PayState{Contract: contractapi.Contract{Name: "paystate"}},
		&Advisory{Contract: contractapi.Contract{Name: "advisory"}},
		&DecisionLog{Contract: contractapi.Contract{Name: "decisionlog"}},
	)
	if err != nil {
		log.Panicf("create queueshield chaincode: %v", err)
	}
	if err := cc.Start(); err != nil {
		log.Panicf("start queueshield chaincode: %v", err)
	}
}
