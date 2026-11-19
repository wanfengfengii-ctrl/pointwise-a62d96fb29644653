import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from batch.identity import TriggerKey
from batch.registration import register
from capture.control import step
from capture.handoff import Handoff, confirm_release_eligibility
from review.lookup import lookup
from review.reconciliation import reopen_shift
from source.plate import InvalidPlate, PlateOrigin, RawPlate
from source.recording import RecordingPort
from source.slot import RecordedPlate, StaleSlot
from tests import BATCH, LEFT, RECORDING, RIGHT, attach_to, crossed_ports, make_ports, take_steps, trace_values


class TestCapture(unittest.TestCase):
    def test_crossed_lanes(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, crossed_ports())
            steps = take_steps(shift, binding, LEFT, RIGHT, LEFT, RIGHT)
            plates = [taken.handoff.receipt.plate for taken in steps]
            self.assertEqual(
                [(plate.key.trigger_id, plate.origin.lane, plate.origin.sequence, plate.reading) for plate in plates],
                [("A", LEFT, 11, 31), ("B", RIGHT, 11, 43), ("B", LEFT, 14, 29), ("A", RIGHT, 18, 47)],
            )
            self.assertEqual([taken.next_position for taken in steps], [1, 1, 2, 2])
            self.assertEqual([taken.exhausted for taken in steps], [False, False, True, True])
            self.assertEqual(trace_values(binding), [
                ("read", LEFT, 0, 11), ("release", LEFT, 0, 11),
                ("read", RIGHT, 0, 11), ("release", RIGHT, 0, 11),
                ("read", LEFT, 1, 14), ("release", LEFT, 1, 14),
                ("read", RIGHT, 1, 18), ("release", RIGHT, 1, 18),
            ])
            for plate in plates:
                self.assertEqual(shift.evidence.read_plate(plate.origin), plate)
            self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))

    def test_unknown_trigger(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, make_ports((("X", 11, 31), ("A", 14, 29))))
            with self.assertRaisesRegex(InvalidPlate, "outside the registered manifest"):
                step(binding, shift.evidence, LEFT)
            self.assertEqual(trace_values(binding), [("read", LEFT, 0, 11)])
            self.assertEqual(binding.lane(LEFT).current_position, 0)
            self.assertEqual(binding.lane(LEFT).read_current().plate.key.trigger_id, "X")
            self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "X")), ())

    def test_invalid_reading(self):
        for value in (None, True, 31.0, "31"):
            with self.subTest(value=value), reopen_shift(":memory:") as shift:
                register(shift.catalog, BATCH, ("A",))
                binding = attach_to(shift, make_ports((("A", 11, value),)))
                with self.assertRaises(InvalidPlate):
                    step(binding, shift.evidence, LEFT)
                self.assertEqual(binding.lane(LEFT).current_position, 0)
                self.assertEqual(trace_values(binding), [("read", LEFT, 0, 11)])
                self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "A")), ())

    def test_invalid_slot_identity(self):
        mismatches = (PlateOrigin(BATCH, RIGHT, 11), PlateOrigin(BATCH, LEFT, 12),
                      PlateOrigin("other", LEFT, 11), PlateOrigin(BATCH, LEFT, True))
        for origin in mismatches:
            with self.subTest(origin=origin), reopen_shift(":memory:") as shift:
                register(shift.catalog, BATCH, ("A",))
                raw = RawPlate(TriggerKey(BATCH, "A"), origin, 31)
                port = RecordingPort(BATCH, RECORDING, LEFT, (RecordedPlate(11, raw),))
                _, right = make_ports()
                binding = attach_to(shift, (port, right))
                with self.assertRaises(InvalidPlate):
                    step(binding, shift.evidence, LEFT)
                self.assertEqual(binding.lane(LEFT).current_position, 0)
                self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "A")), ())

    def test_stale_release(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, crossed_ports())
            taken = step(binding, shift.evidence, LEFT)
            for lane in (LEFT, RIGHT):
                with self.assertRaises(StaleSlot):
                    binding.lane(lane).release_current(taken.handoff.token)
            self.assertEqual([binding.lane(lane).current_position for lane in (LEFT, RIGHT)], [1, 0])
            self.assertEqual(trace_values(binding), [("read", LEFT, 0, 11), ("release", LEFT, 0, 11)])
            self.assertEqual(binding.lane(LEFT).read_current().plate.key.trigger_id, "B")

    def test_last_slot_exhaustion(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("B", 11, 43), ("A", 18, 47))))
            taken = step(binding, shift.evidence, LEFT)
            self.assertTrue(taken.exhausted)
            self.assertIsNone(step(binding, shift.evidence, LEFT))
            self.assertEqual(binding.lane(RIGHT).current_position, 0)
            right_b, right_a = take_steps(shift, binding, RIGHT, RIGHT)
            self.assertFalse(right_b.exhausted)
            self.assertTrue(right_a.exhausted)
            self.assertIsNone(step(binding, shift.evidence, RIGHT))
            self.assertEqual(len(binding.trace), 6)

    def test_commit_before_release(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "capture.sqlite3"
            with reopen_shift(path) as shift:
                register(shift.catalog, BATCH, ("A", "B"))
                binding = attach_to(shift, crossed_ports())
                shift.db.execute("""
                    CREATE TEMP TRIGGER block_evidence AFTER INSERT ON plate_evidence
                    BEGIN SELECT RAISE(ABORT, 'evidence write blocked'); END
                """)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "evidence write blocked"):
                    step(binding, shift.evidence, LEFT)
                self.assertEqual(binding.lane(LEFT).current_position, 0)
                self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "A")), ())
                self.assertEqual(trace_values(binding), [("read", LEFT, 0, 11)])
                shift.db.execute("DROP TRIGGER temp.block_evidence")
                shift.db.execute("""
                    CREATE TEMP TRIGGER block_release AFTER UPDATE ON lane_positions
                    BEGIN SELECT RAISE(ABORT, 'release blocked'); END
                """)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "release blocked"):
                    step(binding, shift.evidence, LEFT)
                with reopen_shift(path) as observer:
                    self.assertEqual(observer.progress.read_position(BATCH, RECORDING, LEFT), 0)
                    self.assertEqual(observer.evidence.read_plate(PlateOrigin(BATCH, LEFT, 11)).reading, 31)
                    self.assertIsNone(lookup(observer.catalog, observer.results, BATCH, "A"))
                shift.db.execute("DROP TRIGGER temp.block_release")
                self.assertEqual(step(binding, shift.evidence, LEFT).next_position, 1)

    def test_equal_readings(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("B", 11, 31),)))
            left, right = take_steps(shift, binding, LEFT, RIGHT)
            self.assertEqual([left.next_position, right.next_position], [1, 1])
            a = shift.evidence.read_plate(PlateOrigin(BATCH, LEFT, 11))
            b = shift.evidence.read_plate(PlateOrigin(BATCH, RIGHT, 11))
            self.assertEqual((a.key.trigger_id, a.reading), ("A", 31))
            self.assertEqual((b.key.trigger_id, b.reading), ("B", 31))
            trial = attach_to(shift, make_ports(batch=BATCH))
            self.assertIsNone(trial.lane(LEFT).read_current())

    def test_receipt_cannot_authorize_another_lane(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("B", 11, 31),)))
            left = step(binding, shift.evidence, LEFT)
            right_slot = binding.lane(RIGHT).read_current()
            with self.assertRaises(InvalidPlate):
                confirm_release_eligibility(right_slot, Handoff(right_slot.token, left.handoff.receipt))
            self.assertEqual(binding.lane(RIGHT).current_position, 0)
            self.assertEqual(step(binding, shift.evidence, RIGHT).next_position, 1)

    def test_repeat_current(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, crossed_ports())
            shift.db.execute("""
                CREATE TEMP TRIGGER block_release BEFORE UPDATE ON lane_positions
                BEGIN SELECT RAISE(ABORT, 'release blocked'); END
            """)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "release blocked"):
                step(binding, shift.evidence, LEFT)
            committed = shift.evidence.read_trigger(TriggerKey(BATCH, "A"))
            self.assertEqual(len(committed), 1)
            shift.db.execute("DROP TRIGGER temp.block_release")
            repeated = step(binding, shift.evidence, LEFT)
            self.assertEqual(repeated.handoff.receipt.plate, committed[0])
            self.assertEqual(repeated.next_position, 1)
            self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "A")), committed)
            self.assertEqual(trace_values(binding), [
                ("read", LEFT, 0, 11), ("read", LEFT, 0, 11), ("release", LEFT, 0, 11),
            ])

    def test_conflicting_evidence_preserves_original(self):
        for conflicting in (("B", 11, 32), ("A", 12, 31), ("A", 11, 32)):
            with self.subTest(conflicting=conflicting), reopen_shift(":memory:") as shift:
                register(shift.catalog, BATCH, ("A", "B"))
                binding = attach_to(shift, make_ports((("A", 11, 31), conflicting)))
                initial = step(binding, shift.evidence, LEFT).handoff.receipt.plate
                with self.assertRaises(InvalidPlate):
                    step(binding, shift.evidence, LEFT)
                self.assertEqual(binding.lane(LEFT).current_position, 1)
                self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "A")), (initial,))
                self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "B")), ())
