from dataclasses import dataclass

from batch.identity import LaneId
from source.plate import RawPlate


class StaleSlot(ValueError):
    pass


@dataclass(frozen=True)
class RecordedPlate:
    sequence: int
    plate: RawPlate


@dataclass(frozen=True)
class SlotToken:
    batch_id: str
    recording_id: str
    lane: LaneId
    position: int
    sequence: int


@dataclass(frozen=True)
class CurrentSlot:
    token: SlotToken
    plate: RawPlate

    def matches_release(self, token: SlotToken) -> bool:
        return (
            isinstance(token, SlotToken)
            and type(token.position) is int
            and type(token.sequence) is int
            and type(self.token.sequence) is int
            and self.token == token
        )

    def matches_plate(self, plate: RawPlate) -> bool:
        return (
            plate.key.batch_id == plate.origin.batch_id == self.token.batch_id
            and plate.origin.lane is self.token.lane
            and type(self.token.sequence) is int
            and type(plate.origin.sequence) is int
            and plate.origin.sequence == self.token.sequence
        )
