from dataclasses import dataclass

from archive.evidence import EvidenceLedger
from batch.identity import LaneId, TriggerKey
from source.plate import RawPlate


@dataclass(frozen=True)
class PairedEvidence:
    key: TriggerKey
    left: RawPlate
    right: RawPlate

    def __post_init__(self) -> None:
        if self.left.key != self.key or self.right.key != self.key:
            raise ValueError("both plates must belong to the paired trigger")
        if self.left.origin.lane is not LaneId.LEFT or self.right.origin.lane is not LaneId.RIGHT:
            raise ValueError("paired evidence needs one left and one right plate")
        if self.left.origin.batch_id != self.key.batch_id or self.right.origin.batch_id != self.key.batch_id:
            raise ValueError("paired origins must belong to the paired batch")


def pair_for_trigger(ledger: EvidenceLedger, key: TriggerKey) -> PairedEvidence | None:
    plates = ledger.read_trigger(key)
    by_lane = {plate.origin.lane: plate for plate in plates}
    if LaneId.LEFT not in by_lane or LaneId.RIGHT not in by_lane:
        return None
    return PairedEvidence(key, by_lane[LaneId.LEFT], by_lane[LaneId.RIGHT])
