"""Load config/{control,policy,operators}.yaml once (AGENTS.md rule 16).

control.yaml becomes nested frozen dataclasses; the policy rule table stays data (dicts/lists) because it is
interpreted by policy.py, and is never mutated.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, make_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("CONTROL_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config"))


def _freeze(name: str, d: Any) -> Any:
    if isinstance(d, list):
        return tuple(d)
    if not isinstance(d, dict):
        return d
    cls = make_dataclass(name.title().replace("_", ""), [(k, Any) for k in d], frozen=True)
    return cls(**{k: _freeze(k, v) for k, v in d.items()})


@dataclass(frozen=True)
class ControlConfig:
    c: Any               # control.yaml (frozen)
    policy: dict         # policy.yaml (data)
    operators: tuple


def load(config_dir: Path = CONFIG_DIR, overrides: dict | None = None) -> ControlConfig:
    d = yaml.safe_load((config_dir / "control.yaml").read_text(encoding="utf-8"))
    for k, v in (overrides or {}).items():
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    policy = yaml.safe_load((config_dir / "policy.yaml").read_text(encoding="utf-8"))
    ops = yaml.safe_load((config_dir / "operators.yaml").read_text(encoding="utf-8"))["operators"]
    return ControlConfig(_freeze("control", d), policy, tuple(ops))


@lru_cache(maxsize=1)
def default() -> ControlConfig:
    return load()
