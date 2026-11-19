#!/usr/bin/env python3
"""
TwinGuard plot generator -- thesis-ready figures.

Default mode: randomized adversarial trial plots (trials_summary.csv).
Legacy mode:  --campaign generates fixed-campaign figures.

Randomized trial figures (12 total):
  F1  f1_trial_outcomes           -- trial outcome overview (4 categories)
  F2  f2_detection_timeline       -- detection outcome by trial sequence
  F3  f3_duration_detection_rate  -- duration vs detection-rate (integer-second buckets)
  F4  f4_detection_by_strategy    -- detection rate by attack strategy
  F5  f5_undetected_impact        -- undetected physical impact by strategy
  F6  f6_false_positive_summary   -- false-positive rate on no-attack trials
  F7  f7_strategy_outcome_stack   -- detected/missed/harmful-missed by strategy
  F8  f8_risk_vs_detection        -- risk-assigned attacks vs detected attacks
  F9  f9_detection_by_attack_category -- detection rate by family and strategy
  F10 f10_strategy_risk_map       -- detection rate vs miss rate
  F11 f11_detection_rate_sensitivity -- detection rate with/without attack types
  F12 f12_ttd_ecdf                -- cumulative time-to-detection curve

no_attack trials are negative controls throughout:
  - detection on a no_attack trial = false positive, not a hit
  - clean no_attack trials are NOT counted as missed attacks
  - all attack-detection metrics exclude no_attack from the denominator

Usage (randomized trials -- main thesis plots):
  python experiments/plots.py --randomized
  python experiments/plots.py --randomized --summary-csv path/to/trials_summary.csv
  python experiments/plots.py --randomized --output-dir path/to/plots --formats png svg

Usage (legacy fixed-campaign):
  python experiments/plots.py --campaign thesis_m5_detection_campaign
  python experiments/plots.py --campaign thesis_m5_detection_campaign --formats png svg
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from pathlib import Path
from typing import Any

try:
    import matplotlib
    matplotlib.use("Agg")  # headless / non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.ticker as mticker
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "visualization" / "output" / "experiments"
_DEFAULT_RANDOMIZED_ID = "randomized_adversarial_trials"
_DEFAULT_OUTSIDE_THRESHOLD_ID = "outside_threshold_trials"

# Risk level colour palette -- matches TwinGuard RiskPanel tokens.css
_LEVEL_COLORS: dict[str, str] = {
    "low":      "#00c878",
    "false_positive_candidate": "#8aa0b4",
    "moderate": "#e6b400",
    "high":     "#ff8c00",
    "critical": "#ff3060",
}
_LEVEL_ORDER = ["low", "false_positive_candidate", "moderate", "high", "critical"]
_FIG_DPI = 180

_STRATEGY_ORDER = ["constant", "ramp", "near_threshold", "micro_spoof", "dropout", "burst", "pulse"]
_DIFFICULTY_ORDER = ["hard", "medium", "easy"]
_STRATEGY_COLORS: dict[str, str] = {
    "constant":       "#4e9af1",
    "ramp":           "#c47aff",
    "near_threshold": "#e6b400",
    "micro_spoof":    "#00d4aa",
    "dropout":        "#ff6666",
    "burst":          "#ff8c00",
    "pulse":          "#888888",
}

# Outcome palette -- consistent across all randomized figures
_OUTCOME_COLORS: dict[str, str] = {
    "detected_attack":  "#00c878",  # green
    "missed_attack":    "#ff8c00",  # orange
    "false_positive":   "#ff3060",  # red
    "clean_no_attack":  "#8aa0b4",  # blue-gray
}
_OUTCOME_MARKERS: dict[str, str] = {
    "detected_attack":  "o",
    "missed_attack":    "x",
    "false_positive":   "D",
    "clean_no_attack":  "s",
}
_OUTCOME_LABELS: dict[str, str] = {
    "detected_attack":  "Detected attack",
    "missed_attack":    "Missed attack",
    "false_positive":   "False positive (no-attack trial)",
    "clean_no_attack":  "Clean no-attack",
}


# â”€â”€ Data helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_csv(csv_path: Path) -> list[dict[str, Any]]:
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _is_excluded(row: dict[str, Any]) -> bool:
    return str(row.get("excluded", "")).lower() in ("true", "1", "yes")


def _is_no_attack(row: dict[str, Any]) -> bool:
    """True for negative-control trials (attack_family == 'no_attack')."""
    return str(row.get("attack_family", "")).lower() == "no_attack"


def _outcome_category(row: dict[str, Any]) -> str:
    """Classify a trial into one of four mutually exclusive outcome categories.

    detected_attack  -- real attack trial that was detected
    missed_attack    -- real attack trial that was NOT detected
    false_positive   -- no_attack (negative control) trial that triggered an alert
    clean_no_attack  -- no_attack trial that produced no alert
    """
    is_na = _is_no_attack(row)
    detected = _parse_bool(row.get("detected", "False"))
    if not is_na and detected:
        return "detected_attack"
    if not is_na and not detected:
        return "missed_attack"
    if is_na and detected:
        return "false_positive"
    return "clean_no_attack"


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_bool(v: Any) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _level_color(level: str) -> str:
    return _LEVEL_COLORS.get(str(level).lower(), "#888888")


def _level_rank(level: str) -> int:
    try:
        return _LEVEL_ORDER.index(str(level).lower())
    except ValueError:
        return -1


def _sorted_strategies(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    for r in rows:
        seen.add(str(r.get("attack_strategy", "unknown")))

    def _key(s: str) -> tuple[int, str]:
        try:
            return (_STRATEGY_ORDER.index(s), s)
        except ValueError:
            return (len(_STRATEGY_ORDER), s)

    return sorted(seen, key=_key)


def _attack_category(row: dict[str, Any]) -> str:
    category = str(row.get("attack_family", "") or "").strip()
    return category if category else "unknown"


def _attack_subcategory(row: dict[str, Any]) -> str:
    family = _attack_category(row)
    strategy = str(row.get("attack_strategy", "") or "").strip() or "unknown"
    return f"{family}\n{strategy}"


def _sorted_attack_categories(rows: list[dict[str, Any]]) -> list[str]:
    preferred = ["velocity_spoof", "false_brake", "no_attack"]
    seen = {_attack_category(r) for r in rows}

    def _key(category: str) -> tuple[int, str]:
        try:
            return (preferred.index(category), category)
        except ValueError:
            return (len(preferred), category)

    return sorted(seen, key=_key)


def _sorted_attack_subcategories(rows: list[dict[str, Any]]) -> list[str]:
    preferred_family = {"velocity_spoof": 0, "false_brake": 1, "no_attack": 2}
    preferred_strategy = {s: i for i, s in enumerate(_STRATEGY_ORDER)}
    seen = {_attack_subcategory(r) for r in rows}

    def _key(label: str) -> tuple[int, int, str]:
        family, _, strategy = label.partition("\n")
        return (
            preferred_family.get(family, len(preferred_family)),
            preferred_strategy.get(strategy, len(preferred_strategy)),
            label,
        )

    return sorted(seen, key=_key)


# â”€â”€ Shared figure style â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _setup_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": "#ffffff",
        "axes.facecolor":   "#ffffff",
        "axes.edgecolor":   "#222222",
        "axes.labelcolor":  "#222222",
        "xtick.color":      "#333333",
        "ytick.color":      "#333333",
        "text.color":       "#222222",
        "grid.color":       "#d9dde3",
        "grid.linewidth":   0.7,
        "legend.facecolor": "#ffffff",
        "legend.edgecolor": "#c8cdd6",
        "legend.labelcolor": "#222222",
        "font.size":        10,
        "axes.titlesize":   12,
        "axes.titleweight": "bold",
        "axes.spines.top":  False,
        "axes.spines.right": False,
        "savefig.facecolor": "#ffffff",
    })


def _save_fig(fig: "plt.Figure", path: Path, formats: list[str]) -> None:
    for fmt in formats:
        out = path.with_suffix(f".{fmt}")
        fig.savefig(out, dpi=_FIG_DPI, bbox_inches="tight")
        print(f"  Saved: {out.name}")
    plt.close(fig)


# â”€â”€ Analytical helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _rolling_mean(vals: list[float], window: int) -> list[float]:
    result: list[float] = []
    for i in range(len(vals)):
        chunk = vals[max(0, i - window + 1) : i + 1]
        result.append(sum(chunk) / len(chunk))
    return result


def _bucket_by_integer_second(
    durations: list[float], detected: list[int]
) -> tuple[list[int], list[float], list[int]]:
    """Aggregate trials by floored-to-integer attack duration.

    Each duration is floored to an integer second (e.g. 2.7 s â†’ bucket 2).
    Returns (seconds, rate_pct, counts) sorted by second value; empty buckets
    are omitted.
    """
    bucket_det: dict[int, list[int]] = {}
    for dur, det in zip(durations, detected):
        bucket = int(dur)  # floor to integer second
        if bucket not in bucket_det:
            bucket_det[bucket] = []
        bucket_det[bucket].append(det)

    sorted_seconds = sorted(bucket_det.keys())
    rates = [
        sum(bucket_det[s]) / len(bucket_det[s]) * 100
        for s in sorted_seconds
    ]
    counts = [len(bucket_det[s]) for s in sorted_seconds]
    return sorted_seconds, rates, counts


def _bucket_by_duration_interval(
    durations: list[float], detected: list[int]
) -> tuple[list[str], list[float], list[int]]:
    """Aggregate trials into short duration intervals."""
    if not durations:
        return [], [], []

    min_d = min(durations)
    max_d = max(durations)
    span = max_d - min_d
    if span <= 0:
        label = f"{min_d:.1f}-{max_d:.1f}s"
        rate = sum(detected) / len(detected) * 100 if detected else 0.0
        return [label], [rate], [len(detected)]

    target_bins = min(12, max(6, int(len(durations) ** 0.5) + 3))
    raw_width = span / target_bins
    if raw_width <= 0.25:
        width = 0.25
    elif raw_width <= 0.5:
        width = 0.5
    elif raw_width <= 1.0:
        width = 1.0
    elif raw_width <= 2.0:
        width = 2.0
    else:
        width = 5.0

    start = int(min_d / width) * width
    bucket_det: dict[int, list[int]] = {}
    for dur, det in zip(durations, detected):
        bucket = int((dur - start) / width)
        if bucket not in bucket_det:
            bucket_det[bucket] = []
        bucket_det[bucket].append(det)

    sorted_buckets = sorted(bucket_det.keys())
    labels: list[str] = []
    rates = [
        sum(bucket_det[b]) / len(bucket_det[b]) * 100
        for b in sorted_buckets
    ]
    counts = [len(bucket_det[b]) for b in sorted_buckets]
    for b in sorted_buckets:
        lo = start + b * width
        hi = lo + width
        labels.append(f"{lo:.1f}-{hi:.1f}s")
    return labels, rates, counts


def _placeholder_fig(
    title: str, message: str, out_dir: Path, stem: str, formats: list[str]
) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.text(0.5, 0.5, message, transform=ax.transAxes,
            ha="center", va="center", fontsize=11, color="#888888",
            multialignment="center")
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    _save_fig(fig, out_dir / stem, formats)


# â”€â”€ Randomized trial plot functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def plot_trial_outcomes(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F1: Four-category bar chart of trial outcomes.

    Categories:
      detected_attack  -- real attack, system raised alert
      missed_attack    -- real attack, system silent  (false negative)
      false_positive   -- no_attack trial, system raised alert
      clean_no_attack  -- no_attack trial, system silent  (correct)

    Excluded rows are not counted. no_attack trials are negative controls;
    clean no_attack is NOT a missed attack.
    """
    valid = [r for r in rows if not _is_excluded(r)]

    counts: dict[str, int] = {cat: 0 for cat in _OUTCOME_LABELS}
    for r in valid:
        counts[_outcome_category(r)] += 1

    categories = list(_OUTCOME_LABELS.keys())
    labels = [_OUTCOME_LABELS[c] for c in categories]
    values = [counts[c] for c in categories]
    colors = [_OUTCOME_COLORS[c] for c in categories]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(labels, values, color=colors, alpha=0.85, width=0.55)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.25,
            str(val),
            ha="center", va="bottom", fontsize=11, color="#222222",
        )
    ax.set_ylabel("Trial count")
    ax.set_title(f"F1 â€” Trial Outcomes  (n={len(valid)})")
    ax.set_ylim(0, max(values, default=1) * 1.35)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=0.4)
    plt.xticks(rotation=15, ha="right")
    fig.tight_layout()
    _save_fig(fig, out_dir / "f1_trial_outcomes", formats)


