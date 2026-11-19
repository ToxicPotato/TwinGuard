"""Orchestrate twin execution, comparison, and frame enrichment."""

from dataclasses import asdict
from time import perf_counter

from python.comparison.metrics import build_metrics
from python.comparison.raw_eval import compare_raw_outputs
from python.delivery.frame_payload import attach_twin_payload, frame_to_dict, serialize_scenario_output
from python.frames.geometry import derive_display_geometry
from python.models.frame import Frame
from python.models.high_res_inputs import HighResInputs
from python.models.low_res_inputs import LowResInputs
from python.twins.high_res.model import HighResTwin
from python.twins.low_res.model import LowResTwin
from python.twins.scenario.model import ScenarioTwin


class TwinRunner:
    """Coordinate both twins over normalized frames and enrich replay output."""

    def __init__(self):
        self.low_res_twin = LowResTwin()
        self.high_res_twin = HighResTwin()
        self.scenario_twin = ScenarioTwin()

    def reset(self) -> None:
        """Reset both twins before processing a new run."""
        self.low_res_twin.reset()
        self.high_res_twin.reset()
        self.scenario_twin.reset()

    def run_twins(self, frame: Frame) -> dict:
        """Run both twins for one normalized frame and compare raw outputs."""
        low_inputs = LowResInputs.from_frame(frame)
        high_inputs = HighResInputs.from_frame(frame)

        start = perf_counter()
        low_output = self.low_res_twin.evaluate(low_inputs)
        low_ms = (perf_counter() - start) * 1000.0

        start = perf_counter()
        high_output = self.high_res_twin.evaluate(high_inputs)
        high_ms = (perf_counter() - start) * 1000.0

        start = perf_counter()
        scenario_output = self.scenario_twin.evaluate(high_inputs)
        scenario_ms = (perf_counter() - start) * 1000.0

        low_res = asdict(low_output)
        high_res = asdict(high_output)
        scenario = serialize_scenario_output(scenario_output)

        return {
            "low_res": low_res,
            "high_res": high_res,
            "scenario": scenario,
            "comparison": {
                "timing_ms": {
                    "low_res": round(low_ms, 5),
                    "high_res": round(high_ms, 5),
                    "scenario": round(scenario_ms, 5),
                },
                "raw": compare_raw_outputs(low_res, high_res),
            },
        }

    def enrich_frame(self, frame: Frame) -> dict:
        """Attach twin, display, and comparison outputs to one frame."""
        result = self.run_twins(frame)
        display = derive_display_geometry(frame)
        frame_payload = frame_to_dict(frame)
        enriched = attach_twin_payload(
            frame_payload,
            result["low_res"],
            result["high_res"],
            display,
            comparison=result["comparison"],
            scenario=result["scenario"],
        )
        return enriched

    def process_enriched_frames(self, frames: list[Frame]) -> tuple[list[dict], dict]:
        """Return enriched frames and comparison metrics for a frame sequence."""
        self.reset()
        enriched = []
        timings = []
        frame_records = []

        for frame in frames:
            enriched_frame = self.enrich_frame(frame)
            enriched.append(enriched_frame)
            timing = enriched_frame["comparison"]["timing_ms"]
            timings.append(
                {
                    "low_res_ms": timing["low_res"],
                    "high_res_ms": timing["high_res"],
                    "scenario_ms": timing["scenario"],
                }
            )
            frame_records.append(
                {
                    "raw": enriched_frame["comparison"]["raw"],
                }
            )

        return enriched, build_metrics(timings, frame_records)
