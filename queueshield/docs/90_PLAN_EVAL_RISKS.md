# 90 — Plan, evaluation protocol, risks, judge Q&A and sources

> **Working copy** of the QueueShield spec v1.0 (19 Oct 2026), moved next to the code on 2026-10-20. The original stays frozen in `Citibank/queueshield-spec/` (next to `queueshield/`); this copy is the one the team updates.
> Folder names in this repo: `ledger/` → `m1_ledger/`, `sim/` → `m2_simulator/`, `detect/` → `m3_detection/`, `control/` → `m4_control/`, `console/` → `m5_console/`. Shared docs: `docs/` at the repo root; module specs: `SPEC.md` inside each module folder.

## 1. Team assignment (fill tonight)

| Module | Owner | Backup reviewer | Machine needs |
|---|---|---|---|
| M1 Ledger | | M4 owner | Linux or WSL2, ≥ 16 GB RAM (11 containers incl. 2 YugabyteDB), Docker, Go, Node 20 |
| M2 Simulator | | M3 owner | Python 3.11, ≥ 4 cores for batch |
| M3 Detection | | M2 owner | Python 3.11 |
| M4 Control | | M1 owner | Python 3.11 |
| M5 Console | | everyone | Node 20, a 1080p screen for recording |

Day 0 (tonight, Mon 19 Oct) checklist:
- [ ] Create the code repo with the layout in README; copy `AGENTS.md` and `contracts/`; add `CODEOWNERS`.
- [ ] Each owner reads their module spec fully and lists questions in the team chat.
- [ ] M1 owner starts the Drunix clone and image pulls overnight (they are large).
- [ ] Check the hackathon rules on reusing ideas from another competition; agree how to disclose (QueueShield began as an IBM Z Datathon entry; the Drunix layer, UPI model and this build are new).
- [ ] Confirm the deck format and the exact 25 Oct cutoff on the dashboard.

## 2. Five-day plan with integration gates

| Day | M1 Ledger | M2 Simulator | M3 Detection | M4 Control | M5 Console | Integration gate (end of day) |
|---|---|---|---|---|---|---|
| 1 Tue 20 | network up with sample chaincode; logic + golden vectors; **mock gateway shipped** | engine, tape, S0; mock stream | ingest, segments, windows; mock ticks | fixture recommendations; decisions → M1 mock | skeleton, SSE client, all panels on fixtures; compose skeleton | every module `make run-mock` green; contracts frozen at noon |
| 2 Wed 21 | queueshield chaincode deployed; live gateway writes + events | legs, switch coupling, naive + npci_rule, S4, S6; quick calibration | features, D0, D3 rules, surge gate, localizer | rules, eligibility, governor, action queue | core panels against mocks | M2 shows S6 switch storm; M1 L3 passes |
| 3 Thu 22 | MVCC retries, checkpointed events, `/v1/network` | ledger_first via mock then live; actions; live runner | live from M2; incidents; first grid | live inputs; ledger writes live | first compose run; DrunixPanel live | **S6 end-to-end on real Drunix** (unknowns opened, attested, pushed; budgets visible) |
| 4 Fri 23 | quick benchmark 10/25/50 tx/s; screenshots | S1, S3, (S8); arena U0/U2/U4 on S6 × 5 seeds | rough threshold tuning; grid endpoint | simulated operator; batch endpoints | arena tab, split replay, recordings; deck screenshots | full demo once end-to-end; preliminary arena numbers labelled preliminary |
| 5 Sat 24 | rehearse bring-up from scratch | freeze `sim_default.yaml` | freeze detect configs | freeze policy | polish, claims lint, backup video | two clean rehearsals; deck final; **submit Sun 25 with buffer** |

**Pitchable prototype = Definition of Done:** (1) a real Drunix network running `queueshield`; (2) S6 end to end in U4 with ledger push resolution visible in the console; (3) S3 with blocked failover and a DO_NOT_SHIFT advisory on the ledger; (4) the S4 cascade map crossing the 0.5 contour; (5) a preliminary arena chart (U0 vs U2 vs U4) labelled "simulation, 5 seeds, preliminary"; (6) replay mode and a backup video.

Cut order if a day slips (top first): IsolationForest → arena (keep split replay) → `decisionlog` contract (anchor decision hash inside the advisory) → S4/cascade map (keep S6 and S3). Never cut: real Drunix + S6 end to end + claims policy.

## 3. Dependencies and the mock that removes each wait

