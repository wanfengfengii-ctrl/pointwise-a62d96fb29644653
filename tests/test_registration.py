import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.release import publish
from batch.identity import TriggerKey
from batch.registration import UnknownBatch, get_registered_batch, register
from batch.validation import ManifestConflict
from review.lookup import lookup
from review.reconciliation import reopen_shift
from source.progress import RecordingConflict, RecordingNotBound
from source.recording import InvalidRecording
from tests import BATCH, LEFT, RECORDING, RIGHT, attach_to, make_ports, take_steps


class TestRegistration(unittest.TestCase):
    def test_initial_registration(self):
        with reopen_shift(":memory:") as shift:
            manifest = register(shift.catalog, BATCH, ["A", "B"])
            self.assertEqual((manifest.batch_id, manifest.ordered_triggers), (BATCH, ("A", "B")))
            self.assertEqual(get_registered_batch(shift.catalog, BATCH), manifest)
            self.assertTrue(manifest.contains("A"))
            self.assertFalse(manifest.contains("a"))

    def test_repeat_same_manifest(self):
        with reopen_shift(":memory:") as shift:
            initial = register(shift.catalog, BATCH, ["B", "A"])
            repeated = register(shift.catalog, BATCH, ("B", "A"))
            self.assertEqual(initial, repeated)
            self.assertEqual(repeated.ordered_triggers, ("B", "A"))

    def test_idempotent_initialization(self):
        ports = make_ports((("A", 8, 31),), (("A", 9, 47),))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "shift.sqlite3"
            with reopen_shift(path) as shift:
                manifest = register(shift.catalog, BATCH, ("A", "B"))
                binding = attach_to(shift, ports)
                take_steps(shift, binding, LEFT, RIGHT)
                issued = publish(shift.catalog, shift.evidence, shift.results, BATCH, "A")
                self.assertIsNotNone(issued)
                previous = lookup(shift.catalog, shift.results, BATCH, "A")
                self.assertEqual(previous.difference, 16)
            with reopen_shift(path) as shift:
                self.assertEqual(register(shift.catalog, BATCH, ["A", "B"]), manifest)
                binding = attach_to(shift, ports)
                self.assertEqual([binding.lane(lane).current_position for lane in (LEFT, RIGHT)], [1, 1])
                self.assertEqual(take_steps(shift, binding, LEFT, RIGHT), (None, None))
                self.assertEqual(binding.trace, ())
                self.assertEqual([plate.reading for plate in shift.evidence.read_trigger(TriggerKey(BATCH, "A"))],
                                 [31, 47])
                self.assertEqual(lookup(shift.catalog, shift.results, BATCH, "A"), previous)
                self.assertEqual(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A"), issued)

    def test_conflicting_manifest(self):
        with reopen_shift(":memory:") as shift:
            manifest = register(shift.catalog, BATCH, ["A", "B"])
            with self.assertRaises(ManifestConflict):
                register(shift.catalog, BATCH, ["A", "C"])
            self.assertEqual(get_registered_batch(shift.catalog, BATCH), manifest)

    def test_reordered_manifest(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ["A", "B"])
            with self.assertRaises(ManifestConflict):
                register(shift.catalog, BATCH, ["B", "A"])
            self.assertEqual(get_registered_batch(shift.catalog, BATCH).ordered_triggers, ("A", "B"))

    def test_duplicate_trigger(self):
        with reopen_shift(":memory:") as shift:
            with self.assertRaisesRegex(ValueError, "duplicate trigger"):
                register(shift.catalog, BATCH, ["A", "A"])
            with self.assertRaises(UnknownBatch):
                get_registered_batch(shift.catalog, BATCH)
            self.assertEqual(register(shift.catalog, BATCH, ["A"]).ordered_triggers, ("A",))

    def test_attach_valid(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            ports = make_ports((("A", 11, 31),), (("B", 11, 43),))
            binding = attach_to(shift, reversed(ports))
            self.assertEqual(binding.recording_id, RECORDING)
            self.assertEqual(binding.lane(LEFT).read_current().plate.key.trigger_id, "A")
            self.assertEqual(binding.lane(RIGHT).read_current().plate.key.trigger_id, "B")
            self.assertEqual([binding.lane(lane).current_position for lane in (LEFT, RIGHT)], [0, 0])
            with self.assertRaises(RecordingConflict):
                attach_to(shift, tuple(replace(port, recording_id="second") for port in ports))
            self.assertEqual(attach_to(shift, ports).lane(LEFT).current_position, 0)

    def test_attach_mismatched_port(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            left, right = make_ports((("A", 11, 31),), (("B", 11, 43),))
            for invalid in (replace(right, batch_id="other"), replace(right, lane_id="other"),
                            replace(right, lane_id=LEFT), replace(right, recording_id="other")):
                with self.subTest(port=invalid):
                    with self.assertRaises(InvalidRecording):
                        attach_to(shift, (left, invalid))
                    for lane in (LEFT, RIGHT):
                        with self.assertRaises(RecordingNotBound):
                            shift.progress.read_position(BATCH, RECORDING, lane)
            binding = attach_to(shift, (left, right))
            self.assertEqual(binding.lane(LEFT).read_current().token.sequence, 11)
            self.assertEqual(binding.lane(RIGHT).read_current().plate.key.trigger_id, "B")
