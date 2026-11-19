#!/usr/bin/env python3
"""
Unit tests for the TwinGuard experiment pipeline.

Tests config validation, output path helpers, metric extraction, and
manifest/event file writing.  No live backend or robots required.

Run from the repo root:
  python -m pytest experiments/tests/test_pipeline.py -v
or:
  python experiments/tests/test_pipeline.py
"""
from __future__ import annotations

import csv
import json
import random
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

# Allow direct imports from experiments/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_campaign import (  # noqa: E402
    EventLog,
    _attack_status_idle,
    _build_attack_request,
    _is_clean_scenario,
    _make_rep_seed,
    _resolve_attack_params,
    _resolve_campaign_seed,
    _validate_config,
    _validate_randomize_block,
    count_completed_runs,
    run_output_dir,
    scenario_output_dir,
)
from analyze_campaign import (  # noqa: E402
    CSV_FIELDS,
    _relevant_objects,
    _timestamp_starts,
    extract_metrics,
)


_TEST_TMP_ROOT = Path(__file__).resolve().parents[2] / "tmp" / "experiment_tests"


@contextmanager
def _workspace_tempdir():
    _TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    td = _TEST_TMP_ROOT / f"case_{uuid.uuid4().hex}"
    td.mkdir(parents=True, exist_ok=True)
    try:
        yield str(td)
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_MANIFEST = {
    "campaign_id": "test_campaign",
    "scenario_id": "velocity_spoof_static_low",
    "label": "Static low-speed spoof",
    "repetition": 1,
    "run_id": "run-abc-0001",
    "backend_url": "http://localhost:8000",
    "started_at": 1700000000.0,
    "stopped_at": 1700000070.0,
    "attack_type": "velocity_spoof",
    "expected_attack_start_s": 15.0,
    "expected_attack_end_s": 30.0,
    "attack_request": {
        "mode": "static",
        "speed_mps": 0.15,
        "duration_s": 15,
        "delay_s": 0,
        "target_robot": "follower_1",
    },
    "attack_response": {"ok": True},
    "git_commit": "abc123def456",
    "errors": [],
    "warnings": [],
}

SAMPLE_ANALYSIS = {
    "run_id": "run-abc-0001",
    "status": "complete",
    "frame_count": 1200,
    "duration_s": 60.0,
    "risk": "high",
    "risk_score": 75,
    "analysis": {
        "anomaly_frames": 45,
        "anomaly_ratio": 0.0375,
        "findings": ["Velocity spoof detected in 45/1200 frames"],
        "timeline": [],
    },
    "nist_findings": {
        "worst_risk_level": "high",
        "risk_objects": [
            {
                "id": "obj_001",
                "signal_type": "velocity_spoof",
                "signal_subtype": "detector",
                "risk_level": "high",
                "risk_score": 12,
                "likelihood": 3,
                "impact": 4,
                "timestamp_range": [18.5, 33.2],
                "affected_robots": ["follower_1"],
                "evidence_summary": "Active velocity spoof detected via sensor labels.",
                "confidence": 0.85,
                "completeness": 0.9,
                "assumptions": [],
                "csf_mappings": [],
                "incident_actions": [],
            }
        ],
        "nist_summary": {
            "total_findings": 1,
            "level_counts": {
                "low": 0, "moderate": 0, "high": 1, "critical": 0
            },
            "avg_confidence": 0.85,
            "session_completeness": 0.9,
            "nist_methods": ["velocity_spoof_detector"],
        },
    },
}

VALID_CONFIG = {
    "campaign_id": "test_campaign",
    "repetitions": 2,
    "warmup_s": 10,
    "recovery_s": 15,
    "backend_url": "http://localhost:8000",
    "scenarios": [
        {"id": "baseline_clean", "label": "Clean baseline", "attack": None},
        {
            "id": "vs_static_low",
            "label": "Static velocity spoof",
            "attack": {
                "type": "velocity_spoof",
                "mode": "static",
                "speed_mps": 0.15,
                "delay_s": 0,
                "duration_s": 15,
                "target_robot": "follower_1",
            },
        },
        {
            "id": "false_brake_short",
            "label": "False brake short",
            "attack": {
                "type": "false_brake",
                "delay_s": 0,
                "duration_s": 8,
                "target_robot": "follower_1",
            },
        },
    ],
}