| Needs | From | Until real, use |
|---|---|---|
| payment events | M2 | `contracts/fixtures/payment_events.jsonl`, then M2 mock stream |
| segment state / incidents | M3 | `contracts/fixtures/incident.json`, then M3 mock ticks |
| recommendations | M4 | `contracts/fixtures/recommendation.json` |
| ledger | M1 | M1 mock gateway (Day 1) |
| forecaster training runs | M2 batch | M3 trains on whatever M2 has by Day 3; retrain Day 4 |
| ledger latency for batch | M1 benchmark | defaults in `sim_default.yaml` `ledger_model` |

## 4. Demo talk track (4 minutes)

1. "On 12 April 2025 UPI lost about five hours. NPCI said the cause was status checks: banks asking 'did this payment go through?' so often that the switch fell over. A timeout is not a failure, and asking is load."
2. "This is a live Drunix network — two organisations, Lite Peers, Committing Peers, the Validation Service, YugabyteDB. Only unknown payments, advisories and decisions touch it."
3. Surge: "Festival demand doubles. Latency holds, queues drain. QueueShield stays quiet."
4. Bank slowdown: "One bank goes slow on every PSP. The localizer says bank-side, so failover is blocked — moving traffic would only spread it. I approve slowing retries and deferring checks; a signed DO_NOT_SHIFT advisory lands on the ledger."
5. April-2025 replay: "Left: every app polls the switch; the switch saturates and everything slows. Right: the banks attest outcomes once on Drunix and every PSP gets pushed the answer. Switch checks stay flat. Zero duplicate payments. The TAT clock is on the ledger."
6. Retry storm: "The platform dashboard is late; QueueShield names the PSP first. The cascade map crosses the point of no return with a countdown. Approve; the decision is on the ledger; recovery. Same seed in the arena: naive stuck, NPCI rule slower, QueueShield recovered."
7. Close: "Simulation results, synthetic data, a local Drunix network. The next step is a sandbox pilot with NPCI APIs."

## 5. Build phase (10–22 Nov, if shortlisted)

| Priority | M1 | M2 | M3 | M4 | M5 |
|---|---|---|---|---|---|
| P0 | TAT sweeper; benchmark full (P8); `checkpolicy` contract | full calibration; S2, S5, S7; U1, U3; config sets A/B/C | matched-budget tuning; D1, D2; IsolationForest; ensemble vs grid | rollback proposals; PACE_PAYOUTS; operator-delay sweep | full demo polish; report figures |
| P1 | private data collection; Org3 authority | statistics + bootstrap CIs in arena | ablations R/M/RM; RRCF | regulator observer feed | regulator view |
| P2 | Lite Peer scale-out; upstream contribution | performance | early-warning-signal features | — | final video |

Gate on 22 Nov: every pre-registered hypothesis reported (held or not), README reproduces the demo in < 30 min, claims review done.

## 6. Evaluation protocol

| ID | Hypothesis | Metric | Scenarios / universes |
|---|---|---|---|
| P1 | D3 detects localised incidents sooner than D0, D1, D2 at ≤ 1 false alert per simulated hour | detection delay (+ missed count) | S2, S3, S4, S5, S7 (U0 traffic) |
| P2 | D3 stays within the budget during surges | false alerts / simulated hour | S0, S1 |
| P3 | U4 recovers faster with fewer wasted retries than U0, U1, U2 | recovery time, excess retries, peak queue | S4 paired |
| P4 | Localisation prevents harmful failover | harmful failovers | S3, U1 vs U4 |
| P5 | Governed checks lower the switch peak vs naive polling | peak switch checks/s | S6, U0 vs U3 |
| P6 | Forecaster gives positive lead time with few false criticals | lead time vs queue-threshold alert; false criticals/h | S4, S1, S5 |
| P7 | Ledger-first resolution removes most residual switch checks with zero duplicate commits | switch checks per unknown; duplicates; median/p95 resolve time | S6, U3 vs U4 |
| P8 | Drunix carries the exception path at measured rates | submit/evaluate latency percentiles, event lag, max sustained tx/s | M1 benchmark |

Method: disjoint configuration sets (A train 1–999, B validation 1000–1999, C test 2000–2999 seeds); thresholds frozen and tagged `eval-freeze` before set C runs once; pair by seed; report medians, IQR and 95% bootstrap CIs of paired differences (10 000 resamples); Wilcoxon signed-rank as a sanity check; missed incidents beside every delay; every comparison not in P1–P8 labelled exploratory. Pitch sample: 5 seeds per scenario per universe, labelled preliminary. Build sample: ≥ 20 configurations per scenario per universe.

Threats to validity, stated in the report: circularity (we wrote simulator and detectors) mitigated by held-out sets, the U2 baseline, ablations and negative results; small topology (3 PSPs, 5 banks); simulated operator; the switch slowdown coupling is an assumption; ledger throughput measured on a laptop-scale network.

## 7. Risk register

