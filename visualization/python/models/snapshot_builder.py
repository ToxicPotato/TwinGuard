"""Shared helpers for building canonical robot snapshots."""

from python.models.frame import (
    LeaderInput,
    PoseState,
    RobotSnapshot,
    RoutedSignals,
    SensorSignals,
    SteeringDemand,
    WheelCommands,
)


def build_robot_snapshot(
    *,
    estimated_x=None,
    estimated_y=None,
    estimated_yaw=None,
    estimated_v=None,
    reference_x=None,
    reference_y=None,
    reference_yaw=None,
    reference_v=None,
    routed_le=None,
    routed_he=None,
    routed_rc=None,
    routed_vv=None,
    routed_st=None,
    sensors_le_raw=None,
    sensors_he_raw=None,
    sensors_tk=None,
    sensors_d=None,
    sensors_dv=None,
    sensors_lc=None,
    sensors_lane_le=None,
    sensors_lane_he=None,
    steering_sc=None,
    steering_sd_v=None,
    wheels_wl=None,
    wheels_wr=None,
    leader_input_id=None,
    leader_input_v=None,
    leader_input_state=None,
) -> RobotSnapshot:
    """Build one canonical robot snapshot from explicit grouped values."""
    return RobotSnapshot.from_values(
        estimated=PoseState(
            x=estimated_x,
            y=estimated_y,
            yaw=estimated_yaw,
            v=estimated_v,
        ),
        reference=PoseState(
            x=reference_x,
            y=reference_y,
            yaw=reference_yaw,
            v=reference_v,
        ),
        routed=RoutedSignals(
            le=routed_le,
            he=routed_he,
            rc=routed_rc,
            vv=routed_vv,
            st=routed_st,
        ),
        sensors=SensorSignals(
            le_raw=sensors_le_raw,
            he_raw=sensors_he_raw,
            tk=sensors_tk,
            d=sensors_d,
            dv=sensors_dv,
            lc=sensors_lc,
            lane_le=sensors_lane_le,
            lane_he=sensors_lane_he,
        ),
        steering=SteeringDemand(
            sc=steering_sc,
            sd_v=steering_sd_v,
        ),
        wheels=WheelCommands(
            wl=wheels_wl,
            wr=wheels_wr,
        ),
        leader_input=LeaderInput(
            id=leader_input_id,
            v=leader_input_v,
            state=leader_input_state,
        ),
    )
