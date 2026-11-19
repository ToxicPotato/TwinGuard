#!/usr/bin/env python3
"""
TwinGuard continuous randomized adversarial trial runner.

The experiment uses an algorithmic adversarial attack generator rather than a
fixed scenario list.  Each trial samples a fresh attack strategy from
configurable probability distributions and parameter bounds, enabling empirical
evaluation of detection coverage across a broader attack space.

Runs continuously until interrupted with Ctrl+C. Progress is saved after
every trial. Runtime problems are recorded as errors/warnings on the trial
instead of creating a separate excluded-results category.

Usage:
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml --seed 1337
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml --max-trials 50
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml --dry-run

Output:
  visualization/output/experiments/<experiment_id>/
    trials/<trial_id>/
      manifest.json, trial_result.json, recording_analysis.json,
      risk_snapshot.json, live_alerts.json, events.csv
    trials_summary.csv         <- one row per trial, appended after each trial
    experiment_summary.json    <- written on graceful Ctrl+C shutdown
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit(
        "pyyaml is required.\n"
        "Install it with:  pip install pyyaml\n"
        "Or:               pip install -r experiments/requirements.txt"
    )

# Reuse helpers from sibling modules in experiments/
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_campaign import (  # noqa: E402
    EventLog,
    _git_commit,
    _http_get,
    _http_post,
    _log,
    _make_rep_seed,
    _POST_STOP_SETTLE_S,
    _sleep,
    _wait_for_attack_idle,
    check_backend,
)
from analyze_campaign import (  # noqa: E402
    _coerce_float,
    _recording_start_t,
    extract_metrics,
)
from attack_generator import (  # noqa: E402
    build_attack_request_from_strategy,
    generate_attack_strategy,
    validate_attack_generator_config,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "visualization" / "output" / "experiments"

TRIAL_CSV_FIELDS = [
    "experiment_id",
    "trial_id",
    "trial_number",
    "run_id",
    "seed",
    "attack_family",
    "attack_strategy",
    "attack_difficulty",
    "attack_type",
    "target_robot",
    "attack_mode",
    "speed_mps",
    "speed_start",
    "speed_end",
    "delay_s",
    "duration_s",
    "expected_attack_start_s",
    "expected_attack_end_s",
    "detected",
    "first_detection_s",
    "time_to_detection_s",
    "pre_attack_detection",
    "risk_level",
    "risk_score",
    "worst_risk_level",
    "anomaly_frames",
    "anomaly_ratio",
    "confidence",
    "completeness",
    "max_lane_error",
    "max_spacing_error",
    "out_of_formation",
    "out_of_formation_duration_s",
    "recovery_time_s",
    "undetected_physical_impact",
    "generated_attack_strategy_json",
]


# ── Config loading and validation ─────────────────────────────────────────────

def _validate_config(cfg: dict[str, Any]) -> None:
    for field in ("experiment_id", "attack_generator"):
        if field not in cfg:
            raise ValueError(f"Config missing required field: '{field}'")
    validate_attack_generator_config(cfg["attack_generator"])


def load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate_config(cfg)
    return cfg


def _existing_trial_count(csv_path: Path) -> int:
    """Return the highest trial_number already present in a summary CSV."""
    if not csv_path.exists() or csv_path.stat().st_size <= 0:
        return 0
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            max_trial = 0
            for row in csv.DictReader(f):
                try:
                    max_trial = max(max_trial, int(row.get("trial_number") or 0))
                except (TypeError, ValueError):
                    continue
            return max_trial
    except OSError:
        return 0


# ── Baseline stability ────────────────────────────────────────────────────────

def _wait_for_baseline_stable(
    base_url: str,
    *,
    settle_s: float,
    timeout_s: float,
    window_s: float,
    dry_run: bool = False,
) -> tuple[bool, str | None]:
    """Wait until the platoon appears to be in a stable baseline state.

    Currently a conservative fixed sleep.  Full stability detection over a
    sliding window requires per-robot pose telemetry the backend does not yet
    expose.

    TODO: poll GET /platoon/status and verify that max_lane_error and
    max_spacing_error remain below thresholds for window_s consecutive seconds,
    with a hard timeout of timeout_s.
    """
    if dry_run:
        _log(f"[DRY] would wait {settle_s:.1f}s for baseline stability")
        return True, None
    if settle_s > 0:
        _sleep(settle_s, dry_run=False, reason="baseline settle")
    return True, None


# ── Clean baseline gate ───────────────────────────────────────────────────────

# Signal types in current_risk_objects that indicate an active live velocity-spoof
# threat (as opposed to historical findings which should not block a new trial).
_VS_LIVE_SIGNAL_TYPES = frozenset({"velocity_spoof", "velocity_spoof_live"})
_LIVE_DIRTY_STATUSES = frozenset({"active", "pending"})
_DEFAULT_PLATOON_TARGET_STATES = frozenset({3, 4})
_STATE_LABELS = {
    0: "AUTONOMOUS",
    1: "CANDIDATE",
    2: "ALIGNING",
    3: "PLATOONING",
    4: "RECOVERY",
}


def _risk_snapshot_clean(snapshot: dict[str, Any]) -> tuple[bool, str | None]:
    """Return (True, None) when GET /risk/system shows no current live velocity_spoof.

    Accepts snapshots where historical_baseline is high/critical — prior-trial
    findings raise the historical score but must NOT block the next trial.
    Only current_live objects with signal_type in _VS_LIVE_SIGNAL_TYPES and
    live_contribution threats are treated as blocking.
    """
    for obj in snapshot.get("current_risk_objects") or []:
        signal_type = str(obj.get("signal_type") or "")
        if signal_type in ("historical_baseline", "no_active_threat", ""):
            continue
        if signal_type in _VS_LIVE_SIGNAL_TYPES:
            level = obj.get("risk_level", "low")
            return False, (
                f"Current live risk object: signal_type={signal_type!r} level={level!r}"
            )

    for threat in (snapshot.get("live_contribution") or {}).get("threats") or []:
        attack_type = str(threat.get("attack_type") or "")
        status = str(threat.get("status") or "")
        if attack_type == "velocity_spoof" and status in _LIVE_DIRTY_STATUSES:
            return False, f"Live velocity_spoof threat: status={status!r}"

    return True, None


def _alerts_clean(alerts: dict[str, Any] | list[Any]) -> tuple[bool, str | None]:
    """Return (True, None) when GET /risk/alerts shows no active velocity_spoof alert.

    false_brake alerts are ignored here — only velocity_spoof can produce
    spurious pre-trial contamination via the detector's rolling buffer.
    The input can be the full /risk/alerts response dict (which has an
    active_alerts key) or a bare list of alert dicts.
    """
    if isinstance(alerts, dict):
        active = alerts.get("active_alerts") or []
    elif isinstance(alerts, list):
        active = alerts
    else:
        return True, None

    for alert in active:
        attack_type = str(alert.get("attack_type") or "")
        status = str(alert.get("status") or "")
        source = str(alert.get("source") or "")
        if attack_type == "velocity_spoof" and status in _LIVE_DIRTY_STATUSES:
            return False, (
                f"Active velocity_spoof alert: status={status!r} source={source!r}"
            )

    return True, None


def _wait_for_clean_live_state(
    backend_url: str,
    *,
    timeout_s: float,
    poll_s: float = 1.0,
    require_no_live_alerts: bool = True,
    require_no_current_velocity_spoof: bool = True,
) -> tuple[bool, str | None]:
    """Poll /risk/system and /risk/alerts until both report a clean live state.

    Returns (True, None) when clean within timeout_s.
    Returns (False, reason) if timeout elapses before a clean reading.
    """
    deadline = time.monotonic() + timeout_s
    last_reason: str = "not polled yet"

    while time.monotonic() <= deadline:
        reasons: list[str] = []

        if require_no_current_velocity_spoof:
            snapshot, err = _http_get(backend_url, "/risk/system", timeout=5)
            if err:
                reasons.append(f"risk/system error: {err}")
            else:
                ok, reason = _risk_snapshot_clean(snapshot or {})
                if not ok:
                    reasons.append(reason or "live velocity_spoof detected")

        if require_no_live_alerts:
            alert_resp, err = _http_get(backend_url, "/risk/alerts", timeout=5)
            if err:
                reasons.append(f"risk/alerts error: {err}")
            else:
                ok, reason = _alerts_clean(alert_resp or {})
                if not ok:
                    reasons.append(reason or "active velocity_spoof alert")

        if not reasons:
            return True, None

        last_reason = "; ".join(reasons)
        time.sleep(poll_s)

    return False, f"timeout after {timeout_s:.0f}s -- last: {last_reason}"


def _handle_gate_failure(
    clean_ok: bool,
    clean_reason: str | None,
    on_timeout: str,
    errors: list[str],
    warnings: list[str],
    gate_name: str = "Clean baseline gate",
) -> bool:
    """Handle a gate outcome.  Returns True if the trial should be excluded.

    on_timeout='exclude_trial':   append to errors (->excluded) and return True.
    on_timeout='warn_and_continue': append to warnings and return False.
    If clean_ok is True, do nothing and return False.
    """
    if clean_ok:
        return False
    msg_core = clean_reason or "unknown reason"
    if on_timeout == "exclude_trial":
        errors.append(f"{gate_name} failed: {msg_core}")
        return True
    warnings.append(f"{gate_name} failed before trial: {msg_core}")
    return False


def _state_name(state: int | None) -> str:
    if state is None:
        return "unknown"
    return _STATE_LABELS.get(state, f"state {state}")


def _latest_frame_from_buffer(buffer_snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest enriched frame payload from /live/buffer."""
    frames = buffer_snapshot.get("frames") or []
    if not isinstance(frames, list) or not frames:
        return None
    newest = frames[-1]
    if not isinstance(newest, dict):
        return None
    data = newest.get("data")
    if isinstance(data, dict):
        return data
    return newest


