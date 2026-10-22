# M4 Control — status (updated 2026-10-20)

Legend: ✅ done and verified by a test that was run · 🟡 built, not fully verified · ⬜ not started.

## Done

| Item | State | Evidence |
|---|---|---|
| Rule table R0–R7 as data, first match wins, fallback | ✅ | C-1 (one test per row) |
| SHIFT_TRAFFIC eligibility (§4) with first failed check as `blocked_by` | ✅ | C-2, C-3 |
| BANK_SIDE: shift blocked "shared bank b", maps to DO_NOT_SHIFT advisory | ✅ | C-3, C-4 |
| Safety invariants SI-1, SI-2, SI-4, SI-5 over 5 000 random states | ✅ | C-2 |
| Governor budget formula, r_min/r_max, monotone in switch use, publish on > 10 % change | ✅ | C-7 |
| One PENDING recommendation per incident; SUPERSEDED / EXPIRED; expired when the incident closes | ✅ | dedicated test |
| Decisions → actions (SI-3) → ledger decision + advisories (SI-9), 409 on double decision / blocked action | ✅ | C-4, C-6, API contract test |
| Ledger outage: actions still applied, writes queued and retried every tick / 10 s | ✅ | C-5 |
| Simulated operator: delay honoured, confidence ≥ 0.6, never approves blocked | ✅ | C-8 |
| Live inputs (M3 + M1 SSE), mock mode, batch endpoints | ✅ | live integration smoke 2026-10-20: auto-approved BANK_SIDE package wrote advisories to the M1 mock |

## Open items (summary — the detailed task cards are in `ROADMAP.md`), in spec order

1. **C-9 rollback proposals** [BUILD]: after 6 clean ticks create a single-`ROLLBACK` recommendation for each applied action; on approval revoke its advisory (`DELETE /v1/advisories/{id}`). `actions.py` from IBM (`ActionManager.tick`) is the model; `control.yaml rollback.clean_ticks` exists.
2. **PACE_PAYOUTS** in R3 (needs an M3 feature for PAYOUT share per bank — ask M3 via a contract proposal) and its params (`max_rate_per_s = 0.5 × spare, min 5/s`).
3. **R2 DEFER_CHECKS(top bank)** uses the localizer candidate lift; check against real M3 output.
4. Budget publication currently emits many CHECK_BUDGET actions at low demo rates (29 in 137 sim s in the smoke). Consider a minimum interval or a larger change threshold; keep SI-5.
5. Ledger events → recommendation/decision status (`DecisionRecorded` tx id is stored; surface it on the `decision` stream for M5).
6. Operator-delay sweep (5, 15, 30, 60, 120 s) for the arena — the IBM project found operator delay was the dominant factor.
7. `C_status` uses the default 80/s; switch capacity is not in `segment_state` — propose adding it if M2 calibration changes capacity.

## Known issues
- Live smoke: during recovery, small INSUFFICIENT_EVIDENCE incidents from M3 produced PENDING recommendations that expired after 120 sim s (correct behaviour; noise is an M3 tuning item).
- `operator_sim` lives inside `controller.py` (`_auto_operator`) rather than its own file.

## Reused from the IBM project
Rule-order idea, SHIFT checks returning the first failing reason, approval/rejection flow and SI checks, simulated operator, API hardening patterns (see `docs/REUSE_MAP.md`). New: budget publisher instead of per-payment scheduler, ledger writes, advisories, rule table as YAML.
