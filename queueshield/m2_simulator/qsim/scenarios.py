"""Scenarios S0-S8 and ground truth (docs/M2_SIMULATOR.md §7). Adapted from the IBM project's qs/sim/scenarios.py.

A *configuration* is one draw of scenario parameters from the ranges in config/scenarios.yaml, made with an RNG
seeded by (seed, scenario) and kept apart from the random tape. Ground truth never enters the event stream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from qsim.config import SimConfig


@dataclass
class Modifier:
    """A scheduled fault; value ramps linearly from v0 at start_ms to v1 at end_ms.

    kind: psp_service (psp), capacity (psp, value = fraction of workers kept), bank_latency (bank, both legs),
          route_latency (psp + bank), credit_hold (bank; v0 = held fraction, resolve_ms = release time).
    """
    kind: str
    start_ms: int
    end_ms: int
    v0: float = 1.0
    v1: Optional[float] = None
    psp: Optional[str] = None
    bank: Optional[str] = None
    resolve_ms: int = 0

    def value(self, t: int) -> float:
        v1 = self.v0 if self.v1 is None else self.v1
        if self.end_ms <= self.start_ms:
            return self.v0
        f = min(1.0, max(0.0, (t - self.start_ms) / (self.end_ms - self.start_ms)))
        return self.v0 + (v1 - self.v0) * f

    def active(self, t: int) -> bool:
        return self.start_ms <= t < self.end_ms


@dataclass
class ScenarioSpec:
    scenario: str
    params: dict = field(default_factory=dict)
    modifiers: list = field(default_factory=list)
    rate_fn: Optional[Callable] = None
    rate_max_mult: float = 1.0
    extra_payments: list = field(default_factory=list)     # (t_ms, psp_idx, ben_idx, kind)
    truth: list = field(default_factory=list)


def _u(rng: np.random.Generator, lo_hi) -> float:
    lo, hi = lo_hi
    return float(rng.uniform(lo, hi))


def _i(rng: np.random.Generator, lo_hi) -> int:
    return int(round(_u(rng, lo_hi)))


def _truth(idx: int, onset: int, end: int, level: str, psp: str, bank: str, kind: str, mag: float,
           is_incident: bool) -> dict:
    return {"incident_id": f"gt-{idx}", "onset_ms": int(onset), "end_ms": int(end), "level": level,
            "psp": psp, "bank": bank, "kind": kind, "magnitude": float(mag), "is_incident": is_incident}


def _surge_fn(onset: int, dur: int, mult: float, flash_start: int, flash_ms: int, flash: float):
    def fn(t: np.ndarray) -> np.ndarray:
        m = np.ones_like(t, dtype=float)
        m[(t >= onset) & (t < onset + dur)] = mult
        m[(t >= flash_start) & (t < flash_start + flash_ms)] = flash
        return m
    return fn


def build(scenario: str, seed: int, cfg: SimConfig, overrides: Optional[dict] = None) -> ScenarioSpec:
    """Draw one configuration. `overrides` pins any drawn parameter (e.g. {"psp": "P1", "onset": 200000})."""
    sc = cfg.scenarios
    ov = overrides or {}
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 7919, int(scenario[1:])]))
    psps, banks = cfg.topology.psps, cfg.topology.banks
    psp = ov.get("psp", psps[int(rng.integers(len(psps)))])
    bank = ov.get("bank", banks[int(rng.integers(len(banks)))])
    spec = ScenarioSpec(scenario)
    if scenario == "S0":
        return spec
    p = sc[scenario] if scenario in sc else {}

    def draw(name: str, fn=_i):
        return ov[name] if name in ov else fn(rng, p[name])

    if scenario in ("S1", "S5"):
        s1 = sc["S1"]
        on, d = (ov["onset"] if "onset" in ov else _i(rng, s1["onset"])), (ov.get("duration") or _i(rng, s1["duration"]))
        m = ov.get("mult") or _u(rng, s1["mult"])
        # A benign surge must stay below capacity (IBM lesson, OldReference DEVIATIONS WP-13): cap the flash at
        # rho <= flash_rho_cap given the configured baseline utilisation.
        flash = min(s1["flash_mult"], s1["flash_rho_cap"] / s1["base_utilisation"])
        mid = on + d // 2 - s1["flash_ms"] // 2
        spec.rate_fn = _surge_fn(on, d, m, mid, s1["flash_ms"], max(m, flash))
        spec.rate_max_mult = max(m, flash)
        spec.params.update(onset=on, duration=d, mult=m, flash=max(m, flash))
        spec.truth.append(_truth(0, on, on + d, "platform", "*", "*", "surge", m, False))
    if scenario in ("S2", "S5"):
        s2 = sc["S2"]
        on = ov.get("onset2") or _i(rng, s2["onset"])
        d, m = _i(rng, s2["duration"]), _u(rng, s2["mult"])
        spec.modifiers.append(Modifier("psp_service", on, on + d, v0=m, psp=psp))
        spec.params.update(psp=psp, onset2=on, duration2=d, mult2=m)
        spec.truth.append(_truth(1, on, on + d, "psp", psp, "*", "psp_slowdown", m, True))
    elif scenario == "S3":
        on, d, m = draw("onset"), draw("duration"), draw("mult", _u)
        spec.modifiers.append(Modifier("bank_latency", on, on + d, v0=m, bank=bank))
        spec.params.update(bank=bank, onset=on, duration=d, mult=m)
        spec.truth.append(_truth(1, on, on + d, "bank", "*", bank, "bank_slowdown", m, True))
    elif scenario == "S4":
        on, d, f = draw("onset"), draw("duration"), draw("worker_loss", _u)
        spec.modifiers.append(Modifier("capacity", on, on + d, v0=1.0 - f, psp=psp))
        spec.params.update(psp=psp, onset=on, duration=d, worker_loss=f)
        spec.truth.append(_truth(1, on, on + d, "psp", psp, "*", "retry_storm", f, True))
    elif scenario == "S6":
        on, d, h, r = draw("onset"), draw("duration"), draw("hold_frac", _u), draw("resolve_after")
        spec.modifiers.append(Modifier("credit_hold", on, on + d, v0=h, bank=bank, resolve_ms=on + d + r))
        spec.params.update(bank=bank, onset=on, duration=d, hold_frac=h, resolve_after=r,
                           resolve_credit_prob=p["resolve_credit_prob"])
        spec.truth.append(_truth(1, on, on + d, "bank", "*", bank, "verification_storm", h, True))
    elif scenario == "S7":
        start, ramp, m_end = draw("onset"), p["ramp_ms"], p["mult_end"]
        spec.modifiers.append(Modifier("route_latency", start, start + ramp, v0=1.0, v1=m_end, psp=psp, bank=bank))
        onset = start + round(ramp * (p["onset_threshold"] - 1.0) / (m_end - 1.0))
        spec.params.update(psp=psp, bank=bank, start=start, mult_end=m_end)
        spec.truth.append(_truth(1, onset, start + ramp, "route", psp, bank, "silent_drift", m_end, True))
    elif scenario == "S8":
        t0, n = draw("onset"), draw("batch_n")
        end = t0 + p["batch_delay_ms"] + p["batch_spread_ms"] + 60_000
        spec.modifiers.append(Modifier("bank_latency", t0, end, v0=p["slow_mult"], bank=bank))
        b0 = t0 + p["batch_delay_ms"]
        bi = banks.index(bank)
        spec.extra_payments = [(b0 + int(i * p["batch_spread_ms"] / n), 0, bi, "PAYOUT") for i in range(n)]
        spec.params.update(bank=bank, onset=t0, batch_n=n)
        spec.truth.append(_truth(1, t0, end, "bank", "*", bank, "payout_burst", float(n), True))
    elif scenario not in ("S1", "S5"):
        raise ValueError(f"unknown scenario {scenario!r}")
    return spec
