from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.cost import attribute_run, fold_session, price_usage, sum_usage  # noqa: E402

PAID = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": None}   # USD per Mtok; no cache-write price published
FREE = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def u(i=0, o=0, cr=0, cw=0):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}


def turn(ts, model, usage):
    return {"timestamp": ts, "model": model, "usage": usage}


def run(launch_id, wire, started, ended, price, source="paid", priced_models=None):
    return {"launch_id": launch_id, "route": f"{source}/{wire}", "source": source, "wire_model": wire,
            "started": started, "ended": ended, "price": price, "priced_models": priced_models or {}}


class PriceTest(unittest.TestCase):
    def test_usage_times_price_over_four_fields(self):
        usd, why = price_usage(u(i=1_000_000, o=500_000, cr=2_000_000), PAID)
        self.assertEqual((usd, why), (1.0 + 1.0 + 0.2, []))

    def test_an_absent_price_is_not_zero(self):
        usd, why = price_usage(u(i=10, cw=10), PAID)
        self.assertIsNone(usd)
        self.assertIn("cache_write", why[0])
        self.assertEqual(price_usage(u(i=10), None), (None, ["no price table"]))
        self.assertEqual(price_usage(u(cw=0), PAID), (0.0, []))      # a zero field needs no price

    def test_sum_usage(self):
        self.assertEqual(sum_usage([u(i=1, o=2), u(i=3, cr=4)]), u(i=4, o=2, cr=4))


class AttributionTest(unittest.TestCase):
    T = ["2026-09-07T01:00:00Z", "2026-09-07T01:01:00Z", "2026-09-07T01:02:00Z", "2026-09-07T01:03:00Z"]

    def test_a_run_prices_its_own_window_at_its_own_snapshot(self):
        turns = [turn(self.T[0], "m", u(i=1_000_000)), turn(self.T[1], "m", u(o=1_000_000)), turn(self.T[3], "m", u(i=9))]
        line = attribute_run(turns, run("L1", "m", self.T[0], self.T[2], PAID))
        self.assertEqual(line["turns"], 2)
        self.assertEqual(line["cost_usd"], 3.0)
        self.assertEqual(line["models_seen"], ["m"])
        self.assertEqual(line["usage"], u(i=1_000_000, o=1_000_000))

    def test_a_switched_model_without_a_price_makes_the_run_unknown(self):
        turns = [turn(self.T[0], "m", u(i=10)), turn(self.T[1], "other", u(i=10))]
        line = attribute_run(turns, run("L1", "m", self.T[0], None, PAID))
        self.assertEqual(line["cost_usd"], "unknown")
        self.assertEqual(line["models_seen"], ["m", "other"])
        self.assertTrue(any("other" in r for r in line["unknown_reasons"]))
        priced = attribute_run(turns, run("L1", "m", self.T[0], None, PAID, priced_models={"other": FREE}))
        self.assertEqual(priced["cost_usd"], 0.00001)

    def test_unpriced_field_makes_the_run_unknown(self):
        line = attribute_run([turn(self.T[0], "m", u(cw=5))], run("L1", "m", self.T[0], None, PAID))
        self.assertEqual(line["cost_usd"], "unknown")


class FoldTest(unittest.TestCase):
    T = ["2026-09-07T01:00:00Z", "2026-09-07T01:01:00Z", "2026-09-07T02:00:00Z", "2026-09-07T02:01:00Z"]

    def test_fresh_session_this_run_equals_session_total(self):
        turns = [turn(self.T[0], "m", u(i=1_000_000)), turn(self.T[1], "m", u(o=1_000_000))]
        line = attribute_run(turns, run("L1", "m", self.T[0], self.T[1], PAID))
        total = fold_session(turns, [line])
        self.assertEqual(total["cost_usd"], line["cost_usd"])
        self.assertEqual((total["turns"], total["covered_turns"], total["uncovered_turns"]), (2, 2, 0))

    def test_paid_then_free_resume_is_paid_plus_zero_not_zero(self):
        # the rev-6 P2: a session begun on a paid route and resumed on a free one keeps the paid cost
        turns = [turn(self.T[0], "paid-m", u(i=1_000_000)), turn(self.T[1], "paid-m", u(o=1_000_000)),
                 turn(self.T[2], "free-m", u(i=5_000_000)), turn(self.T[3], "free-m", u(o=5_000_000))]
        r1 = attribute_run(turns, run("L1", "paid-m", self.T[0], self.T[1], PAID))
        r2 = attribute_run(turns, run("L2", "free-m", self.T[2], self.T[3], FREE, source="mock"))
        total = fold_session(turns, [r1, r2])
        self.assertEqual(r1["cost_usd"], 3.0)
        self.assertEqual(r2["cost_usd"], 0.0)
        self.assertEqual(total["cost_usd"], 3.0)
        self.assertEqual(total["usage"], u(i=6_000_000, o=6_000_000))
        self.assertEqual((total["covered_turns"], total["uncovered_turns"]), (4, 0))

    def test_turns_no_ledger_line_covers_make_the_total_unknown(self):
        # e.g. a session begun under the old launcher, resumed under agent-on: the past price cannot be restored
        turns = [turn(self.T[0], "m", u(i=100)), turn(self.T[2], "m", u(i=100))]
        r2 = attribute_run(turns, run("L2", "m", self.T[2], self.T[3], FREE))
        total = fold_session(turns, [r2])
        self.assertEqual(total["cost_usd"], "unknown")
        self.assertEqual((total["covered_turns"], total["uncovered_turns"]), (1, 1))
        self.assertTrue(any("not covered" in r for r in total["unknown_reasons"]))

    def test_an_unknown_run_makes_the_total_unknown(self):
        turns = [turn(self.T[0], "m", u(cw=5))]
        total = fold_session(turns, [attribute_run(turns, run("L1", "m", self.T[0], None, PAID))])
        self.assertEqual(total["cost_usd"], "unknown")

    def test_overlapping_runs_are_unknown_not_double_counted(self):
        turns = [turn(self.T[0], "m", u(i=100))]
        r1 = attribute_run(turns, run("L1", "m", self.T[0], None, FREE))
        r2 = attribute_run(turns, run("L2", "m", self.T[0], None, FREE))
        total = fold_session(turns, [r1, r2])
        self.assertEqual(total["cost_usd"], "unknown")


if __name__ == "__main__":
    unittest.main()
