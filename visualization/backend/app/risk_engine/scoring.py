"""Likelihood and impact scoring for TwinGuard risk signals."""

from __future__ import annotations

import uuid

from .models import RiskObject, risk_level_from_score
from .nist_catalog import CSF_MAPPINGS, IR_ACTIONS


def _clamp(value: int, lo: int = 1, hi: int = 5) -> int:
    return max(lo, min(hi, value))


def _new_id() -> str:
    return f"ri_{uuid.uuid4().hex[:8]}"


def session_completeness(
    frame_count: int,
    parse_errors: int,
) -> float:
    """Estimate evidence completeness in the interval [0.0, 1.0]."""
    if frame_count == 0:
        return 0.0

    completeness = 1.0
    error_ratio = parse_errors / max(frame_count + parse_errors, 1)
    completeness -= min(0.30, error_ratio * 3)

    if frame_count < 50:
        completeness -= 0.20
    elif frame_count < 100:
        completeness -= 0.10

    return round(max(0.10, min(1.0, completeness)), 3)


def score_velocity_spoof(
    *,
    run_id: str,
    source_type: str,
    affected_robots: list[str],
    detection_frames: int,
    total_frames: int,
    first_frame: int | None,
    last_frame: int | None,
    first_t: float | None,
    last_t: float | None,
    max_speed_delta: float | None,
    spoof_kind_counts: dict[str, int],
    completeness: float,
) -> RiskObject:
    """Score one velocity-spoof risk finding."""
    ratio = detection_frames / max(total_frames, 1)
    detection_span_s = max(0.0, last_t - first_t) if first_t is not None and last_t is not None else 0.0

    likelihood = 2
    if detection_frames >= 5 or detection_span_s >= 0.5:
        likelihood += 1
    if ratio >= 0.05 or detection_frames >= 25 or detection_span_s >= 2.0:
        likelihood += 1
    if len(affected_robots) > 1 or (ratio >= 0.20 and detection_span_s >= 2.0):
        likelihood += 1
    if completeness < 0.60:
        likelihood -= 1
    dominant_kind = _dominant_kind(spoof_kind_counts)
    observed_kinds = sorted(spoof_kind_counts)
    if dominant_kind == "zeroed":
        likelihood += 1
    likelihood = _clamp(likelihood)

    impact = 3
    if len(affected_robots) > 1:
        impact += 1
    if max_speed_delta is not None and max_speed_delta >= 0.50:
        impact += 1
    elif max_speed_delta is not None and max_speed_delta >= 0.20 and len(affected_robots) == 1:
        impact += 1
    if dominant_kind == "zeroed":
        impact += 1
    impact = _clamp(impact)

    risk_score = likelihood * impact

    raw_confidence = 0.50
    if detection_frames >= 5:
        raw_confidence += 0.10
    if detection_span_s >= 0.5:
        raw_confidence += 0.10
    if len(affected_robots) > 1:
        raw_confidence += 0.10
    if max_speed_delta is not None:
        raw_confidence += 0.05
    if ratio >= 0.05:
        raw_confidence += 0.05
    raw_confidence = min(0.95, raw_confidence)
    confidence = round(raw_confidence * (0.5 + 0.5 * completeness), 3)
    confidence = max(0.10, min(0.95, confidence))

    evidence_parts = [
        f"Velocity spoof detected in {detection_frames}/{total_frames} frames ({ratio:.1%} ratio).",
        f"Affected robot(s): {', '.join(affected_robots)}.",
    ]
    if dominant_kind is not None:
        evidence_parts.append(f"Dominant spoof type: {dominant_kind}.")
    if observed_kinds:
        evidence_parts.append(f"Observed spoof types: {', '.join(observed_kinds)}.")
    if detection_span_s > 0:
        evidence_parts.append(f"Detection window spans {detection_span_s:.2f} s.")
    if max_speed_delta is not None:
        evidence_parts.append(f"Maximum observed physical speed range: {max_speed_delta:.3f} m/s.")

    assumptions = [
        "ScenarioTwin detection threshold is 0.05 m/s between leader velocity and received leader_input_v.",
        "leader_input_v reflects the signal received by the follower over the V2V channel.",
        "Velocity spoof subtypes currently include zeroed, underreported, overreported, fixed, and ramped.",
        "A dominant zeroed spoof is treated as more severe because it can force the follower to perceive a stopped leader.",
        "Likelihood reflects evidence credibility and repeatability, not only affected-frame percentage.",
        "Impact is conservative because proximity, stopping distance, collision state, and operator override state are not yet recorded.",
        "Detection count is a conservative lower bound; completeness losses may mean misses exist.",
    ]

    actions = IR_ACTIONS.get("velocity_spoof", []) if risk_score >= 10 else []
    return RiskObject(
        id=_new_id(),
        source_type=source_type,
        run_id=run_id,
        frame_range=(first_frame, last_frame) if first_frame is not None and last_frame is not None else None,
        timestamp_range=(first_t, last_t) if first_t is not None and last_t is not None else None,
        affected_robots=list(affected_robots),
        signal_type="velocity_spoof",
        signal_subtype=dominant_kind,
        observed_signal_subtypes=observed_kinds,
        evidence_summary=" ".join(evidence_parts),
        likelihood=likelihood,
        impact=impact,
        risk_score=risk_score,
        risk_level=risk_level_from_score(risk_score),
        assumptions=assumptions,
        confidence=confidence,
        completeness=completeness,
        csf_mappings=CSF_MAPPINGS.get("velocity_spoof", []),
        incident_actions=actions,
    )


def _dominant_kind(kind_counts: dict[str, int]) -> str | None:
    """Return the most common spoof subtype, preferring alphabetical order on ties."""
    if not kind_counts:
        return None
    return min(kind_counts.items(), key=lambda item: (-item[1], item[0]))[0]
