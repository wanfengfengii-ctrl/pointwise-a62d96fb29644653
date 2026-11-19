from batch.trigger_manifest import TriggerManifest
from source.plate import InvalidPlate, RawPlate, validate_plate
from source.slot import CurrentSlot


def validate_current_plate(manifest: TriggerManifest, slot: CurrentSlot) -> RawPlate:
    plate = validate_plate(slot.plate)
    if not slot.matches_plate(plate) or plate.key.batch_id != manifest.batch_id:
        raise InvalidPlate("raw origin does not match the current slot")
    if not manifest.contains(plate.key.trigger_id):
        raise InvalidPlate(f"trigger is outside the registered manifest: {plate.key.trigger_id!r}")
    return plate
