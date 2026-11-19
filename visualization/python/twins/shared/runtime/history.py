"""Store recent twin frame entries in a sliding time window."""

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from python.twins.shared.constants import DEFAULT_HISTORY_WINDOW_SECONDS
from python.twins.shared.models.frame_assessment import FrameAssessment


TInputs = TypeVar("TInputs")


@dataclass(slots=True)
class TwinHistoryEntry(Generic[TInputs]):
    """Store one aligned frame entry for the twin runtime."""

    t: float
    inputs: TInputs
    frame_assessment: FrameAssessment


@dataclass(slots=True)
class TwinHistoryBuffer(Generic[TInputs]):
    """Maintain a sliding window of recent twin frame entries."""

    window_seconds: float = DEFAULT_HISTORY_WINDOW_SECONDS
    _items: list[TwinHistoryEntry[TInputs]] = field(default_factory=list)

    def _trimmed_items(self, current_entry: TwinHistoryEntry[TInputs]) -> list[TwinHistoryEntry[TInputs]]:
        """Return buffered entries still inside the active history window."""
        cutoff_time = current_entry.t - self.window_seconds
        return [item for item in self._items if item.t >= cutoff_time]

    def with_current(self, current_entry: TwinHistoryEntry[TInputs]) -> list[TwinHistoryEntry[TInputs]]:
        """Return the active history window including the current entry."""
        active_items = self._trimmed_items(current_entry)
        return [*active_items, current_entry]

    def append(self, current_entry: TwinHistoryEntry[TInputs]) -> None:
        """Append an entry and discard items outside the history window."""
        self._items = self.with_current(current_entry)

    def reset(self) -> None:
        """Clear all buffered history items."""
        self._items.clear()
