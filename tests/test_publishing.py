import unittest

from archive.release import publish
from batch.identity import TriggerKey
from batch.registration import register
from review.lookup import lookup
from review.reconciliation import reopen_shift
from source.plate import PlateOrigin
from tests import BATCH, LEFT, RIGHT, attach_to, claim_values, make_ports, take_steps


class TestPublishing(unittest.TestCase):
    def test_signed_contrast(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, make_ports((("A", 11, 31), ("B", 14, 29)),
                                                  (("A", 18, 47), ("B", 20, 43))))
            take_steps(shift, binding, LEFT, RIGHT)
            signed = publish(shift.catalog, shift.evidence, shift.results, BATCH, "A")
            actual = lookup(shift.catalog, shift.results, BATCH, "A")
            self.assertEqual(actual.result_id, signed.result_id)
            self.assertEqual(claim_values(actual), (31, 47, 16, PlateOrigin(BATCH, LEFT, 11),
                                                    PlateOrigin(BATCH, RIGHT, 18)))
            take_steps(shift, binding, LEFT, RIGHT)
            publish(shift.catalog, shift.evidence, shift.results, BATCH, "B")
            self.assertEqual(claim_values(lookup(shift.catalog, shift.results, BATCH, "B")),
                             (29, 43, 14, PlateOrigin(BATCH, LEFT, 14), PlateOrigin(BATCH, RIGHT, 20)))

    def test_trigger_pairing(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A", "B"))
            binding = attach_to(shift, make_ports((("A", 11, 31), ("B", 14, 29)),
                                                  (("B", 15, 43), ("A", 18, 47))))
            take_steps(shift, binding, LEFT, RIGHT)
            self.assertIsNone(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A"))
            self.assertIsNone(publish(shift.catalog, shift.evidence, shift.results, BATCH, "B"))
            take_steps(shift, binding, LEFT, RIGHT)
            publish(shift.catalog, shift.evidence, shift.results, BATCH, "A")
            publish(shift.catalog, shift.evidence, shift.results, BATCH, "B")
            self.assertEqual(claim_values(lookup(shift.catalog, shift.results, BATCH, "A")),
                             (31, 47, 16, PlateOrigin(BATCH, LEFT, 11), PlateOrigin(BATCH, RIGHT, 18)))
            self.assertEqual(claim_values(lookup(shift.catalog, shift.results, BATCH, "B")),
                             (29, 43, 14, PlateOrigin(BATCH, LEFT, 14), PlateOrigin(BATCH, RIGHT, 15)))

    def test_no_cross_batch_pair(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A",))
            register(shift.catalog, "other", ("A",))
            first = attach_to(shift, make_ports((("A", 11, 31),)))
            second = attach_to(shift, make_ports(right=(("A", 18, 47),), batch="other"), "other")
            take_steps(shift, first, LEFT)
            take_steps(shift, second, RIGHT)
            for batch in (BATCH, "other"):
                self.assertIsNone(publish(shift.catalog, shift.evidence, shift.results, batch, "A"))
                self.assertIsNone(lookup(shift.catalog, shift.results, batch, "A"))

    def test_ready_stays_pending(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A",))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("A", 18, 47),)))
            take_steps(shift, binding, LEFT, RIGHT)
            self.assertEqual(len(shift.evidence.read_trigger(TriggerKey(BATCH, "A"))), 2)
            self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
            self.assertEqual(shift.results.read_published_batch(BATCH), {})
            self.assertIsNotNone(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A"))
            self.assertEqual(lookup(shift.catalog, shift.results, BATCH, "A").difference, 16)

    def test_half_pair_is_pending(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A",))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("A", 18, 47),)))
            take_steps(shift, binding, LEFT)
            self.assertEqual(binding.lane(LEFT).current_position, 1)
            self.assertEqual(binding.lane(RIGHT).current_position, 0)
            self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
            self.assertIsNone(shift.results.read_published(TriggerKey(BATCH, "A")))

    def test_publish_pending(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A",))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("A", 18, 47),)))
            take_steps(shift, binding, LEFT)
            self.assertIsNone(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A"))
            self.assertIsNone(lookup(shift.catalog, shift.results, BATCH, "A"))
            original = shift.evidence.read_plate(PlateOrigin(BATCH, LEFT, 11))
            self.assertEqual(original.reading, 31)
            take_steps(shift, binding, RIGHT)
            self.assertIsNotNone(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A"))
            self.assertEqual(lookup(shift.catalog, shift.results, BATCH, "A").difference, 16)

    def test_signed_precision(self):
        wide = 2 ** 100
        for left, right, difference in ((47, 31, -16), (31, 31, 0), (-wide, wide + 7, 2 * wide + 7),
                                        (wide, -wide + 3, -2 * wide + 3)):
            with self.subTest(left=left, right=right), reopen_shift(":memory:") as shift:
                register(shift.catalog, BATCH, ("A",))
                binding = attach_to(shift, make_ports((("A", 11, left),), (("A", 18, right),)))
                take_steps(shift, binding, LEFT, RIGHT)
                publish(shift.catalog, shift.evidence, shift.results, BATCH, "A")
                self.assertEqual(claim_values(lookup(shift.catalog, shift.results, BATCH, "A")),
                                 (left, right, difference, PlateOrigin(BATCH, LEFT, 11),
                                  PlateOrigin(BATCH, RIGHT, 18)))

    def test_republish(self):
        with reopen_shift(":memory:") as shift:
            register(shift.catalog, BATCH, ("A",))
            binding = attach_to(shift, make_ports((("A", 11, 31),), (("A", 18, 47),)))
            take_steps(shift, binding, LEFT, RIGHT)
            original = publish(shift.catalog, shift.evidence, shift.results, BATCH, "A")
            self.assertIsNotNone(original)
            self.assertEqual(publish(shift.catalog, shift.evidence, shift.results, BATCH, "A"), original)
            self.assertEqual(shift.results.read_published_batch(BATCH), {"A": original})
