"""Configuration routes — /reconnect."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import service

router = APIRouter()


class ReconnectRequest(BaseModel):
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    input_prefix: str | None = None  # static topic prefix, e.g. "vehicle" or "site-a/vehicle"


@router.post("/reconnect")
def reconnect(body: ReconnectRequest):
    try:
        service.reconnect(body.host, body.port, body.username, body.password, body.input_prefix)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
