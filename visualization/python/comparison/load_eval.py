"""Load-oriented comparison helpers."""


def summarize_timings(records: list[dict]) -> dict:
    """Summarize per-frame timing samples."""
    if not records:
        return {}
    low_total      = sum(item["low_res_ms"]  for item in records)
    high_total     = sum(item["high_res_ms"] for item in records)
    scenario_total = sum(item.get("scenario_ms", 0.0) for item in records)
    return {
        "frames": len(records),
        "low_res_total_ms":      round(low_total, 5),
        "high_res_total_ms":     round(high_total, 5),
        "scenario_total_ms":     round(scenario_total, 5),
        "low_res_avg_ms":        round(low_total      / len(records), 5),
        "high_res_avg_ms":       round(high_total     / len(records), 5),
        "scenario_avg_ms":       round(scenario_total / len(records), 5),
    }
