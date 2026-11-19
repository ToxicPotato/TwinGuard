"""Frame models shared by file and live ingestion."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class PoseState:
    """Store pose and speed state."""

    x: float | None = None
    y: float | None = None
    yaw: float | None = None
    v: float | None = None


@dataclass(slots=True)
class RoutedSignals:
    """Controller-routed signals and active state."""

    le: float | None = None
    he: float | None = None
    rc: float | None = None
    vv: float | None = None
    st: int | None = None


@dataclass(slots=True)
class SensorSignals:
    """Raw sensor-side observations."""

    le_raw: float | None = None
    he_raw: float | None = None
    tk: bool | None = None
    d: float | None = None
    dv: bool | None = None
    lc: float | None = None
    lane_le: float | None = None
    lane_he: float | None = None


@dataclass(slots=True)
class SteeringDemand:
    """Controller output demand values."""

    sc: float | None = None
    sd_v: float | None = None


@dataclass(slots=True)
class WheelCommands:
    """Diff-drive wheel commands."""

    wl: float | None = None
    wr: float | None = None


@dataclass(slots=True)
class LeaderInput:
    """Controller-facing leader input values."""

    id: str | None = None
    v: float | None = None
    state: int | None = None


@dataclass(slots=True)
class RobotSnapshot:
    """Store normalized per-robot replay or live state."""

    estimated: PoseState = field(default_factory=PoseState)
    reference: PoseState = field(default_factory=PoseState)
    routed: RoutedSignals = field(default_factory=RoutedSignals)
    sensors: SensorSignals = field(default_factory=SensorSignals)
    steering: SteeringDemand = field(default_factory=SteeringDemand)
    wheels: WheelCommands = field(default_factory=WheelCommands)
    leader_input: LeaderInput = field(default_factory=LeaderInput)

    @classmethod
    def from_values(
        cls,
        *,
        estimated: PoseState,
        reference: PoseState,
        routed: RoutedSignals,
        sensors: SensorSignals,
        steering: SteeringDemand,
        wheels: WheelCommands,
        leader_input: LeaderInput,
    ) -> "RobotSnapshot":
        """Build a robot snapshot from grouped value objects."""
        return cls(
            estimated=estimated,
            reference=reference,
            routed=routed,
            sensors=sensors,
            steering=steering,
            wheels=wheels,
            leader_input=leader_input,
        )


@dataclass(slots=True)
class Frame:
    """Store a normalized frame before twin enrichment."""

    t: float
    robots: dict[str, RobotSnapshot] = field(default_factory=dict)

    @classmethod
    def from_snapshots(cls, t: float, robots: dict[str, RobotSnapshot]) -> "Frame":
        """Build a frame from per-robot snapshots."""
        return cls(
            t=round(float(t), 5),
            robots=robots,
        )
