# M2 Simulator. Run from sim/. PY defaults to the shared dev venv (Windows path; override on Linux).
PY ?= ../.venv/Scripts/python
.PHONY: test run run-mock arena-small
test:
	$(PY) -m pytest -q
run:
	SIM_MODE=live $(PY) -m uvicorn --factory qsim.api:create_app --port 8001
run-mock:
	SIM_MODE=mock $(PY) -m uvicorn --factory qsim.api:create_app --port 8001
arena-small:
	$(PY) -m qsim.batch --scenario S6 --seeds 1 2 3 4 5 --universes U0 U2 U4
