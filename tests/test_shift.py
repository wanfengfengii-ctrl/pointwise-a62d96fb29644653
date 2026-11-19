import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.release import publish
from batch.identity import TriggerKey
from batch.registration import UnknownBatch, register
from batch.trigger_manifest import UnknownTrigger
from capture.control import step
from capture.resume import resume_capture
from review.checklist import checklist
from review.lookup import lookup
from review.reconciliation import reconcile_shift, reopen_shift
from source.plate import PlateOrigin
from tests import BATCH, LEFT, RIGHT, attach_to, claim_values, crossed_ports, take_steps, trace_values


def entry_values(entries):
    return [(entry.trigger_id, entry.status, entry.result_id) for entry in entries]


def setup_b_first(shift, ports):
    register(shift.catalog, BATCH, ("A", "B"))
    binding = attach_to(shift, ports)
    take_steps(shift, binding, LEFT, RIGHT, LEFT)
    publish(shift.catalog, shift.evidence, shift.results, BATCH, "B")
    return binding, lookup(shift.catalog, shift.results, BATCH, "B")


class TestShift(unittest.TestCase):
    def test_manifest_order_after_reopen(self):
        ports = crossed_ports()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "shift.sqlite3"
            with reopen_shift(path) as shift:
                _, original_b = setup_b_first(shift, ports)
                self.assertIsNotNone(original_b)
            with reopen_shift(path) as shift:
                entries = checklist(shift.catalog, shift.results, BATCH)
                self.assertEqual(entry_values(entries), [("A", "pending", None),
                                                         ("B", "published", original_b.result_id)])
                restored_b = lookup(shift.catalog, shift.results, BATCH, "B")
                self.assertEqual(restored_b, original_b)
                self.assertEqual(claim_values(restored_b),
                                 (29, 43, 14, PlateOrigin(BATCH, LEFT, 14), PlateOrigin(BATCH, RIGHT, 11)))
                self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
                binding = attach_to(shift, ports)
                left, right = resume_capture(binding, shift.evidence)
                self.assertEqual((left.position, left.current), (2, None))
                self.assertEqual((right.position, right.current.plate.key.trigger_id), (1, "A"))
                self.assertIsNone(right.handoff)
                self.assertEqual(trace_values(binding), [("read", RIGHT, 1, 18)])

    def test_unknown_trigger(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A",))
            self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
            with self.assertRaises(UnknownTrigger):
                lookup(shift.catalog, shift.results, BATCH, "B")
            with self.assertRaises(UnknownTrigger):
                publish(shift.catalog, shift.evidence, shift.results, BATCH, "B")

    def test_unknown_batch(self):
        with reopen_shift(":memory:") as shift:
            with self.assertRaises(UnknownBatch):
                checklist(shift.catalog, shift.results, BATCH)
            with self.assertRaises(UnknownBatch):
                lookup(shift.catalog, shift.results, BATCH, "A")

    def test_reopen_before_release(self):
        ports = crossed_ports()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "shift.sqlite3"
            with reopen_shift(path) as shift:
                register(shift.catalog, BATCH, ("A", "B"))
                binding = attach_to(shift, ports)
                shift.db.execute("""
                    CREATE TEMP TRIGGER interrupt_release AFTER UPDATE ON lane_positions
                    BEGIN SELECT RAISE(ABORT, 'release interrupted'); END
                """)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "release interrupted"):
                    step(binding, shift.evidence, LEFT)
                original = shift.evidence.read_plate(PlateOrigin(BATCH, LEFT, 11))
                self.assertEqual(original.reading, 31)
                self.assertEqual(binding.lane(LEFT).current_position, 0)
            with reopen_shift(path) as shift:
                binding = attach_to(shift, ports)
                left, right = resume_capture(binding, shift.evidence)
                self.assertEqual(left.position, 0)
                self.assertEqual(left.handoff.receipt.plate, original)
                self.assertEqual(right.position, 0)
                self.assertIsNone(right.handoff)
                taken = step(binding, shift.evidence, LEFT)
                self.assertEqual(taken.handoff, left.handoff)
                self.assertEqual(taken.next_position, 1)
                self.assertEqual(binding.lane(RIGHT).current_position, 0)
                self.assertEqual(shift.evidence.read_trigger(TriggerKey(BATCH, "A")), (original,))
                releases = [event for event in trace_values(binding) if event[0] == "release"]
                self.assertEqual(releases, [("release", LEFT, 0, 11)])

    def test_retry_publication_after_rollback(self):
        ports = crossed_ports()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "shift.sqlite3"
            with reopen_shift(path) as shift:
                binding, original_b = setup_b_first(shift, ports)
                self.assertIsNotNone(original_b)
                trace = trace_values(binding)
            with reopen_shift(path) as shift:
                binding = attach_to(shift, ports)
                take_steps(shift, binding, RIGHT)
                trace.extend(trace_values(binding))
                key = TriggerKey(BATCH, "A")
                original_boards = shift.evidence.read_trigger(key)
                self.assertEqual([(p.origin.lane, p.origin.sequence, p.reading) for p in original_boards],
                                 [(LEFT, 11, 31), (RIGHT, 18, 47)])
                shift.db.execute("CREATE TEMP TABLE commit_parent(id INTEGER PRIMARY KEY)")
                shift.db.execute("""
                    CREATE TEMP TABLE commit_guard (
                        id INTEGER REFERENCES commit_parent(id) DEFERRABLE INITIALLY DEFERRED
                    )
                """)
                shift.db.execute("""
                    CREATE TEMP TRIGGER interrupt_commit AFTER INSERT ON published_results
                    WHEN NEW.trigger_id = 'A'
                    BEGIN INSERT INTO commit_guard VALUES (1); END
                """)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY constraint failed"):
                    publish(shift.catalog, shift.evidence, shift.results, BATCH, "A")
                self.assertFalse(shift.db.in_transaction)
                self.assertIsNone(shift.results.read_published(key))
                self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
                self.assertEqual(shift.evidence.read_trigger(key), original_boards)
                self.assertEqual(lookup(shift.catalog, shift.results, BATCH, "B"), original_b)
                self.assertEqual(entry_values(checklist(shift.catalog, shift.results, BATCH)),
                                 [("A", "pending", None), ("B", "published", original_b.result_id)])
            with reopen_shift(path) as shift:
                self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
                self.assertEqual(shift.evidence.read_trigger(key), original_boards)
                self.assertEqual(lookup(shift.catalog, shift.results, BATCH, "B"), original_b)
                reconciled = reconcile_shift(shift, BATCH)
                a, b = reconciled.results
                self.assertEqual([a.trigger_id, b.trigger_id], ["A", "B"])
                self.assertEqual(claim_values(a), (31, 47, 16, PlateOrigin(BATCH, LEFT, 11),
                                                   PlateOrigin(BATCH, RIGHT, 18)))
                self.assertEqual(b, original_b)
                self.assertEqual(entry_values(reconciled.checklist),
                                 [("A", "published", a.result_id), ("B", "published", b.result_id)])
                self.assertEqual(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A").result_id,
                                 a.result_id)
                self.assertEqual(reconciled.captures, ())
            self.assertEqual(trace, [
                ("read", LEFT, 0, 11), ("release", LEFT, 0, 11),
                ("read", RIGHT, 0, 11), ("release", RIGHT, 0, 11),
                ("read", LEFT, 1, 14), ("release", LEFT, 1, 14),
                ("read", RIGHT, 1, 18), ("release", RIGHT, 1, 18),
            ])

    def test_reconcile_can_continue_capture(self):
        with reopen_shift(":memory:") as shift:
            binding, original_b = setup_b_first(shift, crossed_ports())
            reviewed = reconcile_shift(shift, BATCH, binding=binding, lanes=(RIGHT,))
            self.assertEqual(len(reviewed.captures), 1)
            self.assertTrue(reviewed.captures[0].exhausted)
            self.assertEqual([(item.trigger_id, item.difference) for item in reviewed.results],
                             [("A", 16), ("B", 14)])
            self.assertEqual(reviewed.results[1], original_b)
