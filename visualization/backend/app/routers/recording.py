"""Start, stop, and inspect operator-triggered live recordings."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..live.broadcaster import LiveBroadcaster, get_broadcaster

router = APIRouter()


class RunStartRequest(BaseModel):
    """Operator-supplied metadata for a new live recording."""

    name: str = ""


@router.post("/capture/start")
async def live_run_start(body: RunStartRequest, b: LiveBroadcaster = Depends(get_broadcaster)) -> dict[str, Any]:
    """Begin writing a new recording from the active live MQTT stream."""
    return await b.start_run(name=body.name)


@router.post("/capture/stop")
async def live_run_stop(b: LiveBroadcaster = Depends(get_broadcaster)) -> dict[str, Any]:
    """Stop the active recording and return the persisted metadata document."""
    return await b.stop_run()


@router.get("/capture/active")
def live_run_active(b: LiveBroadcaster = Depends(get_broadcaster)) -> dict[str, Any]:
    """Return the currently active recording, if one exists."""
    return b.get_active_run()
