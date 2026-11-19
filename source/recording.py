from collections.abc import Iterable
from dataclasses import dataclass, field

from batch.catalog import ManifestCatalog
from batch.identity import LaneId, require_identifier
from batch.registration import get_registered_batch
from batch.trigger_manifest import TriggerManifest
from source.lane import Lane, LaneEvent
from source.progress import LaneProgressStore
from source.slot import CurrentSlot, RecordedPlate, SlotToken


class InvalidRecording(ValueError):
    pass


@dataclass(frozen=True)
class RecordingPort:
    batch_id: str
    recording_id: str
    lane_id: LaneId
    _plates: tuple[RecordedPlate, ...] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_plates", tuple(self._plates))

    def _has_slot(self, position: int) -> bool:
        return 0 <= position < len(self._plates)

    def _slot_at(self, position: int) -> CurrentSlot | None:
        if not self._has_slot(position):
            return None
        item = self._plates[position]
        token = SlotToken(self.batch_id, self.recording_id, self.lane_id, position, item.sequence)
        return CurrentSlot(token, item.plate)


@dataclass(frozen=True)
class RecordingBinding:
    manifest: TriggerManifest
    recording_id: str
    _lanes: dict[LaneId, Lane] = field(repr=False)
    _trace: list[LaneEvent] = field(repr=False, compare=False)

    def lane(self, lane_id: LaneId) -> Lane:
        if not isinstance(lane_id, LaneId):
            raise InvalidRecording("expected a left or right lane identifier")
        return self._lanes[lane_id]

    @property
    def trace(self) -> tuple[LaneEvent, ...]:
        return tuple(self._trace)


def attach(
    catalog: ManifestCatalog,
    progress: LaneProgressStore,
    batch_id: str,
    ports: Iterable[RecordingPort],
) -> RecordingBinding:
    manifest = get_registered_batch(catalog, batch_id)
    supplied = tuple(ports)
    if len(supplied) != 2:
        raise InvalidRecording("a recording needs exactly two ports")
    by_lane = {}
    for port in supplied:
        if not isinstance(port, RecordingPort) or not isinstance(port.lane_id, LaneId):
            raise InvalidRecording("invalid recording port or lane")
        if port.batch_id != manifest.batch_id:
            raise InvalidRecording("recording port belongs to another batch")
        if port.lane_id in by_lane:
            raise InvalidRecording("recording lanes must be distinct")
        by_lane[port.lane_id] = port
    left = by_lane[LaneId.LEFT]
    right = by_lane[LaneId.RIGHT]
    recording_id = require_identifier(left.recording_id, "recording_id")
    if right.recording_id != recording_id:
        raise InvalidRecording("ports must belong to the same recording")
    progress.bind_recording(manifest.batch_id, recording_id)
    trace = []
    lanes = {lane_id: Lane(port, progress, trace) for lane_id, port in by_lane.items()}
    return RecordingBinding(manifest, recording_id, lanes, trace)
