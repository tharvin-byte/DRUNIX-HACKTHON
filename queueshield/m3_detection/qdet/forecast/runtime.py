"""Cascade Forecaster runtime (docs/M3_DETECTION.md §6.5): per-PSP p_stuck, EMA, state, countdown.

It forecasts whether the PSP's backlog locks in *if nothing changes*; it never triggers actions. Without a trained
grid (data/models/forecaster_grid.json) p_stuck is null and severity never escalates on the forecast.
"""
from __future__ import annotations

import json
import math
import os
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

from qdet import segments as S
from qdet.features import FI, FeatureTick
from qdet.forecast.grid import StuckGrid


def model_dir() -> Path:
    return Path(os.environ.get("MODEL_DIR", Path(__file__).resolve().parents[3] / "data" / "models"))


def load_grid(cfg) -> Optional[StuckGrid]:
    f = model_dir() / cfg.forecaster.grid_file
    if not f.is_file():
        return None
    return StuckGrid.from_dict(json.loads(f.read_text(encoding="utf-8")))


def phase_point(ft: FeatureTick, p: int, client_timeout_ms: float) -> Optional[tuple]:
    """(delay_frac, orbit_frac) for PSP p, or None without the information to compute it."""
    i = S.PSP0 + p
    qd, orbit = ft.F[i, FI["queue_delay_est_ms"]], ft.F[i, FI["orbit_proxy"]]
    workers, svc = ft.workers[p], ft.B[i, FI["p50_ms"]]
    if math.isnan(qd) or math.isnan(orbit) or math.isnan(workers) or math.isnan(svc) or svc <= 0:
        return None
    cap_per_s = workers / (svc / 1000.0)
    return qd / client_timeout_ms, (orbit / cap_per_s if cap_per_s > 0 else 0.0)


class ForecastRuntime:
    def __init__(self, cfg, grid: Optional[StuckGrid]) -> None:
        self.cfg, self.grid = cfg, grid
        self.ema = np.full(S.NP, np.nan)
        self.hist = [deque(maxlen=cfg.forecaster.countdown_ticks) for _ in range(S.NP)]

    def update(self, ft: FeatureTick, client_timeout_ms: float) -> list:
        """Per PSP: dict(p_stuck, state, phase_point, countdown_s_estimate)."""
        fc, out = self.cfg.forecaster, []
        for p in range(S.NP):
            pp = phase_point(ft, p, client_timeout_ms)
            if pp is not None:
                self.hist[p].append(pp[0])
            if self.grid is None or pp is None:
                out.append({"p_stuck": None, "state": None,
                            "phase_point": None if pp is None else {"delay_frac": round(pp[0], 4),
                                                                    "orbit_frac": round(pp[1], 4)},
                            "countdown_s_estimate": None})
                continue
            raw = float(self.grid.predict(pp[0], pp[1])[0])
            self.ema[p] = raw if np.isnan(self.ema[p]) else fc.ema * raw + (1 - fc.ema) * self.ema[p]
            ps = float(self.ema[p])
            state = "CRITICAL" if ps >= fc.critical else "WATCH" if ps >= fc.watch else "CALM"
            out.append({"p_stuck": round(ps, 4), "state": state,
                        "phase_point": {"delay_frac": round(pp[0], 4), "orbit_frac": round(pp[1], 4)},
                        "countdown_s_estimate": self._countdown(p) if state != "CALM" else None})
        return out

    def _countdown(self, p: int) -> Optional[float]:
        """Rough estimate: linear extrapolation of delay_frac over the last ticks to 1.0."""
        h = list(self.hist[p])
        if len(h) < 2:
            return None
        slope = (h[-1] - h[0]) / ((len(h) - 1) * self.cfg.tick_ms / 1000.0)
        if h[-1] >= 1.0:
            return 0.0
        if slope <= 0:
            return None
        return round((1.0 - h[-1]) / slope, 1)
