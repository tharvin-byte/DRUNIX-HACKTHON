"""Per-segment, per-feature EWMA mean / mean-absolute-deviation baselines with a freeze rule (§4.1).

Ported from the IBM project's qs/core/baselines.py; spread floors now come from config.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


class Baselines:
    def __init__(self, features: list, n_segments: int, alpha: float, warm_ticks: int, z_clip: float,
                 spread_floor: dict) -> None:
        self.features = list(features)
        self.alpha, self.warm_ticks, self.z_clip = alpha, warm_ticks, z_clip
        shape = (n_segments, len(self.features))
        self.mean = np.zeros(shape)
        self.spread = np.zeros(shape)
        self.n = np.zeros(shape, dtype=np.int64)
        self.ticks = np.zeros(n_segments, dtype=np.int64)
        self.frozen = np.zeros(n_segments, dtype=bool)
        self.floor = np.array([spread_floor.get(f, 0.01) for f in self.features])

    def col(self, name: str) -> int:
        return self.features.index(name)

    def warming_up(self) -> np.ndarray:
        return self.ticks < self.warm_ticks

    def base(self) -> np.ndarray:
        return np.where(self.n > 0, self.mean, np.nan)

    def eff_spread(self) -> np.ndarray:
        return np.maximum(self.spread, self.floor)

    def z(self, x: np.ndarray) -> np.ndarray:
        """Clipped deviation score; NaN where x or the baseline is missing (NaN is never zero, pitfall 1)."""
        with np.errstate(invalid="ignore", divide="ignore"):
            z = (x - self.mean) / self.eff_spread()
        z = np.clip(z, -self.z_clip, self.z_clip)
        z[(self.n == 0) | np.isnan(x)] = np.nan
        return z

    def update(self, x: np.ndarray, rows: np.ndarray) -> None:
        """Fold this tick into the baselines for rows with data that are not frozen."""
        rows = rows & ~self.frozen
        ok = rows[:, None] & ~np.isnan(x)
        self.n[ok] += 1
        a = np.maximum(self.alpha, 1.0 / np.maximum(self.n, 1))     # cumulative mean while warming up
        xv = np.where(ok, x, 0.0)
        dev = np.where(self.n <= 1, 0.0, np.abs(xv - self.mean))
        self.mean = np.where(ok, self.mean + a * (xv - self.mean), self.mean)
        self.spread = np.where(ok, self.spread + a * (dev - self.spread), self.spread)
        self.ticks[rows] += 1

    def set_frozen(self, rows: Optional[np.ndarray]) -> None:
        self.frozen = np.zeros_like(self.frozen) if rows is None else rows.astype(bool)
