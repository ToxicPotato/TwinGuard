"""Shared FastAPI dependencies: sys.path setup, TwinRunner singleton, replay runs."""

import os
import sys

# Add visualization/ to sys.path so `python.*` modules are importable
_VIZ_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _VIZ_DIR not in sys.path:
    sys.path.insert(0, _VIZ_DIR)

from python.ingestion.file_extractor import extract_frames  # noqa: E402
from python.ingestion.file_loader import detect_robots, load_all_sheets  # noqa: E402
from python.orchestration.twin_runner import TwinRunner  # noqa: E402

# ── Singletons ────────────────────────────────────────────────────────────────

_runner = TwinRunner()
_runs: dict = {}


def get_runner() -> TwinRunner:
    return _runner


def get_runs() -> dict:
    return _runs


def set_runs(runs: dict) -> None:
    global _runs
    _runs = runs


# ── Pipeline helpers (extracted from generate_twin.py) ───────────────────────

def build_runs_from_xlsx(path: str) -> dict:
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
                "twin": {
                    "architecture": "independent-python-twins",
                    "low_res": "twins.low_res",
                    "high_res": "twins.high_res",
                },
                "comparison": comparison_metrics,
            },
        }
    return runs
