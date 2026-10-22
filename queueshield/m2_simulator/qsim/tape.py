"""Common-random-number tape (docs/M2_SIMULATOR.md §10). Ported from the IBM project's qs/sim/tape.py.

Generated once per (seed, scenario configuration) before the run, from named PCG64 streams. Every draw is
indexed by (payment index, attempt number) and never consumed in order, so all five universes of a seed see
identical underlying randomness: policies change *when* and *how much* a draw is scaled, never the draw.
Service times are lognormal built from standard normals: exp(mu + sigma*z) is F^-1(quantile).
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from qsim.config import SimConfig

STREAMS = ("arrivals", "routing", "service", "declines", "clients", "banks", "status")


def streams(seed: int) -> dict:
    children = np.random.SeedSequence(int(seed)).spawn(len(STREAMS))
    return {name: np.random.Generator(np.random.PCG64(ss)) for name, ss in zip(STREAMS, children)}


def _pick(u: np.ndarray, shares) -> np.ndarray:
    c = np.cumsum(np.asarray(shares, dtype=float))
    c[-1] = 1.0 + 1e-12
    return np.searchsorted(c, u, side="right").astype(np.int64)


class Tape:
    def __init__(self, seed: int, cfg: SimConfig, horizon_ms: int,
                 rate_fn: Optional[Callable[[np.ndarray], np.ndarray]] = None, rate_max_mult: float = 1.0,
                 extra: Optional[list] = None) -> None:
        """rate_fn maps times (ms) to a demand multiplier in [0, rate_max_mult] (thinned NHPP).

        extra: scheduled payments [(t_ms, psp_idx, beneficiary_idx, kind)] such as the S8 payout batch;
        they get draws like any other payment and are merged into the arrival order.
        """
        self.seed = int(seed)
        g = streams(seed)
        A = cfg.client.max_attempts_tape
        self.max_attempts = A

        lam = cfg.fresh_rate_per_s * rate_max_mult
        n0 = int(g["arrivals"].poisson(lam * horizon_ms / 1000.0))
        t = np.sort(g["arrivals"].random(n0) * horizon_ms)
        u_thin = g["arrivals"].random(n0)
        if rate_fn is not None:
            t = t[u_thin < rate_fn(t) / rate_max_mult]
        t = t.astype(np.int64)
        n_base = len(t)
        psp = _pick(g["routing"].random(n_base), cfg.topology.psp_shares)
        rem = _pick(g["routing"].random(n_base), cfg.topology.bank_shares)
        ben = _pick(g["routing"].random(n_base), cfg.topology.bank_shares)
        kinds = [k for k, _ in cfg.kinds]
        kind = _pick(g["routing"].random(n_base), [s for _, s in cfg.kinds])
        kind_names = np.array(kinds + ["PAYOUT"], dtype=object)
        if extra:
            ex = np.array([e[0] for e in extra], dtype=np.int64)
            t = np.concatenate([t, ex])
            psp = np.concatenate([psp, np.array([e[1] for e in extra])])
            rem = np.concatenate([rem, _pick(g["routing"].random(len(extra)), cfg.topology.bank_shares)])
            ben = np.concatenate([ben, np.array([e[2] for e in extra])])
            kind = np.concatenate([kind, np.full(len(extra), len(kinds))])
            order = np.argsort(t, kind="stable")
            t, psp, rem, ben, kind = t[order], psp[order], rem[order], ben[order], kind[order]
        n = len(t)
        self.n = n
        self.arrivals = t
        self.psp, self.rem, self.ben = psp, rem, ben
        self.kind = kind_names[kind]
        # per attempt
        self.u_route = g["routing"].random((n, A))
        self.z_psp = g["service"].standard_normal((n, A))
        self.z_rem = g["service"].standard_normal((n, A))
        self.z_ben = g["service"].standard_normal((n, A))
        self.u_bd = g["declines"].random((n, A))
        self.u_td_rem = g["declines"].random((n, A))
        self.u_td_ben = g["declines"].random((n, A))
        self.u_hold = g["banks"].random((n, A))
        self.u_hold_outcome = g["banks"].random((n, A))
        self.z_ledger = g["banks"].standard_normal((n, 8))
        self.u_retry = g["clients"].random((n, A))
        self.u_delay = g["clients"].random((n, A))
        self.u_honour = g["clients"].random((n, A))
        self.u_profile = g["clients"].random(n)
        self.z_status = g["status"].standard_normal((n, 32))   # naive clients poll at most 30 times
