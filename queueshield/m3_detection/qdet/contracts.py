"""JSON-Schema validation against the shared contracts (AGENTS.md rules 4-5).

The schemas live in `contracts/schemas/` at the repo root (read-only for modules). Every outgoing
message is validated before it is sent; every incoming one before it is used. Invalid incoming
messages are counted in `REJECTED` and dropped, never raised into the caller's event loop.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

MODULE = "m3"  # set by the module's __init__ (used only for log/metric labels)


class RejectedCounter:
    """`rejected_messages_total{schema}` (AGENTS.md rule 4)."""

    def __init__(self) -> None:
        self.total = 0
        self.by_schema: dict[str, int] = {}

    def inc(self, schema: str) -> None:
        self.total += 1
        self.by_schema[schema] = self.by_schema.get(schema, 0) + 1


REJECTED = RejectedCounter()


def contracts_dir() -> Path:
    env = os.environ.get("CONTRACTS_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "contracts" / "schemas").is_dir():
            return p / "contracts"
    raise FileNotFoundError("contracts/schemas not found; set CONTRACTS_DIR")


@lru_cache(maxsize=1)
def _registry() -> Registry:
    reg: Registry = Registry()
    for f in sorted((contracts_dir() / "schemas").glob("*.schema.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        reg = reg.with_resource(doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012))
    return reg


@lru_cache(maxsize=None)
def _validator(name: str, defn: str | None) -> Draft202012Validator:
    f = contracts_dir() / "schemas" / f"{name}.schema.json"
    schema: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
    if defn:
        schema = {"$ref": f"{schema['$id']}#/$defs/{defn}"}
    return Draft202012Validator(schema, registry=_registry())


def errors(name: str, obj: Any, defn: str | None = None) -> list[str]:
    """Human-readable validation errors ([] = valid). `defn` selects a `$defs` entry (e.g. lockstep)."""
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in _validator(name, defn).iter_errors(obj)]


def validate(name: str, obj: Any, defn: str | None = None) -> None:
    """Raise ValueError if `obj` does not validate (use for messages we send)."""
    errs = errors(name, obj, defn)
    if errs:
        raise ValueError(f"{name} invalid: {errs[0]}")


def accept(name: str, obj: Any, defn: str | None = None) -> bool:
    """Validate an incoming message. False (and counted) if invalid; never raises."""
    if errors(name, obj, defn):
        REJECTED.inc(name)
        return False
    return True
