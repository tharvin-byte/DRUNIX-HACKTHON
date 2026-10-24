"""M2-T08 Configuration sets A/B/C generator (docs/M2_SIMULATOR.md §7).

Generates disjoint seed splits:
- Set A (train): seeds 1..999
- Set B (validation): seeds 1000..1999
- Set C (test): seeds 2000..2999
Writes `data/configs/{A,B,C}.json`.
"""
from __future__ import annotations

import json
from pathlib import Path

from qsim import config as config_mod
from qsim import scenarios

ROOT_DIR = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT_DIR / "data" / "configs"
SCENARIOS = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")


def build_split(name: str, seed_start: int, count_per_scenario: int = 10) -> dict:
    cfg = config_mod.load()
    entries = []
    for idx, sc in enumerate(SCENARIOS):
        for k in range(count_per_scenario):
            seed = seed_start + idx * 50 + k
            spec = scenarios.build(sc, seed, cfg)
            entries.append({
                "split": name,
                "scenario": sc,
                "seed": seed,
                "params": spec.params,
                "truth": spec.truth,
            })
    return {
        "split": name,
        "seed_range": [seed_start, seed_start + 998],
        "count": len(entries),
        "configs": entries,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    splits = {
        "A": build_split("A", 1, count_per_scenario=10),
        "B": build_split("B", 1000, count_per_scenario=10),
        "C": build_split("C", 2000, count_per_scenario=10),
    }
    for k, payload in splits.items():
        (OUT_DIR / f"{k}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote splits A, B, C to {OUT_DIR}")


if __name__ == "__main__":
    main()
