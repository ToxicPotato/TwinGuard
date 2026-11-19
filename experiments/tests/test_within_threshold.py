#!/usr/bin/env python3
"""
Tests for the outside-threshold adversarial trial pipeline.

Verifies that:
  - outside_threshold_trials.yaml loads and validates without error
  - micro_spoof is NOT used in this pipeline
  - near_threshold, dropout, pulse are NOT used in this pipeline
  - all generated velocity_spoof attacks use the "constant" strategy
  - generated velocity_spoof speeds use the configured per-target ranges
  - all generated velocity_spoof trials have deviation_mps > VELOCITY_SPOOF_THRESHOLD_MPS
  - all generated velocity_spoof trials have within_threshold == False
  - false_brake trials can be generated
  - false_brake trials carry threshold_applicability == "not_velocity_threshold_based"
  - false_brake trials carry expected_detectability == "control_attack_not_velocity_threshold"
  - no_attack trials are generated as negative controls

No live backend required.

Run from the repo root:
  python -m pytest experiments/tests/test_within_threshold.py -v
or:
  python experiments/tests/test_within_threshold.py
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_randomized_trials import load_config  # noqa: E402
from attack_generator import generate_attack_strategy, build_attack_request_from_strategy  # noqa: E402
from run_within_threshold_trials import (  # noqa: E402
    _DEFAULT_WITHIN_THRESHOLD_CONFIG,
    _existing_trial_count,
    _gen_cfg_for_trial,
    _validate_within_threshold_config,
)

# Mirrors VELOCITY_SPOOF_THRESHOLD_MPS from
# visualization/python/twins/scenario/checks/velocity_spoof.py line 9
VELOCITY_SPOOF_THRESHOLD_MPS = 0.05

# Speed bounds implied by the YAML
_SPEED_MIN = 0.80        # Fridjof default (leader = Bjarte ~1.0 m/s)
_SPEED_MAX = 0.90
_TORLEIF_SPEED_MIN = 0.40  # Torleif override (leader = Fridjof ~0.80-0.95 m/s)
_TORLEIF_SPEED_MAX = 0.60
_REFERENCE_SPEED = 1.0

_YAML_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "outside_threshold_trials.yaml"
_RANDOMIZED_YAML_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "randomized_trials.yaml"

# Large enough to expose off-by-one errors; small enough to run instantly.
_SAMPLE_N = 300


def _load_gen_cfg() -> dict:
    cfg = load_config(_YAML_PATH)
    return cfg["attack_generator"]


def _sample_strategies(n: int, seed: int = 0) -> list[dict]:
    gen_cfg = _load_gen_cfg()
    rng = random.Random(seed)
    return [generate_attack_strategy(rng, gen_cfg) for _ in range(n)]


# ── Config loading ────────────────────────────────────────────────────────────

class TestYamlLoads(unittest.TestCase):

    def test_file_exists(self):
        self.assertTrue(_YAML_PATH.exists(), f"YAML not found at {_YAML_PATH}")

    def test_load_config_succeeds(self):
        cfg = load_config(_YAML_PATH)
        self.assertIsInstance(cfg, dict)

    def test_experiment_id(self):
        cfg = load_config(_YAML_PATH)
        self.assertEqual(cfg["experiment_id"], "outside_threshold_trials")

    def test_has_attack_generator_section(self):
        cfg = load_config(_YAML_PATH)
        self.assertIn("attack_generator", cfg)

    def test_own_runner_defaults_to_outside_threshold_yaml(self):
        self.assertEqual(_DEFAULT_WITHIN_THRESHOLD_CONFIG, _YAML_PATH)

    def test_own_runner_accepts_outside_threshold_yaml(self):
        cfg = load_config(_YAML_PATH)
        _validate_within_threshold_config(cfg)

    def test_own_runner_rejects_micro_spoof(self):
        cfg = load_config(_YAML_PATH)
        cfg["attack_generator"]["velocity_spoof"]["strategy_probabilities"] = {
            "constant": 0.5,
            "micro_spoof": 0.5,
        }
        with self.assertRaises(ValueError):
            _validate_within_threshold_config(cfg)

    def test_family_sequence_includes_all_simple_families(self):
        cfg = load_config(_YAML_PATH)
        sequence = cfg["attack_generator"]["family_sequence"]
        self.assertEqual(set(sequence), {"velocity_spoof", "false_brake", "no_attack"})

    def test_runner_cycles_families_by_trial_number(self):
        gen_cfg = load_config(_YAML_PATH)["attack_generator"]
        expected = ["velocity_spoof", "false_brake", "velocity_spoof", "false_brake", "no_attack"]
        actual = [
            next(iter(_gen_cfg_for_trial(gen_cfg, idx)["family_probabilities"]))
            for idx in range(1, 6)
        ]
        self.assertEqual(actual, expected)


class TestLifecycleMatchesRandomized(unittest.TestCase):
    """The threshold pipeline mostly keeps the lifecycle while tightening timing."""

    @classmethod
    def setUpClass(cls):
        cls.within_cfg = load_config(_YAML_PATH)
        cls.randomized_cfg = load_config(_RANDOMIZED_YAML_PATH)

    def test_top_level_lifecycle_fields_match_randomized(self):
        keys = [
            "backend_url",
            # warmup_s deliberately differs: the case study uses a longer clean period.
            "recovery_s",
            "pre_run_settle_s",
            "baseline_stability_timeout_s",
            "baseline_stability_window_s",
            "formation_thresholds",
            "clean_baseline",
        ]
        for key in keys:
            self.assertEqual(
                self.within_cfg.get(key),
                self.randomized_cfg.get(key),
                f"outside_threshold_trials.yaml must match randomized_trials.yaml for {key}",
            )

    def test_platoon_gate_is_stricter_than_randomized(self):
        gate = self.within_cfg["platoon_state_gate"]
        self.assertEqual(gate["allowed_target_states"], [3])
        self.assertTrue(gate["recheck_before_attack"])

    def test_attack_timing_has_zero_delay_for_sanity_pipeline(self):
        within_timing = self.within_cfg["attack_generator"].get("timing")
        self.assertEqual(within_timing["delay_s"], {"min": 0, "max": 0})
        self.assertEqual(within_timing["duration_s"], {"min": 2, "max": 8})

    def test_targets_are_focused_for_sanity_pipeline(self):
        within_targets = self.within_cfg["attack_generator"].get("target_robots")
        self.assertEqual(within_targets, ["Fridjof", "Torleif"])


# ── Generator config structure ────────────────────────────────────────────────

class TestGeneratorConfigStructure(unittest.TestCase):

    def setUp(self):
        self.gen_cfg = _load_gen_cfg()

    def test_velocity_spoof_family_present(self):
        self.assertIn("velocity_spoof", self.gen_cfg["family_probabilities"])

    def test_false_brake_family_present(self):
        self.assertIn("false_brake", self.gen_cfg["family_probabilities"])

    def test_no_micro_spoof_in_strategy_probabilities(self):
        sprobs = self.gen_cfg["velocity_spoof"]["strategy_probabilities"]
        self.assertNotIn("micro_spoof", sprobs)

    def test_no_near_threshold_in_strategy_probabilities(self):
        sprobs = self.gen_cfg["velocity_spoof"]["strategy_probabilities"]
        self.assertNotIn("near_threshold", sprobs)

    def test_no_dropout_in_strategy_probabilities(self):
        sprobs = self.gen_cfg["velocity_spoof"]["strategy_probabilities"]
        self.assertNotIn("dropout", sprobs)

    def test_no_pulse_in_strategy_probabilities(self):
        sprobs = self.gen_cfg["velocity_spoof"]["strategy_probabilities"]
        self.assertNotIn("pulse", sprobs)

    def test_only_constant_strategy(self):
        sprobs = self.gen_cfg["velocity_spoof"]["strategy_probabilities"]
        self.assertEqual(set(sprobs.keys()), {"constant"})

    def test_constant_probability_is_one(self):
        sprobs = self.gen_cfg["velocity_spoof"]["strategy_probabilities"]
        self.assertAlmostEqual(float(sprobs["constant"]), 1.0)

    def test_speed_min_at_least_0_80(self):
        speed = self.gen_cfg["velocity_spoof"]["speed_mps"]
        self.assertGreaterEqual(float(speed["min"]), _SPEED_MIN)

    def test_speed_max_at_most_0_90(self):
        speed = self.gen_cfg["velocity_spoof"]["speed_mps"]
        self.assertLessEqual(float(speed["max"]), _SPEED_MAX)

    def test_torleif_speed_override_configured(self):
        by_target = self.gen_cfg["velocity_spoof"].get("speed_mps_by_target")
        self.assertIsNotNone(by_target, "speed_mps_by_target missing from velocity_spoof config")
        self.assertIn("Torleif", by_target)
        torleif_range = by_target["Torleif"]
        self.assertGreaterEqual(float(torleif_range["min"]), _TORLEIF_SPEED_MIN)
        self.assertLessEqual(float(torleif_range["max"]), _TORLEIF_SPEED_MAX)

    def test_threshold_context_configured(self):
        vs_cfg = self.gen_cfg["velocity_spoof"]
        self.assertIn("threshold_context", vs_cfg)

    def test_threshold_context_threshold_mps(self):
        ctx = self.gen_cfg["velocity_spoof"]["threshold_context"]
        self.assertAlmostEqual(float(ctx["threshold_mps"]), VELOCITY_SPOOF_THRESHOLD_MPS)

    def test_threshold_context_reference_speed(self):
        ctx = self.gen_cfg["velocity_spoof"]["threshold_context"]
        self.assertAlmostEqual(float(ctx["reference_speed_mps"]), _REFERENCE_SPEED)

    def test_false_brake_has_threshold_applicability(self):
        fb_cfg = self.gen_cfg["false_brake"]
        self.assertEqual(fb_cfg.get("threshold_applicability"), "not_velocity_threshold_based")

    def test_false_brake_has_expected_detectability(self):
        fb_cfg = self.gen_cfg["false_brake"]
        self.assertEqual(
            fb_cfg.get("expected_detectability"), "control_attack_not_velocity_threshold"
        )

    def test_target_robots_configured(self):
        targets = self.gen_cfg.get("target_robots")
        self.assertIsInstance(targets, list)
        self.assertGreater(len(targets), 0)


# ── Generated strategy invariants ────────────────────────────────────────────

class TestGeneratedStrategyInvariants(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.strategies = _sample_strategies(_SAMPLE_N, seed=42)
        cls.vs_strategies = [
            s for s in cls.strategies if s["attack_family"] == "velocity_spoof"
        ]
        cls.fb_strategies = [
            s for s in cls.strategies if s["attack_family"] == "false_brake"
        ]
        cls.no_attack_strategies = [
            s for s in cls.strategies if s["attack_family"] == "no_attack"
        ]

    # ── exclusion: forbidden strategies never sampled ────────────────────────

    def test_no_micro_spoof_generated(self):
        strats = {s["strategy"] for s in self.strategies}
        self.assertNotIn("micro_spoof", strats)

    def test_no_near_threshold_generated(self):
        strats = {s["strategy"] for s in self.strategies}
        self.assertNotIn("near_threshold", strats)

    def test_no_dropout_generated(self):
        strats = {s["strategy"] for s in self.strategies}
        self.assertNotIn("dropout", strats)

    def test_no_pulse_generated(self):
        strats = {s["strategy"] for s in self.strategies}
        self.assertNotIn("pulse", strats)

    # ── velocity_spoof: constant strategy only ───────────────────────────────

    def test_all_vs_strategies_are_constant(self):
        for s in self.vs_strategies:
            self.assertEqual(
                s["strategy"], "constant",
                f"Unexpected velocity_spoof strategy: {s['strategy']!r}",
            )

    # ── velocity_spoof: speed bounds ────────────────────────────────────────

    def test_all_vs_speed_mps_in_range(self):
        for s in self.vs_strategies:
            spd = s["speed_mps"]
            if s.get("target_robot") == "Torleif":
                self.assertGreaterEqual(spd, _TORLEIF_SPEED_MIN, f"Torleif speed_mps={spd} < {_TORLEIF_SPEED_MIN}")
                self.assertLessEqual(spd, _TORLEIF_SPEED_MAX, f"Torleif speed_mps={spd} > {_TORLEIF_SPEED_MAX}")
            else:
                self.assertGreaterEqual(spd, _SPEED_MIN, f"speed_mps={spd} < {_SPEED_MIN}")
                self.assertLessEqual(spd, _SPEED_MAX, f"speed_mps={spd} > {_SPEED_MAX}")

    def test_fridjof_vs_speed_uses_default_range(self):
        fridjof_vs = [s for s in self.vs_strategies if s.get("target_robot") == "Fridjof"]
        self.assertGreater(len(fridjof_vs), 0, "No Fridjof velocity_spoof trials in sample")
        for s in fridjof_vs:
            self.assertGreaterEqual(s["speed_mps"], _SPEED_MIN)
            self.assertLessEqual(s["speed_mps"], _SPEED_MAX)

    def test_torleif_vs_speed_uses_target_override(self):
        torleif_vs = [s for s in self.vs_strategies if s.get("target_robot") == "Torleif"]
        self.assertGreater(len(torleif_vs), 0, "No Torleif velocity_spoof trials in sample")
        for s in torleif_vs:
            self.assertGreaterEqual(s["speed_mps"], _TORLEIF_SPEED_MIN)
            self.assertLessEqual(s["speed_mps"], _TORLEIF_SPEED_MAX)

    # ── velocity_spoof: threshold metadata ──────────────────────────────────

    def test_all_vs_have_deviation_mps(self):
        for s in self.vs_strategies:
            self.assertIn("deviation_mps", s)

    def test_all_vs_deviation_mps_above_threshold(self):
        for s in self.vs_strategies:
            dev = s["deviation_mps"]
            self.assertGreater(
                dev, VELOCITY_SPOOF_THRESHOLD_MPS,
                f"deviation_mps={dev} <= VELOCITY_SPOOF_THRESHOLD_MPS={VELOCITY_SPOOF_THRESHOLD_MPS}",
            )

    def test_all_vs_deviation_mps_matches_speed(self):
        for s in self.vs_strategies:
            expected_dev = round(abs(_REFERENCE_SPEED - s["speed_mps"]), 4)
            self.assertAlmostEqual(
                s["deviation_mps"], expected_dev, places=4,
                msg=f"deviation_mps mismatch: got {s['deviation_mps']}, expected {expected_dev}",
            )

    def test_all_vs_have_within_threshold_false(self):
        for s in self.vs_strategies:
            self.assertIn("within_threshold", s)
            self.assertFalse(
                s["within_threshold"],
                f"within_threshold is True for speed_mps={s['speed_mps']}",
            )

    def test_all_vs_have_threshold_mps_field(self):
        for s in self.vs_strategies:
            self.assertIn("threshold_mps", s)
            self.assertAlmostEqual(s["threshold_mps"], VELOCITY_SPOOF_THRESHOLD_MPS)

    def test_all_vs_have_threshold_reference_speed(self):
        for s in self.vs_strategies:
            self.assertIn("threshold_reference_speed_mps", s)
            self.assertAlmostEqual(s["threshold_reference_speed_mps"], _REFERENCE_SPEED)

    def test_all_vs_have_expected_detectability(self):
        for s in self.vs_strategies:
            self.assertIn("expected_detectability", s)
            self.assertEqual(s["expected_detectability"], "should_detect")

    # ── false_brake: metadata ────────────────────────────────────────────────

    def test_all_fb_strategy_is_simple_brake(self):
        for s in self.fb_strategies:
            self.assertEqual(s["strategy"], "simple_brake")

    def test_all_fb_have_threshold_applicability(self):
        for s in self.fb_strategies:
            self.assertIn("threshold_applicability", s)
            self.assertEqual(s["threshold_applicability"], "not_velocity_threshold_based")

    def test_all_fb_have_expected_detectability(self):
        for s in self.fb_strategies:
            self.assertIn("expected_detectability", s)
            self.assertEqual(s["expected_detectability"], "control_attack_not_velocity_threshold")

    def test_fb_do_not_have_within_threshold(self):
        for s in self.fb_strategies:
            self.assertNotIn(
                "within_threshold", s,
                "false_brake should not carry within_threshold",
            )

    # ── no_attack: clean negative controls ──────────────────────────────────

    def test_no_attack_do_not_have_within_threshold(self):
        for s in self.no_attack_strategies:
            self.assertNotIn("within_threshold", s)

    def test_no_attack_difficulty_is_none(self):
        for s in self.no_attack_strategies:
            self.assertEqual(s["attack_difficulty"], "none")

    # ── population presence ──────────────────────────────────────────────────

    def test_some_velocity_spoof_trials_present(self):
        # With 300 samples and P(vs)=0.55 the chance of zero is negligible
        self.assertGreater(len(self.vs_strategies), 0)

    def test_some_false_brake_trials_present(self):
        # With 300 samples and P(fb)=0.35 the chance of zero is negligible
        self.assertGreater(len(self.fb_strategies), 0)

    def test_some_no_attack_trials_present(self):
        # With 300 samples and P(no_attack)=0.10 the chance of zero is negligible
        self.assertGreater(len(self.no_attack_strategies), 0)


# ── Determinism with fixed seed ───────────────────────────────────────────────

class TestWithinThresholdDeterminism(unittest.TestCase):

    def test_same_seed_same_strategies(self):
        a = _sample_strategies(20, seed=7)
        b = _sample_strategies(20, seed=7)
        self.assertEqual(a, b)

    def test_different_seeds_differ(self):
        a = _sample_strategies(20, seed=0)
        b = _sample_strategies(20, seed=99)
        self.assertNotEqual(a, b)


# ── Normal pipeline unaffected ────────────────────────────────────────────────

class TestNormalPipelineUnaffected(unittest.TestCase):
    """Verify that the normal randomized_trials.yaml is not broken by generator changes."""

    @classmethod
    def setUpClass(cls):
        normal_yaml = Path(__file__).resolve().parents[1] / "scenarios" / "randomized_trials.yaml"
        cfg = load_config(normal_yaml)
        gen_cfg = cfg["attack_generator"]
        rng = random.Random(1337)
        cls.normal_strategies = [generate_attack_strategy(rng, gen_cfg) for _ in range(100)]

    def test_normal_constant_lacks_threshold_fields(self):
        # Normal pipeline has no threshold_context, so constant trials should
        # not carry within_threshold / threshold_mps / deviation_mps
        constant = [s for s in self.normal_strategies if s.get("strategy") == "constant"]
        for s in constant:
            self.assertNotIn(
                "within_threshold", s,
                "Normal pipeline constant trial should not carry within_threshold",
            )
            self.assertNotIn("threshold_mps", s)
            self.assertNotIn("deviation_mps", s)

    def test_normal_false_brake_lacks_threshold_applicability(self):
        fb = [s for s in self.normal_strategies if s["attack_family"] == "false_brake"]
        for s in fb:
            self.assertNotIn(
                "threshold_applicability", s,
                "Normal pipeline false_brake should not carry threshold_applicability",
            )


# ── Compiled request target_robot uses upstream leader topic for velocity_spoof ─

_LEADER_BY_FOLLOWER = {"Fridjof": "Bjarte", "Torleif": "Fridjof"}


class TestCompiledRequestTarget(unittest.TestCase):
    """Verify that build_attack_request_from_strategy sets target_robot to the
    upstream leader topic target for velocity_spoof attacks.

    The tamper service injects on the target_robot's MQTT topics.  For
    velocity_spoof this is the leader's topic (Bjarte for Fridjof, Fridjof for
    Torleif).  follower_robot is kept separately in the request body so runners
    and logs know which logical robot is under attack.
    """

    def _vs_strategy(self, follower: str, speed: float = 0.85) -> dict:
        return {
            "attack_family": "velocity_spoof",
            "strategy": "constant",
            "target_robot": follower,
            "speed_mps": speed,
            "delay_s": 0.0,
            "duration_s": 5.0,
        }

    def test_fridjof_vs_target_robot_is_bjarte(self):
        _, body = build_attack_request_from_strategy(self._vs_strategy("Fridjof"))
        self.assertEqual(body["target_robot"], "Bjarte")
        self.assertEqual(body["follower_robot"], "Fridjof")

    def test_torleif_vs_target_robot_is_fridjof(self):
        _, body = build_attack_request_from_strategy(self._vs_strategy("Torleif", speed=0.50))
        self.assertEqual(body["target_robot"], "Fridjof")
        self.assertEqual(body["follower_robot"], "Torleif")

    def test_vs_target_robot_differs_from_follower_robot(self):
        for follower, leader in _LEADER_BY_FOLLOWER.items():
            _, body = build_attack_request_from_strategy(self._vs_strategy(follower))
            self.assertEqual(body["follower_robot"], follower)
            self.assertEqual(body["target_robot"], leader,
                             f"velocity_spoof {follower}: expected target_robot={leader!r}")

    def test_false_brake_fridjof_target_robot_is_leader(self):
        strategy = {
            "attack_family": "false_brake",
            "strategy": "simple_brake",
            "target_robot": "Fridjof",
            "delay_s": 0.0,
            "duration_s": 3.0,
        }
        _, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(body["target_robot"], "Bjarte")
        self.assertEqual(body["follower_robot"], "Fridjof")

    def test_explicit_attack_topic_robot_overrides_default(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "constant",
            "target_robot": "Fridjof",
            "attack_topic_robot": "CustomRobot",
            "speed_mps": 0.85,
            "delay_s": 0.0,
            "duration_s": 5.0,
        }
        _, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(body["target_robot"], "CustomRobot")

    def test_vs_compiled_for_all_within_threshold_targets(self):
        gen_cfg = _load_gen_cfg()
        rng = random.Random(0)
        targets = gen_cfg.get("target_robots", [])
        for follower in targets:
            vs_cfg = gen_cfg.get("velocity_spoof", {})
            by_target = vs_cfg.get("speed_mps_by_target", {})
            speed_range = by_target.get(follower, vs_cfg.get("speed_mps", {"min": 0.5, "max": 0.9}))
            speed = rng.uniform(float(speed_range["min"]), float(speed_range["max"]))
            strategy = {
                "attack_family": "velocity_spoof",
                "strategy": "constant",
                "target_robot": follower,
                "speed_mps": speed,
                "delay_s": 0.0,
                "duration_s": 5.0,
            }
            _, body = build_attack_request_from_strategy(strategy)
            expected_leader = _LEADER_BY_FOLLOWER.get(follower, follower)
            self.assertEqual(
                body["target_robot"], expected_leader,
                f"velocity_spoof {follower}: target_robot should be {expected_leader!r}, "
                f"got {body['target_robot']!r}",
            )


class TestAppendExistingTrials(unittest.TestCase):
    """Existing summary rows should make a resumed run continue numbering."""

    def test_missing_summary_starts_at_zero(self):
        self.assertEqual(_existing_trial_count(Path("does-not-exist.csv")), 0)

    def test_existing_summary_returns_highest_trial_number(self):
        path = Path(__file__).resolve().parents[2] / "tmp" / "outside_threshold_resume_test.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "trial_number,detected\n1,True\n4,False\n2,True\n",
            encoding="utf-8",
        )
        try:
            self.assertEqual(_existing_trial_count(path), 4)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
