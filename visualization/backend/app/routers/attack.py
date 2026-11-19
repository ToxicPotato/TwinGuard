"""Attack control - HTTP proxy to the tamper-service REST API."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import settings

router = APIRouter()

_TIMEOUT = 5.0


def _tamper_base() -> str:
    return settings.tamper_api_url


@dataclass
class _AttackContext:
    """Tracks pending attack for display purposes."""

    fires_at: float | None = None
    follower: str | None = None
    target: str | None = None


@dataclass
class _VelocitySpoofContext:
    """Tracks pending velocity-spoof attack for display purposes."""

    fires_at: float | None = None
    follower: str | None = None
    target: str | None = None
    mode: str | None = None
    speed_mps: float | None = None
    speed_start: float | None = None
    speed_end: float | None = None


_ctx = _AttackContext()
_vs_ctx = _VelocitySpoofContext()


class FalseBrakeRequest(BaseModel):
    duration_s: float = Field(gt=0, le=60)
    delay_s: float = Field(default=0.0, ge=0, le=300)
    follower_robot: Optional[str] = None
    target_robot: Optional[str] = None


class VelocitySpoofRequest(BaseModel):
    mode: Literal["static", "ramp"] = "static"
    speed_mps: Optional[float] = Field(default=None, ge=-20, le=20)
    speed_start: Optional[float] = Field(default=None, ge=-20, le=20)
    speed_end: Optional[float] = Field(default=None, ge=-20, le=20)
    duration_s: float = Field(gt=0, le=120)
    delay_s: float = Field(default=0.0, ge=0, le=300)
    follower_robot: Optional[str] = None
    target_robot: Optional[str] = None


def _clear_false_brake_context() -> None:
    _ctx.fires_at = None
    _ctx.follower = None
    _ctx.target = None


def _clear_velocity_spoof_context() -> None:
    _vs_ctx.fires_at = None
    _vs_ctx.follower = None
    _vs_ctx.target = None
    _vs_ctx.mode = None
    _vs_ctx.speed_mps = None
    _vs_ctx.speed_start = None
    _vs_ctx.speed_end = None


def _false_brake_display_status(
    *,
    now: float,
    active: bool,
    remaining_s: float,
    status_target_robot: str | None,
    tamper_pending: bool,
    tamper_fires_in_s: float,
) -> dict[str, object]:
    if active:
        return {
            "status": "active",
            "remaining_s": round(remaining_s, 1),
            "follower": _ctx.follower,
            "target_robot": _ctx.target or status_target_robot,
        }
    if tamper_pending:
        return {
            "status": "pending",
            "fires_in_s": round(tamper_fires_in_s, 1),
            "follower": _ctx.follower,
            "target_robot": _ctx.target or status_target_robot,
        }
    if _ctx.fires_at is not None and _ctx.fires_at > now:
        return {
            "status": "pending",
            "fires_in_s": round(max(0.0, _ctx.fires_at - now), 1),
            "follower": _ctx.follower,
            "target_robot": _ctx.target,
        }

    return {"status": "idle", "follower": None, "target_robot": None}


def _velocity_spoof_display_status(
    *,
    now: float,
    active: bool,
    remaining_s: float,
    status_target_robot: str | None,
    speed_mps: float | None,
    mode: str | None,
    speed_start: float | None,
    speed_end: float | None,
    tamper_pending: bool,
    tamper_fires_in_s: float,
) -> dict[str, object]:
    if active:
        return {
            "status": "active",
            "remaining_s": round(remaining_s, 1),
            "follower": _vs_ctx.follower,
            "target_robot": _vs_ctx.target or status_target_robot,
            "speed_mps": speed_mps,
            "mode": mode,
            "speed_start": speed_start,
            "speed_end": speed_end,
        }
    if tamper_pending:
        return {
            "status": "pending",
            "fires_in_s": round(tamper_fires_in_s, 1),
            "follower": _vs_ctx.follower,
            "target_robot": _vs_ctx.target or status_target_robot,
            "speed_mps": _vs_ctx.speed_mps,
            "mode": _vs_ctx.mode,
            "speed_start": _vs_ctx.speed_start,
            "speed_end": _vs_ctx.speed_end,
        }
    if _vs_ctx.fires_at is not None and _vs_ctx.fires_at > now:
        return {
            "status": "pending",
            "fires_in_s": round(max(0.0, _vs_ctx.fires_at - now), 1),
            "follower": _vs_ctx.follower,
            "target_robot": _vs_ctx.target,
            "speed_mps": _vs_ctx.speed_mps,
            "mode": _vs_ctx.mode,
            "speed_start": _vs_ctx.speed_start,
            "speed_end": _vs_ctx.speed_end,
        }

    return {
        "status": "idle",
        "follower": None,
        "target_robot": None,
        "speed_mps": None,
        "mode": None,
        "speed_start": None,
        "speed_end": None,
    }


def _top_level_status(
    false_brake: dict[str, object],
    velocity_spoof: dict[str, object],
) -> dict[str, object]:
    """Return the legacy top-level summary consumed by older frontends.

    Always surfaces false-brake fields at the top level so AttackPanel.svelte
    continues to interpret status/follower/target_robot as false-brake state.
    Velocity-spoof state is available exclusively under the 'velocity_spoof' key.
    """
    return false_brake


@router.get("/status")
async def get_attack_status():
    """Return attack state for all attack types."""

    now = time.monotonic()

    fb_active = False
    fb_remaining_s = 0.0
    fb_tamper_pending = False
    fb_tamper_fires_in_s = 0.0
    vs_active = False
    vs_remaining_s = 0.0
    vs_speed_mps: float | None = None
    vs_mode: str | None = None
    vs_speed_start: float | None = None
    vs_speed_end: float | None = None
    fb_target_robot: str | None = None
    vs_target_robot: str | None = None
    vs_tamper_pending = False
    vs_tamper_fires_in_s = 0.0

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.get(f"{_tamper_base()}/status")
            data = res.json()
        fb_active = data.get("false_brake_active", False)
        fb_remaining_s = data.get("false_brake_remaining_s", 0.0)
        fb_tamper_pending = data.get("false_brake_pending", False)
        fb_tamper_fires_in_s = data.get("false_brake_fires_in_s", 0.0)
        fb_target_robot = data.get("false_brake_target_robot_id")
        vs_active = data.get("slowdown_active", False)
        vs_remaining_s = data.get("slowdown_remaining_s", 0.0)
        vs_speed_mps = data.get("slowdown_speed_mps")
        vs_mode = data.get("slowdown_mode")
        vs_speed_start = data.get("slowdown_speed_start")
        vs_speed_end = data.get("slowdown_speed_end")
        vs_tamper_pending = data.get("velocity_spoof_pending", False)
        vs_tamper_fires_in_s = data.get("velocity_spoof_fires_in_s", 0.0)
        vs_target_robot = data.get("slowdown_target_robot_id")
    except Exception:
        pass

    fb_status = _false_brake_display_status(
        now=now,
        active=fb_active,
        remaining_s=fb_remaining_s,
        status_target_robot=fb_target_robot,
        tamper_pending=fb_tamper_pending,
        tamper_fires_in_s=fb_tamper_fires_in_s,
    )
    if fb_status["status"] == "active":
        _ctx.fires_at = None   # pending window is over — attack has started
    elif fb_status["status"] == "idle":
        _clear_false_brake_context()

    vs_status = _velocity_spoof_display_status(
        now=now,
        active=vs_active,
        remaining_s=vs_remaining_s,
        status_target_robot=vs_target_robot,
        speed_mps=vs_speed_mps,
        mode=vs_mode,
        speed_start=vs_speed_start,
        speed_end=vs_speed_end,
        tamper_pending=vs_tamper_pending,
        tamper_fires_in_s=vs_tamper_fires_in_s,
    )
    if vs_status["status"] == "active":
        _vs_ctx.fires_at = None
    elif vs_status["status"] == "idle":
        _clear_velocity_spoof_context()

    return {
        **_top_level_status(fb_status, vs_status),
        "false_brake": fb_status,
        "velocity_spoof": vs_status,
    }


@router.post("/velocity_spoof")
async def trigger_velocity_spoof(body: VelocitySpoofRequest):
    """Forward a velocity-spoof trigger to the tamper-service."""

    now = time.monotonic()
    _vs_ctx.fires_at = now + body.delay_s
    _vs_ctx.follower = body.follower_robot
    _vs_ctx.target = body.target_robot
    _vs_ctx.mode = body.mode
    _vs_ctx.speed_mps = body.speed_mps
    _vs_ctx.speed_start = body.speed_start
    _vs_ctx.speed_end = body.speed_end

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(
                f"{_tamper_base()}/velocity_override",
                json={
                    "mode": body.mode,
                    "speed_mps": body.speed_mps,
                    "speed_start": body.speed_start,
                    "speed_end": body.speed_end,
                    "duration_s": body.duration_s,
                    "delay_s": body.delay_s,
                    "target_robot": body.target_robot,
                },
            )
            data = res.json()
        if not data.get("ok"):
            _clear_velocity_spoof_context()
            # Normalize non-standard error shapes (e.g. FastAPI 422 validation)
            # to the {"ok": bool} contract the React UI expects.
            if "ok" not in data:
                detail = data.get("detail", data)
                return {"ok": False, "error": detail if isinstance(detail, str) else str(detail)}
        return data
    except Exception as exc:
        _clear_velocity_spoof_context()
        return {"ok": False, "error": str(exc)}


@router.post("/false_brake")
async def trigger_false_brake(body: FalseBrakeRequest):
    """Forward a false-brake trigger to the tamper-service and record context."""

    now = time.monotonic()
    _ctx.fires_at = now + body.delay_s
    _ctx.follower = body.follower_robot
    _ctx.target = body.target_robot

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(
                f"{_tamper_base()}/false_brake",
                json={
                    "duration_s": body.duration_s,
                    "delay_s": body.delay_s,
                    "target_robot": body.target_robot,
                },
            )
            data = res.json()
        if not data.get("ok"):
            _clear_false_brake_context()
            if "ok" not in data:
                detail = data.get("detail", data)
                return {"ok": False, "error": detail if isinstance(detail, str) else str(detail)}
        return data
    except Exception as exc:
        _clear_false_brake_context()
        return {"ok": False, "error": str(exc)}


@router.post("/reset")
async def reset_attack():
    """Forward a reset to the tamper-service and clear local context."""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(f"{_tamper_base()}/reset")
            data = res.json()
        if data.get("ok"):
            _clear_false_brake_context()
            _clear_velocity_spoof_context()
        return data
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/false_brake/stop")
async def stop_false_brake():
    """Stop false-brake without affecting other attack types."""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(f"{_tamper_base()}/false_brake/stop")
            data = res.json()
        if data.get("ok"):
            _clear_false_brake_context()
        return data
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/velocity_spoof/stop")
async def stop_velocity_spoof():
    """Stop velocity spoof without affecting other attack types."""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            res = await client.post(f"{_tamper_base()}/velocity_override/stop")
            data = res.json()
        if data.get("ok"):
            _clear_velocity_spoof_context()
        return data
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
