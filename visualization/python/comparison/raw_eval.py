"""Raw twin output comparison helpers."""


def _tracking_status_counts(per_robot: dict) -> dict[str, int]:
    """Count current-frame leader-tracking statuses across robots."""
    counts = {
        "observed": 0,
        "not_observed": 0,
        "unknown": 0,
    }
    for payload in per_robot.values():
        status = payload.get("assessment", {}).get("leader_tracking_status")
        if status not in counts:
            continue
        counts[status] += 1
    return counts


def compare_raw_outputs(low_res: dict, high_res: dict) -> dict:
    """Compare raw analytical outputs from the two twins."""
    low_platoon = low_res.get("platoon", {})
    high_platoon = high_res.get("platoon", {})
    low_per_robot = low_res.get("per_robot", {})
    high_per_robot = high_res.get("per_robot", {})

    low_gap_rate = {
        rid: payload.get("trend", {}).get("relation", {}).get("gap_rate_mps")
        for rid, payload in low_per_robot.items()
        if payload.get("trend", {}).get("relation", {}).get("gap_rate_mps") is not None
    }
    high_gap_rate = {
        rid: payload.get("trend", {}).get("relation", {}).get("gap_rate_mps")
        for rid, payload in high_per_robot.items()
        if payload.get("trend", {}).get("relation", {}).get("gap_rate_mps") is not None
    }
    low_good_temporal = sum(
        1 for payload in low_per_robot.values()
        if payload.get("temporal", {}).get("support_quality") == "good"
    )
    high_good_temporal = sum(
        1 for payload in high_per_robot.values()
        if payload.get("temporal", {}).get("support_quality") == "good"
    )
    low_tracking_counts = _tracking_status_counts(low_per_robot)
    high_tracking_counts = _tracking_status_counts(high_per_robot)
    return {
        "low_res_gap_count": len(low_per_robot),
        "high_res_gap_count": len(high_per_robot),
        "low_res_component_count": len(low_platoon.get("assessment", {}).get("components", [])),
        "high_res_component_count": len(high_platoon.get("assessment", {}).get("components", [])),
        "low_res_structure_status": low_platoon.get("assessment", {}).get("structure_status"),
        "high_res_structure_status": high_platoon.get("assessment", {}).get("structure_status"),
        "low_res_platoon_trend_count": len(low_platoon.get("trend", [])),
        "high_res_platoon_trend_count": len(high_platoon.get("trend", [])),
        "high_res_checks": len(high_per_robot),
        "low_res_good_temporal_count": low_good_temporal,
        "high_res_good_temporal_count": high_good_temporal,
        "low_res_gap_rate_count": len(low_gap_rate),
        "high_res_gap_rate_count": len(high_gap_rate),
        "low_res_tracking_observed_count": low_tracking_counts["observed"],
        "low_res_tracking_not_observed_count": low_tracking_counts["not_observed"],
        "low_res_tracking_unknown_count": low_tracking_counts["unknown"],
        "high_res_tracking_observed_count": high_tracking_counts["observed"],
        "high_res_tracking_not_observed_count": high_tracking_counts["not_observed"],
        "high_res_tracking_unknown_count": high_tracking_counts["unknown"],
    }
