"""System-wide risk assessment aggregating live attack state and historical recordings.

Canonical risk model
--------------------
NIST SP 800-30 levels (low / moderate / high / critical) are the single authoritative
scale for the overview page.  The coarse 0-100 / low-elevated-high labels produced by
RunAccumulator are mapped to NIST equivalents when no NIST findings are available.

Historical aggregation
----------------------
Runs are weighted by recency: weight(i) = exp(-0.3 * i) where i=0 is the most recent
run.  This means clean recent runs lower the baseline; a single old bad run cannot
permanently lock the score at its worst level.

Dominance rule: a live active threat always sets the floor.
  - live active  → overall ≥ high
  - live pending → overall ≥ moderate
  - detector sees velocity_spoof in rolling buffer → overall ≥ high (even without tamper-service)
  - no live threat → overall comes from the weighted historical score
"""

from __future__ import annotations

import math
import time
from typing import Any

from .models import build_risk_matrix, risk_level_from_score

_LEVEL_ORDER: dict[str, int] = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
_COARSE_TO_NIST: dict[str, str] = {"low": "low", "elevated": "moderate", "high": "high"}
_LEVEL_REPRESENTATIVE_SCORE: dict[str, int] = {"low": 2, "moderate": 6, "high": 12, "critical": 20}

# Normalized per-run score for the recency-weighted historical model (0–1).
_LEVEL_SCORE: dict[str, float] = {"low": 0.0, "moderate": 1 / 3, "high": 2 / 3, "critical": 1.0}

# Thresholds for mapping weighted score → NIST level (checked highest-first).
_WEIGHTED_THRESHOLDS: list[tuple[float, str]] = [
    (0.75, "critical"),
    (0.40, "high"),
    (0.12, "moderate"),
]

# Likelihood × Impact for synthesized current-state risk objects.
# Keys are (attack_type, status, detection_source_category):
#   detection_source_category: "confirmed" = tamper-service or detector+control; "sensor" = detector only
_CURRENT_THREAT_L_I: dict[tuple[str, str, str], tuple[int, int]] = {
    ("velocity_spoof", "active",  "confirmed"): (4, 4),  # 16 → high
    ("velocity_spoof", "active",  "sensor"):    (3, 4),  # 12 → high
    ("velocity_spoof", "pending", "confirmed"): (3, 4),  # 12 → high
    ("velocity_spoof", "pending", "sensor"):    (3, 4),  # 12 → high
    ("false_brake",    "active",  "confirmed"): (4, 5),  # 20 → critical
    ("false_brake",    "active",  "sensor"):    (3, 5),  # 15 → high
    ("false_brake",    "pending", "confirmed"): (3, 5),  # 15 → high
    ("false_brake",    "pending", "sensor"):    (3, 5),  # 15 → high
}

# Historical baseline → L×I when included as a current risk factor.
_HIST_BASELINE_L_I: dict[str, tuple[int, int]] = {
    "moderate": (2, 3),   # 6  → moderate
    "high":     (3, 4),   # 12 → high
    "critical": (4, 5),   # 20 → critical
}


def _nist_level(coarse: str) -> str:
    return _COARSE_TO_NIST.get(coarse, "low")


def _max_level(a: str, b: str) -> str:
    return a if _LEVEL_ORDER.get(a, 0) >= _LEVEL_ORDER.get(b, 0) else b


def _run_worst_nist_level(run: dict[str, Any]) -> str:
    """Return the worst NIST level found in a completed run."""
    nist = run.get("nist_findings")
    if nist:
        return str(nist.get("worst_risk_level") or "low")
    return _nist_level(str(run.get("risk") or "low"))


# ── Live threat analysis ──────────────────────────────────────────────────────

def _live_level_from_attack(attack_status: dict[str, Any]) -> tuple[str, int]:
    """Derive a NIST level and representative score from current tamper-service state."""
    fb_state = str((attack_status.get("false_brake") or {}).get("status") or "idle")
    vs_state = str((attack_status.get("velocity_spoof") or {}).get("status") or "idle")

    if fb_state == "active" or vs_state == "active":
        return "high", 15
    if fb_state == "pending" or vs_state == "pending":
        return "moderate", 6
    return "low", 0


