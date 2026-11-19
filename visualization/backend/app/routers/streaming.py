"""WebSocket and REST endpoints for the live MQTT data feed.

Covers connection status and the rolling frame buffer used for client catch-up.
Recording of named runs is handled separately in recording.py.
"""

from typing import Any

from fastapi import APIRouter, Depends, WebSocket

from ..live.broadcaster import LiveBroadcaster, broadcaster, get_broadcaster

# Re-export so main.py and routers/config.py can import broadcaster from here
__all__ = ["broadcaster", "router"]

router = APIRouter()
ws_router = APIRouter()


@router.get("/status")
def live_status(b: LiveBroadcaster = Depends(get_broadcaster)) -> dict[str, Any]:
    return b.get_status()


@router.get("/buffer")
def live_buffer(limit: int | None = None, b: LiveBroadcaster = Depends(get_broadcaster)) -> dict[str, Any]:
    return b.get_buffer_snapshot(limit=limit)


@ws_router.websocket("/ws/live")
async def ws_live(ws: WebSocket, b: LiveBroadcaster = Depends(get_broadcaster)) -> None:
    await b.connect(ws)
