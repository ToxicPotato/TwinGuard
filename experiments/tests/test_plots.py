#!/usr/bin/env python3
"""
Unit tests for experiments/plots.py randomized trial plot helpers.

Tests cover:
  - _parse_bool: robust boolean parsing for CSV string values
  - _is_excluded: row filtering from CSV string values
  - _is_no_attack / _outcome_category: negative-control semantics
  - _sorted_strategies: ordering follows _STRATEGY_ORDER then alphabetical
  - _bucket_by_duration_interval: integer-second bucketing helper
  - no_attack semantics in _write_randomized_summary_json:
      detection_rate excludes no_attack denominator
      no_attack FP counted separately from missed attacks
  - plot_trial_outcomes: 4-category outcome bar chart (F1)
  - plot_detection_timeline: single-axis timeline (F2)
  - plot_duration_detection_rate: duration vs detection-rate line chart (F3)
  - plot_detection_by_strategy: bar chart, attack trials only (F4)
  - plot_undetected_impact: undetected impact rate by strategy (F5)
  - plot_false_positive_summary: no_attack false-positive bar (F6)
  - plot_strategy_outcome_stack: stacked strategy outcomes (F7)
  - plot_risk_vs_detection: risk-assigned attacks vs detections (F8)
  - plot_detection_by_attack_category: attack-family detection rate (F9)
  - plot_strategy_risk_map: detection rate vs harmful-miss rate (F10)
  - plot_detection_rate_sensitivity: detection-rate comparison groups (F11)
  - plot_ttd_ecdf: cumulative time-to-detection curve (F12)
  - _write_randomized_summary_json: detection rate, by_strategy, no_attack stats

No live backend, no matplotlib display required.

Run from the repo root:
  python -m pytest experiments/tests/test_plots.py -v
or:
  python experiments/tests/test_plots.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")

from plots import (  # noqa: E402
    _bucket_by_duration_interval,
    _is_excluded,
    _is_no_attack,
    _outcome_category,
    _parse_bool,
    _sorted_strategies,
    _write_randomized_summary_json,
    plot_detection_by_strategy,
    plot_detection_timeline,
    plot_duration_detection_rate,
    plot_false_positive_summary,
    plot_detection_by_attack_category,
    plot_detection_rate_sensitivity,
    plot_risk_vs_detection,
    plot_strategy_outcome_stack,
    plot_strategy_risk_map,
    plot_trial_outcomes,
    plot_ttd_ecdf,
    plot_undetected_impact,
    _STRATEGY_ORDER,
)


def _row(
    *,
    attack_strategy: str = "constant",
    attack_family: str = "velocity_spoof",
    detected: str = "False",
    excluded: str = "False",
    exclusion_reason: str = "",
    worst_risk_level: str = "low",
    attack_difficulty: str = "medium",
    risk_score: str = "",
    speed_mps: str = "0.8",
    speed_start: str = "",
    speed_end: str = "",
    duration_s: str = "10",
    delay_s: str = "5",
    time_to_detection_s: str = "",
    trial_number: str = "",
    out_of_formation: str = "False",
    anomaly_ratio: str = "",
    undetected_physical_impact: str = "False",
) -> dict:
    return {
        "attack_strategy": attack_strategy,
        "attack_family": attack_family,
        "detected": detected,
        "excluded": excluded,
        "exclusion_reason": exclusion_reason,
        "worst_risk_level": worst_risk_level,
        "attack_difficulty": attack_difficulty,
        "risk_score": risk_score,
        "speed_mps": speed_mps,
        "speed_start": speed_start,
        "speed_end": speed_end,
        "duration_s": duration_s,
        "delay_s": delay_s,
        "time_to_detection_s": time_to_detection_s,
        "trial_number": trial_number,
        "out_of_formation": out_of_formation,
        "anomaly_ratio": anomaly_ratio,
        "undetected_physical_impact": undetected_physical_impact,
    }


class TestParseBool(unittest.TestCase):
    def test_true_string(self):
        self.assertTrue(_parse_bool("True"))

    def test_true_lowercase(self):
        self.assertTrue(_parse_bool("true"))

    def test_true_int_string(self):
        self.assertTrue(_parse_bool("1"))

    def test_true_yes(self):
        self.assertTrue(_parse_bool("yes"))

    def test_false_string(self):
        self.assertFalse(_parse_bool("False"))

    def test_false_lowercase(self):
        self.assertFalse(_parse_bool("false"))

    def test_false_zero(self):
        self.assertFalse(_parse_bool("0"))

    def test_false_empty(self):
        self.assertFalse(_parse_bool(""))

    def test_false_none_string(self):
        self.assertFalse(_parse_bool("None"))

    def test_true_bool_value(self):
        self.assertTrue(_parse_bool(True))

    def test_false_bool_value(self):
        self.assertFalse(_parse_bool(False))

    def test_true_int(self):
        self.assertTrue(_parse_bool(1))

    def test_false_int(self):
        self.assertFalse(_parse_bool(0))


class TestIsExcluded(unittest.TestCase):
    def test_excluded_true_string(self):
        self.assertTrue(_is_excluded({"excluded": "True"}))

    def test_excluded_false_string(self):
        self.assertFalse(_is_excluded({"excluded": "False"}))

    def test_excluded_1(self):
        self.assertTrue(_is_excluded({"excluded": "1"}))

    def test_excluded_0(self):
        self.assertFalse(_is_excluded({"excluded": "0"}))

    def test_excluded_missing_key(self):
        self.assertFalse(_is_excluded({}))

    def test_excluded_yes(self):
        self.assertTrue(_is_excluded({"excluded": "yes"}))

    def test_excluded_empty(self):
        self.assertFalse(_is_excluded({"excluded": ""}))


class TestIsNoAttack(unittest.TestCase):
    def test_no_attack_family(self):
        self.assertTrue(_is_no_attack(_row(attack_family="no_attack")))

    def test_no_attack_uppercase(self):
        self.assertTrue(_is_no_attack({"attack_family": "NO_ATTACK"}))

    def test_velocity_spoof_is_not_no_attack(self):
        self.assertFalse(_is_no_attack(_row(attack_family="velocity_spoof")))

    def test_false_brake_is_not_no_attack(self):
        self.assertFalse(_is_no_attack(_row(attack_family="false_brake")))

    def test_empty_family_is_not_no_attack(self):
        self.assertFalse(_is_no_attack(_row(attack_family="")))

    def test_missing_family_key(self):
        self.assertFalse(_is_no_attack({}))


class TestOutcomeCategory(unittest.TestCase):
    def test_detected_attack(self):
        r = _row(attack_family="velocity_spoof", detected="True")
        self.assertEqual(_outcome_category(r), "detected_attack")

    def test_missed_attack(self):
        r = _row(attack_family="velocity_spoof", detected="False")
        self.assertEqual(_outcome_category(r), "missed_attack")

    def test_false_positive(self):
        r = _row(attack_family="no_attack", detected="True")
        self.assertEqual(_outcome_category(r), "false_positive")

    def test_clean_no_attack(self):
        r = _row(attack_family="no_attack", detected="False")
        self.assertEqual(_outcome_category(r), "clean_no_attack")

    def test_false_brake_detected_is_detected_attack(self):
        r = _row(attack_family="false_brake", detected="True")
        self.assertEqual(_outcome_category(r), "detected_attack")

    def test_four_categories_exhaustive(self):
        """Confirm every combination of (is_attack, detected) maps to distinct category."""
        cats = {
            _outcome_category(_row(attack_family="velocity_spoof", detected="True")),
            _outcome_category(_row(attack_family="velocity_spoof", detected="False")),
            _outcome_category(_row(attack_family="no_attack", detected="True")),
            _outcome_category(_row(attack_family="no_attack", detected="False")),
        }
        self.assertEqual(len(cats), 4)


class TestSortedStrategies(unittest.TestCase):
    def test_known_strategies_ordered_by_strategy_order(self):
        rows = [
            _row(attack_strategy="ramp"),
            _row(attack_strategy="constant"),
            _row(attack_strategy="dropout"),
        ]
        result = _sorted_strategies(rows)
        self.assertEqual(result.index("constant"), 0)
        self.assertEqual(result.index("ramp"), 1)
        self.assertEqual(result.index("dropout"), 2)

    def test_unknown_strategy_appended_alphabetically(self):
        rows = [
            _row(attack_strategy="constant"),
            _row(attack_strategy="zzz_custom"),
        ]
        result = _sorted_strategies(rows)
        self.assertEqual(result[0], "constant")
        self.assertIn("zzz_custom", result)

    def test_deduplicates_strategies(self):
        rows = [_row(attack_strategy="constant")] * 5
        result = _sorted_strategies(rows)
        self.assertEqual(result.count("constant"), 1)

    def test_empty_rows(self):
        result = _sorted_strategies([])
        self.assertEqual(result, [])


class TestBucketByDurationInterval(unittest.TestCase):
    def test_empty_input(self):
        labels, rates, counts = _bucket_by_duration_interval([], [])
        self.assertEqual(labels, [])
        self.assertEqual(rates, [])
        self.assertEqual(counts, [])

    def test_single_bucket_mixed_detection(self):
        labels, rates, counts = _bucket_by_duration_interval([2.7, 2.3], [1, 0])
        self.assertTrue(labels)
        self.assertAlmostEqual(rates[0], 50.0)
        self.assertEqual(counts[0], 2)

    def test_floor_creates_separate_buckets(self):
        # 2.9 → bucket 2; 3.0 → bucket 3
        labels, rates, counts = _bucket_by_duration_interval([2.9, 3.0], [1, 1])
        self.assertTrue(all("-" in label for label in labels))

    def test_returns_sorted_seconds(self):
        labels, rates, counts = _bucket_by_duration_interval([10.0, 2.0, 5.5], [1, 0, 1])
        self.assertEqual(sum(counts), 3)

    def test_100_percent_detection(self):
        labels, rates, counts = _bucket_by_duration_interval([5.0, 5.5, 5.9], [1, 1, 1])
        self.assertTrue(all(rate == 100.0 for rate in rates))

    def test_zero_percent_detection(self):
        labels, rates, counts = _bucket_by_duration_interval([5.0, 5.5, 5.9], [0, 0, 0])
        self.assertTrue(all(rate == 0.0 for rate in rates))

    def test_multiple_buckets_rates_and_counts(self):
        # bucket 1: 2/2 detected = 100%; bucket 5: 0/2 detected = 0%
        labels, rates, counts = _bucket_by_duration_interval(
            [1.0, 1.5, 5.0, 5.9], [1, 1, 0, 0]
        )
        self.assertGreaterEqual(len(labels), 2)
        self.assertEqual(sum(counts), 4)
        self.assertIn(100.0, rates)
        self.assertIn(0.0, rates)


class TestNoAttackSemantics(unittest.TestCase):
    """Verify no_attack trials are treated as negative controls throughout."""

    def _summary(self, rows, baseline_speed=1.0):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_randomized_summary_json(rows, out, ["png"], baseline_speed, "test")
            return json.loads((out / "randomized_plot_summary.json").read_text())

    def test_clean_no_attack_does_not_reduce_detection_rate(self):
        """A clean no_attack trial must NOT count as a missed attack."""
        rows = [
            _row(attack_family="velocity_spoof", detected="True"),
            _row(attack_family="velocity_spoof", detected="True"),
            _row(attack_family="no_attack", detected="False"),
        ]
        s = self._summary(rows)
        # 2 detected / 2 attack trials = 1.0
        self.assertAlmostEqual(s["detection_rate"], 1.0)
        self.assertEqual(s["attack_trials"], 2)

    def test_false_positive_not_counted_as_detected_attack(self):
        """A false positive on no_attack must NOT increment detected_count."""
        rows = [
            _row(attack_family="velocity_spoof", detected="False"),
            _row(attack_family="no_attack", detected="True"),
        ]
        s = self._summary(rows)
        self.assertEqual(s["detected_count"], 0)
        self.assertEqual(s["no_attack_fp_count"], 1)
        self.assertAlmostEqual(s["detection_rate"], 0.0)

    def test_no_attack_fp_rate_computed_correctly(self):
        rows = [
            _row(attack_family="no_attack", detected="True"),
            _row(attack_family="no_attack", detected="True"),
            _row(attack_family="no_attack", detected="False"),
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["no_attack_fp_rate"], 2 / 3, places=5)

    def test_no_attack_fp_rate_zero_when_all_clean(self):
        rows = [
            _row(attack_family="no_attack", detected="False"),
            _row(attack_family="no_attack", detected="False"),
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["no_attack_fp_rate"], 0.0)

    def test_no_attack_fp_rate_zero_when_no_no_attack_trials(self):
        rows = [_row(attack_family="velocity_spoof", detected="True")]
        s = self._summary(rows)
        self.assertAlmostEqual(s["no_attack_fp_rate"], 0.0)
        self.assertEqual(s["no_attack_trials"], 0)

    def test_attack_and_no_attack_trial_counts(self):
        rows = [
            _row(attack_family="velocity_spoof"),
            _row(attack_family="velocity_spoof"),
            _row(attack_family="no_attack"),
        ]
        s = self._summary(rows)
        self.assertEqual(s["attack_trials"], 2)
        self.assertEqual(s["no_attack_trials"], 1)

    def test_false_negative_rate_excludes_no_attack(self):
        rows = [
            _row(attack_family="velocity_spoof", detected="True"),
            _row(attack_family="velocity_spoof", detected="False"),
            _row(attack_family="velocity_spoof", detected="False"),
            _row(attack_family="no_attack", detected="False"),  # should not affect rate
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["false_negative_rate"], 2 / 3, places=5)

    def test_by_strategy_excludes_no_attack_rows(self):
        """by_strategy must be computed over attack trials only."""
        rows = [
            _row(attack_strategy="constant", attack_family="velocity_spoof",
                 detected="True"),
            _row(attack_strategy="constant", attack_family="no_attack",
                 detected="False"),
        ]
        s = self._summary(rows)
        # Only the velocity_spoof trial counts
        self.assertEqual(s["by_strategy"]["constant"]["total"], 1)
        self.assertAlmostEqual(s["by_strategy"]["constant"]["rate"], 1.0)

    def test_missed_count_excludes_clean_no_attack(self):
        rows = [
            _row(attack_family="velocity_spoof", detected="False"),
            _row(attack_family="no_attack", detected="False"),
        ]
        s = self._summary(rows)
        # Only the velocity_spoof undetected trial is a "miss"
        self.assertEqual(s["missed_count"], 1)


class TestDetectionRateByStrategy(unittest.TestCase):
    def _rates(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_randomized_summary_json(rows, out, ["png"], 1.0, "test")
            summary = json.loads((out / "randomized_plot_summary.json").read_text())
            return {s: d["rate"] for s, d in summary["by_strategy"].items()}

    def test_100_percent_detection(self):
        rows = [_row(attack_strategy="constant", detected="True") for _ in range(4)]
        rates = self._rates(rows)
        self.assertAlmostEqual(rates["constant"], 1.0)

    def test_zero_percent_detection(self):
        rows = [_row(attack_strategy="constant", detected="False") for _ in range(4)]
        rates = self._rates(rows)
        self.assertAlmostEqual(rates["constant"], 0.0)

    def test_mixed_detection_rate(self):
        rows = (
            [_row(attack_strategy="ramp", detected="True")] * 3
            + [_row(attack_strategy="ramp", detected="False")] * 1
        )
        rates = self._rates(rows)
        self.assertAlmostEqual(rates["ramp"], 0.75)

    def test_excluded_rows_not_counted_in_valid_denominator(self):
        rows = [
            _row(attack_strategy="constant", detected="True"),
            _row(attack_strategy="constant", detected="False"),
            _row(attack_strategy="constant", detected="True", excluded="True"),
        ]
        rates = self._rates(rows)
        # 1 detected / 2 valid = 0.5 (excluded row filtered out)
        self.assertAlmostEqual(rates["constant"], 0.5)

    def test_by_strategy_has_false_negative_rate(self):
        rows = [
            _row(attack_strategy="constant", detected="True"),
            _row(attack_strategy="constant", detected="False"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_randomized_summary_json(rows, out, ["png"], 1.0, "test")
            summary = json.loads((out / "randomized_plot_summary.json").read_text())
        entry = summary["by_strategy"]["constant"]
        self.assertIn("false_negative_rate", entry)
        self.assertAlmostEqual(entry["false_negative_rate"], 0.5)


class TestRiskCountsByStrategy(unittest.TestCase):
    def _risk_dist(self, rows, strategy):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_randomized_summary_json(rows, out, ["png"], 1.0, "test")
            summary = json.loads((out / "randomized_plot_summary.json").read_text())
            return summary["risk_level_distribution"]

    def test_risk_level_counted_correctly(self):
        rows = [
            _row(worst_risk_level="critical"),
            _row(worst_risk_level="high"),
            _row(worst_risk_level="low"),
            _row(worst_risk_level="critical"),
        ]
        dist = self._risk_dist(rows, "constant")
        self.assertEqual(dist["critical"], 2)
        self.assertEqual(dist["high"], 1)
        self.assertEqual(dist["low"], 1)
        self.assertEqual(dist["moderate"], 0)

    def test_excluded_rows_not_in_risk_dist(self):
        rows = [
            _row(worst_risk_level="critical"),
            _row(worst_risk_level="critical", excluded="True"),
        ]
        dist = self._risk_dist(rows, "constant")
        self.assertEqual(dist["critical"], 1)


class TestSummaryJsonAggregation(unittest.TestCase):
    def _summary(self, rows, baseline_speed=1.0):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_randomized_summary_json(rows, out, ["png"], baseline_speed, "test_exp")
            return json.loads((out / "randomized_plot_summary.json").read_text())

    def test_total_counts(self):
        rows = [
            _row(detected="True"),
            _row(detected="False"),
            _row(excluded="True"),
        ]
        s = self._summary(rows)
        self.assertEqual(s["total_trials"], 3)
        self.assertEqual(s["valid_trials"], 2)
        self.assertEqual(s["excluded_trials"], 1)
        self.assertEqual(s["detected_count"], 1)
        self.assertEqual(s["missed_count"], 1)

    def test_detection_rate(self):
        rows = [_row(detected="True")] * 3 + [_row(detected="False")] * 1
        s = self._summary(rows)
        self.assertAlmostEqual(s["detection_rate"], 0.75)

    def test_detection_rate_excludes_no_attack_denominator(self):
        rows = [
            _row(attack_family="velocity_spoof", detected="True"),
            _row(attack_family="velocity_spoof", detected="True"),
            _row(attack_family="no_attack", detected="False"),
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["detection_rate"], 1.0)

    def test_mean_ttd(self):
        rows = [
            _row(detected="True", time_to_detection_s="4.0"),
            _row(detected="True", time_to_detection_s="8.0"),
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["mean_time_to_detection_s"], 6.0)

    def test_median_ttd_odd(self):
        rows = [
            _row(detected="True", time_to_detection_s="1.0"),
            _row(detected="True", time_to_detection_s="3.0"),
            _row(detected="True", time_to_detection_s="9.0"),
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["median_time_to_detection_s"], 3.0)

    def test_median_ttd_even(self):
        rows = [
            _row(detected="True", time_to_detection_s="2.0"),
            _row(detected="True", time_to_detection_s="6.0"),
        ]
        s = self._summary(rows)
        self.assertAlmostEqual(s["median_time_to_detection_s"], 4.0)

    def test_no_detected_ttd_is_none(self):
        rows = [_row(detected="False")]
        s = self._summary(rows)
        self.assertIsNone(s["mean_time_to_detection_s"])
        self.assertIsNone(s["median_time_to_detection_s"])

    def test_by_attack_difficulty_hard(self):
        rows = [
            _row(attack_difficulty="hard", detected="True"),
            _row(attack_difficulty="hard", detected="True"),
            _row(attack_difficulty="hard", detected="False"),
        ]
        s = self._summary(rows)
        self.assertEqual(s["by_attack_difficulty"]["hard"]["total"], 3)
        self.assertEqual(s["by_attack_difficulty"]["hard"]["detected"], 2)
        self.assertAlmostEqual(s["by_attack_difficulty"]["hard"]["rate"], 2 / 3)

    def test_by_attack_difficulty_all_levels_present(self):
        s = self._summary([])
        for level in ("hard", "medium", "easy"):
            self.assertIn(level, s["by_attack_difficulty"])

    def test_figures_list_length(self):
        s = self._summary([])
        self.assertEqual(len(s["figures"]), 12)

    def test_figures_use_first_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_randomized_summary_json([], out, ["svg", "png"], 1.0, "x")
            s = json.loads((out / "randomized_plot_summary.json").read_text())
        for fig in s["figures"]:
            self.assertTrue(fig.endswith(".svg"), f"Expected .svg: {fig}")

    def test_figures_include_new_names(self):
        s = self._summary([])
        names = [f.rsplit(".", 1)[0] for f in s["figures"]]
        self.assertIn("f3_duration_detection_rate", names)
        self.assertIn("f4_detection_by_strategy", names)
        self.assertIn("f5_undetected_impact", names)
        self.assertIn("f6_false_positive_summary", names)
        self.assertIn("f7_strategy_outcome_stack", names)
        self.assertIn("f8_risk_vs_detection", names)
        self.assertIn("f9_detection_by_attack_category", names)
        self.assertIn("f10_strategy_risk_map", names)
        self.assertIn("f11_detection_rate_sensitivity", names)
        self.assertIn("f12_ttd_ecdf", names)

    def test_baseline_speed_recorded(self):
        s = self._summary([], baseline_speed=2.5)
        self.assertAlmostEqual(s["baseline_speed_mps"], 2.5)

    def test_experiment_id_recorded(self):
        s = self._summary([])
        self.assertEqual(s["experiment_id"], "test_exp")

    def test_by_strategy_fields_present(self):
        rows = [_row(attack_strategy="constant", detected="True", time_to_detection_s="5.0")]
        s = self._summary(rows)
        self.assertIn("constant", s["by_strategy"])
        entry = s["by_strategy"]["constant"]
        for key in ("total", "detected", "missed", "rate", "false_negative_rate", "mean_ttd_s"):
            self.assertIn(key, entry)

    def test_risk_dist_all_levels_present(self):
        s = self._summary([])
        for level in ("low", "moderate", "high", "critical"):
            self.assertIn(level, s["risk_level_distribution"])

    def test_empty_rows_no_crash(self):
        s = self._summary([])
        self.assertEqual(s["total_trials"], 0)
        self.assertEqual(s["valid_trials"], 0)
        self.assertEqual(s["detection_rate"], 0.0)

    def test_no_attack_fp_fields_present(self):
        s = self._summary([])
        self.assertIn("no_attack_fp_count", s)
        self.assertIn("no_attack_fp_rate", s)
        self.assertIn("no_attack_trials", s)


class TestPlotFunctionsSmoke(unittest.TestCase):
    """Smoke tests -- verify each analytical plot function creates the output file."""

    # Mix of attack trials (velocity_spoof + false_brake), no_attack trials, and excluded
    _ROWS = [
        _row(attack_strategy="constant", attack_family="velocity_spoof",
             detected="True", attack_difficulty="easy",
             worst_risk_level="high", risk_score="75.0", duration_s="8",
             time_to_detection_s="3.0", trial_number="1", anomaly_ratio="0.4"),
        _row(attack_strategy="constant", attack_family="velocity_spoof",
             detected="False", attack_difficulty="medium",
             worst_risk_level="moderate", risk_score="30.0", duration_s="12",
             trial_number="2", anomaly_ratio="0.1",
             undetected_physical_impact="True"),
        _row(attack_strategy="ramp", attack_family="velocity_spoof",
             detected="True", attack_difficulty="hard",
             speed_mps="", speed_start="0.8", speed_end="0.5",
             worst_risk_level="critical", risk_score="90.0", duration_s="15",
             time_to_detection_s="5.0", trial_number="3", anomaly_ratio="0.7"),
        _row(attack_strategy="dropout", attack_family="velocity_spoof",
             detected="False", attack_difficulty="easy",
             speed_mps="0.0", worst_risk_level="low", risk_score="10.0",
             duration_s="6", trial_number="4", anomaly_ratio="0.05",
             undetected_physical_impact="False"),
        _row(attack_strategy="burst", attack_family="false_brake",
             detected="True", attack_difficulty="medium",
             worst_risk_level="critical", risk_score="95.0",
             duration_s="4", time_to_detection_s="2.0", trial_number="5",
             anomaly_ratio="0.9"),
        _row(attack_strategy="near_threshold", attack_family="velocity_spoof",
             detected="False", attack_difficulty="hard",
             speed_mps="0.95", worst_risk_level="low", risk_score="15.0",
             duration_s="20", trial_number="6", anomaly_ratio="0.02",
             undetected_physical_impact="True"),
        # Negative controls
        _row(attack_strategy="constant", attack_family="no_attack",
             detected="False", worst_risk_level="low", risk_score="5.0",
             trial_number="7"),
        _row(attack_strategy="constant", attack_family="no_attack",
             detected="True", worst_risk_level="moderate", risk_score="35.0",
             trial_number="8"),
        # Excluded
        _row(excluded="True", trial_number="9"),
    ]

    def setUp(self):
        import matplotlib.pyplot as plt
        plt.rcParams.update({
            "figure.facecolor": "#1a1a2e",
            "axes.facecolor": "#16213e",
            "text.color": "#cccccc",
        })

    def _tmpdir(self):
        self._tmp = tempfile.mkdtemp()
        return Path(self._tmp)

    # F1
    def test_f1_trial_outcomes_creates_file(self):
        out = self._tmpdir()
        plot_trial_outcomes(self._ROWS, out, ["png"])
        self.assertTrue((out / "f1_trial_outcomes.png").exists())

    def test_f1_trial_outcomes_empty_rows(self):
        out = self._tmpdir()
        plot_trial_outcomes([], out, ["png"])
        self.assertTrue((out / "f1_trial_outcomes.png").exists())

    # F2
    def test_f2_detection_timeline_creates_file(self):
        out = self._tmpdir()
        plot_detection_timeline(self._ROWS, out, ["png"])
        self.assertTrue((out / "f2_detection_timeline.png").exists())

    def test_f2_detection_timeline_empty_rows(self):
        out = self._tmpdir()
        plot_detection_timeline([], out, ["png"])
        self.assertTrue((out / "f2_detection_timeline.png").exists())

    def test_f2_detection_timeline_attack_only_rows(self):
        """Timeline with no no_attack trials should not crash."""
        rows = [r for r in self._ROWS
                if str(r.get("attack_family", "")) != "no_attack"
                and not _is_excluded(r)]
        out = self._tmpdir()
        plot_detection_timeline(rows, out, ["png"])
        self.assertTrue((out / "f2_detection_timeline.png").exists())

    def test_f2_detection_timeline_no_attack_only(self):
        """Timeline with ONLY no_attack trials -- rate line absent but no crash."""
        rows = [_row(attack_family="no_attack", detected="False", trial_number="1"),
                _row(attack_family="no_attack", detected="True", trial_number="2")]
        out = self._tmpdir()
        plot_detection_timeline(rows, out, ["png"])
        self.assertTrue((out / "f2_detection_timeline.png").exists())

    # F3
    def test_f3_duration_detection_rate_creates_file(self):
        out = self._tmpdir()
        plot_duration_detection_rate(self._ROWS, out, ["png"])
        self.assertTrue((out / "f3_duration_detection_rate.png").exists())

    def test_f3_duration_detection_rate_empty_rows(self):
        out = self._tmpdir()
        plot_duration_detection_rate([], out, ["png"])
        self.assertTrue((out / "f3_duration_detection_rate.png").exists())

    def test_f3_duration_detection_rate_excludes_no_attack(self):
        """Only attack trials should appear; no_attack rows excluded, no crash."""
        rows = [
            _row(attack_family="velocity_spoof", detected="True", duration_s="5"),
            _row(attack_family="velocity_spoof", detected="False", duration_s="15"),
            _row(attack_family="no_attack", detected="False", duration_s="10"),
        ]
        out = self._tmpdir()
        plot_duration_detection_rate(rows, out, ["png"])
        self.assertTrue((out / "f3_duration_detection_rate.png").exists())

    # F4
    def test_f4_detection_by_strategy_creates_file(self):
        out = self._tmpdir()
        plot_detection_by_strategy(self._ROWS, out, ["png"])
        self.assertTrue((out / "f4_detection_by_strategy.png").exists())

    def test_f4_detection_by_strategy_empty_rows(self):
        out = self._tmpdir()
        plot_detection_by_strategy([], out, ["png"])
        self.assertTrue((out / "f4_detection_by_strategy.png").exists())

    def test_f4_detection_by_strategy_only_no_attack_rows(self):
        """Only no_attack rows → placeholder, no crash."""
        rows = [_row(attack_family="no_attack", detected="False")]
        out = self._tmpdir()
        plot_detection_by_strategy(rows, out, ["png"])
        self.assertTrue((out / "f4_detection_by_strategy.png").exists())

    # F5
    def test_f5_undetected_impact_creates_file(self):
        out = self._tmpdir()
        plot_undetected_impact(self._ROWS, out, ["png"])
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    def test_f5_undetected_impact_empty_rows(self):
        out = self._tmpdir()
        plot_undetected_impact([], out, ["png"])
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    def test_f5_undetected_impact_all_detected(self):
        """No missed attacks → placeholder file created at correct stem."""
        rows = [_row(attack_family="velocity_spoof", detected="True",
                     attack_strategy="constant")] * 3
        out = self._tmpdir()
        plot_undetected_impact(rows, out, ["png"])
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    # F6
    def test_f6_false_positive_summary_creates_file(self):
        out = self._tmpdir()
        plot_false_positive_summary(self._ROWS, out, ["png"])
        self.assertTrue((out / "f6_false_positive_summary.png").exists())

    def test_f6_false_positive_summary_empty_rows(self):
        out = self._tmpdir()
        plot_false_positive_summary([], out, ["png"])
        self.assertTrue((out / "f6_false_positive_summary.png").exists())

    def test_f6_false_positive_summary_no_no_attack_rows(self):
        """No no_attack rows → placeholder, no crash."""
        rows = [_row(attack_family="velocity_spoof", detected="True")]
        out = self._tmpdir()
        plot_false_positive_summary(rows, out, ["png"])
        self.assertTrue((out / "f6_false_positive_summary.png").exists())

    def test_f6_false_positive_summary_all_fp(self):
        """All no_attack trials trigger alerts → FP rate = 100%, file created."""
        rows = [_row(attack_family="no_attack", detected="True") for _ in range(3)]
        out = self._tmpdir()
        plot_false_positive_summary(rows, out, ["png"])
        self.assertTrue((out / "f6_false_positive_summary.png").exists())

    def test_all_excluded_writes_placeholder_for_every_function(self):
        """Every function must write a file even when all rows are excluded."""
        rows = [_row(excluded="True") for _ in range(3)]
        funcs_and_stems = [
            (plot_detection_timeline,        "f2_detection_timeline"),
            (plot_duration_detection_rate,   "f3_duration_detection_rate"),
            (plot_detection_by_strategy,     "f4_detection_by_strategy"),
            (plot_undetected_impact,         "f5_undetected_impact"),
            (plot_false_positive_summary,    "f6_false_positive_summary"),
            (plot_strategy_outcome_stack,    "f7_strategy_outcome_stack"),
            (plot_risk_vs_detection,         "f8_risk_vs_detection"),
            (plot_detection_by_attack_category, "f9_detection_by_attack_category"),
            (plot_strategy_risk_map,         "f10_strategy_risk_map"),
            (plot_detection_rate_sensitivity, "f11_detection_rate_sensitivity"),
            (plot_ttd_ecdf,                  "f12_ttd_ecdf"),
        ]
        for func, stem in funcs_and_stems:
            out = Path(tempfile.mkdtemp())
            func(rows, out, ["png"])
            self.assertTrue(
                (out / f"{stem}.png").exists(),
                f"{func.__name__} did not write {stem}.png with all-excluded rows",
            )


class TestUndetectedImpactRate(unittest.TestCase):
    """Verify plot_undetected_impact uses rate semantics with correct denominator."""

    def _run(self, rows):
        out = Path(tempfile.mkdtemp())
        plot_undetected_impact(rows, out, ["png"])
        return out

    def test_strategy_with_impact_and_misses_creates_file(self):
        """2 missed, 1 with impact → 50% rate; file created."""
        rows = [
            _row(attack_strategy="constant", detected="False",
                 undetected_physical_impact="True"),
            _row(attack_strategy="constant", detected="False",
                 undetected_physical_impact="False"),
        ]
        out = self._run(rows)
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    def test_strategy_with_misses_but_no_impact_creates_file(self):
        """All missed attacks have no impact → 0% rate; file still created."""
        rows = [
            _row(attack_strategy="ramp", detected="False",
                 undetected_physical_impact="False"),
            _row(attack_strategy="ramp", detected="False",
                 undetected_physical_impact="False"),
            _row(attack_strategy="ramp", detected="False",
                 undetected_physical_impact="False"),
        ]
        out = self._run(rows)
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    def test_no_missed_attacks_produces_placeholder(self):
        """All-detected rows → no missed attacks → placeholder at correct stem."""
        rows = [
            _row(attack_strategy="constant", detected="True",
                 undetected_physical_impact="False"),
        ] * 3
        out = self._run(rows)
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    def test_no_attack_rows_excluded(self):
        """no_attack rows must not enter the missed-attack denominator."""
        rows = [
            # This no_attack row must not be counted as a missed attack
            _row(attack_family="no_attack", detected="False",
                 undetected_physical_impact="True"),
            # One real missed attack trial
            _row(attack_strategy="constant", detected="False",
                 undetected_physical_impact="True"),
        ]
        out = self._run(rows)
        # Real missed attack present → a bar should be drawn, not a placeholder
        self.assertTrue((out / "f5_undetected_impact.png").exists())

    def test_detected_attacks_not_in_denominator(self):
        """Detected attacks must not appear in the missed-attack denominator."""
        rows = [
            _row(attack_strategy="burst", detected="True",
                 undetected_physical_impact="False"),
            _row(attack_strategy="burst", detected="True",
                 undetected_physical_impact="False"),
            # Only this row is a missed attack; impact_rate must be 100%, not 33%
            _row(attack_strategy="burst", detected="False",
                 undetected_physical_impact="True"),
        ]
        out = self._run(rows)
        self.assertTrue((out / "f5_undetected_impact.png").exists())


class TestNewStrategyPlots(unittest.TestCase):
    """F7/F10-F12: outcome, risk-map, sensitivity, and ECDF plots."""

    _ROWS = [
        _row(attack_family="velocity_spoof", attack_strategy="constant",
             detected="True", time_to_detection_s="0.1"),
        _row(attack_family="velocity_spoof", attack_strategy="micro_spoof",
             detected="False", undetected_physical_impact="True"),
        _row(attack_family="velocity_spoof", attack_strategy="dropout",
             detected="False", undetected_physical_impact="False"),
        _row(attack_family="false_brake", attack_strategy="burst",
             detected="True", time_to_detection_s="0.5"),
        _row(attack_family="no_attack", attack_strategy="none",
             detected="True", time_to_detection_s="0.1"),
    ]

    def _tmpdir(self):
        return Path(tempfile.mkdtemp())

    def test_f7_strategy_outcome_stack_creates_file(self):
        out = self._tmpdir()
        plot_strategy_outcome_stack(self._ROWS, out, ["png"])
        self.assertTrue((out / "f7_strategy_outcome_stack.png").exists())

    def test_f10_strategy_risk_map_creates_file(self):
        out = self._tmpdir()
        plot_strategy_risk_map(self._ROWS, out, ["png"])
        self.assertTrue((out / "f10_strategy_risk_map.png").exists())

    def test_f11_detection_rate_sensitivity_creates_file(self):
        out = self._tmpdir()
        plot_detection_rate_sensitivity(self._ROWS, out, ["png"])
        self.assertTrue((out / "f11_detection_rate_sensitivity.png").exists())

    def test_f12_ttd_ecdf_creates_file(self):
        out = self._tmpdir()
        plot_ttd_ecdf(self._ROWS, out, ["png"])
        self.assertTrue((out / "f12_ttd_ecdf.png").exists())

    def test_f12_placeholder_without_detected_ttd(self):
        out = self._tmpdir()
        plot_ttd_ecdf([
            _row(attack_family="velocity_spoof", detected="False"),
            _row(attack_family="no_attack", detected="True", time_to_detection_s="0.1"),
        ], out, ["png"])
        self.assertTrue((out / "f12_ttd_ecdf.png").exists())


class TestNewRelationshipPlots(unittest.TestCase):
    """F8-F9: risk and attack-category relationship plots."""

    _ROWS = [
        _row(attack_family="velocity_spoof", attack_strategy="constant",
             detected="True", worst_risk_level="high",
             time_to_detection_s="2.0"),
        _row(attack_family="velocity_spoof", attack_strategy="near_threshold",
             detected="False", worst_risk_level="low"),
        _row(attack_family="false_brake", attack_strategy="burst",
             detected="True", worst_risk_level="critical",
             time_to_detection_s="1.0"),
        _row(attack_family="no_attack", attack_strategy="none",
             detected="True", worst_risk_level="moderate",
             time_to_detection_s="0.5"),
        _row(excluded="True", detected="True", worst_risk_level="critical"),
    ]

    def _tmpdir(self):
        return Path(tempfile.mkdtemp())

    def test_f8_risk_vs_detection_creates_file(self):
        out = self._tmpdir()
        plot_risk_vs_detection(self._ROWS, out, ["png"])
        self.assertTrue((out / "f8_risk_vs_detection.png").exists())

    def test_f8_placeholder_without_attack_rows(self):
        out = self._tmpdir()
        plot_risk_vs_detection([
            _row(attack_family="no_attack", detected="True")
        ], out, ["png"])
        self.assertTrue((out / "f8_risk_vs_detection.png").exists())

    def test_f9_detection_by_attack_category_creates_file(self):
        out = self._tmpdir()
        plot_detection_by_attack_category(self._ROWS, out, ["png"])
        self.assertTrue((out / "f9_detection_by_attack_category.png").exists())

    def test_f9_placeholder_without_attack_rows(self):
        out = self._tmpdir()
        plot_detection_by_attack_category([
            _row(attack_family="no_attack", detected="False")
        ], out, ["png"])
        self.assertTrue((out / "f9_detection_by_attack_category.png").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
