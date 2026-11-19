"""Compute the high-res frame-assessment result."""

import math

from python.models.high_res_inputs import HighResInputs, HighResRobotInputs
from python.twins.shared.constants import ROBOT_LENGTH_METERS
from python.twins.shared.models.frame_assessment import (
    FrameAssessment,
    FrameGapObservation,
    RobotFrameAssessment,
    build_platoon_assessment,
)


class HighResFrameAssessmentModel:
    """Compute high-res frame-local assessment from sensors and signals."""

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
    def _leader_map_hypothesis(robots: dict[str, HighResRobotInputs]) -> dict[str, str | None]:
        """Infer one leader map hypothesis from the current high-res frame."""
        leader_map_hypothesis: dict[str, str | None] = {}
        for robot_id, robot in robots.items():
            input_leader_id = robot.leader_input_id or None
            if input_leader_id is None or input_leader_id not in robots:
                leader_map_hypothesis[robot_id] = None
                continue
            if not (robot.dv or robot.tk or robot.st in (2, 3, 4)):
                leader_map_hypothesis[robot_id] = None
                continue
            leader_map_hypothesis[robot_id] = input_leader_id
        return leader_map_hypothesis

    @staticmethod
    def _component_evidence(order: list[str], robots: dict[str, HighResRobotInputs]) -> tuple[str, list[str]]:
        """Summarize how well one visible high-res chain is supported."""
        if not order:
            return "unknown", []

        front_robot = robots[order[0]]
        front_input_leader_id = front_robot.leader_input_id or None
        upstream_off_frame = (
            front_input_leader_id is not None and front_input_leader_id not in robots
        )

        conflict_robot_ids: list[str] = []
        supported_pairs = 0
        weak_pairs = 0

        for index in range(len(order) - 1):
            leader = robots[order[index]]
            follower = robots[order[index + 1]]

            has_tracking = bool(follower.dv) or bool(follower.tk)
            if has_tracking:
                supported_pairs += 1
            else:
                weak_pairs += 1

            if (
                follower.dv
                and follower.d is not None
                and None not in (leader.x, leader.y, follower.x, follower.y)
            ):
                center_gap = math.hypot(
                    (leader.x or 0.0) - (follower.x or 0.0),
                    (leader.y or 0.0) - (follower.y or 0.0),
                )
                expected_bumper_gap = center_gap - ROBOT_LENGTH_METERS
                if abs(follower.d - expected_bumper_gap) > max(1.0, center_gap * 0.35):
                    conflict_robot_ids.extend([order[index], order[index + 1]])

        if conflict_robot_ids:
            return "conflicted", list(dict.fromkeys(conflict_robot_ids))
        if upstream_off_frame or weak_pairs > 0:
            return "partial", []
        if supported_pairs > 0:
            return "aligned", []
        return "unknown", []

    @staticmethod
    def _robot_assessment(
        rid: str,
        robots: dict[str, HighResRobotInputs],
        leader_map_hypothesis: dict[str, str | None],
    ) -> RobotFrameAssessment:
        """Build one high-res robot assessment from the current frame."""
        robot = robots[rid]
        direct_leader_hypothesis_id = leader_map_hypothesis.get(rid)

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

        # High-res tracking is based on current-frame sensor visibility only.
        if robot.st == 3:
            leader_tracking_status = (
                "observed" if (bool(robot.dv) or bool(robot.tk)) else "not_observed"
            )
        else:
            leader_tracking_status = "unknown"
        leader = (
            robots.get(direct_leader_hypothesis_id)
            if direct_leader_hypothesis_id is not None
            else None
        )
        # High-res uses the direct range sensor when it is available.
        bumper_gap = round(robot.d, 5) if robot.dv and robot.d is not None else None
        center_gap = None
        if leader is not None:
            center_gap = round(
                math.hypot(
                    (leader.x or 0.0) - (robot.x or 0.0),
                    (leader.y or 0.0) - (robot.y or 0.0),
                ),
                5,
            )
        gap = FrameGapObservation(
            bumper_gap_meters=bumper_gap,
            source="distance_sensor" if bumper_gap is not None else "",
        )

        return RobotFrameAssessment(
            state=robot.st,
            direct_leader_hypothesis_id=direct_leader_hypothesis_id,
            front_leader_hypothesis_id=front_leader_hypothesis_id,
            chain_termination_reason=chain_termination_reason,
            role_hypothesis=role_hypothesis,
            leader_tracking_status=leader_tracking_status,
            gap=gap,
        )


    @classmethod
    def evaluate(cls, inputs: HighResInputs) -> FrameAssessment:
        """Compute the shared frame-assessment result for the high-res twin."""
        robots = inputs.robots
        per_robot: dict[str, RobotFrameAssessment] = {}
        # This map stores immediate leader relations, not component front leaders.
        leader_map_hypothesis = cls._leader_map_hypothesis(robots)
        # Components are the primary current-frame structure model.

        platoon_assessment = build_platoon_assessment(
            leader_map_hypothesis,
            lambda order: cls._component_evidence(order, robots),
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