# ── Config validation ─────────────────────────────────────────────────────────

class TestConfigValidation(unittest.TestCase):

    def test_valid_config_passes(self):
        _validate_config(VALID_CONFIG)

    def test_missing_campaign_id_raises(self):
        bad = {k: v for k, v in VALID_CONFIG.items() if k != "campaign_id"}
        with self.assertRaises(ValueError, msg="Should raise for missing campaign_id"):
            _validate_config(bad)

    def test_missing_scenarios_raises(self):
        bad = {k: v for k, v in VALID_CONFIG.items() if k != "scenarios"}
        with self.assertRaises(ValueError):
            _validate_config(bad)

    def test_empty_scenarios_raises(self):
        bad = dict(VALID_CONFIG, scenarios=[])
        with self.assertRaises(ValueError):
            _validate_config(bad)

    def test_scenario_missing_id_raises(self):
        bad = dict(VALID_CONFIG, scenarios=[{"label": "no id", "attack": None}])
        with self.assertRaises(ValueError):
            _validate_config(bad)

    def test_scenario_missing_label_raises(self):
        bad = dict(VALID_CONFIG, scenarios=[{"id": "s", "attack": None}])
        with self.assertRaises(ValueError):
            _validate_config(bad)

    def test_scenario_missing_attack_key_raises(self):
        bad = dict(VALID_CONFIG, scenarios=[{"id": "s", "label": "missing attack"}])
        with self.assertRaises(ValueError):
            _validate_config(bad)


# ── Clean scenario detection ───────────────────────────────────────────────────

class TestIsCleanScenario(unittest.TestCase):

    def test_none_is_clean(self):
        self.assertTrue(_is_clean_scenario(None))

    def test_string_none_is_clean(self):
        self.assertTrue(_is_clean_scenario("none"))
        self.assertTrue(_is_clean_scenario("None"))
        self.assertTrue(_is_clean_scenario("null"))
        self.assertTrue(_is_clean_scenario(""))

    def test_dict_is_not_clean(self):
        self.assertFalse(_is_clean_scenario({"type": "false_brake"}))

    def test_string_type_is_not_clean(self):
        self.assertFalse(_is_clean_scenario("false_brake"))


# ── Attack request builder ────────────────────────────────────────────────────

class TestBuildAttackRequest(unittest.TestCase):

    def test_false_brake_request(self):
        cfg = {"type": "false_brake", "duration_s": 8, "delay_s": 0, "target_robot": "follower_1"}
        attack_type, body = _build_attack_request(cfg)
        self.assertEqual(attack_type, "false_brake")
        self.assertEqual(body["duration_s"], 8.0)
        self.assertEqual(body["delay_s"], 0.0)
        self.assertEqual(body["target_robot"], "follower_1")
        self.assertEqual(body["follower_robot"], "follower_1")
        self.assertNotIn("type", body, "attack type must not be in the body sent to API")

    def test_velocity_spoof_static_request(self):
        cfg = {
            "type": "velocity_spoof", "mode": "static",
            "speed_mps": 0.3, "duration_s": 15, "delay_s": 5,
            "target_robot": "follower_1",
        }
        attack_type, body = _build_attack_request(cfg)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertEqual(body["mode"], "static")
        self.assertAlmostEqual(body["speed_mps"], 0.3)
        self.assertEqual(body["duration_s"], 15.0)
        self.assertEqual(body["target_robot"], "follower_1")
        self.assertEqual(body["follower_robot"], "follower_1")
        self.assertNotIn("speed_start", body, "speed_start absent for static mode")

    def test_velocity_spoof_ramp_request(self):
        cfg = {
            "type": "velocity_spoof", "mode": "ramp",
            "speed_start": 0.4, "speed_end": 0.05,
            "duration_s": 20, "delay_s": 0,
        }
        attack_type, body = _build_attack_request(cfg)
        self.assertEqual(body["mode"], "ramp")
        self.assertAlmostEqual(body["speed_start"], 0.4)
        self.assertAlmostEqual(body["speed_end"], 0.05)
        self.assertNotIn("speed_mps", body, "speed_mps absent for ramp mode")

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            _build_attack_request({"type": "laser_beam", "duration_s": 5})


