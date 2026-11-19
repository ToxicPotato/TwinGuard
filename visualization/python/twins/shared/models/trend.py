"""Define the shared public trend output contract and platoon builders."""

from dataclasses import dataclass, field
from typing import Callable, TypeVar

from python.twins.shared.constants import (
    GAP_TREND_STABLE_THRESHOLD_MPS,
    MOTION_ACCEL_THRESHOLD_MPS2,
)
from python.twins.shared.runtime.history import TwinHistoryEntry

TInputs = TypeVar("TInputs")


@dataclass(slots=True)
class RobotMotionTrend:
    """Describe how one robot's own motion evolves over time."""

    # Coarse motion label derived from the observed speed-rate sign and magnitude.
    label: str = "uncertain"
    # Estimated speed-rate in m/s^2 across the active comparable history samples.
    speed_rate_mps2: float | None = None


@dataclass(slots=True)
class RobotRelationTrend:
    """Describe how one robot's leader/platoon relation evolves over time."""

    # Observed bumper-gap rate toward the current assessed direct leader in m/s.
    gap_rate_mps: float | None = None
    # Number of same-leader gap samples that contributed to gap_rate_mps.
    gap_sample_count: int = 0
    # Number of non-null direct-leader changes observed in the active window.
    leader_change_count: int = 0
    # Number of observed entries considered for relation analysis.
    frames_assessed: int = 0


@dataclass(slots=True)
class RobotTrendEstimate:
    """Store the full trend summary for one robot."""

    # Motion trend based on the robot's own speed evolution.
    motion: RobotMotionTrend = field(default_factory=RobotMotionTrend)
    # Relation trend based on leader history and comparable gap evolution.
    relation: RobotRelationTrend = field(default_factory=RobotRelationTrend)


@dataclass(slots=True)
class PlatoonTrendEstimate:
    """Describe how one resolved platoon evolves over time."""

    # Best resolved front-to-tail member order for the persistent platoon.
    resolved_order: list[str] = field(default_factory=list)
    # Coarse structure label for whether the platoon currently appears stable or fragmented.
    structure_trend: str = "uncertain"
    # Continuity label describing whether fragments stayed connected over time.
    continuity_trend: str = "uncertain"
    # Coarse platoon-level gap label derived from the mean pairwise gap-rate.
    gap_trend: str = "uncertain"
    # Mean bumper-gap rate across comparable follower-leader pairs in the resolved order.
    mean_gap_rate_mps: float | None = None
    # Fraction of observed frames where the full resolved platoon was visible at once.
    complete_visibility_ratio: float | None = None


@dataclass(slots=True)
class TrendEstimateResult:
    """Store shared trend output for the current frame."""

    # Per-robot trend payload for robots visible in the current frame.
    per_robot: dict[str, RobotTrendEstimate] = field(default_factory=dict)
    # Resolved platoon trends active in the current frame.
    per_platoon: list[PlatoonTrendEstimate] = field(default_factory=list)


def observed_robot_entries(
    history_entries: list[TwinHistoryEntry[TInputs]],
    robot_id: str,
) -> list[TwinHistoryEntry[TInputs]]:
    """Return history entries where the robot exists in both inputs and assessment."""
    matching_entries = []

    for entry in history_entries:
        if robot_id not in entry.inputs.robots:
            continue
        if robot_id not in entry.frame_assessment.per_robot:
            continue
        matching_entries.append(entry)

    return matching_entries


def motion_label(speed_rate_mps2: float | None) -> str:
    """Map an observed speed-rate to a coarse motion trend label."""
    if speed_rate_mps2 is None:
        return "uncertain"
    if speed_rate_mps2 <= -MOTION_ACCEL_THRESHOLD_MPS2:
        return "decelerating"
    if speed_rate_mps2 >= MOTION_ACCEL_THRESHOLD_MPS2:
        return "accelerating"
    return "steady"


def motion_rate_mps2(speed_samples: list[tuple[float, float]]) -> float | None:
    """Return one observed speed-rate from prepared speed samples."""
    if len(speed_samples) < 2:
        return None

    first_t, first_speed = speed_samples[0]
    last_t, last_speed = speed_samples[-1]
    if last_t <= first_t:
        return None

    return round((last_speed - first_speed) / (last_t - first_t), 5)


def leader_history(
    observed_entries: list[TwinHistoryEntry[TInputs]],
    robot_id: str,
) -> list[str | None]:
    """Return the assessed direct-leader history for one robot."""
    history: list[str | None] = []

    for entry in observed_entries:
        robot_assessment = entry.frame_assessment.per_robot.get(robot_id)
        if robot_assessment is None:
            continue
        history.append(robot_assessment.direct_leader_hypothesis_id)

    return history


