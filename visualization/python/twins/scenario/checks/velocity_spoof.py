"""Velocity spoof scenario rules."""

from dataclasses import dataclass

from python.models.high_res_inputs import HighResRobotInputs
from python.twins.scenario.output import RobotScenarioLabels

# Minimum mismatch between actual and perceived leader speed before spoof is flagged.
VELOCITY_SPOOF_THRESHOLD_MPS = 0.05

# Small tolerance for treating perceived speed as effectively unchanged or zero.
VELOCITY_SPOOF_EPSILON_MPS = 0.02


@dataclass(slots=True)
class VelocitySpoofSignal:
    """Actual and perceived leader speed for one follower in one frame."""

    actual_v: float
    perceived_v: float

    @property
    def speed_error(self) -> float:
        """Difference between actual and perceived leader speed."""
        return self.actual_v - self.perceived_v


@dataclass(slots=True)
class VelocitySpoofState:
    """Stored velocity-spoof history for one robot."""

    previous_signal: VelocitySpoofSignal | None = None
    previous_perceived_step_sign: int | None = None
    consecutive_perceived_steps: int = 0
    spoof_frames: int = 0


def evaluate_velocity_spoof(robot_id: str, robots: dict[str, HighResRobotInputs], state: VelocitySpoofState) -> tuple[RobotScenarioLabels, VelocitySpoofSignal | None]:
    """Evaluate velocity spoof labels for one robot and return the current signal."""
    signal = _read_signal(robot_id, robots)
    labels = _classify_signal(signal, state)
    return labels, signal


def update_velocity_spoof_state(state: VelocitySpoofState, signal: VelocitySpoofSignal | None, is_spoofed: bool) -> None:
    """Update stored velocity-spoof state after the current frame is classified."""
    if signal is None:
        state.previous_signal = None
        state.previous_perceived_step_sign = None
        state.consecutive_perceived_steps = 0
        state.spoof_frames = 0
        return

    state.previous_perceived_step_sign, state.consecutive_perceived_steps = _measure_trend(state, signal)
    state.previous_signal = signal
    state.spoof_frames = state.spoof_frames + 1 if is_spoofed else 0


def _read_signal(robot_id: str, robots: dict[str, HighResRobotInputs]) -> VelocitySpoofSignal | None:
    """Read the leader-speed values needed to evaluate velocity spoofing."""
    robot = robots[robot_id]
    if robot.leader_input_id is None:
        return None

    # TwinGuard relay topology: follower reads tampered actions/+/estimated/velocity
    # and republishes as vehicle/+/leader_input with v_mps set to the (possibly
    # spoofed) value.  active_state stays 0 because the simulator never sets it.
    # The leader_input_v field is always valid when leader_input_id is set, so
    # gating on active_state would suppress every frame including real attack frames.
    leader = robots.get(robot.leader_input_id)
    if leader is None or leader.v is None or robot.leader_input_v is None:
        return None

    return VelocitySpoofSignal(actual_v=leader.v, perceived_v=robot.leader_input_v)


def _classify_signal(signal: VelocitySpoofSignal | None, state: VelocitySpoofState) -> RobotScenarioLabels:
    """Classify the current velocity-spoof signal."""
    if signal is None or abs(signal.speed_error) <= VELOCITY_SPOOF_THRESHOLD_MPS:
        return RobotScenarioLabels()

    spoof_kind = _frame_kind(signal)
    spoof_kind = _history_kind(signal, spoof_kind, state)
    return RobotScenarioLabels(
        velocity_spoof=True,
        velocity_spoof_kind=spoof_kind,
    )


def _frame_kind(signal: VelocitySpoofSignal) -> str:
    """Classify the current frame without using history."""
    if (
        abs(signal.perceived_v) <= VELOCITY_SPOOF_EPSILON_MPS
        and signal.actual_v > VELOCITY_SPOOF_THRESHOLD_MPS
    ):
        return "zeroed"

    if signal.speed_error > 0:
        return "underreported"

    return "overreported"


def _history_kind(signal: VelocitySpoofSignal, frame_kind: str, state: VelocitySpoofState) -> str:
    """Refine the frame label with stored history."""
    if frame_kind == "zeroed" or state.previous_signal is None:
        return frame_kind

    perceived_step = signal.perceived_v - state.previous_signal.perceived_v
    actual_step = signal.actual_v - state.previous_signal.actual_v
    error_step = signal.speed_error - state.previous_signal.speed_error

    if (
        abs(perceived_step) <= VELOCITY_SPOOF_EPSILON_MPS
        and abs(actual_step) > VELOCITY_SPOOF_THRESHOLD_MPS
    ):
        return "fixed"

    if (
        state.consecutive_perceived_steps >= 2
        and abs(perceived_step) > VELOCITY_SPOOF_EPSILON_MPS
        and abs(error_step) > VELOCITY_SPOOF_EPSILON_MPS
    ):
        return "ramped"

    return frame_kind


def _measure_trend(state: VelocitySpoofState, signal: VelocitySpoofSignal) -> tuple[int | None, int]:
    """Measure how long perceived speed has moved in the same direction."""
    if state.previous_signal is None:
        return None, 0

    perceived_step = signal.perceived_v - state.previous_signal.perceived_v
    if abs(perceived_step) <= VELOCITY_SPOOF_EPSILON_MPS:
        return state.previous_perceived_step_sign, 0

    step_sign = 1 if perceived_step > 0 else -1
    if step_sign == state.previous_perceived_step_sign:
        return step_sign, state.consecutive_perceived_steps + 1

    return step_sign, 1
