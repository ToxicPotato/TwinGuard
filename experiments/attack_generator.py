"""
TwinGuard algorithmic adversarial attack generator.

Each call to generate_attack_strategy produces a fresh attack strategy by
sampling attack family, target robot, timing, temporal shape/strategy, and
magnitude from configurable probability distributions and parameter bounds.

This is not a list of preset templates with randomized slots.  Every trial
produces a genuinely independent strategy whose shape is only constrained
by the generator config.

Public API
----------
validate_attack_generator_config(cfg)
    Validate the attack_generator config section.  Raises ValueError on any
    structural problem.

generate_attack_strategy(rng, gen_cfg, observed_baseline=None) -> dict
    Sample one complete attack strategy.  Returns a strategy dict that
    describes both the logical intent (strategy, attack_difficulty) and all
    parameters needed to compile it to a backend request.

build_attack_request_from_strategy(strategy) -> tuple[str, dict]
    Compile a strategy dict into (attack_type, request_body) ready to POST
    to /attack/<attack_type>.  Raises ValueError for strategies that cannot
    be expressed with the current backend API (e.g. pulse).

Backend compatibility
---------------------
  constant       -> velocity_spoof static
  near_threshold -> velocity_spoof static
  micro_spoof    -> velocity_spoof static  (small deviation, sustained)
  dropout        -> velocity_spoof static  (speed_mps = 0.0)
  ramp           -> velocity_spoof ramp
  pulse          -> velocity_spoof pulse, orchestrated by experiment runner
  false_brake burst -> false_brake

attack_difficulty values
------------------------
  hard   -- small deviation / near-threshold; hard for TwinGuard to detect
  medium -- moderate deviation or pulsed pattern
  easy   -- large deviation or dropout; easy to detect
  none   -- no_attack trials (negative control)
"""
from __future__ import annotations

import random
from typing import Any

# Assumed leader speed for difficulty classification when no observed baseline
# is available.  Matches the typical TwinGuard simulation default.
_ASSUMED_LEADER_SPEED_MPS: float = 1.0

# Attack difficulty deviation boundaries (m/s) for velocity_spoof strategies.
_DIFF_HARD_MAX_DEVIATION: float = 0.10    # < 0.10 m/s deviation -> hard (to detect)
_DIFF_MEDIUM_MAX_DEVIATION: float = 0.30  # < 0.30 m/s deviation -> medium
# >= 0.30 m/s deviation -> easy (to detect)

