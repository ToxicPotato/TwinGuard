"""Subscribe to live MQTT topics and build canonical live frames."""

import json
import logging
import threading
import time
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

from python.models.frame import (
    Frame,
    RobotSnapshot,
)
from python.models.snapshot_builder import build_robot_snapshot

log = logging.getLogger(__name__)

# Each entry maps a topic suffix to a list of (json_key, group, field) tuples.
# One MQTT message carries a JSON object; each json_key extracts one canonical field.
_TOPIC_MAP: dict[str, list[tuple[str, str, str]]] = {
    "estimated/pose": [
        ("x_m", "estimated", "x"),
        ("y_m", "estimated", "y"),
        ("yaw_rad", "estimated", "yaw"),
    ],
    "estimated/velocity": [("v_mps", "estimated", "v")],
    "reference/pose": [
        ("x_m", "reference", "x"),
        ("y_m", "reference", "y"),
        ("yaw_rad", "reference", "yaw"),
    ],
    "reference/velocity": [("v_mps", "reference", "v")],
    "routed_signals": [
        ("lateral_error", "routed", "le"),
        ("heading_error", "routed", "he"),
        ("curvature", "routed", "rc"),
        ("v_mps", "routed", "vv"),
        ("active_state", "routed", "st"),
    ],
    "diff_drive_commands": [
        ("left_wheel_speed", "wheels", "wl"),
        ("right_wheel_speed", "wheels", "wr"),
    ],
    "steering_demand": [
        ("curvature_cmd", "steering", "sc"),
        ("v_mps", "steering", "sd_v"),
    ],
    "leader_input": [
        ("id", "leader_input", "id"),
        ("v_mps", "leader_input", "v"),
        ("active_state", "leader_input", "state"),
    ],
    "sensor_data/lane_state": [
        ("curvature", "sensors", "lc"),
        ("heading_error", "sensors", "lane_he"),
        ("lateral_error", "sensors", "lane_le"),
    ],
    "sensor_data/leader_state": [
        ("lateral_error_raw", "sensors", "le_raw"),
        ("heading_error_raw", "sensors", "he_raw"),
        ("tracking_valid", "sensors", "tk"),
    ],
    "sensor_data/distance_state": [
        ("measured_distance", "sensors", "d"),
        ("tracking_valid", "sensors", "dv"),
    ],
}

_BOOL_FIELDS = {("sensors", "tk"), ("sensors", "dv")}
_INT_FIELDS = {("routed", "st"), ("leader_input", "state")}
_STR_FIELDS = {("leader_input", "id")}
_REQUIRED_FIELDS = {
    ("estimated", "x"),
    ("estimated", "y"),
    ("estimated", "yaw"),
    ("estimated", "v"),
    ("routed", "st"),
}


def _parse_value(key: tuple[str, str], raw):
    """Cast one JSON-decoded value to the canonical Python type.

    ``raw`` is already a Python object (bool/int/float/str) produced by
    ``json.loads`` — we just enforce the expected type for each field.
    """
    if key in _STR_FIELDS:
        return str(raw)
    if key in _BOOL_FIELDS:
        return bool(raw)
    if key in _INT_FIELDS:
        return int(raw)
    return float(raw)




@dataclass(slots=True)
class RobotBufferState:
    """Latest known MQTT-backed state for one robot."""

    fields: dict[tuple[str, str], object] = field(default_factory=dict)
    last_seen_monotonic: float = 0.0


def _robot_is_ready(fields: dict[tuple[str, str], object]) -> bool:
    """Return ``True`` when the minimum fields needed by the twins exist."""
    for required_field in _REQUIRED_FIELDS:
        if required_field not in fields:
            return False
    return True


def _assemble_snapshot(fields: dict[tuple[str, str], object]) -> RobotSnapshot:
    """Build one canonical robot snapshot from buffered live fields."""
    return build_robot_snapshot(
        estimated_x=fields.get(("estimated", "x")),
        estimated_y=fields.get(("estimated", "y")),
        estimated_yaw=fields.get(("estimated", "yaw")),
        estimated_v=fields.get(("estimated", "v")),
        reference_x=fields.get(("reference", "x")),
        reference_y=fields.get(("reference", "y")),
        reference_yaw=fields.get(("reference", "yaw")),
        reference_v=fields.get(("reference", "v")),
        routed_le=fields.get(("routed", "le")),
        routed_he=fields.get(("routed", "he")),
        routed_rc=fields.get(("routed", "rc")),
        routed_vv=fields.get(("routed", "vv")),
        routed_st=fields.get(("routed", "st")),
        sensors_le_raw=fields.get(("sensors", "le_raw")),
        sensors_he_raw=fields.get(("sensors", "he_raw")),
        sensors_tk=fields.get(("sensors", "tk")),
        sensors_d=fields.get(("sensors", "d")),
        sensors_dv=fields.get(("sensors", "dv")),
        sensors_lc=fields.get(("sensors", "lc")),
        sensors_lane_le=fields.get(("sensors", "lane_le")),
        sensors_lane_he=fields.get(("sensors", "lane_he")),
        steering_sc=fields.get(("steering", "sc")),
        steering_sd_v=fields.get(("steering", "sd_v")),
        wheels_wl=fields.get(("wheels", "wl")),
        wheels_wr=fields.get(("wheels", "wr")),
        leader_input_id=fields.get(("leader_input", "id")),
        leader_input_v=fields.get(("leader_input", "v")),
        leader_input_state=fields.get(("leader_input", "state")),
    )


