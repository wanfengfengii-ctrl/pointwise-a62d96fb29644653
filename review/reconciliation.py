import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.evidence import EvidenceLedger
from archive.evidence_store import EvidenceStore
from archive.release import publish
from archive.result_store import ResultStore
from batch.catalog import ManifestCatalog
from batch.identity import LaneId, TriggerKey
from batch.registration import get_registered_batch, register
from capture.control import CaptureStep, step
from review.checklist import ChecklistEntry, checklist
from review.lookup import lookup
from review.provenance import ReviewResult
from source.lane import LaneEvent
from source.plate import PlateOrigin, RawPlate
from source.progress import LaneProgressStore
from source.recording import RecordingBinding, RecordingPort, attach
from source.slot import RecordedPlate


@dataclass
class Shift:
    db: sqlite3.Connection
    catalog: ManifestCatalog
    progress: LaneProgressStore
    evidence: EvidenceLedger
    results: ResultStore

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.db.close()


@dataclass(frozen=True)
class ShiftReview:
    captures: tuple[CaptureStep, ...]
    checklist: tuple[ChecklistEntry, ...]
    results: tuple[ReviewResult, ...]


def reopen_shift(path: str | Path) -> Shift:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA synchronous = FULL")
        catalog = ManifestCatalog(db)
        progress = LaneProgressStore(db)
        evidence_store = EvidenceStore(db)
        results = ResultStore(db)
        for store in (catalog, progress, evidence_store, results):
            store.initialize()
        return Shift(db, catalog, progress, EvidenceLedger(evidence_store), results)
    except BaseException:
        db.close()
        raise


def reconcile_shift(
    shift: Shift,
    batch_id: str,
    *,
    binding: RecordingBinding | None = None,
    lanes: Iterable[LaneId] = (),
) -> ShiftReview:
    manifest = get_registered_batch(shift.catalog, batch_id)
    schedule = tuple(lanes)
    if binding is None and schedule:
        raise ValueError("continuing capture requires a recording binding")
    if binding is not None and binding.manifest != manifest:
        raise ValueError("recording binding does not match this shift manifest")
    if any(not isinstance(lane_id, LaneId) for lane_id in schedule):
        raise ValueError("schedule must contain lane identifiers")
    captures = []
    if binding is not None:
        for lane_id in schedule:
            taken = step(binding, shift.evidence, lane_id)
            if taken is not None:
                captures.append(taken)
    for trigger in manifest.ordered_triggers:
        publish(shift.catalog, shift.evidence, shift.results, batch_id, trigger)
    entries = checklist(shift.catalog, shift.results, batch_id)
    results = []
    for entry in entries:
        if entry.result_id is not None:
            result = lookup(shift.catalog, shift.results, batch_id, entry.trigger_id)
            if result is None:
                raise RuntimeError("published checklist entry has no result")
            results.append(result)
    return ShiftReview(tuple(captures), entries, tuple(results))


