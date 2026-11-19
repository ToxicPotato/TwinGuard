"""Accumulate run-level analysis while a live capture is being written."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

_TIMELINE_BUCKET_SIZE = 20


def _risk_label(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 35:
        return "elevated"
    return "low"


def _as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


@dataclass(slots=True)
class RobotRunStats:
    """Per-robot aggregates derived from enriched frames in one recording."""

    frames: int = 0
    velocity_spoof_frames: int = 0
    first_velocity_spoof_t: float | None = None
    last_velocity_spoof_t: float | None = None
    velocity_spoof_kind_counts: dict[str, int] = field(default_factory=dict)
    speed_min: float | None = None
    speed_max: float | None = None
    max_abs_lane_error: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "velocity_spoof_frames": self.velocity_spoof_frames,
            "first_velocity_spoof_t": self.first_velocity_spoof_t,
            "last_velocity_spoof_t": self.last_velocity_spoof_t,
            "velocity_spoof_kind_counts": dict(sorted(self.velocity_spoof_kind_counts.items())),
            "dominant_velocity_spoof_kind": _dominant_kind(self.velocity_spoof_kind_counts),
            "speed_min": self.speed_min,
            "speed_max": self.speed_max,
            "max_abs_lane_error": self.max_abs_lane_error,
        }


@dataclass(slots=True)
class TimelineBucket:
    """Compact frame-range summary used by the recordings detail view."""

    start_frame: int
    end_frame: int
    frames: int = 0
    anomaly_frames: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "frames": self.frames,
            "anomaly_frames": self.anomaly_frames,
        }


@dataclass(slots=True)
class RunAccumulator:
    """Build the persisted recording analysis directly from enriched live frames."""

    run_id: str
    name: str
    started_at: float
    live_hz: float
    frame_count: int = 0
    _timeline: list[TimelineBucket] = field(default_factory=list)
    _robots: dict[str, RobotRunStats] = field(default_factory=dict)
    _anomaly_frames: int = 0
    _first_t: float | None = None
    _last_t: float | None = None
    _previous_t: float | None = None
    _max_gap_s: float = 0.0

    @classmethod
    def from_recording_file(
        cls,
        *,
        run_id: str,
        name: str,
        started_at: float,
        live_hz: float,
        recording_path: Path,
    ) -> "RunAccumulator":
        """Rebuild aggregates from an on-disk recording after an interrupted process restart."""
        accumulator = cls(run_id=run_id, name=name, started_at=started_at, live_hz=live_hz)
        with recording_path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue
                try:
                    envelope = json.loads(raw_line)
                except json.JSONDecodeError:
                    # A crash can leave the final JSONL line partially written.
                    # Recovery should salvage every complete frame before that point.
                    continue
                if not isinstance(envelope, dict):
                    continue
                enriched_frame = envelope.get("data")
                if isinstance(enriched_frame, dict):
                    accumulator.consume_frame(enriched_frame)
        return accumulator

    def consume_frame(self, enriched_frame: dict[str, Any]) -> None:
        """Update run aggregates from one frame that was successfully written to disk."""
        self.frame_count += 1

        timestamp_s = _as_number(enriched_frame.get("t"))
        if timestamp_s is not None:
            self._update_timing(timestamp_s)

        bucket = self._current_bucket()
        bucket.frames += 1
        bucket.end_frame = self.frame_count

        frame_has_anomaly = False
        per_robot_labels = enriched_frame.get("scenario", {}).get("per_robot", {})
        robot_payloads = enriched_frame.get("robots", {})
        if not isinstance(per_robot_labels, dict):
            per_robot_labels = {}
        if not isinstance(robot_payloads, dict):
            robot_payloads = {}

        for robot_id in sorted(set(robot_payloads) | set(per_robot_labels)):
            robot_stats = self._robots.setdefault(robot_id, RobotRunStats())
            robot_stats.frames += 1

            robot_payload = robot_payloads.get(robot_id, {})
            if not isinstance(robot_payload, dict):
                robot_payload = {}

            speed = _as_number(robot_payload.get("v"))
            if speed is not None:
                robot_stats.speed_min = speed if robot_stats.speed_min is None else min(robot_stats.speed_min, speed)
                robot_stats.speed_max = speed if robot_stats.speed_max is None else max(robot_stats.speed_max, speed)

            lane_error = _as_number(robot_payload.get("lane_le"))
            if lane_error is not None:
                abs_lane_error = abs(lane_error)
                robot_stats.max_abs_lane_error = (
                    abs_lane_error
                    if robot_stats.max_abs_lane_error is None
                    else max(robot_stats.max_abs_lane_error, abs_lane_error)
                )

            labels = per_robot_labels.get(robot_id, {})
            if _has_velocity_spoof(labels):
                frame_has_anomaly = True
                robot_stats.velocity_spoof_frames += 1
                spoof_kind = _velocity_spoof_kind(labels)
                if spoof_kind is not None:
                    robot_stats.velocity_spoof_kind_counts[spoof_kind] = (
                        robot_stats.velocity_spoof_kind_counts.get(spoof_kind, 0) + 1
                    )
                if timestamp_s is not None:
                    robot_stats.first_velocity_spoof_t = (
                        timestamp_s
                        if robot_stats.first_velocity_spoof_t is None
                        else min(robot_stats.first_velocity_spoof_t, timestamp_s)
                    )
                    robot_stats.last_velocity_spoof_t = (
                        timestamp_s
                        if robot_stats.last_velocity_spoof_t is None
                        else max(robot_stats.last_velocity_spoof_t, timestamp_s)
                    )

        if frame_has_anomaly:
            self._anomaly_frames += 1
            bucket.anomaly_frames += 1

    def running_stats(self) -> dict[str, Any]:
        """Return lightweight stats for an in-progress run without finalising it."""
        anomaly_ratio = self._anomaly_frames / self.frame_count if self.frame_count else 0.0
        return {
            "run_id": self.run_id,
            "name": self.name,
            "started_at": self.started_at,
            "frame_count": self.frame_count,
            "anomaly_frames": self._anomaly_frames,
            "anomaly_ratio": round(anomaly_ratio, 5),
            "robots_with_spoofing": sorted(
                robot_id for robot_id, stats in self._robots.items()
                if stats.velocity_spoof_frames > 0
            ),
        }

    def finalize(self, *, ended_at: float, status: str, frames_bytes: int) -> dict[str, Any]:
        """Return the fully materialized metadata document for one completed recording."""
        duration_s = max(0.0, ended_at - self.started_at)
        anomaly_ratio = self._anomaly_frames / self.frame_count if self.frame_count else 0.0
        risk_score = self._score_run(status=status, anomaly_ratio=anomaly_ratio, max_gap_s=self._max_gap_s)

        analysis = {
            "frame_count": self.frame_count,
            "duration_s": duration_s,
            "anomaly_frames": self._anomaly_frames,
            "anomaly_ratio": round(anomaly_ratio, 5),
            "max_gap_s": round(self._max_gap_s, 4),
            "robots": {robot_id: robot_stats.to_dict() for robot_id, robot_stats in self._robots.items()},
            "timeline": [bucket.to_dict() for bucket in self._timeline],
            "findings": self._build_findings(anomaly_ratio),
        }

        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": status,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "duration_s": duration_s,
            "frame_count": self.frame_count,
            "live_hz": self.live_hz,
            "frames_bytes": frames_bytes,
            "has_frames": frames_bytes > 0,
            "risk": _risk_label(risk_score),
            "risk_score": risk_score,
            "analysis": analysis,
        }

    def _current_bucket(self) -> TimelineBucket:
        bucket_index = (self.frame_count - 1) // _TIMELINE_BUCKET_SIZE
        while len(self._timeline) <= bucket_index:
            start_frame = len(self._timeline) * _TIMELINE_BUCKET_SIZE + 1
            self._timeline.append(TimelineBucket(start_frame=start_frame, end_frame=start_frame - 1))
        return self._timeline[bucket_index]

    def _update_timing(self, timestamp_s: float) -> None:
        self._first_t = timestamp_s if self._first_t is None else min(self._first_t, timestamp_s)
        self._last_t = timestamp_s if self._last_t is None else max(self._last_t, timestamp_s)
        if self._previous_t is not None:
            self._max_gap_s = max(self._max_gap_s, max(0.0, timestamp_s - self._previous_t))
        self._previous_t = timestamp_s

    def _score_run(self, *, status: str, anomaly_ratio: float, max_gap_s: float) -> int:
        score = 0
        if anomaly_ratio > 0.1:
            score += 70
        elif anomaly_ratio > 0.02:
            score += 50
        elif anomaly_ratio > 0:
            score += 30

        if max_gap_s > 1.0:
            score += 10
        if status in ("interrupted", "crashed"):
            score += 10
        return min(score, 100)

    def _build_findings(self, anomaly_ratio: float) -> list[str]:
        if not self._anomaly_frames:
            return ["No velocity-spoof detections were found in this run."]

        findings = [f"Velocity spoof was detected in {self._anomaly_frames} frame(s) ({anomaly_ratio:.1%})."]
        for robot_id, robot_stats in sorted(self._robots.items()):
            if robot_stats.velocity_spoof_frames <= 0:
                continue
            dominant_kind = _dominant_kind(robot_stats.velocity_spoof_kind_counts)
            kind_suffix = f" Dominant type: {dominant_kind}." if dominant_kind else ""
            if robot_stats.first_velocity_spoof_t is not None and robot_stats.last_velocity_spoof_t is not None:
                findings.append(
                    f"{robot_id}: detected from t={robot_stats.first_velocity_spoof_t:.2f}s "
                    f"to t={robot_stats.last_velocity_spoof_t:.2f}s "
                    f"({robot_stats.velocity_spoof_frames} frame(s)).{kind_suffix}"
                )
            else:
                findings.append(
                    f"{robot_id}: detected in {robot_stats.velocity_spoof_frames} frame(s).{kind_suffix}"
                )
        return findings


def _has_velocity_spoof(labels: Any) -> bool:
    """Return whether one per-robot scenario payload flags velocity spoofing."""
    return isinstance(labels, dict) and bool(labels.get("velocity_spoof"))


def _velocity_spoof_kind(labels: Any) -> str | None:
    """Return the stored velocity spoof subtype when present."""
    kind = labels.get("velocity_spoof_kind") if isinstance(labels, dict) else None
    return kind if isinstance(kind, str) and kind else None


def _dominant_kind(kind_counts: dict[str, int]) -> str | None:
    """Return the most common spoof subtype, preferring alphabetical order on ties."""
    if not kind_counts:
        return None
    return min(kind_counts.items(), key=lambda item: (-item[1], item[0]))[0]
