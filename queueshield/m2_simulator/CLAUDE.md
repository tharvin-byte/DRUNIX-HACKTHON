# M2 Simulator — instructions for whoever (human or AI agent) works in `m2_simulator/`

## Read in this order
1. `../AGENTS.md` — binding rules for every module.
2. This file.
3. `STATUS.md` — what exists and is verified.
4. `ROADMAP.md` — the task cards (M2-T01 …) with acceptance checks. **Pick work from here.**
5. `SPEC.md` — the module spec (working copy). Shared context: `../docs/00_PRODUCT.md`, `../docs/01_SYSTEM.md`,
   `../contracts/CONTRACTS.md` §1, §4.1, §6. Research notes: `../docs/RESEARCH.md`.

## How to work a task
1. Take the lowest-numbered open P0 card in `ROADMAP.md` unless the lead assigned another. Say which card you took.
2. Read the code it names. Run `../.venv/Scripts/python -m pytest -q` first to see the baseline (16 passing on 2026-10-20).
3. Write or extend the test that encodes the card's **Done when**, then the code.
4. Run the full suite again. Run the card's exact check command.
5. Update `STATUS.md` (move the item, add evidence) and tick the card in `ROADMAP.md` (`✅ done <date>`).
   Any deviation from `SPEC.md` → one line in `../docs/DEVIATIONS.md`.
6. Report in one paragraph: what you built, which tests pass (with the command), every deviation, open questions.
   Never claim a test passes unless you ran it.

## Hard rules for this module
- Stay inside `m2_simulator/`. Outside it you may only append one line to `../docs/DEVIATIONS.md` or add a proposal file in
  `../contracts/PROPOSALS/`. Never edit `../contracts/`. Never import `qdet`/`qctl` or code from other module folders
  (`tests/test_isolation.py` fails if you do). Talk to other modules only over HTTP/SSE or `../data/` files.
- Determinism: all randomness through `qsim/tape.py` streams or a generator seeded from (seed, scenario). No `random`,
  no `time.time()` in simulation logic. Same seed + universe ⇒ identical event stream (S-1).
- Never emit ground truth on the stream (which attempt committed, holds, onsets). Ground truth lives only in
  `ground_truth.json` and `Engine.ground_truth_stats()`.
- Zombie work keeps its PSP worker; status checks go through the shared switch service — otherwise the April-2025 loop disappears.
- Every tunable number lives in `config/*.yaml`. After M2-T01, `sim_default.yaml` is frozen (tag `sim-frozen`); a later
  dynamics change regenerates every dataset and must be announced to M3.
- Validate every emitted event against `payment_event.schema.json` (tests do it fully; the live path validates each one).
- Claims: never "prevents outages", "production-ready", "NPCI-approved", "Citi integration", "guaranteed". Outcome numbers say "simulation".
- Commit messages start `M2: `; branch `m2/<short-name>`; do not commit unless asked.

## Environment
Windows dev machine: shared venv `../.venv` (Python 3.11); pip behind TLS interception needs
`--trusted-host pypi.org --trusted-host files.pythonhosted.org`; `make` is not installed — run the Makefile lines by hand.
Write multi-line files with the editor, not shell heredocs.

## Prompt to give a coding agent
```
You are the M2 Simulator agent for QueueShield. Work only in queueshield/m2_simulator/.
Read ../AGENTS.md, CLAUDE.md, STATUS.md, ROADMAP.md and SPEC.md in full. Take card <M2-Txx> from ROADMAP.md.
Tests first; run ../.venv/Scripts/python -m pytest -q before and after. Update STATUS.md and ROADMAP.md.
Report what passed with the exact command, every deviation, and open questions.
```
