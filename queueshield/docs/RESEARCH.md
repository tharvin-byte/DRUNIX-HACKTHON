# Research notes (2026-10-20)

What we checked outside the repo to decide what to build next, and what it means for each module. Each item says how
solid it is: **read** = the page itself was opened; **excerpt** = only search-result text was seen (verify before
quoting on a slide). Numbers used in UI/deck text must still follow `00_PRODUCT.md` §2 (evidence table) and §8 (claims).

## 1. The hackathon

| Fact | Status | Source |
|---|---|---|
| DRUNIX Hackathon 2026 by NPCI × Citi, launched at Global Fintech Fest 2026; registration 10–30 Sep 2026; selected teams may get NPCI API / infrastructure access | excerpt | [Internshala listing](https://internshala.com/competitions/drunix-hackathon-2026-by-npci-x-citi/) |
| Timeline: **pitch submission 25 Oct 2026, prototype build 10–22 Nov, grand finale 4 Dec** | read (another team's README) | [Project Axis](https://github.com/ferroflux/project-axis) |
| Official problem-statement text | **not found publicly** — check the dashboard (spec Day-0 checklist) | — |

**Implication:** P0 = pitchable prototype by Sat 24 Oct (submit Sun 25 with buffer); NPCI API access may arrive for the
build phase — keep "next step: sandbox pilot with NPCI APIs" in the close.

## 2. NPCI rules our simulator and policies model

| Rule | Status | Source |
|---|---|---|
| Check Transaction Status: first check ≥ 90 s after the transaction; a later communication allows 45–60 s; at most 3 checks within 2 h | excerpt (matches spec E5) | [MediaNama Apr 2025](https://www.medianama.com/2025/04/223-npci-new-guidelines-upi-outage/), [Inc42](https://inc42.com/buzz/npci-brings-in-additional-measures-to-curb-upi-outage) |
| PSPs must **stop further status checks after certain errors** (e.g. connection timeout, no route to host) | excerpt | same |
| Check-status response target cut 30 s → 10 s from 16 Jun 2025 | excerpt (matches E6) | [MediaNama Jun 2025](https://www.medianama.com/2025/06/223-npci-upi-changes-transaction-speed-fraud-prevention/) |
| "Peak hours" 10:00–13:00 and 17:00–21:30; members should restrict non-customer-initiated APIs at peak; balance enquiry capped at 50/app/customer/day | excerpt | [MediaNama May 2025](https://www.medianama.com/2025/05/223-npci-banks-balance-upi-transaction-guidelines/), [BOOM](https://www.boomlive.in/web-stories/news/npci-rolls-out-new-limits-on-upi-balance-checks-among-other-guidelines-2463) |
| No newer (2026) circular on status checks found | excerpt | search on 2026-10-20 |

**Implications:** M2-T04 (stop codes are in the spec but not yet in the code), M2 enhancement "peak-hour demand + U2b
45–60 s variant", M4 policy text can cite "follows the principle of OC-215" (claims-safe wording in `00_PRODUCT.md` §8).

## 3. Drunix as published

| Fact | Status | Source |
|---|---|---|
| Apache-2.0 fork of Hyperledger Fabric, backward compatible with HLF 2.5.x; segregated peers, SQL state DB, stateless validation service | read | [npci/drunix](https://github.com/npci/drunix) |
| On 2026-10-20 the repo showed **no published release**, 17 commits, 9 open issues, 7 open PRs | read | same |
| Lite Peer = stateless endorser (simulation only) that relays CommitStatus to the Committing Peer; CP validates via the round-robin Validation Service and commits to the state DB (YugabyteDB supported); private data in the per-org KeyDB transient store; LPs and VSs scale horizontally | read | [docs/drunix-arch.md](https://github.com/npci/drunix/blob/main/docs/drunix-arch.md) |
| The architecture doc does **not** cover client chaincode events, range queries on the SQL state DB, or the Gateway client | read | same |

**Implication:** every `[VERIFY]` in `m1_ledger/SPEC.md` §1 stays open until someone runs the network (M1-T01). Budget
two days for bring-up; keep the M1 mock as the team's default until then.

## 4. Competitors (Drunix hackathon entries named in the spec)

| Project | What it is | Status | What it means for us |
|---|---|---|---|
| **Pulse** ([cs25b1074-stack/citi](https://github.com/cs25b1074-stack/citi)) | Per-bank signed payment transitions (DEBITED/CREDITED/REVERSED/DECLINED) on Fabric/Drunix, SLA deadline → STUCK visible to a regulator org (Org3), WebSocket push with `lastSeq` replay, React UI with a "Money is with …" custody banner, merchant POS and regulator desk; self-reported ~90–95 % fewer status requests | read — closest competitor | Our single-payment ledger story overlaps. **Lead with the network level**: storm detection, localisation, lock-in forecast, check budgets, signed advisories and decisions, paired-seed arena with an NPCI-rule baseline. Borrow: custody chip, regulator view, drop-and-replay demo |
| **Tally** ([sharannya310106/tally-drunix](https://github.com/sharannya310106/tally-drunix)) | Proposal only: shared event history, conflicting-status detection, deadlines, idempotency, audit trail | read | No implementation; same single-payment space |
| **Project Axis** ([ferroflux/project-axis](https://github.com/ferroflux/project-axis)) | Proposal: cross-border tokenised deposits, compliance on-chain, atomic FX swap, maker-checker; 3 orgs incl. regulator | read | Different problem; their maker-checker idea fits our SHIFT_TRAFFIC approval (M4 enhancement) |

Positioning sentence (claims-safe): "Among the public Drunix projects we reviewed, QueueShield is the one that treats
unknown payments as a network-level load problem: it detects the tipping segment, forecasts lock-in, budgets
verification, and records the operator's decisions on the same ledger."

## 5. Research on metastable failures and overload control

| Work | What it says | Status | Use |
|---|---|---|---|
| Huang et al., *Metastable Failures in the Wild*, OSDI 2022 | 22 metastable failures; retry policy the most common sustaining effect | spec E10 | already in the evidence table |
| Isaacs et al., *Analyzing Metastable Failures*, HotOS 2025 (AWS) | combine probabilistic queueing models, discrete-event simulators and emulators to find where systems are vulnerable | excerpt ([PDF](https://cdn.amazon.science/a4/ff/894a054e485f9d80936e796fbd07/analyzing-metastable-failures.pdf), [page](https://www.amazon.science/publications/analyzing-metastable-failures)) | cites our exact method (model + simulator); M2-T01 calibration, M3 analytic lock-in check, deck "why trust the simulator" |
| Farahbakhsh et al., *Modeling Metastability*, HotNets 2025 | a precise definition of metastability and a general mechanism | excerpt ([PDF](https://conferences.sigcomm.org/hotnets/2025/papers/hotnets25-final415.pdf)) | use its definition to decide "metastable" vs "congestion" wording (M2 §8.6) |
| *Formal Analysis of Metastable Failures in Software Systems*, arXiv 2510.03551 | abstract CTMC models of request-response systems focused on retry storms | excerpt ([arXiv](https://arxiv.org/abs/2510.03551)) | back-of-envelope bistability check for M2-T01; explainable second forecaster for M3 |
| Retry budgets (Google SRE: ≤ 3 attempts per request, ≤ 10 % retry ratio) | retries capped as a fraction of base load | spec E12 | M2/M4 enhancement "retry budget" |
| Adaptive LIFO + CoDel (Facebook pattern; HBase `AdaptiveLifoCoDelCallQueue`) | FIFO normally, LIFO + drop of stale work under overload, because waiting clients give up and retry | excerpt ([HBase API docs](https://hbase.apache.org/devapidocs/org/apache/hadoop/hbase/ipc/AdaptiveLifoCoDelCallQueue.html)) | candidate new action (needs a contract proposal); complements SHED_EXPIRED and PRIORITIZE_FRESH |
| *Retry Amplification in Distributed Systems*, arXiv 2608.25403 | retry budgets adjusted by observed failure rate; cut immediately on upstream overload signals | excerpt only ([arXiv](https://arxiv.org/pdf/2608.25403)) | read before citing |

## 6. What was *not* done
- No hands-on test of Drunix (no Docker/Go on the dev machine).
- Spec evidence E1/E2 (UPI volumes) and E7–E9, E14, E15 were not re-checked on 2026-10-20.
- Excerpt-level items above must be opened and read before they appear on a slide.
