"""Ledger bridge (docs/M2_SIMULATOR.md §5, docs/01_SYSTEM.md §5).

- model: implemented inside engine.py (`_h_ledger_open`, `_truth_changed`, `_h_ledger_resolve`), lognormal submit
  latency + event lag from config `ledger_model` (replace with `data/ledger_bench.json` once M1 measures it).
- live / mock: TODO(M2, Day 3). Open unknowns with `POST LEDGER_URL/v1/payments` (ledger_open_request), attest legs
  with `POST /v1/payments/{txnRef}/attest` as the owning bank, subscribe to `GET /v1/stream` and resolve a payment
  only on a terminal `PaymentUpdated` (test S-11). Never fake a ledger event: if the gateway is down fall back to
  `model`, report health `degraded` (docs/01_SYSTEM.md §10).
"""
from __future__ import annotations

SUPPORTED_MODES = ("model",)


def mode_supported(mode: str) -> bool:
    return mode in SUPPORTED_MODES