class DemoMismatch(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DemoMismatch(message)


def _sample_ports(sample: dict) -> tuple[RecordingPort, ...]:
    batch_id = sample["batch_id"]
    recording_id = sample["recording_id"]
    ports = []
    for lane in LaneId:
        entries = []
        for trigger, sequence, reading in sample[lane.value]:
            raw = RawPlate(TriggerKey(batch_id, trigger), PlateOrigin(batch_id, lane, sequence), reading)
            entries.append(RecordedPlate(sequence, raw))
        ports.append(RecordingPort(batch_id, recording_id, lane, tuple(entries)))
    return tuple(ports)


def _take_demo_plate(
    shift: Shift, binding: RecordingBinding, lane: LaneId, trigger: str, next_position: int,
) -> None:
    taken = step(binding, shift.evidence, lane)
    _require(taken is not None, f"{lane.value} did not hand off {trigger}")
    _require(
        taken.handoff.receipt.plate.key.trigger_id == trigger
        and taken.next_position == next_position
        and binding.lane(lane).current_position == next_position,
        f"{lane.value} did not advance after handing off {trigger}",
    )


def _fail_demo_publication(shift: Shift, batch_id: str) -> None:
    shift.db.execute("""
        CREATE TEMP TRIGGER demo_block_publication AFTER INSERT ON published_results
        BEGIN
            SELECT RAISE(ABORT, 'coating demo publication blocked');
        END
    """)
    try:
        try:
            publish(shift.catalog, shift.evidence, shift.results, batch_id, "A")
        except sqlite3.IntegrityError as error:
            if str(error) != "coating demo publication blocked":
                raise
        else:
            raise DemoMismatch("first publication did not encounter the planned write failure")
    finally:
        shift.db.execute("DROP TRIGGER temp.demo_block_publication")


def _claim_values(result: ReviewResult) -> list:
    return [result.left_reading, result.right_reading, result.difference,
            [result.left_origin.lane.value, result.left_origin.sequence],
            [result.right_origin.lane.value, result.right_origin.sequence]]


def _statuses(entries: tuple[ChecklistEntry, ...]) -> list:
    return [[entry.trigger_id, entry.status] for entry in entries]


def _trace_values(trace: tuple[LaneEvent, ...]) -> list:
    return [[event.action, event.lane.value, event.position, event.sequence] for event in trace]


def run_shift_demo(sample_path: str | Path, database_path: str | Path) -> dict:
    sample = json.loads(Path(sample_path).read_text(encoding="utf-8"))
    batch_id = sample["batch_id"]
    ports = _sample_ports(sample)
    left, right = LaneId.LEFT, LaneId.RIGHT
    with reopen_shift(database_path) as shift:
        register(shift.catalog, batch_id, sample["triggers"])
        binding = attach(shift.catalog, shift.progress, batch_id, ports)
        _take_demo_plate(shift, binding, left, "A", 1)
        _require(lookup(shift.catalog, shift.results, batch_id, "A") is None,
                 "left A became visible before right A arrived")
        _take_demo_plate(shift, binding, right, "B", 1)
        _take_demo_plate(shift, binding, left, "B", 2)
        _require(publish(shift.catalog, shift.evidence, shift.results, batch_id, "B") is not None,
                 "B did not publish after its two boards arrived")
        original_b = lookup(shift.catalog, shift.results, batch_id, "B")
        _require(original_b is not None, "B was unavailable after publication")
        trace = binding.trace

    with reopen_shift(database_path) as shift:
        binding = attach(shift.catalog, shift.progress, batch_id, ports)
        before = _statuses(checklist(shift.catalog, shift.results, batch_id))
        _take_demo_plate(shift, binding, right, "A", 2)
        trace += binding.trace
        _require(lookup(shift.catalog, shift.results, batch_id, "A") is None,
                 "A became visible before formal publication")
        _fail_demo_publication(shift, batch_id)
        pending_after_failure = lookup(shift.catalog, shift.results, batch_id, "A") is None
        _require(pending_after_failure, "A was visible after failed publication")
        _require(lookup(shift.catalog, shift.results, batch_id, "B") == original_b,
                 "failed publication changed historical B")

    with reopen_shift(database_path) as shift:
        reviewed = reconcile_shift(shift, batch_id)
        actual = {result.trigger_id: _claim_values(result) for result in reviewed.results}
        final_b = lookup(shift.catalog, shift.results, batch_id, "B")
        published_a = publish(shift.catalog, shift.evidence, shift.results, batch_id, "A")
        issued_a = lookup(shift.catalog, shift.results, batch_id, "A")
        _require(published_a is not None and issued_a is not None
                 and published_a.result_id == issued_a.result_id, "A did not retain its result number")
        downstream = {
            "reopened_checklist": before,
            "pending_after_failure": pending_after_failure,
            "final_checklist": _statuses(reviewed.checklist),
            "history_unchanged": final_b == original_b,
            "trace": _trace_values(trace),
        }

    expected = {"A": [31, 47, 16, ["left", 11], ["right", 18]],
                "B": [29, 43, 14, ["left", 14], ["right", 11]]}
    expected_downstream = {
        "reopened_checklist": [["A", "pending"], ["B", "published"]],
        "pending_after_failure": True,
        "final_checklist": [["A", "published"], ["B", "published"]],
        "history_unchanged": True,
        "trace": [["read", "left", 0, 11], ["release", "left", 0, 11],
                  ["read", "right", 0, 11], ["release", "right", 0, 11],
                  ["read", "left", 1, 14], ["release", "left", 1, 14],
                  ["read", "right", 1, 18], ["release", "right", 1, 18]],
    }
    _require(actual == expected, "claimed readings or origins differ from the recorded boards")
    _require(downstream == expected_downstream, "checklist or slot history differs from the shift script")
    return {
        "case_id": "v8", "input": sample, "expected": expected, "actual": actual,
        "downstream_expected": expected_downstream, "downstream_actual": downstream,
        "code_paths": ["capture/control.py", "archive/evidence_store.py", "archive/pairing.py",
                       "archive/contrast.py", "archive/result_store.py", "review/checklist.py",
                       "review/lookup.py", "review/reconciliation.py"],
        "oracle": "按样例原触发手算 47-31 和 43-29，并按四次指定调用逐项核对读板、放行和班末清单。",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the coating shift replay in a fresh local database")
    parser.add_argument("--sample", default="samples/shift.json")
    args = parser.parse_args(argv)
    try:
        with TemporaryDirectory(prefix="coating-shift-") as directory:
            report = run_shift_demo(args.sample, Path(directory) / "shift.sqlite3")
    except DemoMismatch as error:
        print(f"SPECTRAL_HANDOFF_MISMATCH {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, LookupError, TypeError, sqlite3.Error, RuntimeError) as error:
        print(f"SPECTRAL_DEMO_ERROR {error}", file=sys.stderr)
        return 2
    print("POINTWISE_SCENARIO " + json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
