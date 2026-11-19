#!/usr/bin/env python3
"""
TwinGuard campaign analysis — aggregate run outputs into a CSV summary.

Reads manifest.json and recording_analysis.json for every completed run under
a campaign directory and writes a flat campaign_summary.csv suitable for
thesis tables and plot inputs.

Usage:
  python experiments/analyze_campaign.py --campaign thesis_m5_detection_campaign
  python experiments/analyze_campaign.py --campaign thesis_m5_detection_campaign \\
      --output-root /custom/path
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "visualization" / "output" / "experiments"

# Columns in the output CSV — order matches thesis table layout
CSV_FIELDS = [
    "campaign_id",
    "scenario_id",
    "label",
    "run_id",
    "repetition",
    "attack_type",
    "expected_attack_start_s",
    "expected_attack_end_s",
    "started_at",
    "stopped_at",
    "duration_s",
    "frame_count",
    "detected",
    "first_detection_s",
    "time_to_detection_s",
    "pre_attack_detection",
    "pre_attack_detection_s",
    "anomaly_frames",
    "anomaly_ratio",
    "raw_anomaly_frames",
    "raw_anomaly_ratio",
    "startup_ignore_s",
    "startup_ignored_anomaly_frames",
    "false_positive_candidate",
    "risk_score",
    "risk_level",
    "worst_risk_level",
    "total_findings",
    "raw_worst_risk_level",
    "raw_total_findings",
    "confidence",
    "completeness",
    "excluded",
    "exclusion_reason",
    "git_commit",
    "errors",
]

_LEVEL_ORDER = ["low", "moderate", "high", "critical"]
_SUMMARY_LEVEL_ORDER = ["low", "false_positive_candidate", "moderate", "high", "critical"]
_DEFAULT_STARTUP_IGNORE_S = 3.0
_DEFAULT_BASELINE_FP_MAX_RATIO = 0.01
_PRE_ATTACK_TOLERANCE_S = 1.0


def _nist_level_rank(level: str) -> int:
    try:
        return _SUMMARY_LEVEL_ORDER.index(str(level).lower())
    except ValueError:
        return -1


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _is_clean_attack_type(attack_type: str) -> bool:
    return str(attack_type or "none").lower() == "none"


def _ignored_startup_anomalies(
    timeline: list[dict[str, Any]],
    *,
    frame_count: int,
    duration_s: float | None,
    startup_ignore_s: float,
) -> int:
    """Estimate how many anomaly frames fall inside the startup grace window."""
    if not timeline or frame_count <= 0 or not duration_s or duration_s <= 0 or startup_ignore_s <= 0:
        return 0

    ignored_until_frame = int(math.ceil((startup_ignore_s / duration_s) * frame_count))
    if ignored_until_frame <= 0:
        return 0

    ignored = 0
    for bucket in timeline:
        start = _coerce_int(bucket.get("start_frame"))
        end = _coerce_int(bucket.get("end_frame"))
        anomalies = _coerce_int(bucket.get("anomaly_frames"))
        if start <= 0 or end < start or anomalies <= 0:
            continue
        overlap = max(0, min(end, ignored_until_frame) - start + 1)
        bucket_frames = end - start + 1
        if overlap <= 0 or bucket_frames <= 0:
            continue
        if overlap >= bucket_frames:
            ignored += anomalies
        else:
            ignored += int(round(anomalies * (overlap / bucket_frames)))
    return ignored


def _recording_start_t(run_id: str | None) -> float | None:
    """Read the first simulation timestamp from the persisted JSONL recording."""
    if not run_id:
        return None
    path = _REPO_ROOT / "visualization" / "output" / "live_recordings" / f"{run_id}.jsonl"
    if not path.exists():
        return None
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        frame = json.loads(first_line)
        return _coerce_float(((frame.get("data") or {}).get("t")))
    except Exception:
        return None


def _relative_detection_t(
    absolute_t: float,
    recording_start_t: float | None,
    duration_s: float | None,
) -> float:
    """Convert simulation timestamp to seconds into recording when possible."""
    if recording_start_t is None:
        return absolute_t
    relative = absolute_t - recording_start_t
    if duration_s is not None and -1 <= relative <= duration_s + 1:
        return round(max(0.0, relative), 3)
    return absolute_t


# ── Metric extraction ─────────────────────────────────────────────────────────

def extract_metrics(
    manifest: dict[str, Any],
    analysis: dict[str, Any] | None,
    *,
    startup_ignore_s: float = _DEFAULT_STARTUP_IGNORE_S,
    baseline_fp_max_ratio: float = _DEFAULT_BASELINE_FP_MAX_RATIO,
    recording_start_t: float | None = None,
) -> dict[str, Any]:
    """
    Build one CSV row from a run's manifest and recording analysis.

    Handles missing or partial analysis gracefully so failed runs still appear
    in the summary with exclusion flags set.
    """
    errors: list[str] = manifest.get("errors") or []
    warnings: list[str] = manifest.get("warnings") or []
    excluded = bool(errors)
    exclusion_reason = "; ".join(errors) if errors else ""

    # Derive attack_type from manifest (stored explicitly since v1)
    attack_type: str = manifest.get("attack_type") or "none"
    # Fallback: infer from scenario_id name if not stored
    if not attack_type or attack_type == "none":
        sc = manifest.get("scenario_id", "")
        if "false_brake" in sc:
            attack_type = "false_brake"
        elif "velocity_spoof" in sc:
            attack_type = "velocity_spoof"

    expected_start = _coerce_float(manifest.get("expected_attack_start_s"))
    expected_end = _coerce_float(manifest.get("expected_attack_end_s"))

    # Defaults — overwritten from analysis when available
    detected = False
    first_detection_s: float | None = None
    time_to_detection_s: float | None = None
    pre_attack_detection = False
    pre_attack_detection_s: float | None = None
    anomaly_frames = 0
    anomaly_ratio = 0.0
    raw_anomaly_frames = 0
    raw_anomaly_ratio = 0.0
    startup_ignored_anomaly_frames = 0
    false_positive_candidate = False
    risk_score = 0
    risk_level = "low"
    worst_risk_level = "low"
    raw_worst_risk_level = "low"
    total_findings = 0
    raw_total_findings = 0
    confidence: float | None = None
    completeness: float | None = None
    frame_count = 0
    duration_s: float | None = None

    if analysis:
        frame_count = _coerce_int(analysis.get("frame_count"))
        duration_s = _coerce_float(analysis.get("duration_s"))
        risk_score = _coerce_int(analysis.get("risk_score"))
        risk_level = analysis.get("risk") or "low"

        inner = analysis.get("analysis") or {}
        raw_anomaly_frames = _coerce_int(inner.get("anomaly_frames"))
        anomaly_ratio_raw = _coerce_float(inner.get("anomaly_ratio"))
        raw_anomaly_ratio = anomaly_ratio_raw if anomaly_ratio_raw is not None else 0.0
        timeline = inner.get("timeline") or []
        startup_ignored_anomaly_frames = _ignored_startup_anomalies(
            timeline if isinstance(timeline, list) else [],
            frame_count=frame_count,
            duration_s=duration_s,
            startup_ignore_s=startup_ignore_s,
        )
        anomaly_frames = max(0, raw_anomaly_frames - startup_ignored_anomaly_frames)
        anomaly_ratio = anomaly_frames / frame_count if frame_count > 0 else 0.0

        nist = analysis.get("nist_findings") or {}
        raw_worst_risk_level = nist.get("worst_risk_level") or "low"
        worst_risk_level = raw_worst_risk_level
        ns = nist.get("nist_summary") or {}
        raw_total_findings = _coerce_int(ns.get("total_findings"))
        total_findings = raw_total_findings
        confidence = _coerce_float(ns.get("avg_confidence"))
        completeness = _coerce_float(ns.get("session_completeness"))

        # Determine detection and timing from NIST risk objects
        objects: list[dict[str, Any]] = nist.get("risk_objects") or []
        relevant = _relevant_objects(objects, attack_type)

        if relevant:
            detected = True
            ts_ranges = _timestamp_ranges(relevant)
            detection_candidates: list[float] = []
            pre_attack_candidates: list[float] = []
            for abs_start, abs_end in ts_ranges:
                start = _relative_detection_t(abs_start, recording_start_t, duration_s)
                end = _relative_detection_t(abs_end, recording_start_t, duration_s)
                if expected_start is None:
                    detection_candidates.append(start)
                    continue
                if start < expected_start - _PRE_ATTACK_TOLERANCE_S:
                    pre_attack_candidates.append(start)
                if end >= expected_start - _PRE_ATTACK_TOLERANCE_S:
                    detection_candidates.append(max(start, expected_start))

            if not detection_candidates:
                ts_starts = _timestamp_starts(relevant)
                detection_candidates = [
                    _relative_detection_t(t, recording_start_t, duration_s)
                    for t in ts_starts
                ]

            if pre_attack_candidates:
                pre_attack_detection = True
                pre_attack_detection_s = round(min(pre_attack_candidates), 3)

            if detection_candidates:
                first_detection_s = round(min(detection_candidates), 3)
                if expected_start is not None:
                    time_to_detection_s = round(first_detection_s - expected_start, 3)
                    if abs(time_to_detection_s) < 0.001:
                        time_to_detection_s = 0.0
                    if -_PRE_ATTACK_TOLERANCE_S < time_to_detection_s < 0:
                        time_to_detection_s = 0.0
                    if time_to_detection_s < 0:
                        time_to_detection_s = None

        # Fallback: frame-level anomaly signal (no timestamp precision)
        if not detected and anomaly_frames > 0 and attack_type != "none":
            detected = True
            # TTD cannot be computed from frame count alone without timestamps

        if _is_clean_attack_type(attack_type):
            startup_only = raw_anomaly_frames > 0 and anomaly_frames == 0
            tiny_after_startup = (
                anomaly_frames > 0
                and frame_count > 0
                and anomaly_ratio <= baseline_fp_max_ratio
            )
            if startup_only or tiny_after_startup:
                false_positive_candidate = True
                detected = False
                first_detection_s = None
                time_to_detection_s = None
                pre_attack_detection = False
                pre_attack_detection_s = None
                risk_score = 0
                risk_level = "false_positive_candidate"
                worst_risk_level = "false_positive_candidate"
                total_findings = 0
            elif not detected:
                worst_risk_level = "low"

    if confidence is not None:
        confidence = round(confidence, 3)
    if completeness is not None:
        completeness = round(completeness, 3)

    return {
        "campaign_id": manifest.get("campaign_id", ""),
        "scenario_id": manifest.get("scenario_id", ""),
        "label": manifest.get("label", ""),
        "run_id": manifest.get("run_id") or "",
        "repetition": manifest.get("repetition", ""),
        "attack_type": attack_type,
        "expected_attack_start_s": expected_start,
        "expected_attack_end_s": expected_end,
        "started_at": _coerce_float(manifest.get("started_at")),
        "stopped_at": _coerce_float(manifest.get("stopped_at")),
        "duration_s": duration_s,
        "frame_count": frame_count,
        "detected": detected,
        "first_detection_s": first_detection_s,
        "time_to_detection_s": time_to_detection_s,
        "pre_attack_detection": pre_attack_detection,
        "pre_attack_detection_s": pre_attack_detection_s,
        "anomaly_frames": anomaly_frames,
        "anomaly_ratio": round(anomaly_ratio, 4),
        "raw_anomaly_frames": raw_anomaly_frames,
        "raw_anomaly_ratio": round(raw_anomaly_ratio, 4),
        "startup_ignore_s": startup_ignore_s,
        "startup_ignored_anomaly_frames": startup_ignored_anomaly_frames,
        "false_positive_candidate": false_positive_candidate,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "worst_risk_level": worst_risk_level,
        "total_findings": total_findings,
        "raw_worst_risk_level": raw_worst_risk_level,
        "raw_total_findings": raw_total_findings,
        "confidence": confidence,
        "completeness": completeness,
        "excluded": excluded,
        "exclusion_reason": exclusion_reason,
        "git_commit": manifest.get("git_commit"),
        "errors": "; ".join(str(e) for e in errors),
    }


def _relevant_objects(
    objects: list[dict[str, Any]], attack_type: str
) -> list[dict[str, Any]]:
    """
    Return risk objects relevant to the given attack type.

    For clean runs (attack_type='none' or 'no_attack') return all objects so
    false positives are visible.  For attack runs, match by signal_type prefix.
    """
    if attack_type in ("none", "no_attack"):
        return objects
    # ScenarioTwin has no separate false-brake check: false braking shows up as
    # velocity spoofing with kind "zeroed", so the risk layer labels it
    # velocity_spoof. Without this mapping false-brake trials never get a TTD.
    wanted = "velocity_spoof" if attack_type == "false_brake" else attack_type
    return [
        o for o in objects
        if wanted in (o.get("signal_type") or "")
    ]


def _timestamp_starts(objects: list[dict[str, Any]]) -> list[float]:
    results: list[float] = []
    for obj in objects:
        tr = obj.get("timestamp_range")
        if isinstance(tr, (list, tuple)) and len(tr) >= 1:
            v = _coerce_float(tr[0])
            if v is not None:
                results.append(v)
    return results


def _timestamp_ranges(objects: list[dict[str, Any]]) -> list[tuple[float, float]]:
    results: list[tuple[float, float]] = []
    for obj in objects:
        tr = obj.get("timestamp_range")
        if isinstance(tr, (list, tuple)) and len(tr) >= 2:
            start = _coerce_float(tr[0])
            end = _coerce_float(tr[1])
            if start is not None and end is not None:
                results.append((start, end))
    return results


# ── File loading ──────────────────────────────────────────────────────────────

def load_run_dir(
    run_dir: Path,
    *,
    startup_ignore_s: float = _DEFAULT_STARTUP_IGNORE_S,
    baseline_fp_max_ratio: float = _DEFAULT_BASELINE_FP_MAX_RATIO,
) -> dict[str, Any] | None:
    """Load manifest + analysis for one run dir.  Returns None on hard failure."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  Warning: cannot parse {manifest_path}: {exc}", file=sys.stderr)
        return None

    analysis_path = run_dir / "recording_analysis.json"
    analysis: dict[str, Any] | None = None
    if analysis_path.exists():
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(
                f"  Warning: cannot parse {analysis_path}: {exc}", file=sys.stderr
            )

    return extract_metrics(
        manifest,
        analysis,
        startup_ignore_s=startup_ignore_s,
        baseline_fp_max_ratio=baseline_fp_max_ratio,
        recording_start_t=_recording_start_t(manifest.get("run_id")),
    )


