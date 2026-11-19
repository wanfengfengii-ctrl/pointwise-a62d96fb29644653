from dataclasses import dataclass

from archive.evidence import EvidenceLedger, EvidenceReceipt
from batch.identity import LaneId
from capture.handoff import Handoff
from source.lane import Lane
from source.plate import InvalidPlate, validate_plate
from source.recording import RecordingBinding
from source.slot import CurrentSlot


@dataclass(frozen=True)
class LaneResumeState:
    lane: LaneId
    position: int
    current: CurrentSlot | None
    handoff: Handoff | None


def recover_lane(lane: Lane, evidence: EvidenceLedger) -> LaneResumeState:
    slot = lane.read_current()
    if slot is None:
        return LaneResumeState(lane.lane_id, lane.current_position, None, None)
    handoff = None
    try:
        plate = validate_plate(slot.plate)
    except InvalidPlate:
        pass
    else:
        if slot.matches_plate(plate) and evidence.read_plate(plate.origin) == plate:
            handoff = Handoff(slot.token, EvidenceReceipt(plate))
    return LaneResumeState(lane.lane_id, slot.token.position, slot, handoff)


def resume_capture(binding: RecordingBinding, evidence: EvidenceLedger) -> tuple[LaneResumeState, ...]:
    return tuple(recover_lane(binding.lane(lane_id), evidence) for lane_id in LaneId)
