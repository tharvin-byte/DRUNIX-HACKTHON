"""D3: rule signals, surge gate, rule score, persistence, severity, confidence and reasons (§4.3).

Ported from the IBM project's qs/core/detectors/{rules,persistence}.py. The [PITCH] score is the rule score
(signals/6 through a fixed logistic); the IBM confirmation set showed rules-only beat rules+IsolationForest on
false alerts, so the [BUILD] IsolationForest is not wired yet (iforest.py is a placeholder).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from qdet import segments as S
from qdet.features import FI, FeatureTick

SIGNALS = ("lat", "to", "near_to", "q", "raf", "rej")
# reason code -> (feature, sign); top features by |z| become reasons (supporting evidence, not proof of cause)
REASONS = (("TIMEOUT_UP", "timeout_ratio"), ("NEAR_TIMEOUT_UP", "near_timeout_ratio"),
           ("LATENCY_UP", "latency_ratio"), ("RAF_UP", "raf"), ("QUEUE_GROWING", "queue_delay_est_ms"),
           ("REJECTS_UP", "reject_ratio"), ("PENDING_BACKLOG", "pending_frac"),
           ("SWITCH_STATUS_SATURATED", "switch_status_util"), ("LEDGER_UNRESOLVED_UP", "ledger_unresolved"))


def _ok(x: float) -> bool:
    return x is not None and not math.isnan(x)


def signals(f: np.ndarray, z: np.ndarray, b: np.ndarray, sp: np.ndarray, cfg) -> dict:
    """Six boolean signals for one segment row (f features, z scores, b baseline means, sp spreads)."""
    d = cfg.d3
    g = lambda arr, n: arr[FI[n]]       # noqa: E731
    out = dict.fromkeys(SIGNALS, False)
    zl, lr = g(z, "latency_ratio"), g(f, "latency_ratio")
    out["lat"] = _ok(zl) and zl >= d.z_lat and _ok(lr) and lr >= d.lat_min_ratio

    def above(name: str, k: float, abs_min: float) -> bool:
        x, m, s = g(f, name), g(b, name), g(sp, name)
        return _ok(x) and _ok(m) and x >= m + k * s and x >= abs_min
    out["to"] = above("timeout_ratio", d.to_k_spread, d.to_abs)
    out["near_to"] = above("near_timeout_ratio", d.near_to_k_spread, d.near_to_abs)
    out["rej"] = above("reject_ratio", d.rej_k_spread, d.rej_abs)
    qg, qd, qb = g(f, "queue_growth"), g(f, "queue_delay_est_ms"), g(b, "queue_delay_est_ms")
    out["q"] = (_ok(qg) and qg > d.queue_growth_eps and _ok(qd) and _ok(qb)
                and qd >= d.q_delay_mult * qb and qd - qb >= d.q_min_delay_ms)
    rf, rb = g(f, "raf"), g(b, "raf")
    out["raf"] = _ok(rf) and _ok(rb) and rf >= d.raf_mult * rb
    return out


def rule_score(n_signals: int, cfg) -> float:
    d = cfg.d3
    return 1.0 / (1.0 + math.exp(-d.logistic_k * (n_signals / len(SIGNALS) - d.logistic_x0)))


def reasons(f: np.ndarray, z: np.ndarray, b: np.ndarray, top: int) -> list:
    ranked = []
    for code, feat in REASONS:
        zv = z[FI[feat]]
        if _ok(zv) and zv > 0:
            ranked.append((abs(zv), code, feat))
    out = []
    for _, code, feat in sorted(ranked, reverse=True)[:top]:
        r = {"code": code, "z": round(float(z[FI[feat]]), 3)}
        if _ok(f[FI[feat]]):
            r["observed"] = round(float(f[FI[feat]]), 6)
        if _ok(b[FI[feat]]):
            r["baseline"] = round(float(b[FI[feat]]), 6)
        out.append(r)
    return out


@dataclass
class SegResult:
    signals: dict
    n_signals: int
    score: float
    surge: bool
    warning: bool
    new_warning: bool
    persistence_fraction: float
    reasons: list = field(default_factory=list)
    confidence: float = 0.0


class D3:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        d = cfg.d3
        self._hits = [deque(maxlen=d.persistence_n) for _ in range(S.N)]
        self._fast = np.zeros(S.N, dtype=int)
        self._surge_q = np.zeros(S.N, dtype=int)      # consecutive ticks with queue not growing
        self.active = np.zeros(S.N, dtype=bool)

    def update(self, ft: FeatureTick) -> list:
        d = self.cfg.d3
        out = []
        for i in range(S.N):
            f, z, b, sp = ft.F[i], ft.Z[i], ft.B[i], ft.spread[i]
            if not ft.eligible[i]:
                self._hits[i].clear()
                self.active[i] = False
                out.append(SegResult(dict.fromkeys(SIGNALS, False), 0, 0.0, False, False, False, 0.0))
                continue
            sig = signals(f, z, b, sp, self.cfg)
            n = sum(sig.values())
            qg = f[FI["queue_growth"]]
            self._surge_q[i] = self._surge_q[i] + 1 if not (_ok(qg) and qg > d.queue_growth_eps) else 0
            za = z[FI["arrival_rate"]]
            surge = (_ok(za) and za >= d.surge_z and n <= d.surge_max_signals and self._surge_q[i] >= d.surge_ticks)
            score = rule_score(n, self.cfg)
            hit = score >= d.tau and n >= d.min_signals and not surge
            self._hits[i].append(hit)
            persisted = sum(self._hits[i]) >= d.persistence_k
            self._fast[i] = self._fast[i] + 1 if (score >= d.fast_score and n >= d.fast_signals) else 0
            warn = (persisted or self._fast[i] >= d.fast_ticks) and not surge
            new = warn and not self.active[i]
            self.active[i] = warn
            frac = sum(self._hits[i]) / d.persistence_n
            arr = f[FI["arrival_rate"]]
            samples = 0.0 if not _ok(arr) else arr * self.cfg.windows.short_s
            conf = (0.4 * score + 0.3 * n / len(SIGNALS) + 0.2 * frac
                    + 0.1 * min(1.0, samples / d.confidence_samples))
            out.append(SegResult(sig, n, score, bool(surge), bool(warn), bool(new), frac,
                                 reasons(f, z, b, d.reasons_top) if warn else [], round(min(1.0, conf), 4)))
        return out
