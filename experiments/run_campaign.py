#!/usr/bin/env python3
"""
TwinGuard experiment campaign runner.

Executes scenario-driven experiments by calling the TwinGuard backend API:
  recording start/stop, attack triggers, risk snapshots.
No manual UI clicks required.

Usage:
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --dry-run
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --force
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --scenario baseline_clean
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --seed 1337

Output per run:
  visualization/output/experiments/<campaign_id>/<scenario_id>/<run_id>/
    manifest.json, events.csv, scenario.json,
    recording_analysis.json, risk_snapshot.json, live_alerts.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit(
        "pyyaml is required.\n"
        "Install it with:  pip install pyyaml\n"
        "Or:               pip install -r experiments/requirements.txt"
    )

from attack_generator import leader_topic_target_for_follower

# ── Paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "visualization" / "output" / "experiments"

# Seconds the runner waits after capture/stop before fetching analysis,
# giving the backend time to finalize the recording file.
_POST_STOP_SETTLE_S = 3.0
_PRE_RUN_IDLE_TIMEOUT_S = 10.0
_DEFAULT_PRE_RUN_SETTLE_S = 3.0

# Supported randomizable attack fields and their absolute allowed value bounds.
# Format: field -> (abs_min, min_is_exclusive, abs_max)
#   abs_min / abs_max: None means unbounded.
#   min_is_exclusive:  True when the field must be strictly > abs_min.
_RANDOMIZE_FIELDS: dict[str, tuple[float | None, bool, float | None]] = {
    "delay_s":     (0.0,   False, None),   # >= 0
    "duration_s":  (0.0,   True,  None),   # > 0
    "speed_mps":   (-20.0, False, 20.0),
    "speed_start": (-20.0, False, 20.0),
    "speed_end":   (-20.0, False, 20.0),
}

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http_post(
    base_url: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: int = 10,
) -> tuple[dict[str, Any], str | None]:
    """POST JSON to the backend.  Returns (response_dict, error_string | None)."""
    url = f"{base_url}{path}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        return {}, f"HTTP {exc.code}: {exc.read().decode()[:300]}"
    except urllib.error.URLError as exc:
        return {}, f"Connection error: {exc.reason}"
    except Exception as exc:
        return {}, str(exc)


def _http_get(
    base_url: str,
    path: str,
    timeout: int = 10,
) -> tuple[dict[str, Any], str | None]:
    """GET JSON from the backend.  Returns (response_dict, error_string | None)."""
    url = f"{base_url}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        return {}, f"HTTP {exc.code}: {exc.read().decode()[:300]}"
    except urllib.error.URLError as exc:
        return {}, f"Connection error: {exc.reason}"
    except Exception as exc:
        return {}, str(exc)


def check_backend(base_url: str) -> tuple[bool, str]:
    """Return (reachable, message)."""
    resp, err = _http_get(base_url, "/health", timeout=5)
    if err:
        return False, err
    return True, resp.get("status", "ok")


def _attack_status_idle(status: dict[str, Any]) -> bool:
    """Return True when backend reports no active or pending attacks."""
    for attack_key in ("false_brake", "velocity_spoof"):
        attack = status.get(attack_key)
        if isinstance(attack, dict) and attack.get("status") != "idle":
            return False

    # Older/fallback status shapes may expose top-level active flags.
    busy_flags = (
        "false_brake_active",
        "false_brake_pending",
        "slowdown_active",
        "velocity_spoof_pending",
    )
    return not any(bool(status.get(flag)) for flag in busy_flags)


def _wait_for_attack_idle(
    base_url: str,
    *,
    timeout_s: float = _PRE_RUN_IDLE_TIMEOUT_S,
    poll_s: float = 0.5,
) -> tuple[bool, str | None]:
    """Poll /attack/status until no attack is active or pending."""
    deadline = time.monotonic() + timeout_s
    last_err: str | None = None
    while time.monotonic() <= deadline:
        status, err = _http_get(base_url, "/attack/status", timeout=5)
        if err:
            last_err = err
        elif _attack_status_idle(status):
            return True, None
        else:
            last_err = f"attack status not idle: {status}"
        time.sleep(poll_s)
    return False, last_err


# ── Config loading and validation ─────────────────────────────────────────────

def load_config(path: Path) -> dict[str, Any]:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict[str, Any]) -> None:
    for field in ("campaign_id", "scenarios"):
        if field not in cfg:
            raise ValueError(f"Config missing required field: '{field}'")
    if not isinstance(cfg["scenarios"], list) or len(cfg["scenarios"]) == 0:
        raise ValueError("'scenarios' must be a non-empty list")
    for i, sc in enumerate(cfg["scenarios"]):
        for field in ("id", "label"):
            if field not in sc:
                raise ValueError(f"Scenario[{i}] missing required field '{field}'")
        if "attack" not in sc:
            raise ValueError(
                f"Scenario '{sc.get('id', i)}' missing 'attack' field "
                "(use null / ~ for a clean baseline run)"
            )
        attack = sc.get("attack")
        if isinstance(attack, dict):
            _validate_randomize_block(sc["id"], attack)


# ── Randomization ─────────────────────────────────────────────────────────────

def _validate_randomize_block(scenario_id: str, attack_cfg: dict[str, Any]) -> None:
    """Validate the optional randomize block inside an attack config.

    Raises ValueError with a helpful message on any problem.  Does nothing
    when no randomize key is present.
    """
    randomize = attack_cfg.get("randomize")
    if not randomize:
        return
    if not isinstance(randomize, dict):
        raise ValueError(
            f"Scenario '{scenario_id}': attack.randomize must be a mapping, "
            f"got {type(randomize).__name__}"
        )
    for field, bounds in randomize.items():
        if field not in _RANDOMIZE_FIELDS:
            raise ValueError(
                f"Scenario '{scenario_id}': unsupported randomize field '{field}'. "
                f"Supported fields: {sorted(_RANDOMIZE_FIELDS)}"
            )
        if not isinstance(bounds, dict) or "min" not in bounds or "max" not in bounds:
            raise ValueError(
                f"Scenario '{scenario_id}': randomize.{field} must have 'min' and 'max'"
            )
        try:
            lo = float(bounds["min"])
            hi = float(bounds["max"])
        except (ValueError, TypeError):
            raise ValueError(
                f"Scenario '{scenario_id}': randomize.{field} min/max must be numeric"
            )
        abs_min, exclusive_min, abs_max = _RANDOMIZE_FIELDS[field]
        if lo > hi:
            raise ValueError(
                f"Scenario '{scenario_id}': randomize.{field} min ({lo}) > max ({hi})"
            )
        if abs_min is not None:
            if exclusive_min and lo <= abs_min:
                raise ValueError(
                    f"Scenario '{scenario_id}': randomize.{field} min must be > {abs_min}, got {lo}"
                )
            if not exclusive_min and lo < abs_min:
                raise ValueError(
                    f"Scenario '{scenario_id}': randomize.{field} min must be >= {abs_min}, got {lo}"
                )
        if abs_max is not None and hi > abs_max:
            raise ValueError(
                f"Scenario '{scenario_id}': randomize.{field} max must be <= {abs_max}, got {hi}"
            )


def _make_rep_seed(campaign_seed: int, scenario_id: str, repetition: int) -> int:
    """Derive a deterministic per-repetition seed from campaign seed + scenario + rep.

    The same (campaign_seed, scenario_id, repetition) triple always produces
    the same integer, so campaigns are fully reproducible given the seed.
    """
    key = f"{campaign_seed}:{scenario_id}:{repetition}"
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _resolve_campaign_seed(cfg: dict[str, Any], cli_seed: int | None) -> int:
    """Return the integer seed to use for the campaign, in priority order:
    CLI --seed > YAML random_seed > generated at runtime.
    """
    if cli_seed is not None:
        return int(cli_seed)
    cfg_seed = cfg.get("random_seed")
    if cfg_seed is not None:
        return int(cfg_seed)
    return random.randint(0, 2**31 - 1)


def _resolve_attack_params(
    attack_cfg: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve randomized fields in an attack config.

    Returns:
        (resolved_attack_cfg, randomized_parameters)
        - resolved_attack_cfg: attack config with concrete values substituted
          for every field that had a randomize entry; the 'randomize' key is
          stripped from the returned dict.
        - randomized_parameters: {field_name: resolved_value} for every field
          that was sampled, or {} when no randomize block is present.
    """
    randomize = attack_cfg.get("randomize")
    if not randomize:
        return attack_cfg, {}

    resolved = {k: v for k, v in attack_cfg.items() if k != "randomize"}
    randomized_parameters: dict[str, Any] = {}

    for field, bounds in randomize.items():
        lo = float(bounds["min"])
        hi = float(bounds["max"])
        value = round(rng.uniform(lo, hi), 4)
        resolved[field] = value
        randomized_parameters[field] = value

    return resolved, randomized_parameters


