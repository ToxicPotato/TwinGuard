"""JSON-file report registry — stores metadata for all generated reports."""

import json
import os
from datetime import datetime, timezone
from typing import Literal

from .config import settings

_REGISTRY_FILE = os.path.join(settings.output_dir, "reports.json")


def _load() -> dict:
    if not os.path.exists(_REGISTRY_FILE):
        return {}
    with open(_REGISTRY_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(registry: dict) -> None:
    os.makedirs(settings.output_dir, exist_ok=True)
    with open(_REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def register(
    report_id: str,
    source: Literal["xlsx", "snapshot"],
    runs: list[str],
    robots: list[str],
    fmt: str,
    file_path: str,
) -> dict:
    registry = _load()
    entry = {
        "id": report_id,
        "source": source,
        "runs": runs,
        "robots": robots,
        "format": fmt,
        "file": file_path,
        "generated": datetime.now(timezone.utc).isoformat(),
        "size_kb": os.path.getsize(file_path) // 1024 if os.path.exists(file_path) else 0,
    }
    registry[report_id] = entry
    _save(registry)
    return entry


def get_all() -> list[dict]:
    return list(_load().values())


def get_one(report_id: str) -> dict | None:
    return _load().get(report_id)
