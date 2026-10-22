# 00 — Product, domain and rules of the game

This document tells every agent **what** QueueShield is, **why** each part exists, which real-world facts it is built on, and what we are allowed to claim. Module specs (`M1`–`M5`) tell you **how**.

---

## 1. The problem in one paragraph

India's UPI processed 24.07 billion payments in September 2026, an average of 802 million a day. When a bank or PSP route slows down, the payer's app times out and the payment's outcome becomes **unknown** (the money may or may not have moved). Every party that cares then asks the central switch for the status, and users retry. Those status checks and retries are extra load on a system that is already slow, so the slowdown deepens and spreads. In March and April 2025 this exact loop caused three UPI outages; NPCI attributed them to a high number of Check Transaction Status API calls at very high TPS from PSP banks, and responded with a circular that limits status checks. That circular is a set of timers each bank must honour on its own, verified by annual audits. Nobody has a shared, tamper-evident, push-based record of payment state, and nobody gets an early warning that a segment is about to tip into a self-sustaining storm.

## 2. Evidence base (all figures used anywhere in the build must come from this table)

| ID | Fact | Value | Source (opened 19 Oct 2026) |
|---|---|---|---|
| E1 | UPI monthly volume, Sep 2026 | 24.07 billion, Rs 29.37 lakh crore | StartupTalky citing NPCI data — https://startuptalky.com/india-upi-transactions-september-2026/ |
| E2 | UPI daily average, Sep 2026 | 802 million/day (record) | same |
| E3 | UPI outages linked to status checks | 26 Mar, 2 Apr, 12 Apr 2025 | MediaNama — https://www.medianama.com/2025/04/223-npci-new-guidelines-upi-outage/ |
| E4 | NPCI's stated cause | high number of Check Transaction Status APIs at very high TPS by PSP banks | NPCI circular UPI-OC-215 FY25-26, via E3 |
| E5 | NPCI rule after Apr 2025 (OC-215) | first check ≥ 90 s after the transaction (45–60 s after a later revision); at most 3 checks within 2 h; stop after listed error codes; then settlement files or one UDIR check | E3 |
| E6 | NPCI response-time cuts (OC-214), from 16 Jun 2025 | Request/Response Pay 30 s → 15 s; Check Transaction Status 30 s → 10 s; Reversal 30 s → 10 s; Validate Address 15 s → 10 s; NPCI cautioned this must not raise technical declines | MediaNama — https://www.medianama.com/2025/06/223-npci-upi-changes-transaction-speed-fraud-prevention/ |
| E7 | RBI TAT, UPI funds transfer, debit without credit | beneficiary bank auto-reverses by T+1; Rs 100/day beyond T+1, credited without a complaint | RBI/2019-20/67 — https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11693 |
| E8 | RBI TAT, UPI merchant payment, no confirmation | auto-reversal within T+5; Rs 100/day beyond T+5 | same |
| E9 | NPCI technical decline (TD) definition | declines due to technical reasons (connectivity, switch unavailability, incorrect message data); incidents counted when >3 lakh declines last >30 min | NPCI — https://www.npci.org.in/statistics/bd-td-and-uptime |
| E10 | Retry storms are common | 22 metastable failures from 11 organisations; retry policy the most common sustaining effect (>50%); ≥4 of 15 major AWS outages in a decade were metastable | Huang et al., OSDI 2022 — https://www.usenix.org/conference/osdi22/presentation/huang-lexiang |
| E11 | Indian gateway routing reality | bandit (Thompson sampling) routing; issues are usually one bank or one mode; shifting traffic too fast overloads other gateways | Cashfree engineering blog (search excerpt) |
| E12 | Retry budget practice | ≤3 attempts per request + ≤10% retry ratio per client; growth ~1.1x instead of ~3x | Google SRE book, Handling Overload (search excerpt) |
| E13 | Drunix | NPCI's Apache-2.0 fork of Hyperledger Fabric 2.5: Lite Peer, Committing Peer, stateless Validation Service, YugabyteDB SQL state, KeyDB transient store | https://github.com/npci/drunix, docs/drunix-arch.md |
| E14 | Citi Token Services | tokenised deposits on a Citi-run private permissioned blockchain; 24/7 near-instant liquidity; instant API-initiated payment status notifications | https://services.citi.com/solutions/citi-token-services |
| E15 | Citi Payment Outlier Detection | ML flags payments that break a client's pattern; client approves/rejects in CitiDirect BE / CitiConnect before release; 90 countries (2019) | Citi press release 2019 (search excerpt) |