def _robot_state_from_frame(frame: dict[str, Any] | None, robot_id: str) -> int | None:
    """Extract routed active_state (`st`) for one robot from an enriched frame."""
    if not frame:
        return None
    robots = frame.get("robots") or {}
    if not isinstance(robots, dict):
        return None
    payload = robots.get(robot_id)
    if not isinstance(payload, dict):
        return None
    state = payload.get("st")
    try:
        return int(state)
    except (TypeError, ValueError):
        return None


def _target_platoon_state_ok(
    buffer_snapshot: dict[str, Any],
    target_robot: str | None,
    allowed_states: set[int] | frozenset[int] = _DEFAULT_PLATOON_TARGET_STATES,
) -> tuple[bool, str | None, int | None]:
    """Return whether the selected attack target is currently in an allowed state."""
    if not target_robot:
        return True, None, None

    frame = _latest_frame_from_buffer(buffer_snapshot)
    if frame is None:
        return False, "No live frame available for target-state check", None

    state = _robot_state_from_frame(frame, target_robot)
    if state in allowed_states:
        return True, None, state

    allowed = ", ".join(
        f"{s} ({_state_name(s)})" for s in sorted(allowed_states)
    )
    return (
        False,
        f"Target {target_robot!r} is {_state_name(state)}; expected one of {allowed}",
        state,
    )


def _wait_for_target_platoon_state(
    backend_url: str,
    target_robot: str | None,
    *,
    timeout_s: float | None,
    poll_s: float = 1.0,
    allowed_states: set[int] | frozenset[int] = _DEFAULT_PLATOON_TARGET_STATES,
    reset_on_mismatch: bool = True,
    verbose: bool = False,
) -> tuple[bool, str | None, int | None]:
    """Poll /live/buffer until target_robot is in a platooning-capable state.

    State 3 is PLATOONING and state 4 is RECOVERY.  Both indicate that the
    robot is or was recently part of the platoon control path, so attacks
    against its leader input are meaningful.  Lower states are ignored to avoid
    sampling attacks against autonomous/candidate/alignment behavior.
    """
    if not target_robot:
        return True, None, None

    wait_forever = timeout_s is None or timeout_s <= 0
    deadline = None if wait_forever else time.monotonic() + timeout_s
    last_reason: str | None = None
    last_state: int | None = None
    last_printed: str | None = None
    first_frame_id: int | None = None

    while wait_forever or time.monotonic() <= deadline:
        snapshot, err = _http_get(backend_url, "/live/buffer?limit=1", timeout=5)
        if err:
            last_reason = f"live/buffer error: {err}"
        else:
            frames = (snapshot or {}).get("frames") or []
            newest = frames[-1] if isinstance(frames, list) and frames else {}
            frame_id_raw = (snapshot or {}).get("last_frame_id")
            if isinstance(newest, dict):
                frame_id_raw = newest.get("frame_id", frame_id_raw)
            try:
                frame_id = int(frame_id_raw)
            except (TypeError, ValueError):
                frame_id = None

            if first_frame_id is None:
                first_frame_id = frame_id
                last_reason = "Waiting for a fresh live frame after gate start"
                time.sleep(poll_s)
                continue
            if frame_id is None or frame_id <= first_frame_id:
                last_reason = "No fresh live frame received; simulation may not be running"
                if reset_on_mismatch:
                    _http_post(backend_url, "/attack/reset")
                if verbose and last_reason != last_printed:
                    print(f"\n    pause: waiting for fresh simulation frames - {last_reason}", flush=True)
                    last_printed = last_reason
                time.sleep(poll_s)
                continue

            ok, reason, state = _target_platoon_state_ok(snapshot or {}, target_robot, allowed_states)
            last_state = state
            if ok:
                if verbose and last_printed is not None:
                    print(
                        f"\n    target ready: {target_robot} state={state} ({_state_name(state)})",
                        flush=True,
                    )
                return True, None, state
            last_reason = reason
            if reset_on_mismatch:
                _http_post(backend_url, "/attack/reset")
        if verbose and last_reason and last_reason != last_printed:
            wait_msg = "waiting until target enters state 3/4"
            if not wait_forever and deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
                wait_msg = f"waiting {remaining:.0f}s for target state 3/4"
            print(f"\n    pause: {wait_msg} - {last_reason}", flush=True)
            last_printed = last_reason
        time.sleep(poll_s)

    return (
        False,
        f"timeout after {timeout_s:.0f}s -- last: {last_reason or 'unknown'}",
        last_state,
    )


