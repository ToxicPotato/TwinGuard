"""Serve enriched live frames and persist operator-triggered recordings."""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from ..config import settings
from ..deps import get_runner
from ..risk_engine.live_extractor import derive_nist_findings
from .run_accumulator import RunAccumulator
from ..routers.config import mqtt_config_payload

log = logging.getLogger(__name__)


@dataclass(slots=True)
class InterruptedRunState:
    """State needed to finalize a recording after an unexpected disconnect."""

    run_id: str
    accumulator: RunAccumulator
    file_path: str


class LiveBroadcaster:
    """Poll MQTT, enrich frames, broadcast to clients, and write recordings."""

    def __init__(self, runner=None) -> None:
        self._runner = runner if runner is not None else get_runner()
        self._clients: set[WebSocket] = set()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._consumer_task: asyncio.Task | None = None
        self._frame_source = None
        self._poll_stop: threading.Event = threading.Event()
        self._lock = threading.Lock()
        self._session_id: str | None = None
        self._session_started_at: float | None = None
        self._last_frame_id = 0
        self._rolling_buffer: deque[dict[str, Any]] = deque()
        self._source_epoch = 0
        self._active_epoch_counts: dict[int, int] = {}
        # Per-socket send lock to serialize concurrent _broadcast() calls.
        self._send_locks: dict[WebSocket, asyncio.Lock] = {}
        # Recording state is mutated only while holding self._lock.
        self._run_id: str | None = None
        self._run_name: str | None = None
        self._run_started_at: float | None = None
        self._run_frame_counter: int = 0
        self._run_active: bool = False
        self._run_file_path: str | None = None
        self._run_file: Any = None
        self._run_accumulator: RunAccumulator | None = None
        self._pending_interrupted_run: InterruptedRunState | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._consumer_task = asyncio.create_task(self._consume_frames())
        self._start_mqtt_polling()
        log.info("LiveBroadcaster started (%.0f Hz)", settings.live_hz)

    async def stop(self) -> None:
        source_epoch = self._source_epoch
        self._poll_stop.set()
        if self._frame_source is not None:
            try:
                self._frame_source.stop()
            except Exception as exc:
                log.warning("Error stopping MQTT source during shutdown: %s", exc)
            self._frame_source = None
        await self._drain_source_epoch(source_epoch)
        with self._lock:
            self._close_current_connection_locked()
            self._clear_live_state_locked()
        if self._pending_interrupted_run is not None:
            await self._finalize_interrupted_run()
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

    def _start_mqtt_polling(self) -> bool:
        try:
            from python.ingestion.mqtt_ingestion import MqttFrameSource

            with self._lock:
                self._source_epoch += 1
                source_epoch = self._source_epoch
            self._frame_source = MqttFrameSource(
                host=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
                topic=settings.mqtt_topic,
            )
            self._frame_source.start()
            with self._lock:
                self._begin_new_connection_locked()
            stop = threading.Event()
            self._poll_stop = stop
            interval = 1.0 / settings.live_hz
            t = threading.Thread(target=self._poll_forever, args=(interval, stop, source_epoch), daemon=True)
            t.start()
            self._broadcast_meta_update()
            self.broadcast_config_update()
            return True
        except Exception as exc:
            self._frame_source = None
            log.warning("MQTT not available - live mode disabled: %s", exc)
            return False

    def reconnect_mqtt(self) -> bool:
        source_epoch = self._source_epoch
        self._poll_stop.set()
        if self._frame_source is not None:
            try:
                self._frame_source.stop()
            except Exception as exc:
                log.warning("Error stopping MQTT source during reconnect: %s", exc)
            self._frame_source = None
        self._drain_source_epoch_sync(source_epoch)
        with self._lock:
            self._close_current_connection_locked()
            self._clear_live_state_locked()
        if self._pending_interrupted_run is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(
                asyncio.create_task, self._finalize_interrupted_run()
            )
        ok = self._start_mqtt_polling()
        if not ok:
            self._broadcast_meta_update()
            self.broadcast_config_update()
        return ok

    def _poll_forever(self, interval_s: float, stop: threading.Event, source_epoch: int) -> None:
        source = self._frame_source
        while not stop.is_set():
            t0 = time.monotonic()
            frame = source.build_frame(t=t0)
            if frame is not None:
                self._enqueue(frame, source_epoch)
            time.sleep(max(0.0, interval_s - (time.monotonic() - t0)))

    def _enqueue(self, frame, source_epoch: int) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._put_nowait, source_epoch, frame)

    def _put_nowait(self, source_epoch: int, frame) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait((source_epoch, frame))
        except asyncio.QueueFull:
            pass

    def _queue_has_epoch_locked(self, source_epoch: int) -> bool:
        return any(item_epoch == source_epoch for item_epoch, _ in list(self._queue._queue))

    async def _drain_source_epoch(self, source_epoch: int) -> None:
        while True:
            with self._lock:
                active_count = self._active_epoch_counts.get(source_epoch, 0)
                queued = self._queue_has_epoch_locked(source_epoch)
            if active_count == 0 and not queued:
                return
            await asyncio.sleep(0.01)

    def _drain_source_epoch_sync(self, source_epoch: int) -> None:
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._drain_source_epoch(source_epoch), self._loop)
        future.result()

    def _known_robots(self) -> list[str]:
        if self._frame_source is None:
            return []
        try:
            return self._frame_source.known_robots()
        except Exception:
            return []

    def is_connected(self) -> bool:
        return self._frame_source is not None

    def _recording_dir(self) -> str:
        return settings.live_recordings_dir

    def _ensure_recording_dir(self) -> None:
        os.makedirs(settings.live_recordings_dir, exist_ok=True)

    def _run_frames_path(self, run_id: str) -> str:
        return os.path.join(self._recording_dir(), f"{run_id}.jsonl")

    def _run_meta_path(self, run_id: str) -> str:
        return os.path.join(self._recording_dir(), f"{run_id}.meta.json")

    def _safe_run_id(self, run_id: str) -> str:
        try:
            parsed = uuid.UUID(run_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(404, f"Run '{run_id}' not found") from exc
        normalized = str(parsed)
        if normalized != run_id:
            raise HTTPException(404, f"Run '{run_id}' not found")
        return normalized

    def _begin_new_connection_locked(self) -> None:
        self._session_id = str(uuid.uuid4())
        self._session_started_at = time.time()
        self._last_frame_id = 0
        self._rolling_buffer.clear()

    def _close_current_connection_locked(self) -> None:
        if self._run_active:
            if self._run_file is not None:
                try:
                    self._run_file.flush()
                    self._run_file.close()
                except Exception as exc:
                    log.warning("Error closing capture file on disconnect: %s", exc)
                self._run_file = None
            if self._run_id and self._run_accumulator and self._run_file_path:
                self._pending_interrupted_run = InterruptedRunState(
                    run_id=self._run_id,
                    accumulator=self._run_accumulator,
                    file_path=self._run_file_path,
                )
            self._run_active = False
            self._run_id = None
            self._run_name = None
            self._run_started_at = None
            self._run_file_path = None
            self._run_frame_counter = 0
            self._run_accumulator = None

    def _clear_live_state_locked(self) -> None:
        self._session_id = None
        self._session_started_at = None
        self._last_frame_id = 0
        self._rolling_buffer.clear()

    def _trim_rolling_buffer_locked(self) -> None:
        max_frames = max(1, int(settings.rolling_buffer_max_frames))
        while len(self._rolling_buffer) > max_frames:
            self._rolling_buffer.popleft()

    def update_rolling_buffer_max_frames(self) -> None:
        with self._lock:
            self._trim_rolling_buffer_locked()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session_id": self._session_id,
                "connected": self._frame_source is not None,
                "started_at": self._session_started_at,
                "last_frame_id": self._last_frame_id,
                "rolling_buffer_size": len(self._rolling_buffer),
                "rolling_buffer_max_frames": settings.rolling_buffer_max_frames,
                "live_hz": settings.live_hz,
                "robots": self._known_robots(),
            }

    def get_buffer_snapshot(self, limit: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._frame_source is None or self._session_id is None:
                return {
                    "session_id": None,
                    "started_at": None,
                    "last_frame_id": 0,
                    "live_hz": settings.live_hz,
                    "robots": [],
                    "frames": [],
                    "connected": False,
                }
            frames = list(self._rolling_buffer)
            if limit is not None:
                frames = frames[-max(1, int(limit)):]
            return {
                "session_id": self._session_id,
                "started_at": self._session_started_at,
                "last_frame_id": self._last_frame_id,
                "live_hz": settings.live_hz,
                "robots": self._known_robots(),
                "frames": frames,
                "connected": True,
            }

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._send_locks[ws] = asyncio.Lock()
        self._clients.add(ws)
        log.info("Client connected (%d total)", len(self._clients))
        try:
            async with self._send_locks[ws]:
                await self._send_meta(ws)
                await self._send_config(ws)
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(ws)
            self._send_locks.pop(ws, None)
            log.info("Client disconnected (%d remaining)", len(self._clients))

    def _meta_payload(self) -> str:
        status = self.get_status()
        return json.dumps({
            "type": "meta",
            "session_id": status["session_id"],
            "robots": status["robots"],
            "live_hz": status["live_hz"],
            "last_frame_id": status["last_frame_id"],
            "connected": status["connected"],
        })

    async def _send_meta(self, ws: WebSocket) -> None:
        try:
            await ws.send_text(self._meta_payload())
        except Exception:
            pass

    async def _send_config(self, ws: WebSocket) -> None:
        try:
            await ws.send_text(json.dumps({
                "type": "config",
                "data": mqtt_config_payload(connected=self._frame_source is not None),
            }))
        except Exception:
            pass

    async def _consume_frames(self) -> None:
        while True:
            source_epoch, frame = await self._queue.get()
            try:
                with self._lock:
                    self._active_epoch_counts[source_epoch] = self._active_epoch_counts.get(source_epoch, 0) + 1
                    if source_epoch != self._source_epoch:
                        continue
                enriched = self._runner.enrich_frame(frame)
                envelope = self._store_frame(enriched)
                if self._clients:
                    payload = json.dumps({"type": "frame", "data": envelope})
                    await self._broadcast(payload)
            except Exception as exc:
                log.warning("Frame enrichment failed: %s", exc, exc_info=True)
            finally:
                with self._lock:
                    next_count = self._active_epoch_counts.get(source_epoch, 0) - 1
                    if next_count > 0:
                        self._active_epoch_counts[source_epoch] = next_count
                    else:
                        self._active_epoch_counts.pop(source_epoch, None)
                self._queue.task_done()

    def _store_frame(self, enriched: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._session_id is None:
                self._begin_new_connection_locked()
            self._last_frame_id += 1
            envelope = {
                "session_id": self._session_id,
                "frame_id": self._last_frame_id,
                "data": enriched,
            }
            self._rolling_buffer.append(envelope)
            self._trim_rolling_buffer_locked()
            if self._run_active and self._run_id and self._run_file is not None:
                next_frame_id = self._run_frame_counter + 1
                run_envelope = {
                    "run_id": self._run_id,
                    "frame_id": next_frame_id,
                    "data": enriched,
                }
                wrote_frame = False
                try:
                    self._run_file.write(json.dumps(run_envelope, separators=(",", ":")) + "\n")
                    self._run_file.flush()
                    self._run_frame_counter = next_frame_id
                    wrote_frame = True
                except Exception as exc:
                    log.warning("Failed to write capture frame for run %s: %s", self._run_id, exc)
                if wrote_frame and self._run_accumulator is not None:
                    self._run_accumulator.consume_frame(enriched)
            return envelope

    async def _broadcast(self, message: str) -> None:
        if not self._clients:
            return
        clients = list(self._clients)

        async def _send_one(ws: WebSocket) -> None:
            lock = self._send_locks.get(ws)
            if lock is None:
                return
            async with lock:
                await ws.send_text(message)

        results = await asyncio.gather(
            *[_send_one(ws) for ws in clients],
            return_exceptions=True,
        )
        dead: set[WebSocket] = {
            ws for ws, result in zip(clients, results)
            if isinstance(result, Exception)
        }
        self._clients -= dead
        for ws in dead:
            self._send_locks.pop(ws, None)

    def _broadcast_meta_update(self) -> None:
        if self._loop is None:
            return
        payload = self._meta_payload()
        self._loop.call_soon_threadsafe(asyncio.create_task, self._broadcast(payload))

    def broadcast_config_update(self) -> None:
        if self._loop is None:
            return
        payload = json.dumps({
            "type": "config",
            "data": mqtt_config_payload(connected=self._frame_source is not None),
        })
        self._loop.call_soon_threadsafe(asyncio.create_task, self._broadcast(payload))

    # ── Run recording ─────────────────────────────────────────────────────────

    async def start_run(self, name: str = "") -> dict[str, Any]:
        self._ensure_recording_dir()
        with self._lock:
            if self._frame_source is None:
                raise HTTPException(409, "No active MQTT connection — cannot start a capture")
            if self._run_active:
                raise HTTPException(409, f"Capture '{self._run_id}' is already active")
            run_id = str(uuid.uuid4())
            run_file_path = self._run_frames_path(run_id)
            try:
                run_file = open(run_file_path, "w", encoding="utf-8")
            except Exception as exc:
                raise HTTPException(500, f"Could not create capture file: {exc}") from exc
            self._run_id = run_id
            self._run_name = name
            self._run_started_at = time.time()
            self._run_frame_counter = 0
            self._run_file_path = run_file_path
            self._run_file = run_file
            self._run_accumulator = RunAccumulator(
                run_id=run_id,
                name=name,
                started_at=self._run_started_at,
                live_hz=settings.live_hz,
            )
            self._run_active = True
            started_at = self._run_started_at

        self._runner.reset()

        # Persist a minimal marker immediately so interrupted runs remain discoverable.
        initial_meta = {
            "run_id": run_id,
            "name": name,
            "started_at": started_at,
            "status": "active",
            "live_hz": settings.live_hz,
            "frame_count": 0,
        }
        try:
            await asyncio.to_thread(self._write_run_meta, initial_meta, run_id)
        except Exception as exc:
            # Roll back fully so a failed metadata write never leaves recording state half-open.
            with self._lock:
                self._run_active = False
                self._run_id = None
                self._run_name = None
                self._run_started_at = None
                self._run_frame_counter = 0
                self._run_file_path = None
                self._run_accumulator = None
                fh = self._run_file
                self._run_file = None
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
            try:
                os.remove(run_file_path)
            except Exception:
                pass
            raise HTTPException(500, f"Could not write capture metadata: {exc}") from exc
        return {"run_id": run_id, "name": name, "started_at": started_at}

    async def stop_run(self, status: str = "completed") -> dict[str, Any]:
        with self._lock:
            if not self._run_active:
                raise HTTPException(409, "No active capture")
            run_id = self._run_id
            run_name = self._run_name or ""
            started_at = self._run_started_at
            accumulator = self._run_accumulator
            file_path = self._run_file_path
            run_file = self._run_file
            self._run_active = False
            self._run_id = None
            self._run_name = None
            self._run_started_at = None
            self._run_file_path = None
            self._run_file = None
            self._run_frame_counter = 0
            self._run_accumulator = None

        if run_file is not None:
            try:
                run_file.flush()
                run_file.close()
            except Exception as exc:
                log.warning("Error closing capture file on stop: %s", exc)

        ended_at = time.time()
        if accumulator is None or run_id is None or started_at is None or file_path is None:
            raise HTTPException(500, f"Capture '{run_name}' ended in an invalid state")
        return await asyncio.to_thread(self._finalize_run, accumulator, file_path, ended_at, status)

    def _write_run_meta(self, meta: dict, run_id: str) -> None:
        with open(self._run_meta_path(run_id), "w", encoding="utf-8") as f:
            json.dump(meta, f, separators=(",", ":"))

    def _finalize_run(
        self,
        accumulator: RunAccumulator,
        file_path: str,
        ended_at: float,
        status: str,
    ) -> dict[str, Any]:
        frames_bytes = int(os.path.getsize(file_path)) if os.path.exists(file_path) else 0
        meta = accumulator.finalize(ended_at=ended_at, status=status, frames_bytes=frames_bytes)
        analysis = meta.get("analysis")
        if isinstance(analysis, dict):
            try:
                meta["nist_findings"] = derive_nist_findings(accumulator.run_id, meta, analysis)
            except Exception as exc:
                log.warning("Failed to derive NIST findings for run %s: %s", accumulator.run_id, exc)
        self._write_run_meta(meta, accumulator.run_id)
        return meta

    def _recover_orphaned_run(self, run_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        """Finalize a recording that was left in the initial active state after a process restart."""
        file_path = Path(self._run_frames_path(run_id))
        started_at = meta.get("started_at")
        if not isinstance(started_at, (int, float)):
            raise ValueError(f"Run '{run_id}' is missing a valid started_at timestamp")

        accumulator = RunAccumulator.from_recording_file(
            run_id=run_id,
            name=str(meta.get("name") or ""),
            started_at=float(started_at),
            live_hz=float(meta.get("live_hz") or settings.live_hz),
            recording_path=file_path,
        )
        ended_at = file_path.stat().st_mtime if file_path.exists() else time.time()
        return self._finalize_run(accumulator, str(file_path), ended_at, "crashed")

    async def _finalize_interrupted_run(self) -> None:
        info = self._pending_interrupted_run
        self._pending_interrupted_run = None
        if info is None:
            return
        try:
            await asyncio.to_thread(self._finalize_run, info.accumulator, info.file_path, time.time(), "interrupted")
        except Exception as exc:
            log.warning("Failed to finalize interrupted capture %s: %s", info.run_id, exc)

    def get_live_detection_state(self, scan_frames: int = 60) -> dict[str, Any]:
        """Scan the rolling buffer for velocity_spoof labels in recent enriched frames."""
        with self._lock:
            connected = self._frame_source is not None
            session_id = self._session_id
            if not connected or not self._rolling_buffer:
                return {"connected": connected, "session_id": session_id, "attacks": []}
            recent = list(self._rolling_buffer)[-max(1, scan_frames):]

        robot_timestamps: dict[str, list[float]] = {}
        for envelope in recent:
            data = envelope.get("data") or {}
            per_robot = (data.get("scenario") or {}).get("per_robot") or {}
            t = data.get("t")
            if not isinstance(per_robot, dict):
                continue
            for robot_id, labels in per_robot.items():
                if isinstance(labels, dict) and labels.get("velocity_spoof"):
                    bucket = robot_timestamps.setdefault(robot_id, [])
                    if isinstance(t, (int, float)):
                        bucket.append(float(t))

        if not robot_timestamps:
            return {"connected": connected, "session_id": session_id, "attacks": []}

        all_ts = [t for times in robot_timestamps.values() for t in times]
        return {
            "connected": connected,
            "session_id": session_id,
            "attacks": [{
                "attack_type": "velocity_spoof",
                "robots": sorted(robot_timestamps.keys()),
                "first_seen_at": min(all_ts) if all_ts else None,
                "last_seen_at": max(all_ts) if all_ts else None,
                "frame_count": sum(len(v) for v in robot_timestamps.values()),
                "per_robot_frames": {k: len(v) for k, v in robot_timestamps.items()},
            }],
        }

    def get_live_run_state(self) -> dict[str, Any] | None:
        """Return in-progress accumulator stats, or None if no active run."""
        with self._lock:
            if not self._run_active or self._run_accumulator is None:
                return None
            return self._run_accumulator.running_stats()

    def get_active_run(self) -> dict[str, Any]:
        with self._lock:
            if not self._run_active:
                return {"active": False}
            return {
                "active": True,
                "run_id": self._run_id,
                "name": self._run_name,
                "started_at": self._run_started_at,
                "frame_count": self._run_frame_counter,
            }

    def list_runs(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        rec_dir = self._recording_dir()
        if not os.path.exists(rec_dir):
            return out
        with self._lock:
            current_run_id = self._run_id if self._run_active else None
        for name in os.listdir(rec_dir):
            if not name.endswith(".meta.json"):
                continue
            try:
                with open(os.path.join(rec_dir, name), "r", encoding="utf-8") as f:
                    meta = json.load(f)
                run_id = meta.get("run_id") or ""
                if meta.get("status") == "active" and run_id != current_run_id:
                    meta = self._recover_orphaned_run(run_id, meta)
                out.append(meta)
            except Exception as exc:
                log.warning("Could not read run metadata %s: %s", name, exc)
        out.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
        return out

    def get_run_meta(self, run_id: str) -> dict[str, Any] | None:
        safe_id = self._safe_run_id(run_id)
        meta_path = self._run_meta_path(safe_id)
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with self._lock:
            current_run_id = self._run_id if self._run_active else None
        if meta.get("status") == "active" and safe_id != current_run_id:
            return self._recover_orphaned_run(safe_id, meta)
        return meta

    def delete_run(self, run_id: str) -> bool:
        """Delete the frames and metadata files for a run. Returns True if anything was deleted."""
        safe_id = self._safe_run_id(run_id)
        with self._lock:
            if self._run_active and self._run_id == safe_id:
                raise HTTPException(409, f"Cannot delete run '{safe_id}' — it is currently active")
        frames_path = self._run_frames_path(safe_id)
        meta_path = self._run_meta_path(safe_id)
        deleted = False
        for path in (frames_path, meta_path):
            try:
                os.remove(path)
                deleted = True
            except FileNotFoundError:
                pass
        return deleted


broadcaster = LiveBroadcaster()


def get_broadcaster() -> "LiveBroadcaster":
    return broadcaster
