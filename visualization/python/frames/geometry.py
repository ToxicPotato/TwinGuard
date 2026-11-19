"""Derived geometry shared by frame delivery and display."""

import math

from python.models.frame import Frame, RobotSnapshot


def road_center_state(robot: RobotSnapshot) -> dict | None:
    """Reconstruct road-center state from routed lane signals. Returns None if signals unavailable."""
    if robot.routed.he is None or robot.routed.le is None:
        return None
    road_yaw = robot.estimated.yaw - robot.routed.he
    road_x = robot.estimated.x + robot.routed.le * math.sin(road_yaw)
    road_y = robot.estimated.y - robot.routed.le * math.cos(road_yaw)
    return {"x": round(road_x, 5), "y": round(road_y, 5), "yaw": round(road_yaw, 5)}


def derive_display_geometry(frame: Frame) -> dict:
    """Build display geometry for one frame."""
    road_center = {}
    for rid, robot in frame.robots.items():
        result = road_center_state(robot)
        if result is not None:
            road_center[rid] = result
    return {"road_center": road_center}
