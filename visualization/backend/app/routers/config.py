"""Runtime MQTT configuration - get, update, and test broker connection."""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter()


class MqttConfigResponse(BaseModel):
    host: str
    port: int
    username: Optional[str]
    topic: str
    live_hz: float
    rolling_buffer_max_frames: int
    connected: bool


class MqttConfigUpdate(BaseModel):
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    topic: Optional[str] = None
    live_hz: Optional[float] = Field(default=None, gt=0, le=100)
    rolling_buffer_max_frames: Optional[int] = Field(default=None, ge=60, le=200000)

    @field_validator("topic")
    @classmethod
    def topic_must_end_with_robot_wildcard(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.endswith("/+/#"):
            raise ValueError(
                "Topic must end with /+/# where + marks the robot-id slot "
                "(e.g. vehicle/+/#, site-a/vehicle/+/#)"
            )
        static_prefix = v[: -len("/+/#")]
        if not static_prefix:
            raise ValueError(
                "Topic must include at least one static prefix segment (e.g. vehicle/+/#)"
            )
        if "+" in static_prefix or "#" in static_prefix:
            raise ValueError(
                "Topic prefix before /+/# must be a static path with no wildcards"
            )
        return v


class MqttTestRequest(BaseModel):
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    use_stored_password: bool = False


class MqttTestResponse(BaseModel):
    ok: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None


def mqtt_config_payload(*, connected: bool) -> dict:
    return {
        "host": settings.mqtt_host,
        "port": settings.mqtt_port,
        "username": settings.mqtt_username,
        "topic": settings.mqtt_topic,
        "live_hz": settings.live_hz,
        "rolling_buffer_max_frames": settings.rolling_buffer_max_frames,
        "connected": connected,
    }


@router.get("/mqtt", response_model=MqttConfigResponse)
def get_mqtt_config():
    """Return current MQTT settings (password is never returned)."""
    from ..live.broadcaster import broadcaster

    return MqttConfigResponse(
        **mqtt_config_payload(connected=broadcaster.is_connected())
    )


def _forward_reconnect_to_tamper(body: MqttConfigUpdate) -> str | None:
    """Forward broker settings to the tamper-service. Returns an error string or None on success."""
    import httpx
    # If the user didn't submit a new password, forward the stored one so the
    # tamper-service doesn't lose credentials on unrelated config updates.
    effective_password = body.password if body.password is not None else settings.mqtt_password
    # Derive the tamper-service input_prefix from the backend topic (strip trailing /+/#).
    topic = body.topic if body.topic is not None else settings.mqtt_topic
    input_prefix = topic.removesuffix("/+/#") if topic.endswith("/+/#") else None
    try:
        res = httpx.post(
            f"{settings.tamper_api_url}/reconnect",
            json={"host": body.host, "port": body.port, "username": body.username,
                  "password": effective_password, "input_prefix": input_prefix},
            timeout=5.0,
        )
        data = res.json()
        if not data.get("ok"):
            return data.get("error") or f"tamper-service error (HTTP {res.status_code})"
        return None
    except Exception as exc:
        return str(exc)


@router.patch("/mqtt")
def update_mqtt_config(body: MqttConfigUpdate):
    """Update MQTT settings and reconnect the broker."""
    from ..live.broadcaster import broadcaster

    broker_changed = (
        settings.mqtt_host != body.host
        or settings.mqtt_port != body.port
        or settings.mqtt_username != (body.username or None)
        or (body.password is not None and settings.mqtt_password != (body.password or None))
        or (body.topic is not None and settings.mqtt_topic != body.topic)
    )
    reconnect_needed = broker_changed or (body.live_hz is not None and settings.live_hz != body.live_hz)
    buffer_only_update = (
        not reconnect_needed
        and body.rolling_buffer_max_frames is not None
        and settings.rolling_buffer_max_frames != body.rolling_buffer_max_frames
    )
    settings.mqtt_host = body.host
    settings.mqtt_port = body.port
    settings.mqtt_username = body.username or None
    if body.password is not None:
        settings.mqtt_password = body.password or None
    if body.topic is not None:
        settings.mqtt_topic = body.topic
    if body.live_hz is not None:
        settings.live_hz = body.live_hz
    if body.rolling_buffer_max_frames is not None:
        settings.rolling_buffer_max_frames = body.rolling_buffer_max_frames
        broadcaster.update_rolling_buffer_max_frames()
    ok = True
    tamper_error = None
    if reconnect_needed or (not broadcaster.is_connected() and not buffer_only_update):
        was_disconnected = not broadcaster.is_connected()
        ok = broadcaster.reconnect_mqtt()
        # Sync tamper when broker settings changed, or when the backend just recovered
        # from a disconnected state (tamper may also be disconnected and needs to resync).
        if broker_changed or (was_disconnected and ok):
            tamper_error = _forward_reconnect_to_tamper(body)
    broadcaster.broadcast_config_update()
    if not ok:
        return {"ok": False, "error": "MQTT source could not start - check host and port"}
    if tamper_error:
        log.warning("Tamper-service reconnect failed (settings applied): %s", tamper_error)
        return {"ok": True, "warning": f"Tamper service unreachable: {tamper_error}"}
    return {"ok": True}


@router.post("/mqtt/test", response_model=MqttTestResponse)
async def test_mqtt_connection(body: MqttTestRequest):
    """Attempt a throwaway connection to the broker and return latency or error."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _blocking_test, body)
    return result


def _blocking_test(body: MqttTestRequest) -> MqttTestResponse:
    import threading

    import paho.mqtt.client as mqtt

    connected_event = threading.Event()
    error_rc = [None]
    t_start = time.monotonic()

    def on_connect(client, userdata, flags, rc):
        error_rc[0] = rc
        connected_event.set()

    effective_password = settings.mqtt_password if body.use_stored_password else body.password

    client = mqtt.Client()
    if body.username:
        client.username_pw_set(body.username, effective_password)
    client.on_connect = on_connect

    try:
        client.connect_async(body.host, body.port)
        client.loop_start()
        fired = connected_event.wait(timeout=5.0)
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        return MqttTestResponse(ok=False, error=str(exc))

    if not fired:
        return MqttTestResponse(ok=False, error="Connection timed out after 5 s")

    rc = error_rc[0]
    if rc != 0:
        rc_messages = {
            1: "Refused: incorrect protocol version",
            2: "Refused: invalid client identifier",
            3: "Refused: server unavailable",
            4: "Refused: bad username or password",
            5: "Refused: not authorised",
        }
        return MqttTestResponse(ok=False, error=rc_messages.get(rc, f"Connection refused (rc={rc})"))

    latency_ms = int((time.monotonic() - t_start) * 1000)
    return MqttTestResponse(ok=True, latency_ms=latency_ms)
