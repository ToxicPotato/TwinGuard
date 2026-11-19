"""Run the low-res twin orchestration pipeline."""

from python.twins.low_res.models.frame_assessment import LowResFrameAssessmentModel
from python.twins.low_res.models.trend import LowResTrendModel
from python.models.low_res_inputs import LowResInputs
from python.models.twin_output import TwinOutput
from python.twins.shared.models.temporal import evaluate_temporal_support
from python.twins.shared.runtime.history import TwinHistoryBuffer, TwinHistoryEntry


class LowResTwin:
    """Run the low-res twin pipeline for one input frame."""

    def __init__(self):
        self.history = TwinHistoryBuffer[LowResInputs]()

    def evaluate(self, inputs: LowResInputs) -> TwinOutput:
        frame_assessment = LowResFrameAssessmentModel.evaluate(inputs)
        current_entry = TwinHistoryEntry(
            t=inputs.t,
            inputs=inputs,
            frame_assessment=frame_assessment,
        )
        history_entries = self.history.with_current(current_entry)
        temporal_support = evaluate_temporal_support(history_entries)
        trend_result = LowResTrendModel.evaluate(history_entries)

        self.history.append(current_entry)
        return TwinOutput.from_parts(
            frame_assessment=frame_assessment,
            temporal_support=temporal_support,
            trend_result=trend_result,
        )

    def reset(self) -> None:
        """Reset the low-res twin state."""
        self.history.reset()
