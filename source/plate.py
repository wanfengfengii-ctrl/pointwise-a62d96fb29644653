from dataclasses import dataclass

from batch.identity import LaneId, TriggerKey, require_identifier


class InvalidPlate(ValueError):
    pass


@dataclass(frozen=True)
class PlateOrigin:
    batch_id: str
    lane: LaneId
    sequence: int


@dataclass(frozen=True)
class RawPlate:
    key: TriggerKey
    origin: PlateOrigin
    reading: int


def validate_reading(value: object) -> int:
    if type(value) is not int:
        raise InvalidPlate("raw reading must be an integer count")
    return value


def validate_plate(plate: RawPlate) -> RawPlate:
    if not isinstance(plate, RawPlate) or not isinstance(plate.key, TriggerKey):
        raise InvalidPlate("raw plate must identify a trigger")
    if not isinstance(plate.origin, PlateOrigin):
        raise InvalidPlate("raw plate must identify its origin")
    try:
        require_identifier(plate.key.batch_id, "batch_id")
        require_identifier(plate.key.trigger_id, "trigger_id")
    except ValueError as error:
        raise InvalidPlate(str(error)) from error
    if plate.origin.batch_id != plate.key.batch_id:
        raise InvalidPlate("origin belongs to a different batch")
    if not isinstance(plate.origin.lane, LaneId) or type(plate.origin.sequence) is not int:
        raise InvalidPlate("origin must identify a lane and integer sequence")
    validate_reading(plate.reading)
    return plate


def encode_count(value: int) -> str:
    return format(validate_reading(value), "x")


def decode_count(encoded: str) -> int:
    return int(encoded, 16)