def _run_baseline_probe(
    backend_url: str,
    experiment_id: str,
    trial_number: int,
    trial_dir: Path,
    probe_s: float,
) -> tuple[bool, str | None]:
    """Start a short recording, stop it, and verify no velocity_spoof frames appear.

    Writes baseline_probe_analysis.json to trial_dir for traceability.
    Returns (True, None) when baseline is clean, or (False, reason) on any problem.
    """
    probe_name = f"{experiment_id}__baseline_probe_trial_{trial_number:04d}"
    resp, err = _http_post(backend_url, "/live/capture/start", {"name": probe_name}, timeout=15)
    if err:
        return False, f"Probe start failed: {err}"
    probe_run_id = (resp or {}).get("run_id")
    if not probe_run_id:
        return False, f"No run_id in probe response: {resp}"

    _sleep(probe_s, dry_run=False, reason="baseline probe")
    _http_post(backend_url, "/live/capture/stop", timeout=15)
    _sleep(_POST_STOP_SETTLE_S, dry_run=False, reason="probe settle")

    analysis, err = _http_get(backend_url, f"/recordings/{probe_run_id}", timeout=20)
    if err:
        return False, f"Probe analysis error: {err}"

    (trial_dir / "baseline_probe_analysis.json").write_text(
        json.dumps(analysis, indent=2, default=str)
    )

    inner = (analysis.get("analysis") or {})
    anomaly_frames = int(inner.get("anomaly_frames") or 0)
    nist = analysis.get("nist_findings") or {}
    vs_objects = [
        o for o in (nist.get("risk_objects") or [])
        if "velocity_spoof" in str(o.get("signal_type") or "")
    ]
    if anomaly_frames > 0:
        return False, f"Probe: {anomaly_frames} velocity_spoof frame(s) detected"
    if vs_objects:
        return False, f"Probe: {len(vs_objects)} velocity_spoof NIST finding(s)"
    return True, None


# ── Formation analysis ────────────────────────────────────────────────────────

def _analyze_formation(
    analysis: dict[str, Any] | None,
    thresholds: dict[str, Any],
    detected: bool,
) -> dict[str, Any]:
    """Extract physical formation quality metrics from recording analysis data.

    Reads formation-quality metrics from the recording analysis payload.

    Historical note:
    - Older code expected top-level ``analysis.max_lane_error_m`` and
      ``analysis.max_spacing_error_m``.
    - The current backend persists per-robot ``max_abs_lane_error`` inside
      ``analysis.robots`` and does not yet guarantee a top-level spacing metric.

    This function therefore:
    - prefers explicit top-level metrics when present
    - otherwise derives ``max_lane_error`` as the maximum per-robot
      ``max_abs_lane_error``
    - preserves ``max_spacing_error`` only when a real spacing metric exists

    Out-of-formation is flagged when either available metric exceeds its
    configured threshold.

    TODO: compute out_of_formation_duration_s and recovery_time_s when the
    backend exposes per-robot pose time-series in recording_analysis.json.
    """
    max_lane_error: float | None = None
    max_spacing_error: float | None = None
    out_of_formation = False
    out_of_formation_duration_s: float | None = None
    recovery_time_s: float | None = None

    if analysis:
        inner = analysis.get("analysis") or {}
        max_lane_error = _coerce_float(inner.get("max_lane_error_m"))
        if max_lane_error is None:
            max_lane_error = _coerce_float(inner.get("max_lane_error"))

        if max_lane_error is None:
            robots = inner.get("robots") or {}
            if isinstance(robots, dict):
                lane_vals = [
                    lane_val
                    for lane_val in (
                        _coerce_float((payload or {}).get("max_abs_lane_error"))
                        for payload in robots.values()
                        if isinstance(payload, dict)
                    )
                    if lane_val is not None
                ]
                if lane_vals:
                    max_lane_error = max(lane_vals)

        max_spacing_error = _coerce_float(inner.get("max_spacing_error_m"))
        if max_spacing_error is None:
            max_spacing_error = _coerce_float(inner.get("max_spacing_error"))

        lane_threshold = _coerce_float(thresholds.get("max_lane_error_m"))
        spacing_threshold = _coerce_float(thresholds.get("max_spacing_error_m"))

        lane_violated = (
            max_lane_error is not None
            and lane_threshold is not None
            and max_lane_error > lane_threshold
        )
        spacing_violated = (
            max_spacing_error is not None
            and spacing_threshold is not None
            and max_spacing_error > spacing_threshold
        )
        out_of_formation = lane_violated or spacing_violated

    undetected_physical_impact = out_of_formation and not detected
    return {
        "max_lane_error": max_lane_error,
        "max_spacing_error": max_spacing_error,
        "out_of_formation": out_of_formation,
        "out_of_formation_duration_s": out_of_formation_duration_s,
        "recovery_time_s": recovery_time_s,
        "undetected_physical_impact": undetected_physical_impact,
    }


# ── Trial result builder ──────────────────────────────────────────────────────

