"""High-resolution twin input contracts."""

from dataclasses import dataclass

from python.models.frame import Frame, RobotSnapshot


@dataclass(slots=True)
class HighResRobotInputs:
    """Per-robot input contract for the high-resolution twin."""

    x: float | None = None
    y: float | None = None
    yaw: float | None = None
    v: float | None = None
    st: int | None = None
    leader_input_id: str | None = None
    leader_input_v: float | None = None
    leader_input_state: int | None = None
    d: float | None = None
    dv: bool | None = None
    tk: bool | None = None
    lc: float | None = None
    le: float | None = None
    he: float | None = None
    rc: float | None = None
    vv: float | None = None
    le_raw: float | None = None
    he_raw: float | None = None
    sc: float | None = None
    sd_v: float | None = None
    wl: float | None = None
    wr: float | None = None
    rx: float | None = None
    ry: float | None = None
    ryaw: float | None = None
    rv: float | None = None

    @classmethod
    def from_snapshot(cls, robot: RobotSnapshot) -> "HighResRobotInputs":
        """Build high-resolution robot inputs from a robot snapshot."""
        return cls(
            x=robot.estimated.x,
            y=robot.estimated.y,
            yaw=robot.estimated.yaw,
            v=robot.estimated.v,
            st=robot.routed.st,
            leader_input_id=robot.leader_input.id,
            leader_input_v=robot.leader_input.v,
            leader_input_state=robot.leader_input.state,
            d=robot.sensors.d,
            dv=robot.sensors.dv,
            tk=robot.sensors.tk,
            lc=robot.sensors.lc,
            le=robot.routed.le,
            he=robot.routed.he,
            rc=robot.routed.rc,
            vv=robot.routed.vv,
            le_raw=robot.sensors.le_raw,
            he_raw=robot.sensors.he_raw,
            sc=robot.steering.sc,
            sd_v=robot.steering.sd_v,
            wl=robot.wheels.wl,
            wr=robot.wheels.wr,
            rx=robot.reference.x,
            ry=robot.reference.y,
            ryaw=robot.reference.yaw,
            rv=robot.reference.v,
        )


@dataclass(slots=True)
class HighResInputs:
    """Store frame-level inputs for the high-resolution twin."""

    t: float
    robots: dict[str, HighResRobotInputs]

    @classmethod
    def from_frame(cls, frame: Frame) -> "HighResInputs":
        """Build high-resolution inputs from a normalized frame."""
        return cls(
            t=frame.t,
            robots={
                rid: HighResRobotInputs.from_snapshot(robot)
                for rid, robot in frame.robots.items()
            },
        )