def leader_change_count(leader_ids: list[str | None]) -> int:
    """Count non-null leader-id changes across observed history."""
    previous_leader_id: str | None = None
    change_count = 0

    for leader_id in leader_ids:
        if leader_id is None:
            continue
        if previous_leader_id is not None and leader_id != previous_leader_id:
            change_count += 1
        previous_leader_id = leader_id

    return change_count


def gap_rate_mps(gap_samples: list[tuple[float, float]]) -> float | None:
    """Return one observed gap-rate from comparable gap samples."""
    if len(gap_samples) < 2:
        return None

    first_t, first_gap = gap_samples[0]
    last_t, last_gap = gap_samples[-1]
    if last_t <= first_t:
        return None

    return round((last_gap - first_gap) / (last_t - first_t), 5)
def _current_component_orders(current_entry: TwinHistoryEntry[TInputs]) -> list[list[str]]:
    """Return non-empty current component orders from the frame assessment."""
    component_orders: list[list[str]] = []
    for component in current_entry.frame_assessment.platoon.components:
        if not component.order:
            continue
        component_orders.append(component.order)
    return component_orders


def _robot_links(history_entries: list[TwinHistoryEntry[TInputs]]) -> dict[str, set[str]]:
    """Return historical co-membership links between robots."""
    robot_links: dict[str, set[str]] = {}

    for entry in history_entries:
        for component in entry.frame_assessment.platoon.components:
            visible_component_order: list[str] = []
            for robot_id in component.order:
                if robot_id not in entry.frame_assessment.per_robot:
                    continue
                visible_component_order.append(robot_id)

            for robot_id in visible_component_order:
                robot_links.setdefault(robot_id, set()).add(robot_id)

            for robot_id in visible_component_order:
                robot_links[robot_id].update(visible_component_order)

    return robot_links


def _resolved_member_ids(
    current_component_order: list[str],
    assigned_current_robot_ids: set[str],
    robot_links: dict[str, set[str]],
) -> list[str]:
    """Return the resolved members connected to one current fragment."""
    seed_robot_ids: list[str] = []
    for robot_id in current_component_order:
        if robot_id in assigned_current_robot_ids:
            continue
        seed_robot_ids.append(robot_id)

    if not seed_robot_ids:
        return []

    resolved_member_ids: list[str] = []
    pending_robot_ids = list(seed_robot_ids)
    seen_robot_ids: set[str] = set()

    # Expand one current visible fragment through historical co-membership
    # links so we recover the larger persistent platoon it belongs to.
    while pending_robot_ids:
        robot_id = pending_robot_ids.pop()
        if robot_id in seen_robot_ids:
            continue

        seen_robot_ids.add(robot_id)
        resolved_member_ids.append(robot_id)

        for linked_robot_id in robot_links.get(robot_id, set()):
            if linked_robot_id in seen_robot_ids:
                continue
            pending_robot_ids.append(linked_robot_id)

    return resolved_member_ids


def _resolved_order(
    history_entries: list[TwinHistoryEntry[TInputs]],
    member_ids: list[str],
) -> list[str]:
    """Return the strongest recent visible order for one persistent platoon."""
    member_set = set(member_ids)

    for entry in reversed(history_entries):
        flattened_order: list[str] = []
        for component in entry.frame_assessment.platoon.components:
            flattened_order.extend(component.order)

        candidate_order = []
        for robot_id in flattened_order:
            if robot_id not in member_set:
                continue
            candidate_order.append(robot_id)

        if candidate_order:
            # Preserve the strongest recent visible order first, then append
            # currently missing members so the resolved platoon still contains
            # its full membership.
            missing_ids = []
            for robot_id in member_ids:
                if robot_id in candidate_order:
                    continue
                missing_ids.append(robot_id)
            return [*candidate_order, *missing_ids]

    return member_ids


def _complete_visibility_ratio(
    history_entries: list[TwinHistoryEntry[TInputs]],
    member_ids: list[str],
) -> float | None:
    """Return how often the full resolved platoon is visible at once."""
    member_set = set(member_ids)
    observed_frames = 0
    complete_frames = 0

    for entry in history_entries:
        visible_ids = set(entry.inputs.robots)
        if not (visible_ids & member_set):
            continue
        observed_frames += 1
        if member_set <= visible_ids:
            complete_frames += 1

    if observed_frames <= 0:
        return None
    return round(complete_frames / observed_frames, 5)