def _build_trial_result(
    manifest: dict[str, Any],
    analysis: dict[str, Any] | None,
    formation: dict[str, Any],
    *,
    startup_ignore_s: float = 3.0,
) -> dict[str, Any]:
    """Merge manifest + detection metrics + formation metrics into a trial result."""
    rec_start_t = _recording_start_t(manifest.get("run_id"))
    metrics = extract_metrics(
        manifest,
        analysis,
        startup_ignore_s=startup_ignore_s,
        recording_start_t=rec_start_t,
    )

    strategy = manifest.get("generated_attack_strategy") or {}
    resolved = manifest.get("resolved_attack_request") or {}

    return {
        "experiment_id": manifest.get("experiment_id", ""),
        "trial_id": manifest.get("trial_id", ""),
        "trial_number": manifest.get("trial_number", 0),
        "run_id": manifest.get("run_id", ""),
        "seed": manifest.get("seed"),
        "attack_family": strategy.get("attack_family") or manifest.get("attack_type"),
        "attack_strategy": strategy.get("strategy"),
        "attack_difficulty": strategy.get("attack_difficulty"),
        "attack_type": manifest.get("attack_type"),
        "target_robot": manifest.get("target_robot"),
        "attack_mode": resolved.get("mode"),
        "speed_mps": resolved.get("speed_mps"),
        "speed_start": resolved.get("speed_start"),
        "speed_end": resolved.get("speed_end"),
        "delay_s": resolved.get("delay_s"),
        "duration_s": resolved.get("duration_s"),
        "expected_attack_start_s": manifest.get("expected_attack_start_s"),
        "expected_attack_end_s": manifest.get("expected_attack_end_s"),
        "detected": metrics["detected"],
        "first_detection_s": metrics["first_detection_s"],
        "time_to_detection_s": metrics["time_to_detection_s"],
        "pre_attack_detection": metrics["pre_attack_detection"],
        "risk_level": metrics["risk_level"],
        "risk_score": metrics["risk_score"],
        "worst_risk_level": metrics["worst_risk_level"],
        "anomaly_frames": metrics["anomaly_frames"],
        "anomaly_ratio": metrics["anomaly_ratio"],
        "confidence": metrics["confidence"],
        "completeness": metrics["completeness"],
        "max_lane_error": formation["max_lane_error"],
        "max_spacing_error": formation["max_spacing_error"],
        "out_of_formation": formation["out_of_formation"],
        "out_of_formation_duration_s": formation["out_of_formation_duration_s"],
        "recovery_time_s": formation["recovery_time_s"],
        "undetected_physical_impact": formation["undetected_physical_impact"],
        "generated_attack_strategy_json": json.dumps(
            {k: v for k, v in strategy.items() if not k.startswith("_")},
            default=str,
        ),
        "excluded": metrics["excluded"],
        "exclusion_reason": metrics["exclusion_reason"],
    }


# ── Experiment summary ────────────────────────────────────────────────────────

def _build_experiment_summary(
    results: list[dict[str, Any]],
    cfg: dict[str, Any],
    started_at: float,
    stopped_at: float,
    seed: int,
) -> dict[str, Any]:
    """Aggregate all trial results into an experiment-level summary."""
    total = len(results)
    detected_count = sum(1 for r in results if r.get("detected"))
    detection_rate = detected_count / total if total else 0.0

    ttds = [
        r["time_to_detection_s"]
        for r in results
        if r.get("detected") and r.get("time_to_detection_s") is not None
    ]
    mean_ttd = sum(ttds) / len(ttds) if ttds else None

    risk_level_counts: dict[str, int] = {}
    attack_family_counts: dict[str, int] = {}
    attack_strategy_counts: dict[str, int] = {}
    attack_difficulty_counts: dict[str, int] = {}

    for r in results:
        for key, bucket in (
            ("worst_risk_level", risk_level_counts),
            ("attack_family", attack_family_counts),
            ("attack_strategy", attack_strategy_counts),
            ("attack_difficulty", attack_difficulty_counts),
        ):
            label = str(r.get(key) or "unknown")
            bucket[label] = bucket.get(label, 0) + 1

    return {
        "experiment_id": cfg.get("experiment_id"),
        "total_trials": total,
        "detected_trials": detected_count,
        "detection_rate": round(detection_rate, 4),
        "mean_time_to_detection_s": round(mean_ttd, 3) if mean_ttd is not None else None,
        "risk_level_counts": risk_level_counts,
        "attack_family_counts": attack_family_counts,
        "attack_strategy_counts": attack_strategy_counts,
        "attack_difficulty_counts": attack_difficulty_counts,
        "out_of_formation_trials": sum(1 for r in results if r.get("out_of_formation")),
        "undetected_physical_impact_trials": sum(
            1 for r in results if r.get("undetected_physical_impact")
        ),
        "pre_attack_detection_trials": sum(1 for r in results if r.get("pre_attack_detection")),
        "seed": seed,
        "started_at": started_at,
        "stopped_at": stopped_at,
        "duration_s": round(stopped_at - started_at, 1),
    }


def _print_final_summary(summary: dict[str, Any]) -> None:
    total = summary["total_trials"]
    det = summary["detected_trials"]
    rate = summary["detection_rate"]
    mean_ttd = summary.get("mean_time_to_detection_s")
    oof = summary.get("out_of_formation_trials", 0)
    upi = summary.get("undetected_physical_impact_trials", 0)
    pre = summary.get("pre_attack_detection_trials", 0)
    ttd_str = f"{mean_ttd:.1f}s" if mean_ttd is not None else "n/a"

    print(f"\n{'-'*72}")
    print(f"Summary: {summary.get('experiment_id')}")
    print(f"Trials={total}  Detected={det}/{total} ({rate*100:.1f}%)  Mean TTD={ttd_str}")
    print(f"OOF={oof}  Undetected OOF={upi}  Pre-attack={pre}")

    print("\nRisk levels")
    for lvl, cnt in sorted(summary.get("risk_level_counts", {}).items()):
        print(f"  {lvl:<18} {cnt:>4}")
    print("\nStrategies")
    for strat, cnt in sorted(summary.get("attack_strategy_counts", {}).items()):
        print(f"  {strat:<18} {cnt:>4}")
    print("\nDifficulty")
    for sl, cnt in sorted(summary.get("attack_difficulty_counts", {}).items()):
        print(f"  {sl:<18} {cnt:>4}")
    print(f"{'-'*72}")


# ── Single trial execution ────────────────────────────────────────────────────

