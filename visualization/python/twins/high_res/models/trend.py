"""Build high-res trend output from aligned history entries."""

import math

from python.models.high_res_inputs import HighResInputs
from python.twins.shared.constants import (
    ROBOT_LENGTH_METERS,
)
from python.twins.shared.models.trend import (
    PlatoonTrendEstimate,
    RobotMotionTrend,
    RobotRelationTrend,
    RobotTrendEstimate,
    TrendEstimateResult,
    build_resolved_platoons,
    gap_rate_mps,
    leader_history,
    leader_change_count,
    motion_label,
    motion_rate_mps2,
    observed_robot_entries,
)
from python.twins.shared.runtime.history import TwinHistoryEntry


class HighResTrendModel:
    """Build high-res trend output from high-res-specific evidence."""

    @staticmethod
    def _pose_speed_samples(
        observed_entries: list[TwinHistoryEntry[HighResInputs]],
        robot_id: str,
    ) -> list[tuple[float, float]]:
        """Return pose-derived speed samples for one high-res robot."""
        speed_samples: list[tuple[float, float]] = []
        previous_entry = None

        for entry in observed_entries:
            robot = entry.inputs.robots.get(robot_id)
            if (
                robot is None
                or robot.x is None
                or robot.y is None
                or previous_entry is None
            ):
                previous_entry = entry
                continue

            previous_robot = previous_entry.inputs.robots.get(robot_id)
            if (
                previous_robot is None
                or previous_robot.x is None
                or previous_robot.y is None
                or entry.t <= previous_entry.t
            ):
                previous_entry = entry
                continue

            distance_meters = math.hypot(
                robot.x - previous_robot.x,
                robot.y - previous_robot.y,
            )
            speed_samples.append(
                (
                    entry.t,
                    round(distance_meters / (entry.t - previous_entry.t), 5),
                )
            )
            previous_entry = entry

        return speed_samples

    @staticmethod
    def _selected_speed_samples(
        observed_entries: list[TwinHistoryEntry[HighResInputs]],
        robot_id: str,
    ) -> list[tuple[float, float]]:
        """Return the best high-res speed series for motion estimation."""
        pose_speed_by_t = dict(
            HighResTrendModel._pose_speed_samples(observed_entries, robot_id)
        )
        selected_samples: list[tuple[float, float]] = []

        for entry in observed_entries:
            robot = entry.inputs.robots.get(robot_id)
            if robot is None:
                continue

            pose_speed = pose_speed_by_t.get(entry.t)
            wheel_speed = None
            if robot.wl is not None and robot.wr is not None:
                wheel_speed = round((robot.wl + robot.wr) / 2.0, 5)

            selected_speed = robot.vv
            if selected_speed is None:
                selected_speed = robot.v
            if selected_speed is None:
                selected_speed = wheel_speed
            if selected_speed is None:
                selected_speed = pose_speed
            if selected_speed is None:
                selected_speed = robot.rv

            if selected_speed is not None and pose_speed is not None:
                if abs(selected_speed - pose_speed) > 1.0:
                    if robot.vv is None and robot.v is None and wheel_speed is None:
                        selected_speed = pose_speed

            if selected_speed is None:
                continue

            selected_samples.append((entry.t, round(selected_speed, 5)))

        return selected_samples

    @staticmethod
    def _pair_gap_meters(
        entry: TwinHistoryEntry[HighResInputs],
        leader_id: str,
        follower_id: str,
    ) -> float | None:
        """Return the high-res bumper gap for one observed pair in one entry."""
        follower = entry.inputs.robots.get(follower_id)
        leader = entry.inputs.robots.get(leader_id)
        if follower is None or leader is None:
            return None
        if follower.dv and follower.d is not None:
            return round(follower.d, 5)
        if None in (leader.x, leader.y, follower.x, follower.y):
            return None
        center_gap = math.hypot(
            (leader.x or 0.0) - (follower.x or 0.0),
            (leader.y or 0.0) - (follower.y or 0.0),
        )
        return round(center_gap - ROBOT_LENGTH_METERS, 5)

    @classmethod
    def _build_motion_trend(
        cls,
        observed_entries: list[TwinHistoryEntry[HighResInputs]],
        robot_id: str,
    ) -> RobotMotionTrend:
        """Build the public high-res motion trend from observed robot history."""
        speed_samples = cls._selected_speed_samples(
            observed_entries,
            robot_id,
        )
        speed_rate_mps2 = motion_rate_mps2(speed_samples)
        return RobotMotionTrend(
            label=motion_label(speed_rate_mps2),
            speed_rate_mps2=speed_rate_mps2,
        )

    @classmethod
    def _build_relation_trend(
        cls,
        observed_entries: list[TwinHistoryEntry[HighResInputs]],
        robot_id: str,
    ) -> RobotRelationTrend:
        """Build the public high-res relation trend from aligned robot history."""
        leader_ids = leader_history(observed_entries, robot_id)
        observed_leader_change_count = leader_change_count(leader_ids)
        frames_assessed = len(observed_entries)
        current_leader_id = None
        if observed_entries:
            current_assessment = observed_entries[-1].frame_assessment.per_robot.get(robot_id)
            if current_assessment is not None:
                current_leader_id = current_assessment.direct_leader_hypothesis_id
        gap_samples = cls._comparable_gap_samples(
            observed_entries,
            robot_id,
            current_leader_id,
        )
        observed_gap_rate_mps = gap_rate_mps(gap_samples)

        return RobotRelationTrend(
            gap_rate_mps=observed_gap_rate_mps,
            gap_sample_count=len(gap_samples),
            leader_change_count=observed_leader_change_count,
            frames_assessed=frames_assessed,
        )

    @classmethod
    def _comparable_gap_samples(
        cls,
        observed_entries: list[TwinHistoryEntry[HighResInputs]],
        robot_id: str,
        current_leader_id: str | None,
    ) -> list[tuple[float, float]]:
        """Return high-res gap samples for the current comparable leader relation."""
        gap_samples: list[tuple[float, float]] = []
        if current_leader_id is None:
            return gap_samples

        for entry in observed_entries:
            robot_assessment = entry.frame_assessment.per_robot.get(robot_id)
            if robot_assessment is None:
                continue

            leader_id = robot_assessment.direct_leader_hypothesis_id
            if leader_id != current_leader_id:
                continue

            gap_meters = cls._pair_gap_meters(entry, leader_id, robot_id)
            if gap_meters is None:
                continue

            gap_samples.append((entry.t, gap_meters))

        return gap_samples

    @classmethod
    def _build_robot_trend(
        cls,
        history_entries: list[TwinHistoryEntry[HighResInputs]],
        robot_id: str,
    ) -> RobotTrendEstimate:
        """Build the full high-res trend summary for one robot."""
        observed_entries = observed_robot_entries(history_entries, robot_id)
        return RobotTrendEstimate(
            motion=cls._build_motion_trend(observed_entries, robot_id),
            relation=cls._build_relation_trend(observed_entries, robot_id),
        )

    @classmethod
    def _build_resolved_platoons(
        cls,
        history_entries: list[TwinHistoryEntry[HighResInputs]],
    ) -> list[PlatoonTrendEstimate]:
        """Build public high-res trend platoons from aligned history entries."""
        return build_resolved_platoons(
            history_entries,
            cls._pair_gap_meters,
        )

    @classmethod
    def evaluate(
        cls,
        history_entries: list[TwinHistoryEntry[HighResInputs]],
    ) -> TrendEstimateResult:
        """Build the shared high-res trend output for the current frame."""
        current_entry = history_entries[-1]
        result = TrendEstimateResult()

        for robot_id in current_entry.inputs.robots:
            if robot_id not in current_entry.frame_assessment.per_robot:
                continue
            result.per_robot[robot_id] = cls._build_robot_trend(history_entries, robot_id)

        result.per_platoon = cls._build_resolved_platoons(history_entries)
        return result
