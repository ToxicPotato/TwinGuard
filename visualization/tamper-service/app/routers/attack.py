"""Attack control routes — /status, /false_brake, /velocity_override, /reset."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from ..deps import controller

router = APIRouter()


class FalseBrakeRequest(BaseModel):
    duration_s: float = Field(gt=0, le=60)
    target_robot: str | None = None
    delay_s: float = Field(default=0.0, ge=0, le=300)


class VelocityOverrideRequest(BaseModel):
    mode: str = "static"                                             # 'static' | 'ramp'
    speed_mps: float | None = Field(default=None, ge=-20, le=20)   # static mode
    speed_start: float | None = Field(default=None, ge=-20, le=20) # ramp mode
    speed_end: float | None = Field(default=None, ge=-20, le=20)   # ramp mode
    duration_s: float = Field(gt=0, le=120)
    target_robot: str | None = None
    delay_s: float = Field(default=0.0, ge=0, le=300)

    @model_validator(mode="after")
    def check_mode_params(self) -> "VelocityOverrideRequest":
        if self.mode == "static":
            if self.speed_mps is None:
                raise ValueError("mode='static' requires speed_mps")
        elif self.mode == "ramp":
            if self.speed_start is None or self.speed_end is None:
                raise ValueError("mode='ramp' requires both speed_start and speed_end")
        else:
            raise ValueError(f"mode must be 'static' or 'ramp', got {self.mode!r}")
        return self


@router.get("/status")
def get_status():
    return controller.get_status()


@router.post("/false_brake")
def trigger_false_brake(body: FalseBrakeRequest):
    controller.trigger_false_brake(body.duration_s, body.target_robot, body.delay_s)
    return {"ok": True}


@router.post("/velocity_override")
def trigger_velocity_override(body: VelocityOverrideRequest):
    controller.trigger_velocity_spoof(
        mode=body.mode,
        duration_s=body.duration_s,
        target_robot=body.target_robot,
        delay_s=body.delay_s,
        speed_mps=body.speed_mps,
        speed_start=body.speed_start,
        speed_end=body.speed_end,
    )
    return {"ok": True}


@router.post("/reset")
def reset():
    controller.reset()
    return {"ok": True}


@router.post("/false_brake/stop")
def stop_false_brake():
    controller.stop_false_brake()
    return {"ok": True}


@router.post("/velocity_override/stop")
def stop_velocity_override():
    controller.stop_velocity_spoof()
    return {"ok": True}
