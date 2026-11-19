from batch.identity import LaneId, TriggerKey
from capture.control import step
from source.plate import PlateOrigin, RawPlate
from source.recording import RecordingPort, attach
from source.slot import RecordedPlate


BATCH = "coat"
RECORDING = "scan-1"
LEFT = LaneId.LEFT
RIGHT = LaneId.RIGHT


def make_port(lane, rows, batch=BATCH, recording=RECORDING):
    entries = tuple(
        RecordedPlate(seq, RawPlate(TriggerKey(batch, trigger), PlateOrigin(batch, lane, seq), value))
        for trigger, seq, value in rows
    )
    return RecordingPort(batch, recording, lane, entries)


def make_ports(left=(), right=(), batch=BATCH):
    return make_port(LEFT, left, batch), make_port(RIGHT, right, batch)


def crossed_ports():
    return make_ports((("A", 11, 31), ("B", 14, 29)), (("B", 11, 43), ("A", 18, 47)))


def attach_to(shift, ports, batch=BATCH):
    return attach(shift.catalog, shift.progress, batch, ports)


def take_steps(shift, binding, *lanes):
    return tuple(step(binding, shift.evidence, lane) for lane in lanes)


def claim_values(result):
    return (result.left_reading, result.right_reading, result.difference,
            result.left_origin, result.right_origin)


def trace_values(binding):
    return [(event.action, event.lane, event.position, event.sequence) for event in binding.trace]
