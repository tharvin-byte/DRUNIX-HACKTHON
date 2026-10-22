"""Comparison detectors D0, D1, D2 (§4.2). Ported from the IBM project's threshold.py / adaptive.py.

D0 mirrors a platform dashboard; D1 is a per-segment fixed threshold; D2 is a per-segment CUSUM on the
baseline z-scores of timeout_ratio and latency_ratio. Knobs come from config and are tuned to the matched
false-alert budget before any test run.
"""
from __future__ import annotations

import math

import numpy as np

from qdet import segments as S
from qdet.features import FI, FeatureTick


class D0:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.run = 0

    def update(self, ft: FeatureTick) -> bool:
        x = ft.F[S.PLATFORM, FI["success_ratio"]]
        self.run = self.run + 1 if (not math.isnan(x) and x < self.cfg.d0.theta0) else 0
        return self.run >= self.cfg.d0.ticks


class D1:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.run = np.zeros(S.N, dtype=int)

    def update(self, ft: FeatureTick) -> np.ndarray:
        c = self.cfg.d1
        to, sr = ft.F[:, FI["timeout_ratio"]], ft.F[:, FI["success_ratio"]]
        with np.errstate(invalid="ignore"):
            bad = (np.nan_to_num(to) > c.timeout_a * c.sensitivity) | (np.nan_to_num(sr, nan=1.0) < c.success_b / c.sensitivity)
        bad &= ft.eligible
        self.run = np.where(bad, self.run + 1, 0)
        return self.run >= c.ticks


class D2:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.s = np.zeros((S.N, 2))

    def update(self, ft: FeatureTick) -> np.ndarray:
        c = self.cfg.d2
        z = np.stack([ft.Z[:, FI["timeout_ratio"]], ft.Z[:, FI["latency_ratio"]]], axis=1)
        z = np.nan_to_num(z)
        self.s = np.maximum(0.0, self.s + z - c.k)
        self.s[~ft.eligible] = 0.0
        return (self.s >= c.h).any(axis=1) & ft.eligible
