# M3 Detection. Run from detect/. PY defaults to the shared dev venv; override with your own:
#   make test PY=.venv/Scripts/python
PY ?= ../.venv/Scripts/python
.PHONY: test run run-mock train-forecaster
test:
	$(PY) -m pytest -q
run:
	DETECT_MODE=live $(PY) -m uvicorn --factory qdet.api:create_app --port 8002
run-mock:
	DETECT_MODE=mock $(PY) -m uvicorn --factory qdet.api:create_app --port 8002
train-forecaster:
	$(PY) scripts/train_forecaster.py --runs ../data/runs --out ../data/models/forecaster_grid.json