def plot_detection_timeline(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F2: Rolling detection rate by trial sequence.

    This figure intentionally keeps the story simple:
    - x-axis: attack-trial sequence
    - y-axis: rolling detection rate (%)

    no_attack trials are excluded from the detection-rate denominator and are
    not shown as separate points.
    """
    valid = [r for r in rows if not _is_excluded(r)]
    if not valid:
        _placeholder_fig(
            "F2 â€” Detection Timeline",
            "No valid trial data available.",
            out_dir, "f2_detection_timeline", formats,
        )
        return

    def _trial_num(r: dict[str, Any]) -> float:
        v = _coerce_float(r.get("trial_number"))
        return v if v is not None else float("inf")
    valid.sort(key=_trial_num)

    attack_rows = [r for r in valid if not _is_no_attack(r)]
    attack_detected = [
        1.0 if _parse_bool(r.get("detected", "False")) else 0.0
        for r in attack_rows
    ]
    n_attack = len(attack_detected)
    if n_attack == 0:
        _placeholder_fig(
            "F2 â€” Detection Timeline",
            "No real attack trials found  (no_attack trials are excluded).",
            out_dir, "f2_detection_timeline", formats,
        )
        return

    xs = list(range(1, n_attack + 1))
    window = max(3, min(10, max(n_attack // 5, 1)))
    roll = _rolling_mean(attack_detected, window)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(
        xs, [v * 100 for v in roll],
        color="#3a8fcc", linewidth=2.4, zorder=3,
    )
    ax.fill_between(xs, [v * 100 for v in roll], alpha=0.12, color="#3a8fcc")
    ax.axhline(50, color="#d9dde3", linewidth=0.8, linestyle="--")
    ax.set_ylim(0, 105)
    ax.set_xlim(1, max(xs))
    ax.set_ylabel("Detection rate (%)")
    ax.set_xlabel("Trial sequence")
    ax.set_title(f"F2 â€” Rolling Detection Rate by Trial Sequence  (window={window}, attack trials only)")
    ax.grid(alpha=0.25, axis="y")

    fig.tight_layout()
    _save_fig(fig, out_dir / "f2_detection_timeline", formats)


def plot_duration_detection_rate(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F3: Detection rate by attack duration interval."""
    pts = [
        (r, _coerce_float(r.get("duration_s")))
        for r in rows
        if not _is_excluded(r) and not _is_no_attack(r)
    ]
    pts = [(r, d) for r, d in pts if d is not None]

    if len(pts) < 2:
        _placeholder_fig(
            "F3 â€” Duration vs Detection Rate",
            "Insufficient attack trial data  (need â‰¥ 2 trials with duration).",
            out_dir, "f3_duration_detection_rate", formats,
        )
        return

    durations = [d for _, d in pts]
    detected_flags = [1 if _parse_bool(r.get("detected", "False")) else 0 for r, _ in pts]
    labels, rates, counts = _bucket_by_duration_interval(durations, detected_flags)

    if not labels:
        _placeholder_fig(
            "F3 â€” Duration vs Detection Rate",
            "No buckets produced from duration data.",
            out_dir, "f3_duration_detection_rate", formats,
        )
        return

    x = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.85), 5))
    bars = ax.bar(x, rates, color="#3a8fcc", alpha=0.84, width=0.62)

    for bar, rate, cnt in zip(bars, rates, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            rate + 2.5,
            f"{rate:.0f}%\nn={cnt}",
            ha="center", va="bottom", fontsize=8, color="#555555",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_xlabel("Attack duration interval")
    ax.set_ylabel("Detection rate (%)")
    ax.set_title(
        "F3 - Detection Rate by Attack Duration Interval  "
        "(attack trials only, n={})".format(len(pts))
    )
    ax.set_ylim(0, 125)
    ax.axhline(100, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax.grid(alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f3_duration_detection_rate", formats)



def plot_detection_by_strategy(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F4: Detection rate by attack strategy -- bar chart.

    Only real attack trials are counted (no_attack excluded from denominator).
    Each bar shows the strategy-level detection rate; n= annotates the trial count.
    """
    valid = [r for r in rows if not _is_excluded(r) and not _is_no_attack(r)]
    strategies = _sorted_strategies(valid) if valid else []

    if not strategies:
        _placeholder_fig(
            "F4 â€” Detection Rate by Strategy",
            "No valid attack trial data available.",
            out_dir, "f4_detection_by_strategy", formats,
        )
        return

    rates: list[float] = []
    counts: list[int] = []
    for strat in strategies:
        s_rows = [r for r in valid if str(r.get("attack_strategy", "")) == strat]
        s_det = sum(1 for r in s_rows if _parse_bool(r.get("detected", "False")))
        rates.append(s_det / len(s_rows) * 100 if s_rows else 0.0)
        counts.append(len(s_rows))

    colors = [_STRATEGY_COLORS.get(s, "#555555") for s in strategies]
    fig, ax = plt.subplots(figsize=(max(6, len(strategies) * 1.4), 5))
    bars = ax.bar(strategies, rates, color=colors, alpha=0.85, width=0.6)
    for bar, rate, cnt in zip(bars, rates, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{rate:.0f}%\n(n={cnt})",
            ha="center", va="bottom", fontsize=9, color="#222222",
        )
    ax.set_ylabel("Detection rate  (%)")
    ax.set_ylim(0, 130)
    ax.set_xlabel("Attack strategy")
    ax.set_title("F4 â€” Detection Rate by Strategy  (attack trials only)")
    ax.axhline(100, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax.grid(axis="y", alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f4_detection_by_strategy", formats)


def plot_undetected_impact(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F5: Undetected physical impact rate by strategy (among missed attacks).

    For each strategy, computes:
      undetected_impact_rate = (missed trials with undetected_physical_impact==True)
                               / (total missed trials for that strategy) * 100

    Denominator: missed real attack trials per strategy.
    no_attack trials and detected attacks are excluded throughout.
    Strategies with zero missed attacks are omitted from the plot.
    """
    valid = [r for r in rows if not _is_excluded(r) and not _is_no_attack(r)]
    missed = [r for r in valid if not _parse_bool(r.get("detected", "False"))]

    strategies = _sorted_strategies(valid) if valid else []
    # Keep only strategies that have at least one missed trial
    strategies = [
        s for s in strategies
        if any(str(r.get("attack_strategy", "")) == s for r in missed)
    ]

    if not strategies:
        _placeholder_fig(
            "F5 â€” Undetected Physical Impact Rate",
            "No missed attack trials available.",
            out_dir, "f5_undetected_impact", formats,
        )
        return

    rates: list[float] = []
    counts: list[int] = []
    for strat in strategies:
        s_missed = [r for r in missed if str(r.get("attack_strategy", "")) == strat]
        s_impact = sum(
            1 for r in s_missed
            if _parse_bool(r.get("undetected_physical_impact", "False"))
        )
        rates.append(s_impact / len(s_missed) * 100)
        counts.append(len(s_missed))

    colors = [_STRATEGY_COLORS.get(s, "#555555") for s in strategies]
    fig, ax = plt.subplots(figsize=(max(6, len(strategies) * 1.4), 5))
    bars = ax.bar(strategies, rates, color=colors, alpha=0.85, width=0.6)
    for bar, rate, cnt in zip(bars, rates, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.5,
            f"{rate:.0f}%\n(n={cnt})",
            ha="center", va="bottom", fontsize=9, color="#222222",
        )
    ax.set_ylabel("Undetected impact rate  (%)")
    ax.set_ylim(0, 130)
    ax.set_xlabel("Attack strategy")
    ax.set_title(
        "F5 â€” Undetected Physical Impact Rate by Strategy  (among missed attacks)"
    )
    ax.axhline(100, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax.grid(axis="y", alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f5_undetected_impact", formats)


def plot_false_positive_summary(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F6: False positive rate on no_attack (negative control) trials.

    Shows clean vs false-positive outcomes for no_attack trials only.
    A high FP rate indicates the system raises alerts without any active attack.
    """
    valid = [r for r in rows if not _is_excluded(r)]
    no_attack_rows = [r for r in valid if _is_no_attack(r)]

    if not no_attack_rows:
        _placeholder_fig(
            "F6 â€” False Positive Summary",
            "No no_attack (negative control) trials found.",
            out_dir, "f6_false_positive_summary", formats,
        )
        return

    fp_count = sum(
        1 for r in no_attack_rows if _parse_bool(r.get("detected", "False"))
    )
    clean_count = len(no_attack_rows) - fp_count
    fp_rate = fp_count / len(no_attack_rows) * 100

    labels = ["Clean (no alert)", "False Positive (alert)"]
    values = [clean_count, fp_count]
    colors = [_OUTCOME_COLORS["clean_no_attack"], _OUTCOME_COLORS["false_positive"]]

    fig, ax = plt.subplots(figsize=(6, 4.5))
    bars = ax.bar(labels, values, color=colors, alpha=0.85, width=0.5)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.15,
            str(val),
            ha="center", va="bottom", fontsize=11, color="#222222",
        )
    ax.set_ylabel("Trial count")
    ax.set_title(
        "F6 â€” False Positive Summary  "
        "(n={} no-attack trials,  FP rate={:.1f}%)".format(len(no_attack_rows), fp_rate)
    )
    ax.set_ylim(0, max(values, default=1) * 1.40)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=0.4)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f6_false_positive_summary", formats)


def plot_ttd_by_strategy(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F7: Time-to-detection by strategy (detected attacks only).

    Box plot with jitter scatter overlay.  Only real attack trials that were
    detected contribute.  no_attack trials and undetected attacks are excluded.
    Answers: "How quickly does TwinGuard detect attacks when it does detect them?"
    """
    detected = [
        r for r in rows
        if not _is_excluded(r)
        and not _is_no_attack(r)
        and _parse_bool(r.get("detected", "False"))
    ]

    if not detected:
        _placeholder_fig(
            "F7 â€” Time to Detection by Strategy",
            "No detected attack trials available.",
            out_dir, "f7_ttd_by_strategy", formats,
        )
        return

    strategies = _sorted_strategies(detected)
    ttd_by_strat: dict[str, list[float]] = {}
    for strat in strategies:
        vals = [
            v for v in (
                _coerce_float(r.get("time_to_detection_s"))
                for r in detected
                if str(r.get("attack_strategy", "")) == strat
            )
            if v is not None
        ]
        if vals:
            ttd_by_strat[strat] = vals

    if not ttd_by_strat:
        _placeholder_fig(
            "F7 â€” Time to Detection by Strategy",
            "No TTD data available for detected attacks.",
            out_dir, "f7_ttd_by_strategy", formats,
        )
        return

    labels = [s for s in strategies if s in ttd_by_strat]
    data = [ttd_by_strat[s] for s in labels]
    colors = [_STRATEGY_COLORS.get(s, "#555555") for s in labels]

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.6), 5.5))

    bp = ax.boxplot(
        data, tick_labels=labels, patch_artist=True,
        notch=False, widths=0.45, zorder=2,
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    for median in bp["medians"]:
        median.set_color("#ffffff")
        median.set_linewidth(1.8)
    for whisker in bp["whiskers"]:
        whisker.set_color("#555555")
    for cap in bp["caps"]:
        cap.set_color("#555555")
    for flier in bp["fliers"]:
        flier.set(marker="o", markerfacecolor="#ff3060", markersize=5, alpha=0.6)

    # Deterministic jitter scatter overlay
    _jitter_rng = random.Random(0)
    for i, (strat, vals) in enumerate(zip(labels, data), start=1):
        jxs = [i + _jitter_rng.uniform(-0.18, 0.18) for _ in vals]
        ax.scatter(
            jxs, vals,
            color=_STRATEGY_COLORS.get(strat, "#555555"),
            alpha=0.70, s=25, zorder=3, edgecolors="none",
        )

    # n= annotation above each group
    all_vals_flat = [v for vals in data for v in vals]
    y_top = max(all_vals_flat) if all_vals_flat else 1.0
    for i, (strat, vals) in enumerate(zip(labels, data), start=1):
        ax.text(
            i, y_top * 1.08,
            f"n={len(vals)}",
            ha="center", va="bottom", fontsize=8, color="#555555",
        )

    ax.set_ylabel("Time to first detection (s)")
    ax.set_xlabel("Attack strategy")
    ax.set_title("F7 â€” Time to Detection by Strategy  (detected attacks only)")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f7_ttd_by_strategy", formats)


def plot_strategy_outcome_stack(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F7: 100% stacked outcome composition by attack strategy."""
    attack_rows = [
        r for r in rows if not _is_excluded(r) and not _is_no_attack(r)
    ]
    strategies = _sorted_strategies(attack_rows) if attack_rows else []

    if not strategies:
        _placeholder_fig(
            "F7 - Strategy Outcome Stack",
            "No valid attack trial data available.",
            out_dir, "f7_strategy_outcome_stack", formats,
        )
        return

    detected_counts: list[int] = []
    missed_no_impact_counts: list[int] = []
    missed_impact_counts: list[int] = []
    for strat in strategies:
        s_rows = [r for r in attack_rows if str(r.get("attack_strategy", "")) == strat]
        det = sum(1 for r in s_rows if _parse_bool(r.get("detected", "False")))
        missed = [r for r in s_rows if not _parse_bool(r.get("detected", "False"))]
        harmful = sum(
            1 for r in missed
            if _parse_bool(r.get("undetected_physical_impact", "False"))
        )
        detected_counts.append(det)
        missed_no_impact_counts.append(len(missed) - harmful)
        missed_impact_counts.append(harmful)

    totals = [
        det + miss_no + miss_imp
        for det, miss_no, miss_imp
        in zip(detected_counts, missed_no_impact_counts, missed_impact_counts)
    ]
    detected_pct = [
        det / total * 100 if total else 0.0
        for det, total in zip(detected_counts, totals)
    ]
    missed_no_impact_pct = [
        miss / total * 100 if total else 0.0
        for miss, total in zip(missed_no_impact_counts, totals)
    ]
    missed_impact_pct = [
        miss / total * 100 if total else 0.0
        for miss, total in zip(missed_impact_counts, totals)
    ]

    x = list(range(len(strategies)))
    fig, ax = plt.subplots(figsize=(max(8, len(strategies) * 1.35), 5.8))
    ax.bar(
        x, detected_pct, label="Detected attack",
        color=_OUTCOME_COLORS["detected_attack"], alpha=0.88,
    )
    ax.bar(
        x, missed_no_impact_pct, bottom=detected_pct,
        label="Missed without physical impact", color="#e6b400", alpha=0.86,
    )
    impact_bottom = [
        det + miss for det, miss in zip(detected_pct, missed_no_impact_pct)
    ]
    ax.bar(
        x, missed_impact_pct, bottom=impact_bottom,
        label="Missed with physical impact",
        color=_OUTCOME_COLORS["missed_attack"], alpha=0.90,
    )

    for i, total in enumerate(totals):
        ax.text(
            i, 102, f"n={total}",
            ha="center", va="bottom", fontsize=8, color="#222222",
        )
        segments = [
            (detected_pct[i], 0.0),
            (missed_no_impact_pct[i], detected_pct[i]),
            (missed_impact_pct[i], impact_bottom[i]),
        ]
        for pct, bottom in segments:
            if pct < 6.0:
                continue
            ax.text(
                i, bottom + pct / 2,
                f"{pct:.0f}%",
                ha="center", va="center", fontsize=9,
                color="#111111", fontweight="bold",
            )

    ax.set_xticks(x)
    ax.set_xticklabels(strategies, rotation=35, ha="right")
    ax.set_ylabel("Share of strategy trials (%)")
    ax.set_xlabel("Attack strategy")
    ax.set_title("F7 - Stacked Attack Outcome Percentages by Strategy")
    ax.set_ylim(0, 112)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
    ax.grid(axis="y", alpha=0.35)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.18),
        ncol=3,
        fontsize=9,
        framealpha=0.92,
    )
    fig.subplots_adjust(top=0.78, bottom=0.22, left=0.08, right=0.98)
    _save_fig(fig, out_dir / "f7_strategy_outcome_stack", formats)


def plot_risk_vs_detection(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F8: Risk-assigned attack count vs detected count by risk level.

    Only real attack trials are counted. no_attack rows are excluded because
    their detections are false positives, not attack detections.
    """
    attack_rows = [
        r for r in rows if not _is_excluded(r) and not _is_no_attack(r)
    ]
    levels = [
        level for level in _LEVEL_ORDER
        if any(str(r.get("worst_risk_level", "low")).lower() == level for r in attack_rows)
    ]

    if not levels:
        _placeholder_fig(
            "F8 - Risk vs Detection",
            "No valid attack trial data available.",
            out_dir, "f8_risk_vs_detection", formats,
        )
        return

    total_counts: list[int] = []
    detected_counts: list[int] = []
    detection_rates: list[float] = []
    for level in levels:
        level_rows = [
            r for r in attack_rows
            if str(r.get("worst_risk_level", "low")).lower() == level
        ]
        det = sum(1 for r in level_rows if _parse_bool(r.get("detected", "False")))
        total = len(level_rows)
        total_counts.append(total)
        detected_counts.append(det)
        detection_rates.append(det / total * 100 if total else 0.0)

    x = list(range(len(levels)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(max(7, len(levels) * 1.5), 5.2))
    ax.bar(
        [i - width / 2 for i in x], total_counts, label="Given this risk level",
        color="#4e9af1", alpha=0.78, width=width,
    )
    ax.bar(
        [i + width / 2 for i in x], detected_counts, label="Detected",
        color=_OUTCOME_COLORS["detected_attack"], alpha=0.88, width=width,
    )

    for i, (total, det, rate) in enumerate(zip(total_counts, detected_counts, detection_rates)):
        ax.text(
            i, max(total, det) + 0.25,
            f"{det}/{total}\n{rate:.0f}%",
            ha="center", va="bottom", fontsize=9, color="#222222",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(levels)
    ax.set_ylabel("Attack trial count")
    ax.set_xlabel("Worst risk level")
    ax.set_title("F8 - Risk Assignment vs Detection  (attack trials only)")
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=0.35)
    ax.legend(loc="upper left")
    fig.tight_layout()
    _save_fig(fig, out_dir / "f8_risk_vs_detection", formats)


def plot_detection_by_attack_category(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F9: Detection rate by attack family and sub-attack type.

    The top panel compares broad attack families. The bottom panel compares
    family/strategy combinations such as velocity_spoof/near_threshold.
    """
    attack_rows = [
        r for r in rows if not _is_excluded(r) and not _is_no_attack(r)
    ]
    categories = _sorted_attack_categories(attack_rows)
    subcategories = _sorted_attack_subcategories(attack_rows)

    if not categories:
        _placeholder_fig(
            "F9 - Detection by Attack Type",
            "No valid attack trial data available.",
            out_dir, "f9_detection_by_attack_category", formats,
        )
        return

    category_rates: list[float] = []
    category_counts: list[int] = []
    category_colors: list[str] = []
    for category in categories:
        c_rows = [r for r in attack_rows if _attack_category(r) == category]
        det = sum(1 for r in c_rows if _parse_bool(r.get("detected", "False")))
        category_rates.append(det / len(c_rows) * 100 if c_rows else 0.0)
        category_counts.append(len(c_rows))
        category_colors.append("#4e9af1" if category == "velocity_spoof" else "#ff8c00")

    sub_rates: list[float] = []
    sub_counts: list[int] = []
    sub_colors: list[str] = []
    for label in subcategories:
        s_rows = [r for r in attack_rows if _attack_subcategory(r) == label]
        det = sum(1 for r in s_rows if _parse_bool(r.get("detected", "False")))
        family, _, strategy = label.partition("\n")
        color = _STRATEGY_COLORS.get(strategy, "#555555")
        if family == "false_brake":
            color = "#ff8c00"
        sub_rates.append(det / len(s_rows) * 100 if s_rows else 0.0)
        sub_counts.append(len(s_rows))
        sub_colors.append(color)

    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1,
        figsize=(max(8, len(subcategories) * 1.35), 8.2),
        gridspec_kw={"height_ratios": [1, 1.45]},
    )

    top_bars = ax_top.bar(
        categories, category_rates, color=category_colors, alpha=0.85, width=0.55
    )
    for bar, rate, cnt in zip(top_bars, category_rates, category_counts):
        ax_top.text(
            bar.get_x() + bar.get_width() / 2,
            rate + 1.5,
            f"{rate:.0f}%\n(n={cnt})",
            ha="center", va="bottom", fontsize=9, color="#222222",
        )
    ax_top.set_ylabel("Detection rate (%)")
    ax_top.set_title("F9 - Detection Rate by Attack Category and Sub-Type  (attack trials only)")
    ax_top.set_ylim(0, 130)
    ax_top.axhline(100, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax_top.grid(axis="y", alpha=0.35)

    bottom_bars = ax_bottom.bar(
        subcategories, sub_rates, color=sub_colors, alpha=0.85, width=0.58
    )
    for bar, rate, cnt in zip(bottom_bars, sub_rates, sub_counts):
        ax_bottom.text(
            bar.get_x() + bar.get_width() / 2,
            rate + 1.5,
            f"{rate:.0f}%\n(n={cnt})",
            ha="center", va="bottom", fontsize=8, color="#222222",
        )
    ax_bottom.set_ylabel("Detection rate (%)")
    ax_bottom.set_xlabel("Attack category / strategy")
    ax_bottom.set_ylim(0, 130)
    ax_bottom.axhline(100, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax_bottom.grid(axis="y", alpha=0.35)
    ax_bottom.tick_params(axis="x", labelrotation=35)
    for tick in ax_bottom.get_xticklabels():
        tick.set_ha("right")

    fig.tight_layout()
    _save_fig(fig, out_dir / "f9_detection_by_attack_category", formats)


def plot_ttd_by_attack_subcategory(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F10: Time-to-detection by attack family and subcategory/strategy.

    Only detected real attacks with TTD values contribute. Labels combine
    attack_family and attack_strategy, e.g. velocity_spoof/near_threshold.
    """
    detected = [
        r for r in rows
        if not _is_excluded(r)
        and not _is_no_attack(r)
        and _parse_bool(r.get("detected", "False"))
        and _coerce_float(r.get("time_to_detection_s")) is not None
    ]

    if not detected:
        _placeholder_fig(
            "F10 - TTD by Attack Subcategory",
            "No TTD data available for detected attacks.",
            out_dir, "f10_ttd_by_attack_subcategory", formats,
        )
        return

    labels = _sorted_attack_subcategories(detected)
    ttd_by_label: dict[str, list[float]] = {}
    for label in labels:
        vals = [
            v for v in (
                _coerce_float(r.get("time_to_detection_s"))
                for r in detected
                if _attack_subcategory(r) == label
            )
            if v is not None
        ]
        if vals:
            ttd_by_label[label] = vals

    labels = [label for label in labels if label in ttd_by_label]
    data = [ttd_by_label[label] for label in labels]

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 1.45), 5.8))
    bp = ax.boxplot(
        data, tick_labels=labels, patch_artist=True,
        notch=False, widths=0.45, zorder=2,
    )
    for patch, label in zip(bp["boxes"], labels):
        family, _, strategy = label.partition("\n")
        color = _STRATEGY_COLORS.get(strategy, "#555555")
        if family == "false_brake":
            color = "#ff8c00"
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    for median in bp["medians"]:
        median.set_color("#ffffff")
        median.set_linewidth(1.8)
    for whisker in bp["whiskers"]:
        whisker.set_color("#555555")
    for cap in bp["caps"]:
        cap.set_color("#555555")

    _jitter_rng = random.Random(1)
    for i, (label, vals) in enumerate(zip(labels, data), start=1):
        family, _, strategy = label.partition("\n")
        color = _STRATEGY_COLORS.get(strategy, "#555555")
        if family == "false_brake":
            color = "#ff8c00"
        jxs = [i + _jitter_rng.uniform(-0.18, 0.18) for _ in vals]
        ax.scatter(
            jxs, vals, color=color, alpha=0.72, s=25, zorder=3,
            edgecolors="none",
        )

    all_vals = [v for vals in data for v in vals]
    y_top = max(all_vals) if all_vals else 1.0
    for i, vals in enumerate(data, start=1):
        ax.text(
            i, y_top * 1.08,
            f"n={len(vals)}",
            ha="center", va="bottom", fontsize=8, color="#555555",
        )

    ax.set_ylabel("Time to first detection (s)")
    ax.set_xlabel("Attack category / strategy")
    ax.set_title("F10 - Time to Detection by Attack Subcategory  (detected attacks only)")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f10_ttd_by_attack_subcategory", formats)


def plot_strategy_risk_map(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F10: Strategy risk map: detection rate vs miss rate."""
    attack_rows = [
        r for r in rows if not _is_excluded(r) and not _is_no_attack(r)
    ]
    strategies = _sorted_strategies(attack_rows) if attack_rows else []
    if not strategies:
        _placeholder_fig(
            "F10 - Strategy Risk Map",
            "No valid attack trial data available.",
            out_dir, "f10_strategy_risk_map", formats,
        )
        return

    xs: list[float] = []
    ys: list[float] = []
    sizes: list[float] = []
    colors: list[str] = []
    labels: list[str] = []
    for strat in strategies:
        s_rows = [r for r in attack_rows if str(r.get("attack_strategy", "")) == strat]
        detected = sum(1 for r in s_rows if _parse_bool(r.get("detected", "False")))
        missed = len(s_rows) - detected
        total = len(s_rows)
        xs.append(detected / total * 100 if total else 0.0)
        ys.append(missed / total * 100 if total else 0.0)
        sizes.append(120 + total * 45)
        colors.append(_STRATEGY_COLORS.get(strat, "#555555"))
        labels.append(f"{strat}\nn={total}")

    fig, ax = plt.subplots(figsize=(8, 5.8))
    ax.scatter(xs, ys, s=sizes, c=colors, alpha=0.72, edgecolors="#555555", linewidths=1.0)
    for x, y, label in zip(xs, ys, labels):
        ax.text(x + 1.5, y + 1.5, label, fontsize=8, color="#222222")

    ax.set_xlim(-3, 103)
    ax.set_ylim(-3, 103)
    ax.set_xlabel("Detection rate (%)")
    ax.set_ylabel("Missed attacks (%)")
    ax.set_title("F10 - Detection Rate vs Miss Rate by Strategy")
    ax.axvline(80, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax.axhline(20, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax.grid(alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f10_strategy_risk_map", formats)


def plot_detection_rate_sensitivity(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F11: Highest achievable detection rate under transparent filters."""
    attack_rows = [
        r for r in rows if not _is_excluded(r) and not _is_no_attack(r)
    ]
    if not attack_rows:
        _placeholder_fig(
            "F11 - Detection Rate Sensitivity",
            "No valid attack trial data available.",
            out_dir, "f11_detection_rate_sensitivity", formats,
        )
        return

    def _rate(subset: list[dict[str, Any]]) -> float:
        if not subset:
            return 0.0
        detected = sum(1 for r in subset if _parse_bool(r.get("detected", "False")))
        return detected / len(subset) * 100

    def _short_list(values: tuple[str, ...], max_items: int = 3) -> str:
        clean = [v.replace("_", " ") for v in values]
        if len(clean) <= max_items:
            return " + ".join(clean)
        return " + ".join(clean[:max_items]) + f" +{len(clean) - max_items}"

    def _best_strategy_subset(min_fraction: float) -> tuple[str, list[dict[str, Any]]] | None:
        strategies = sorted({str(r.get("attack_strategy", "")) for r in attack_rows})
        min_count = max(1, int(len(attack_rows) * min_fraction + 0.999))
        best: tuple[float, int, tuple[str, ...], list[dict[str, Any]]] | None = None
        for size in range(1, len(strategies) + 1):
            for combo in itertools.combinations(strategies, size):
                subset = [
                    r for r in attack_rows
                    if str(r.get("attack_strategy", "")) in combo
                ]
                if len(subset) < min_count:
                    continue
                candidate = (_rate(subset), len(subset), combo, subset)
                if best is None or candidate[0] > best[0] or (
                    candidate[0] == best[0] and candidate[1] > best[1]
                ):
                    best = candidate
        if best is None:
            return None
        _, _, combo, subset = best
        return (_short_list(combo), subset)

    def _best_single(field: str) -> tuple[str, list[dict[str, Any]]] | None:
        values = sorted({str(r.get(field, "")) for r in attack_rows})
        best: tuple[float, int, str, list[dict[str, Any]]] | None = None
        for value in values:
            subset = [r for r in attack_rows if str(r.get(field, "")) == value]
            candidate = (_rate(subset), len(subset), value, subset)
            if best is None or candidate[0] > best[0] or (
                candidate[0] == best[0] and candidate[1] > best[1]
            ):
                best = candidate
        if best is None:
            return None
        _, _, value, subset = best
        return (value.replace("_", " "), subset)

    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in attack_rows:
        by_family.setdefault(_attack_category(row), []).append(row)
    best_family = max(
        by_family.items(),
        key=lambda item: (_rate(item[1]), len(item[1])),
        default=None,
    )

    scenarios: list[tuple[str, list[dict[str, Any]]]] = [
        ("All", attack_rows),
    ]
    best_single_strategy = _best_single("attack_strategy")
    if best_single_strategy is not None:
        label, subset = best_single_strategy
        scenarios.append((f"Only strategy: {label}", subset))
    if best_family is not None:
        family, subset = best_family
        scenarios.append((f"Only family: {family.replace('_', ' ')}", subset))
    best_25 = _best_strategy_subset(0.25)
    if best_25 is not None:
        label, subset = best_25
        scenarios.append((f"Only selected strategies: {label}", subset))
    best_50 = _best_strategy_subset(0.50)
    if best_50 is not None:
        label, subset = best_50
        scenarios.append((f"Only larger strategy group: {label}", subset))

    strategies_by_rate = sorted(
        {
            str(r.get("attack_strategy", ""))
            for r in attack_rows
        },
        key=lambda s: _rate([r for r in attack_rows if str(r.get("attack_strategy", "")) == s]),
    )
    if strategies_by_rate:
        worst = strategies_by_rate[0]
        scenarios.append((
            f"All except weakest: {worst.replace('_', ' ')}",
            [r for r in attack_rows if str(r.get("attack_strategy", "")) != worst],
        ))
    if len(strategies_by_rate) >= 2:
        worst_two = tuple(strategies_by_rate[:2])
        scenarios.append((
            "All except weakest two: " + _short_list(worst_two, max_items=2),
            [
                r for r in attack_rows
                if str(r.get("attack_strategy", "")) not in worst_two
            ],
        ))

    labels: list[str] = []
    rates: list[float] = []
    counts: list[int] = []
    for label, subset in scenarios:
        if not subset:
            continue
        labels.append(label)
        rates.append(_rate(subset))
        counts.append(len(subset))

    if not labels:
        _placeholder_fig(
            "F11 - Detection Rate Sensitivity",
            "No non-empty comparison groups available.",
            out_dir, "f11_detection_rate_sensitivity", formats,
        )
        return

    colors = ["#8aa0b4"] + ["#4e9af1"] * (len(labels) - 1)
    if len(colors) > 1:
        max_rate = max(rates[1:], default=rates[0])
        colors = [
            "#8aa0b4" if i == 0 else (
                "#00c878" if rate == max_rate else "#4e9af1"
            )
            for i, rate in enumerate(rates)
        ]
    y_positions = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(10, max(5.0, len(labels) * 0.55 + 1.2)))
    bars = ax.barh(y_positions, rates, color=colors, alpha=0.86, height=0.62)
    for bar, rate, count in zip(bars, rates, counts):
        ax.text(
            min(rate + 1.5, 99),
            bar.get_y() + bar.get_height() / 2,
            f"{rate:.0f}% (n={count})",
            ha="left", va="center", fontsize=9, color="#222222",
        )
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Detection rate (%)")
    ax.set_title("F11 - Detection Rate After Filtering Attack Types")
    ax.set_xlim(0, 110)
    ax.axvline(100, color="#c8cdd6", linewidth=0.8, linestyle="--")
    ax.grid(axis="x", alpha=0.35)
    fig.subplots_adjust(left=0.36, right=0.95, top=0.90, bottom=0.12)
    _save_fig(fig, out_dir / "f11_detection_rate_sensitivity", formats)


def plot_ttd_ecdf(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """F12: Cumulative distribution of time-to-detection."""
    ttd_vals = sorted(
        v for v in (
            _coerce_float(r.get("time_to_detection_s"))
            for r in rows
            if not _is_excluded(r)
            and not _is_no_attack(r)
            and _parse_bool(r.get("detected", "False"))
        )
        if v is not None
    )
    if not ttd_vals:
        _placeholder_fig(
            "F12 - Time-to-Detection ECDF",
            "No TTD data available for detected attacks.",
            out_dir, "f12_ttd_ecdf", formats,
        )
        return

    n = len(ttd_vals)
    ys = [(i + 1) / n * 100 for i in range(n)]

    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.step(ttd_vals, ys, where="post", color="#00c878", linewidth=2.3)
    ax.scatter(ttd_vals, ys, color="#00c878", s=22, alpha=0.72)

    threshold_parts: list[str] = []
    for threshold in (0.1, 0.2, 0.5, 1.0):
        pct = sum(1 for v in ttd_vals if v <= threshold) / n * 100
        threshold_parts.append(f"{threshold:.1f}s: {pct:.0f}%")
        ax.axvline(threshold, color="#c8cdd6", linewidth=0.8, linestyle="--")

    ax.text(
        0.98, 0.05,
        "Detected by " + " | ".join(threshold_parts),
        transform=ax.transAxes, ha="right", va="bottom",
        fontsize=8, color="#222222",
        bbox={"facecolor": "#ffffff", "edgecolor": "#c8cdd6", "alpha": 0.85},
    )
    ax.set_xlabel("Time to first detection (s)")
    ax.set_ylabel("Detected attacks caught by this time (%)")
    ax.set_title("F12 - Time-to-Detection ECDF  (detected attacks only)")
    ax.set_ylim(0, 105)
    ax.set_xlim(left=0)
    ax.grid(alpha=0.35)
    fig.tight_layout()
    _save_fig(fig, out_dir / "f12_ttd_ecdf", formats)


# â”€â”€ Randomized trial summary JSON â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _write_randomized_summary_json(
    rows: list[dict[str, Any]],
    out_dir: Path,
    formats: list[str],
    baseline_speed: float,
    experiment_id: str,
) -> None:
    # Exclude invalid/excluded rows first
    valid = [r for r in rows if not _is_excluded(r)]

    # Separate real attack trials from no_attack negative controls
    attack_rows = [r for r in valid if not _is_no_attack(r)]
    no_attack_rows = [r for r in valid if _is_no_attack(r)]

    # Detection metrics are computed over ATTACK trials only
    detected_attack_rows = [
        r for r in attack_rows if _parse_bool(r.get("detected", "False"))
    ]
    missed_rows = [
        r for r in attack_rows if not _parse_bool(r.get("detected", "False"))
    ]
    fp_rows = [
        r for r in no_attack_rows if _parse_bool(r.get("detected", "False"))
    ]

    detection_rate = (
        len(detected_attack_rows) / len(attack_rows) if attack_rows else 0.0
    )

    ttd_vals = [
        v for v in (
            _coerce_float(r.get("time_to_detection_s")) for r in detected_attack_rows
        ) if v is not None
    ]
    mean_ttd: float | None = sum(ttd_vals) / len(ttd_vals) if ttd_vals else None
    sorted_ttd = sorted(ttd_vals)
    n = len(sorted_ttd)
    if n == 0:
        median_ttd: float | None = None
    elif n % 2 == 1:
        median_ttd = sorted_ttd[n // 2]
    else:
        median_ttd = (sorted_ttd[n // 2 - 1] + sorted_ttd[n // 2]) / 2.0

    # by_strategy: attack trials only (no_attack excluded)
    all_strategies = sorted(
        set(str(r.get("attack_strategy", "unknown")) for r in attack_rows)
    )
    by_strategy: dict[str, Any] = {}
    for s in all_strategies:
        s_rows = [r for r in attack_rows if str(r.get("attack_strategy", "")) == s]
        s_det = [r for r in s_rows if _parse_bool(r.get("detected", "False"))]
        s_ttd = [
            v for v in (
                _coerce_float(r.get("time_to_detection_s")) for r in s_det
            ) if v is not None
        ]
        by_strategy[s] = {
            "total": len(s_rows),
            "detected": len(s_det),
            "missed": len(s_rows) - len(s_det),
            "rate": len(s_det) / len(s_rows) if s_rows else 0.0,
            "false_negative_rate": (
                (len(s_rows) - len(s_det)) / len(s_rows) if s_rows else 0.0
            ),
            "mean_ttd_s": sum(s_ttd) / len(s_ttd) if s_ttd else None,
        }

    # by_attack_difficulty: attack trials only
    by_attack_difficulty: dict[str, Any] = {}
    for difficulty in _DIFFICULTY_ORDER:
        d_rows = [
            r for r in attack_rows
            if str(r.get("attack_difficulty", "")).lower() == difficulty
        ]
        d_det = sum(1 for r in d_rows if _parse_bool(r.get("detected", "False")))
        by_attack_difficulty[difficulty] = {
            "total": len(d_rows),
            "detected": d_det,
            "rate": d_det / len(d_rows) if d_rows else 0.0,
        }

    risk_dist: dict[str, int] = {l: 0 for l in _LEVEL_ORDER}
    for row in valid:
        lv = str(row.get("worst_risk_level", "low")).lower()
        if lv in risk_dist:
            risk_dist[lv] += 1

    figure_names = [
        "f1_trial_outcomes",
        "f2_detection_timeline",
        "f3_duration_detection_rate",
        "f4_detection_by_strategy",
        "f5_undetected_impact",
        "f6_false_positive_summary",
        "f7_strategy_outcome_stack",
        "f8_risk_vs_detection",
        "f9_detection_by_attack_category",
        "f10_strategy_risk_map",
        "f11_detection_rate_sensitivity",
        "f12_ttd_ecdf",
    ]
    figures = [f"{name}.{formats[0]}" for name in figure_names]

    summary = {
        "experiment_id": experiment_id,
        "total_trials": len(rows),
        "valid_trials": len(valid),
        "excluded_trials": len(rows) - len(valid),
        "attack_trials": len(attack_rows),
        "no_attack_trials": len(no_attack_rows),
        "detected_count": len(detected_attack_rows),
        "missed_count": len(missed_rows),
        "detection_rate": detection_rate,
        "false_negative_rate": 1.0 - detection_rate if attack_rows else 0.0,
        "no_attack_fp_count": len(fp_rows),
        "no_attack_fp_rate": (
            len(fp_rows) / len(no_attack_rows) if no_attack_rows else 0.0
        ),
        "mean_time_to_detection_s": mean_ttd,
        "median_time_to_detection_s": median_ttd,
        "baseline_speed_mps": baseline_speed,
        "by_strategy": by_strategy,
        "by_attack_difficulty": by_attack_difficulty,
        "risk_level_distribution": risk_dist,
        "figures": figures,
    }

    out_path = out_dir / "randomized_plot_summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  Saved: {out_path.name}")


# â”€â”€ Randomized trial orchestration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_randomized_plots(
    summary_csv: Path,
    output_dir: Path,
    formats: list[str],
    baseline_speed: float = 1.0,
) -> None:
    if not HAS_MPL:
        sys.exit(
            "matplotlib is required.\n"
            "Install it with:  pip install matplotlib\n"
            "Or:               pip install -r experiments/requirements.txt"
        )

    if not summary_csv.exists():
        sys.exit(
            f"trials_summary.csv not found: {summary_csv}\n"
            "Run run_randomized_trials.py first:\n"
            "  python experiments/run_randomized_trials.py "
            "--config experiments/scenarios/randomized_trials.yaml"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_style()

    rows = _load_csv(summary_csv)
    experiment_id = summary_csv.parent.name

    print(f"\nGenerating trial plots for: {experiment_id}")
    print(f"Input:  {summary_csv}")
    print(f"Output: {output_dir}")
    print()

    plot_trial_outcomes(rows, output_dir, formats)
    plot_detection_timeline(rows, output_dir, formats)
    plot_duration_detection_rate(rows, output_dir, formats)
    plot_detection_by_strategy(rows, output_dir, formats)
    plot_undetected_impact(rows, output_dir, formats)
    plot_false_positive_summary(rows, output_dir, formats)
    plot_strategy_outcome_stack(rows, output_dir, formats)
    plot_risk_vs_detection(rows, output_dir, formats)
    plot_detection_by_attack_category(rows, output_dir, formats)
    plot_strategy_risk_map(rows, output_dir, formats)
    plot_detection_rate_sensitivity(rows, output_dir, formats)
    plot_ttd_ecdf(rows, output_dir, formats)
    _write_randomized_summary_json(
        rows, output_dir, formats, baseline_speed, experiment_id
    )

    print(f"\nAll trial plots written to: {output_dir}")


# â”€â”€ Legacy fixed-campaign functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _scenario_order(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        sc = row["scenario_id"]
        if sc not in seen and not _is_excluded(row):
            seen.append(sc)
    return seen


def plot_risk_score(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """Bar chart: mean +/- std coarse risk score per scenario."""
    scenarios = _scenario_order(rows)
    valid = [r for r in rows if not _is_excluded(r)]

    means, stds, colors = [], [], []
    for sc in scenarios:
        sc_rows = [r for r in valid if r["scenario_id"] == sc]
        scores = [float(r["risk_score"]) for r in sc_rows
                  if r.get("risk_score") not in (None, "", "None")]
        mean = sum(scores) / len(scores) if scores else 0.0
        std = (
            (sum((x - mean) ** 2 for x in scores) / len(scores)) ** 0.5
            if len(scores) > 1 else 0.0
        )
        means.append(mean)
        stds.append(std)
        lvls = [r.get("worst_risk_level", "low") for r in sc_rows]
        top_level = max(lvls, key=_level_rank) if lvls else "low"
        colors.append(_level_color(top_level))

    fig, ax = plt.subplots(figsize=(max(7, len(scenarios) * 1.5), 5))
    x = range(len(scenarios))
    ax.bar(x, means, color=colors, alpha=0.82, yerr=stds, capsize=4,
           error_kw={"ecolor": "#666666"})
    ax.set_xticks(list(x))
    ax.set_xticklabels(scenarios, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Risk Score (0-100 coarse)")
    ax.set_title("F5 -- Risk Score by Scenario  (mean +/- std)")
    ax.set_ylim(0, max(max(means, default=0) * 1.30, 15))
    ax.yaxis.set_minor_locator(mticker.AutoMinorLocator())
    ax.grid(axis="y", which="major", alpha=0.4)

    legend_patches = [mpatches.Patch(color=c, label=l) for l, c in _LEVEL_COLORS.items()]
    ax.legend(handles=legend_patches, title="Worst level", loc="upper right",
              fontsize=8, title_fontsize=8)
    _save_fig(fig, out_dir / "f5_risk_score_by_scenario", formats)


def plot_risk_level_counts(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """Stacked bar of worst_risk_level distribution per scenario."""
    scenarios = _scenario_order(rows)
    valid = [r for r in rows if not _is_excluded(r)]

    counts: dict[str, dict[str, int]] = {
        sc: {l: 0 for l in _LEVEL_ORDER} for sc in scenarios
    }
    for row in valid:
        sc = row["scenario_id"]
        if sc not in counts:
            continue
        lv = str(row.get("worst_risk_level", "low")).lower()
        if lv in counts[sc]:
            counts[sc][lv] += 1

    fig, ax = plt.subplots(figsize=(max(7, len(scenarios) * 1.5), 5))
    x = list(range(len(scenarios)))
    bottoms = [0] * len(scenarios)
    for level in _LEVEL_ORDER:
        heights = [counts[sc][level] for sc in scenarios]
        ax.bar(x, heights, bottom=bottoms, color=_level_color(level), label=level, alpha=0.85)
        bottoms = [b + h for b, h in zip(bottoms, heights)]

    ax.set_xticks(x)
    ax.set_xticklabels(scenarios, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("Run count")
    ax.set_title("F3 -- Worst Risk Level Distribution by Scenario")
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.legend(loc="upper right", fontsize=8, title="Risk level", title_fontsize=8)
    ax.grid(axis="y", alpha=0.4)
    _save_fig(fig, out_dir / "f3_risk_level_counts", formats)


def plot_detection_latency(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """Box plot of time-to-detection per attack scenario."""
    scenarios = [
        sc for sc in _scenario_order(rows)
        if any(
            r["scenario_id"] == sc
            and r.get("attack_type", "none") != "none"
            and not _is_excluded(r)
            for r in rows
        )
    ]

    ttd_by_scenario: dict[str, list[float]] = {}
    for sc in scenarios:
        vals = [
            float(r["time_to_detection_s"])
            for r in rows
            if r["scenario_id"] == sc
            and not _is_excluded(r)
            and _coerce_float(r.get("time_to_detection_s")) is not None
        ]
        if vals:
            ttd_by_scenario[sc] = vals

    if not ttd_by_scenario:
        print("  Skipping F4: no time-to-detection data available yet")
        return

    labels = list(ttd_by_scenario.keys())
    data = [ttd_by_scenario[sc] for sc in labels]

    fig, ax = plt.subplots(figsize=(max(7, len(labels) * 1.6), 5))
    bp = ax.boxplot(data, labels=labels, patch_artist=True, notch=False, widths=0.55)
    for patch in bp["boxes"]:
        patch.set_facecolor("#3a8fcc")
        patch.set_alpha(0.72)
    for median in bp["medians"]:
        median.set_color("#ffffff")
        median.set_linewidth(1.8)
    for whisker in bp["whiskers"]:
        whisker.set_color("#555555")
    for cap in bp["caps"]:
        cap.set_color("#555555")
    for flier in bp["fliers"]:
        flier.set(marker="o", markerfacecolor="#ff3060", markersize=5, alpha=0.6)

    ax.axhline(0, color="#555555", linewidth=0.8, linestyle="--", alpha=0.5,
               label="attack start baseline")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Time to first detection (s)")
    ax.set_title("F4 -- Detection Latency by Scenario  (from expected attack start)")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.4)
    ax.legend(fontsize=8)
    _save_fig(fig, out_dir / "f4_detection_latency", formats)


def plot_confidence_completeness(
    rows: list[dict[str, Any]], out_dir: Path, formats: list[str]
) -> None:
    """Scatter of evidence confidence vs completeness, coloured by worst risk level."""
    valid = [r for r in rows if not _is_excluded(r)]

    points: dict[str, tuple[list[float], list[float]]] = {
        l: ([], []) for l in _LEVEL_ORDER
    }
    for row in valid:
        conf = _coerce_float(row.get("confidence"))
        comp = _coerce_float(row.get("completeness"))
        if conf is None or comp is None:
            continue
        level = str(row.get("worst_risk_level", "low")).lower()
        if level not in points:
            level = "low"
        points[level][0].append(comp)
        points[level][1].append(conf)

    all_pts = sum(len(v[0]) for v in points.values())
    if all_pts == 0:
        print("  Skipping F7: no confidence/completeness data available yet")
        return

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    for level in _LEVEL_ORDER:
        xs, ys = points[level]
        if xs:
            ax.scatter(xs, ys, c=_level_color(level), label=level,
                       s=65, alpha=0.78, edgecolors="none", zorder=3)

    ax.set_xlabel("Completeness  (0-1)")
    ax.set_ylabel("Confidence  (0-1)")
    ax.set_title("F7 -- Evidence Quality: Confidence vs Completeness")
    ax.set_xlim(-0.05, 1.10)
    ax.set_ylim(-0.05, 1.10)
    ax.axhline(0.7, color="#c8cdd6", linewidth=0.8, linestyle=":")
    ax.axvline(0.7, color="#c8cdd6", linewidth=0.8, linestyle=":")
    ax.text(0.71, 0.02, "quality floor", color="#666688", fontsize=7)
    ax.grid(alpha=0.35)
    ax.legend(title="Worst level", fontsize=8, title_fontsize=8)
    _save_fig(fig, out_dir / "f7_confidence_completeness", formats)


def plot_attack_timeline(
    run_dir: Path, out_dir: Path, formats: list[str]
) -> None:
    """Timeline of events.csv events with expected attack window overlay."""
    events_path = run_dir / "events.csv"
    manifest_path = run_dir / "manifest.json"
    if not events_path.exists() or not manifest_path.exists():
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with open(events_path, encoding="utf-8") as f:
        events = list(csv.DictReader(f))

    if not events:
        return

    scenario_id = manifest.get("scenario_id", run_dir.parent.name)
    rep = manifest.get("repetition", "?")
    atk_start = _coerce_float(manifest.get("expected_attack_start_s"))
    atk_end = _coerce_float(manifest.get("expected_attack_end_s"))

    ts = [_coerce_float(e["t_s"]) or 0.0 for e in events]
    labels = [e["event"] for e in events]

    fig, ax = plt.subplots(figsize=(11, 3.8))
    if atk_start is not None and atk_end is not None:
        ax.axvspan(
            atk_start, atk_end, alpha=0.15, color="#ff3060",
            label=f"expected attack  ({atk_start:.0f}-{atk_end:.0f}s)",
        )
    for i, (t, label) in enumerate(zip(ts, labels)):
        is_attack = "attack" in label
        is_error = "error" in label
        color = (
            "#ff3060" if is_attack or is_error
            else "#3a8fcc" if "recording" in label
            else "#888888"
        )
        ax.axvline(t, color=color, linewidth=1.1, alpha=0.75)
        y_pos = 0.92 - (i % 4) * 0.20
        ax.text(
            t, y_pos, label.replace("_", " "),
            rotation=55, fontsize=6.5, va="bottom", ha="right",
            color=color, transform=ax.get_xaxis_transform(),
        )
    ax.set_xlabel("Time into recording (s)")
    ax.set_title(f"F2 -- Timeline: {scenario_id} rep {rep}")
    ax.set_ylim(0, 1.25)
    ax.set_yticks([])
    ax.grid(axis="x", alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    stem = f"f2_timeline_{scenario_id}_rep{rep}"
    _save_fig(fig, out_dir / stem, formats)


def generate_plots(
    campaign_id: str,
    output_root: Path,
    formats: list[str],
) -> None:
    if not HAS_MPL:
        sys.exit(
            "matplotlib is required.\n"
            "Install it with:  pip install matplotlib\n"
            "Or:               pip install -r experiments/requirements.txt"
        )

    campaign_dir = output_root / campaign_id
    csv_path = campaign_dir / "campaign_summary.csv"
    if not csv_path.exists():
        sys.exit(
            f"campaign_summary.csv not found in {campaign_dir}.\n"
            "Run analyze_campaign.py first:\n"
            f"  python experiments/analyze_campaign.py --campaign {campaign_id}"
        )

    plots_dir = campaign_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    _setup_style()
    rows = _load_csv(csv_path)
    print(f"\nGenerating plots for: {campaign_id}")
    print(f"Plots directory: {plots_dir}\n")

    plot_risk_score(rows, plots_dir, formats)
    plot_risk_level_counts(rows, plots_dir, formats)
    plot_detection_latency(rows, plots_dir, formats)
    plot_confidence_completeness(rows, plots_dir, formats)

    for scenario_dir in sorted(campaign_dir.iterdir()):
        if not scenario_dir.is_dir() or scenario_dir.name == "plots":
            continue
        for run_dir in sorted(scenario_dir.iterdir()):
            if run_dir.is_dir() and (run_dir / "events.csv").exists():
                plot_attack_timeline(run_dir, plots_dir, formats)
                break

    print(f"\nAll plots written to: {plots_dir}")


# â”€â”€ CLI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TwinGuard plot generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  # Randomized adversarial trial plots (main thesis plots):
  python experiments/plots.py --randomized
  python experiments/plots.py --randomized --formats png svg
  python experiments/plots.py --randomized --summary-csv path/to/trials_summary.csv

  # Outside-threshold sanity trial plots:
  python experiments/plots.py --outside-threshold

  # Legacy fixed-campaign plots:
  python experiments/plots.py --campaign thesis_m5_detection_campaign
  python experiments/plots.py --campaign thesis_m5_detection_campaign --formats png svg
""",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--randomized",
        action="store_true",
        help="Generate randomized trial plots from trials_summary.csv (main thesis mode)",
    )
    mode.add_argument(
        "--outside-threshold",
        action="store_true",
        help="Generate outside-threshold trial plots from trials_summary.csv",
    )
    mode.add_argument(
        "--campaign",
        metavar="CAMPAIGN_ID",
        help="Generate fixed-campaign plots from campaign_summary.csv (legacy mode)",
    )
    parser.add_argument(
        "--summary-csv", default=None, metavar="PATH",
        help=(
            "Path to trials_summary.csv (default: "
            "<output-root>/<selected experiment>/trials_summary.csv)"
        ),
    )
    parser.add_argument(
        "--output-dir", default=None, metavar="PATH",
        help=(
            "Directory to write randomized trial plots to "
            "(default: <output-root>/<selected experiment>/plots/)"
        ),
    )
    parser.add_argument(
        "--output-root", default=None, metavar="PATH",
        help="Root output directory (default: visualization/output/experiments/)",
    )
    parser.add_argument(
        "--formats", nargs="+", default=["png"], choices=["png", "svg", "pdf"],
        help="Output format(s) for each figure (default: png)",
    )
    parser.add_argument(
        "--baseline-speed", type=float, default=1.0, metavar="M_PER_S",
        help="Leader baseline speed in m/s for spoof magnitude calculation (default: 1.0)",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root) if args.output_root else _DEFAULT_OUTPUT_ROOT

    if args.randomized or args.outside_threshold:
        default_id = (
            _DEFAULT_RANDOMIZED_ID
            if args.randomized
            else _DEFAULT_OUTSIDE_THRESHOLD_ID
        )
        summary_csv = (
            Path(args.summary_csv)
            if args.summary_csv
            else output_root / default_id / "trials_summary.csv"
        )
        output_dir = (
            Path(args.output_dir)
            if args.output_dir
            else output_root / default_id / "plots"
        )
        generate_randomized_plots(
            summary_csv=summary_csv,
            output_dir=output_dir,
            formats=args.formats,
            baseline_speed=args.baseline_speed,
        )
    else:
        generate_plots(args.campaign, output_root, args.formats)


if __name__ == "__main__":
    main()
