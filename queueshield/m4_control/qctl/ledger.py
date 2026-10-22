"""Ledger writes for decisions and advisories (docs/M4_CONTROL.md §6 steps 3-5).

HttpLedger talks to the M1 gateway (live Drunix or the M1 mock: same routes). ModelLedger is the batch stand-in:
synthetic tx ids and the ledger events M1 would emit, returned to M2 in the lockstep response.
A ledger failure never blocks actions: the caller queues the write and retries (see controller.retry_ledger).
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone

import httpx


class LedgerUnavailable(Exception):
    pass


class HttpLedger:
    def __init__(self, url: str, cfg) -> None:
        self.url = url.rstrip("/")
        self.cfg = cfg
        self.http = httpx.Client(timeout=10.0, headers={"X-QS-Key": os.environ.get("QS_API_KEY", "")})

    def write(self, kind: str, body: dict) -> dict:
        """kind: 'decisions' | 'advisories'. Returns the gateway body ({..., "tx_id"})."""
        last = None
        for i in range(self.cfg.c.ledger.retries):
            try:
                r = self.http.post(f"{self.url}/v1/{kind}", json=body)
                if r.status_code in (200, 201):
                    return r.json()
                if r.status_code == 409:                  # already recorded (idempotent retry)
                    return {"tx_id": None, "conflict": True}
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            time.sleep(self.cfg.c.ledger.backoff_s[min(i, len(self.cfg.c.ledger.backoff_s) - 1)])
        raise LedgerUnavailable(last or "unknown")

    def revoke(self, adv_id: str, reason: str) -> dict:
        r = self.http.request("DELETE", f"{self.url}/v1/advisories/{adv_id}", json={"reason": reason})
        if r.status_code != 200:
            raise LedgerUnavailable(f"HTTP {r.status_code}")
        return r.json()


class ModelLedger:
    """Batch: no network. Produces the ledger_event records M1 would emit (one per write)."""

    def __init__(self) -> None:
        self.block = 0
        self.events: list = []

    def write(self, kind: str, body: dict) -> dict:
        self.block += 1
        tx = hashlib.sha256(f"{kind}:{body['id']}".encode()).hexdigest()[:16]
        name = "DecisionRecorded" if kind == "decisions" else "AdvisoryIssued"
        self.events.append({"event_id": f"{tx}:{name}", "block_number": self.block, "tx_id": tx,
                            "chaincode": "queueshield", "name": name, "payload": body,
                            "received_wall_iso": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                            "mock": True})
        return {"tx_id": tx, "block_number": self.block}

    def revoke(self, adv_id: str, reason: str) -> dict:
        return {"tx_id": None}

    def drain(self) -> list:
        ev, self.events = self.events, []
        return ev
