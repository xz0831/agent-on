from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.ids import ulid  # noqa: E402

ALPHABET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


class UlidTest(unittest.TestCase):
    def test_shape(self):
        u = ulid()
        self.assertEqual(len(u), 26)
        self.assertTrue(set(u) <= ALPHABET)

    def test_sorts_by_time_and_is_deterministic_for_fixed_inputs(self):
        a = ulid(now_ms=1_000, rand=bytes(10))
        b = ulid(now_ms=2_000, rand=bytes(10))
        self.assertLess(a, b)
        self.assertEqual(a, ulid(now_ms=1_000, rand=bytes(10)))
        self.assertEqual(ulid(now_ms=0, rand=bytes(10)), "0" * 26)

    def test_unique_in_a_burst(self):
        self.assertEqual(len({ulid() for _ in range(2000)}), 2000)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            ulid(now_ms=-1)
        with self.assertRaises(ValueError):
            ulid(rand=b"short")


if __name__ == "__main__":
    unittest.main()
