"""Scenario state stored between frames."""

from python.twins.scenario.checks.velocity_spoof import VelocitySpoofState


class ScenarioState:
    """State the scenario twin keeps between frames for all scenario types."""

    def __init__(self) -> None:
        self._velocity_spoof_by_robot: dict[str, VelocitySpoofState] = {}

    def reset(self) -> None:
        """Clear all scenario state before a new run."""
        self._velocity_spoof_by_robot.clear()

    def get_velocity_spoof_state(self, robot_id: str) -> VelocitySpoofState:
        """Return velocity spoof state for one robot."""
        return self._velocity_spoof_by_robot.setdefault(robot_id, VelocitySpoofState())
