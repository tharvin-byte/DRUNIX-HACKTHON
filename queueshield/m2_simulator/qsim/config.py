"""Load `config/*.yaml` once into frozen dataclasses (AGENTS.md rule 16). No tunable number lives in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("SIM_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config"))


@dataclass(frozen=True)
class Topology:
    psps: tuple
    psp_shares: tuple
    banks: tuple
    bank_shares: tuple


@dataclass(frozen=True)
class PspCfg:
    workers: int | tuple
    q_max: int
    t_psp_mean_ms: float
    t_psp_cv: float
    reject_ms: int
    shed_cost_ms: int
    starvation_guard_ms: int


@dataclass(frozen=True)
class BankCfg:
    leg_mean_ms: float
    leg_cv: float
    bd_rate: float
    td_rate: tuple
    reversal_delay_ms: int


@dataclass(frozen=True)
class SwitchCfg:
    status_workers: int
    status_mean_ms: float
    status_cv: float
    status_q_max: int
    status_timeout_ms: int
    status_bank_cost_ms: float
    slowdown_alpha: float
    slowdown_u0: float
    overload_reply_ms: int


@dataclass(frozen=True)
class ClientCfg:
    timeout_ms: int
    naive_share_governed_universes: float
    max_attempts_tape: int


@dataclass(frozen=True)
class RunCfg:
    length_ms: int
    warmup_ms: int
    tick_ms: int
    snapshot_ms: int
    drain_ms: int
    goodput_deadline_ms: int


@dataclass(frozen=True)
class LedgerModelCfg:
    submit_p50_ms: float
    submit_p95_ms: float
    event_lag_p50_ms: float


@dataclass(frozen=True)
class BudgetCfg:
    rate_per_s: float
    burst: int
    first_check_delay_ms: int
    max_checks: int
    horizon_ms: int
    ledger_wait_ms: int


@dataclass(frozen=True)
class LiveCfg:
    demo_rate_factor: float
    action_poll_s: float


@dataclass(frozen=True)
class SimConfig:
    topology: Topology
    kinds: tuple            # ((kind, share), ...)
    psp: PspCfg
    bank: BankCfg
    switch: SwitchCfg
    fresh_rate_per_s: float
    client: ClientCfg
    run: RunCfg
    ledger_model: LedgerModelCfg
    default_budget: BudgetCfg
    live: LiveCfg
    profiles: dict
    scenarios: dict


def _tuplify(v: Any) -> Any:
    return tuple(_tuplify(x) for x in v) if isinstance(v, list) else v


def _build(cls, d: dict):
    names = {f.name for f in fields(cls)}
    unknown = set(d) - names
    if unknown:
        raise ValueError(f"unknown keys for {cls.__name__}: {sorted(unknown)}")
    return cls(**{k: _tuplify(v) for k, v in d.items()})


def _resolve_profiles(raw: dict) -> dict:
    """Expand `inherits:` so every profile is a flat dict."""
    out: dict = {}

    def get(name: str) -> dict:
        if name in out:
            return out[name]
        p = dict(raw[name])
        parent = p.pop("inherits", None)
        merged = {**get(parent), **p} if parent else p
        out[name] = merged
        return merged

    for name, v in raw.items():
        if isinstance(v, dict):
            get(name)
    out["retry_after_honour_frac"] = raw["retry_after_honour_frac"]
    return out


def load(config_dir: Path = CONFIG_DIR, overrides: dict | None = None) -> SimConfig:
    d = yaml.safe_load((config_dir / "sim_default.yaml").read_text(encoding="utf-8"))
    for k, v in (overrides or {}).items():          # shallow section overrides, e.g. {"psp": {"q_max": 3000}}
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    profiles = _resolve_profiles(yaml.safe_load((config_dir / "profiles.yaml").read_text(encoding="utf-8")))
    scenarios = yaml.safe_load((config_dir / "scenarios.yaml").read_text(encoding="utf-8"))
    return SimConfig(
        topology=_build(Topology, d["topology"]), kinds=tuple(d["kinds"].items()),
        psp=_build(PspCfg, d["psp"]), bank=_build(BankCfg, d["bank"]), switch=_build(SwitchCfg, d["switch"]),
        fresh_rate_per_s=float(d["demand"]["fresh_rate_per_s"]), client=_build(ClientCfg, d["client"]),
        run=_build(RunCfg, d["run"]), ledger_model=_build(LedgerModelCfg, d["ledger_model"]),
        default_budget=_build(BudgetCfg, d["default_budget"]), live=_build(LiveCfg, d["live"]),
        profiles=profiles, scenarios=scenarios)


@lru_cache(maxsize=1)
def default() -> SimConfig:
    return load()


def with_rate(cfg: SimConfig, rate: float) -> SimConfig:
    return replace(cfg, fresh_rate_per_s=rate)
