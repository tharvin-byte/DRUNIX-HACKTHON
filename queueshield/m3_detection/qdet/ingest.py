"""Ingest: schema validation, dedupe (LRU of event ids) and watermark ordering (docs/M3_DETECTION.md §1).

Ported from the IBM project's qs/core/ingest.py and dedupe.py. Events are held until the watermark (max sim_ms
seen minus watermark_ms) passes them so handlers see an ordered stream; later events are delivered with late=True.
"""
from __future__ import annotations

import heapq
from collections import OrderedDict
from typing import Callable

from qdet import contracts


class DedupeLRU:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._d: OrderedDict = OrderedDict()

    def seen_before(self, key: str) -> bool:
        if key in self._d:
            self._d.move_to_end(key)
            return True
        self._d[key] = None
        if len(self._d) > self.capacity:
            self._d.popitem(last=False)
        return False


class Ingestor:
    def __init__(self, handler: Callable[[dict, bool], None], dedupe_capacity: int, watermark_ms: int,
                 validate: bool = True) -> None:
        self.handler = handler
        self.dedupe = DedupeLRU(dedupe_capacity)
        self.watermark_ms = watermark_ms
        self.validate = validate
        self.max_ms = -1
        self._heap: list = []
        self._n = 0
        self.metrics = {"accepted": 0, "duplicates": 0, "rejected": 0, "late": 0}

    def ingest(self, events) -> None:
        for e in events:
            if self.validate and not contracts.accept("payment_event", e):
                self.metrics["rejected"] += 1
                continue
            if self.dedupe.seen_before(e["event_id"]):
                self.metrics["duplicates"] += 1
                continue
            self.metrics["accepted"] += 1
            t = e["sim_ms"]
            if self.max_ms >= 0 and t < self.max_ms - self.watermark_ms:
                self.metrics["late"] += 1
                self.handler(e, True)
                continue
            self.max_ms = max(self.max_ms, t)
            self._n += 1
            heapq.heappush(self._heap, (t, self._n, e))
        self.release_until(self.max_ms - self.watermark_ms)

    def release_until(self, t_ms: int) -> int:
        n = 0
        while self._heap and self._heap[0][0] <= t_ms:
            _, _, e = heapq.heappop(self._heap)
            self.handler(e, False)
            n += 1
        return n
