"""Define the shared frame-assessment stage output model."""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class FrameGapObservation:
    """Store current-frame gap observations only."""

    # Bumper-to-bumper gap from follower front to leader rear for this frame.
    bumper_gap_meters: float | None = None
    # Evidence origin such as `pose_geometry` or `distance_sensor`.
    source: str = ""


@dataclass(slots=True)
class RobotFrameAssessment:
    """Store the thin current-frame assessment for one robot."""

    # Routed/controller state observed for this robot in the current frame.
    state: int | None = None
    # Immediate leader hypothesis for this robot only, not the front leader of a chain.
    direct_leader_hypothesis_id: str | None = None
    # Front-most visible leader reached by walking the direct-leader chain.
    front_leader_hypothesis_id: str | None = None
    # Why the visible direct-leader chain stopped for this robot in the current frame.
    chain_termination_reason: str = ""
    # Visible platoon component membership for this robot in the current frame.
    component_id: str | None = None
    # Structural role interpretation for this frame, for example follower or front_leader.
    role_hypothesis: str = ""
    # Current-frame leader-tracking evidence status for this robot.
    leader_tracking_status: str = "unknown"
    # Current-frame gap observation toward the hypothesized direct leader.
    gap: FrameGapObservation = field(default_factory=FrameGapObservation)


@dataclass(slots=True)
class PlatoonComponentHypothesis:
    """Store one hypothesized platoon component."""

    # Stable id for one visible platoon component in the current frame.
    component_id: str | None = None
    # Visible robot order from front leader toward the tail in this frame.
    order: list[str] = field(default_factory=list)
    # Structural evidence summary for this visible component.
    structure_evidence_status: str = ""
    # Robots involved in local conflicts for the component evidence check.
    evidence_conflict_robot_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlatoonFrameAssessment:
    """Store the platoon-level frame assessment."""

    # Visible platoon components inferred from the current direct-leader map.
    components: list[PlatoonComponentHypothesis] = field(default_factory=list)
    # Coarse frame-level structure summary across all visible components.
    structure_status: str = ""


@dataclass(slots=True)
class FrameAssessment:
    """Store the shared frame-assessment result for one frame."""

    # Platoon-wide current-frame structure assessment.
    platoon: PlatoonFrameAssessment = field(default_factory=PlatoonFrameAssessment)
    # Per-robot current-frame structure and gap assessment.
    per_robot: dict[str, RobotFrameAssessment] = field(default_factory=dict)


def build_platoon_assessment(leader_map_hypothesis: dict[str, str | None], component_evidence_fn: Callable[[list[str]], tuple[str, list[str]]]) -> PlatoonFrameAssessment:
    """Build the shared platoon assessment from a direct-leader map."""
    components: list[PlatoonComponentHypothesis] = []
    leaders: list[str] = []

    for robot_id, leader_id in leader_map_hypothesis.items():
        if leader_id is None:
            leaders.append(robot_id)

    for component_index, leader in enumerate(leaders):
        order = [leader]
        current_id = leader

        while True:
            next_id = None
            for robot_id, leader_id in leader_map_hypothesis.items():
                if leader_id == current_id and robot_id not in order:
                    next_id = robot_id
                    break
            if next_id is None:
                break

            order.append(next_id)
            current_id = next_id

        structure_evidence_status, evidence_conflict_robot_ids = (
            component_evidence_fn(order)
        )
        components.append(
            PlatoonComponentHypothesis(
                component_id=f"c{component_index}",
                order=order,
                structure_evidence_status=structure_evidence_status,
                evidence_conflict_robot_ids=evidence_conflict_robot_ids,
            )
        )

    structure_status = "empty"
    if len(components) == 1:
        structure_status = "single_component"
    if len(components) > 1:
        structure_status = "multiple_components"

    return PlatoonFrameAssessment(
        components=components,
        structure_status=structure_status
    )