def _run_pulse_attack(
    backend_url: str,
    attack_request: dict[str, Any],
    evlog: EventLog,
) -> list[str]:
    """Execute a pulse attack as repeated static velocity-spoof windows."""
    warnings: list[str] = []
    delay_s = float(attack_request.get("delay_s", 0.0))
    duration_s = float(attack_request.get("duration_s", 0.0))
    pulse_count = max(1, int(attack_request.get("pulse_count", 1)))
    duty_cycle = max(0.0, min(1.0, float(attack_request.get("duty_cycle", 0.5))))
    low_speed = float(attack_request.get("low_speed_mps", 0.0))
    high_speed = float(attack_request.get("high_speed_mps", 0.0))
    target_robot = attack_request.get("target_robot")
    follower_robot = attack_request.get("follower_robot")

    if delay_s > 0:
        evlog.add("pulse_delay_wait", f"{delay_s:.1f}s")
        _sleep(delay_s, dry_run=False)

    cycle_s = duration_s / pulse_count if pulse_count > 0 else duration_s
    high_s = max(0.05, cycle_s * duty_cycle)
    low_s = max(0.0, cycle_s - high_s)

    for idx in range(pulse_count):
        evlog.add("pulse_high", f"{idx + 1}/{pulse_count} speed={high_speed:.3f} duration={high_s:.3f}s")
        body: dict[str, Any] = {
            "mode": "static",
            "speed_mps": high_speed,
            "duration_s": high_s,
            "delay_s": 0.0,
        }
        if follower_robot:
            body["follower_robot"] = follower_robot
        if target_robot:
            body["target_robot"] = target_robot
        resp, err = _http_post(backend_url, "/attack/velocity_spoof", body)
        if err:
            warnings.append(f"Pulse high trigger error: {err}")
            evlog.add("pulse_high_error", err)
        elif not resp.get("ok", True):
            warnings.append(f"Pulse high returned ok=False: {resp}")
            evlog.add("pulse_high_nack", str(resp))
        _sleep(high_s, dry_run=False)

        if low_s > 0:
            evlog.add("pulse_low", f"{idx + 1}/{pulse_count} speed={low_speed:.3f} duration={low_s:.3f}s")
            body = {
                "mode": "static",
                "speed_mps": low_speed,
                "duration_s": low_s,
                "delay_s": 0.0,
            }
            if follower_robot:
                body["follower_robot"] = follower_robot
            if target_robot:
                body["target_robot"] = target_robot
            resp, err = _http_post(backend_url, "/attack/velocity_spoof", body)
            if err:
                warnings.append(f"Pulse low trigger error: {err}")
                evlog.add("pulse_low_error", err)
            elif not resp.get("ok", True):
                warnings.append(f"Pulse low returned ok=False: {resp}")
                evlog.add("pulse_low_nack", str(resp))
            _sleep(low_s, dry_run=False)

    return warnings