Rule: a number that is not in this table, not measured by our own code, and not computed from these by stated arithmetic MUST NOT appear in UI text, README, report or slides.

## 3. What QueueShield is (and is not)

QueueShield is an **operator decision-support and coordination layer** for a real-time payment network. It has two planes:

1. **Off-ledger intelligence plane** (M2, M3, M4, M5): watches every payment event, detects and localises degradation, forecasts lock-in, computes check budgets, and recommends bounded actions that a human approves.
2. **On-ledger coordination plane** (M1, Drunix): holds only what several organisations must agree on — unknown-payment records with signed bank attestations and RBI TAT clocks, network advisories, and operator decisions. Outcomes are **pushed** to subscribers as chaincode events.

| QueueShield is | QueueShield is not |
|---|---|
| A detector and decision aid for operators | An autonomous router or a payment processor |
| A forecaster of whether a degradation becomes self-sustaining *if nothing changes* | A predictor of faults before they begin |
| A shared, signed record for **exceptions** (unknown payments, advisories, decisions) | A ledger for every UPI payment |
| Evaluated in a reactive simulator calibrated to public NPCI statistics | Validated on real bank traffic |
| Built on a local Drunix test network | An NPCI-approved or Citi-integrated system |

## 4. Design principles (every module MUST respect these)

1. **Localise before you act.** Every alert names a segment and a level (PSP, bank, route, switch).
2. **Leading indicators beat success rate.** Latency, near-timeout share, timeouts, retry ratio, pending count and queue growth move before the platform success rate does.
3. **Separate surge from degradation.** A surge raises arrivals with stable latency and a draining queue.
4. **A timeout is unknown, not failure.** Unknown payments are resolved by evidence before any re-attempt.
5. **Safeguards are load.** Status checks, retries and shifted traffic all consume capacity and are budgeted.
6. **Push, don't poll.** Whoever knows the outcome (the bank) attests it once; everyone else subscribes.
7. **Ledger for the exceptions, not the firehose.** Only unknown payments, advisories and decisions are written on-chain.
8. **Right-size the response.** Slow retries first, defer checks, shift traffic last and only gradually, never across a shared bank.
9. **Human in the loop.** The system recommends; a person approves; the approval is recorded on the ledger.
10. **Honest evaluation.** Identical seeds, held-out configurations, a strong NPCI-rule baseline, and negative results reported.

## 5. Actors and organisations

| Actor | In reality | In our build |
|---|---|---|
| Payer PSP | App's PSP bank (e.g. the bank behind a UPI app) | P1, P2, P3 (simulated) |
| Remitter bank | Debits the payer | B1–B5 in the remitter role (simulated); attests via Org1 |
| Beneficiary bank | Credits the payee; auto-reverses under RBI TAT | B1–B5 in the beneficiary role (simulated); attests via Org2 |
| Switch (NPCI-like) | Routes payments; serves Check Transaction Status | Simulated switch with finite status capacity |
| Network authority (NPCI-like) | Issues rules and advisories | Org1 hosts the authority role in the 2-org test network; Org3 is [STRETCH] |
| Sponsor bank (Citi-like role) | Sends corporate payout batches; runs PSP services | Payout traffic in scenario S8; a role, never a claimed integration |
| Operator | Payments ops / SRE on duty | Human in the console; simulated operator in batch |
| Regulator observer | Audits compliance | Read-only console view of TAT breaches and decisions [BUILD] |

## 6. Real-world constants and their simulator analogues

The simulator compresses time so a 10-minute run shows a full incident. Every analogue MUST be labelled "analogue" in UI and report.

| Real constant | Real value | Simulator analogue | Compression |
|---|---|---|---|
| Pay request timeout (OC-214) | 15 s | client timeout 3 000 ms | 5:1 |
| Check Transaction Status response cap | 10 s | status call timeout 2 000 ms | 5:1 |
| First status check delay (OC-215) | 90 s | 10 000 ms | 9:1 |
| Max checks per payment | 3 within 2 h | 3 within 120 000 ms | 60:1 (run-length bound) |
| TAT for UPI debit-without-credit | T+1 day | `tatSeconds` = 120 s (wall clock on ledger, demo) | ~720:1 |
| Compensation | Rs 100/day | reported as count of TAT breaches; no money shown | n/a |

