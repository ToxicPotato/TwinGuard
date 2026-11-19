"""
Tests for tamper-service attack override dicts.

Both FalseBrakeAttack and SlowdownAttack must include leader_input.active_state = "1"
in their override dicts so the velocity-spoof detector gate (leader_input_state != 0)
correctly evaluates the injected signal.

Run from the tamper-service directory:
  cd visualization/tamper-service
  python -m pytest tests/test_attack_overrides.py -v
  # or without pytest:
  python tests/test_attack_overrides.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add tamper-service/ to path so ``app.*`` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.attacks.false_brake import FalseBrakeAttack
from app.attacks.slowdown import SlowdownAttack


class TestFalseBrakeOverride(unittest.TestCase):
    """FalseBrakeAttack must activate the leader_input channel in its override."""

    def setUp(self):
        self.settings = Settings()
        self.attack = FalseBrakeAttack(self.settings)

    def test_leader_input_topic_present(self):
        override = self.attack.override_dict()
        self.assertIn("leader_input", override)

    def test_leader_input_v_mps_present(self):
        override = self.attack.override_dict()
        self.assertIn("v_mps", override["leader_input"])

    def test_leader_input_active_state_is_one(self):
        """active_state = '1' activates the channel so the detector gate passes."""
        override = self.attack.override_dict()
        self.assertEqual(override["leader_input"]["active_state"], "1")

    def test_leader_input_v_mps_default_is_zero(self):
        """Default false-brake leader_input_v is '0.0' (leader appears stopped)."""
        override = self.attack.override_dict()
        self.assertEqual(override["leader_input"]["v_mps"], "0.0")

    def test_estimated_velocity_override_present(self):
        override = self.attack.override_dict()
        self.assertIn("estimated/velocity", override)

    def test_routed_signals_active_state_present(self):
        override = self.attack.override_dict()
        self.assertIn("routed_signals", override)
        self.assertIn("active_state", override["routed_signals"])


class TestSlowdownOverrideStatic(unittest.TestCase):
    """SlowdownAttack (static) must inject leader_input with v_mps and active_state."""

    def setUp(self):
        self.attack = SlowdownAttack()
        self.attack.trigger(speed_mps=0.15, duration_s=30.0)

    def test_leader_input_topic_present(self):
        override = self.attack.override_dict()
        self.assertIn("leader_input", override)

    def test_leader_input_v_mps_matches_speed(self):
        override = self.attack.override_dict()
        self.assertAlmostEqual(float(override["leader_input"]["v_mps"]), 0.15, places=3)

    def test_leader_input_active_state_is_one(self):
        override = self.attack.override_dict()
        self.assertEqual(override["leader_input"]["active_state"], "1")

    def test_estimated_velocity_still_overridden(self):
        """estimated/velocity override should still be present for backward compat."""
        override = self.attack.override_dict()
        self.assertIn("estimated/velocity", override)
        self.assertAlmostEqual(float(override["estimated/velocity"]["v_mps"]), 0.15, places=3)

    def test_routed_signals_still_overridden(self):
        override = self.attack.override_dict()
        self.assertIn("routed_signals", override)

    def test_no_overrides_when_not_active(self):
        stopped = SlowdownAttack()
        self.assertEqual(stopped.override_dict(), {})


class TestSlowdownOverrideRamp(unittest.TestCase):
    """SlowdownAttack (ramp) must include leader_input at the ramp's interpolated speed."""

    def setUp(self):
        self.attack = SlowdownAttack()
        self.attack.trigger_ramp(speed_start=0.40, speed_end=0.05, duration_s=20.0)

    def test_leader_input_topic_present(self):
        override = self.attack.override_dict()
        self.assertIn("leader_input", override)

    def test_leader_input_active_state_is_one(self):
        override = self.attack.override_dict()
        self.assertEqual(override["leader_input"]["active_state"], "1")

    def test_leader_input_v_within_ramp_range(self):
        override = self.attack.override_dict()
        v = float(override["leader_input"]["v_mps"])
        self.assertGreaterEqual(v, 0.04, "should be >= speed_end - epsilon during active ramp")
        self.assertLessEqual(v, 0.41, "should be <= speed_start + epsilon during active ramp")

    def test_estimated_velocity_matches_leader_input(self):
        override = self.attack.override_dict()
        self.assertEqual(
            override["leader_input"]["v_mps"],
            override["estimated/velocity"]["v_mps"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
