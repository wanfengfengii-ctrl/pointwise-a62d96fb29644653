from dataclasses import dataclass

from archive.evidence import EvidenceLedger, EvidenceReceipt
from source.plate import InvalidPlate, RawPlate
from source.slot import CurrentSlot, SlotToken


@dataclass(frozen=True)
class Handoff:
    token: SlotToken
    receipt: EvidenceReceipt


def accept_current_plate(ledger: EvidenceLedger, slot: CurrentSlot, plate: RawPlate) -> Handoff:
    if not slot.matches_plate(plate) or slot.plate != plate:
        raise InvalidPlate("only the current plate can be handed off")
    return Handoff(slot.token, ledger.accept_plate(plate))


def confirm_release_eligibility(slot: CurrentSlot, handoff: Handoff) -> SlotToken:
    plate = handoff.receipt.plate
    if not slot.matches_release(handoff.token) or not slot.matches_plate(plate) or slot.plate != plate:
        raise InvalidPlate("durable receipt does not identify this current plate")
    return handoff.token