## 7. Scenario and universe catalogue (summary; full parameters in M2 §7)

| ID | Name | Story it tells |
|---|---|---|
| S0 | Normal | Baseline, false-alert rate |
| S1 | Festive-sale surge | Demand ×1.6 with a flash ×2.5; must stay quiet |
| S2 | PSP slowdown | One PSP's service time ×1.6–3.0 |
| S3 | Bank slowdown | One bank's legs ×4–8 on every PSP: the shared-bank failover trap |
| S4 | Retry storm | One PSP loses 50–70% of workers for 40–90 s; metastable lock-in |
| S5 | Surge + slowdown | S1 and S2 overlapping |
| S6 | **April 2025 replay** | One beneficiary bank black-holes 40% of credits for 60 s; status storm at the switch |
| S7 | Silent drift | One route's latency ramps ×1 → ×2.2 over 120 s |
| S8 | Bulk payout burst | Sponsor-bank batch hits a beneficiary bank that is already slow |

| Universe | Clients | Network behaviour | Represents |
|---|---|---|---|
| U0 | naive | No control; checks every 2 s; users retry | Pre-April-2025 behaviour |
| U1 | naive | Textbook failover on success rate | Reactive rule that spreads bank faults |
| U2 | npci_rule | OC-215 timers honoured by every PSP | NPCI's fix — the strong honest baseline |
| U3 | governed | QueueShield recommendations + budgets, no ledger | Intelligence plane alone |
| U4 | ledger_first | QueueShield + Drunix push resolution + advisories | Full system |

## 8. Claims policy (binding on code, UI text, README, report, slides, video)

| Topic | May say | Must not say |
|---|---|---|
| Results | "In our simulator, on held-out configurations, X compared with Y" | "QueueShield prevents UPI outages" |
| Prediction | "Forecasts whether a degradation will lock in if nothing changes" | "Predicts outages before they start" |
| NPCI | "Follows the principle of NPCI's April 2025 circulars in a scaled analogue" | "Implements UPI", "NPCI-approved" |
| Citi | "Same design principle as Citi Token Services' pushed status notifications" | any Citi integration or endorsement |
| Drunix | "Runs on a local Drunix test network with measured latency and throughput" | "Scales to UPI volumes" without measurement |
| Safety | "Duplicate commits are a tested invariant in governed universes" | "Duplicate payments are impossible" |
| Novelty | "Among the public projects we reviewed, none combines these elements" | "Nobody has done this" |
| Data | "All data is synthetic; simulator calibrated to public NPCI statistics" | "Real transaction data" |

Every outcome number on screen carries the label **"simulation"**. Any sentence containing *production, guarantee, prevent, savings, approved, real-time at UPI scale* needs a second human reviewer.

## 9. Glossary

| Term | Meaning |
|---|---|
| Segment | `platform`, a PSP, a bank, a PSP×bank route, or the `switch`; id form `level:psp:bank`, e.g. `route:P1:B3`, `bank:*:B3` |
| Unknown payment | A payment whose attempt timed out with no confirmed outcome |
| Attestation | A signed ledger statement by the bank that owns a leg: DEBIT, CREDIT, FAILURE_REMITTER, FAILURE_BENEFICIARY, REVERSAL |
| RAF | Retry Amplification Factor = retry attempts / fresh attempts |
| Orbit | Payments waiting to retry (retry backlog) |
| Zombie work | Work still served after the client gave up |
| Goodput | Payments completed successfully within the deadline, per second |
| Metastable failure | Degraded state kept alive by a feedback effect after the trigger ends |
| Point of no return | The p_stuck = 0.5 contour on the forecaster's phase plane |
| Advisory | A signed, time-boxed network instruction on the ledger: SLOW_RETRIES, DEFER_CHECKS, DO_NOT_SHIFT, PACE_PAYOUTS |
| Check budget | Per-PSP rate of switch status checks allowed now (token bucket) |
| Arena | The same seed replayed in U0–U4 for paired comparison |
| Common random numbers | Every universe consumes the same random tape, so differences come from policy only |
