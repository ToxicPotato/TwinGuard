"""Run the scenario twin for one frame."""

from python.models.high_res_inputs import HighResInputs
from python.twins.scenario.output import RobotScenarioLabels, ScenarioOutput
from python.twins.scenario.state import ScenarioState
from python.twins.scenario.checks.velocity_spoof import (
    evaluate_velocity_spoof,
    update_velocity_spoof_state,
)


class ScenarioTwin:
    """Evaluate explicit scenario labels for one input frame."""

    def __init__(self) -> None:
        self._state = ScenarioState()

    def evaluate(self, inputs: HighResInputs) -> ScenarioOutput:
        """Classify each robot and attach simple scenario labels."""
        per_robot: dict[str, RobotScenarioLabels] = {}

        for robot_id in inputs.robots:
            state = self._state.get_velocity_spoof_state(robot_id)
            labels, signal = evaluate_velocity_spoof(robot_id, inputs.robots, state)
            per_robot[robot_id] = labels
            update_velocity_spoof_state(state, signal, labels.velocity_spoof)

        return ScenarioOutput(per_robot=per_robot)

    def reset(self) -> None:
        """Reset any history before processing a new run."""
        self._state.reset()
