"""JSON-lines logging to stdout: {"ts","module","level","msg",...ids} (AGENTS.md rule 17).

Only ids and short codes belong in `**ids`; never payloads, amounts or personal data.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

_MODULE = "m?"


def set_module(module: str) -> None:
    global _MODULE
    _MODULE = module


def log(level: str, msg: str, **ids: object) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "module": _MODULE,
           "level": level, "msg": msg, **ids}
    sys.stdout.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
    sys.stdout.flush()


def info(msg: str, **ids: object) -> None:
    log("info", msg, **ids)


def warn(msg: str, **ids: object) -> None:
    log("warn", msg, **ids)


def error(msg: str, **ids: object) -> None:
    log("error", msg, **ids)
