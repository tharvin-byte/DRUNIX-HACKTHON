# M4 Control. Run from control/. PY defaults to the shared dev venv; override with your own:
#   make test PY=.venv/Scripts/python
PY ?= ../.venv/Scripts/python
.PHONY: test run run-mock run-auto
test:
	$(PY) -m pytest -q
run:
	CONTROL_MODE=live $(PY) -m uvicorn --factory qctl.api:create_app --port 8003
run-auto:
	CONTROL_MODE=live OPERATOR_MODE=auto $(PY) -m uvicorn --factory qctl.api:create_app --port 8003
run-mock:
	CONTROL_MODE=mock $(PY) -m uvicorn --factory qctl.api:create_app --port 8003
