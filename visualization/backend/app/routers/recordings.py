"""Read persisted metadata for completed or interrupted live recordings."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..live.broadcaster import LiveBroadcaster, get_broadcaster

router = APIRouter()


def _run_summary(run_meta: dict[str, Any]) -> dict[str, Any]:
    """Project the stored metadata document down to the list-view fields."""
    return {
        "run_id": run_meta.get("run_id"),
        "name": run_meta.get("name", ""),
        "status": run_meta.get("status", "unknown"),
        "started_at": run_meta.get("started_at"),
        "ended_at": run_meta.get("ended_at"),
        "duration_s": run_meta.get("duration_s"),
        "frame_count": int(run_meta.get("frame_count") or 0),
        "live_hz": run_meta.get("live_hz"),
        "frames_bytes": int(run_meta.get("frames_bytes") or 0),
        "has_frames": bool(run_meta.get("has_frames", False)),
        "risk": run_meta.get("risk", "low"),
        "risk_score": int(run_meta.get("risk_score") or 0),
    }


def _load_all_summaries(b: LiveBroadcaster) -> list[dict[str, Any]]:
    return [_run_summary(meta) for meta in b.list_runs()]


@router.get("/status")
def get_recordings_status(b: LiveBroadcaster = Depends(get_broadcaster)):
    rec_dir = Path(settings.live_recordings_dir)
    if not rec_dir.exists():
        return {
            "status": "missing",
            "message": f"Recording directory not found: {rec_dir}",
            "run_count": 0,
            "usable_run_count": 0,
            "total_bytes": 0,
            "disk_free_bytes": None,
            "disk_total_bytes": None,
        }

    summaries = _load_all_summaries(b)
    usable = [s for s in summaries if s["has_frames"]]
    total_bytes = sum(s["frames_bytes"] for s in summaries)
    disk = shutil.disk_usage(rec_dir)
    base = {
        "run_count": len(summaries),
        "usable_run_count": len(usable),
        "total_bytes": total_bytes,
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
    }
    if not summaries:
        return {"status": "empty", "message": "No captures recorded yet.", **base}
    return {
        "status": "ready",
        "message": f"{len(usable)} valid capture(s) ready for analysis.",
        **base,
    }


@router.get("")
def list_recordings(b: LiveBroadcaster = Depends(get_broadcaster)):
    summaries = _load_all_summaries(b)
    return {"runs": [s for s in summaries if s["has_frames"]]}


@router.delete("/{run_id}")
def delete_recording(run_id: str, b: LiveBroadcaster = Depends(get_broadcaster)):
    deleted = b.delete_run(run_id)
    if not deleted:
        raise HTTPException(404, f"Recording '{run_id}' not found")
    return {"deleted": True, "run_id": run_id}


@router.get("/{run_id}")
def analyze_recording(run_id: str, b: LiveBroadcaster = Depends(get_broadcaster)):
    """Return the full materialized metadata document for one recording."""
    run_meta = b.get_run_meta(run_id)
    if run_meta is None:
        raise HTTPException(404, f"Run '{run_id}' not found")
    return run_meta