_LEADER_TOPIC_BY_FOLLOWER: dict[str, str] = {
    "Fridjof": "Bjarte",
    "Torleif": "Fridjof",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def leader_topic_target_for_follower(follower_robot: str | None) -> str | None:
    """Map a logical follower under attack to the upstream topic to tamper."""
    if not follower_robot:
        return None
    return _LEADER_TOPIC_BY_FOLLOWER.get(follower_robot, follower_robot)


def _sample_weighted(rng: random.Random, probs: dict[str, Any]) -> str:
    """Sample one key from a probability dict.  Values are relative weights."""
    total = sum(float(v) for v in probs.values())
    r = rng.uniform(0.0, total)
    cumulative = 0.0
    for key, prob in probs.items():
        cumulative += float(prob)
        if r < cumulative:
            return key
    return list(probs.keys())[-1]


def _sample_range(rng: random.Random, bounds: dict[str, Any]) -> float:
    """Sample uniformly from [min, max]."""
    lo = float(bounds["min"])
    hi = float(bounds["max"])
    return rng.uniform(lo, hi)


def _sample_int_range(rng: random.Random, bounds: dict[str, Any]) -> int:
    """Sample a uniform integer from [min, max] inclusive."""
    lo = int(bounds["min"])
    hi = int(bounds["max"])
    return rng.randint(lo, hi)


def _vs_attack_difficulty(
    strategy: str,
    *,
    speed_mps: float | None = None,
    speed_start: float | None = None,
    speed_end: float | None = None,
    leader_speed: float = _ASSUMED_LEADER_SPEED_MPS,
) -> str:
    """Classify attack_difficulty for a velocity_spoof strategy.

    Returns 'hard', 'medium', or 'easy' (defender's perspective).
    """
    if strategy == "near_threshold":
        return "hard"
    if strategy == "pulse":
        return "medium"
    if strategy == "dropout":
        return "easy"

    # constant: classify by magnitude of deviation from leader speed
    if strategy == "constant" and speed_mps is not None:
        deviation = abs(leader_speed - speed_mps)
        if deviation <= _DIFF_HARD_MAX_DEVIATION:
            return "hard"
        if deviation <= _DIFF_MEDIUM_MAX_DEVIATION:
            return "medium"
        return "easy"

    # ramp: use the maximum deviation across the ramp range
    if strategy == "ramp" and speed_start is not None and speed_end is not None:
        deviation = max(abs(leader_speed - speed_start), abs(leader_speed - speed_end))
        if deviation <= _DIFF_HARD_MAX_DEVIATION:
            return "hard"
        if deviation <= _DIFF_MEDIUM_MAX_DEVIATION:
            return "medium"
        return "easy"

    return "easy"


# ── Config validation ─────────────────────────────────────────────────────────

def validate_attack_generator_config(cfg: dict[str, Any]) -> None:
    """Validate the attack_generator config section.  Raises ValueError on problems."""
    for field in ("family_probabilities",):
        if field not in cfg:
            raise ValueError(f"attack_generator missing required field: '{field}'")

    # target_robots
    targets = cfg.get("target_robots")
    if targets is not None:
        if not isinstance(targets, list) or not targets:
            raise ValueError("attack_generator.target_robots must be a non-empty list")

    # family_probabilities
    fprobs = cfg["family_probabilities"]
    if not isinstance(fprobs, dict) or not fprobs:
        raise ValueError("attack_generator.family_probabilities must be a non-empty mapping")
    total_fp = 0.0
    for family, prob in fprobs.items():
        try:
            p = float(prob)
        except (TypeError, ValueError):
            raise ValueError(
                f"attack_generator.family_probabilities.{family} must be numeric, got {prob!r}"
            )
        if p <= 0:
            raise ValueError(
                f"attack_generator.family_probabilities.{family} must be > 0, got {p}"
            )
        total_fp += p
    if total_fp <= 0:
        raise ValueError("attack_generator.family_probabilities total weight must be > 0")

    # timing bounds
    timing = cfg.get("timing", {})
    for key in ("delay_s", "duration_s"):
        bounds = timing.get(key)
        if bounds is not None:
            lo = float(bounds.get("min", 0))
            hi = float(bounds.get("max", 1))
            if lo > hi:
                raise ValueError(f"attack_generator.timing.{key}: min ({lo}) > max ({hi})")

    # velocity_spoof section (required when that family is in family_probabilities)
    if "velocity_spoof" in fprobs:
        vs = cfg.get("velocity_spoof")
        if not isinstance(vs, dict):
            raise ValueError(
                "attack_generator.velocity_spoof section required when "
                "velocity_spoof is in family_probabilities"
            )
        sprobs = vs.get("strategy_probabilities")
        if not isinstance(sprobs, dict) or not sprobs:
            raise ValueError(
                "attack_generator.velocity_spoof.strategy_probabilities must be "
                "a non-empty mapping"
            )
        total_sp = sum(float(v) for v in sprobs.values())
        if total_sp <= 0:
            raise ValueError(
                "attack_generator.velocity_spoof.strategy_probabilities total must be > 0"
            )
        for strat, prob in sprobs.items():
            try:
                p = float(prob)
            except (TypeError, ValueError):
                raise ValueError(
                    f"attack_generator.velocity_spoof.strategy_probabilities.{strat} "
                    f"must be numeric, got {prob!r}"
                )
            if p < 0:
                raise ValueError(
                    f"attack_generator.velocity_spoof.strategy_probabilities.{strat} "
                    f"must be >= 0, got {p}"
                )

    # false_brake section (required when that family is in family_probabilities)
    if "false_brake" in fprobs:
        fb = cfg.get("false_brake")
        # false_brake section is optional; timing.duration_s is used as fallback
        if fb is not None and not isinstance(fb, dict):
            raise ValueError("attack_generator.false_brake must be a mapping when present")


# ── Strategy generators ───────────────────────────────────────────────────────

def _generate_vs_constant(
    rng: random.Random,
    vs_cfg: dict[str, Any],
    target: str,
    delay_s: float,
    duration_s: float,
) -> dict[str, Any]:
    speed_mps = round(_sample_range(rng, vs_cfg["speed_mps"]), 4)
    difficulty = _vs_attack_difficulty("constant", speed_mps=speed_mps)
    out: dict[str, Any] = {
        "attack_family": "velocity_spoof",
        "strategy": "constant",
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": round(duration_s, 4),
        "speed_mps": speed_mps,
        "attack_difficulty": difficulty,
    }
    # When a threshold_context section is present in the velocity_spoof config,
    # stamp each trial with threshold compliance metadata so callers can assess
    # whether the injected speed falls within the detector window.
    threshold_ctx = vs_cfg.get("threshold_context")
    if threshold_ctx is not None:
        ref_speed = float(threshold_ctx.get("reference_speed_mps", _ASSUMED_LEADER_SPEED_MPS))
        threshold_mps = float(threshold_ctx.get("threshold_mps", 0.05))
        deviation = round(abs(ref_speed - speed_mps), 4)
        out["deviation_mps"] = deviation
        out["threshold_mps"] = threshold_mps
        out["threshold_reference_speed_mps"] = ref_speed
        out["within_threshold"] = deviation <= threshold_mps
        out["expected_detectability"] = str(
            threshold_ctx.get("expected_detectability", "within_detector_threshold")
        )
    return out


def _generate_vs_ramp(
    rng: random.Random,
    vs_cfg: dict[str, Any],
    target: str,
    delay_s: float,
    duration_s: float,
) -> dict[str, Any]:
    ramp_cfg = vs_cfg["ramp"]
    speed_start = round(_sample_range(rng, ramp_cfg["start_mps"]), 4)
    speed_end = round(_sample_range(rng, ramp_cfg["end_mps"]), 4)
    difficulty = _vs_attack_difficulty("ramp", speed_start=speed_start, speed_end=speed_end)
    return {
        "attack_family": "velocity_spoof",
        "strategy": "ramp",
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": round(duration_s, 4),
        "speed_start": speed_start,
        "speed_end": speed_end,
        "attack_difficulty": difficulty,
    }


def _generate_vs_near_threshold(
    rng: random.Random,
    vs_cfg: dict[str, Any],
    target: str,
    delay_s: float,
    duration_s: float,
) -> dict[str, Any]:
    nt_cfg = vs_cfg["near_threshold"]
    baseline = float(nt_cfg.get("baseline_speed_mps", _ASSUMED_LEADER_SPEED_MPS))
    threshold = float(nt_cfg.get("threshold_mps", 0.05))
    margin = round(_sample_range(rng, nt_cfg["margin_mps"]), 4)
    direction = _sample_weighted(rng, nt_cfg["direction_probabilities"])

    if direction == "underreport":
        speed_mps = max(0.0, round(baseline - threshold - margin, 4))
    else:
        speed_mps = round(baseline + threshold + margin, 4)

    return {
        "attack_family": "velocity_spoof",
        "strategy": "near_threshold",
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": round(duration_s, 4),
        "baseline_speed_mps": baseline,
        "threshold_mps": threshold,
        "margin_mps": margin,
        "direction": direction,
        "speed_mps": speed_mps,
        "attack_difficulty": "hard",
    }


def _generate_vs_pulse(
    rng: random.Random,
    vs_cfg: dict[str, Any],
    target: str,
    delay_s: float,
    duration_s: float,
) -> dict[str, Any]:
    pulse_cfg = vs_cfg["pulse"]
    pulse_count = _sample_int_range(rng, pulse_cfg["pulse_count"])
    duty_cycle = round(_sample_range(rng, pulse_cfg["duty_cycle"]), 4)
    low_speed_mps = round(_sample_range(rng, pulse_cfg["low_speed_mps"]), 4)
    high_speed_mps = round(_sample_range(rng, pulse_cfg["high_speed_mps"]), 4)
    return {
        "attack_family": "velocity_spoof",
        "strategy": "pulse",
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": round(duration_s, 4),
        "pulse_count": pulse_count,
        "duty_cycle": duty_cycle,
        "low_speed_mps": low_speed_mps,
        "high_speed_mps": high_speed_mps,
        "attack_difficulty": "medium",
    }


def _generate_vs_dropout(
    rng: random.Random,
    vs_cfg: dict[str, Any],
    target: str,
    delay_s: float,
    duration_s: float,
) -> dict[str, Any]:
    speed_mps = float((vs_cfg.get("dropout") or {}).get("speed_mps", 0.0))
    return {
        "attack_family": "velocity_spoof",
        "strategy": "dropout",
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": round(duration_s, 4),
        "speed_mps": round(speed_mps, 4),
        "attack_difficulty": "easy",
    }


def _generate_vs_micro_spoof(
    rng: random.Random,
    vs_cfg: dict[str, Any],
    target: str,
    delay_s: float,
    duration_s: float,
) -> dict[str, Any]:
    """Micro-spoof: small sustained deviation at the edge of detection sensitivity.

    Deviation is sampled from a narrow range well below the normal near_threshold
    margin.  Duration is enforced >= 1.5 s so the detector has a window to observe
    the anomaly.  Compiles to a static velocity_spoof request.
    """
    ms_cfg = vs_cfg.get("micro_spoof") or {}

    # Duration must be sustained for at least 1.5 s
    dur_bounds = ms_cfg.get("duration_s") or {"min": 1.5, "max": 12.0}
    actual_duration = max(1.5, round(_sample_range(rng, dur_bounds), 4))

    # Small deviation from leader speed
    dev_bounds = ms_cfg.get("deviation_mps") or {"min": 0.01, "max": 0.08}
    deviation = round(_sample_range(rng, dev_bounds), 4)

    # Direction of the spoof
    dir_probs = ms_cfg.get("direction_probabilities") or {"underreport": 0.6, "overreport": 0.4}
    direction = _sample_weighted(rng, dir_probs)

    if direction == "underreport":
        speed_mps = max(0.0, round(_ASSUMED_LEADER_SPEED_MPS - deviation, 4))
    else:
        speed_mps = round(_ASSUMED_LEADER_SPEED_MPS + deviation, 4)

    out: dict[str, Any] = {
        "attack_family": "velocity_spoof",
        "strategy": "micro_spoof",
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": actual_duration,
        "deviation_mps": deviation,
        "direction": direction,
        "speed_mps": speed_mps,
        "attack_difficulty": "hard",  # always hardest to detect
    }

    # When a detector threshold is configured in the micro_spoof section,
    # record whether this sampled deviation stays within it and annotate
    # expected detectability.  This enables within-threshold experiment configs
    # to stamp trials clearly without changing the normal pipeline.
    threshold = ms_cfg.get("threshold_mps")
    if threshold is not None:
        threshold_f = float(threshold)
        within = deviation < threshold_f
        out["threshold_mps"] = threshold_f
        out["within_threshold"] = within
        out["expected_detectability"] = (
            "below_detector_threshold" if within else "at_threshold_boundary"
        )

    return out


def _generate_no_attack(
    rng: random.Random,
    gen_cfg: dict[str, Any],
    target: str,
    duration_s: float,
) -> dict[str, Any]:
    """Generate a no-attack strategy for a clean recording trial."""
    return {
        "attack_family": "no_attack",
        "strategy": "none",
        "target_robot": target,
        "delay_s": 0.0,
        "duration_s": round(duration_s, 4),
        "attack_difficulty": "none",
    }


def _generate_false_brake(
    rng: random.Random,
    gen_cfg: dict[str, Any],
    target: str,
    delay_s: float,
) -> dict[str, Any]:
    fb_cfg = gen_cfg.get("false_brake") or {}
    timing = gen_cfg.get("timing") or {}
    dur_bounds = fb_cfg.get("duration_s") or timing.get("duration_s") or {"min": 1.0, "max": 15.0}
    duration_s = round(_sample_range(rng, dur_bounds), 4)
    difficulty = "medium" if duration_s < 5.0 else "easy"
    out: dict[str, Any] = {
        "attack_family": "false_brake",
        "strategy": str(fb_cfg.get("strategy_label", "burst")),
        "target_robot": target,
        "delay_s": round(delay_s, 4),
        "duration_s": duration_s,
        "attack_difficulty": difficulty,
    }
    # Optional metadata fields to clarify threshold applicability.
    # Only emitted when explicitly set in the false_brake config section.
    threshold_applicability = fb_cfg.get("threshold_applicability")
    if threshold_applicability is not None:
        out["threshold_applicability"] = str(threshold_applicability)
    expected_detectability = fb_cfg.get("expected_detectability")
    if expected_detectability is not None:
        out["expected_detectability"] = str(expected_detectability)
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def generate_attack_strategy(
    rng: random.Random,
    gen_cfg: dict[str, Any],
    observed_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sample one complete attack strategy from the generator config.

    Parameters
    ----------
    rng:
        Seeded random generator.  The caller is responsible for seeding it
        deterministically if reproducibility is required.
    gen_cfg:
        The attack_generator config section from the experiment YAML.
    observed_baseline:
        Optional live telemetry from the platoon (e.g. measured leader speed).
        When provided, near_threshold strategies adapt their baseline_speed_mps
        to the observed value.  Currently only the key ``leader_speed_mps`` is
        used.

    Returns
    -------
    dict with at least:
        attack_family, strategy, target_robot, delay_s, duration_s,
        attack_difficulty
    Plus strategy-specific fields (speed_mps, speed_start/end, etc.).
    """
    # 1. Sample attack family
    family = _sample_weighted(rng, gen_cfg["family_probabilities"])

    # 2. Sample target robot
    targets = gen_cfg.get("target_robots") or ["Fridjof"]
    target: str = rng.choice(targets)

    # 3. Sample global timing
    timing = gen_cfg.get("timing") or {}
    delay_bounds = timing.get("delay_s") or {"min": 0.0, "max": 10.0}
    dur_bounds = timing.get("duration_s") or {"min": 1.0, "max": 20.0}
    delay_s = _sample_range(rng, delay_bounds)
    duration_s = _sample_range(rng, dur_bounds)

    if family == "velocity_spoof":
        vs_cfg = gen_cfg.get("velocity_spoof") or {}
        strategy = _sample_weighted(rng, vs_cfg.get("strategy_probabilities", {"constant": 1.0}))

        # Per-target speed range override: if speed_mps_by_target has an entry
        # for this robot, replace the top-level speed_mps bounds with it.
        speed_by_target = vs_cfg.get("speed_mps_by_target") or {}
        if target in speed_by_target:
            vs_cfg = dict(vs_cfg, speed_mps=speed_by_target[target])

        # Allow observed baseline to override near_threshold reference speed
        if observed_baseline and "near_threshold" in vs_cfg:
            obs_speed = observed_baseline.get("leader_speed_mps")
            if obs_speed is not None:
                nt = dict(vs_cfg.get("near_threshold") or {})
                nt["baseline_speed_mps"] = float(obs_speed)
                vs_cfg = dict(vs_cfg, near_threshold=nt)

        if strategy == "constant":
            return _generate_vs_constant(rng, vs_cfg, target, delay_s, duration_s)
        if strategy == "ramp":
            return _generate_vs_ramp(rng, vs_cfg, target, delay_s, duration_s)
        if strategy == "near_threshold":
            return _generate_vs_near_threshold(rng, vs_cfg, target, delay_s, duration_s)
        if strategy == "micro_spoof":
            return _generate_vs_micro_spoof(rng, vs_cfg, target, delay_s, duration_s)
        if strategy == "pulse":
            return _generate_vs_pulse(rng, vs_cfg, target, delay_s, duration_s)
        if strategy == "dropout":
            return _generate_vs_dropout(rng, vs_cfg, target, delay_s, duration_s)
        raise ValueError(f"Unknown velocity_spoof strategy: {strategy!r}")

    if family == "no_attack":
        return _generate_no_attack(rng, gen_cfg, target, duration_s)

    if family == "false_brake":
        return _generate_false_brake(rng, gen_cfg, target, delay_s)

    raise ValueError(f"Unknown attack family: {family!r}")


def build_attack_request_from_strategy(
    strategy: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Compile a generated strategy dict into (attack_type, request_body).

    The returned pair is ready to POST to /attack/<attack_type>.

    Raises ValueError for strategies that cannot be expressed with the current
    backend API — specifically velocity_spoof pulse, which requires multi-cycle
    start/stop that the backend does not support.
    """
    family: str = strategy["attack_family"]
    strat: str = strategy.get("strategy", "")
    delay_s = float(strategy.get("delay_s", 0.0))
    duration_s = float(strategy.get("duration_s", 10.0))
    target = strategy.get("target_robot")
    topic_target = strategy.get("attack_topic_robot") or leader_topic_target_for_follower(target)

    if family == "velocity_spoof":
        if strat in ("constant", "near_threshold", "dropout", "micro_spoof"):
            body: dict[str, Any] = {
                "mode": "static",
                "speed_mps": float(strategy["speed_mps"]),
                "duration_s": duration_s,
                "delay_s": delay_s,
            }
            if target:
                body["follower_robot"] = target
            if topic_target:
                body["target_robot"] = topic_target
            return "velocity_spoof", body

        if strat == "ramp":
            body = {
                "mode": "ramp",
                "speed_start": float(strategy["speed_start"]),
                "speed_end": float(strategy["speed_end"]),
                "duration_s": duration_s,
                "delay_s": delay_s,
            }
            if target:
                body["follower_robot"] = target
            if topic_target:
                body["target_robot"] = topic_target
            return "velocity_spoof", body

        if strat == "pulse":
            body = {
                "mode": "pulse",
                "low_speed_mps": float(strategy["low_speed_mps"]),
                "high_speed_mps": float(strategy["high_speed_mps"]),
                "pulse_count": int(strategy["pulse_count"]),
                "duty_cycle": float(strategy["duty_cycle"]),
                "duration_s": duration_s,
                "delay_s": delay_s,
            }
            if target:
                body["follower_robot"] = target
            if topic_target:
                body["target_robot"] = topic_target
            return "velocity_spoof", body

        raise ValueError(
            f"velocity_spoof strategy {strat!r} has no supported backend representation"
        )

    if family == "false_brake":
        body = {
            "duration_s": duration_s,
            "delay_s": delay_s,
        }
        if target:
            body["follower_robot"] = target
        if topic_target:
            body["target_robot"] = topic_target
        return "false_brake", body

    if family == "no_attack":
        raise ValueError(
            "no_attack strategies have no backend request — caller must handle this case"
        )

    raise ValueError(f"Unknown attack family: {family!r}")
