"""Define the public twin output model."""

from dataclasses import dataclass, field

from python.twins.shared.models.frame_assessment import (
    FrameAssessment,
    PlatoonFrameAssessment,
    RobotFrameAssessment,
)
from python.twins.shared.models.temporal import RobotTemporalSupport, TemporalSupportByRobot
from python.twins.shared.models.trend import PlatoonTrendEstimate, RobotTrendEstimate, TrendEstimateResult


def _default_robot_trend() -> RobotTrendEstimate:
    """Build an empty robot trend payload."""
    return RobotTrendEstimate()


def _default_robot_assessment() -> RobotFrameAssessment:
    """Build an empty robot assessment payload."""
    return RobotFrameAssessment()


def _default_robot_temporal() -> RobotTemporalSupport:
    """Build an empty temporal support payload for one robot."""
    return RobotTemporalSupport()


@dataclass(slots=True)
class TwinRobotOutput:
    """Store all public output for one robot."""

    assessment: RobotFrameAssessment = field(default_factory=_default_robot_assessment)
    temporal: RobotTemporalSupport = field(default_factory=_default_robot_temporal)
    trend: RobotTrendEstimate = field(default_factory=_default_robot_trend)


@dataclass(slots=True)
class TwinPlatoonOutput:
    """Store platoon-level output shared across robots."""

    assessment: PlatoonFrameAssessment = field(default_factory=PlatoonFrameAssessment)
    trend: list[PlatoonTrendEstimate] = field(default_factory=list)


@dataclass(slots=True)
class TwinOutput:
    """Store the full public output for one twin at one frame."""

    platoon: TwinPlatoonOutput = field(default_factory=TwinPlatoonOutput)
    per_robot: dict[str, TwinRobotOutput] = field(default_factory=dict)

    @classmethod
    def from_parts(
        cls,
        *,
        frame_assessment: FrameAssessment,
        temporal_support: TemporalSupportByRobot,
        trend_result: TrendEstimateResult,
    ) -> "TwinOutput":
        """Build the full public twin output from stage results."""
        robot_ids = (
            set(frame_assessment.per_robot)
            | set(trend_result.per_robot)
            | set(temporal_support.per_robot)
        )
        per_robot = {
            rid: TwinRobotOutput(
                assessment=frame_assessment.per_robot.get(rid, RobotFrameAssessment()),
                temporal=temporal_support.for_robot(rid),
                trend=trend_result.per_robot.get(rid, _default_robot_trend()),
            )
            for rid in robot_ids
        }
        return cls(
            platoon=TwinPlatoonOutput(
                assessment=frame_assessment.platoon,
                trend=trend_result.per_platoon,
            ),
            per_robot=per_robot,
        )
