"""Report generation endpoints.

POST /reports          — generate from xlsx upload or live snapshot JSON
GET  /reports          — list all reports
GET  /reports/{id}     — single report metadata
GET  /reports/{id}/download?format=html|json
"""

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from .. import storage

# Add visualization/ root so python.* modules are importable
if settings.viz_dir not in sys.path:
    sys.path.insert(0, settings.viz_dir)

from python.delivery.html_builder import build_html  # noqa: E402
from python.ingestion.file_extractor import extract_frames  # noqa: E402
from python.ingestion.file_loader import detect_robots, load_all_sheets  # noqa: E402
from python.orchestration.twin_runner import TwinRunner  # noqa: E402

router = APIRouter()


# ── Input models ──────────────────────────────────────────────────────────────

class SnapshotReportRequest(BaseModel):
    """Generate a report from a live-data snapshot already in memory."""
    source: Literal["snapshot"] = "snapshot"
    runs: dict  # same structure as RUNS in main.js


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_runs_from_xlsx(path: str) -> dict:
    runner = TwinRunner()
    sheets = load_all_sheets(path)
    runs = {}
    for sheet_name, df in sheets.items():
        robots = detect_robots(df)
        frames, comparison_metrics = runner.process_enriched_frames(extract_frames(df, robots))
        runs[sheet_name] = {
            "frames": frames,
            "meta": {
                "sheet": sheet_name,
                "duration": frames[-1]["t"],
                "count": len(frames),
                "robots": robots,
                "dt": round(1 / 60, 6),
                "twin": {"architecture": "independent-python-twins"},
                "comparison": comparison_metrics,
            },
        }
    return runs


def _generate_report(runs: dict, fmt: str, report_id: str) -> str:
    os.makedirs(settings.output_dir, exist_ok=True)
    out_path = os.path.join(settings.output_dir, f"{report_id}.{fmt}")

    if fmt == "html":
        build_html(runs, out_path)
    elif fmt == "json":
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(runs, f, separators=(",", ":"))
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    return out_path


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/reports", status_code=201)
async def create_report_from_xlsx(
    file: UploadFile,
    fmt: str = "html",
):
    """Upload an xlsx file and generate a report."""
    if fmt not in ("html", "json"):
        raise HTTPException(400, "format must be 'html' or 'json'")
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "Only .xlsx files are accepted")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        runs = _build_runs_from_xlsx(tmp_path)
    except Exception as exc:
        raise HTTPException(500, f"Processing failed: {exc}") from exc
    finally:
        os.unlink(tmp_path)

    report_id = f"rpt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    try:
        file_path = _generate_report(runs, fmt, report_id)
    except Exception as exc:
        raise HTTPException(500, f"Report generation failed: {exc}") from exc

    all_robots = list({r for run in runs.values() for r in run["meta"]["robots"]})
    entry = storage.register(
        report_id=report_id,
        source="xlsx",
        runs=list(runs.keys()),
        robots=all_robots,
        fmt=fmt,
        file_path=file_path,
    )
    return entry


@router.post("/reports/snapshot", status_code=201)
async def create_report_from_snapshot(body: SnapshotReportRequest, fmt: str = "html"):
    """Generate a report from a live-data snapshot (runs dict posted as JSON)."""
    if fmt not in ("html", "json"):
        raise HTTPException(400, "format must be 'html' or 'json'")

    report_id = f"rpt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    try:
        file_path = _generate_report(body.runs, fmt, report_id)
    except Exception as exc:
        raise HTTPException(500, f"Report generation failed: {exc}") from exc

    all_robots = list({r for run in body.runs.values() for r in run.get("meta", {}).get("robots", [])})
    entry = storage.register(
        report_id=report_id,
        source="snapshot",
        runs=list(body.runs.keys()),
        robots=all_robots,
        fmt=fmt,
        file_path=file_path,
    )
    return entry


@router.get("/reports")
def list_reports():
    return storage.get_all()


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    entry = storage.get_one(report_id)
    if not entry:
        raise HTTPException(404, f"Report '{report_id}' not found")
    return entry


@router.get("/reports/{report_id}/download")
def download_report(report_id: str):
    entry = storage.get_one(report_id)
    if not entry:
        raise HTTPException(404, f"Report '{report_id}' not found")
    path = entry["file"]
    if not os.path.exists(path):
        raise HTTPException(410, "Report file no longer exists")
    media = "text/html" if entry["format"] == "html" else "application/json"
    return FileResponse(path, media_type=media, filename=os.path.basename(path))
