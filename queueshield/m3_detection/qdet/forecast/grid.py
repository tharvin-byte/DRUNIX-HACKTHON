"""Explainable point-of-no-return grid (docs/M3_DETECTION.md §6.4). Ported from the IBM project's forecast/grid.py.

20 x 20 bins over delay_frac in [0, delay_max] x orbit_frac in [0, orbit_max]; cell p = (stuck + 1) / (n + 2)
(Beta(1,1)); optional monotone envelope (running max along both axes). Inference is two index lookups.
The export matches `GET /v1/forecaster/grid` (contracts/CONTRACTS.md §2).
"""
from __future__ import annotations

import numpy as np


class StuckGrid:
    def __init__(self, delay_max: float = 2.0, orbit_max: float = 3.0, n: int = 20, version: str = "grid-v1") -> None:
        self.n, self.delay_max, self.orbit_max, self.version = n, delay_max, orbit_max, version
        self.p = np.full((n, n), 0.5)
        self.trained = False

    def _idx(self, delay, orbit) -> tuple:
        i = np.clip((np.asarray(delay, float) / self.delay_max * self.n).astype(int), 0, self.n - 1)
        j = np.clip((np.asarray(orbit, float) / self.orbit_max * self.n).astype(int), 0, self.n - 1)
        return i, j

    def fit(self, delay, orbit, stuck, weights=None, monotone: bool = True) -> "StuckGrid":
        stuck = np.asarray(stuck, float)
        w = np.ones_like(stuck) if weights is None else np.asarray(weights, float)
        i, j = self._idx(delay, orbit)
        pos, tot = np.zeros((self.n, self.n)), np.zeros((self.n, self.n))
        np.add.at(pos, (i, j), w * stuck)
        np.add.at(tot, (i, j), w)
        self.p = (pos + 1.0) / (tot + 2.0)
        if monotone:
            self.p = np.maximum.accumulate(np.maximum.accumulate(self.p, axis=0), axis=1)
        self.trained = True
        return self

    def predict(self, delay, orbit) -> np.ndarray:
        i, j = self._idx(np.atleast_1d(delay), np.atleast_1d(orbit))
        return self.p[i, j]

    def edges(self) -> tuple:
        return np.linspace(0, self.delay_max, self.n + 1), np.linspace(0, self.orbit_max, self.n + 1)

    def contour(self, level: float = 0.5) -> list:
        """Polyline of the first delay bin edge where p >= level, per orbit column ([x=delay, y=orbit])."""
        de, oe = self.edges()
        pts = []
        for j in range(self.n):
            hit = np.nonzero(self.p[:, j] >= level)[0]
            if hit.size:
                pts.append([round(float(de[hit[0]]), 4), round(float((oe[j] + oe[j + 1]) / 2), 4)])
        return pts

    def to_dict(self) -> dict:
        de, oe = self.edges()
        return {"version": self.version, "delay_bins": [round(float(x), 6) for x in de],
                "orbit_bins": [round(float(x), 6) for x in oe], "p": np.round(self.p, 6).tolist(),
                "contour_0_5": self.contour(0.5)}

    @classmethod
    def from_dict(cls, d: dict) -> "StuckGrid":
        de, oe, p = d["delay_bins"], d["orbit_bins"], np.asarray(d["p"], float)
        g = cls(float(de[-1]), float(oe[-1]), p.shape[0], d.get("version", "grid-v1"))
        g.p, g.trained = p, True
        return g
