"""Output contracts for the scenario twin."""

from dataclasses import dataclass, field


@dataclass
class RobotScenarioLabels:
    """Scenario labels for one robot in one frame."""

    velocity_spoof: bool = False
    velocity_spoof_kind: str | None = None


@dataclass
class ScenarioOutput:
    """Scenario twin output for one frame."""

    per_robot: dict[str, RobotScenarioLabels] = field(default_factory=dict)
