# M2 Simulator — status (updated 2026-10-20)

Legend: ✅ done and verified by a test that was run · 🟡 built, not fully verified · ⬜ not started.

## Done

| Item | State | Evidence |
|---|---|---|
| Config in YAML → frozen dataclasses (§9 defaults) | ✅ | `config/*.yaml`, `qsim/config.py` |
| Common-random-number tape, named PCG64 streams (§10) | ✅ | S-3 test |
| Engine: PSP queues/workers, remitter + beneficiary legs, declines, zombie work, reversals | ✅ | S-1, S-2 tests |
| Switch status service + slowdown coupling (§2.2) | ✅ | S-7: U0 S6 slowdown > 2, util > 0.95 |
| Client profiles naive / npci_rule / governed / ledger_first, 30 % naive mix in U3/U4 (§4) | ✅ | S-6 (SI-1 from the stream) |
| U1 textbook failover rule | 🟡 | implemented, no dedicated test |
| Ledger **model** for U4 (open unknowns, pushed resolution) | ✅ | `test_ledger_model_resolves_unknowns_in_u4` |
| Actions THROTTLE_RETRIES, SHED_EXPIRED, PRIORITIZE_FRESH, SHIFT_TRAFFIC, CHECK_BUDGET, DEFER_CHECKS, ROLLBACK | ✅/🟡 | S-9 (throttle); others applied but not individually tested |
| Scenarios S0–S8 incl. S8 payout batch | 🟡 | S8 events validate; S1/S2/S5/S7 not exercised by tests |
| Events validate against `payment_event.schema.json` | ✅ | S-5 contract tests |
| Batch runner writes `data/runs/<run_id>/*` + valid `result.json` | ✅ | ran S3 and S6 (600 s S3 run in 8.4 s wall) |
| HTTP API: health, scenario, status, stream, timeseries, results | ✅ | `test_api.py`; live run used in the integration smoke |
| Mock mode (fixture replay) | 🟡 | implemented; not covered by a test |

Last test run: `../.venv/Scripts/python -m pytest -q` → see the root README "Verification" table.

## Open items (summary — the detailed task cards are in `ROADMAP.md`), in spec order

1. **Calibration gate G-SIM (§8) — highest priority.** At the spec defaults, any S4 trigger (even 20 s at 50 % worker loss) locks *all three* PSPs at `q_max` for the rest of the run under U0 **and** U2: once ~27 unknowns/s appear, npci_rule's 3 checks each exceed the switch's ~80 checks/s, slowdown hits ×4 and everything times out. §8 needs short triggers to recover in ≥ 80 % of seeds. Write `scripts/calibrate.py` (S4 and S6 sweeps), then tune in this order: switch capacity (`status_workers`), `slowdown_alpha` / `slowdown_u0`, whether slowdown should also scale PSP processing, then the §8 list. Save `data/figures/F1_s4.png`, `F1_s6.png`, tag `sim-frozen`.
2. **S-4 utilisation**: S0 gives P1 ≈ 0.58, P2 ≈ 0.51, P3 ≈ 0.37 with equal workers per PSP. Decide whether 0.50–0.60 is per PSP (then make workers proportional to share) or a platform mean.
3. **S-11: live ledger bridge** (`ledger_bridge.py`): open unknowns on M1 (`POST /v1/payments`), banks attest legs (`/attest`), resolve only on a terminal `PaymentUpdated` from `GET /v1/stream`. M1's mock gateway is ready for this today.
4. **S-10 arena**: `POST /v1/arena` background job (today: `python -m qsim.batch`), 5 seeds × U0/U2/U4 on S6 through the M3/M4 lockstep endpoints (`DETECT_URL`, `CONTROL_URL`); forward ledger-model events to M4 in U4 (TODO in `batch.py`).
5. Metrics still `null`: `tat_breaches`, `harmful_failovers` (arena compares with the paired U2 run).
6. PACE_PAYOUTS enforcement (recorded but not applied).
7. Replace placeholder `td_rate` with NPCI bank-wise technical-decline figures (E9) and record the source month in `config/README.md`.
8. Replace the sim-side fallback `default_budget` (rate 10/s) once M4 publishes budgets from t = 0; it is a placeholder.
9. Live pacing: the live runner reaches ~1.7× wall clock at speed 4 (Python step cost); fine for the demo, measure before quoting.

## Known issues
- `fresh_rate()` used by THROTTLE_RETRIES reads a 10 s ring that is reset per snapshot; OK at 1 s snapshots, fragile if `snapshot_ms` changes.
- S1 flash is capped at ρ ≤ 0.95 (≈ ×1.73, spec says ×2.5) — IBM lesson; see docs/DEVIATIONS.md.

## Reused from the IBM project
Heap loop, queue/worker accounting, fresh/retry split, shed and fresh-first controls, modifier ramps, tape idea, scenario builder, id helpers (see `docs/REUSE_MAP.md`). New: two legs per payment, switch coupling, universes U2–U4, ledger model, contract events.