class TestAttackStatusIdle(unittest.TestCase):
    def test_new_status_shape_idle(self):
        self.assertTrue(_attack_status_idle({
            "false_brake": {"status": "idle"},
            "velocity_spoof": {"status": "idle"},
        }))

    def test_new_status_shape_active_is_not_idle(self):
        self.assertFalse(_attack_status_idle({
            "false_brake": {"status": "idle"},
            "velocity_spoof": {"status": "active"},
        }))

    def test_legacy_pending_flag_is_not_idle(self):
        self.assertFalse(_attack_status_idle({"velocity_spoof_pending": True}))


# ── Output path helpers ───────────────────────────────────────────────────────

class TestOutputPaths(unittest.TestCase):

    def test_scenario_dir_structure(self):
        root = Path("/tmp/tg_test_exp")
        d = scenario_output_dir(root, "camp", "sc")
        self.assertEqual(d, root / "camp" / "sc")

    def test_run_dir_structure(self):
        root = Path("/tmp/tg_test_exp")
        d = run_output_dir(root, "camp", "sc", "run123")
        self.assertEqual(d, root / "camp" / "sc" / "run123")

    def test_count_nonexistent_dir_returns_zero(self):
        self.assertEqual(count_completed_runs(Path("/tmp/no_such_dir_xyz_tw")), 0)

    def test_count_completed_runs_clean(self):
        with _workspace_tempdir() as td:
            sc_dir = Path(td)
            # Good run
            (sc_dir / "run1").mkdir()
            (sc_dir / "run1" / "manifest.json").write_text(
                json.dumps({"errors": []})
            )
            # Errored run (should NOT count)
            (sc_dir / "run2").mkdir()
            (sc_dir / "run2" / "manifest.json").write_text(
                json.dumps({"errors": ["something failed"]})
            )
            # Incomplete (no manifest — should NOT count)
            (sc_dir / "run3").mkdir()

            self.assertEqual(count_completed_runs(sc_dir), 1)

    def test_count_multiple_good_runs(self):
        with _workspace_tempdir() as td:
            sc_dir = Path(td)
            for i in range(3):
                d = sc_dir / f"run{i}"
                d.mkdir()
                (d / "manifest.json").write_text(json.dumps({"errors": []}))
            self.assertEqual(count_completed_runs(sc_dir), 3)


# ── Metric extraction ─────────────────────────────────────────────────────────

