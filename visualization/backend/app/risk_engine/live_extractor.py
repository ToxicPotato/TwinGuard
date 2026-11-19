"""Derive NIST findings from already-materialized live recording analysis."""

from __future__ import annotations

from typing import Any

from .models import build_risk_matrix
from .scoring import score_velocity_spoof, session_completeness


def derive_nist_findings(
    run_id: str,
    meta: dict[str, Any],
    analysis: dict[str, Any],
) -> dict:
    """Build NIST findings from persisted recording metadata and analysis."""
    frame_count = int(analysis.get("frame_count") or 0)
    parse_errors = int(analysis.get("parse_errors") or 0)
    anomaly_frames = int(analysis.get("anomaly_frames") or 0)
    robots: dict[str, Any] = analysis.get("robots") or {}
    completeness = session_completeness(
        frame_count=frame_count,
        parse_errors=parse_errors,
    )

    risk_objects: list[dict] = []
    if anomaly_frames > 0:
        affected_robots: list[str] = []
        max_speed_delta: float | None = None
        first_t: float | None = None
        last_t: float | None = None
        spoof_kind_counts: dict[str, int] = {}

        for robot_id, robot in robots.items():
            spoof_frames = int(robot.get("velocity_spoof_frames") or 0)
            if spoof_frames <= 0:
                continue
            affected_robots.append(robot_id)

            speed_min = robot.get("speed_min")
            speed_max = robot.get("speed_max")
            if isinstance(speed_min, (int, float)) and isinstance(speed_max, (int, float)):
                delta = abs(float(speed_max) - float(speed_min))
                if max_speed_delta is None or delta > max_speed_delta:
                    max_speed_delta = delta

            first_detection = robot.get("first_velocity_spoof_t")
            last_detection = robot.get("last_velocity_spoof_t")
            if isinstance(first_detection, (int, float)):
                first_t = float(first_detection) if first_t is None else min(first_t, float(first_detection))
            if isinstance(last_detection, (int, float)):
                last_t = float(last_detection) if last_t is None else max(last_t, float(last_detection))

            kind_counts = robot.get("velocity_spoof_kind_counts")
            if isinstance(kind_counts, dict):
                for kind, count in kind_counts.items():
                    if isinstance(kind, str) and isinstance(count, (int, float)) and count > 0:
                        spoof_kind_counts[kind] = spoof_kind_counts.get(kind, 0) + int(count)

        if affected_robots:
            risk_objects.append(
                score_velocity_spoof(
                    run_id=run_id,
                    source_type="live_recording",
                    affected_robots=affected_robots,
                    detection_frames=anomaly_frames,
                    total_frames=frame_count,
                    first_frame=None,
                    last_frame=None,
                    first_t=first_t,
                    last_t=last_t,
                    max_speed_delta=max_speed_delta,
                    spoof_kind_counts=spoof_kind_counts,
                    completeness=completeness,
                ).to_dict()
            )

    matrix = build_risk_matrix(risk_objects)
    return {
        "risk_objects": risk_objects,
        "matrix": matrix,
        "completeness": completeness,
        "worst_risk_level": _worst_level(risk_objects),
        "rerun_decision": _build_rerun_decision(risk_objects, completeness),
        "nist_summary": _build_summary(risk_objects, completeness),
    }


def _worst_level(risk_objects: list[dict]) -> str:
    order = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
    worst = "low"
    for risk_object in risk_objects:
        level = risk_object.get("risk_level", "low")
        if order.get(level, 0) > order.get(worst, 0):
            worst = level
    return worst


def _build_summary(risk_objects: list[dict], completeness: float) -> dict:
    counts: dict[str, int] = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
    for risk_object in risk_objects:
        level = risk_object.get("risk_level", "low")
        if level in counts:
            counts[level] += 1
    average_confidence = (
        round(sum(risk_object.get("confidence", 0) for risk_object in risk_objects) / len(risk_objects), 3)
        if risk_objects
        else 0.0
    )
    return {
        "total_findings": len(risk_objects),
        "level_counts": counts,
        "avg_confidence": average_confidence,
        "session_completeness": completeness,
        "nist_methods": [
            "NIST SP 800-30 Rev. 1 (risk scoring)",
            "NIST CSF 2.0 (outcome categorization)",
            "NIST SP 800-61 Rev. 3 (incident handling recommendations)",
        ],
    }


def _build_rerun_decision(risk_objects: list[dict], completeness: float) -> dict:
    if not risk_objects:
        return {
            "decision": "safe_to_rerun",
            "label": "Safe to rerun",
            "severity": "low",
            "next_run_allowed": True,
            "reason": "No velocity-spoof NIST finding was generated for this valid recording.",
            "required_actions": [
                "Keep the recording available for traceability.",
                "Continue normal pre-run checks before the next run.",
            ],
        }

    worst = max(risk_objects, key=lambda risk_object: int(risk_object.get("risk_score", 0)))
    level = str(worst.get("risk_level", "low"))
    affected = worst.get("affected_robots") or []
    affected_count = len(affected) if isinstance(affected, list) else 0
    score = int(worst.get("risk_score", 0))
    likelihood = int(worst.get("likelihood", 1))
    impact = int(worst.get("impact", 1))

    reason = (
        f"Velocity spoof risk is {level} with score {score}/25 "
        f"(likelihood {likelihood}/5, impact {impact}/5) across "
        f"{affected_count} affected robot(s). Evidence completeness is {round(completeness * 100)}%."
    )

    if level == "critical":
        return {
            "decision": "do_not_rerun_until_contained",
            "label": "Do not rerun until contained",
            "severity": "critical",
            "next_run_allowed": False,
            "reason": reason,
            "required_actions": [
                "Place affected robots into the approved safe state before any new run.",
                "Preserve robot, controller, broker, network, and recording evidence.",
                "Isolate the command channel by blocking suspect publishers and enforcing topic ACLs.",
                "Validate controller configuration, leader-follower assignment, fail-safe limits, and command authentication before recovery.",
            ],
        }

    if level == "high":
        return {
            "decision": "investigate_before_rerun",
            "label": "Investigate before rerun",
            "severity": "high",
            "next_run_allowed": False,
            "reason": reason,
            "required_actions": [
                "Preserve the session recording and control-channel logs.",
                "Confirm whether the injection was expected, controlled, or unauthorized.",
                "Check affected robot state and operator intervention records.",
                "Validate MQTT/broker write permissions before the next run.",
            ],
        }

    if level == "moderate":
        return {
            "decision": "review_before_rerun",
            "label": "Review before rerun",
            "severity": "moderate",
            "next_run_allowed": True,
            "reason": reason,
            "required_actions": [
                "Review the detection window and affected robot list.",
                "Confirm whether this was an expected test injection.",
                "Run a clean baseline first if the injection was unexpected.",
            ],
        }

    return {
        "decision": "safe_to_rerun",
        "label": "Safe to rerun",
        "severity": "low",
        "next_run_allowed": True,
        "reason": reason,
        "required_actions": [
            "Record the finding for traceability.",
            "Continue normal pre-run checks before the next run.",
        ],
    }