# ── Output directory helpers ──────────────────────────────────────────────────

def scenario_output_dir(output_root: Path, campaign_id: str, scenario_id: str) -> Path:
    return output_root / campaign_id / scenario_id


def run_output_dir(
    output_root: Path, campaign_id: str, scenario_id: str, run_id: str
) -> Path:
    return output_root / campaign_id / scenario_id / run_id


def count_completed_runs(scenario_dir: Path) -> int:
    """Count run subdirs that have a manifest.json with no errors."""
    if not scenario_dir.exists():
        return 0
    count = 0
    for child in scenario_dir.iterdir():
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
            if not manifest.get("errors"):
                count += 1
        except Exception:
            pass
    return count


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=str(_REPO_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


# ── Event log ─────────────────────────────────────────────────────────────────

class EventLog:
    """Accumulates timestamped events for events.csv."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._t0: float | None = None

    def mark_start(self) -> None:
        self._t0 = time.time()

    def add(self, event: str, detail: str = "") -> None:
        now = time.time()
        t_s = round(now - self._t0, 3) if self._t0 is not None else 0.0
        self._events.append(
            {
                "timestamp_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                "t_s": t_s,
                "event": event,
                "detail": detail,
            }
        )
        _log(f"[{t_s:8.2f}s] {event}  {detail}")

    def write_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp_iso", "t_s", "event", "detail"]
            )
            writer.writeheader()
            writer.writerows(self._events)


# ── Logging helper ────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def _sleep(seconds: float, dry_run: bool, reason: str = "") -> None:
    if dry_run:
        _log(f"[DRY-RUN] would sleep {seconds:.1f}s  ({reason})")
        return
    if seconds > 0:
        time.sleep(seconds)


# ── Attack request builder ────────────────────────────────────────────────────

def _build_attack_request(attack_cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (attack_type, request_body) from a (resolved) scenario attack config."""
    attack_type = str(attack_cfg.get("type", ""))
    delay_s = float(attack_cfg.get("delay_s", 0.0))
    duration_s = float(attack_cfg.get("duration_s", 10.0))
    follower_robot = attack_cfg.get("follower_robot") or attack_cfg.get("target_robot")
    topic_target = attack_cfg.get("attack_topic_robot")
    if topic_target is None:
        if attack_cfg.get("follower_robot") and attack_cfg.get("target_robot"):
            topic_target = attack_cfg.get("target_robot")
        else:
            topic_target = leader_topic_target_for_follower(follower_robot)

    if attack_type == "false_brake":
        body: dict[str, Any] = {
            "duration_s": duration_s,
            "delay_s": delay_s,
        }
        if follower_robot:
            body["follower_robot"] = follower_robot
        if topic_target:
            body["target_robot"] = topic_target

    elif attack_type == "velocity_spoof":
        body = {
            "mode": attack_cfg.get("mode", "static"),
            "duration_s": duration_s,
            "delay_s": delay_s,
        }
        for key in ("speed_mps", "speed_start", "speed_end"):
            if attack_cfg.get(key) is not None:
                body[key] = attack_cfg[key]
        if follower_robot:
            body["follower_robot"] = follower_robot
        if topic_target:
            body["target_robot"] = topic_target

    else:
        raise ValueError(f"Unknown attack type: '{attack_type}'")

    return attack_type, body


def _is_clean_scenario(attack: Any) -> bool:
    """Return True when the scenario has no attack (baseline / clean run)."""
    if attack is None:
        return True
    if isinstance(attack, str) and attack.lower() in ("none", "null", ""):
        return True
    return False


# ── Single-run execution ──────────────────────────────────────────────────────

def run_scenario(
    cfg: dict[str, Any],
    scenario: dict[str, Any],
    repetition: int,
    output_root: Path,
    dry_run: bool = False,
    *,
    campaign_seed: int | None = None,
    is_first_run: bool = True,
) -> dict[str, Any]:
    """Execute one scenario repetition.  Returns the manifest dict."""
    campaign_id: str = cfg["campaign_id"]
    scenario_id: str = scenario["id"]
    backend_url: str = cfg.get("backend_url", "http://localhost:8000")
    warmup_s: float = float(cfg.get("warmup_s", 15))
    effective_warmup_s: float = warmup_s if is_first_run else 0.0
    recovery_s: float = float(cfg.get("recovery_s", 20))
    pre_run_settle_s: float = float(cfg.get("pre_run_settle_s", _DEFAULT_PRE_RUN_SETTLE_S))
    attack_cfg = scenario.get("attack")
    is_clean = _is_clean_scenario(attack_cfg)
    git_hash = _git_commit()
    evlog = EventLog()

    errors: list[str] = []
    warnings: list[str] = []
    run_id: str | None = None
    run_dir: Path | None = None
    started_at: float | None = None
    stopped_at: float | None = None
    attack_type: str | None = None
    attack_request: dict[str, Any] | None = None
    attack_response: dict[str, Any] | None = None
    expected_attack_start_s: float | None = None
    expected_attack_end_s: float | None = None
    randomized_parameters: dict[str, Any] = {}

    # ── Resolve randomized attack parameters ──────────────────────────────────
    resolved_attack_cfg = attack_cfg  # default: use config as-is

    if not is_clean and isinstance(attack_cfg, dict) and attack_cfg.get("randomize"):
        if campaign_seed is not None:
            rep_seed = _make_rep_seed(campaign_seed, scenario_id, repetition)
        else:
            # No campaign seed: generate one for this run and record it so the
            # run can be reproduced by passing --seed <campaign_seed>.
            rep_seed = random.randint(0, 2**31 - 1)
            campaign_seed = rep_seed  # record in manifest as the effective seed
        rng = random.Random(rep_seed)
        resolved_attack_cfg, randomized_parameters = _resolve_attack_params(attack_cfg, rng)

    # ── Compute timing and build attack body ──────────────────────────────────
    if not is_clean:
        try:
            attack_type, attack_request = _build_attack_request(resolved_attack_cfg)
        except (ValueError, TypeError) as exc:
            errors.append(f"Invalid attack config: {exc}")
            is_clean = True

    if not is_clean and attack_request is not None:
        delay_s = float(resolved_attack_cfg.get("delay_s", 0.0))
        duration_s = float(resolved_attack_cfg.get("duration_s", 10.0))
        expected_attack_start_s = effective_warmup_s + delay_s
        expected_attack_end_s = expected_attack_start_s + duration_s
        scenario_duration_s = effective_warmup_s + delay_s + duration_s + recovery_s
    else:
        scenario_duration_s = float(scenario.get("duration_s", 60.0))

    # ── Dry-run summary ───────────────────────────────────────────────────────
    if dry_run:
        print(f"\n  {'-'*52}")
        _log(f"SCENARIO  {scenario_id}")
        _log(f"label     {scenario['label']}")
        _log(f"rep       {repetition} / {cfg.get('repetitions', 1)}")
        _log(f"backend   {backend_url}")
        if randomized_parameters:
            _log(f"randomized  {randomized_parameters}")
        _log(f"attack    {resolved_attack_cfg}")
        _log(f"total     {scenario_duration_s:.0f}s")
        if not is_clean:
            _log(f"atk-win   t={expected_attack_start_s:.0f}s - {expected_attack_end_s:.0f}s")
        _log("POST /attack/reset")
        _log("GET  /attack/status until idle")
        if pre_run_settle_s > 0:
            _sleep(pre_run_settle_s, dry_run=True, reason="pre-run settle")
        _log("POST /live/capture/start")
        if not is_clean:
            _sleep(effective_warmup_s, dry_run=True, reason="warmup")
            _log(f"POST /attack/{attack_type}  {json.dumps(attack_request)}")
            _sleep(
                float(resolved_attack_cfg.get("delay_s", 0)) + float(resolved_attack_cfg.get("duration_s", 0)),
                dry_run=True,
                reason="attack window",
            )
            _sleep(recovery_s, dry_run=True, reason="recovery")
        else:
            _sleep(scenario_duration_s, dry_run=True, reason="recording")
        _log("POST /attack/reset")
        _log("POST /live/capture/stop")
        _log(f"GET  /recordings/<run_id>")
        _log(f"GET  /risk/system")
        _log(f"GET  /risk/alerts")
        _log(f"write {output_root / campaign_id / scenario_id}/<run_id>/")
        return {
            "dry_run": True,
            "campaign_id": campaign_id,
            "scenario_id": scenario_id,
            "repetition": repetition,
            "randomized_parameters": randomized_parameters,
        }

    # ── Live execution ────────────────────────────────────────────────────────
    try:
        evlog.mark_start()

        # 1. Pre-run reset
        evlog.add("pre_reset")
        _http_post(backend_url, "/attack/reset")
        idle_ok, idle_err = _wait_for_attack_idle(backend_url)
        if idle_ok:
            evlog.add("pre_attack_idle")
        else:
            warnings.append(f"Attack status did not become idle before recording: {idle_err}")
            evlog.add("pre_attack_idle_warning", str(idle_err))
        if pre_run_settle_s > 0:
            evlog.add("pre_run_settle", f"{pre_run_settle_s:.1f}s")
            _sleep(pre_run_settle_s, dry_run=False)

        # 2. Start recording
        run_name = f"{campaign_id}__{scenario_id}__rep{repetition}"
        resp, err = _http_post(
            backend_url, "/live/capture/start", {"name": run_name}, timeout=15
        )
        if err:
            raise RuntimeError(f"Failed to start recording: {err}")
        run_id = resp.get("run_id")
        if not run_id:
            raise RuntimeError(f"No run_id in start response: {resp}")

        started_at = time.time()
        evlog.add("recording_start", f"run_id={run_id}")

        # Create output dir immediately once we have the run_id
        run_dir = run_output_dir(output_root, campaign_id, scenario_id, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        # scenario.json preserves the original YAML config unchanged
        (run_dir / "scenario.json").write_text(
            json.dumps(scenario, indent=2, default=str)
        )

        if not is_clean:
            # 3. Warmup
            evlog.add("warmup_start", f"{effective_warmup_s:.1f}s")
            _sleep(effective_warmup_s, dry_run=False)
            evlog.add("warmup_end")

            # 4. Trigger attack
            evlog.add(
                "attack_trigger",
                f"type={attack_type} delay={resolved_attack_cfg.get('delay_s', 0)}s",
            )
            attack_response, err = _http_post(
                backend_url, f"/attack/{attack_type}", attack_request
            )
            if err:
                warnings.append(f"Attack trigger HTTP error: {err}")
                evlog.add("attack_trigger_error", err)
            elif not attack_response.get("ok", True):
                warnings.append(f"Attack returned ok=False: {attack_response}")
                evlog.add("attack_nack", str(attack_response))
            else:
                evlog.add("attack_accepted")

            # Log expected windows
            evlog.add(
                "expected_attack_fire",
                f"t={expected_attack_start_s:.1f}s",
            )
            evlog.add(
                "expected_attack_end",
                f"t={expected_attack_end_s:.1f}s",
            )

            # 5. Wait through attack window and recovery
            api_delay = float(resolved_attack_cfg.get("delay_s", 0.0))
            api_duration = float(resolved_attack_cfg.get("duration_s", 10.0))
            evlog.add("attack_window_wait", f"{api_delay + api_duration:.1f}s")
            _sleep(api_delay + api_duration, dry_run=False)
            evlog.add("recovery_start", f"{recovery_s:.1f}s")
            _sleep(recovery_s, dry_run=False)
            evlog.add("recovery_end")

            # Explicit stop (belt-and-suspenders; tamper-service auto-expires)
            _http_post(backend_url, f"/attack/{attack_type}/stop")

        else:
            # Clean baseline: record for the configured duration
            evlog.add(
                "clean_recording",
                f"{scenario_duration_s:.1f}s",
            )
            _sleep(scenario_duration_s, dry_run=False)
            evlog.add("clean_recording_end")

        # 6. Final reset + stop recording
        evlog.add("post_reset")
        _http_post(backend_url, "/attack/reset")

        evlog.add("recording_stop")
        _, err = _http_post(backend_url, "/live/capture/stop", timeout=15)
        stopped_at = time.time()
        if err:
            warnings.append(f"Stop recording error: {err}")

        # Give backend time to finalize the JSONL file
        _sleep(_POST_STOP_SETTLE_S, dry_run=False)

        # 7. Fetch recording analysis
        analysis, err = _http_get(backend_url, f"/recordings/{run_id}", timeout=20)
        if err:
            warnings.append(f"Analysis fetch error: {err}")
            evlog.add("analysis_fetch_error", err)
        else:
            (run_dir / "recording_analysis.json").write_text(
                json.dumps(analysis, indent=2, default=str)
            )
            evlog.add(
                "analysis_fetched",
                f"frames={analysis.get('frame_count', '?')}",
            )

        # 8. Fetch system risk snapshot
        risk, err = _http_get(backend_url, "/risk/system", timeout=15)
        if err:
            warnings.append(f"Risk snapshot error: {err}")
        else:
            (run_dir / "risk_snapshot.json").write_text(
                json.dumps(risk, indent=2, default=str)
            )
            evlog.add("risk_snapshot_fetched")

        alerts, err = _http_get(backend_url, "/risk/alerts", timeout=10)
        if err:
            warnings.append(f"Alerts fetch error: {err}")
        else:
            (run_dir / "live_alerts.json").write_text(
                json.dumps(alerts, indent=2, default=str)
            )
            evlog.add("alerts_fetched")

    except Exception as exc:
        errors.append(str(exc))
        evlog.add("error", str(exc))
        _log(f"ERROR: {exc}")

    finally:
        # 9. Always write events.csv and manifest.json, even for partial runs
        manifest: dict[str, Any] = {
            "campaign_id": campaign_id,
            "scenario_id": scenario_id,
            "label": scenario.get("label", ""),
            "repetition": repetition,
            "run_id": run_id,
            "backend_url": backend_url,
            "started_at": started_at,
            "stopped_at": stopped_at,
            "attack_type": attack_type,
            "expected_attack_start_s": expected_attack_start_s,
            "expected_attack_end_s": expected_attack_end_s,
            "attack_request": attack_request,
            "resolved_attack_request": attack_request,
            "attack_response": attack_response,
            "random_seed": campaign_seed,
            "randomized_parameters": randomized_parameters,
            "git_commit": git_hash,
            "errors": errors,
            "warnings": warnings,
        }
        if run_dir is not None:
            evlog.write_csv(run_dir / "events.csv")
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, default=str)
            )
        else:
            # run_dir was never created (recording start failed); log to stderr
            print(
                f"  WARNING: no output directory for {scenario_id} rep {repetition}",
                file=sys.stderr,
            )

    status = "ERROR" if errors else ("WARN" if warnings else "ok")
    _log(f">> {status}  run_id={run_id or 'none'}  dir={run_dir}")
    return manifest