class TestExtractMetrics(unittest.TestCase):

    def test_all_csv_fields_present(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        for field in CSV_FIELDS:
            self.assertIn(field, row, f"Missing CSV field: {field}")

    def test_basic_identity_fields(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        self.assertEqual(row["campaign_id"], "test_campaign")
        self.assertEqual(row["scenario_id"], "velocity_spoof_static_low")
        self.assertEqual(row["run_id"], "run-abc-0001")
        self.assertEqual(row["repetition"], 1)

    def test_detection_true_with_matching_object(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        self.assertTrue(row["detected"])

    def test_first_detection_from_timestamp_range(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        self.assertAlmostEqual(row["first_detection_s"], 18.5, places=1)

    def test_time_to_detection_computed(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        # expected_attack_start=15.0, first_detection=18.5 → TTD=3.5s
        self.assertAlmostEqual(row["time_to_detection_s"], 3.5, places=1)

    def test_time_to_detection_uses_recording_relative_time(self):
        analysis = dict(SAMPLE_ANALYSIS)
        analysis["nist_findings"] = dict(SAMPLE_ANALYSIS["nist_findings"])
        analysis["nist_findings"]["risk_objects"] = [
            dict(
                SAMPLE_ANALYSIS["nist_findings"]["risk_objects"][0],
                timestamp_range=[18605.4, 18620.4],
            )
        ]
        row = extract_metrics(SAMPLE_MANIFEST, analysis, recording_start_t=18590.4)
        self.assertAlmostEqual(row["first_detection_s"], 15.0, places=1)
        self.assertAlmostEqual(row["time_to_detection_s"], 0.0, places=1)

    def test_pre_attack_detection_does_not_create_negative_ttd(self):
        analysis = dict(SAMPLE_ANALYSIS)
        analysis["nist_findings"] = dict(SAMPLE_ANALYSIS["nist_findings"])
        analysis["nist_findings"]["risk_objects"] = [
            dict(
                SAMPLE_ANALYSIS["nist_findings"]["risk_objects"][0],
                timestamp_range=[0.0, 60.0],
            )
        ]
        row = extract_metrics(SAMPLE_MANIFEST, analysis)
        self.assertTrue(row["pre_attack_detection"])
        self.assertAlmostEqual(row["pre_attack_detection_s"], 0.0, places=1)
        self.assertAlmostEqual(row["first_detection_s"], 15.0, places=1)
        self.assertAlmostEqual(row["time_to_detection_s"], 0.0, places=1)

    def test_pre_attack_only_detection_has_no_ttd(self):
        analysis = dict(SAMPLE_ANALYSIS)
        analysis["nist_findings"] = dict(SAMPLE_ANALYSIS["nist_findings"])
        analysis["nist_findings"]["risk_objects"] = [
            dict(
                SAMPLE_ANALYSIS["nist_findings"]["risk_objects"][0],
                timestamp_range=[0.0, 5.0],
            )
        ]
        row = extract_metrics(SAMPLE_MANIFEST, analysis)
        self.assertTrue(row["pre_attack_detection"])
        self.assertAlmostEqual(row["pre_attack_detection_s"], 0.0, places=1)
        self.assertIsNone(row["time_to_detection_s"])

    def test_risk_fields_populated(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        self.assertEqual(row["worst_risk_level"], "high")
        self.assertEqual(row["total_findings"], 1)
        self.assertAlmostEqual(row["confidence"], 0.85, places=2)
        self.assertAlmostEqual(row["completeness"], 0.9, places=2)

    def test_frame_metrics(self):
        row = extract_metrics(SAMPLE_MANIFEST, SAMPLE_ANALYSIS)
        self.assertEqual(row["frame_count"], 1200)
        self.assertEqual(row["anomaly_frames"], 45)
        self.assertAlmostEqual(row["anomaly_ratio"], 0.0375, places=4)

    def test_clean_run_not_detected(self):
        clean_manifest = dict(
            SAMPLE_MANIFEST,
            scenario_id="baseline_clean",
            attack_type="none",
            expected_attack_start_s=None,
            expected_attack_end_s=None,
            attack_request=None,
        )
        clean_analysis = dict(
            SAMPLE_ANALYSIS,
            risk="low",
            risk_score=0,
            analysis={"anomaly_frames": 0, "anomaly_ratio": 0.0, "timeline": [], "findings": []},
            nist_findings={
                "worst_risk_level": "low",
                "risk_objects": [],
                "nist_summary": {
                    "total_findings": 0,
                    "level_counts": {"low": 0, "moderate": 0, "high": 0, "critical": 0},
                    "avg_confidence": 0.0,
                    "session_completeness": 1.0,
                    "nist_methods": [],
                },
            },
        )
        row = extract_metrics(clean_manifest, clean_analysis)
        self.assertFalse(row["detected"])
        self.assertIsNone(row["first_detection_s"])
        self.assertIsNone(row["time_to_detection_s"])

    def test_errored_run_marked_excluded(self):
        bad_manifest = dict(SAMPLE_MANIFEST, errors=["Backend unreachable"])
        row = extract_metrics(bad_manifest, None)
        self.assertTrue(row["excluded"])
        self.assertIn("Backend unreachable", row["exclusion_reason"])

    def test_no_analysis_returns_zero_defaults(self):
        row = extract_metrics(SAMPLE_MANIFEST, None)
        self.assertEqual(row["frame_count"], 0)
        self.assertEqual(row["total_findings"], 0)
        self.assertFalse(row["detected"])

    def test_anomaly_fallback_detection(self):
        """Runs with anomaly_frames > 0 are detected even without NIST timestamp."""
        analysis_no_ts = dict(
            SAMPLE_ANALYSIS,
            nist_findings={
                "worst_risk_level": "high",
                "risk_objects": [],  # no NIST objects
                "nist_summary": {
                    "total_findings": 0,
                    "avg_confidence": 0.0,
                    "session_completeness": 0.8,
                    "level_counts": {"low": 0, "moderate": 0, "high": 0, "critical": 0},
                    "nist_methods": [],
                },
            },
        )
        row = extract_metrics(SAMPLE_MANIFEST, analysis_no_ts)
        self.assertTrue(row["detected"])

    def test_clean_startup_blip_marked_false_positive_candidate(self):
        clean_manifest = dict(
            SAMPLE_MANIFEST,
            scenario_id="baseline_clean",
            attack_type="none",
            expected_attack_start_s=None,
            expected_attack_end_s=None,
            attack_request=None,
        )
        clean_analysis = dict(
            SAMPLE_ANALYSIS,
            risk="low",
            risk_score=30,
            analysis={
                "anomaly_frames": 6,
                "anomaly_ratio": 0.005,
                "timeline": [
                    {"start_frame": 1, "end_frame": 20, "frames": 20, "anomaly_frames": 6},
                    {"start_frame": 21, "end_frame": 1200, "frames": 1180, "anomaly_frames": 0},
                ],
                "findings": [],
            },
            nist_findings={
                "worst_risk_level": "critical",
                "risk_objects": [
                    {
                        "signal_type": "velocity_spoof",
                        "risk_level": "critical",
                        "timestamp_range": [0.2, 0.4],
                    }
                ],
                "nist_summary": {
                    "total_findings": 1,
                    "avg_confidence": 0.75,
                    "session_completeness": 1.0,
                },
            },
        )
        row = extract_metrics(clean_manifest, clean_analysis, startup_ignore_s=3.0)
        self.assertFalse(row["detected"])
        self.assertTrue(row["false_positive_candidate"])
        self.assertEqual(row["worst_risk_level"], "false_positive_candidate")
        self.assertEqual(row["raw_worst_risk_level"], "critical")
        self.assertEqual(row["anomaly_frames"], 0)
        self.assertEqual(row["raw_anomaly_frames"], 6)

    def test_clean_tiny_residual_after_startup_marked_false_positive_candidate(self):
        clean_manifest = dict(
            SAMPLE_MANIFEST,
            scenario_id="baseline_clean",
            attack_type="none",
            expected_attack_start_s=None,
            expected_attack_end_s=None,
            attack_request=None,
        )
        clean_analysis = dict(
            SAMPLE_ANALYSIS,
            risk="low",
            risk_score=30,
            analysis={
                "anomaly_frames": 5,
                "anomaly_ratio": 0.0042,
                "timeline": [
                    {"start_frame": 1, "end_frame": 60, "frames": 60, "anomaly_frames": 0},
                    {"start_frame": 61, "end_frame": 1200, "frames": 1140, "anomaly_frames": 5},
                ],
                "findings": [],
            },
            nist_findings={
                "worst_risk_level": "critical",
                "risk_objects": [
                    {
                        "signal_type": "velocity_spoof",
                        "risk_level": "critical",
                        "timestamp_range": [5.0, 5.2],
                    }
                ],
                "nist_summary": {
                    "total_findings": 1,
                    "avg_confidence": 0.75,
                    "session_completeness": 1.0,
                },
            },
        )
        row = extract_metrics(
            clean_manifest,
            clean_analysis,
            startup_ignore_s=3.0,
            baseline_fp_max_ratio=0.01,
        )
        self.assertFalse(row["detected"])
        self.assertTrue(row["false_positive_candidate"])
        self.assertEqual(row["worst_risk_level"], "false_positive_candidate")


# ── Object filter helpers ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_relevant_objects_matches_attack_type(self):
        objs = [
            {"signal_type": "velocity_spoof", "id": "a"},
            {"signal_type": "false_brake", "id": "b"},
            {"signal_type": "velocity_spoof_live", "id": "c"},
        ]
        rel = _relevant_objects(objs, "velocity_spoof")
        self.assertEqual({o["id"] for o in rel}, {"a", "c"})

    def test_relevant_objects_none_returns_all(self):
        objs = [{"signal_type": "velocity_spoof"}, {"signal_type": "false_brake"}]
        self.assertEqual(len(_relevant_objects(objs, "none")), 2)

    def test_timestamp_starts_extracts_first_value(self):
        objs = [
            {"timestamp_range": [5.5, 20.0]},
            {"timestamp_range": [12.0, 25.0]},
            {"timestamp_range": None},
            {"timestamp_range": []},
        ]
        ts = _timestamp_starts(objs)
        self.assertIn(5.5, ts)
        self.assertIn(12.0, ts)
        self.assertEqual(len(ts), 2)


# ── EventLog and file writing ─────────────────────────────────────────────────

class TestEventLog(unittest.TestCase):

    def test_events_written_to_csv(self):
        with _workspace_tempdir() as td:
            evlog = EventLog()
            evlog.mark_start()
            evlog.add("recording_start", "run_id=test-001")
            evlog.add("warmup_start", "15.0s")
            evlog.add("attack_trigger", "type=false_brake")
            evlog.add("recording_stop")

            out = Path(td) / "events.csv"
            evlog.write_csv(out)

            self.assertTrue(out.exists())
            with open(out) as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["event"], "recording_start")
            self.assertEqual(rows[0]["detail"], "run_id=test-001")
            self.assertEqual(rows[2]["event"], "attack_trigger")

    def test_t_s_is_monotonically_non_decreasing(self):
        with _workspace_tempdir() as td:
            evlog = EventLog()
            evlog.mark_start()
            evlog.add("a")
            evlog.add("b")
            evlog.add("c")
            out = Path(td) / "events.csv"
            evlog.write_csv(out)
            with open(out) as f:
                rows = list(csv.DictReader(f))
            ts = [float(r["t_s"]) for r in rows]
            for a, b in zip(ts, ts[1:]):
                self.assertGreaterEqual(b, a)

    def test_csv_headers_correct(self):
        with _workspace_tempdir() as td:
            evlog = EventLog()
            evlog.mark_start()
            evlog.add("init")
            out = Path(td) / "events.csv"
            evlog.write_csv(out)
            with open(out) as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
            self.assertEqual(headers, ["timestamp_iso", "t_s", "event", "detail"])


# ── Manifest roundtrip ────────────────────────────────────────────────────────

class TestManifestIO(unittest.TestCase):

    def test_manifest_roundtrip(self):
        with _workspace_tempdir() as td:
            p = Path(td) / "manifest.json"
            p.write_text(json.dumps(SAMPLE_MANIFEST, indent=2))
            loaded = json.loads(p.read_text())
            self.assertEqual(loaded["campaign_id"], "test_campaign")
            self.assertEqual(loaded["run_id"], "run-abc-0001")
            self.assertEqual(loaded["errors"], [])

    def test_manifest_preserves_null_fields(self):
        m = dict(SAMPLE_MANIFEST, attack_type=None, expected_attack_start_s=None)
        with _workspace_tempdir() as td:
            p = Path(td) / "manifest.json"
            p.write_text(json.dumps(m, indent=2, default=str))
            loaded = json.loads(p.read_text())
            self.assertIsNone(loaded["attack_type"])
            self.assertIsNone(loaded["expected_attack_start_s"])


# ── Randomization helpers ─────────────────────────────────────────────────────

class TestMakeRepSeed(unittest.TestCase):

    def test_same_inputs_produce_same_seed(self):
        s1 = _make_rep_seed(1337, "scenario_a", 1)
        s2 = _make_rep_seed(1337, "scenario_a", 1)
        self.assertEqual(s1, s2)

    def test_different_repetition_produces_different_seed(self):
        self.assertNotEqual(
            _make_rep_seed(1337, "scenario_a", 1),
            _make_rep_seed(1337, "scenario_a", 2),
        )

    def test_different_scenario_produces_different_seed(self):
        self.assertNotEqual(
            _make_rep_seed(1337, "scenario_a", 1),
            _make_rep_seed(1337, "scenario_b", 1),
        )

    def test_different_campaign_seed_produces_different_seed(self):
        self.assertNotEqual(
            _make_rep_seed(1337, "scenario_a", 1),
            _make_rep_seed(9999, "scenario_a", 1),
        )

    def test_result_is_non_negative_integer(self):
        seed = _make_rep_seed(0, "x", 0)
        self.assertIsInstance(seed, int)
        self.assertGreaterEqual(seed, 0)


class TestResolveCampaignSeed(unittest.TestCase):

    def test_cli_seed_takes_priority_over_yaml(self):
        cfg = {"random_seed": 999}
        self.assertEqual(_resolve_campaign_seed(cfg, cli_seed=42), 42)

    def test_yaml_seed_used_when_no_cli_seed(self):
        cfg = {"random_seed": 1337}
        self.assertEqual(_resolve_campaign_seed(cfg, cli_seed=None), 1337)

    def test_generated_seed_when_neither_provided(self):
        seed = _resolve_campaign_seed({}, cli_seed=None)
        self.assertIsInstance(seed, int)
        self.assertGreaterEqual(seed, 0)


class TestValidateRandomizeBlock(unittest.TestCase):

    def test_valid_block_passes(self):
        attack = {
            "type": "velocity_spoof",
            "randomize": {
                "delay_s": {"min": 5, "max": 25},
                "duration_s": {"min": 5, "max": 20},
            },
        }
        _validate_randomize_block("sc", attack)  # must not raise

    def test_no_randomize_key_is_noop(self):
        _validate_randomize_block("sc", {"type": "false_brake", "duration_s": 8})

    def test_unsupported_field_raises(self):
        attack = {"randomize": {"laser_power": {"min": 1, "max": 10}}}
        with self.assertRaises(ValueError, msg="Unknown field should raise"):
            _validate_randomize_block("sc", attack)

    def test_min_greater_than_max_raises(self):
        attack = {"randomize": {"delay_s": {"min": 30, "max": 5}}}
        with self.assertRaises(ValueError):
            _validate_randomize_block("sc", attack)

    def test_duration_s_must_be_strictly_positive(self):
        attack = {"randomize": {"duration_s": {"min": 0, "max": 10}}}
        with self.assertRaises(ValueError, msg="duration_s min=0 must reject (exclusive)"):
            _validate_randomize_block("sc", attack)

    def test_delay_s_zero_min_is_allowed(self):
        attack = {"randomize": {"delay_s": {"min": 0, "max": 10}}}
        _validate_randomize_block("sc", attack)  # must not raise

    def test_speed_mps_out_of_bounds_raises(self):
        attack = {"randomize": {"speed_mps": {"min": -25, "max": 0}}}
        with self.assertRaises(ValueError):
            _validate_randomize_block("sc", attack)

    def test_missing_min_or_max_raises(self):
        attack = {"randomize": {"delay_s": {"min": 5}}}
        with self.assertRaises(ValueError):
            _validate_randomize_block("sc", attack)

    def test_non_numeric_bounds_raises(self):
        attack = {"randomize": {"delay_s": {"min": "five", "max": 10}}}
        with self.assertRaises(ValueError):
            _validate_randomize_block("sc", attack)


class TestResolveAttackParams(unittest.TestCase):

    def _rng(self, seed: int = 0) -> random.Random:
        return random.Random(seed)

    def test_no_randomize_returns_cfg_unchanged(self):
        cfg = {"type": "false_brake", "duration_s": 8, "delay_s": 0}
        resolved, params = _resolve_attack_params(cfg, self._rng())
        self.assertEqual(resolved, cfg)
        self.assertEqual(params, {})

    def test_randomize_block_stripped_from_resolved(self):
        cfg = {
            "type": "velocity_spoof",
            "speed_mps": 0.15,
            "randomize": {"delay_s": {"min": 5, "max": 25}},
        }
        resolved, _ = _resolve_attack_params(cfg, self._rng())
        self.assertNotIn("randomize", resolved)

    def test_delay_within_range(self):
        cfg = {"randomize": {"delay_s": {"min": 5, "max": 25}}}
        for seed in range(20):
            resolved, params = _resolve_attack_params(cfg, self._rng(seed))
            v = params["delay_s"]
            self.assertGreaterEqual(v, 5.0)
            self.assertLessEqual(v, 25.0)

    def test_duration_within_range(self):
        cfg = {"randomize": {"duration_s": {"min": 5, "max": 20}}}
        for seed in range(20):
            resolved, params = _resolve_attack_params(cfg, self._rng(seed))
            v = params["duration_s"]
            self.assertGreater(v, 0.0)
            self.assertGreaterEqual(v, 5.0)
            self.assertLessEqual(v, 20.0)

    def test_resolved_value_written_into_config(self):
        cfg = {"type": "velocity_spoof", "randomize": {"delay_s": {"min": 10, "max": 10}}}
        resolved, params = _resolve_attack_params(cfg, self._rng())
        self.assertAlmostEqual(resolved["delay_s"], 10.0, places=3)
        self.assertAlmostEqual(params["delay_s"], 10.0, places=3)

    def test_seed_reproducibility(self):
        cfg = {"randomize": {"delay_s": {"min": 0, "max": 30}, "duration_s": {"min": 5, "max": 60}}}
        r1, p1 = _resolve_attack_params(cfg, self._rng(42))
        r2, p2 = _resolve_attack_params(cfg, self._rng(42))
        self.assertEqual(p1, p2)
        self.assertEqual(r1, r2)

    def test_different_seeds_produce_different_values(self):
        cfg = {"randomize": {"delay_s": {"min": 0, "max": 1000}}}
        _, p1 = _resolve_attack_params(cfg, self._rng(1))
        _, p2 = _resolve_attack_params(cfg, self._rng(2))
        self.assertNotAlmostEqual(p1["delay_s"], p2["delay_s"], places=1)


class TestRandomizationEndToEnd(unittest.TestCase):
    """Config-level validation catches bad randomize blocks."""

    def _cfg_with_attack(self, attack: dict) -> dict:
        return {
            "campaign_id": "test",
            "scenarios": [{"id": "s", "label": "L", "attack": attack}],
        }

    def test_valid_randomized_scenario_passes_validation(self):
        attack = {
            "type": "velocity_spoof",
            "mode": "static",
            "speed_mps": 0.15,
            "target_robot": "Fridjof",
            "randomize": {
                "delay_s": {"min": 5, "max": 25},
                "duration_s": {"min": 5, "max": 20},
            },
        }
        _validate_config(self._cfg_with_attack(attack))

    def test_invalid_randomize_propagates_through_validate_config(self):
        attack = {
            "type": "false_brake",
            "randomize": {"laser_beam": {"min": 1, "max": 5}},
        }
        with self.assertRaises(ValueError):
            _validate_config(self._cfg_with_attack(attack))

    def test_fixed_scenario_params_unchanged_by_resolve(self):
        cfg = {
            "type": "velocity_spoof",
            "mode": "static",
            "speed_mps": 0.15,
            "delay_s": 0,
            "duration_s": 15,
            "target_robot": "Fridjof",
        }
        resolved, params = _resolve_attack_params(cfg, random.Random(0))
        self.assertEqual(params, {})
        self.assertEqual(resolved["speed_mps"], 0.15)
        self.assertEqual(resolved["delay_s"], 0)
        self.assertEqual(resolved["duration_s"], 15)

    def test_rep_seed_determinism_across_calls(self):
        s1 = _make_rep_seed(1337, "velocity_spoof_static_low_randomized", 3)
        s2 = _make_rep_seed(1337, "velocity_spoof_static_low_randomized", 3)
        self.assertEqual(s1, s2)

    def test_full_pipeline_resolved_cfg_used_by_build_request(self):
        """Resolved config (with concrete delay/duration) feeds _build_attack_request."""
        cfg = {
            "type": "velocity_spoof",
            "mode": "static",
            "speed_mps": 0.15,
            "target_robot": "Fridjof",
            "randomize": {
                "delay_s": {"min": 5, "max": 25},
                "duration_s": {"min": 5, "max": 20},
            },
        }
        rng = random.Random(_make_rep_seed(1337, "velocity_spoof_static_low_randomized", 1))
        resolved, params = _resolve_attack_params(cfg, rng)

        attack_type, body = _build_attack_request(resolved)
        self.assertEqual(attack_type, "velocity_spoof")
        self.assertAlmostEqual(body["delay_s"], params["delay_s"], places=3)
        self.assertAlmostEqual(body["duration_s"], params["duration_s"], places=3)
        self.assertEqual(body["follower_robot"], "Fridjof")
        self.assertEqual(body["target_robot"], "Bjarte")
        self.assertGreaterEqual(body["delay_s"], 5.0)
        self.assertLessEqual(body["delay_s"], 25.0)
        self.assertGreaterEqual(body["duration_s"], 5.0)
        self.assertLessEqual(body["duration_s"], 20.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