# ── Campaign aggregation ──────────────────────────────────────────────────────

def analyze_campaign(
    campaign_id: str,
    output_root: Path,
    *,
    startup_ignore_s: float = _DEFAULT_STARTUP_IGNORE_S,
    baseline_fp_max_ratio: float = _DEFAULT_BASELINE_FP_MAX_RATIO,
) -> Path:
    campaign_dir = output_root / campaign_id
    if not campaign_dir.exists():
        sys.exit(f"Campaign directory not found: {campaign_dir}")

    manifest_paths = sorted(campaign_dir.rglob("manifest.json"), key=str)
    print(f"\nAnalyzing campaign: {campaign_id}")
    print(f"Directory: {campaign_dir}")
    print(f"Runs found: {len(manifest_paths)}\n")

    rows: list[dict[str, Any]] = []
    for mp in manifest_paths:
        run_dir = mp.parent
        row = load_run_dir(
            run_dir,
            startup_ignore_s=startup_ignore_s,
            baseline_fp_max_ratio=baseline_fp_max_ratio,
        )
        if row is None:
            continue
        status = "EXCLUDED" if row["excluded"] else "ok"
        short_run = str(row["run_id"])[:8] + "…" if row["run_id"] else "(no run_id)"
        print(
            f"  {row['scenario_id']:<32}  rep={row['repetition']}"
            f"  run={short_run}  [{status}]"
        )
        rows.append(row)

    if not rows:
        print("\nNo completed runs found. Run run_campaign.py first.")
        out_path = campaign_dir / "campaign_summary.csv"
        return out_path

    out_path = campaign_dir / "campaign_summary.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    _print_summary_stats(rows)
    print(
        f"\nSummary CSV written: {out_path}  ({len(rows)} rows)"
        f"\nStartup ignore window: {startup_ignore_s:.1f}s"
        f"\nBaseline false-positive max ratio: {baseline_fp_max_ratio:.3f}"
    )
    return out_path