def _mean_gap_rate_mps(
    history_entries: list[TwinHistoryEntry[TInputs]],
    resolved_order: list[str],
    pair_gap_meters: Callable[[TwinHistoryEntry[TInputs], str, str], float | None],
) -> float | None:
    """Return the mean gap-rate across comparable follower-leader pairs."""
    pair_rates: list[float] = []

    for index in range(1, len(resolved_order)):
        leader_id = resolved_order[index - 1]
        follower_id = resolved_order[index]
        first_gap = None
        first_t = None
        last_gap = None
        last_t = None

        for entry in history_entries:
            gap = pair_gap_meters(entry, leader_id, follower_id)
            if gap is None:
                continue
            if first_gap is None:
                first_gap = gap
                first_t = entry.t
            last_gap = gap
            last_t = entry.t

        if (
            first_gap is None
            or first_t is None
            or last_gap is None
            or last_t is None
            or last_t <= first_t
        ):
            continue

        # Each comparable follower-leader pair contributes one observed
        # gap-rate over the active history window.
        pair_rates.append(round((last_gap - first_gap) / (last_t - first_t), 5))

    if not pair_rates:
        return None
    return round(sum(pair_rates) / len(pair_rates), 5)


def _gap_trend(mean_gap_rate_mps: float | None) -> str:
    """Map a mean gap-rate to a coarse platoon gap trend."""
    if mean_gap_rate_mps is None:
        return "uncertain"
    if mean_gap_rate_mps <= -GAP_TREND_STABLE_THRESHOLD_MPS:
        return "tightening"
    if mean_gap_rate_mps >= GAP_TREND_STABLE_THRESHOLD_MPS:
        return "spreading"
    return "stable"


def build_resolved_platoons(
    history_entries: list[TwinHistoryEntry[TInputs]],
    pair_gap_meters: Callable[[TwinHistoryEntry[TInputs], str, str], float | None],
) -> list[PlatoonTrendEstimate]:
    """Build persistent platoon trends from aligned history entries."""
    current_entry = history_entries[-1]
    current_component_orders = _current_component_orders(current_entry)
    if not current_component_orders:
        return []

    robot_links = _robot_links(history_entries)

    resolved_platoons: list[PlatoonTrendEstimate] = []
    assigned_current_robot_ids: set[str] = set()

    for current_component_order in current_component_orders:
        resolved_member_ids = _resolved_member_ids(
            current_component_order,
            assigned_current_robot_ids,
            robot_links,
        )
        if not resolved_member_ids:
            continue

        # Mark current-frame robots so another visible fragment does not build
        # the same resolved platoon twice.
        for robot_id in resolved_member_ids:
            if robot_id in current_entry.inputs.robots:
                assigned_current_robot_ids.add(robot_id)

        resolved_order = _resolved_order(history_entries, resolved_member_ids)
        visibility_ratio = _complete_visibility_ratio(history_entries, resolved_member_ids)
        mean_gap_rate_mps = _mean_gap_rate_mps(
            history_entries,
            resolved_order,
            pair_gap_meters,
        )

        split_frame_count = 0
        for entry in history_entries:
            overlapping_component_count = 0
            resolved_robot_ids = set(resolved_member_ids)

            for component in entry.frame_assessment.platoon.components:
                component_robot_ids = set(component.order)
                if not (component_robot_ids & resolved_robot_ids):
                    continue
                overlapping_component_count += 1

            if overlapping_component_count > 1:
                split_frame_count += 1

        current_overlap_count = 0
        resolved_robot_ids = set(resolved_member_ids)
        for component_order in current_component_orders:
            current_component_robot_ids = set(component_order)
            if not (current_component_robot_ids & resolved_robot_ids):
                continue
            current_overlap_count += 1

        currently_fragmented = current_overlap_count > 1

        if currently_fragmented:
            structure_trend = "fragmented"
        else:
            structure_trend = "stable"

        if currently_fragmented:
            continuity_trend = (
                "temporarily_fragmented"
                if (visibility_ratio or 0.0) > 0.0
                else "persistently_fragmented"
            )
        elif split_frame_count > 0:
            continuity_trend = "rejoining"
        else:
            continuity_trend = "continuous"

        resolved_platoons.append(
            PlatoonTrendEstimate(
                resolved_order=resolved_order,
                structure_trend=structure_trend,
                continuity_trend=continuity_trend,
                gap_trend=_gap_trend(mean_gap_rate_mps),
                mean_gap_rate_mps=mean_gap_rate_mps,
                complete_visibility_ratio=visibility_ratio,
            )
        )

    return resolved_platoons
