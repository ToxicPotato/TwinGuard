#!/usr/bin/env python3
"""
Summarize the EnCyCriS case study directly from the recorded frames.

Reads every trial written by run_within_threshold_trials.py, loads the trial's
JSONL recording, and derives all numbers from ScenarioTwin's per-frame labels:

  * detected / time to first detection (TTD) per attack trial
  * detections before the attack starts (clean period)
  * false positives in no-attack trials (any label counts)
  * how the target's follower reacted (speed ``v`` and distance ``d``)

Results do not depend on the risk layer or on the analysis' startup-ignore
window, so every number can be traced to the recording. The runner's own
detected/TTD values are shown next to them as a cross-check.

Runner semantics: ``target_robot`` in the manifest is the FOLLOWER that receives
the falsified values (Fridjof -> messages of Bjarte are changed,
Torleif -> messages of Fridjof are changed). The paper calls the vehicle whose
messages are changed the "target"; see LEADER_OF below.

Usage:
    python experiments/case_study_summary.py
    python experiments/case_study_summary.py \
        --experiment-dir visualization/output/experiments/outside_threshold_trials \
        --recordings-dir visualization/output/live_recordings
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EXPERIMENT_DIR = (
    _REPO_ROOT / "visualization" / "output" / "experiments" / "outside_threshold_trials"
)
_DEFAULT_RECORDINGS_DIR = _REPO_ROOT / "visualization" / "output" / "live_recordings"

# Follower (runner target) -> vehicle whose outgoing messages are changed (paper target).
LEADER_OF = {"Fridjof": "Bjarte", "Torleif": "Fridjof"}

FAMILY_ORDER = ["velocity_spoof", "false_brake", "no_attack"]
FAMILY_LABEL = {
    "velocity_spoof": "Velocity spoofing",
    "false_brake": "False braking",
    "no_attack": "No attack",
}
# Shorter labels so the results table fits one IEEE column.
TABLE_LABEL = {
    "velocity_spoof": "Spoofing",
    "false_brake": "False braking",
    "no_attack": "No attack",
}

# A label this much before the planned start counts as a pre-attack detection
# (absorbs request latency between the runner's clock and the first frame).
PRE_ATTACK_TOLERANCE_S = 0.25
# Length of the clean window right before the attack used as speed baseline.
BASELINE_WINDOW_S = 3.0


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_frames(path: Path) -> list[dict[str, Any]]:
    """Return the enriched frames ({t, robots, scenario}) of one recording."""
    frames: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = envelope.get("data", envelope)
            if isinstance(data, dict) and _num(data.get("t")) is not None:
                frames.append(data)
    frames.sort(key=lambda d: float(d["t"]))
    return frames


def _relative_times(frames: list[dict[str, Any]], started_at: float | None) -> list[float]:
    """Seconds since recording start.

    Live frames are stamped with the backend's time.monotonic(), so the first
    recorded frame is the reference (it arrives within one 50 ms frame period
    of the capture start). If timestamps ever are epoch seconds, the runner's
    ``started_at`` is used instead.
    """
    ts = [float(fr["t"]) for fr in frames]
    if not ts:
        return []
    if started_at is not None and ts[0] > 1e9 and abs(ts[0] - started_at) < 30:
        ref = started_at
    else:
        ref = ts[0]
    return [t - ref for t in ts]


def _labels(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    per_robot = (frame.get("scenario") or {}).get("per_robot") or {}
    return per_robot if isinstance(per_robot, dict) else {}


def _flagged(frame: dict[str, Any], robot: str | None = None) -> list[str]:
    """Robots that ScenarioTwin labels as receiving spoofed velocity."""
    out = []
    for rid, lab in _labels(frame).items():
        if robot is not None and rid != robot:
            continue
        if isinstance(lab, dict) and lab.get("velocity_spoof"):
            out.append(rid)
    return out


def _field(frame: dict[str, Any], robot: str, key: str) -> float | None:
    payload = (frame.get("robots") or {}).get(robot) or {}
    return _num(payload.get(key)) if isinstance(payload, dict) else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _attack_start_from_events(trial_dir: Path) -> float | None:
    """Seconds from recording start to the runner's attack request (events.csv).

    The runner re-checks the follower's platoon state after the clean period,
    so the request is sent somewhat later than the planned start. Measuring TTD
    from the request covers the whole chain: API, relay, vehicle, frames, monitor.
    """
    try:
        with open(trial_dir / "events.csv", newline="", encoding="utf-8") as f:
            events: dict[str, float | None] = {}
            for r in csv.DictReader(f):
                events.setdefault(r.get("event") or "", _num(r.get("t_s")))
    except OSError:
        return None
    rec = events.get("recording_start")
    trig = events.get("attack_trigger")
    if rec is None or trig is None:
        return None
    return trig - rec


SPEED_LAG_S = 0.5  # window for speed from consecutive positions


def speed_series(rel: list[float], frames: list[dict[str, Any]], robot: str) -> list[tuple[float, float]]:
    """(t, speed) computed from reported positions over SPEED_LAG_S.

    The simulator reports a constant estimated velocity ``v``, so the measured
    reaction of a vehicle has to come from how far it actually moved.
    """
    pts = [(t, _field(fr, robot, "x"), _field(fr, robot, "y")) for t, fr in zip(rel, frames)]
    out: list[tuple[float, float]] = []
    j = 0
    for i, (t, x, y) in enumerate(pts):
        if x is None or y is None:
            continue
        while j < i and pts[j][0] < t - SPEED_LAG_S:
            j += 1
        tj, xj, yj = pts[j]
        if xj is None or yj is None or t - tj < 0.8 * SPEED_LAG_S:
            continue
        out.append((t, ((x - xj) ** 2 + (y - yj) ** 2) ** 0.5 / (t - tj)))
    return out


def analyze_trial(trial_dir: Path, recordings_dir: Path) -> dict[str, Any]:
    manifest = _load_json(trial_dir / "manifest.json") or {}
    runner = _load_json(trial_dir / "trial_result.json") or {}

    family = manifest.get("attack_family") or manifest.get("attack_type") or "?"
    follower = manifest.get("target_robot")
    run_id = manifest.get("run_id")
    row: dict[str, Any] = {
        "trial_id": manifest.get("trial_id", trial_dir.name),
        "trial_number": manifest.get("trial_number"),
        "run_id": run_id,
        "family": family,
        "follower": follower,
        "attacked_vehicle": LEADER_OF.get(follower or "", None) if family != "no_attack" else None,
        "speed_mps": (manifest.get("resolved_attack_request") or {}).get("speed_mps"),
        "duration_s": _num((manifest.get("generated_attack_strategy") or {}).get("duration_s")),
        "excluded": "",
        "runner_detected": runner.get("detected"),
        "runner_ttd_s": runner.get("time_to_detection_s"),
    }

    if manifest.get("errors"):
        row["excluded"] = "errors: " + "; ".join(map(str, manifest["errors"]))[:120]
        return row
    if not run_id:
        row["excluded"] = "no run_id"
        return row
    rec_path = recordings_dir / f"{run_id}.jsonl"
    if not rec_path.exists():
        row["excluded"] = f"recording not found: {rec_path.name}"
        return row

    frames = load_frames(rec_path)
    if not frames:
        row["excluded"] = "empty recording"
        return row
    rel = _relative_times(frames, _num(manifest.get("started_at")))

    start = _num(manifest.get("expected_attack_start_s"))
    end = _num(manifest.get("expected_attack_end_s"))
    recovery = _num(manifest.get("recovery_s")) or 0.0
    planned_start = start
    actual_start = _attack_start_from_events(trial_dir)
    if actual_start is not None and start is not None and end is not None:
        start, end = actual_start, actual_start + (end - start)
    row["attack_start_s"] = round(start, 3) if start is not None else None
    row["attack_start_delay_s"] = (
        round(start - planned_start, 3) if start is not None and planned_start is not None else None
    )
    any_flag = [bool(_flagged(fr)) for fr in frames]

    row["frames"] = len(frames)
    row["recording_s"] = round(rel[-1] - rel[0], 2)
    row["detection_frame_share"] = round(sum(any_flag) / len(frames), 4)

    # Clean-period samples of every vehicle (nominal speed v and distance d for
    # the Setup paragraph): before the attack, or the whole no-attack recording.
    clean_until = start if start is not None else float("inf")
    baseline: dict[str, dict[str, list[float]]] = {}
    robots_seen = sorted({rid for fr in frames for rid in (fr.get("robots") or {})})
    for t, fr in zip(rel, frames):
        if t >= clean_until:
            break
        for rid in (fr.get("robots") or {}):
            for key in ("v", "d"):
                val = _field(fr, rid, key)
                if val is not None:
                    baseline.setdefault(rid, {"v": [], "d": [], "speed": []})[key].append(val)
    for rid in robots_seen:
        sp = [v for t, v in speed_series(rel, frames, rid) if t < clean_until]
        baseline.setdefault(rid, {"v": [], "d": [], "speed": []})["speed"].extend(sp)
    row["_baseline"] = baseline

    if family == "no_attack" or start is None or end is None:
        flagged_robots = sorted({r for fr in frames for r in _flagged(fr)})
        row["detected"] = bool(flagged_robots)  # every label is a false positive
        row["false_positive"] = bool(flagged_robots)
        row["flagged_robots"] = ",".join(flagged_robots)
        return row

    # Pre-attack detections (clean period), any vehicle.
    pre = [t for t, f in zip(rel, any_flag) if f and t < start - PRE_ATTACK_TOLERANCE_S]
    row["pre_attack_detection"] = bool(pre)
    row["first_pre_attack_detection_s"] = round(min(pre), 3) if pre else None
    row["clean_period_s"] = round(start - rel[0], 2)

    # Detection on the follower during the attack window (+ recovery tail).
    win_end = end + recovery
    hits = [
        (t, fr) for t, fr in zip(rel, frames)
        if start - PRE_ATTACK_TOLERANCE_S <= t <= win_end and _flagged(fr, follower)
    ]
    row["detected"] = bool(hits)
    row["ttd_s"] = round(max(0.0, hits[0][0] - start), 3) if hits else None
    kinds = [
        (_labels(fr).get(follower) or {}).get("velocity_spoof_kind")
        for _, fr in hits
    ]
    kinds = [k for k in kinds if k]
    row["dominant_kind"] = max(set(kinds), key=kinds.count) if kinds else None
    others = sorted({
        r for t, fr in zip(rel, frames)
        if start <= t <= win_end for r in _flagged(fr) if r != follower
    })
    row["other_flagged_robots"] = ",".join(others)

    # Diagnostics, mainly for misses: did the attack reach the follower at all?
    leader = LEADER_OF.get(follower or "")
    in_win = [fr for t, fr in zip(rel, frames) if start <= t <= end]
    follower_present = [fr for fr in in_win if follower in (fr.get("robots") or {})]
    dvs = []
    for fr in follower_present:
        v_in = _field(fr, follower, "leader_input_v")
        v_obs = _field(fr, leader, "v") if leader else None
        if v_in is not None and v_obs is not None:
            dvs.append(abs(v_obs - v_in))
    row["window_frames"] = len(in_win)
    row["follower_frames_in_window"] = len(follower_present)
    row["signal_frames_in_window"] = len(dvs)
    row["max_abs_dv"] = round(max(dvs), 3) if dvs else None
    row["warnings"] = "; ".join(map(str, manifest.get("warnings") or []))[:200]
    if not row["detected"]:
        if not in_win:
            row["miss_reason"] = "recording does not cover the attack window"
        elif not follower_present:
            row["miss_reason"] = "follower missing from frames during attack"
        elif not dvs:
            row["miss_reason"] = "no leader-input signal (follower not platooning?)"
        elif max(dvs) <= 0.05:
            row["miss_reason"] = "attack never reached follower (|dv| <= 0.05)"
        else:
            row["miss_reason"] = "|dv| > 0.05 but no label: check monitor"

    # Follower reaction: speed v and distance sensor d.
    def series(key: str, lo: float, hi: float) -> list[float]:
        vals = []
        for t, fr in zip(rel, frames):
            if lo <= t < hi and follower:
                v = _field(fr, follower, key)
                if v is not None:
                    vals.append(v)
        return vals

    lo = max(rel[0], start - BASELINE_WINDOW_S)
    sp = speed_series(rel, frames, follower) if follower else []
    base_s = [v for t, v in sp if lo <= t < start]
    att_s = [v for t, v in sp if start <= t <= win_end]
    base_d = series("d", lo, start)
    att_d = series("d", start, win_end)
    row["follower_speed_baseline"] = round(_median(base_s), 3) if base_s else None
    row["follower_speed_min"] = round(min(att_s), 3) if att_s else None
    if base_s and att_s:
        row["follower_speed_drop"] = round(_median(base_s) - min(att_s), 3)
    row["follower_d_baseline"] = round(_median(base_d), 3) if base_d else None
    row["follower_d_max_attack"] = round(max(att_d), 3) if att_d else None
    if base_d and att_d:
        row["follower_gap_increase"] = round(max(att_d) - _median(base_d), 3)
    return row


CSV_FIELDS = [
    "trial_number", "trial_id", "run_id", "family", "follower", "attacked_vehicle",
    "speed_mps", "duration_s", "excluded", "frames", "recording_s", "clean_period_s",
    "detected", "ttd_s", "dominant_kind", "pre_attack_detection",
    "first_pre_attack_detection_s", "false_positive", "flagged_robots",
    "other_flagged_robots", "detection_frame_share",
    "attack_start_s", "attack_start_delay_s",
    "follower_speed_baseline", "follower_speed_min", "follower_speed_drop",
    "follower_d_baseline", "follower_d_max_attack", "follower_gap_increase",
    "runner_detected", "runner_ttd_s",
    "window_frames", "follower_frames_in_window", "signal_frames_in_window",
    "max_abs_dv", "miss_reason", "warnings",
]


def _fmt(x: float | None, nd: int = 2) -> str:
    return "--" if x is None else f"{x:.{nd}f}"


def summarize(rows: list[dict[str, Any]]) -> str:
    out: list[str] = []
    valid = [r for r in rows if not r["excluded"]]
    excluded = [r for r in rows if r["excluded"]]
    out.append(f"Trials: {len(rows)} total, {len(valid)} valid, {len(excluded)} excluded")
    for r in excluded:
        out.append(f"  excluded {r['trial_id']}: {r['excluded']}")

    # Nominal platoon behavior in clean periods (for the Setup paragraph).
    pooled: dict[str, dict[str, list[float]]] = {}
    for r in valid:
        for rid, series_by_key in (r.get("_baseline") or {}).items():
            for key, vals in series_by_key.items():
                pooled.setdefault(rid, {"v": [], "d": [], "speed": []}).setdefault(key, []).extend(vals)
    if pooled:
        out.append("")
        out.append("== Clean-period baseline per vehicle (median [p10-p90]):")
        for rid in sorted(pooled):
            parts = []
            for key in ("v", "speed", "d"):
                vals = sorted(pooled[rid].get(key) or [])
                if vals:
                    p10 = vals[int(0.1 * (len(vals) - 1))]
                    p90 = vals[int(0.9 * (len(vals) - 1))]
                    parts.append(f"{key}={_median(vals):.3f} [{p10:.3f}-{p90:.3f}]")
            out.append(f"   {rid:<8} " + "  ".join(parts))

    latex: list[str] = []
    for fam in FAMILY_ORDER:
        rs = [r for r in valid if r["family"] == fam]
        if not rs:
            continue
        det = sum(1 for r in rs if r.get("detected"))
        out.append("")
        out.append(f"== {FAMILY_LABEL[fam]}: n={len(rs)}, detected={det}/{len(rs)}")
        if fam == "no_attack":
            out.append(f"   false positives: {det}  (robots: "
                       f"{sorted({x for r in rs for x in (r.get('flagged_robots') or '').split(',') if x})})")
            latex.append("        \\midrule")
            latex.append(f"        {TABLE_LABEL[fam]:<13} & -- & {len(rs)} & {det} & n/a & n/a \\\\")
            continue
        ttds = [r["ttd_s"] for r in rs if r.get("ttd_s") is not None]
        med = _median(ttds)
        out.append(f"   TTD median={_fmt(med)} s  min={_fmt(min(ttds) if ttds else None)}  "
                   f"max={_fmt(max(ttds) if ttds else None)}  (from the attack request)")
        delays = [r["attack_start_delay_s"] for r in rs if r.get("attack_start_delay_s") is not None]
        if delays:
            out.append(f"   request sent after planned start by: median={_fmt(_median(delays))} s "
                       f"max={_fmt(max(delays))} s")
        pre = sum(1 for r in rs if r.get("pre_attack_detection"))
        out.append(f"   pre-attack detections: {pre}/{len(rs)}")
        kinds = [r["dominant_kind"] for r in rs if r.get("dominant_kind")]
        out.append(f"   dominant kinds: { {k: kinds.count(k) for k in sorted(set(kinds))} }")
        others = [r for r in rs if r.get("other_flagged_robots")]
        out.append(f"   trials where another vehicle was also flagged: {len(others)}")
        for veh in sorted({r["attacked_vehicle"] for r in rs if r.get("attacked_vehicle")}):
            sub = [r for r in rs if r.get("attacked_vehicle") == veh]
            def col(key: str) -> list[float]:
                return [r[key] for r in sub if r.get(key) is not None]
            sb, smin, gi = col("follower_speed_baseline"), col("follower_speed_min"), col("follower_gap_increase")
            db, dmax = col("follower_d_baseline"), col("follower_d_max_attack")
            out.append(
                f"   attacked {veh} (follower {sub[0]['follower']}), n={len(sub)}: "
                f"follower speed (from positions) baseline median={_fmt(_median(sb))}, "
                f"min during attack median={_fmt(_median(smin))} "
                f"[range {_fmt(min(smin) if smin else None)}-{_fmt(max(smin) if smin else None)}]; "
                f"gap d baseline median={_fmt(_median(db))}, max during attack median={_fmt(_median(dmax))} "
                f"(increase median={_fmt(_median(gi))})"
            )
        misses = [r for r in rs if not r.get("detected")]
        if misses:
            out.append("   missed:")
            for r in misses:
                out.append(
                    f"     {r['trial_id']} target={r.get('attacked_vehicle')} "
                    f"dur={_fmt(r.get('duration_s'), 1)}s max|dv|={_fmt(r.get('max_abs_dv'), 3)} "
                    f"follower/signal frames={r.get('follower_frames_in_window')}/"
                    f"{r.get('signal_frames_in_window')} of {r.get('window_frames')} -> "
                    f"{r.get('miss_reason')}"
                )
                if r.get("warnings"):
                    out.append(f"       runner warnings: {r['warnings']}")
        # One table row per attacked vehicle: n, detected, TTD median [max], follower v_min.
        if latex:
            latex.append("        \\midrule")
        first = True
        for veh in sorted({r["attacked_vehicle"] for r in rs if r.get("attacked_vehicle")}):
            sub = [r for r in rs if r.get("attacked_vehicle") == veh]
            sub_det = sum(1 for r in sub if r.get("detected"))
            sub_ttd = [r["ttd_s"] for r in sub if r.get("ttd_s") is not None]
            ttd_txt = (f"{_median(sub_ttd):.2f} [{max(sub_ttd):.2f}]" if sub_ttd else "--")
            vmin = [r["follower_speed_min"] for r in sub
                    if r.get("follower_speed_min") is not None]
            label = TABLE_LABEL[fam] if first else ""
            first = False
            latex.append(
                f"        {label:<13} & \\texttt{{{veh}}} & {len(sub)} & {sub_det} & "
                f"{ttd_txt} & {_fmt(_median(vmin))} \\\\"
            )

    agree = [r for r in valid if r.get("runner_detected") is not None]
    mismatch = [r for r in agree if bool(r["runner_detected"]) != bool(r.get("detected"))]
    out.append("")
    out.append(f"Cross-check vs runner 'detected': {len(agree) - len(mismatch)}/{len(agree)} agree")
    for r in mismatch:
        out.append(f"  mismatch {r['trial_id']} ({r['family']}): frames={r.get('detected')} "
                   f"runner={r['runner_detected']}")

    out.append("")
    out.append("LaTeX rows for tables/case-study-results.tex:")
    out.extend(latex)
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--experiment-dir", type=Path, default=_DEFAULT_EXPERIMENT_DIR)
    ap.add_argument("--recordings-dir", type=Path, default=_DEFAULT_RECORDINGS_DIR)
    ap.add_argument("--out-csv", type=Path, default=None,
                    help="Per-trial CSV (default: <experiment-dir>/case_study_trials.csv)")
    args = ap.parse_args()

    trial_dirs = sorted(p for p in (args.experiment_dir / "trials").glob("*") if p.is_dir())
    if not trial_dirs:
        raise SystemExit(f"No trial folders under {args.experiment_dir / 'trials'}")
    rows = [analyze_trial(d, args.recordings_dir) for d in trial_dirs]
    rows.sort(key=lambda r: (r.get("trial_number") or 0, r["trial_id"]))

    out_csv = args.out_csv or (args.experiment_dir / "case_study_trials.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(summarize(rows))
    print(f"\nPer-trial CSV: {out_csv}")


if __name__ == "__main__":
    main()