def run_trial(
    cfg: dict[str, Any],
    trial_number: int,
    rng: random.Random,
    trial_seed: int,
    output_dir: Path,
    *,
    dry_run: bool = False,
    startup_ignore_s: float = 3.0,
    is_first_trial: bool = True,
) -> dict[str, Any]:
    """Execute one randomized trial.  Returns a trial result dict.

    Uses the attack generator to sample a fresh strategy, compiles it to a
    backend request, runs the full recording/attack/analysis lifecycle, and
    returns a flat result dict. Runtime errors are recorded in the trial
    manifest/result without adding a separate excluded-results category.
    """
    experiment_id: str = cfg["experiment_id"]
    backend_url: str = cfg.get("backend_url", "http://localhost:8000")
    warmup_s: float = float(cfg.get("warmup_s", 10))
    effective_warmup_s: float = warmup_s if is_first_trial else 0.0
    recovery_s: float = float(cfg.get("recovery_s", 15))
    pre_run_settle_s: float = float(cfg.get("pre_run_settle_s", 3.0))
    baseline_stability_timeout_s: float = float(cfg.get("baseline_stability_timeout_s", 60.0))
    baseline_stability_window_s: float = float(cfg.get("baseline_stability_window_s", 5.0))
    thresholds: dict[str, Any] = cfg.get("formation_thresholds") or {}
    gen_cfg: dict[str, Any] = cfg["attack_generator"]

    trial_id = f"trial-{trial_number:04d}-{uuid.uuid4().hex[:8]}"
    evlog = EventLog()
    errors: list[str] = []
    warnings: list[str] = []
    run_id: str | None = None
    trial_dir: Path | None = None
    started_at: float | None = None
    stopped_at: float | None = None
    analysis: dict[str, Any] | None = None

    # ── Generate strategy ─────────────────────────────────────────────────────
    strategy = generate_attack_strategy(rng, gen_cfg)

    # Compile strategy to backend request; pulse is a logical request executed below.
    is_no_attack = strategy.get("attack_family") == "no_attack"
    attack_type: str
    attack_request: dict[str, Any]
    compilation_failed = False
    if is_no_attack:
        attack_type = "no_attack"
        attack_request = {}
    else:
        try:
            attack_type, attack_request = build_attack_request_from_strategy(strategy)
        except ValueError as exc:
            errors.append(f"Strategy compilation failed: {exc}")
            attack_type = strategy.get("attack_family", "unknown")
            attack_request = {}
            compilation_failed = True

    target_robot = strategy.get("target_robot")
    delay_s = float(strategy.get("delay_s", 0.0))
    duration_s = float(strategy.get("duration_s", 10.0))
    if is_no_attack:
        expected_attack_start_s = None
        expected_attack_end_s = None
    else:
        expected_attack_start_s = effective_warmup_s + delay_s
        expected_attack_end_s = expected_attack_start_s + duration_s

    manifest: dict[str, Any] = {
        "experiment_id": experiment_id,
        "campaign_id": experiment_id,     # for extract_metrics compatibility
        "trial_id": trial_id,
        "trial_number": trial_number,
        "scenario_id": attack_type,       # proxy for extract_metrics attack-type fallback
        "label": (
            f"Trial {trial_number}: {attack_type} / "
            f"{strategy.get('strategy', '?')} / "
            f"difficulty={strategy.get('attack_difficulty', '?')}"
        ),
        "run_id": None,
        "backend_url": backend_url,
        "seed": trial_seed,
        "started_at": None,
        "stopped_at": None,
        "attack_type": attack_type,
        "attack_family": strategy.get("attack_family"),
        "attack_strategy": strategy.get("strategy"),
        "attack_difficulty": strategy.get("attack_difficulty"),
        "target_robot": target_robot,
        "generated_attack_strategy": {k: v for k, v in strategy.items() if not k.startswith("_")},
        "resolved_attack_request": attack_request,
        "expected_attack_start_s": expected_attack_start_s,
        "expected_attack_end_s": expected_attack_end_s,
        "warmup_s": effective_warmup_s,
        "recovery_s": recovery_s,
        "git_commit": _git_commit(),
        "errors": errors,
        "warnings": warnings,
    }

    # ── Dry-run path ──────────────────────────────────────────────────────────
    if dry_run:
        manifest["run_id"] = "dry-run"
        formation = _analyze_formation(None, thresholds, False)
        result = _build_trial_result(
            {**manifest, "run_id": "dry-run"},
            None,
            formation,
            startup_ignore_s=startup_ignore_s,
        )
        return result

    # ── Compilation failure before recording ──────────────────────────────────
    if compilation_failed:
        trial_dir = output_dir / "trials" / trial_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        manifest["errors"] = errors
        (trial_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )
        evlog.write_csv(trial_dir / "events.csv")
        formation = _analyze_formation(None, thresholds, False)
        result = _build_trial_result(manifest, None, formation, startup_ignore_s=startup_ignore_s)
        (trial_dir / "trial_result.json").write_text(
            json.dumps(result, indent=2, default=str)
        )
        return result

    # ── Live execution ────────────────────────────────────────────────────────
    gate_excluded = False
    cb_cfg = cfg.get("clean_baseline") or {}
    cb_enabled = bool(cb_cfg.get("enabled", False))
    cb_timeout = float(cb_cfg.get("timeout_s", 60.0))
    cb_poll = float(cb_cfg.get("poll_s", 1.0))
    cb_on_timeout = str(cb_cfg.get("on_timeout", "warn_and_continue"))
    cb_req_alerts = bool(cb_cfg.get("require_no_live_alerts", True))
    cb_req_vs = bool(cb_cfg.get("require_no_current_velocity_spoof", True))
    cb_use_probe = bool(cb_cfg.get("use_probe_recording", False))
    cb_probe_s = float(cb_cfg.get("baseline_probe_s", 3.0))
    ps_cfg = cfg.get("platoon_state_gate") or {}
    ps_enabled = bool(ps_cfg.get("enabled", False))
    ps_timeout_raw = ps_cfg.get("timeout_s", 60.0)
    ps_timeout = None if ps_timeout_raw is None else float(ps_timeout_raw)
    ps_poll = float(ps_cfg.get("poll_s", 1.0))
    ps_on_timeout = str(ps_cfg.get("on_timeout", "warn_and_continue"))
    ps_reset_on_mismatch = bool(ps_cfg.get("reset_on_mismatch", True))
    ps_allowed_states = frozenset(
        int(s) for s in ps_cfg.get("allowed_target_states", [3, 4])
    )

    try:
        evlog.mark_start()

        # 1. Reset attack state
        evlog.add("pre_reset")
        _http_post(backend_url, "/attack/reset")

        # 2. Wait for attack idle
        evlog.add("wait_idle")
        ok, err = _wait_for_attack_idle(backend_url, timeout_s=10.0)
        if not ok:
            warnings.append(f"Attack not fully idle before trial: {err}")
            evlog.add("idle_timeout", str(err) if err else "timeout")

        # 3. Baseline stability settle
        evlog.add("baseline_settle", f"{pre_run_settle_s:.1f}s")
        ok, err = _wait_for_baseline_stable(
            backend_url,
            settle_s=pre_run_settle_s,
            timeout_s=baseline_stability_timeout_s,
            window_s=baseline_stability_window_s,
        )
        if not ok:
            warnings.append(f"Platoon did not return to baseline: {err}")
            evlog.add("baseline_unstable", str(err) if err else "timeout")

        # 3b. Clean live state gate — verify no stale velocity_spoof state
        # before starting the recording.  Stale live state is the primary cause
        # of pre_attack_detection=True in recordings that should be clean.
        if cb_enabled:
            evlog.add("clean_baseline_gate_start", f"timeout={cb_timeout:.0f}s")
            clean_ok, clean_reason = _wait_for_clean_live_state(
                backend_url,
                timeout_s=cb_timeout,
                poll_s=cb_poll,
                require_no_live_alerts=cb_req_alerts,
                require_no_current_velocity_spoof=cb_req_vs,
            )
            if clean_ok:
                evlog.add("clean_baseline_gate_ok")
            else:
                evlog.add("clean_baseline_gate_failed", clean_reason or "timeout")
            gate_excluded = _handle_gate_failure(
                clean_ok, clean_reason, cb_on_timeout, errors, warnings
            )

        # 3c. Optional baseline probe recording (disabled by default)
        if not gate_excluded and cb_enabled and cb_use_probe:
            trial_dir = output_dir / "trials" / trial_id
            trial_dir.mkdir(parents=True, exist_ok=True)
            evlog.add("baseline_probe_start", f"{cb_probe_s:.1f}s")
            probe_ok, probe_reason = _run_baseline_probe(
                backend_url, experiment_id, trial_number, trial_dir, cb_probe_s
            )
            if probe_ok:
                evlog.add("baseline_probe_ok")
            else:
                evlog.add("baseline_probe_failed", probe_reason or "unknown")
                gate_excluded = _handle_gate_failure(
                    False, f"Probe: {probe_reason}", cb_on_timeout, errors, warnings
                )

        # 3d. Target-state gate -- attacks are only meaningful when the selected
        # follower is in PLATOONING (3) or RECOVERY (4), unless configured otherwise.
        if not gate_excluded and ps_enabled and not is_no_attack:
            states_desc = ",".join(str(s) for s in sorted(ps_allowed_states))
            timeout_desc = "forever" if ps_timeout is None or ps_timeout <= 0 else f"{ps_timeout:.0f}s"
            evlog.add(
                "platoon_state_gate_start",
                f"target={target_robot} states={states_desc} timeout={timeout_desc}",
            )
            state_ok, state_reason, observed_state = _wait_for_target_platoon_state(
                backend_url,
                target_robot,
                timeout_s=ps_timeout,
                poll_s=ps_poll,
                allowed_states=ps_allowed_states,
                reset_on_mismatch=ps_reset_on_mismatch,
                verbose=True,
            )
            if state_ok:
                evlog.add(
                    "platoon_state_gate_ok",
                    f"target={target_robot} state={observed_state}",
                )
            else:
                evlog.add("platoon_state_gate_failed", state_reason or "timeout")
            gate_excluded = _handle_gate_failure(
                state_ok,
                state_reason,
                ps_on_timeout,
                errors,
                warnings,
                gate_name="Platoon target-state gate",
            )

        # Steps 4-11 only run when the gate blocks did not stop this trial.
        if not gate_excluded:
            # 4. Start recording
            run_name = f"{experiment_id}__trial_{trial_number:04d}"
            resp, err = _http_post(
                backend_url, "/live/capture/start", {"name": run_name}, timeout=15
            )
            if err:
                raise RuntimeError(f"Failed to start recording: {err}")
            run_id = resp.get("run_id")
            if not run_id:
                raise RuntimeError(f"No run_id in start response: {resp}")

            manifest["run_id"] = run_id
            started_at = time.time()
            manifest["started_at"] = started_at
            evlog.add("recording_start", f"run_id={run_id}")

            trial_dir = output_dir / "trials" / trial_id
            trial_dir.mkdir(parents=True, exist_ok=True)

            # 5. Warmup
            evlog.add("warmup_start", f"{effective_warmup_s:.1f}s")
            _sleep(effective_warmup_s, dry_run=False)
            evlog.add("warmup_end")

            # 6. Trigger attack (skipped for no_attack trials)
            if is_no_attack:
                evlog.add("no_attack_recording", f"duration={duration_s:.1f}s")
            else:
                evlog.add(
                    "attack_trigger",
                    (
                        f"type={attack_type} strategy={strategy.get('strategy')} "
                        f"follower={attack_request.get('follower_robot')} "
                        f"topic_target={attack_request.get('target_robot')}"
                    ),
                )
                if attack_request.get("mode") == "pulse":
                    pulse_warnings = _run_pulse_attack(backend_url, attack_request, evlog)
                    warnings.extend(pulse_warnings)
                    evlog.add("pulse_complete")
                else:
                    attack_resp, err = _http_post(backend_url, f"/attack/{attack_type}", attack_request)
                    if err:
                        warnings.append(f"Attack trigger error: {err}")
                        evlog.add("attack_trigger_error", err)
                    elif not attack_resp.get("ok", True):
                        warnings.append(f"Attack returned ok=False: {attack_resp}")
                        evlog.add("attack_nack", str(attack_resp))
                    else:
                        evlog.add("attack_accepted")

                evlog.add("expected_attack_fire", f"t={expected_attack_start_s:.1f}s")
                evlog.add("expected_attack_end", f"t={expected_attack_end_s:.1f}s")

            # 7. Wait through attack window and recovery
            if is_no_attack:
                evlog.add("recording_window_wait", f"{duration_s:.1f}s")
                _sleep(duration_s, dry_run=False)
            elif attack_request.get("mode") != "pulse":
                evlog.add("attack_window_wait", f"{delay_s + duration_s:.1f}s")
                _sleep(delay_s + duration_s, dry_run=False)
            evlog.add("recovery_start", f"{recovery_s:.1f}s")
            _sleep(recovery_s, dry_run=False)
            evlog.add("recovery_end")

            # 8. Reset (tamper-service auto-expires, but belt-and-suspenders)
            if not is_no_attack:
                _http_post(backend_url, f"/attack/{attack_type}/stop")
            _http_post(backend_url, "/attack/reset")
            evlog.add("post_reset")

            # 9. Stop recording
            evlog.add("recording_stop")
            _, err = _http_post(backend_url, "/live/capture/stop", timeout=15)
            stopped_at = time.time()
            manifest["stopped_at"] = stopped_at
            if err:
                warnings.append(f"Stop recording error: {err}")

            _sleep(_POST_STOP_SETTLE_S, dry_run=False)

            # 10. Fetch recording analysis
            analysis, err = _http_get(backend_url, f"/recordings/{run_id}", timeout=20)
            if err:
                warnings.append(f"Analysis fetch error: {err}")
                analysis = None
                evlog.add("analysis_fetch_error", err)
            else:
                (trial_dir / "recording_analysis.json").write_text(
                    json.dumps(analysis, indent=2, default=str)
                )
                evlog.add("analysis_fetched")

            # 11. Fetch risk + alerts snapshots
            risk_snap, err = _http_get(backend_url, "/risk/system", timeout=15)
            if err:
                warnings.append(f"Risk snapshot error: {err}")
            else:
                (trial_dir / "risk_snapshot.json").write_text(
                    json.dumps(risk_snap, indent=2, default=str)
                )

            alerts_resp, err = _http_get(backend_url, "/risk/alerts", timeout=10)
            if err:
                warnings.append(f"Alerts fetch error: {err}")
            else:
                (trial_dir / "live_alerts.json").write_text(
                    json.dumps(alerts_resp, indent=2, default=str)
                )

    except Exception as exc:
        errors.append(str(exc))
        evlog.add("error", str(exc))
        _log(f"  ERROR trial {trial_number}: {exc}")

    finally:
        try:
            _http_post(backend_url, "/attack/reset")
        except Exception:
            pass

        manifest["errors"] = errors
        manifest["warnings"] = warnings
        if trial_dir is None:
            trial_dir = output_dir / "trials" / trial_id
            trial_dir.mkdir(parents=True, exist_ok=True)
        evlog.write_csv(trial_dir / "events.csv")
        (trial_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )

    # Build result; patch undetected_physical_impact after detected is known
    formation = _analyze_formation(analysis, thresholds, detected=False)
    result = _build_trial_result(manifest, analysis, formation, startup_ignore_s=startup_ignore_s)
    upi = formation["out_of_formation"] and not result["detected"]
    formation["undetected_physical_impact"] = upi
    result["undetected_physical_impact"] = upi

    (trial_dir / "trial_result.json").write_text(
        json.dumps(result, indent=2, default=str)
    )
    return result