def _build_live_alerts(attack_status: dict[str, Any]) -> list[dict[str, Any]]:
    """Build alert entries from current tamper-service attack control state."""
    now = time.time()
    alerts: list[dict[str, Any]] = []

    for attack_key in ("false_brake", "velocity_spoof"):
        sub = attack_status.get(attack_key) or {}
        state = str(sub.get("status") or "idle")
        if state not in ("active", "pending"):
            continue
        target = sub.get("target_robot")
        affected = [r for r in (sub.get("follower"), sub.get("target_robot")) if r]
        alerts.append({
            "id": f"live_{attack_key}_{target or 'all'}",
            "source": "live",
            "is_live": True,
            "run_id": None,
            "run_label": None,
            "attack_type": attack_key,
            "detection_source": "tamper-service",
            "affected_robots": affected,
            "status": state,
            "level": "high" if state == "active" else "moderate",
            "first_seen_at": now,
            "last_seen_at": now,
            "details": {
                k: sub[k]
                for k in ("remaining_s", "fires_in_s", "mode", "speed_mps", "speed_start", "speed_end")
                if sub.get(k) is not None
            },
        })
    return alerts


def _build_detector_live_alerts(live_detection: dict[str, Any]) -> list[dict[str, Any]]:
    """Build alert entries from rolling-buffer frame-label scanning."""
    now = time.time()
    alerts: list[dict[str, Any]] = []
    for attack in live_detection.get("attacks") or []:
        attack_type = str(attack.get("attack_type") or "velocity_spoof")
        robots = list(attack.get("robots") or [])
        alerts.append({
            "id": f"live_{attack_type}_detected",
            "source": "live",
            "is_live": True,
            "run_id": None,
            "run_label": None,
            "attack_type": attack_type,
            "detection_source": "detector",
            "affected_robots": robots,
            "status": "active",
            "level": "high",
            "first_seen_at": attack.get("first_seen_at") or now,
            "last_seen_at": attack.get("last_seen_at") or now,
            "details": {
                "frame_count": attack.get("frame_count"),
                "per_robot_frames": attack.get("per_robot_frames"),
            },
        })
    return alerts


