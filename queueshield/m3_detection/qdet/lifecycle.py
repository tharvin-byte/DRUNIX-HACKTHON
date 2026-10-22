"""Incident lifecycle (docs/M3_DETECTION.md §7). Ported from the IBM project's qs/core/lifecycle.py.

OPEN -> MITIGATING (first ACTION_APPLIED in scope) -> RECOVERING (3 improving ticks) -> CLOSED (6 clean ticks);
a new WARNING on the same segment within 60 s reopens the same id. Segments warned within 30 s that are
overlap merge, and the localizer's primary names the incident. Guard against the IBM stale-primary bug (a
recovery-tail alert rewritten to an old primary): the pipeline passes the primary only while that primary
segment is itself warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from qdet import segments as S

SEV = {"WARNING": 1, "CRITICAL": 2}


@dataclass
class Incident:
    incident_id: str
    segment_id: str
    opened_ms: int
    severity: str = "WARNING"
    state: str = "OPEN"
    updated_ms: int = 0
    closed_ms: Optional[int] = None
    last_warning_ms: int = 0
    clean: int = 0
    improving: int = 0
    verdict: str = "INSUFFICIENT_EVIDENCE"
    reasons: list = field(default_factory=list)
    confidence: float = 0.0
    p_stuck: Optional[float] = None
    countdown: Optional[float] = None
    features_sha256: str = "0" * 64
    merged: set = field(default_factory=set)


def related(a: str, b: str) -> bool:
    """Overlapping (wildcard-compatible) segments, per the §7 merge rule."""
    return S.overlaps(a, b)


class Lifecycle:
    def __init__(self, cfg) -> None:
        self.cfg = cfg.lifecycle
        self.tick_ms = cfg.tick_ms
        self.incidents: dict = {}
        self._n = 0

    def live(self) -> list:
        return [i for i in self.incidents.values() if i.state != "CLOSED"]

    def open_segments(self) -> set:
        out = set()
        for i in self.live():
            out.add(i.segment_id)
            out |= i.merged
        return out

    def on_warning(self, now: int, segment_id: str, severity: str, primary: Optional[str],
                   force: bool = False) -> tuple:
        """Route one warning. Returns (incident, changed).

        `primary` (the localizer's segment) is used when it relates to the warning segment, or always with
        `force` (network-wide verdicts: platform or switch anchor)."""
        seg = primary if primary and (force or related(segment_id, primary)) else segment_id
        inc = next((i for i in self.live() if (related(i.segment_id, seg) or seg in i.merged)
                    and now - i.last_warning_ms <= self.cfg.merge_s * 1000), None)
        if inc is None:
            inc = next((i for i in self.incidents.values() if i.state == "CLOSED" and i.segment_id == seg
                        and i.closed_ms is not None and now - i.closed_ms <= self.cfg.reopen_s * 1000), None)
            if inc is not None:
                inc.state, inc.closed_ms = "OPEN", None
        changed = False
        if inc is None:
            self._n += 1
            inc = Incident(f"inc-{self._n:04d}", seg, now, severity, updated_ms=now)
            self.incidents[inc.incident_id] = inc
            changed = True
        else:
            if segment_id != inc.segment_id:
                inc.merged.add(segment_id)
            if SEV[severity] > SEV[inc.severity]:
                inc.severity, changed = severity, True
            if inc.state == "RECOVERING":
                inc.state, changed = "MITIGATING", True
        inc.last_warning_ms, inc.clean, inc.improving = now, 0, 0
        return inc, changed

    def on_action_applied(self, now: int, scope_segment: Optional[str]) -> list:
        changed = []
        for i in self.live():
            if i.state == "OPEN" and (scope_segment is None or related(i.segment_id, scope_segment)):
                i.state, i.updated_ms = "MITIGATING", now
                changed.append(i)
        return changed

    def tick(self, now: int, warning_segments: set) -> list:
        """Advance live incidents; a tick is clean when no related segment is warning."""
        changed = []
        for i in self.live():
            if any(related(i.segment_id, s) or s in i.merged for s in warning_segments):
                i.clean = i.improving = 0
                continue
            i.clean += 1
            i.improving += 1
            before = i.state
            if i.state == "MITIGATING" and i.improving >= self.cfg.improving_ticks:
                i.state = "RECOVERING"
            if i.clean >= self.cfg.clean_ticks:
                i.state, i.closed_ms = "CLOSED", now
            if i.state != before:
                i.updated_ms = now
                changed.append(i)
        return changed
