#!/usr/bin/env python3
"""
Unit tests for the continuous randomized trial runner and attack generator.

Tests cover:
  - config validation (missing fields, bad probabilities, structural errors)
  - attack strategy generation (family sampling, strategy sampling, bounds)
  - backend request compilation (constant/ramp/near_threshold/dropout/burst)
  - unsupported pulse strategy excluded cleanly (ValueError from compiler)
  - generated_attack_strategy saved into manifest and trial result
  - formation analysis (out_of_formation flag, undetected_physical_impact)
  - trial result building (CSV field presence, no negative TTD)
  - experiment summary aggregation (family/strategy/stealth counts, rates)

No live backend required.

Run from the repo root:
  python -m pytest experiments/tests/test_randomized_trials.py -v
or:
  python experiments/tests/test_randomized_trials.py
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_randomized_trials as randomized_trials  # noqa: E402
from run_randomized_trials import (  # noqa: E402
    TRIAL_CSV_FIELDS,
    _alerts_clean,
    _analyze_formation,
    _build_experiment_summary,
    _build_trial_result,
    _existing_trial_count,
    _handle_gate_failure,
    _latest_frame_from_buffer,
    _risk_snapshot_clean,
    _robot_state_from_frame,
    _target_platoon_state_ok,
    _validate_config,
    _wait_for_target_platoon_state,
    run_trial,
)
from attack_generator import (  # noqa: E402
    build_attack_request_from_strategy,
    generate_attack_strategy,
    validate_attack_generator_config,
)

_TMP_ROOT = Path(__file__).resolve().parents[2] / "tmp" / "trial_tests"


def _tmpdir_path() -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    d = _TMP_ROOT / f"t_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_GEN_CFG = {
    "family_probabilities": {"velocity_spoof": 1.0},
    "velocity_spoof": {
        "strategy_probabilities": {"constant": 1.0},
        "speed_mps": {"min": 0.70, "max": 1.00},
    },
}

MINIMAL_CFG = {
    "experiment_id": "test_exp",
    "backend_url": "http://localhost:8000",
    "attack_generator": MINIMAL_GEN_CFG,
}

FULL_GEN_CFG = {
    "target_robots": ["Fridjof"],
    "family_probabilities": {"velocity_spoof": 0.8, "false_brake": 0.2},
    "timing": {
        "delay_s": {"min": 0, "max": 10},
        "duration_s": {"min": 5, "max": 20},
    },
    "velocity_spoof": {
        "strategy_probabilities": {
            "constant": 0.30,
            "ramp": 0.25,
            "near_threshold": 0.20,
            "pulse": 0.15,
            "dropout": 0.10,
        },
        "speed_mps": {"min": 0.05, "max": 1.05},
        "ramp": {
            "start_mps": {"min": 0.70, "max": 1.05},
            "end_mps": {"min": 0.30, "max": 1.00},
        },
        "near_threshold": {
            "baseline_speed_mps": 1.0,
            "threshold_mps": 0.05,
            "margin_mps": {"min": 0.005, "max": 0.10},
            "direction_probabilities": {"underreport": 0.7, "overreport": 0.3},
        },
        "pulse": {
            "pulse_count": {"min": 2, "max": 8},
            "duty_cycle": {"min": 0.2, "max": 0.8},
            "low_speed_mps": {"min": 0.0, "max": 0.5},
            "high_speed_mps": {"min": 0.8, "max": 1.2},
        },
        "dropout": {"speed_mps": 0.0},
    },
    "false_brake": {
        "duration_s": {"min": 0.5, "max": 15},
    },
}

SAMPLE_ANALYSIS = {
    "run_id": "run-001",
    "frame_count": 600,
    "duration_s": 30.0,
    "risk": "high",
    "risk_score": 70,
    "analysis": {
        "anomaly_frames": 30,
        "anomaly_ratio": 0.05,
        "timeline": [],
        "findings": [],
    },
    "nist_findings": {
        "worst_risk_level": "high",
        "risk_objects": [
            {
                "signal_type": "velocity_spoof",
                "risk_level": "high",
                "risk_score": 10,
                "timestamp_range": [20.0, 28.0],
                "confidence": 0.9,
                "completeness": 0.85,
            }
        ],
        "nist_summary": {
            "total_findings": 1,
            "avg_confidence": 0.9,
            "session_completeness": 0.85,
            "level_counts": {"low": 0, "moderate": 0, "high": 1, "critical": 0},
            "nist_methods": ["velocity_spoof_detector"],
        },
    },
}

SAMPLE_MANIFEST = {
    "experiment_id": "test_exp",
    "campaign_id": "test_exp",
    "trial_id": "trial-0001-abcd1234",
    "trial_number": 1,
    "scenario_id": "velocity_spoof",
    "label": "Trial 1: velocity_spoof / constant / difficulty=medium",
    "run_id": "run-001",
    "seed": 1337,
    "started_at": 1700000000.0,
    "stopped_at": 1700000060.0,
    "attack_type": "velocity_spoof",
    "attack_family": "velocity_spoof",
    "attack_strategy": "constant",
    "attack_difficulty": "medium",
    "target_robot": "Fridjof",
    "generated_attack_strategy": {
        "attack_family": "velocity_spoof",
        "strategy": "constant",
        "target_robot": "Fridjof",
        "speed_mps": 0.85,
        "delay_s": 5.0,
        "duration_s": 12.0,
        "attack_difficulty": "medium",
    },
    "resolved_attack_request": {
        "mode": "static",
        "speed_mps": 0.85,
        "duration_s": 12.0,
        "delay_s": 5.0,
        "target_robot": "Fridjof",
    },
    "expected_attack_start_s": 15.0,
    "expected_attack_end_s": 27.0,
    "warmup_s": 10,
    "recovery_s": 15,
    "errors": [],
    "warnings": [],
    "git_commit": "abc123",
}


# ── Config validation ─────────────────────────────────────────────────────────

class TestValidateConfig(unittest.TestCase):

    def test_minimal_valid_config_passes(self):
        _validate_config(MINIMAL_CFG)

    def test_missing_experiment_id_raises(self):
        cfg = {k: v for k, v in MINIMAL_CFG.items() if k != "experiment_id"}
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_missing_attack_generator_raises(self):
        cfg = {k: v for k, v in MINIMAL_CFG.items() if k != "attack_generator"}
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_attack_generator_missing_family_probabilities_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={})
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_empty_family_probabilities_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={"family_probabilities": {}})
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_zero_family_probability_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={
            "family_probabilities": {"velocity_spoof": 0}
        })
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_negative_family_probability_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={
            "family_probabilities": {"velocity_spoof": -1.0}
        })
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_non_numeric_family_probability_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={
            "family_probabilities": {"velocity_spoof": "high"}
        })
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_velocity_spoof_without_section_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={
            "family_probabilities": {"velocity_spoof": 1.0}
            # no velocity_spoof section
        })
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_velocity_spoof_missing_strategy_probabilities_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={
            "family_probabilities": {"velocity_spoof": 1.0},
            "velocity_spoof": {},
        })
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_negative_strategy_probability_raises(self):
        cfg = dict(MINIMAL_CFG, attack_generator={
            "family_probabilities": {"velocity_spoof": 1.0},
            "velocity_spoof": {
                "strategy_probabilities": {"constant": -0.5},
                "speed_mps": {"min": 0.5, "max": 1.0},
            },
        })
        with self.assertRaises(ValueError):
            _validate_config(cfg)

    def test_full_gen_cfg_passes_validation(self):
        validate_attack_generator_config(FULL_GEN_CFG)

    def test_timing_inverted_bounds_raises(self):
        gen = dict(MINIMAL_GEN_CFG, timing={"delay_s": {"min": 10, "max": 1}})
        with self.assertRaises(ValueError):
            validate_attack_generator_config(gen)


# ── Attack strategy generation ────────────────────────────────────────────────

class TestGenerateAttackStrategy(unittest.TestCase):

    def _rng(self, seed: int = 42) -> random.Random:
        return random.Random(seed)

    def _constant_cfg(self) -> dict:
        return {
            "target_robots": ["Fridjof"],
            "family_probabilities": {"velocity_spoof": 1.0},
            "timing": {"delay_s": {"min": 2, "max": 2}, "duration_s": {"min": 10, "max": 10}},
            "velocity_spoof": {
                "strategy_probabilities": {"constant": 1.0},
                "speed_mps": {"min": 0.8, "max": 0.8},
            },
        }

    def test_constant_strategy_required_fields(self):
        strategy = generate_attack_strategy(self._rng(), self._constant_cfg())
        for field in ("attack_family", "strategy", "target_robot",
                      "delay_s", "duration_s", "speed_mps", "attack_difficulty"):
            self.assertIn(field, strategy, f"Missing field: {field}")

    def test_constant_strategy_values(self):
        strategy = generate_attack_strategy(self._rng(), self._constant_cfg())
        self.assertEqual(strategy["attack_family"], "velocity_spoof")
        self.assertEqual(strategy["strategy"], "constant")
        self.assertAlmostEqual(strategy["speed_mps"], 0.8, places=2)
        self.assertAlmostEqual(strategy["delay_s"], 2.0, places=2)
        self.assertAlmostEqual(strategy["duration_s"], 10.0, places=2)

    def test_ramp_strategy_required_fields(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"ramp": 1.0}))
        strategy = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(strategy["strategy"], "ramp")
        for field in ("speed_start", "speed_end"):
            self.assertIn(field, strategy)

    def test_ramp_speed_within_bounds(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"ramp": 1.0}))
        for seed in range(20):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertGreaterEqual(s["speed_start"], 0.70)
            self.assertLessEqual(s["speed_start"], 1.05)
            self.assertGreaterEqual(s["speed_end"], 0.30)
            self.assertLessEqual(s["speed_end"], 1.00)

    def test_near_threshold_speed_near_boundary(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"near_threshold": 1.0}))
        for seed in range(20):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertEqual(s["strategy"], "near_threshold")
            # speed should be within threshold + max_margin of baseline
            deviation = abs(1.0 - s["speed_mps"])
            self.assertGreaterEqual(deviation, 0.05,
                                    f"Expected deviation >= threshold, got {deviation}")
            self.assertLessEqual(deviation, 0.05 + 0.10 + 0.001,
                                 f"Deviation too large: {deviation}")

    def test_near_threshold_difficulty_always_hard(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"near_threshold": 1.0}))
        for seed in range(10):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertEqual(s["attack_difficulty"], "hard")

    def test_pulse_generated_as_supported_strategy(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"pulse": 1.0}))
        strategy = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(strategy["strategy"], "pulse")
        self.assertIn("pulse_count", strategy)
        self.assertIn("duty_cycle", strategy)
        self.assertIn("low_speed_mps", strategy)
        self.assertIn("high_speed_mps", strategy)
        self.assertNotIn("_unsupported", strategy)

    def test_dropout_speed_zero(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"dropout": 1.0}))
        strategy = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(strategy["strategy"], "dropout")
        self.assertAlmostEqual(strategy["speed_mps"], 0.0, places=4)
        self.assertEqual(strategy["attack_difficulty"], "easy")

    def test_false_brake_strategy(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"false_brake": 1.0})
        strategy = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(strategy["attack_family"], "false_brake")
        self.assertEqual(strategy["strategy"], "burst")
        self.assertIn("duration_s", strategy)
        self.assertIn("attack_difficulty", strategy)

    def test_false_brake_duration_within_bounds(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"false_brake": 1.0})
        for seed in range(20):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertGreaterEqual(s["duration_s"], 0.5)
            self.assertLessEqual(s["duration_s"], 15.0)

    def test_false_brake_difficulty_based_on_duration(self):
        cfg = dict(FULL_GEN_CFG, family_probabilities={"false_brake": 1.0},
                   false_brake={"duration_s": {"min": 1.0, "max": 1.0}})
        s = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(s["attack_difficulty"], "medium")  # duration < 5 s

        cfg_long = dict(FULL_GEN_CFG, family_probabilities={"false_brake": 1.0},
                        false_brake={"duration_s": {"min": 10.0, "max": 10.0}})
        s_long = generate_attack_strategy(self._rng(), cfg_long)
        self.assertEqual(s_long["attack_difficulty"], "easy")  # duration >= 5 s

    def test_deterministic_with_same_seed(self):
        s1 = generate_attack_strategy(random.Random(99), FULL_GEN_CFG)
        s2 = generate_attack_strategy(random.Random(99), FULL_GEN_CFG)
        self.assertEqual(s1["strategy"], s2["strategy"])
        self.assertEqual(s1.get("speed_mps"), s2.get("speed_mps"))

    def test_different_seeds_produce_variation(self):
        strategies = {
            generate_attack_strategy(random.Random(s), FULL_GEN_CFG)["strategy"]
            for s in range(50)
        }
        # With the full distribution there should be more than one strategy used
        self.assertGreater(len(strategies), 1, "Multiple strategies expected across seeds")

    def test_target_robot_within_configured_list(self):
        cfg = dict(FULL_GEN_CFG, target_robots=["Fridjof", "Torleif"])
        for seed in range(20):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertIn(s["target_robot"], ["Fridjof", "Torleif"])

    def test_constant_speed_within_bounds(self):
        cfg = {
            "family_probabilities": {"velocity_spoof": 1.0},
            "timing": {"delay_s": {"min": 0, "max": 10}, "duration_s": {"min": 1, "max": 20}},
            "velocity_spoof": {
                "strategy_probabilities": {"constant": 1.0},
                "speed_mps": {"min": 0.3, "max": 0.7},
            },
        }
        for seed in range(30):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertGreaterEqual(s["speed_mps"], 0.3)
            self.assertLessEqual(s["speed_mps"], 0.7)


# ── Backend request compilation ───────────────────────────────────────────────

class TestBuildAttackRequest(unittest.TestCase):

    def test_constant_compiles_to_static_velocity_spoof(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "constant",
            "target_robot": "Fridjof",
            "speed_mps": 0.85,
            "delay_s": 3.0,
            "duration_s": 10.0,
            "stealth_level": "medium",
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "static")
        self.assertAlmostEqual(body["speed_mps"], 0.85, places=3)
        self.assertAlmostEqual(body["delay_s"], 3.0, places=3)
        self.assertAlmostEqual(body["duration_s"], 10.0, places=3)
        self.assertEqual(body["follower_robot"], "Fridjof")
        self.assertEqual(body["target_robot"], "Bjarte")

    def test_torleif_velocity_spoof_targets_fridjof_topic(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "constant",
            "target_robot": "Torleif",
            "speed_mps": 0.85,
            "delay_s": 0.0,
            "duration_s": 5.0,
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["follower_robot"], "Torleif")
        self.assertEqual(body["target_robot"], "Fridjof")

    def test_near_threshold_compiles_to_static_velocity_spoof(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "near_threshold",
            "target_robot": "Fridjof",
            "speed_mps": 0.94,
            "delay_s": 1.0,
            "duration_s": 5.0,
            "stealth_level": "high",
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "static")
        self.assertAlmostEqual(body["speed_mps"], 0.94, places=3)

    def test_dropout_compiles_to_static_velocity_spoof_zero(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "dropout",
            "target_robot": "Fridjof",
            "speed_mps": 0.0,
            "delay_s": 0.0,
            "duration_s": 8.0,
            "stealth_level": "low",
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "static")
        self.assertAlmostEqual(body["speed_mps"], 0.0, places=3)

    def test_ramp_compiles_to_ramp_velocity_spoof(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "ramp",
            "target_robot": "Fridjof",
            "speed_start": 0.95,
            "speed_end": 0.60,
            "delay_s": 2.0,
            "duration_s": 15.0,
            "stealth_level": "medium",
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "ramp")
        self.assertAlmostEqual(body["speed_start"], 0.95, places=3)
        self.assertAlmostEqual(body["speed_end"], 0.60, places=3)

    def test_false_brake_burst_compiles_correctly(self):
        strategy = {
            "attack_family": "false_brake",
            "strategy": "burst",
            "target_robot": "Fridjof",
            "delay_s": 1.0,
            "duration_s": 6.0,
            "stealth_level": "low",
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "false_brake")
        self.assertAlmostEqual(body["duration_s"], 6.0, places=3)
        self.assertAlmostEqual(body["delay_s"], 1.0, places=3)
        self.assertEqual(body["follower_robot"], "Fridjof")
        self.assertEqual(body["target_robot"], "Bjarte")

    def test_pulse_compiles_to_logical_velocity_spoof_request(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "pulse",
            "target_robot": "Fridjof",
            "delay_s": 0.0,
            "duration_s": 10.0,
            "stealth_level": "medium",
            "pulse_count": 4,
            "duty_cycle": 0.5,
            "low_speed_mps": 0.2,
            "high_speed_mps": 1.3,
        }
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "pulse")
        self.assertEqual(body["pulse_count"], 4)
        self.assertAlmostEqual(body["low_speed_mps"], 0.2)
        self.assertAlmostEqual(body["high_speed_mps"], 1.3)

    def test_generated_pulse_compiles(self):
        """End-to-end: generate pulse strategy -> compile to logical pulse request."""
        cfg = dict(FULL_GEN_CFG, family_probabilities={"velocity_spoof": 1.0},
                   velocity_spoof=dict(FULL_GEN_CFG["velocity_spoof"],
                                       strategy_probabilities={"pulse": 1.0}))
        strategy = generate_attack_strategy(random.Random(42), cfg)
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "pulse")

    def test_no_target_robot_omitted_from_body(self):
        strategy = {
            "attack_family": "velocity_spoof",
            "strategy": "constant",
            "speed_mps": 0.8,
            "delay_s": 0.0,
            "duration_s": 5.0,
        }
        _, body = build_attack_request_from_strategy(strategy)
        self.assertNotIn("target_robot", body)
        self.assertNotIn("follower_robot", body)


# ── Formation analysis ────────────────────────────────────────────────────────

class TestAnalyzeFormation(unittest.TestCase):

    THRESHOLDS = {
        "max_lane_error_m": 0.30,
        "max_spacing_error_m": 0.50,
        "min_violation_duration_s": 2.0,
    }

    def test_none_analysis_returns_no_violation(self):
        f = _analyze_formation(None, self.THRESHOLDS, detected=False)
        self.assertFalse(f["out_of_formation"])
        self.assertFalse(f["undetected_physical_impact"])
        self.assertIsNone(f["max_lane_error"])
        self.assertIsNone(f["max_spacing_error"])

    def test_lane_error_below_threshold_no_violation(self):
        analysis = {"analysis": {"max_lane_error_m": 0.20}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertFalse(f["out_of_formation"])

    def test_lane_error_above_threshold_violation(self):
        analysis = {"analysis": {"max_lane_error_m": 0.35}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertTrue(f["out_of_formation"])

    def test_spacing_error_above_threshold_violation(self):
        analysis = {"analysis": {"max_spacing_error_m": 0.55}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertTrue(f["out_of_formation"])

    def test_undetected_physical_impact_when_oof_and_not_detected(self):
        analysis = {"analysis": {"max_lane_error_m": 0.50}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertTrue(f["out_of_formation"])
        self.assertTrue(f["undetected_physical_impact"])

    def test_no_undetected_impact_when_detected(self):
        analysis = {"analysis": {"max_lane_error_m": 0.50}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=True)
        self.assertTrue(f["out_of_formation"])
        self.assertFalse(f["undetected_physical_impact"])

    def test_no_undetected_impact_when_not_oof(self):
        analysis = {"analysis": {"max_lane_error_m": 0.10}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertFalse(f["out_of_formation"])
        self.assertFalse(f["undetected_physical_impact"])

    def test_no_threshold_config_never_violations(self):
        analysis = {"analysis": {"max_lane_error_m": 999.0}}
        f = _analyze_formation(analysis, {}, detected=False)
        self.assertFalse(f["out_of_formation"])

    def test_lane_error_value_preserved(self):
        analysis = {"analysis": {"max_lane_error_m": 0.42}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertAlmostEqual(f["max_lane_error"], 0.42, places=3)

    def test_lane_error_derived_from_per_robot_metrics(self):
        analysis = {
            "analysis": {
                "robots": {
                    "Fridjof": {"max_abs_lane_error": 0.18},
                    "Torleif": {"max_abs_lane_error": 0.41},
                    "Bjarte": {"max_abs_lane_error": 0.09},
                }
            }
        }
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertAlmostEqual(f["max_lane_error"], 0.41, places=3)
        self.assertTrue(f["out_of_formation"])
        self.assertTrue(f["undetected_physical_impact"])

    def test_top_level_lane_error_takes_precedence_over_derived_robot_value(self):
        analysis = {
            "analysis": {
                "max_lane_error_m": 0.22,
                "robots": {
                    "Fridjof": {"max_abs_lane_error": 0.48},
                },
            }
        }
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertAlmostEqual(f["max_lane_error"], 0.22, places=3)
        self.assertFalse(f["out_of_formation"])

    def test_spacing_error_accepts_non_m_suffix_key(self):
        analysis = {"analysis": {"max_spacing_error": 0.55}}
        f = _analyze_formation(analysis, self.THRESHOLDS, detected=False)
        self.assertAlmostEqual(f["max_spacing_error"], 0.55, places=3)
        self.assertTrue(f["out_of_formation"])


# ── Trial result building ─────────────────────────────────────────────────────

class TestBuildTrialResult(unittest.TestCase):

    def _formation(self, oof=False, upi=False):
        return {
            "max_lane_error": None,
            "max_spacing_error": None,
            "out_of_formation": oof,
            "out_of_formation_duration_s": None,
            "recovery_time_s": None,
            "undetected_physical_impact": upi,
        }

    def test_all_csv_fields_present(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        for field in TRIAL_CSV_FIELDS:
            self.assertIn(field, result, f"Missing CSV field: {field}")

    def test_identity_fields(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        self.assertEqual(result["experiment_id"], "test_exp")
        self.assertEqual(result["trial_id"], "trial-0001-abcd1234")
        self.assertEqual(result["trial_number"], 1)
        self.assertEqual(result["run_id"], "run-001")
        self.assertEqual(result["seed"], 1337)

    def test_attack_fields_from_resolved_request(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        self.assertEqual(result["attack_type"], "velocity_spoof")
        self.assertEqual(result["attack_mode"], "static")
        self.assertAlmostEqual(result["speed_mps"], 0.85, places=3)
        self.assertAlmostEqual(result["delay_s"], 5.0, places=3)
        self.assertAlmostEqual(result["duration_s"], 12.0, places=3)

    def test_generator_fields_from_generated_attack_strategy(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        self.assertEqual(result["attack_family"], "velocity_spoof")
        self.assertEqual(result["attack_strategy"], "constant")
        self.assertEqual(result["attack_difficulty"], "medium")

    def test_generated_attack_strategy_json_in_result(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        json_field = result.get("generated_attack_strategy_json")
        self.assertIsNotNone(json_field)
        parsed = json.loads(json_field)
        self.assertEqual(parsed["attack_family"], "velocity_spoof")
        self.assertNotIn("_unsupported", parsed)

    def test_detection_true_from_analysis(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        self.assertTrue(result["detected"])

    def test_no_negative_ttd(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        ttd = result["time_to_detection_s"]
        if ttd is not None:
            self.assertGreaterEqual(ttd, 0.0, "TTD must be >= 0")

    def test_no_analysis_gives_not_detected(self):
        result = _build_trial_result(SAMPLE_MANIFEST, None, self._formation())
        self.assertFalse(result["detected"])
        self.assertEqual(result["anomaly_frames"], 0)

    def test_errored_manifest_gives_excluded(self):
        bad_manifest = dict(SAMPLE_MANIFEST, errors=["Backend unreachable"])
        result = _build_trial_result(bad_manifest, None, self._formation())
        self.assertTrue(result["excluded"])
        self.assertIn("Backend unreachable", result["exclusion_reason"])

    def test_formation_fields_propagated(self):
        formation = self._formation(oof=True, upi=True)
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, formation)
        self.assertTrue(result["out_of_formation"])
        self.assertTrue(result["undetected_physical_impact"])

    def test_expected_window_fields(self):
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, self._formation())
        self.assertAlmostEqual(result["expected_attack_start_s"], 15.0, places=3)
        self.assertAlmostEqual(result["expected_attack_end_s"], 27.0, places=3)


# ── Experiment summary ────────────────────────────────────────────────────────

class TestBuildExperimentSummary(unittest.TestCase):

    def _result(self, **kwargs) -> dict:
        base = {
            "detected": False,
            "time_to_detection_s": None,
            "worst_risk_level": "low",
            "attack_family": "velocity_spoof",
            "attack_strategy": "constant",
            "attack_difficulty": "medium",
            "attack_type": "velocity_spoof",
            "out_of_formation": False,
            "undetected_physical_impact": False,
            "pre_attack_detection": False,
            "excluded": False,
        }
        base.update(kwargs)
        return base

    def test_empty_results(self):
        summary = _build_experiment_summary([], MINIMAL_CFG, 0.0, 10.0, 42)
        self.assertEqual(summary["total_trials"], 0)
        self.assertEqual(summary["detected_trials"], 0)
        self.assertEqual(summary["detection_rate"], 0.0)
        self.assertIsNone(summary["mean_time_to_detection_s"])

    def test_all_detected(self):
        results = [
            self._result(detected=True, time_to_detection_s=5.0),
            self._result(detected=True, time_to_detection_s=3.0),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["detected_trials"], 2)
        self.assertAlmostEqual(summary["detection_rate"], 1.0, places=3)
        self.assertAlmostEqual(summary["mean_time_to_detection_s"], 4.0, places=3)

    def test_partial_detection(self):
        results = [
            self._result(detected=True, time_to_detection_s=5.0),
            self._result(detected=False),
            self._result(detected=False),
            self._result(detected=True, time_to_detection_s=10.0),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 100.0, 42)
        self.assertEqual(summary["total_trials"], 4)
        self.assertEqual(summary["detected_trials"], 2)
        self.assertAlmostEqual(summary["detection_rate"], 0.5, places=3)
        self.assertAlmostEqual(summary["mean_time_to_detection_s"], 7.5, places=3)

    def test_errored_trials_remain_in_detection_rate_denominator(self):
        results = [
            self._result(detected=True, time_to_detection_s=5.0),
            self._result(excluded=True, detected=False),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["total_trials"], 2)
        self.assertNotIn("excluded_trials", summary)
        self.assertAlmostEqual(summary["detection_rate"], 0.5, places=3)

    def test_risk_level_counts(self):
        results = [
            self._result(worst_risk_level="high"),
            self._result(worst_risk_level="high"),
            self._result(worst_risk_level="low"),
            self._result(worst_risk_level="critical"),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["risk_level_counts"]["high"], 2)
        self.assertEqual(summary["risk_level_counts"]["low"], 1)
        self.assertEqual(summary["risk_level_counts"]["critical"], 1)

    def test_attack_family_counts(self):
        results = [
            self._result(attack_family="velocity_spoof"),
            self._result(attack_family="velocity_spoof"),
            self._result(attack_family="false_brake"),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["attack_family_counts"]["velocity_spoof"], 2)
        self.assertEqual(summary["attack_family_counts"]["false_brake"], 1)

    def test_attack_strategy_counts(self):
        results = [
            self._result(attack_strategy="constant"),
            self._result(attack_strategy="ramp"),
            self._result(attack_strategy="constant"),
            self._result(attack_strategy="near_threshold"),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["attack_strategy_counts"]["constant"], 2)
        self.assertEqual(summary["attack_strategy_counts"]["ramp"], 1)
        self.assertEqual(summary["attack_strategy_counts"]["near_threshold"], 1)

    def test_attack_difficulty_counts(self):
        results = [
            self._result(attack_difficulty="hard"),
            self._result(attack_difficulty="medium"),
            self._result(attack_difficulty="hard"),
            self._result(attack_difficulty="easy"),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["attack_difficulty_counts"]["hard"], 2)
        self.assertEqual(summary["attack_difficulty_counts"]["medium"], 1)
        self.assertEqual(summary["attack_difficulty_counts"]["easy"], 1)

    def test_out_of_formation_count(self):
        results = [
            self._result(out_of_formation=True),
            self._result(out_of_formation=True),
            self._result(out_of_formation=False),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["out_of_formation_trials"], 2)

    def test_undetected_physical_impact_count(self):
        results = [
            self._result(undetected_physical_impact=True),
            self._result(undetected_physical_impact=False),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["undetected_physical_impact_trials"], 1)

    def test_pre_attack_detection_count(self):
        results = [
            self._result(pre_attack_detection=True),
            self._result(pre_attack_detection=False),
            self._result(pre_attack_detection=True),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 60.0, 42)
        self.assertEqual(summary["pre_attack_detection_trials"], 2)

    def test_seed_and_timestamps_recorded(self):
        summary = _build_experiment_summary([], MINIMAL_CFG, 1000.0, 1060.0, 9999)
        self.assertEqual(summary["seed"], 9999)
        self.assertAlmostEqual(summary["started_at"], 1000.0)
        self.assertAlmostEqual(summary["stopped_at"], 1060.0)
        self.assertAlmostEqual(summary["duration_s"], 60.0, places=1)

    def test_mean_ttd_none_when_no_detected_trials(self):
        results = [self._result(detected=False) for _ in range(5)]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 100.0, 1)
        self.assertIsNone(summary["mean_time_to_detection_s"])

    def test_mean_ttd_excludes_none_ttd_entries(self):
        results = [
            self._result(detected=True, time_to_detection_s=10.0),
            self._result(detected=True, time_to_detection_s=None),
            self._result(detected=True, time_to_detection_s=20.0),
        ]
        summary = _build_experiment_summary(results, MINIMAL_CFG, 0.0, 100.0, 1)
        self.assertAlmostEqual(summary["mean_time_to_detection_s"], 15.0, places=3)


class TestAppendExistingTrials(unittest.TestCase):
    """Existing summary rows should make a resumed run continue numbering."""

    def test_missing_summary_starts_at_zero(self):
        tmp = _tmpdir_path()
        self.assertEqual(_existing_trial_count(tmp / "trials_summary.csv"), 0)

    def test_existing_summary_returns_highest_trial_number(self):
        tmp = _tmpdir_path()
        path = tmp / "trials_summary.csv"
        path.write_text(
            "trial_number,detected\n1,True\n3,False\n2,True\n",
            encoding="utf-8",
        )
        self.assertEqual(_existing_trial_count(path), 3)

# Target-state gate

class TestPlatoonTargetStateGate(unittest.TestCase):
    """Tests for attack target gating on active platoon states."""

    def _buffer(self, state, frame_id=12):
        return {
            "last_frame_id": frame_id,
            "frames": [
                {
                    "frame_id": frame_id,
                    "data": {
                        "robots": {
                            "Fridjof": {"st": state},
                            "Torleif": {"st": 0},
                        }
                    },
                }
            ]
        }

    def test_latest_frame_from_buffer_returns_enriched_data(self):
        frame = _latest_frame_from_buffer(self._buffer(3))
        self.assertEqual(frame["robots"]["Fridjof"]["st"], 3)

    def test_robot_state_from_frame_extracts_st(self):
        frame = {"robots": {"Fridjof": {"st": "4"}}}
        self.assertEqual(_robot_state_from_frame(frame, "Fridjof"), 4)

    def test_target_state_three_is_allowed(self):
        ok, reason, state = _target_platoon_state_ok(self._buffer(3), "Fridjof")
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(state, 3)

    def test_target_state_four_is_allowed(self):
        ok, reason, state = _target_platoon_state_ok(self._buffer(4), "Fridjof")
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(state, 4)

    def test_target_state_zero_is_blocked(self):
        ok, reason, state = _target_platoon_state_ok(self._buffer(0), "Fridjof")
        self.assertFalse(ok)
        self.assertEqual(state, 0)
        self.assertIn("PLATOONING", reason)
        self.assertIn("RECOVERY", reason)

    def test_missing_live_frame_is_blocked(self):
        ok, reason, state = _target_platoon_state_ok({"frames": []}, "Fridjof")
        self.assertFalse(ok)
        self.assertIsNone(state)
        self.assertIn("No live frame", reason)

    def test_no_target_skips_gate(self):
        ok, reason, state = _target_platoon_state_ok(self._buffer(0), None)
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertIsNone(state)

    def test_wait_gate_accepts_none_timeout_as_pause_until_ready(self):
        original_get = randomized_trials._http_get
        original_post = randomized_trials._http_post
        original_sleep = randomized_trials.time.sleep
        resets: list[str] = []
        frames = iter([(0, 1), (0, 2), (3, 3)])

        def fake_get(*args, **kwargs):
            state, frame_id = next(frames)
            return self._buffer(state, frame_id), None

        def fake_post(*args, **kwargs):
            resets.append(args[1])
            return {"ok": True}, None

        try:
            randomized_trials._http_get = fake_get
            randomized_trials._http_post = fake_post
            randomized_trials.time.sleep = lambda *_args, **_kwargs: None
            ok, reason, state = _wait_for_target_platoon_state(
                "http://test",
                "Fridjof",
                timeout_s=None,
                poll_s=0.0,
            )
        finally:
            randomized_trials._http_get = original_get
            randomized_trials._http_post = original_post
            randomized_trials.time.sleep = original_sleep

        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(state, 3)
        self.assertEqual(resets, ["/attack/reset"])

    def test_wait_gate_rejects_stale_state_three_until_fresh_frame(self):
        original_get = randomized_trials._http_get
        original_post = randomized_trials._http_post
        original_sleep = randomized_trials.time.sleep
        calls = {"count": 0}

        def fake_get(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                return self._buffer(3, frame_id=10), None
            return self._buffer(3, frame_id=11), None

        try:
            randomized_trials._http_get = fake_get
            randomized_trials._http_post = lambda *args, **kwargs: ({"ok": True}, None)
            randomized_trials.time.sleep = lambda *_args, **_kwargs: None
            ok, reason, state = _wait_for_target_platoon_state(
                "http://test",
                "Fridjof",
                timeout_s=None,
                poll_s=0.0,
            )
        finally:
            randomized_trials._http_get = original_get
            randomized_trials._http_post = original_post
            randomized_trials.time.sleep = original_sleep

        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(state, 3)
        self.assertGreaterEqual(calls["count"], 3)


# ── Clean baseline gate ───────────────────────────────────────────────────────

class TestCleanBaselineGate(unittest.TestCase):
    """Tests for the pre-trial clean live state gate."""

    # ── _risk_snapshot_clean ──────────────────────────────────────────────────

    def test_empty_snapshot_is_clean(self):
        ok, reason = _risk_snapshot_clean({})
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_no_active_threat_marker_is_clean(self):
        snapshot = {
            "current_risk_objects": [
                {"signal_type": "no_active_threat", "source_type": "current_live", "risk_level": "low"}
            ]
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_historical_baseline_high_is_clean(self):
        """High historical baseline must NOT block a new trial."""
        snapshot = {
            "current_risk_objects": [
                {
                    "signal_type": "historical_baseline",
                    "source_type": "current_live",
                    "risk_level": "high",
                    "signal_subtype": "high",
                }
            ]
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertTrue(ok, "Historical baseline high should not block trial")
        self.assertIsNone(reason)

    def test_historical_baseline_critical_is_clean(self):
        snapshot = {
            "current_risk_objects": [
                {"signal_type": "historical_baseline", "risk_level": "critical"}
            ]
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertTrue(ok)

    def test_velocity_spoof_live_object_is_dirty(self):
        snapshot = {
            "current_risk_objects": [
                {
                    "signal_type": "velocity_spoof_live",
                    "source_type": "current_live",
                    "risk_level": "high",
                }
            ]
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertFalse(ok)
        self.assertIn("velocity_spoof_live", reason)

    def test_velocity_spoof_direct_object_is_dirty(self):
        snapshot = {
            "current_risk_objects": [
                {"signal_type": "velocity_spoof", "source_type": "current_live", "risk_level": "high"}
            ]
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertFalse(ok)
        self.assertIsNotNone(reason)

    def test_historical_high_plus_no_threat_is_clean(self):
        """Historical high + no_active_threat together must still be clean."""
        snapshot = {
            "current_risk_objects": [
                {"signal_type": "historical_baseline", "risk_level": "high"},
                {"signal_type": "no_active_threat", "risk_level": "low"},
            ]
        }
        ok, _ = _risk_snapshot_clean(snapshot)
        self.assertTrue(ok)

    def test_live_contribution_active_velocity_spoof_is_dirty(self):
        snapshot = {
            "current_risk_objects": [],
            "live_contribution": {
                "threats": [
                    {"attack_type": "velocity_spoof", "status": "active"}
                ]
            },
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertFalse(ok)
        self.assertIn("velocity_spoof", reason)

    def test_live_contribution_pending_velocity_spoof_is_dirty(self):
        snapshot = {
            "current_risk_objects": [],
            "live_contribution": {
                "threats": [{"attack_type": "velocity_spoof", "status": "pending"}]
            },
        }
        ok, reason = _risk_snapshot_clean(snapshot)
        self.assertFalse(ok)

    def test_live_contribution_false_brake_only_is_clean(self):
        """false_brake in live_contribution should not block velocity_spoof gate."""
        snapshot = {
            "current_risk_objects": [],
            "live_contribution": {
                "threats": [{"attack_type": "false_brake", "status": "active"}]
            },
        }
        ok, _ = _risk_snapshot_clean(snapshot)
        self.assertTrue(ok)

    # ── _alerts_clean ─────────────────────────────────────────────────────────

    def test_empty_alerts_dict_is_clean(self):
        ok, reason = _alerts_clean({"active_alerts": [], "overall_level": "low"})
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_empty_alerts_list_is_clean(self):
        ok, reason = _alerts_clean([])
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_none_alerts_is_clean(self):
        ok, reason = _alerts_clean(None)
        self.assertTrue(ok)

    def test_active_velocity_spoof_alert_is_dirty(self):
        alerts = {
            "active_alerts": [
                {
                    "attack_type": "velocity_spoof",
                    "status": "active",
                    "source": "live",
                    "is_live": True,
                }
            ]
        }
        ok, reason = _alerts_clean(alerts)
        self.assertFalse(ok)
        self.assertIn("velocity_spoof", reason)

    def test_pending_velocity_spoof_alert_is_dirty(self):
        alerts = {
            "active_alerts": [
                {"attack_type": "velocity_spoof", "status": "pending", "source": "live"}
            ]
        }
        ok, reason = _alerts_clean(alerts)
        self.assertFalse(ok)

    def test_false_brake_active_alert_is_clean_for_velocity_spoof_gate(self):
        """false_brake alerts should not block (we are gating on velocity_spoof only)."""
        alerts = {
            "active_alerts": [
                {"attack_type": "false_brake", "status": "active", "source": "live"}
            ]
        }
        ok, _ = _alerts_clean(alerts)
        self.assertTrue(ok)

    def test_alerts_as_bare_list_with_active_vs(self):
        alerts = [{"attack_type": "velocity_spoof", "status": "active", "source": "live"}]
        ok, reason = _alerts_clean(alerts)
        self.assertFalse(ok)

    # ── _handle_gate_failure ──────────────────────────────────────────────────

    def test_gate_success_returns_false_no_side_effects(self):
        errors, warnings = [], []
        should_exclude = _handle_gate_failure(True, None, "exclude_trial", errors, warnings)
        self.assertFalse(should_exclude)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_gate_failure_exclude_trial_returns_true(self):
        errors, warnings = [], []
        should_exclude = _handle_gate_failure(
            False, "velocity_spoof_live active", "exclude_trial", errors, warnings
        )
        self.assertTrue(should_exclude)
        self.assertTrue(any("Clean baseline gate failed" in e for e in errors))
        self.assertEqual(warnings, [])

    def test_gate_failure_warn_and_continue_returns_false(self):
        errors, warnings = [], []
        should_exclude = _handle_gate_failure(
            False, "stale detector state", "warn_and_continue", errors, warnings
        )
        self.assertFalse(should_exclude)
        self.assertEqual(errors, [])
        self.assertTrue(any("Clean baseline gate failed before trial" in w for w in warnings))

    def test_gate_failure_unknown_on_timeout_defaults_to_warn(self):
        """Unrecognised on_timeout value should not exclude (fail open = safer)."""
        errors, warnings = [], []
        should_exclude = _handle_gate_failure(False, "x", "INVALID", errors, warnings)
        self.assertFalse(should_exclude)

    # ── Gate exclusion → excluded trial result ────────────────────────────────

    def test_gate_exclude_produces_excluded_result(self):
        """Excluded gate result → manifest errors → _build_trial_result marks excluded."""
        errors: list[str] = []
        warnings: list[str] = []
        _handle_gate_failure(
            False, "velocity_spoof_live high", "exclude_trial", errors, warnings
        )
        manifest = {
            **SAMPLE_MANIFEST,
            "run_id": None,   # recording never started
            "errors": errors,
            "warnings": warnings,
        }
        formation = {
            "max_lane_error": None, "max_spacing_error": None,
            "out_of_formation": False, "out_of_formation_duration_s": None,
            "recovery_time_s": None, "undetected_physical_impact": False,
        }
        result = _build_trial_result(manifest, None, formation)
        self.assertTrue(result["excluded"])
        self.assertIn("Clean baseline gate failed", result["exclusion_reason"])
        self.assertFalse(result["pre_attack_detection"])

    def test_gate_warn_does_not_exclude_result(self):
        """warn_and_continue gate result → manifest has warning, not excluded."""
        errors: list[str] = []
        warnings: list[str] = []
        _handle_gate_failure(
            False, "stale state", "warn_and_continue", errors, warnings
        )
        manifest = {
            **SAMPLE_MANIFEST,
            "errors": errors,
            "warnings": warnings,
        }
        formation = {
            "max_lane_error": None, "max_spacing_error": None,
            "out_of_formation": False, "out_of_formation_duration_s": None,
            "recovery_time_s": None, "undetected_physical_impact": False,
        }
        result = _build_trial_result(manifest, SAMPLE_ANALYSIS, formation)
        self.assertFalse(result["excluded"])
        self.assertTrue(any("Clean baseline gate failed before trial" in w for w in warnings))

    def test_pre_attack_detection_still_in_csv_fields(self):
        """pre_attack_detection must remain in TRIAL_CSV_FIELDS after gate addition."""
        self.assertIn("pre_attack_detection", TRIAL_CSV_FIELDS)

    def test_no_negative_ttd_after_gate_changes(self):
        """TTD must still be >= 0 when gate is present (regression guard)."""
        formation = {
            "max_lane_error": None, "max_spacing_error": None,
            "out_of_formation": False, "out_of_formation_duration_s": None,
            "recovery_time_s": None, "undetected_physical_impact": False,
        }
        result = _build_trial_result(SAMPLE_MANIFEST, SAMPLE_ANALYSIS, formation)
        ttd = result.get("time_to_detection_s")
        if ttd is not None:
            self.assertGreaterEqual(ttd, 0.0)


# ── No-attack strategy ────────────────────────────────────────────────────────

_NO_ATTACK_GEN_CFG = {
    "family_probabilities": {"no_attack": 1.0},
    "timing": {
        "delay_s": {"min": 0, "max": 0},
        "duration_s": {"min": 10, "max": 10},
    },
}

_MIXED_GEN_CFG_WITH_NO_ATTACK = {
    "target_robots": ["Fridjof"],
    "family_probabilities": {"velocity_spoof": 0.70, "false_brake": 0.20, "no_attack": 0.10},
    "timing": {
        "delay_s": {"min": 0, "max": 10},
        "duration_s": {"min": 5, "max": 20},
    },
    "velocity_spoof": {
        "strategy_probabilities": {"constant": 1.0},
        "speed_mps": {"min": 0.8, "max": 0.8},
    },
    "false_brake": {"duration_s": {"min": 5, "max": 10}},
}


class TestNoAttackStrategy(unittest.TestCase):

    def _rng(self, seed: int = 42) -> random.Random:
        return random.Random(seed)

    def test_no_attack_generates_required_fields(self):
        strategy = generate_attack_strategy(self._rng(), _NO_ATTACK_GEN_CFG)
        for field in ("attack_family", "strategy", "target_robot", "delay_s", "duration_s", "attack_difficulty"):
            self.assertIn(field, strategy, f"Missing field: {field}")

    def test_no_attack_family_and_strategy_values(self):
        strategy = generate_attack_strategy(self._rng(), _NO_ATTACK_GEN_CFG)
        self.assertEqual(strategy["attack_family"], "no_attack")
        self.assertEqual(strategy["strategy"], "none")

    def test_no_attack_difficulty_is_none(self):
        strategy = generate_attack_strategy(self._rng(), _NO_ATTACK_GEN_CFG)
        self.assertEqual(strategy["attack_difficulty"], "none")

    def test_no_attack_delay_is_always_zero(self):
        for seed in range(10):
            strategy = generate_attack_strategy(random.Random(seed), _NO_ATTACK_GEN_CFG)
            self.assertAlmostEqual(strategy["delay_s"], 0.0, places=6)

    def test_no_attack_duration_from_timing_bounds(self):
        cfg = {
            "family_probabilities": {"no_attack": 1.0},
            "timing": {"delay_s": {"min": 0, "max": 0}, "duration_s": {"min": 7, "max": 7}},
        }
        strategy = generate_attack_strategy(self._rng(), cfg)
        self.assertAlmostEqual(strategy["duration_s"], 7.0, places=4)

    def test_build_attack_request_raises_for_no_attack(self):
        strategy = generate_attack_strategy(self._rng(), _NO_ATTACK_GEN_CFG)
        with self.assertRaises(ValueError):
            build_attack_request_from_strategy(strategy)

    def test_no_attack_sampled_when_probability_set(self):
        strategies = [
            generate_attack_strategy(random.Random(s), _NO_ATTACK_GEN_CFG)
            for s in range(20)
        ]
        self.assertTrue(all(s["attack_family"] == "no_attack" for s in strategies))

    def test_no_attack_not_generated_when_not_in_family_probs(self):
        cfg = dict(FULL_GEN_CFG)
        families = {
            generate_attack_strategy(random.Random(s), cfg)["attack_family"]
            for s in range(50)
        }
        self.assertNotIn("no_attack", families)


# ── Warmup first-trial-only ───────────────────────────────────────────────────

_WARMUP_ATTACK_CFG = {
    "experiment_id": "test_warmup_exp",
    "backend_url": "http://localhost:8000",
    "warmup_s": 10,
    "attack_generator": {
        "family_probabilities": {"velocity_spoof": 1.0},
        "timing": {
            "delay_s": {"min": 0, "max": 0},
            "duration_s": {"min": 10, "max": 10},
        },
        "velocity_spoof": {
            "strategy_probabilities": {"constant": 1.0},
            "speed_mps": {"min": 0.8, "max": 0.8},
        },
    },
}

_WARMUP_NO_ATTACK_CFG = {
    "experiment_id": "test_warmup_no_attack",
    "backend_url": "http://localhost:8000",
    "warmup_s": 10,
    "attack_generator": {
        "family_probabilities": {"no_attack": 1.0},
        "timing": {
            "delay_s": {"min": 0, "max": 0},
            "duration_s": {"min": 10, "max": 10},
        },
    },
}


class TestWarmupFirstTrialOnly(unittest.TestCase):

    def _run(self, cfg, trial_number, *, is_first_trial=True, seed=42):
        rng = random.Random(seed)
        return run_trial(
            cfg, trial_number, rng, seed, Path("."),
            dry_run=True,
            is_first_trial=is_first_trial,
        )

    def test_first_trial_expected_start_includes_warmup(self):
        result = self._run(_WARMUP_ATTACK_CFG, 1, is_first_trial=True)
        # delay_s=0, warmup_s=10 → expected_attack_start_s == 10.0
        self.assertAlmostEqual(result["expected_attack_start_s"], 10.0, places=4)

    def test_subsequent_trial_expected_start_excludes_warmup(self):
        result = self._run(_WARMUP_ATTACK_CFG, 2, is_first_trial=False)
        # delay_s=0, effective_warmup_s=0 → expected_attack_start_s == 0.0
        self.assertAlmostEqual(result["expected_attack_start_s"], 0.0, places=4)

    def test_default_is_first_trial_true(self):
        rng = random.Random(42)
        result_default = run_trial(
            _WARMUP_ATTACK_CFG, 1, rng, 42, Path("."), dry_run=True
        )
        self.assertAlmostEqual(result_default["expected_attack_start_s"], 10.0, places=4)

    def test_no_attack_trial_expected_start_is_none(self):
        result = self._run(_WARMUP_NO_ATTACK_CFG, 1, is_first_trial=True)
        self.assertIsNone(result["expected_attack_start_s"])
        self.assertIsNone(result["expected_attack_end_s"])


# ── Micro-spoof strategy ──────────────────────────────────────────────────────

_MICRO_SPOOF_GEN_CFG = {
    "target_robots": ["Fridjof"],
    "family_probabilities": {"velocity_spoof": 1.0},
    "timing": {
        "delay_s": {"min": 0, "max": 5},
        "duration_s": {"min": 5, "max": 10},
    },
    "velocity_spoof": {
        "strategy_probabilities": {"micro_spoof": 1.0},
        "micro_spoof": {
            "duration_s": {"min": 2.0, "max": 8.0},
            "deviation_mps": {"min": 0.01, "max": 0.08},
            "direction_probabilities": {"underreport": 0.6, "overreport": 0.4},
        },
    },
}


class TestMicroSpoofStrategy(unittest.TestCase):

    def _rng(self, seed: int = 42) -> random.Random:
        return random.Random(seed)

    def test_micro_spoof_required_fields(self):
        strategy = generate_attack_strategy(self._rng(), _MICRO_SPOOF_GEN_CFG)
        for field in ("attack_family", "strategy", "target_robot",
                      "delay_s", "duration_s", "deviation_mps",
                      "direction", "speed_mps", "attack_difficulty"):
            self.assertIn(field, strategy, f"Missing field: {field}")

    def test_micro_spoof_family_and_strategy_values(self):
        strategy = generate_attack_strategy(self._rng(), _MICRO_SPOOF_GEN_CFG)
        self.assertEqual(strategy["attack_family"], "velocity_spoof")
        self.assertEqual(strategy["strategy"], "micro_spoof")

    def test_micro_spoof_duration_at_least_1_5_s(self):
        # Even when the config allows very short durations, minimum is enforced
        cfg = dict(_MICRO_SPOOF_GEN_CFG)
        cfg["velocity_spoof"] = dict(_MICRO_SPOOF_GEN_CFG["velocity_spoof"],
                                     micro_spoof={"duration_s": {"min": 0.1, "max": 0.5},
                                                   "deviation_mps": {"min": 0.01, "max": 0.08}})
        for seed in range(20):
            s = generate_attack_strategy(random.Random(seed), cfg)
            self.assertGreaterEqual(s["duration_s"], 1.5,
                                    f"duration_s below minimum 1.5 s: {s['duration_s']}")

    def test_micro_spoof_deviation_within_bounds(self):
        for seed in range(20):
            s = generate_attack_strategy(random.Random(seed), _MICRO_SPOOF_GEN_CFG)
            self.assertGreaterEqual(s["deviation_mps"], 0.01)
            self.assertLessEqual(s["deviation_mps"], 0.08)

    def test_micro_spoof_difficulty_always_hard(self):
        for seed in range(15):
            s = generate_attack_strategy(random.Random(seed), _MICRO_SPOOF_GEN_CFG)
            self.assertEqual(s["attack_difficulty"], "hard")

    def test_micro_spoof_compiles_to_static_velocity_spoof(self):
        strategy = generate_attack_strategy(self._rng(), _MICRO_SPOOF_GEN_CFG)
        attack_type, body = build_attack_request_from_strategy(strategy)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "static")
        self.assertIn("speed_mps", body)

    def test_micro_spoof_direction_underreport_speed_below_baseline(self):
        cfg = dict(_MICRO_SPOOF_GEN_CFG)
        cfg["velocity_spoof"] = dict(_MICRO_SPOOF_GEN_CFG["velocity_spoof"],
                                     micro_spoof={"duration_s": {"min": 2.0, "max": 2.0},
                                                   "deviation_mps": {"min": 0.05, "max": 0.05},
                                                   "direction_probabilities": {"underreport": 1.0}})
        s = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(s["direction"], "underreport")
        self.assertLess(s["speed_mps"], 1.0)  # leader baseline is 1.0

    def test_micro_spoof_direction_overreport_speed_above_baseline(self):
        cfg = dict(_MICRO_SPOOF_GEN_CFG)
        cfg["velocity_spoof"] = dict(_MICRO_SPOOF_GEN_CFG["velocity_spoof"],
                                     micro_spoof={"duration_s": {"min": 2.0, "max": 2.0},
                                                   "deviation_mps": {"min": 0.05, "max": 0.05},
                                                   "direction_probabilities": {"overreport": 1.0}})
        s = generate_attack_strategy(self._rng(), cfg)
        self.assertEqual(s["direction"], "overreport")
        self.assertGreater(s["speed_mps"], 1.0)

    def test_micro_spoof_deterministic_with_same_seed(self):
        s1 = generate_attack_strategy(random.Random(77), _MICRO_SPOOF_GEN_CFG)
        s2 = generate_attack_strategy(random.Random(77), _MICRO_SPOOF_GEN_CFG)
        self.assertEqual(s1["deviation_mps"], s2["deviation_mps"])
        self.assertEqual(s1["direction"], s2["direction"])
        self.assertEqual(s1["speed_mps"], s2["speed_mps"])

    def test_micro_spoof_not_generated_without_probability(self):
        families = {
            generate_attack_strategy(random.Random(s), FULL_GEN_CFG)["strategy"]
            for s in range(50)
        }
        self.assertNotIn("micro_spoof", families)


if __name__ == "__main__":
    unittest.main(verbosity=2)
