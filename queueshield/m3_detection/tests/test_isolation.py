"""AGENTS.md rule 3: this module never imports another module's package; live code never imports scripts/."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOREIGN = re.compile(r"^\s*(from|import)\s+(qsim|qctl|scripts)\b", re.M)


def test_no_cross_module_imports():
    for f in (ROOT / "qdet").rglob("*.py"):
        assert not FOREIGN.search(f.read_text(encoding="utf-8")), f
