"""Build normalized frames from exported simulation sheets."""

from python.ingestion.file_loader import _bool_value, _float_value, _int_value, _string_value
from python.models.frame import Frame, RobotSnapshot
from python.models.snapshot_builder import build_robot_snapshot


def _robot_snapshot(row, prefix: str) -> RobotSnapshot:
    """Build one robot snapshot from a DataFrame row and column prefix."""
    return build_robot_snapshot(
        estimated_x=_float_value(row, prefix + "vehicle_state.estimated.pose.x_m"),
        estimated_y=_float_value(row, prefix + "vehicle_state.estimated.pose.y_m"),
        estimated_yaw=_float_value(row, prefix + "vehicle_state.estimated.pose.yaw_rad"),
        estimated_v=_float_value(row, prefix + "vehicle_state.estimated.velocity.v_mps"),
        reference_x=_float_value(row, prefix + "vehicle_state.reference.pose.x_m"),
        reference_y=_float_value(row, prefix + "vehicle_state.reference.pose.y_m"),
        reference_yaw=_float_value(row, prefix + "vehicle_state.reference.pose.yaw_rad"),
        reference_v=_float_value(row, prefix + "vehicle_state.reference.velocity.v_mps"),
        routed_le=_float_value(row, prefix + "routed_signals.lateral_error"),
        routed_he=_float_value(row, prefix + "routed_signals.heading_error"),
        routed_rc=_float_value(row, prefix + "routed_signals.curvature"),
        routed_vv=_float_value(row, prefix + "routed_signals.v_mps"),
        routed_st=_int_value(row, prefix + "routed_signals.active_state"),
        sensors_le_raw=_float_value(row, prefix + "sensor_bus.leader_state.lateral_error_raw"),
        sensors_he_raw=_float_value(row, prefix + "sensor_bus.leader_state.heading_error_raw"),
        sensors_tk=_bool_value(row, prefix + "sensor_bus.leader_state.tracking_valid"),
        sensors_d=_float_value(row, prefix + "sensor_bus.distance_state.measured_distance"),
        sensors_dv=_bool_value(row, prefix + "sensor_bus.distance_state.tracking_valid"),
        sensors_lc=_float_value(row, prefix + "sensor_bus.lane_state.curvature"),
        sensors_lane_le=_float_value(row, prefix + "sensor_bus.lane_state.lateral_error"),
        sensors_lane_he=_float_value(row, prefix + "sensor_bus.lane_state.heading_error"),
        steering_sc=_float_value(row, prefix + "steering_demand.curvature_cmd"),
        steering_sd_v=_float_value(row, prefix + "steering_demand.v_mps"),
        wheels_wl=_float_value(row, prefix + "diff_drive_commands.left_wheel_speed"),
        wheels_wr=_float_value(row, prefix + "diff_drive_commands.right_wheel_speed"),
        leader_input_id=_string_value(row, prefix + "leader_input.id"),
        leader_input_v=_float_value(row, prefix + "leader_input.v_mps"),
        leader_input_state=_int_value(row, prefix + "leader_input.active_state"),
    )


def extract_frames(df, robots: list[str]) -> list[Frame]:
    """Build normalized frames from a simulation DataFrame."""
    frames: list[Frame] = []

    for _, row in df.iterrows():
        robot_snapshots = {
            rid: _robot_snapshot(row, rid + ".")
            for rid in robots
        }
        frames.append(Frame.from_snapshots(row["time"], robot_snapshots))

    return frames