# ── Experiment loop ───────────────────────────────────────────────────────────

def run_experiment(
    cfg: dict[str, Any],
    output_root: Path,
    *,
    seed: int | None = None,
    max_trials: int | None = None,
    dry_run: bool = False,
    startup_ignore_s: float = 3.0,
) -> None:
    """Run the continuous randomized trial loop until interrupted or max_trials reached."""
    experiment_id: str = cfg["experiment_id"]
    backend_url: str = cfg.get("backend_url", "http://localhost:8000")

    # Resolve seed: CLI > YAML > generated
    if seed is not None:
        campaign_seed = int(seed)
        seed_source = "CLI"
    elif cfg.get("random_seed") is not None:
        campaign_seed = int(cfg["random_seed"])
        seed_source = "config"
    else:
        campaign_seed = random.randint(0, 2**31 - 1)
        seed_source = "generated"

    output_dir = output_root / experiment_id
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    started_at = time.time()
    results: list[dict[str, Any]] = []

    _stop_requested = False

    def _handle_sigint(sig: int, frame: object) -> None:
        nonlocal _stop_requested
        _stop_requested = True
        print("\n\n  Ctrl+C -- stopping after this trial...", flush=True)

    original_handler = signal.signal(signal.SIGINT, _handle_sigint)

    max_str = str(max_trials) if max_trials else "unlimited"
    print(f"\n{'-'*72}")
    print(f"TwinGuard randomized trials")
    print(f"Experiment : {experiment_id}")
    print(f"Seed       : {campaign_seed} ({seed_source})")
    print(f"Max trials : {max_str}")
    print(f"Backend    : {backend_url}")
    if dry_run:
        print("Mode       : DRY-RUN")
        print("Output     : no files written")
        print(f"Real output: {output_dir}")
    else:
        print(f"Output     : {output_dir}")
    print(f"{'-'*72}")

    if not dry_run:
        ok, msg = check_backend(backend_url)
        if not ok:
            print(f"Backend warning: {msg}")
            print("Proceeding; trials will record errors.")
        else:
            print(f"Backend OK : {msg}")
    print("Stop with Ctrl+C after the current trial.\n")
    print(
        f"{'trial':>5}  {'out':<4}  {'family':<12}  {'strategy':<14}  "
        f"{'diff':<6}  {'ttd':<8}  {'risk':<9}  notes",
        flush=True,
    )
    print("-" * 72, flush=True)

    csv_path = output_dir / "trials_summary.csv"
    existing_trials = 0 if dry_run else _existing_trial_count(csv_path)
    csv_needs_header = (
        not dry_run
        and (not csv_path.exists() or csv_path.stat().st_size <= 0)
    )
    csv_file = None if dry_run else open(csv_path, "a", newline="", encoding="utf-8")
    try:
        csv_writer = None
        if csv_file is not None:
            csv_writer = csv.DictWriter(
                csv_file, fieldnames=TRIAL_CSV_FIELDS, extrasaction="ignore"
            )
            if csv_needs_header:
                csv_writer.writeheader()
            csv_file.flush()

        completed_this_session = 0
        trial_number = existing_trials
        while not _stop_requested:
            if max_trials is not None and completed_this_session >= max_trials:
                print(f"\nReached max-trials ({max_trials}). Stopping.", flush=True)
                break

            trial_number += 1
            completed_this_session += 1
            trial_seed = _make_rep_seed(campaign_seed, experiment_id, trial_number)
            rng = random.Random(trial_seed)

            result = run_trial(
                cfg,
                trial_number,
                rng,
                trial_seed,
                output_dir,
                dry_run=dry_run,
                startup_ignore_s=startup_ignore_s,
                is_first_trial=(completed_this_session == 1),
            )
            results.append(result)

            if csv_writer is not None and csv_file is not None:
                csv_writer.writerow({k: result.get(k) for k in TRIAL_CSV_FIELDS})
                csv_file.flush()

            # One-line summary for this trial
            det_tag = "det" if result.get("detected") else "miss"
            family = str(result.get("attack_family") or "?")[:12]
            strat = str(result.get("attack_strategy") or "?")[:14]
            difficulty = str(result.get("attack_difficulty") or "?")[:6]
            ttd = result.get("time_to_detection_s")
            ttd_str = f"{ttd:.1f}s" if ttd is not None else "-"
            risk = str(result.get("worst_risk_level", "?"))[:9]
            tags: list[str] = []
            if completed_this_session == 1:
                wu_cfg = float(cfg.get("warmup_s", 10))
                tags.append(f"warmup={wu_cfg:.0f}s")
            if result.get("attack_family") == "no_attack" and result.get("detected"):
                tags.append("FP")
            if result.get("out_of_formation"):
                tags.append("OOF")
            if result.get("undetected_physical_impact"):
                tags.append("undetected-OOF")
            if result.get("pre_attack_detection"):
                tags.append("pre-attack")
            if result.get("excluded"):
                tags.append("excluded")
            print(
                f"{trial_number:5d}  {det_tag:<4}  {family:<12}  {strat:<14}  "
                f"{difficulty:<6}  {ttd_str:<8}  {risk:<9}  {', '.join(tags)}",
                flush=True,
            )

    finally:
        if csv_file is not None:
            csv_file.close()
        stopped_at = time.time()
        signal.signal(signal.SIGINT, original_handler)

        summary = _build_experiment_summary(
            results, cfg, started_at, stopped_at, campaign_seed
        )
        _print_final_summary(summary)
        if dry_run:
            print("Dry-run only: no summary files were written.")
        else:
            (output_dir / "experiment_summary.json").write_text(
                json.dumps(summary, indent=2, default=str)
            )
            print(f"Summary CSV : {csv_path}")
            print(f"Summary JSON: {output_dir / 'experiment_summary.json'}")
        if seed_source == "generated":
            print(f"To reproduce: --seed {campaign_seed}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TwinGuard continuous randomized adversarial trial runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  # Run continuously until Ctrl+C
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml

  # Fixed seed for reproducibility
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml --seed 1337

  # Cap at 50 trials then stop
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml --max-trials 50

  # Dry-run: show generated strategies without hitting the backend
  python experiments/run_randomized_trials.py \\
      --config experiments/scenarios/randomized_trials.yaml --dry-run --seed 1337
""",
    )
    parser.add_argument(
        "--config", required=True, help="Path to randomized-trials YAML config"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Override random seed (overrides config random_seed)"
    )
    parser.add_argument(
        "--max-trials", type=int, default=None,
        help="Stop after this many trials (default: run until Ctrl+C)"
    )
    parser.add_argument(
        "--output-root", default=None,
        help="Override output root directory"
    )
    parser.add_argument(
        "--backend-url", default=None,
        help="Override backend URL from config"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print generated strategies without making HTTP calls"
    )
    parser.add_argument(
        "--startup-ignore-s", type=float, default=3.0,
        help="Ignore anomaly frames in first N seconds of each recording (default: 3.0)"
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    cfg = load_config(Path(args.config))
    if args.backend_url:
        cfg["backend_url"] = args.backend_url
    output_root = Path(args.output_root) if args.output_root else _DEFAULT_OUTPUT_ROOT
    run_experiment(
        cfg,
        output_root,
        seed=args.seed,
        max_trials=args.max_trials,
        dry_run=args.dry_run,
        startup_ignore_s=args.startup_ignore_s,
    )


if __name__ == "__main__":
    main()
