from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from batch.identity import LaneId
from source.progress import LaneProgressStore
from source.slot import CurrentSlot, SlotToken, StaleSlot

if TYPE_CHECKING:
    from source.recording import RecordingPort


@dataclass(frozen=True)
class LaneEvent:
    action: str
    lane: LaneId
    position: int
    sequence: int


@dataclass(frozen=True)
class LaneAdvance:
    next_position: int
    exhausted: bool


class Lane:
    def __init__(self, port: RecordingPort, progress: LaneProgressStore, trace: list[LaneEvent]):
        self._port = port
        self._progress = progress
        self._trace = trace

    @property
    def lane_id(self) -> LaneId:
        return self._port.lane_id

    @property
    def current_position(self) -> int:
        return self._progress.read_position(self._port.batch_id, self._port.recording_id, self.lane_id)

    def read_current(self) -> CurrentSlot | None:
        slot = self._port._slot_at(self.current_position)
        if slot is not None:
            self._record("read", slot.token)
        return slot

    def release_current(self, token: SlotToken) -> LaneAdvance:
        slot = self._port._slot_at(self.current_position)
        if slot is None or not slot.matches_release(token):
            raise StaleSlot("release does not identify this current slot")
        next_position = self._progress.advance_current(token)
        self._record("release", token)
        return LaneAdvance(next_position, not self._port._has_slot(next_position))

    def _record(self, action: str, token: SlotToken) -> None:
        self._trace.append(LaneEvent(action, token.lane, token.position, token.sequence))
