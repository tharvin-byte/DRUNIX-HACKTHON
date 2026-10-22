# M3 Detection — instructions for whoever (human or AI agent) works in `m3_detection/`

## Read in this order
1. `../AGENTS.md` — binding rules for every module.
2. This file.
3. `STATUS.md` — what exists and is verified.
4. `ROADMAP.md` — the task cards (M3-T01 …) with acceptance checks. **Pick work from here.**
5. `SPEC.md` — the module spec (working copy). Shared: `../docs/00_PRODUCT.md`, `../docs/01_SYSTEM.md`,
   `../contracts/CONTRACTS.md` §2, §6. Research: `../docs/RESEARCH.md`. IBM evaluation code to borrow ideas from:
   `../../OldReferenceAnalagousProject/IBM/qs/eval/`, `scripts/tune_detectors.py` (read-only reference).

## How to work a task
1. Take the lowest-numbered open P0 card in `ROADMAP.md` unless the lead assigned another. Say which card you took.
2. Run `../.venv/Scripts/python -m pytest -q` first (18 passing on 2026-10-20).
3. Write the test for the card's **Done when**, then the code. Use the synthetic `Stream` builder in `tests/conftest.py`
   so tests never need M2 running; use recorded runs in `../data/runs/` only with `pytest.mark.skipif` when absent.
4. Run the full suite and the card's check. Update `STATUS.md`, tick the card in `ROADMAP.md`, log deviations in
   `../docs/DEVIATIONS.md`, report in one paragraph with the exact commands.

## Hard rules for this module
- Stay inside `m3_detection/` (plus one line in `../docs/DEVIATIONS.md` or a file in `../contracts/PROPOSALS/`).
  Never import `qsim`/`qctl` or other modules' code (`tests/test_isolation.py`).
- **No ground truth at inference.** Only `scripts/` may read `ground_truth.json`; `qdet/` never imports `scripts/`.
- Every threshold comes from `config/detect.yaml` or the generated `config/detectors_frozen.yaml`. No magic numbers.
- NaN/None means "no information" — never treat a missing quantile or ratio as 0.
- Bank involvement double-counts by design (remitter and beneficiary); never normalise IB to sum to 1.
- Freeze baselines while an incident is open on a segment.
- Detector comparisons only at the matched false-alert budget; freeze thresholds before any test-set (C) run, score C once.
- Every published message validates against `segment_state` / `incident`.
- Claims: "forecasts whether a degradation will lock in if nothing changes" — never "predicts outages". Reasons are
  "supporting signals, not proof of cause". Report negative results (the IBM project did; the spec requires it).
- Commit messages start `M3: `; branch `m3/<short-name>`; do not commit unless asked.

## Environment
Shared venv `../.venv`; pip needs `--trusted-host …` behind TLS interception; no `make` — run Makefile lines by hand.
Training data comes from M2: `cd ../m2_simulator && ../.venv/Scripts/python -m qsim.batch --scenario S4 --seeds 1 2 3 --universes U0 --out ../data/runs`.

## Prompt to give a coding agent
```
You are the M3 Detection agent for QueueShield. Work only in queueshield/m3_detection/.
Read ../AGENTS.md, CLAUDE.md, STATUS.md, ROADMAP.md and SPEC.md in full. Take card <M3-Txx> from ROADMAP.md.
Tests first; run ../.venv/Scripts/python -m pytest -q before and after. No ground truth at inference.
Update STATUS.md and ROADMAP.md. Report results with the exact command, deviations, open questions.
```
