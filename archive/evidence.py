from dataclasses import dataclass

from archive.evidence_store import EvidenceStore
from batch.identity import TriggerKey
from source.plate import PlateOrigin, RawPlate, validate_plate


@dataclass(frozen=True)
class EvidenceReceipt:
    plate: RawPlate


class EvidenceLedger:
    def __init__(self, store: EvidenceStore):
        self._store = store

    def accept_plate(self, plate: RawPlate) -> EvidenceReceipt:
        """Accept a plate that has passed the capture manifest and slot checks."""
        stored = self._store.insert_or_read(validate_plate(plate))
        return EvidenceReceipt(stored)

    def read_plate(self, origin: PlateOrigin) -> RawPlate | None:
        return self._store.read_origin(origin)

    def read_trigger(self, key: TriggerKey) -> tuple[RawPlate, ...]:
        return self._store.read_trigger(key)