class MqttFrameSource:
    """Subscribe to MQTT and build canonical live frames from buffered state."""

    STALE_TIMEOUT_S = 3.0

    def __init__(self, host: str, port: int = 1883, username: str | None = None, password: str | None = None, topic: str = "vehicle/+/#"):
        self._host = host
        self._port = port
        self._topic = topic
        # Topic format is "{static_prefix}/+/#" — the + is the robot-id wildcard.
        # Drop the last two segments ("+" and "#") to get the purely static prefix.
        # "vehicle/+/#"        → ["vehicle"]          (depth 1, robot_id at index 1)
        # "site-a/vehicle/+/#" → ["site-a", "vehicle"] (depth 2, robot_id at index 2)
        self._topic_prefix: list[str] = topic.split("/")[:-2]
        self._topic_prefix_depth: int = len(self._topic_prefix)
        self._lock = threading.Lock()
        self._robots: dict[str, RobotBufferState] = {}
        self._client = mqtt.Client()
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        log.info("MQTT connected (rc=%s), subscribing to %s", rc, self._topic)
        client.subscribe(self._topic)

    def _parse_topic(self, topic: str) -> tuple[str, list[tuple[str, str, str]]] | None:
        """Parse a topic into ``(robot_id, [(json_key, group, field), ...])``.

        Expected incoming format: ``{static_prefix}/{robot_id}/{signal_path}``.
        The static prefix is matched literally; the segment at depth is the
        robot id; everything after is the signal suffix looked up in _TOPIC_MAP.
        """
        parts = topic.split("/")
        depth = self._topic_prefix_depth
        # Need: all static prefix segments + robot_id + at least one signal segment
        if len(parts) < depth + 2:
            return None
        if parts[:depth] != self._topic_prefix:
            return None
        robot_id = parts[depth]
        suffix = "/".join(parts[depth + 1:])
        mappings = _TOPIC_MAP.get(suffix)
        if mappings is None:
            return None
        return robot_id, mappings

    def _on_message(self, client, userdata, msg):
        result = self._parse_topic(msg.topic)
        if result is None:
            log.debug("Unmapped topic: %s", msg.topic)
            return

        robot_id, mappings = result
        try:
            obj = json.loads(msg.payload.decode())
        except (ValueError, UnicodeDecodeError):
            log.debug("Invalid JSON on %s", msg.topic)
            return

        now = time.monotonic()
        with self._lock:
            state = self._robots.setdefault(robot_id, RobotBufferState())
            for json_key, group, field_name in mappings:
                raw = obj.get(json_key)
                if raw is None:
                    continue
                key = (group, field_name)
                try:
                    state.fields[key] = _parse_value(key, raw)
                except (ValueError, TypeError):
                    pass
            state.last_seen_monotonic = now

    def start(self) -> None:
        """Connect and start the MQTT client loop."""
        self._client.connect(self._host, self._port)
        self._client.loop_start()

    def stop(self) -> None:
        """Stop the MQTT client loop and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()

    def known_robots(self) -> list[str]:
        """Return robot ids seen so far."""
        with self._lock:
            return list(self._robots.keys())

    def build_frame(self, t: float | None = None) -> Frame | None:
        """Build one live frame from the current non-stale buffered robot state."""
        now = time.monotonic()
        with self._lock:
            snapshots: dict[str, RobotSnapshot] = {}

            for robot_id, state in self._robots.items():
                if not _robot_is_ready(state.fields):
                    continue
                if (now - state.last_seen_monotonic) >= self.STALE_TIMEOUT_S:
                    continue
                snapshots[robot_id] = _assemble_snapshot(state.fields)

            if not snapshots:
                return None

        return Frame.from_snapshots(t if t is not None else now, snapshots)
