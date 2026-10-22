"""M3 detection: per-segment state, detectors, localizer, forecaster, incidents (docs/M3_DETECTION.md)."""
from qdet import contracts, jsonlog

MODULE = "m3"
contracts.MODULE = MODULE
jsonlog.set_module(MODULE)
