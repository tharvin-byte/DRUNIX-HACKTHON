"""Server-sent events per docs/01_SYSTEM.md §9: monotonic ids, Last-Event-ID replay from a ring buffer
(>= 50 000 messages), `reset` for ids that fell off the ring, `: hb` heartbeat every 5 s.

`publish` is thread-safe so a simulation thread can feed it; the async generator polls the ring.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from typing import AsyncIterator, Optional

RING = 50_000
HEARTBEAT_S = 5.0
POLL_S = 0.05


class SseHub:
    def __init__(self, ring: int = RING) -> None:
        self._ring: deque = deque(maxlen=ring)   # (id, event, json_text)
        self._next = 1
        self._lock = threading.Lock()

    def publish(self, event: str, data: dict) -> int:
        text = json.dumps(data, separators=(",", ":"), allow_nan=False)
        with self._lock:
            i = self._next
            self._next += 1
            self._ring.append((i, event, text))
        return i

    def last_id(self) -> int:
        with self._lock:
            return self._next - 1

    def _since(self, last: int) -> list:
        with self._lock:
            return [m for m in self._ring if m[0] > last]

    def _oldest(self) -> int:
        with self._lock:
            return self._ring[0][0] if self._ring else self._next

    @staticmethod
    def fmt(i: int, event: str, text: str) -> str:
        return f"id: {i}\nevent: {event}\ndata: {text}\n\n"

    async def stream(self, last_event_id: Optional[str] = None,
                     types: Optional[set] = None) -> AsyncIterator[str]:
        try:
            last = int(last_event_id) if last_event_id not in (None, "") else self.last_id()
        except ValueError:
            last = self.last_id()
        if last_event_id not in (None, "") and last + 1 < self._oldest() and self._next > 1:
            yield self.fmt(self.last_id(), "reset", "{}")   # too old: client must re-read GET /v1/state
            last = self.last_id()
        idle = 0.0
        while True:
            sent = False
            for i, ev, text in self._since(last):
                last = i
                if types is None or ev in types:
                    yield self.fmt(i, ev, text)
                    sent = True
            if sent:
                idle = 0.0
            else:
                idle += POLL_S
                if idle >= HEARTBEAT_S:
                    idle = 0.0
                    yield ": hb\n\n"
            await asyncio.sleep(POLL_S)
