"""REST endpoints for Excel-uploaded datasets.

Datasets are loaded from .xlsx files via the upload pipeline and kept in memory.
Distinct from live-captured recordings (see recording.py / GET /recordings).
"""

import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from ..deps import build_runs_from_xlsx, get_runs, set_runs

router = APIRouter()


# ── Async upload job tracking ─────────────────────────────────────────────────

@dataclass
class _UploadJob:
    status: Literal['processing', 'done', 'error']
    updated_at: float
    result: Optional[dict] = None
    error: Optional[str] = None


_jobs: dict[str, _UploadJob] = {}
_FINISHED_JOB_TTL_S = 300
_MAX_FINISHED_JOBS = 100


def _prune_jobs() -> None:
    now = time.time()
    finished_ids = [
        job_id for job_id, job in _jobs.items()
        if job.status != "processing"
    ]
    for job_id in finished_ids:
        job = _jobs.get(job_id)
        if job is not None and now - job.updated_at > _FINISHED_JOB_TTL_S:
            _jobs.pop(job_id, None)
    finished_jobs = [
        (job_id, job) for job_id, job in _jobs.items()
        if job.status != "processing"
    ]
    if len(finished_jobs) <= _MAX_FINISHED_JOBS:
        return
    finished_jobs.sort(key=lambda item: item[1].updated_at)
    for job_id, _ in finished_jobs[:len(finished_jobs) - _MAX_FINISHED_JOBS]:
        _jobs.pop(job_id, None)


def _run_pipeline(job_id: str, tmp_path: str) -> None:
    """Blocking pipeline — runs in a thread (FastAPI BackgroundTasks)."""
    try:
        runs = build_runs_from_xlsx(tmp_path)
        set_runs(runs)
        _jobs[job_id] = _UploadJob(
            status="done",
            updated_at=time.time(),
            result={name: run["meta"] for name, run in runs.items()},
        )
    except Exception as exc:
        _jobs[job_id] = _UploadJob(status="error", updated_at=time.time(), error=str(exc))
    finally:
        _prune_jobs()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_datasets():
    """Return metadata for all datasets currently loaded in memory (no frame data)."""
    return {name: run["meta"] for name, run in get_runs().items()}


@router.post("/upload")
async def upload_xlsx(file: UploadFile, background_tasks: BackgroundTasks):
    """Save the xlsx, start pipeline in background, return a job ID immediately."""
    _prune_jobs()
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "Only .xlsx files are accepted")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    job_id = str(uuid.uuid4())
    _jobs[job_id] = _UploadJob(status="processing", updated_at=time.time())
    background_tasks.add_task(_run_pipeline, job_id, tmp_path)
    return {"job_id": job_id}


@router.get("/upload/status/{job_id}")
def upload_status(job_id: str):
    """Poll the status of an async upload job."""
    _prune_jobs()
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"status": job.status, "result": job.result, "error": job.error}


@router.get("/{dataset_id}/frames")
def get_frames(dataset_id: str):
    """Return all enriched frames for a dataset."""
    runs = get_runs()
    if dataset_id not in runs:
        raise HTTPException(404, f"Dataset '{dataset_id}' not found")
    return runs[dataset_id]["frames"]
