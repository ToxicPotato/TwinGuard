"""Package frame and twin outputs for replay and UI delivery."""

from dataclasses import asdict

from python.models.frame import Frame, RobotSnapshot
from python.twins.scenario.output import ScenarioOutput


def robot_snapshot_to_dict(robot: RobotSnapshot) -> dict:
    """Serialize a robot snapshot to the flat delivery payload shape."""
    return {
        "x": robot.estimated.x,
        "y": robot.estimated.y,
        "w": robot.estimated.yaw,
        "v": robot.estimated.v,
        "rx": robot.reference.x,
        "ry": robot.reference.y,
        "ryaw": robot.reference.yaw,
        "rv": robot.reference.v,
        "le": robot.routed.le,
        "he": robot.routed.he,
        "rc": robot.routed.rc,
        "vv": robot.routed.vv,
        "st": robot.routed.st,
        "le_raw": robot.sensors.le_raw,
        "he_raw": robot.sensors.he_raw,
        "tk": robot.sensors.tk,
        "d": robot.sensors.d,
        "dv": robot.sensors.dv,
        "lc": robot.sensors.lc,
        "lane_le": robot.sensors.lane_le,
        "lane_he": robot.sensors.lane_he,
        "sc": robot.steering.sc,
        "sd_v": robot.steering.sd_v,
        "wl": robot.wheels.wl,
        "wr": robot.wheels.wr,
        "leader_input_id": robot.leader_input.id,
        "leader_input_v": robot.leader_input.v,
        "leader_input_state": robot.leader_input.state,
    }


def frame_to_dict(frame: Frame) -> dict:
    """Serialize a normalized frame for downstream JSON and UI delivery."""
    robot_map = {rid: robot_snapshot_to_dict(robot) for rid, robot in frame.robots.items()}
    return {"t": round(float(frame.t), 5), "robots": robot_map}


def serialize_scenario_output(output: ScenarioOutput) -> dict:
    """Serialize scenario twin output for JSON delivery."""
    return {
        "per_robot": {
            rid: asdict(labels)
            for rid, labels in output.per_robot.items()
        }
    }


def attach_twin_payload(
    frame: dict,
    low_res: dict,
    high_res: dict,
    display: dict,
    comparison: dict | None = None,
    scenario: dict | None = None,
) -> dict:
    """Attach processed twin outputs to a frame payload in-place."""
    frame["low_res"] = low_res
    frame["high_res"] = high_res
    frame["display"] = display
    if comparison is not None:
        frame["comparison"] = comparison
    if scenario is not None:
        frame["scenario"] = scenario
    return frame
