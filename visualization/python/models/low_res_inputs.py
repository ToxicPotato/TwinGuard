"""Low-resolution twin input contracts."""

from dataclasses import dataclass

from python.models.frame import Frame, RobotSnapshot


@dataclass(slots=True)
class LowResRobotInputs:
    """Per-robot input contract for the low-resolution twin."""

    x: float | None = None
    y: float | None = None
    yaw: float | None = None
    v: float | None = None
    st: int | None = None
    leader_input_id: str | None = None

    @classmethod
    def from_snapshot(cls, robot: RobotSnapshot) -> "LowResRobotInputs":
        """Build low-resolution robot inputs from a robot snapshot."""
        return cls(
            x=robot.estimated.x,
            y=robot.estimated.y,
            yaw=robot.estimated.yaw,
            v=robot.estimated.v,
            st=robot.routed.st,
            leader_input_id=robot.leader_input.id,
        )


@dataclass(slots=True)
class LowResInputs:
    """Store frame-level inputs for the low-resolution twin."""

    t: float
    robots: dict[str, LowResRobotInputs]

    @classmethod
    def from_frame(cls, frame: Frame) -> "LowResInputs":
        """Build low-resolution inputs from a normalized frame."""
        return cls(
            t=frame.t,
            robots={
                rid: LowResRobotInputs.from_snapshot(robot)
                for rid, robot in frame.robots.items()
            },
        )
