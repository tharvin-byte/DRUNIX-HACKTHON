# M1 Ledger. Run from ledger/. Network targets need WSL2/Linux + Docker + Go (docs/M1_LEDGER.md §3).
.PHONY: test test-go test-gateway typecheck run run-mock up down deploy bootstrap smoke bench
test: test-gateway test-go
test-gateway:
	cd gateway && npm test
test-go:
	cd chaincode && go test ./logic/...
typecheck:
	cd gateway && npx tsc --noEmit
run:
	cd gateway && LEDGER_MODE=live node src/main.ts
run-mock:
	cd gateway && LEDGER_MODE=mock node src/main.ts
bootstrap:
	./network/qs-net.sh bootstrap
up:
	./network/qs-net.sh up
down:
	./network/qs-net.sh down
deploy:
	./network/qs-net.sh deploy
smoke:
	@echo "TODO(M1): live smoke open -> debit -> credit -> GetStatus=SUCCESS (docs/M1_LEDGER.md §4.8 item 4)"
bench:
	@echo "TODO(M1): bench/bench.ts -> data/ledger_bench.json (docs/M1_LEDGER.md §7)"
