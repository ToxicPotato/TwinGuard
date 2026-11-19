"""Environment-backed configuration for the MQTT tamper relay."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _derive_input_prefix() -> str:
    """Return the MQTT input prefix, preferring TAMPER_INPUT_PREFIX, then parsing
    TAMPER_INPUT_TOPIC (full wildcard pattern, e.g. vehicle/+/#), then defaulting."""
    explicit = os.getenv("TAMPER_INPUT_PREFIX", "").strip("/")
    if explicit:
        return explicit
    topic = os.getenv("TAMPER_INPUT_TOPIC", "")
    if topic.endswith("/+/#"):
        derived = topic[: -len("/+/#")].strip("/")
        if derived:
            return derived
    return "vehicle"


@dataclass(slots=True)
class Settings:
    mqtt_host: str = os.getenv("TAMPER_MQTT_HOST", "host.docker.internal")
    mqtt_port: int = _env_int("TAMPER_MQTT_PORT", 1883)
    mqtt_username: str | None = os.getenv("TAMPER_MQTT_USERNAME") or None
    mqtt_password: str | None = os.getenv("TAMPER_MQTT_PASSWORD") or None
    input_prefix: str = _derive_input_prefix()
    output_prefix: str = os.getenv("TAMPER_OUTPUT_PREFIX", "actions").strip("/") or "actions"
    target_robot_id: str | None = os.getenv("TAMPER_TARGET_ROBOT_ID") or None
    mode: str = (os.getenv("TAMPER_MODE", "passthrough") or "passthrough").strip().lower()
    enabled: bool = _env_bool("TAMPER_ENABLED", True)
    freeze_estimated_pose: bool = _env_bool("TAMPER_FREEZE_ESTIMATED_POSE", False)
    # Static env overrides — applied as a base layer for non-passthrough modes.
    # All default to None (no-op). Set these to override a specific field permanently.
    estimated_v: str | None = os.getenv("TAMPER_ESTIMATED_V") or None
    routed_v: str | None = os.getenv("TAMPER_ROUTED_V") or None
    routed_state: str | None = os.getenv("TAMPER_ROUTED_STATE") or None
    distance_m: str | None = os.getenv("TAMPER_DISTANCE_M") or None
    distance_valid: str | None = os.getenv("TAMPER_DISTANCE_VALID") or None
    leader_input_v: str | None = os.getenv("TAMPER_LEADER_INPUT_V") or None
    false_brake_leader_input_v: str = os.getenv("TAMPER_FALSE_BRAKE_LEADER_INPUT_V", "0.0")
    false_brake_estimated_v: str = os.getenv("TAMPER_FALSE_BRAKE_ESTIMATED_V", "0.0")
    false_brake_routed_v: str | None = os.getenv("TAMPER_FALSE_BRAKE_ROUTED_V") or None
    false_brake_steering_v: str | None = os.getenv("TAMPER_FALSE_BRAKE_STEERING_V") or None
    false_brake_active_state: str = os.getenv("TAMPER_FALSE_BRAKE_ACTIVE_STATE", "1")
    control_topic_prefix: str = os.getenv("TAMPER_CONTROL_TOPIC_PREFIX", "tamper/control").strip("/") or "tamper/control"


settings = Settings()