def _merge_live_alerts(
    control_alerts: list[dict[str, Any]],
    detector_alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge tamper-service control alerts with detector alerts; same attack_type → one entry."""
    if not detector_alerts:
        return list(control_alerts)
    if not control_alerts:
        return list(detector_alerts)

    by_type: dict[str, dict[str, Any]] = {}
    for alert in control_alerts:
        by_type[alert["attack_type"]] = dict(alert)

    for alert in detector_alerts:
        atype = alert["attack_type"]
        if atype in by_type:
            existing = by_type[atype]
            combined = sorted(
                set(existing.get("affected_robots") or []) | set(alert.get("affected_robots") or [])
            )
            existing["detection_source"] = "detector+control"
            existing["affected_robots"] = combined
            existing["details"] = {**(existing.get("details") or {}), **(alert.get("details") or {})}
        else:
            by_type[atype] = dict(alert)

    return list(by_type.values())


# ── Historical analysis ───────────────────────────────────────────────────────

def _weighted_historical_contribution(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a recency-weighted historical baseline.

    Runs are expected in newest-first order (broadcaster.list_runs() returns that).
    Each run contributes weight exp(-0.3 * i), so clean recent runs dilute old bad ones.
    """
    level_counts: dict[str, int] = {"low": 0, "moderate": 0, "high": 0, "critical": 0}
    worst_ever_level = "low"
    worst_run_id: str | None = None
    total_findings = 0
    weighted_num = 0.0
    total_w = 0.0

    for i, run in enumerate(runs):
        w = math.exp(-0.3 * i)
        run_level = _run_worst_nist_level(run)
        weighted_num += w * _LEVEL_SCORE.get(run_level, 0.0)
        total_w += w

        nist = run.get("nist_findings")
        if nist:
            for obj in nist.get("risk_objects") or []:
                lvl = str(obj.get("risk_level") or "low")
                total_findings += 1
                if lvl in level_counts:
                    level_counts[lvl] += 1
                if _LEVEL_ORDER.get(lvl, 0) > _LEVEL_ORDER.get(worst_ever_level, 0):
                    worst_ever_level = lvl
                    worst_run_id = str(run.get("run_id") or "")
        else:
            nist_equiv = _nist_level(str(run.get("risk") or "low"))
            if nist_equiv != "low":
                total_findings += 1
                if nist_equiv in level_counts:
                    level_counts[nist_equiv] += 1
                if _LEVEL_ORDER.get(nist_equiv, 0) > _LEVEL_ORDER.get(worst_ever_level, 0):
                    worst_ever_level = nist_equiv
                    worst_run_id = str(run.get("run_id") or "")

    weighted_score = weighted_num / total_w if total_w > 0 else 0.0

    level = "low"
    for threshold, lvl in _WEIGHTED_THRESHOLDS:
        if weighted_score >= threshold:
            level = lvl
            break

    return {
        "level": level,
        "weighted_score": round(weighted_score, 4),
        "run_count": len(runs),
        "worst_run_id": worst_run_id,
        "worst_ever_level": worst_ever_level,
        "total_findings": total_findings,
        "level_counts": level_counts,
    }


def _build_current_risk_objects(
    live_alerts: list[dict[str, Any]],
    hist: dict[str, Any],
) -> list[dict[str, Any]]:
    """Synthesize NIST-compatible risk objects that represent the system's posture right now.

    One object per distinct live attack type (merged control+detector alert), plus one
    historical-baseline object when the weighted baseline is moderate or higher.
    Objects use source_type="current_live" and run_id="current" to distinguish them
    from persisted historical findings.
    """
    objects: list[dict[str, Any]] = []
    live_attack_types: set[str] = set()

    for alert in live_alerts:
        attack_type = str(alert.get("attack_type") or "unknown")
        status = str(alert.get("status") or "active")
        detection_source = str(alert.get("detection_source") or "tamper-service")
        affected = list(alert.get("affected_robots") or [])

        # Map detection source to one of two confidence categories.
        det_cat = "confirmed" if detection_source in ("tamper-service", "detector+control") else "sensor"
        key = (attack_type, status, det_cat)
        l_i = _CURRENT_THREAT_L_I.get(key) or _CURRENT_THREAT_L_I.get((attack_type, "active", det_cat))
        if l_i is None:
            l_i = (3, 3)
        likelihood, impact = l_i
        risk_score = likelihood * impact
        risk_level = risk_level_from_score(risk_score)

        confidence = 0.95 if det_cat == "confirmed" else 0.75
        source_desc = {
            "tamper-service":   "attack-control confirmed",
            "detector+control": "sensor labels + attack-control confirmed",
            "detector":         "sensor labels detected",
        }.get(detection_source, detection_source)

        live_attack_types.add(attack_type)
        objects.append({
            "id": f"current_{attack_type}_live",
            "source_type": "current_live",
            "run_id": "current",
            "frame_range": None,
            "timestamp_range": None,
            "affected_robots": affected,
            "signal_type": f"{attack_type}_live",
            "signal_subtype": detection_source,
            "observed_signal_subtypes": [detection_source],
            "evidence_summary": (
                f"Active {attack_type.replace('_', ' ')} detected via {source_desc}."
                + (f" Robots: {', '.join(affected)}." if affected else "")
            ),
            "likelihood": likelihood,
            "impact": impact,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "assumptions": [
                f"Detection source: {source_desc}.",
                f"Likelihood {likelihood}/5: {'confirmed injection in progress' if det_cat == 'confirmed' else 'sensor-label evidence only, injection unconfirmed'}.",
                f"Impact {impact}/5: physical-safety consequence of {attack_type.replace('_', ' ')} in a platooning scenario.",
            ],
            "confidence": confidence,
            "completeness": 1.0,
            "csf_mappings": [],
            "incident_actions": [],
        })

    # Historical baseline as a current risk factor (only when meaningful).
    hist_level = hist.get("level", "low")
    if hist_level != "low":
        l_i = _HIST_BASELINE_L_I.get(hist_level)
        if l_i:
            likelihood, impact = l_i
            risk_score = likelihood * impact
            weighted_score = hist.get("weighted_score", 0.0)
            run_count = int(hist.get("run_count") or 0)
            finding_count = int(hist.get("total_findings") or 0)
            objects.append({
                "id": "current_historical_baseline",
                "source_type": "current_live",
                "run_id": "current",
                "frame_range": None,
                "timestamp_range": None,
                "affected_robots": [],
                "signal_type": "historical_baseline",
                "signal_subtype": hist_level,
                "observed_signal_subtypes": [hist_level],
                "evidence_summary": (
                    f"Recency-weighted historical baseline: {hist_level}. "
                    f"{run_count} completed run(s), {finding_count} finding(s). "
                    f"Weighted score {weighted_score:.3f}."
                ),
                "likelihood": likelihood,
                "impact": impact,
                "risk_score": risk_score,
                "risk_level": hist_level,
                "assumptions": [
                    f"Weighted score {weighted_score:.3f} across {run_count} run(s) maps to {hist_level}.",
                    f"Likelihood {likelihood}/5 reflects recency-weighted frequency of past malicious findings.",
                    f"Impact {impact}/5 reflects safety-relevant consequences observed in recorded data.",
                    "This object is suppressed when weighted baseline is low.",
                ],
                "confidence": 0.70,
                "completeness": round(min(1.0, run_count / 5), 3),
                "csf_mappings": [],
                "incident_actions": [],
            })

    if not objects:
        objects.append({
            "id": "current_no_threat",
            "source_type": "current_live",
            "run_id": "current",
            "frame_range": None,
            "timestamp_range": None,
            "affected_robots": [],
            "signal_type": "no_active_threat",
            "signal_subtype": None,
            "observed_signal_subtypes": [],
            "evidence_summary": "No active threats detected and historical baseline is low.",
            "likelihood": 1,
            "impact": 1,
            "risk_score": 1,
            "risk_level": "low",
            "assumptions": ["No live threats detected.", "Recency-weighted historical baseline is low."],
            "confidence": 1.0,
            "completeness": 1.0,
            "csf_mappings": [],
            "incident_actions": [],
        })

    return objects


def _evidence_quality(runs: list[dict[str, Any]], live_connected: bool) -> dict[str, Any]:
    runs_with_nist = sum(1 for r in runs if r.get("nist_findings"))
    runs_without_nist = len(runs) - runs_with_nist
    notes: list[str] = []
    completeness = 1.0

    if not live_connected:
        notes.append("Live sensor feed not connected — live threat detection unavailable.")
        completeness -= 0.30

    if not runs:
        notes.append("No completed recordings — historical baseline is unavailable.")
        completeness -= 0.20
    elif runs_without_nist > 0:
        ratio = runs_without_nist / max(1, len(runs))
        notes.append(
            f"{runs_without_nist} of {len(runs)} recording(s) lack NIST analysis"
            " and contribute coarse-level estimates only."
        )
        completeness -= 0.10 * min(1.0, ratio)

    return {
        "data_completeness": round(max(0.0, completeness), 3),
        "runs_with_nist": runs_with_nist,
        "runs_without_nist": runs_without_nist,
        "live_connected": live_connected,
        "notes": notes,
    }


def _run_summaries(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for run in runs:
        nist = run.get("nist_findings") or {}
        out.append({
            "run_id": run.get("run_id"),
            "name": run.get("name", ""),
            "status": run.get("status", "unknown"),
            "started_at": run.get("started_at"),
            "ended_at": run.get("ended_at"),
            "duration_s": run.get("duration_s"),
            "frame_count": int(run.get("frame_count") or 0),
            "nist_level": nist.get("worst_risk_level") or _nist_level(str(run.get("risk") or "low")),
            "coarse_score": int(run.get("risk_score") or 0),
            "has_nist": bool(run.get("nist_findings")),
            "finding_count": len(nist.get("risk_objects") or []),
        })
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def compute_live_alerts_only(
    attack_status: dict[str, Any],
    live_detection: dict[str, Any],
    live_run_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lightweight alert computation with no disk reads — for fast polling."""
    control_alerts = _build_live_alerts(attack_status)
    detector_alerts = _build_detector_live_alerts(live_detection)
    active_alerts = _merge_live_alerts(control_alerts, detector_alerts)

    live_level, _ = _live_level_from_attack(attack_status)
    if detector_alerts and live_level == "low":
        live_level = "high"

    return {
        "overall_level": live_level,
        "active_alerts": active_alerts,
        "live_run_state": live_run_state,
        "computed_at": time.time(),
    }


def compute_system_assessment(
    runs: list[dict[str, Any]],
    attack_status: dict[str, Any],
    live_status: dict[str, Any],
    live_detection: dict[str, Any] | None = None,
    live_run_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a system-wide risk assessment.

    Live active threats dominate: historical evidence raises the baseline but
    cannot hide or suppress a detected live threat.  The historical score uses
    recency weighting so clean recent runs can lower the baseline.
    """
    live_connected = bool(live_status.get("connected"))

    live_level, live_score = _live_level_from_attack(attack_status)
    control_alerts = _build_live_alerts(attack_status)
    detector_alerts = _build_detector_live_alerts(live_detection or {})
    live_alerts = _merge_live_alerts(control_alerts, detector_alerts)

    if detector_alerts and live_level == "low":
        live_level = "high"
        live_score = 15

    hist = _weighted_historical_contribution(runs)

    overall_level = live_level if live_level != "low" else hist["level"]
    overall_score = live_score if live_score > 0 else _LEVEL_REPRESENTATIVE_SCORE.get(overall_level, 2)

    current_objects = _build_current_risk_objects(live_alerts, hist)
    current_matrix = build_risk_matrix(current_objects)

    return {
        "overall_level": overall_level,
        "overall_score": overall_score,
        "live_contribution": {
            "level": live_level,
            "score": live_score,
            "connected": live_connected,
            "threats": live_alerts,
            "active_run_state": live_run_state,
        },
        "historical_contribution": hist,
        "current_matrix": current_matrix,
        "current_risk_objects": current_objects,
        "active_alerts": list(live_alerts),
        "run_summaries": _run_summaries(runs),
        "evidence_quality": _evidence_quality(runs, live_connected),
        "computed_at": time.time(),
    }