# ── Campaign loop ─────────────────────────────────────────────────────────────

def run_campaign(
    cfg: dict[str, Any],
    output_root: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    only_scenario: str | None = None,
    seed: int | None = None,
) -> None:
    campaign_id: str = cfg["campaign_id"]
    repetitions: int = int(cfg.get("repetitions", 1))
    scenarios: list[dict[str, Any]] = cfg["scenarios"]
    backend_url: str = cfg.get("backend_url", "http://localhost:8000")

    if only_scenario:
        scenarios = [s for s in scenarios if s["id"] == only_scenario]
        if not scenarios:
            sys.exit(f"Scenario '{only_scenario}' not found in config.")

    # Resolve the campaign-level random seed (CLI > YAML > generated).
    campaign_seed = _resolve_campaign_seed(cfg, seed)
    seed_is_configured = cfg.get("random_seed") is not None or seed is not None

    print(f"\n{'='*60}")
    print(f"  Campaign : {campaign_id}")
    print(f"  Scenarios: {len(scenarios)}  x  {repetitions} rep(s)  "
          f"= {len(scenarios) * repetitions} total run(s)")
    print(f"  Backend  : {backend_url}")
    print(f"  Output   : {output_root / campaign_id}")
    if seed_is_configured:
        print(f"  Seed     : {campaign_seed}")
    else:
        print(f"  Seed     : {campaign_seed}  (generated -- pass --seed {campaign_seed} to reproduce)")
    if dry_run:
        print("  Mode     : DRY-RUN  (no HTTP calls, no files written)")
    print(f"{'='*60}")

    if not dry_run:
        ok, msg = check_backend(backend_url)
        if not ok:
            print(f"\n  WARNING: backend not reachable: {msg}")
            print("  Proceeding anyway -- runs will record errors in manifests.\n")
        else:
            print(f"\n  Backend reachable: {msg}\n")

    total_planned = len(scenarios) * repetitions
    executed = 0
    skipped = 0

    for scenario in scenarios:
        scenario_id: str = scenario["id"]
        sc_dir = scenario_output_dir(output_root, campaign_id, scenario_id)
        done = 0 if (dry_run or force) else count_completed_runs(sc_dir)
        reps_needed = repetitions - done

        if reps_needed <= 0:
            print(f"\n  >> {scenario_id}: all {repetitions} rep(s) done -- skipping")
            skipped += repetitions
            continue

        if done > 0:
            print(
                f"\n  >> {scenario_id}: {done} rep(s) already done, "
                f"running {reps_needed} more"
            )

        for rep in range(done + 1, repetitions + 1):
            n = executed + skipped + 1
            print(f"\n[{n}/{total_planned}]  {scenario_id}  rep {rep}")
            run_scenario(
                cfg, scenario, rep, output_root, dry_run=dry_run,
                campaign_seed=campaign_seed,
                is_first_run=(executed == 0),
            )
            executed += 1

    print(f"\n{'='*60}")
    print(f"  Done: {executed} run(s) executed, {skipped} skipped.")
    print(f"  Output:  {output_root / campaign_id}")
    print(f"{'='*60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TwinGuard experiment campaign runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  # Full campaign (5 repetitions x all scenarios)
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml

  # Dry-run: print plan without hitting the backend
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --dry-run

  # Reproducible run with a fixed seed
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --seed 1337

  # Dry-run with seed to inspect randomized values
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml \\
      --dry-run --seed 1337

  # Re-run everything even if output already exists
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml --force

  # Run a single scenario
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml \\
      --scenario baseline_clean

  # Custom output directory
  python experiments/run_campaign.py --config experiments/scenarios/thesis_campaign.yaml \\
      --output-root /mnt/data/experiments
""",
    )
    parser.add_argument(
        "--config", required=True, help="Path to campaign YAML config file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without making HTTP calls or writing files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run all scenarios even if output directories already exist",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Run only the scenario with this ID (overrides repetition count)",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help=(
            "Override default output root "
            "(default: visualization/output/experiments/)"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "Override random seed for reproducible randomized scenarios. "
            "Takes precedence over random_seed in the YAML config."
        ),
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        sys.exit(f"Config not found: {config_path}")

    try:
        cfg = load_config(config_path)
    except (ValueError, Exception) as exc:
        sys.exit(f"Config error: {exc}")

    output_root = (
        Path(args.output_root) if args.output_root else _DEFAULT_OUTPUT_ROOT
    )

    run_campaign(
        cfg,
        output_root,
        dry_run=args.dry_run,
        force=args.force,
        only_scenario=args.scenario,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
