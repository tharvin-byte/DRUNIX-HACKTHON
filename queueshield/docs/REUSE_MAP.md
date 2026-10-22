# What was reused from the IBM Z Datathon project (`../OldReferenceAnalagousProject/IBM`)

The IBM project ("QueueShield v2") had the same core idea — detect, localise, forecast payment-gateway degradation and
recommend operator-approved actions, evaluated in a reactive simulator with a policy arena — but no ledger, no switch,
no remitter/beneficiary legs, one Python package instead of five services, and gateways G1–G3 instead of PSPs P1–P3.
Code was **adapted** (types, ids, segments and contracts rewritten), never imported. The old folder stays read-only.

**Disclosure:** the spec's Day-0 checklist (docs/90_PLAN_EVAL_RISKS.md §1) asks the team to check the hackathon's rules
on reusing work from another competition and agree how to disclose it. This table is the factual basis for that.

| New file | Adapted from (IBM) | What changed |
|---|---|---|
| `m2_simulator/qsim/engine.py` | `qs/sim/engine.py`, `entities.py`, `controls.py` | kept heap loop, queues/workers, fresh-first, shed, throttle; added remitter + beneficiary legs, switch status service with slowdown coupling, S6 credit hold, U0–U4 client profiles, ledger model, contract events |
| `m2_simulator/qsim/tape.py` | `qs/sim/tape.py` | named PCG64 streams, three service quantiles per attempt, payout batch arrivals |
| `m2_simulator/qsim/scenarios.py` | `qs/sim/scenarios.py` | S0–S8 per the new spec; flash cap kept (IBM lesson) |
| `m2_simulator/qsim/ids.py`, `config.py` | `qs/ids.py`, `qs/config.py` | new id formats, YAML → frozen dataclasses |
| `m3_detection/qdet/windows.py`, `features.py`, `baselines.py` | `qs/core/windows.py`, `features.py`, `baselines.py` | 25 segments with dual bank involvement, near-timeout / switch / ledger features, schema names |
| `m3_detection/qdet/ingest.py` | `qs/core/ingest.py`, `dedupe.py` | dict events validated against the contract |
| `m3_detection/qdet/detectors/d3.py`, `baseline_detectors.py` | `qs/core/detectors/rules.py`, `persistence.py`, `threshold.py`, `adaptive.py` | six signals, logistic rule score, contract reason codes |
| `m3_detection/qdet/lifecycle.py` | `qs/core/lifecycle.py` | overlap merge + stale-primary guard (fixes the IBM WP-11 spurious-incident bug), network-wide anchor |
| `m3_detection/qdet/forecast/grid.py` | `qs/forecast/grid.py` | spec bins, contour export, from/to contract JSON |
| `m3_detection/qdet/localizer.py` | `qs/core/localizer.py` (structure only) | new math: involvement lift, SWITCH_STATUS_OVERLOAD |
| `m4_control/qctl/policy.py` | `qs/core/policy.py` | rule table moved to YAML (R0–R7), SHIFT checks per new §4, advisory mapping |
| `m4_control/qctl/controller.py` | `qs/core/actions.py`, `qs/eval/arena.py` (SimulatedOperator) | decisions → actions → ledger writes, SI-3/SI-9, expiry on incident close (fixes an IBM review finding) |
| `m4_control/qctl/governor.py` | `qs/core/governor.py` (token-bucket math) | now a per-PSP budget *publisher*; M2 runs the bucket |
| `*/contracts.py`, `jsonlog.py`, `sse.py`, API hardening | `qs/api/app.py` patterns | copied per module (AGENTS.md rule 3), contract SSE rules |
| `m1_ledger/**` | — | new |
| `m5_console/**` | — (layout ideas only) | React/TS rewrite |

## Lessons carried over from the IBM results (docs/RESULTS.md, EXPLORATORY.md, DEVIATIONS.md there)
- Rules-only D3 raised fewer false alerts than rules + IsolationForest on two held-out sets → rules are the [PITCH] path here.
- False-alert floors that were needed (`lat_min_ratio`, `q_min_delay`, `queue_growth_eps`) are in `m3_detection/config/detect.yaml`.
- Lock-in only appeared after raising the queue bound; here the opposite problem showed up first (see M2 STATUS: everything locks).
- Monotone grid smoothing cost AUC in IBM; the new spec requires it — compare both once there is data.
- The forecaster had no lead time before collapse → keep "forecasts whether it locks in if nothing changes", never "predicts outages".
- Operator approval delay dominated outcomes → M4 keeps an operator-delay sweep.
