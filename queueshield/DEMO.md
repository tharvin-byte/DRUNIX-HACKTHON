# QueueShield — 4-Minute Stage Demo Script & Runbook

> **Claims guardrail**: Every outcome figure shown in the console is from our simulator and is explicitly labelled **simulation**. The Drunix test network and `queueshield` chaincode are real when running in `live` ledger mode.

---

## Quick Start

### Option A — Full Stack Demo (M1–M5 live on localhost)
```bash
bash scripts/demo.sh
```
Starts M1 (`:8004`), M2 (`:8001`), M3 (`:8002`), M4 (`:8003`), and M5 (`:8000`).

### Option B — Stage-Safe Deterministic Replay (Zero Backend Dependencies)
Open the console with query parameters:
- `http://localhost:8000/?mode=replay&rec=s6_u4&speed=1`
- `http://localhost:8000/?mode=replay&rec=s6_u0&speed=4`

---

## 4-Minute Stage Narrative (`docs/90_PLAN_EVAL_RISKS.md` §4)

| Time | View | Action | Key Takeaway |
|---|---|---|---|
| **0:00–0:20** | **Live tab** (`S0 Normal`) | Show Header badges & HeatMap | Baseline traffic across 3 PSPs × 5 banks (`15` route segments). Zero false alerts. |
| **0:20–0:40** | **DrunixPanel** | Point to Org1MSP / Org2MSP LP·CP·VS chips & block height | Shared permissioned ledger records unknown payment state, TAT breaches, active advisories, and operator decisions. |
| **0:40–1:00** | **Live tab** (`S1 Festive surge`) | Click **S1 Festive surge** | Volume doubles uniformly; multi-signal D3 detector stays quiet (`0` false positives). |
| **1:00–1:45** | **Live tab** (`S3 Bank slowdown`) | Click **S3 Bank slowdown** → Click **Approve selected (S)** | Bank `B1`/`B2` column lights up across all PSPs (`verdict: BANK_SIDE`). Safety gate **blocks** `SHIFT_TRAFFIC` (`🔒 payee bank is fixed`) and issues a `DO_NOT_SHIFT` advisory on Drunix. `DecisionLog` transitions from `recording on ledger…` to `tx <hash> · block <n>`. |
| **1:45–2:45** | **April-2025 split replay** tab | Click **April-2025 split replay** → scrub or press **Play** | Side-by-side comparison of `S6 · seed 1`: `U0 Unprotected` floods the switch with status checks (`100%` switch util, `3.8×` slowdown), while `U4 QueueShield + Drunix` caps status checks inside the `170/s` budget and resolves unknowns via Drunix ledger push. |
| **2:45–3:30** | **Live tab** (`S4 Retry storm`) & **Arena** tab | Click **S4 Retry storm** → inspect **DetectorRace** & **CascadeMap** → switch to **Arena** tab | `DetectorRace` shows `D3` alerting ahead of `D0`/`D1`/`D2`. `CascadeMap` shows `P1` trajectory approaching the `p_stuck = 0.5` contour (`point of no return`). In **Arena**, `U2` (tuned static baseline) is always shown alongside `U0` and `U4` across 5 seeds (`simulation, 5 seeds, preliminary`), plus the operator approval latency sweep. |
| **3:30–4:00** | **About & claims** tab | Click **About & claims** | Review what is real (Drunix network & chaincode) vs simulated (synthetic payment traffic & outcomes). |
