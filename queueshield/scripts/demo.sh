#!/usr/bin/env bash
# QueueShield end-to-end launcher & smoke runner (docs/M5_CONSOLE.md §6, §7).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "/tmp/qs-venv/bin/python" ]; then
  PY="/tmp/qs-venv/bin/python"
fi

if [ "${1:-}" = "--smoke" ]; then
  exec "$PY" m5_console/scripts/integration_smoke.py --seconds "${2:-45}"
fi

echo "[demo] Generating deterministic recordings (s6_u0, s6_u4)..."
node m5_console/scripts/record.mjs

echo "[demo] Starting QueueShield integration smoke check..."
"$PY" m5_console/scripts/integration_smoke.py --seconds "${SMOKE_SECONDS:-45}"
