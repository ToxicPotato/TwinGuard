"""False-brake attack — timer state and field injection definition."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..config import Settings


class FalseBrakeAttack:
    """Timed attack that injects a stopped-leader signal to the follower robot."""

    def __init__(self, settings: Settings, on_expire: Callable[[], None] | None = None):
        self._settings = settings
        self._until: float | None = None
        self._on_expire = on_expire

    def trigger(self, duration_s: float) -> None:
        if duration_s <= 0:
            raise ValueError("False-brake duration must be > 0 seconds")
        self._until = time.monotonic() + duration_s

    def stop(self) -> None:
        self._until = None

    def is_active(self) -> bool:
        if self._until is None:
            return False
        if self._until <= time.monotonic():
            self._until = None
            if self._on_expire:
                self._on_expire()
            return False
        return True

    def remaining_s(self) -> float:
        if not self.is_active():
            return 0.0
        assert self._until is not None
        return round(max(0.0, self._until - time.monotonic()), 3)

    def override_dict(self) -> dict[str, dict[str, str]]:
        """Return all injected field overrides for this attack.

        Keys are topic suffixes; values are dicts of {json_field: value_string}
        to merge into the JSON payload for that topic.
        """
        overrides: dict[str, dict[str, str]] = {
            "leader_input": {
                "v_mps": self._settings.false_brake_leader_input_v,
                # Activate the channel so the velocity-spoof detector gates correctly.
                "active_state": "1",
            },
            "estimated/velocity": {"v_mps": self._settings.false_brake_estimated_v},
            "routed_signals": {"active_state": self._settings.false_brake_active_state},
        }
        if self._settings.false_brake_routed_v is not None:
            overrides.setdefault("routed_signals", {})["v_mps"] = self._settings.false_brake_routed_v
        if self._settings.false_brake_steering_v is not None:
            overrides["steering_demand"] = {"v_mps": self._settings.false_brake_steering_v}
        return overrides

    def override(self, suffix: str) -> dict[str, str] | None:
        """Return the injected field map for a topic suffix, or None to pass through."""
        return self.override_dict().get(suffix)
