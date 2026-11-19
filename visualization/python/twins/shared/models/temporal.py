"""Evaluate per-robot temporal support from frame history."""

from dataclasses import dataclass, field

from python.twins.shared.constants import (
    DEFAULT_HISTORY_WINDOW_SECONDS,
    DEFAULT_MAX_SAMPLE_AGE_SECONDS,
    DEFAULT_MIN_SAMPLES_FOR_TEMPORAL_ESTIMATE,
)
from python.twins.shared.runtime.history import TwinHistoryEntry

HistoryEntry = TwinHistoryEntry[object]

@dataclass(slots=True)
class RobotTemporalSupport:
    """Store temporal support for one robot in the active history window."""
    # Configured size of the history window considered for support evaluation.
    window_seconds: float = round(DEFAULT_HISTORY_WINDOW_SECONDS, 5)
    # Number of visible samples for this robot inside the active history window.
    samples_in_window: int = 0
    # Time span between the oldest and newest visible sample in that window.
    history_span_seconds: float = 0.0
    # Coarse support label derived from sample count, span, and freshness.
    support_quality: str = "insufficient"
    # Time since the previous visible sample; larger means staler support.
    freshness_seconds: float | None = None


@dataclass(slots=True)
class TemporalSupportByRobot:
    """Store temporal support keyed by robot id."""

    # Public temporal support payload indexed by robot id.
    per_robot: dict[str, RobotTemporalSupport] = field(default_factory=dict)

    def for_robot(self, robot_id: str) -> RobotTemporalSupport:
        """Return support for one robot or an insufficient default."""
        support = self.per_robot.get(robot_id)
        return support if support is not None else RobotTemporalSupport()


def _collect_robot_timestamps(history_entries: list[HistoryEntry]) -> dict[str, list[float]]:
    """Collect visible timestamps for each robot in the history window."""
    timestamps_by_robot: dict[str, list[float]] = {}
    for entry in history_entries:
        for robot_id in entry.inputs.robots:
            timestamps_by_robot.setdefault(robot_id, []).append(entry.t)
    return timestamps_by_robot


def _classify_support_quality(samples: int, span_seconds: float, freshness_seconds: float | None) -> str:
    """Classify temporal support quality from sample count and recency."""
    if (
        samples == 1
        or freshness_seconds is None
        or freshness_seconds > DEFAULT_MAX_SAMPLE_AGE_SECONDS
    ):
        return "insufficient"
    if samples >= DEFAULT_MIN_SAMPLES_FOR_TEMPORAL_ESTIMATE and span_seconds > 0.0:
        return "good"
    return "limited"


def _evaluate_robot_support(timestamps: list[float]) -> RobotTemporalSupport:
    """Compute temporal support for one robot from its timestamp history."""
    samples = len(timestamps)
    if samples <= 0:
        return RobotTemporalSupport()

    span = max(timestamps[-1] - timestamps[0], 0.0)
    freshness = None if samples < 2 else max(timestamps[-1] - timestamps[-2], 0.0)

    return RobotTemporalSupport(
        samples_in_window=samples,
        history_span_seconds=round(span, 5),
        support_quality=_classify_support_quality(samples, span, freshness),
        freshness_seconds=None if freshness is None else round(freshness, 5),
    )


def evaluate_temporal_support(history_entries: list[HistoryEntry]) -> TemporalSupportByRobot:
    """Compute per-robot temporal support from the visible frame history."""
    timestamps_by_robot = _collect_robot_timestamps(history_entries)

    per_robot = {}
    for robot_id, timestamps in timestamps_by_robot.items():
        per_robot[robot_id] = _evaluate_robot_support(timestamps)

    return TemporalSupportByRobot(per_robot=per_robot)