def _print_summary_stats(rows: list[dict[str, Any]]) -> None:
    """Print a compact per-scenario stats table to stdout."""
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_scenario.setdefault(row["scenario_id"], []).append(row)

    print(f"\n{'Scenario':<32}  {'Reps':>4}  {'Det%':>5}  {'FP?':>4}  {'MeanTTD':>7}  {'WorstLvl':>24}")
    print("-" * 82)
    for sc_id, sc_rows in by_scenario.items():
        valid = [r for r in sc_rows if not r["excluded"]]
        n = len(valid)
        if n == 0:
            print(f"  {sc_id:<30}  {len(sc_rows):>4}  (all excluded)")
            continue
        det = sum(1 for r in valid if r["detected"])
        fp = sum(1 for r in valid if r.get("false_positive_candidate"))
        det_pct = f"{det/n*100:.0f}%"
        fp_txt = str(fp) if fp else "-"
        ttds = [r["time_to_detection_s"] for r in valid if r["time_to_detection_s"] is not None]
        mean_ttd = f"{sum(ttds)/len(ttds):.1f}s" if ttds else "n/a"
        worst_ranks = [_nist_level_rank(r["worst_risk_level"]) for r in valid]
        worst_lvl = _SUMMARY_LEVEL_ORDER[max(worst_ranks)] if worst_ranks else "low"
        print(f"  {sc_id:<30}  {n:>4}  {det_pct:>5}  {fp_txt:>4}  {mean_ttd:>7}  {worst_lvl:>24}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TwinGuard campaign analysis — aggregate runs into campaign_summary.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  python experiments/analyze_campaign.py --campaign thesis_m5_detection_campaign
  python experiments/analyze_campaign.py --campaign thesis_m5_detection_campaign \\
      --output-root /mnt/data/experiments
""",
    )
    parser.add_argument("--campaign", required=True, help="Campaign ID (directory name)")
    parser.add_argument(
        "--output-root",
        default=None,
        help="Override default output root (default: visualization/output/experiments/)",
    )
    parser.add_argument(
        "--startup-ignore-s",
        type=float,
        default=_DEFAULT_STARTUP_IGNORE_S,
        help=(
            "Ignore anomaly frames in the first N seconds when computing effective "
            f"metrics (default: {_DEFAULT_STARTUP_IGNORE_S})"
        ),
    )
    parser.add_argument(
        "--baseline-fp-max-ratio",
        type=float,
        default=_DEFAULT_BASELINE_FP_MAX_RATIO,
        help=(
            "Clean-run residual anomaly ratio at or below this value is marked "
            f"false_positive_candidate (default: {_DEFAULT_BASELINE_FP_MAX_RATIO})"
        ),
    )
    args = parser.parse_args()
    output_root = (
        Path(args.output_root) if args.output_root else _DEFAULT_OUTPUT_ROOT
    )
    analyze_campaign(
        args.campaign,
        output_root,
        startup_ignore_s=args.startup_ignore_s,
        baseline_fp_max_ratio=args.baseline_fp_max_ratio,
    )


if __name__ == "__main__":
    main()
