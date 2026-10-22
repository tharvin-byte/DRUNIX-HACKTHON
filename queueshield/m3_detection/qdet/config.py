"""Load config/detect.yaml once into nested frozen dataclasses (AGENTS.md rule 16)."""
from __future__ import annotations

import os
from dataclasses import make_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("DETECT_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config"))
# per-feature dicts stay as (read-only) dicts; everything else becomes a frozen dataclass
_DICT_KEYS = {"spread_floor"}


def _freeze(name: str, d: Any) -> Any:
    if isinstance(d, list):
        return tuple(d)
    if not isinstance(d, dict) or name in _DICT_KEYS:
        return d
    cls = make_dataclass(name.title().replace("_", ""), [(k, Any) for k in d], frozen=True)
    return cls(**{k: _freeze(k, v) for k, v in d.items()})


def load(config_dir: Path = CONFIG_DIR, overrides: dict | None = None):
    d = yaml.safe_load((config_dir / "detect.yaml").read_text(encoding="utf-8"))
    frozen = config_dir / "detectors_frozen.yaml"          # written by tuning (§4.2); overrides the defaults
    for src in ([yaml.safe_load(frozen.read_text(encoding="utf-8"))] if frozen.is_file() else []) + [overrides or {}]:
        for k, v in (src or {}).items():
            d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    return _freeze("detect_config", d)


@lru_cache(maxsize=1)
def default():
    return load()
