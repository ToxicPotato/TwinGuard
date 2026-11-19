"""Compute the low-res frame-assessment result."""

import math

from python.models.low_res_inputs import LowResInputs, LowResRobotInputs
from python.twins.shared.constants import ROBOT_LENGTH_METERS
from python.twins.shared.models.frame_assessment import (
    FrameAssessment,
    FrameGapObservation,
    RobotFrameAssessment,
    build_platoon_assessment,
)


class LowResFrameAssessmentModel:
    """Compute low-res frame-local assessment from pose geometry."""

    @staticmethod
    def _component_membership(platoon_assessment: FrameAssessment) -> dict[str, str]:
        """Return a map from robot id to visible component id."""
        component_ids_by_robot: dict[str, str] = {}
        for component in platoon_assessment.platoon.components:
            if not component.component_id:
                continue
            for robot_id in component.order:
                component_ids_by_robot[robot_id] = component.component_id
        return component_ids_by_robot

    @staticmethod
    def _leader_map_hypothesis(robots: dict[str, LowResRobotInputs]) -> dict[str, str | None]:
        """Infer one leader map hypothesis from the current low-res frame."""
        leader_map_hypothesis: dict[str, str | None] = {}
        for rid, robot in robots.items():
            input_leader_id = robot.leader_input_id or None
            if input_leader_id is None or input_leader_id not in robots or robot.st not in (2, 3, 4):
                leader_map_hypothesis[rid] = None
                continue
            leader_map_hypothesis[rid] = input_leader_id
        return leader_map_hypothesis


    # Can be moved to shared
    @staticmethod
    def _component_pose_evidence(order: list[str], robots: dict[str, LowResRobotInputs]) -> tuple[str, list[str]]:
        """Summarize whether one visible chain is locally plausible from pose."""
        if not order:
            return "unknown", []

        front_robot = robots[order[0]]
        front_input_leader_id = front_robot.leader_input_id or None
        upstream_off_frame = (
            front_input_leader_id is not None and front_input_leader_id not in robots
        )

        if len(order) < 2:
            return ("partial", []) if upstream_off_frame else ("unknown", [])

        conflict_robot_ids: list[str] = []
        checked_pairs = 0

        for index in range(len(order) - 1):
            leader = robots[order[index]]
            follower = robots[order[index + 1]]
            if None in (
                leader.x,
                leader.y,
                leader.yaw,
                follower.x,
                follower.y,
                follower.yaw,
            ):
                continue

            checked_pairs += 1

            # Check each linked pair in the robots' own local frames rather than
            # assuming one global movement direction for the whole chain.
            follower_to_leader_x = (leader.x or 0.0) - (follower.x or 0.0)
            follower_to_leader_y = (leader.y or 0.0) - (follower.y or 0.0)
            leader_to_follower_x = (follower.x or 0.0) - (leader.x or 0.0)
            leader_to_follower_y = (follower.y or 0.0) - (leader.y or 0.0)

            follower_forward_x = math.cos(follower.yaw or 0.0)
            follower_forward_y = math.sin(follower.yaw or 0.0)
            leader_forward_x = math.cos(leader.yaw or 0.0)
            leader_forward_y = math.sin(leader.yaw or 0.0)

            follower_forward_dot = (
                follower_to_leader_x * follower_forward_x
                + follower_to_leader_y * follower_forward_y
            )
            leader_backward_dot = -(
                leader_to_follower_x * leader_forward_x
                + leader_to_follower_y * leader_forward_y
            )

            if follower_forward_dot <= 0.0 or leader_backward_dot <= 0.0:
                conflict_robot_ids.extend([order[index], order[index + 1]])
                continue

            pair_distance = math.hypot(follower_to_leader_x, follower_to_leader_y)
            if pair_distance <= 1e-9:
                continue

            # Look for a visible robot that appears to sit between this linked pair.
            # Treat these as candidates only: one skipped robot can create a local
            # conflict even when the rest of the chain is correct.
            for other_id in order:
                if other_id in (order[index], order[index + 1]):
                    continue

                other = robots[other_id]
                if None in (other.x, other.y):
                    continue

                follower_to_other_x = (other.x or 0.0) - (follower.x or 0.0)
                follower_to_other_y = (other.y or 0.0) - (follower.y or 0.0)
                projection = (
                    follower_to_other_x * follower_to_leader_x
                    + follower_to_other_y * follower_to_leader_y
                ) / (pair_distance * pair_distance)

                if not 0.2 <= projection <= 0.8:
                    continue

                projected_x = (follower.x or 0.0) + projection * follower_to_leader_x
                projected_y = (follower.y or 0.0) + projection * follower_to_leader_y
                distance_to_segment = math.hypot(
                    (other.x or 0.0) - projected_x,
                    (other.y or 0.0) - projected_y,
                )

                if distance_to_segment <= max(pair_distance * 0.25, 0.5):
                    conflict_robot_ids.extend(
                        [order[index], other_id, order[index + 1]]
                    )

        if conflict_robot_ids:
            return "conflicted", list(dict.fromkeys(conflict_robot_ids))
        if upstream_off_frame:
            return "partial", []
        if checked_pairs:
            return "aligned", []
        return "unknown", []

    @staticmethod
    def _robot_assessment(rid: str, robots: dict[str, LowResRobotInputs], leader_map_hypothesis: dict[str, str | None]) -> RobotFrameAssessment:
        """Build the current-frame assessment for one low-res robot."""
        robot = robots[rid]
        direct_leader_hypothesis_id = leader_map_hypothesis.get(rid)

        # Walk up the visible direct-leader chain to find the resolved front.
        current_front_id = rid
        visited: set[str] = set()
        while current_front_id not in visited:
            visited.add(current_front_id)
            next_leader_id = leader_map_hypothesis.get(current_front_id)
            if next_leader_id is None:
                break
            current_front_id = next_leader_id
        else:
            current_front_id = None

        front_leader_hypothesis_id = current_front_id
        if front_leader_hypothesis_id is None:
            chain_termination_reason = "cycle_detected"
        else:
            front_input_leader_id = (
                robots[front_leader_hypothesis_id].leader_input_id or None
            )
            chain_termination_reason = (
                "visible_front_reached"
                if front_input_leader_id is None
                else "upstream_not_in_frame"
            )

        # Role is a structural interpretation of this frame, not a temporal claim.
        if direct_leader_hypothesis_id is None:
            has_visible_follower = any(
                leader_id == rid for leader_id in leader_map_hypothesis.values()
            )
            if has_visible_follower:
                role_hypothesis = "front_leader"
            else:
                role_hypothesis = "independent"
        else:
            role_hypothesis = "follower"

        # Low-res derives gap from pose because it has no direct range reading.
        if direct_leader_hypothesis_id is None:
            gap = FrameGapObservation(source="pose_geometry")
        else:
            leader = robots[direct_leader_hypothesis_id]
            center_gap = math.hypot(
                (leader.x or 0.0) - (robot.x or 0.0),
                (leader.y or 0.0) - (robot.y or 0.0),
            )
            gap = FrameGapObservation(
                bumper_gap_meters=round(center_gap - ROBOT_LENGTH_METERS, 5),
                source="pose_geometry",
            )

        return RobotFrameAssessment(
            state=robot.st,
            direct_leader_hypothesis_id=direct_leader_hypothesis_id,
            front_leader_hypothesis_id=front_leader_hypothesis_id,
            chain_termination_reason=chain_termination_reason,
            role_hypothesis=role_hypothesis,
            leader_tracking_status="unknown",
            gap=gap,
        )

    @classmethod
    def evaluate(cls, inputs: LowResInputs) -> FrameAssessment:
        """Compute the shared frame-assessment result for the low-res twin."""
        robots = inputs.robots
        per_robot: dict[str, RobotFrameAssessment] = {}
        # This map stores immediate leader relations, not component front leaders.
        leader_map_hypothesis = cls._leader_map_hypothesis(robots)
        # Components are the primary current-frame structure model.

        platoon_assessment = build_platoon_assessment(
            leader_map_hypothesis,
            lambda order: cls._component_pose_evidence(order, robots),
        )
        frame_assessment = FrameAssessment(platoon=platoon_assessment, per_robot={})
        component_ids_by_robot = cls._component_membership(frame_assessment)
        
        for rid in robots:
            assessment = cls._robot_assessment(
                rid,
                robots,
                leader_map_hypothesis,
            )
            assessment.component_id = component_ids_by_robot.get(rid)
            per_robot[rid] = assessment

        return FrameAssessment(platoon=platoon_assessment, per_robot=per_robot)
