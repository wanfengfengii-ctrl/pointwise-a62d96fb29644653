import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.release import publish
from batch.identity import LaneId, TriggerKey
from batch.registration import register
from capture.control import step
from capture.resume import resume_capture
from review.lookup import lookup
from review.reconciliation import reopen_shift
from source.plate import PlateOrigin, RawPlate
from source.recording import RecordingPort, attach
from source.slot import RecordedPlate


SAMPLE = Path(__file__).with_name("samples") / "supplement.json"


def _port(batch, recording, lane, rows):
    plates = tuple(
        RecordedPlate(seq, RawPlate(TriggerKey(batch, trigger), PlateOrigin(batch, lane, seq), reading))
        for trigger, seq, reading in rows
    )
    return RecordingPort(batch, recording, lane, plates)


def load_fixture(path=SAMPLE):
    sample = json.loads(Path(path).read_text(encoding="utf-8"))
    batch = sample["batch_id"]
    original = sample["original"]
    ports = tuple(_port(batch, original["recording_id"], lane, original[lane.value]) for lane in LaneId)
    extra = sample["supplement"]
    supplement = _port(batch, extra["recording_id"], LaneId(extra["lane"]), extra["plates"])
    return batch, tuple(sample["triggers"]), ports, supplement


def stage_original(shift, batch, triggers, ports):
    register(shift.catalog, batch, triggers)
    binding = attach(shift.catalog, shift.progress, batch, ports)
    first = binding.lane(LaneId.LEFT).read_current()
    assert first is not None and first.plate.key.trigger_id == "A"
    shift.db.execute("""
        CREATE TEMP TRIGGER seed_block_release BEFORE UPDATE ON lane_positions
        BEGIN SELECT RAISE(ABORT, 'fixture release blocked'); END
    """)
    try:
        step(binding, shift.evidence, LaneId.LEFT)
    except sqlite3.IntegrityError as error:
        if str(error) != "fixture release blocked":
            raise
    else:
        raise AssertionError("the slot should still be held")
    finally:
        shift.db.execute("DROP TRIGGER seed_block_release")
    assert binding.lane(LaneId.LEFT).current_position == 0
    assert shift.evidence.read_plate(first.plate.origin) == first.plate
    return first.token


def finish_prefix(shift, batch, ports, held_token):
    binding = attach(shift.catalog, shift.progress, batch, ports)
    left, right = resume_capture(binding, shift.evidence)
    assert left.handoff is not None and left.handoff.token == held_token
    assert right.position == 0
    assert step(binding, shift.evidence, LaneId.LEFT).exhausted
    for _ in range(2):
        step(binding, shift.evidence, LaneId.RIGHT)
    positions = [binding.lane(lane).current_position for lane in LaneId]
    assert positions == [1, 2]
    remaining = binding.lane(LaneId.RIGHT).read_current()
    assert remaining is not None and remaining.plate.key.trigger_id == "C"
    assert [plate.reading for plate in shift.evidence.read_trigger(TriggerKey(batch, "B"))] == [43]
    issued = publish(shift.catalog, shift.evidence, shift.results, batch, "A")
    assert issued is not None and issued.contrast.difference == 16
    assert lookup(shift.catalog, shift.results, batch, "B") is None
    return positions, lookup(shift.catalog, shift.results, batch, "A")


def run_seed(path):
    batch, triggers, ports, _ = load_fixture()
    with reopen_shift(path) as shift:
        held_token = stage_original(shift, batch, triggers, ports)
    with reopen_shift(path) as shift:
        positions, original = finish_prefix(shift, batch, ports, held_token)
    with reopen_shift(path) as shift:
        claimed = lookup(shift.catalog, shift.results, batch, "A")
        assert claimed is not None and claimed == original
        assert lookup(shift.catalog, shift.results, batch, "B") is None
        assert lookup(shift.catalog, shift.results, batch, "C") is None
        return {
            "batch_id": batch,
            "positions": dict(zip((lane.value for lane in LaneId), positions)),
            "published": {"trigger_id": "A", "result_id": claimed.result_id, "difference": claimed.difference},
        }


if __name__ == "__main__":
    with TemporaryDirectory(prefix="coating-supplement-seed-") as directory:
        report = run_seed(Path(directory) / "shift.sqlite3")
    print(json.dumps(report, sort_keys=True))
