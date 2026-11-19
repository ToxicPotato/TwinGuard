"""Tamper rules — composes attacks and routes per-message transform decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .attacks.false_brake import FalseBrakeAttack
from .attacks.slowdown import SlowdownAttack
from .config import Settings


@dataclass(slots=True)
class RobotState:
    frozen_values: dict[str, str] = field(default_factory=dict)


_FREEZE_SUFFIXES = frozenset({
    "estimated/pose",
})


class TamperRules:
    """Composes active attacks and applies them to incoming MQTT payloads."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._state_by_robot: dict[str, RobotState] = {}
        self.false_brake = FalseBrakeAttack(settings, on_expire=self._state_by_robot.clear)
        self.slowdown = SlowdownAttack(on_expire=self._state_by_robot.clear)
        self._false_brake_target_robot_id: str | None = None
        self._slowdown_target_robot_id: str | None = None

    # ── False-brake lifecycle ──────────────────────────────────────────────────

    def trigger_false_brake(self, duration_s: float, target_robot: str | None = None) -> None:
        self._state_by_robot.clear()
        self._false_brake_target_robot_id = target_robot
        self.false_brake.trigger(duration_s)

    def stop_false_brake(self) -> None:
        self._state_by_robot.clear()
        self._false_brake_target_robot_id = None
        self.false_brake.stop()

    def false_brake_active(self) -> bool:
        active = self.false_brake.is_active()
        if not active:
            self._false_brake_target_robot_id = None
        return active

    # ── Slowdown lifecycle ─────────────────────────────────────────────────────

    def trigger_slowdown(
        self,
        speed_mps: float,
        duration_s: float,
        target_robot: str | None = None,
    ) -> None:
        self._state_by_robot.clear()
        self._slowdown_target_robot_id = target_robot
        self.slowdown.trigger(speed_mps, duration_s)

    def trigger_slowdown_ramp(
        self,
        speed_start: float,
        speed_end: float,
        duration_s: float,
        target_robot: str | None = None,
    ) -> None:
        self._state_by_robot.clear()
        self._slowdown_target_robot_id = target_robot
        self.slowdown.trigger_ramp(speed_start, speed_end, duration_s)

    def stop_slowdown(self) -> None:
        self._state_by_robot.clear()
        self._slowdown_target_robot_id = None
        self.slowdown.stop()

    def slowdown_active(self) -> bool:
        active = self.slowdown.is_active()
        if not active:
            self._slowdown_target_robot_id = None
        return active

    # ── Status ─────────────────────────────────────────────────────────────────

    def scenario_status(self) -> dict[str, object]:
        false_brake_active = self.false_brake_active()
        slowdown_active = self.slowdown_active()
        return {
            "false_brake_active": false_brake_active,
            "false_brake_remaining_s": self.false_brake.remaining_s(),
            "false_brake_target_robot_id": self._false_brake_target_robot_id if false_brake_active else None,
            "slowdown_active": slowdown_active,
            "slowdown_remaining_s": self.slowdown.remaining_s(),
            "slowdown_speed_mps": self.slowdown.speed_mps,
            "slowdown_mode": self.slowdown.mode,
            "slowdown_speed_start": self.slowdown.speed_start,
            "slowdown_speed_end": self.slowdown.speed_end,
            "slowdown_target_robot_id": self._slowdown_target_robot_id if slowdown_active else None,
            "mode": self._settings.mode,
            "target_robot_id": self._settings.target_robot_id,
        }

    # ── Transform routing ──────────────────────────────────────────────────────

    def transform(self, robot_id: str, suffix: str, payload: str) -> str:
        if not self._settings.enabled:
            return payload

        base_target_match = self._target_matches(robot_id, self._settings.target_robot_id)
        env_false_brake_active = self._settings.mode == "false_brake"
        timed_false_brake_active = self.false_brake_active()
        sd_active = self.slowdown_active()

        if self._settings.mode == "passthrough" and not timed_false_brake_active and not sd_active:
            return payload

        state = self._state_by_robot.setdefault(robot_id, RobotState())

        # Freeze mode: capture the first seen JSON blob per suffix and replay it.
        if self._settings.mode == "freeze" and base_target_match and suffix in _FREEZE_SUFFIXES:
            if suffix not in state.frozen_values:
                state.frozen_values[suffix] = payload
            return state.frozen_values[suffix]

        # Build override map: base env layer first, then timed attacks on top.
        # Priority (highest wins): slowdown > false_brake > base env overrides.
        # Each entry is topic_suffix → {json_field: value_string}.
        # Base env overrides apply to every robot that passes the base target filter
        # regardless of whether a timed attack is concurrently running on a different
        # robot — gating on timed-attack state would incorrectly silence global env
        # overrides for untargeted robots while a targeted timed attack is in flight.
        overrides: dict[str, dict[str, str]] = {}

        def _merge(src: dict[str, dict[str, str | None]]) -> None:
            for topic, fields in src.items():
                filtered = {f: v for f, v in fields.items() if v is not None}
                if filtered:
                    overrides.setdefault(topic, {}).update(filtered)

        if base_target_match:
            _merge(self._base_overrides())
        if env_false_brake_active and base_target_match:
            _merge(self.false_brake.override_dict())
        if timed_false_brake_active and self._target_matches(robot_id, self._false_brake_target_robot_id):
            _merge(self.false_brake.override_dict())
        if sd_active and self._target_matches(robot_id, self._slowdown_target_robot_id):
            _merge(self.slowdown.override_dict())

        topic_overrides = overrides.get(suffix)
        if topic_overrides:
            try:
                obj = json.loads(payload)
                obj.update(topic_overrides)
                return json.dumps(obj, separators=(",", ":"))
            except (ValueError, TypeError, AttributeError):
                pass  # non-JSON payload — fall through and return as-is

        # freeze_estimated_pose: same capture logic but as a flag, not a mode.
        if self._settings.freeze_estimated_pose and base_target_match and suffix in _FREEZE_SUFFIXES:
            if suffix not in state.frozen_values:
                state.frozen_values[suffix] = payload
            return state.frozen_values[suffix]

        return payload

    @staticmethod
    def _target_matches(robot_id: str, target_robot_id: str | None) -> bool:
        return target_robot_id is None or robot_id == target_robot_id

    def _base_overrides(self) -> dict[str, dict[str, str | None]]:
        """Static env-configured overrides applied as the base layer for non-passthrough modes."""
        return {
            "estimated/velocity": {"v_mps": self._settings.estimated_v},
            "routed_signals": {
                "v_mps": self._settings.routed_v,
                "active_state": self._settings.routed_state,
            },
            "sensor_data/distance_state": {
                "measured_distance": self._settings.distance_m,
                "tracking_valid": self._settings.distance_valid,
            },
            "leader_input": {"v_mps": self._settings.leader_input_v},
        }
