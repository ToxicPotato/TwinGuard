"""Velocity-spoof attack — static override or linear ramp between two speeds."""

from __future__ import annotations

import time
from collections.abc import Callable


class SlowdownAttack:
    """Timed attack that forces robot velocity to a fixed or linearly-ramped value.

    Static mode:  overrides all velocity fields with a single constant speed.
    Ramp mode:    linearly interpolates from speed_start to speed_end over the
                  full attack duration.  The interpolated value is re-computed
                  on every call to override_dict() / speed_mps, so followers
                  see a smooth, continuously-changing reading.
    """

    def __init__(self, on_expire: Callable[[], None] | None = None) -> None:
        self._mode: str | None = None        # 'static' | 'ramp'
        self._speed_start: float | None = None
        self._speed_end: float | None = None  # ramp only; None for static
        self._started_at: float | None = None
        self._until: float | None = None
        self._on_expire = on_expire

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def trigger(self, speed_mps: float, duration_s: float) -> None:
        """Static override: hold `speed_mps` for `duration_s` seconds."""
        if duration_s <= 0:
            raise ValueError("Duration must be > 0 seconds")
        if speed_mps < -20:
            raise ValueError("Speed must be >= -20 m/s")
        now = time.monotonic()
        self._mode = "static"
        self._speed_start = speed_mps
        self._speed_end = None
        self._started_at = now
        self._until = now + duration_s

    def trigger_ramp(self, speed_start: float, speed_end: float, duration_s: float) -> None:
        """Ramp override: linearly interpolate from `speed_start` to `speed_end`."""
        if duration_s <= 0:
            raise ValueError("Duration must be > 0 seconds")
        if speed_start < -20 or speed_end < -20:
            raise ValueError("Speeds must be >= -20 m/s")
        now = time.monotonic()
        self._mode = "ramp"
        self._speed_start = speed_start
        self._speed_end = speed_end
        self._started_at = now
        self._until = now + duration_s

    def stop(self) -> None:
        self._mode = None
        self._speed_start = None
        self._speed_end = None
        self._started_at = None
        self._until = None

    # ── State queries ──────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        if self._until is None:
            return False
        if self._until <= time.monotonic():
            self._expire()
            return False
        return True

    def remaining_s(self) -> float:
        if not self.is_active():
            return 0.0
        assert self._until is not None
        return round(max(0.0, self._until - time.monotonic()), 3)

    @property
    def mode(self) -> str | None:
        return self._mode

    @property
    def speed_mps(self) -> float | None:
        """Current injected speed in m/s (for status reporting)."""
        v = self._current_speed()
        return None if v is None else round(v, 4)

    @property
    def speed_start(self) -> float | None:
        return self._speed_start

    @property
    def speed_end(self) -> float | None:
        return self._speed_end

    # ── Override generation ────────────────────────────────────────────────────

    def override_dict(self) -> dict[str, dict[str, str]]:
        """Return all injected field overrides.  Re-computed on every call for ramp mode.

        Keys are topic suffixes; values are dicts of {json_field: value_string}
        to merge into the JSON payload for that topic.
        """
        v = self._current_speed()
        if v is None:
            return {}
        val = str(round(v, 4))
        return {
            # Inject the spoofed perceived-leader velocity so the velocity-spoof
            # detector can compare it against the actual leader speed.  Setting
            # active_state = 1 marks the channel as authoritative; without this
            # the detector gate (leader_input_state != 0) suppresses evaluation.
            "leader_input": {"v_mps": val, "active_state": "1"},
            "estimated/velocity": {"v_mps": val},
            "routed_signals": {"v_mps": val},
            "steering_demand": {"v_mps": val},
        }

    def override(self, suffix: str) -> dict[str, str] | None:
        return self.override_dict().get(suffix)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _current_speed(self) -> float | None:
        """Return the current injected speed, or None if the attack is not active."""
        if not self.is_active():
            return None
        assert self._speed_start is not None
        if self._mode == "ramp" and self._speed_end is not None and self._started_at is not None and self._until is not None:
            duration = self._until - self._started_at
            elapsed = time.monotonic() - self._started_at
            t = max(0.0, min(1.0, elapsed / duration)) if duration > 0 else 1.0
            return self._speed_start + (self._speed_end - self._speed_start) * t
        return self._speed_start

    def _expire(self) -> None:
        self._until = None
        self._mode = None
        self._speed_start = None
        self._speed_end = None
        self._started_at = None
        if self._on_expire:
            self._on_expire()
