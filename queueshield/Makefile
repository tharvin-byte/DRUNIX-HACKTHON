# Convenience wrapper; each module's own Makefile is the source of truth.
.PHONY: test test-ledger test-sim test-detect test-control test-console
test: test-ledger test-sim test-detect test-control test-console
test-ledger:
	$(MAKE) -C m1_ledger test-gateway
test-sim:
	$(MAKE) -C m2_simulator test
test-detect:
	$(MAKE) -C m3_detection test
test-control:
	$(MAKE) -C m4_control test
test-console:
	$(MAKE) -C m5_console test
