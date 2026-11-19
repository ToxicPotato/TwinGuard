"""
Tests for velocity-spoof detection under TwinGuard's relay topology.

TwinGuard relay chain: tamper injects on actions/Bjarte/estimated/velocity;
Fridjof's controller reads this and republishes vehicle/Fridjof/leader_input
with the (possibly spoofed) v_mps.  active_state stays 0 because the
simulator never sets it.

Consequence: gating on active_state would suppress every frame including
real attack frames, so the gate has been removed.  The detector now relies
on the speed discrepancy between leader.v (read from vehicle/Bjarte) and
robot.leader_input_v (read from vehicle/Fridjof/leader_input).  At baseline
both are 1.0 so speed_error = 0 — no false positives.

Run:
  cd visualization
  python -m pytest python/tests/test_velocity_spoof_gate.py -v
  # or without pytest:
  python python/tests/test_velocity_spoof_gate.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Add visualization/ to the path so ``python.*`` packages resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python.models.high_res_inputs import HighResRobotInputs
from python.twins.scenario.checks.velocity_spoof import (
    VelocitySpoofState,
    evaluate_velocity_spoof,
    _read_signal,
)


def _make_robots(
    *,
    leader_v: float = 1.0,
    follower_leader_input_v: float = 0.0,
    follower_leader_input_state: int | None = None,
    follower_v: float = 1.0,
) -> dict[str, HighResRobotInputs]:
    return {
        "Bjarte": HighResRobotInputs(v=leader_v),
        "Fridjof": HighResRobotInputs(
            v=follower_v,
            leader_input_id="Bjarte",
            leader_input_v=follower_leader_input_v,
            leader_input_state=follower_leader_input_state,
        ),
    }


class TestLeaderInputStateGate(unittest.TestCase):
    """_read_signal behaviour: gated only by leader_input_id and None fields."""

    def test_baseline_relay_no_spoof_signal_state_none(self):
        # TwinGuard baseline: relay chain active, speeds match, active_state unpublished.
        # Signal is read (gate removed) but speed_error = 0 so no detection.
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=1.0, follower_leader_input_state=None)
        signal = _read_signal("Fridjof", robots)
        self.assertIsNotNone(signal, "relay topology — signal is always read when leader_input_id is set")
        self.assertAlmostEqual(signal.speed_error, 0.0, msg="baseline: no discrepancy")

    def test_baseline_relay_no_spoof_signal_state_zero(self):
        # Same as above with explicit active_state = 0.
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=1.0, follower_leader_input_state=0)
        signal = _read_signal("Fridjof", robots)
        self.assertIsNotNone(signal)
        self.assertAlmostEqual(signal.speed_error, 0.0)

    def test_attack_signal_read_with_state_zero(self):
        # TwinGuard attack: tampered leader_input_v, active_state still 0 (simulation gap).
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.8384, follower_leader_input_state=0)
        signal = _read_signal("Fridjof", robots)
        self.assertIsNotNone(signal, "attack signal must not be suppressed")
        self.assertAlmostEqual(signal.actual_v, 1.0)
        self.assertAlmostEqual(signal.perceived_v, 0.8384)
        self.assertAlmostEqual(signal.speed_error, 0.1616, places=4)

    def test_state_active_allows_evaluation(self):
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.0, follower_leader_input_state=1)
        signal = _read_signal("Fridjof", robots)
        self.assertIsNotNone(signal, "state=1 should allow evaluation")
        self.assertAlmostEqual(signal.actual_v, 1.0)
        self.assertAlmostEqual(signal.perceived_v, 0.0)

    def test_no_leader_input_id_suppresses_evaluation(self):
        robots = {
            "Bjarte": HighResRobotInputs(v=1.0),
            "Fridjof": HighResRobotInputs(v=1.0, leader_input_id=None),
        }
        signal = _read_signal("Fridjof", robots)
        self.assertIsNone(signal, "no leader_input_id means no V2V channel — skip")


class TestVelocitySpoofDetection(unittest.TestCase):
    """evaluate_velocity_spoof must not fire on inactive leader_input."""

    def _run(self, robots, robot_id="Fridjof"):
        state = VelocitySpoofState()
        labels, _ = evaluate_velocity_spoof(robot_id, robots, state)
        return labels

    def test_clean_baseline_not_spoofed_when_state_none(self):
        """TwinGuard baseline: relay chain active, speeds match, state=None -> not spoofed."""
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=1.0, follower_leader_input_state=None)
        labels = self._run(robots)
        self.assertFalse(labels.velocity_spoof)
        self.assertIsNone(labels.velocity_spoof_kind)

    def test_clean_baseline_not_spoofed_when_state_zero(self):
        """TwinGuard baseline with explicit state=0: speeds match -> not spoofed."""
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=1.0, follower_leader_input_state=0)
        labels = self._run(robots)
        self.assertFalse(labels.velocity_spoof)

    def test_clean_match_not_spoofed_when_active(self):
        """Active channel with perceived_v ≈ leader.v: not spoofed."""
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.97, follower_leader_input_state=1)
        labels = self._run(robots)
        self.assertFalse(labels.velocity_spoof)

    def test_zeroed_spoof_detected_when_active(self):
        """Attack: state=1, leader_input_v=0.0, leader.v=1.0 -> zeroed spoof."""
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.0, follower_leader_input_state=1)
        labels = self._run(robots)
        self.assertTrue(labels.velocity_spoof)
        self.assertEqual(labels.velocity_spoof_kind, "zeroed")

    def test_underreported_spoof_detected_when_active(self):
        """Attack: state=1, leader_input_v=0.15, leader.v=1.0 -> underreported."""
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.15, follower_leader_input_state=1)
        labels = self._run(robots)
        self.assertTrue(labels.velocity_spoof)
        self.assertEqual(labels.velocity_spoof_kind, "underreported")

    def test_within_threshold_not_spoofed(self):
        """Tiny drift below THRESHOLD_MPS (0.05): not spoofed even when active."""
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.98, follower_leader_input_state=1)
        labels = self._run(robots)
        self.assertFalse(labels.velocity_spoof)

    def test_twinguard_relay_attack_detected_with_state_zero(self):
        """Core TwinGuard case: tampered leader_input_v, active_state=0 -> detected.

        Mirrors run 8b4b8375 where F.li_v=0.8384 and F.li_state=0 throughout.
        speed_error = 0.1616 > threshold 0.05 -> must detect.
        """
        robots = _make_robots(leader_v=1.0, follower_leader_input_v=0.8384, follower_leader_input_state=0)
        labels = self._run(robots)
        self.assertTrue(labels.velocity_spoof, "relay-topology attack must be detected even with state=0")
        self.assertEqual(labels.velocity_spoof_kind, "underreported")

    def test_no_leader_in_robots_not_spoofed(self):
        """leader_input_id points to a robot not in the dict: not spoofed."""
        robots = {
            "Fridjof": HighResRobotInputs(
                v=1.0,
                leader_input_id="Ghost",
                leader_input_v=0.0,
                leader_input_state=1,
            ),
        }
        labels = self._run(robots)
        self.assertFalse(labels.velocity_spoof)


if __name__ == "__main__":
    unittest.main(verbosity=2)
