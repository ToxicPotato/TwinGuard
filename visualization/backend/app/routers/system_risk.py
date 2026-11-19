"""System-wide risk assessment endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..live.broadcaster import LiveBroadcaster, get_broadcaster
from ..risk_engine.system_assessor import compute_live_alerts_only, compute_system_assessment
from .attack import get_attack_status

router = APIRouter()


@router.get("/system")
async def get_system_risk(b: LiveBroadcaster = Depends(get_broadcaster)):
    """Return a full system-wide risk assessment combining live and historical data."""
    live_status = b.get_status()
    live_detection = b.get_live_detection_state()
    live_run_state = b.get_live_run_state()
    runs = [r for r in b.list_runs() if r.get("status") != "active" and r.get("has_frames")]
    attack_status = await get_attack_status()
    return compute_system_assessment(
        runs=runs,
        attack_status=attack_status,
        live_status=live_status,
        live_detection=live_detection,
        live_run_state=live_run_state,
    )


@router.get("/alerts")
async def get_risk_alerts(b: LiveBroadcaster = Depends(get_broadcaster)):
    """Return only active alerts and the live level — no disk reads, for fast polling."""
    attack_status = await get_attack_status()
    live_detection = b.get_live_detection_state()
    live_run_state = b.get_live_run_state()
    return compute_live_alerts_only(
        attack_status=attack_status,
        live_detection=live_detection,
        live_run_state=live_run_state,
    )
