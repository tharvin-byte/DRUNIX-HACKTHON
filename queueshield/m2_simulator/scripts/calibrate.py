"""M2-T01 Calibration sweep (docs/M2_SIMULATOR.md §8).

Sweeps trigger size x duration for S4 (worker_loss x duration) or S6 (hold_frac x duration) across seeds under U0 and U2,
judging a run *stuck* when mean goodput over [end+60s, end+120s] < 50% of the warm-up baseline.
Writes `data/calibration/<scenario>.json`, `data/calibration/summary.json`, and `data/figures/F1_<scenario>.png`.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from qsim import config as config_mod
from qsim import scenarios
from qsim.engine import Engine

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"


def _eval_cell(args: tuple[str, int, str, dict[str, Any], int]) -> tuple[str, int, str, bool, float, float]:
    scenario, seed, universe, pins, horizon_ms = args
    cfg = config_mod.load()
    spec = scenarios.build(scenario, seed, cfg, pins)
    e = Engine(cfg, spec, seed, universe, horizon_ms=horizon_ms)
    e.run_until(horizon_ms)
    onset_s = int(pins["onset"]) // 1000
    end_s = (int(pins["onset"]) + int(pins["duration"])) // 1000
    base_slice = e.ts["goodput"][max(5, onset_s - 40):onset_s]
    base = float(base_slice.mean()) if len(base_slice) else 150.0
    post_slice = e.ts["goodput"][end_s + 60:end_s + 120]
    post = float(post_slice.mean()) if len(post_slice) else 0.0
    frac = post / max(1.0, base)
    stuck = frac < 0.50
    snaps = [x["switch_slowdown_factor"] for x in e.events if x["event_type"] == "SWITCH_SNAPSHOT"]
    max_slow = float(max(snaps)) if snaps else 1.0
    return (scenario, seed, universe, stuck, round(frac, 3), round(max_slow, 3))


def run_sweep(scenario: str, seeds: int = 5, workers: int = 4) -> dict[str, Any]:
    onset_ms = 60_000
    horizon_ms = 265_000
    if scenario == "S4":
        sizes = [0.50, 0.60, 0.65]
        durations = [20_000, 45_000, 80_000]
        size_key = "worker_loss"
        target_entity = {"psp": "P1"}
    elif scenario == "S6":
        sizes = [0.30, 0.35, 0.45]
        durations = [20_000, 45_000, 75_000]
        size_key = "hold_frac"
        target_entity = {"bank": "B1"}
    else:
        raise ValueError(f"calibrate supports S4 or S6, got {scenario}")

    tasks = []
    for sz in sizes:
        for dur in durations:
            for seed in range(1, seeds + 1):
                for u in ("U0", "U2"):
                    pins = {**target_entity, "onset": onset_ms, "duration": dur, size_key: sz}
                    if scenario == "S6":
                        pins["resolve_after"] = 20_000 if dur <= 25_000 else 90_000
                    tasks.append((scenario, seed, u, pins, horizon_ms, sz, dur))

    raw_args = [(t[0], t[1], t[2], t[3], t[4]) for t in tasks]
    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for meta, res in zip(tasks, ex.map(_eval_cell, raw_args)):
            _, seed, u, stuck, frac, max_slow = res
            results.append({
                "size": meta[5],
                "duration_ms": meta[6],
                "seed": seed,
                "universe": u,
                "stuck": bool(stuck),
                "goodput_frac": frac,
                "max_slowdown": max_slow,
            })

    grid_u0 = np.zeros((len(sizes), len(durations)))
    grid_u2 = np.zeros((len(sizes), len(durations)))
    cells = []
    for i, sz in enumerate(sizes):
        for j, dur in enumerate(durations):
            u0_rows = [r for r in results if r["size"] == sz and r["duration_ms"] == dur and r["universe"] == "U0"]
            u2_rows = [r for r in results if r["size"] == sz and r["duration_ms"] == dur and r["universe"] == "U2"]
            p_u0 = float(np.mean([1.0 if r["stuck"] else 0.0 for r in u0_rows]))
            p_u2 = float(np.mean([1.0 if r["stuck"] else 0.0 for r in u2_rows]))
            grid_u0[i, j] = p_u0
            grid_u2[i, j] = p_u2
            cells.append({
                size_key: sz,
                "duration_s": dur // 1000,
                "u0_stuck_frac": round(p_u0, 3),
                "u2_stuck_frac": round(p_u2, 3),
                "u0_mean_goodput_frac": round(float(np.mean([r["goodput_frac"] for r in u0_rows])), 3),
                "u2_mean_goodput_frac": round(float(np.mean([r["goodput_frac"] for r in u2_rows])), 3),
            })

    short_recovers = any(c["duration_s"] == durations[0] // 1000 and c["u0_stuck_frac"] <= 0.20 for c in cells)
    long_sticks = any(
        c["duration_s"] == durations[-1] // 1000 and c["u0_stuck_frac"] >= 0.80 and c["u2_stuck_frac"] < c["u0_stuck_frac"]
        for c in cells
    )
    accepted = bool(short_recovers and long_sticks)

    summary = {
        "scenario": scenario,
        "label": "simulation",
        "seeds": seeds,
        "size_key": size_key,
        "sizes": sizes,
        "durations_s": [d // 1000 for d in durations],
        "accepted_boundary": accepted,
        "short_recovers_ge_80pct": short_recovers,
        "long_sticks_ge_80pct_and_u2_lower": long_sticks,
        "cells": cells,
    }

    cal_dir = DATA_DIR / "calibration"
    fig_dir = DATA_DIR / "figures"
    cal_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)
    (cal_dir / f"{scenario.lower()}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Update combined summary.json
    comb_path = cal_dir / "summary.json"
    comb = {}
    if comb_path.is_file():
        try:
            comb = json.loads(comb_path.read_text(encoding="utf-8"))
        except Exception:
            comb = {}
    comb[scenario] = summary
    comb_path.write_text(json.dumps(comb, indent=2), encoding="utf-8")

    _plot_heatmap(scenario, size_key, sizes, [d // 1000 for d in durations], grid_u0, grid_u2,
                  fig_dir / f"F1_{scenario.lower()}.png")
    return summary


def _plot_heatmap(scenario: str, size_key: str, sizes: list[float], durations_s: list[int],
                  grid_u0: np.ndarray, grid_u2: np.ndarray, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.0), constrained_layout=True)
    for ax, grid, title in [
        (axes[0], grid_u0, f"{scenario} U0 (naive) stuck fraction [simulation]"),
        (axes[1], grid_u2, f"{scenario} U2 (npci_rule) stuck fraction [simulation]"),
    ]:
        im = ax.imshow(grid, vmin=0.0, vmax=1.0, cmap="YlOrRd", origin="lower", aspect="auto")
        ax.set_xticks(range(len(durations_s)), [f"{d}s" for d in durations_s])
        ax.set_yticks(range(len(sizes)), [f"{s:.2f}" for s in sizes])
        ax.set_xlabel("Fault duration (s)")
        ax.set_ylabel(size_key)
        ax.set_title(title, fontsize=10)
        for i in range(len(sizes)):
            for j in range(len(durations_s)):
                ax.text(j, i, f"{grid[i, j]:.2f}", ha="center", va="center", color="black", fontsize=9)
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.85, label="Stuck fraction (simulation)")
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="both", choices=["S4", "S6", "both"])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    targets = ["S4", "S6"] if a.scenario == "both" else [a.scenario]
    for sc in targets:
        res = run_sweep(sc, seeds=a.seeds, workers=a.workers)
        print(f"[{sc}] accepted_boundary={res['accepted_boundary']} cells={json.dumps(res['cells'])}")


if __name__ == "__main__":
    main()
