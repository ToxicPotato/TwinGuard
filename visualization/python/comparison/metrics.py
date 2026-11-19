"""Aggregate comparison metrics."""

from python.comparison.load_eval import summarize_timings


def build_metrics(timing_records: list[dict], frame_records: list[dict]) -> dict:
    """Build the current comparison metrics payload."""
    raw_records = [record["raw"] for record in frame_records]
    return {
        "load": summarize_timings(timing_records),
        "raw": raw_records[-1] if raw_records else {},
    }
