"""State machine for attack lifecycles - arm, fire, and cancel."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .config import Settings
from .rules import TamperRules


class AttackController:
    """Manages false-brake and velocity-spoof attack state.

    Each attack type owns its own pending timer and target robot identity.
    Timed attack application is delegated to TamperRules, which routes each
    attack through its own target instead of mutating one shared target.
    """

    def __init__(self, settings: Settings, rules: TamperRules):
        self._settings = settings
        self._rules = rules
        self._fb_pending_cancel = threading.Event()
        self._fb_pending_fires_at: float | None = None
        self._fb_pending_target: str | None = None
        self._vs_pending_cancel = threading.Event()
        self._vs_pending_fires_at: float | None = None
        self._vs_pending_target: str | None = None

    def get_status(self) -> dict:
        status = self._rules.scenario_status()
        if self._fb_pending_fires_at is not None and not status["false_brake_active"]:
            fires_in_s = max(0.0, self._fb_pending_fires_at - time.monotonic())
            if fires_in_s > 0:
                status["false_brake_pending"] = True
                status["false_brake_fires_in_s"] = round(fires_in_s, 1)
                status["false_brake_target_robot_id"] = self._fb_pending_target
            else:
                self._fb_pending_fires_at = None
                self._fb_pending_target = None
        if self._vs_pending_fires_at is not None and not status["slowdown_active"]:
            vs_fires_in_s = max(0.0, self._vs_pending_fires_at - time.monotonic())
            if vs_fires_in_s > 0:
                status["velocity_spoof_pending"] = True
                status["velocity_spoof_fires_in_s"] = round(vs_fires_in_s, 1)
                status["slowdown_target_robot_id"] = self._vs_pending_target
            else:
                self._vs_pending_fires_at = None
                self._vs_pending_target = None
        return status

    def trigger_false_brake(self, duration_s: float, target_robot: str | None, delay_s: float) -> None:
        if duration_s <= 0:
            raise ValueError("False-brake duration must be > 0 seconds")

        new_target = self._resolve_target(target_robot)
        self._fb_pending_cancel.set()
        self._fb_pending_cancel = threading.Event()
        self._fb_pending_target = new_target

        if delay_s == 0:
            self._fb_pending_fires_at = None
            self._fb_pending_target = None
            self._rules.trigger_false_brake(duration_s, new_target)
            return

        self._fb_pending_fires_at = time.monotonic() + delay_s
        threading.Thread(
            target=self._run_delayed_false_brake,
            args=(self._fb_pending_cancel, duration_s, new_target, delay_s),
            daemon=True,
        ).start()

    def trigger_velocity_spoof(
        self,
        mode: str,
        duration_s: float,
        target_robot: str | None,
        delay_s: float,
        speed_mps: float | None = None,
        speed_start: float | None = None,
        speed_end: float | None = None,
    ) -> None:
        if duration_s <= 0:
            raise ValueError("Velocity-spoof duration must be > 0 seconds")

        new_target = self._resolve_target(target_robot)
        self._vs_pending_cancel.set()
        self._vs_pending_cancel = threading.Event()
        self._vs_pending_target = new_target

        def fire() -> None:
            if mode == "ramp":
                self._rules.trigger_slowdown_ramp(speed_start, speed_end, duration_s, new_target)
            else:
                self._rules.trigger_slowdown(speed_mps or 0.0, duration_s, new_target)

        if delay_s == 0:
            self._vs_pending_fires_at = None
            self._vs_pending_target = None
            fire()
            return

        self._vs_pending_fires_at = time.monotonic() + delay_s
        threading.Thread(
            target=self._run_delayed_velocity_spoof,
            args=(self._vs_pending_cancel, fire, delay_s),
            daemon=True,
        ).start()

    def reset(self) -> None:
        self.stop_false_brake()
        self.stop_velocity_spoof()

    def stop_false_brake(self) -> None:
        self._fb_pending_cancel.set()
        self._fb_pending_fires_at = None
        self._fb_pending_target = None
        self._rules.stop_false_brake()

    def stop_velocity_spoof(self) -> None:
        self._vs_pending_cancel.set()
        self._vs_pending_fires_at = None
        self._vs_pending_target = None
        self._rules.stop_slowdown()

    def _run_delayed_false_brake(
        self,
        cancel_event: threading.Event,
        duration_s: float,
        new_target: str | None,
        delay_s: float,
    ) -> None:
        if cancel_event.wait(timeout=delay_s):
            return
        if cancel_event.is_set():
            return
        self._fb_pending_fires_at = None
        self._fb_pending_target = None
        self._rules.trigger_false_brake(duration_s, new_target)

    def _run_delayed_velocity_spoof(
        self,
        cancel_event: threading.Event,
        fire_fn: Callable[[], None],
        delay_s: float,
    ) -> None:
        if cancel_event.wait(timeout=delay_s):
            return
        if cancel_event.is_set():
            return
        self._vs_pending_fires_at = None
        self._vs_pending_target = None
        fire_fn()

    def _resolve_target(self, target_robot: str | None) -> str | None:
        if target_robot is None:
            return self._settings.target_robot_id
        return target_robot or None
