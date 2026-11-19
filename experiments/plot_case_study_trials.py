#!/usr/bin/env python3
"""
Plot one representative trial per attack type for the paper (IEEE single column).

Each panel shows, around the attack window, what the monitor compares:
  * the velocity the attacked vehicle reports about itself      (v_obs, solid)
  * the leader velocity its follower reports having received     (v_in, dashed)
  * the follower's own measured velocity                         (dotted)
plus the planned attack window (shaded) and the frames where ScenarioTwin
labels the follower (ticks along the top).

By default the script picks, per attack type, the detected trial whose attack
duration is closest to the median duration of that type (attacked vehicle
Bjarte if available). Override with --spoof-trial / --brake-trial.

Usage:
    python experiments/plot_case_study_trials.py --out Paper/figures/case_trials.pdf
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from case_study_summary import (  # noqa: E402
    LEADER_OF,
    _DEFAULT_EXPERIMENT_DIR,
    _DEFAULT_RECORDINGS_DIR,
    _field,
    _flagged,
    _relative_times,
    speed_series,
    analyze_trial,
    load_frames,
    _load_json,
)

# Validated categorical slots 1-3 (dataviz reference palette, light mode);
# line style is the secondary encoding so the figure survives grayscale print.
C_OBS, C_IN, C_OWN = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, WINDOW = "#e1e0d9", "#c3c2b7", "#ecebe6"

PRE_S, POST_S = 3.0, 3.0  # seconds shown before the attack and after it ends


def _style() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "font.size": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "pdf.fonttype": 42,  # embed TrueType fonts (IEEE PDF eXpress)
        "ps.fonttype": 42,
    })


def _pick(rows: list[dict[str, Any]], family: str) -> dict[str, Any] | None:
    cands = [r for r in rows if r["family"] == family and not r["excluded"] and r.get("detected")]
    if not cands:
        cands = [r for r in rows if r["family"] == family and not r["excluded"]]
    if not cands:
        return None
    typical = [r for r in cands if not r.get("other_flagged_robots") and not r.get("pre_attack_detection")] or cands
    preferred = [r for r in typical if r.get("attacked_vehicle") == "Bjarte"] or typical
    durs = [r["duration_s"] for r in preferred if r.get("duration_s") is not None]
    med = statistics.median(durs) if durs else 0.0
    return min(preferred, key=lambda r: abs((r.get("duration_s") or 0.0) - med))


def _panel(ax, row: dict[str, Any], trial_dir: Path, recordings_dir: Path, title: str,
           x_max: float) -> None:
    manifest = _load_json(trial_dir / "manifest.json") or {}
    follower = manifest["target_robot"]
    leader = LEADER_OF.get(follower, follower)
    frames = load_frames(recordings_dir / f"{manifest['run_id']}.jsonl")
    rel = _relative_times(frames, manifest.get("started_at"))
    # t = 0 is the attack request (events.csv), as in case_study_summary.py.
    start = float(row["attack_start_s"])
    end = start + float(row["duration_s"])
    x = [t - start for t in rel]
    keep = [i for i, t in enumerate(x) if -PRE_S <= t <= x_max]

    def series(robot: str, key: str):
        xs, ys = [], []
        for i in keep:
            v = _field(frames[i], robot, key)
            if v is not None:
                xs.append(x[i])
                ys.append(v)
        return xs, ys

    ax.axvspan(0.0, end - start, color=WINDOW, lw=0, zorder=0)
    ax.plot(*series(leader, "v"), color=C_OBS, lw=1.2, ls="-", zorder=3)
    ax.plot(*series(follower, "leader_input_v"), color=C_IN, lw=1.2, ls=(0, (4, 1.5)), zorder=4)
    # The simulator reports a constant estimated velocity, so the follower's
    # actual speed is computed from its reported positions.
    own = [(t - start, v) for t, v in speed_series(rel, frames, follower)
           if -PRE_S <= t - start <= x_max]
    ax.plot([a for a, _ in own], [b for _, b in own], color=C_OWN, lw=1.2,
            ls=(0, (1, 1.2)), zorder=5)

    flagged = [x[i] for i in keep if _flagged(frames[i], follower)]
    ymin, ymax = ax.get_ylim()
    ymax = max(ymax, 1.15)
    ax.set_ylim(min(0.0, ymin), ymax + 0.12)
    ax.plot(flagged, [ymax + 0.04] * len(flagged), ls="none", marker="|",
            ms=4, mew=0.8, color=INK, zorder=6)

    ax.set_xlim(-PRE_S, x_max)
    ax.grid(axis="y", color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_ylabel("Velocity (m/s)")
    ax.set_title(title, loc="left", fontsize=7.5, color=INK, pad=2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot representative case-study trials.")
    ap.add_argument("--experiment-dir", type=Path, default=_DEFAULT_EXPERIMENT_DIR)
    ap.add_argument("--recordings-dir", type=Path, default=_DEFAULT_RECORDINGS_DIR)
    ap.add_argument("--spoof-trial", default=None, help="trial folder name to use for (a)")
    ap.add_argument("--brake-trial", default=None, help="trial folder name to use for (b)")
    ap.add_argument("--out", type=Path, default=Path("case_trials.pdf"))
    args = ap.parse_args()

    trials_root = args.experiment_dir / "trials"
    rows = [analyze_trial(d, args.recordings_dir)
            for d in sorted(p for p in trials_root.glob("*") if p.is_dir())]
    by_id = {r["trial_id"]: r for r in rows}

    chosen = []
    for family, override, letter, name in (
        ("velocity_spoof", args.spoof_trial, "a", "Velocity spoofing"),
        ("false_brake", args.brake_trial, "b", "False braking"),
    ):
        row = by_id.get(override) if override else _pick(rows, family)
        if row is None:
            raise SystemExit(f"No usable {family} trial found under {trials_root}")
        detail = f"target {row['attacked_vehicle']}, {row['duration_s']:.1f} s"
        if family == "velocity_spoof" and row.get("speed_mps") is not None:
            detail = f"target {row['attacked_vehicle']} set to {float(row['speed_mps']):.2f} m/s, {row['duration_s']:.1f} s"
        chosen.append((row, f"({letter}) {name}: {detail}"))
        print(f"({letter}) {row['trial_id']}  detected={row.get('detected')} ttd={row.get('ttd_s')}")

    _style()
    fig, axes = plt.subplots(2, 1, figsize=(3.5, 2.7), sharex=True)
    x_max = max(row["duration_s"] or 0.0 for row, _ in chosen) + POST_S
    for ax, (row, title) in zip(axes, chosen):
        _panel(ax, row, trials_root / row["trial_id"], args.recordings_dir, title, x_max)
    axes[-1].set_xlabel("Time since attack request (s)")

    handles = [
        Line2D([], [], color=C_OBS, lw=1.2, ls="-", label=r"$v^{\mathrm{obs}}$ reported by target"),
        Line2D([], [], color=C_IN, lw=1.2, ls=(0, (4, 1.5)), label=r"$v^{\mathrm{in}}$ received by follower"),
        Line2D([], [], color=C_OWN, lw=1.2, ls=(0, (1, 1.2)), label="Follower speed"),
        Line2D([], [], color=INK, ls="none", marker="|", ms=5, mew=0.8, label="ScenarioTwin label"),
        Patch(facecolor=WINDOW, edgecolor="none", label="Attack window"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 1.01), handlelength=1.8, columnspacing=0.8,
               handletextpad=0.4, labelcolor=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.86), h_pad=0.4)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    fig.savefig(args.out.with_suffix(".png"), dpi=300)
    print(f"Wrote {args.out} and {args.out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
