"""Run the high-res twin orchestration pipeline."""

from python.twins.high_res.models.frame_assessment import HighResFrameAssessmentModel
from python.twins.high_res.models.trend import HighResTrendModel
from python.models.twin_output import (
    TwinOutput,
)
from python.models.high_res_inputs import HighResInputs
from python.twins.shared.models.temporal import evaluate_temporal_support
from python.twins.shared.runtime.history import TwinHistoryBuffer, TwinHistoryEntry


class HighResTwin:
    """Run the high-res twin pipeline for one input frame."""

    def __init__(self):
        self.history = TwinHistoryBuffer[HighResInputs]()

    def evaluate(self, inputs: HighResInputs) -> TwinOutput:
        frame_assessment = HighResFrameAssessmentModel.evaluate(inputs)
        current_entry = TwinHistoryEntry(
            t=inputs.t,
            inputs=inputs,
            frame_assessment=frame_assessment,
        )
        history_entries = self.history.with_current(current_entry)
        temporal_support = evaluate_temporal_support(history_entries)
        trend_result = HighResTrendModel.evaluate(history_entries)

        self.history.append(current_entry)
        return TwinOutput.from_parts(
            frame_assessment=frame_assessment,
            temporal_support=temporal_support,
            trend_result=trend_result,
        )

    def reset(self) -> None:
        """Reset the high-res twin state."""
        self.history.reset()
