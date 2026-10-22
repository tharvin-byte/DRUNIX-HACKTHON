"""Identifier formats (docs/01_SYSTEM.md §7). Adapted from the IBM project's qs/ids.py."""
from __future__ import annotations

import hashlib


def run_id(scenario: str, seed: int, universe: str, suffix: str | None = None) -> str:
    return f"r-{scenario}-{seed}-{universe}" + (f"-{suffix}" if suffix else "")


def payment_id(n: int) -> str:
    return f"p-{n:07d}"


def attempt_id(pid: str, k: int) -> str:
    return f"{pid}-a{k}"


def idempotency_key(n: int) -> str:
    return f"ik-{n:07d}"


def txn_ref(run: str, pid: str) -> str:
    return f"{run}:{pid}"


def idem_key_hash(key: str, run: str) -> str:
    return "sha256:" + hashlib.sha256((key + run).encode()).hexdigest()


class EventIds:
    def __init__(self, run: str) -> None:
        self.run = run
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"{self.run}-{self.n:08d}"