| Risk | Likelihood | Impact | Early signal | Fallback |
|---|---|---|---|---|
| Drunix will not start | High | High | Day 1 `up` fails | WSL2 only; apply known fixes (ccenv 1.0, YugabyteDB wait); ask organisers; M1 mock keeps everyone moving |
| Originality rules | Medium | Very high | rules mention prior work | disclose; emphasise new Drunix/UPI work; RemitWise reshape as fallback |
| Seen as another stuck-payment ledger | Medium | High | judge questions | lead with the network-level storm; competitor slide |
| Go chaincode slow to build | Medium | High | not deployed by Day 2 | cut to `paystate` + `advisory` |
| Events not delivered from the Committing Peer | Medium | Medium | L3 fails | try Lite Peer; fallback: poll `GetStatus` for open unknowns at low rate inside the gateway (documented) |
| Metastability not reproduced | Medium | Medium | calibration fails | congestion forecaster; drop "metastable" |
| Live demo fails | Medium | High | rehearsal failure | replay mode + video |
| Overclaiming | Medium | High | forbidden words in slides | claims lint + second reviewer |
| Team member unavailable | Medium | Medium | missed stand-up | modules are self-contained; backup reviewer takes over with the agent prompt template |

## 8. Judge Q&A (short answers; full list in the team doc)

| Question | Answer |
|---|---|
| Isn't this Pulse or Tally? | They resolve one payment honestly, and we include that pattern. We add the network level: detect the tipping segment, forecast lock-in, budget checks, and prove the system effect on paired seeds. |
| Why a blockchain? | The truth about a payment is split across organisations. Each fact is signed by the org that knows it, the endorsement policy enforces who may say what, and NPCI-rule compliance and TAT become provable rather than self-reported. |
| Can it handle UPI scale? | Only exceptions go on-chain. At an assumed 0.5% unknown rate, 802 M payments/day is ~46 records/s on average; we report our measured throughput and Lite Peers scale out for peaks. |
| Do banks change anything? | They attest legs of unknown payments they already know about — less work than answering repeated status checks. |
| What does Citi get? | Early warning on beneficiary banks, load-aware payout pacing, and the same push-from-ledger status model it runs in Token Services. |
| Is the simulator realistic? | It models queues, timeouts, retries, zombie work, shared banks and a shared status service, calibrated to NPCI technical-decline data; it compares policies on identical random draws, not real banks. |
| Why human approval? | Financial and routing actions; a timeout is not a confirmed failure; the operator-delay sweep shows how fast approval must be. |
| Why no LLM? | Determinism, latency and auditability; an LLM could explain incidents later, outside the decision path. |

## 9. Sources (opened 19 Oct 2026 unless marked)

- npci/drunix repository, README, `docs/drunix-arch.md`, `drunix-network/test-network/README.md`, release v1.0.0 — https://github.com/npci/drunix
- settlemint-drunix README and `docs/architecture.md` (verified Drunix internals by another team) — https://github.com/Nithilan77/settlemint-drunix
- Hyperledger Fabric Gateway client API (Network, chaincode events, checkpointers) — https://hyperledger.github.io/fabric-gateway/main/api/node/interfaces/Network.html (search excerpt)
- MediaNama on NPCI OC-215 (30 Apr 2025) and OC-214 (17 Jun 2025) — https://www.medianama.com/2025/04/223-npci-new-guidelines-upi-outage/ · https://www.medianama.com/2025/06/223-npci-upi-changes-transaction-speed-fraud-prevention/
- RBI TAT circular RBI/2019-20/67 — https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11693
- NPCI BD/TD and uptime statistics — https://www.npci.org.in/statistics/bd-td-and-uptime
- StartupTalky, UPI September 2026 — https://startuptalky.com/india-upi-transactions-september-2026/
- Huang et al., Metastable Failures in the Wild, OSDI 2022 — https://www.usenix.org/conference/osdi22/presentation/huang-lexiang
- Juspay Decision Engine API reference — https://api-reference.hyperswitch.io/decision-engine-api-reference/api-reference/endpoint/score-feedback/updateGatewayScore.md
- Citi Token Services — https://services.citi.com/solutions/citi-token-services
- Drunix competitor repos: Pulse (https://github.com/cs25b1074-stack/citi), Tally (https://github.com/sharannya310106/tally-drunix), Project Axis (https://github.com/ferroflux/project-axis); others via search excerpts
- Search excerpts only: Cashfree routing blog, Razorpay success-rate blog, Google SRE Handling Overload, Citi Payment Outlier Detection press release, D91 Labs TD trend, Kaggle UPI Transactions 2024, PaySim
- QueueShield v2 Complete Implementation Blueprint (IBM Z Datathon 2026) — the team's own document, sections 9–15 and 17 adapted here
