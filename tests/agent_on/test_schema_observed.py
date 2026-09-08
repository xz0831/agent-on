from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import (  # noqa: E402
    USAGE_FIELDS, compute_context, empty_observed, empty_route, empty_source, forbid_claude_cost, validate_observed,
)


def usage(**kw) -> dict:
    return {k: kw.get(k, 0) for k in USAGE_FIELDS}


def full_session(cost="unknown") -> dict:
    return {"id": "s", "at": "2026-09-07T00:00:00Z",
            "first_request": {"input_tokens_total": 10, "usage": usage(input_tokens=10)},
            "this_run": {"turns": 1, "usage": usage(input_tokens=10), "cost_usd": cost, "models_seen": ["m"]},
            "session_total": {"turns": 1, "usage": usage(input_tokens=10), "cost_usd": cost, "covered_turns": 1, "uncovered_turns": 0},
            "scope_note": "fresh", "duration_ms": 1, "effort": None, "permission_mode": None, "claude_code": "2.1.263"}


class ShapeTest(unittest.TestCase):
    def test_empty_document_validates_and_every_unmeasured_field_is_null_not_absent(self):
        doc = empty_observed()
        validate_observed(doc)
        r = empty_route()
        self.assertIsNone(r["served"])
        self.assertEqual(r["cost_model"]["caching"], "unknown")
        self.assertEqual(set(r["limits"]["input"]), {"configured", "advertised", "verified", "checked"})
        self.assertIn("identity", empty_source())

    def assertRule(self, rule, doc):
        with self.assertRaises(SchemaError) as cm:
            validate_observed(doc)
        self.assertEqual(cm.exception.rule, rule, str(cm.exception))

    def test_missing_keys_and_bad_values_are_rejected_by_name(self):
        doc = empty_observed(); del doc["spend"]
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["version"] = 2
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["sources"]["s"] = {"reachable": True}
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["routes"]["r"] = empty_route(); del doc["routes"]["r"]["cost_model"]["caching"]
        self.assertRule("observed.route.shape", doc)
        doc = empty_observed(); doc["routes"]["r"] = empty_route(); doc["routes"]["r"]["cost_model"]["caching"] = None
        self.assertRule("observed.route.shape", doc)
        doc = empty_observed(); doc["routes"]["r"] = empty_route(); doc["routes"]["r"]["served"] = "yes"
        self.assertRule("observed.route.shape", doc)
        doc = empty_observed(); doc["last_check"] = {"at": "x"}
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["last_gate_run"] = {"at": "x", "result": "pass"}
        self.assertRule("observed.shape", doc)

    def test_claude_codes_own_cost_figure_is_rejected_anywhere(self):  # F11
        doc = empty_observed(); doc["routes"]["r"] = empty_route()
        doc["routes"]["r"]["last_session"] = {"skipped": "x", "total_cost_usd": 0.24}
        self.assertRule("observed.no_claude_cost", doc)
        doc = empty_observed(); doc["spend"]["x"] = [{"costUSD": 1}]
        self.assertRule("observed.no_claude_cost", doc)
        forbid_claude_cost({"a": [{"b": {"ok": 1}}]})  # no raise

    def test_last_session_is_skipped_or_full(self):
        doc = empty_observed(); doc["routes"]["r"] = empty_route()
        doc["routes"]["r"]["last_session"] = {"skipped": "no-session-persistence"}
        validate_observed(doc)
        doc["routes"]["r"]["last_session"] = full_session(0.0)
        validate_observed(doc)
        doc["routes"]["r"]["last_session"] = full_session("unknown")
        validate_observed(doc)
        doc["routes"]["r"]["last_session"] = full_session(-1)
        self.assertRule("observed.session.shape", doc)
        doc["routes"]["r"]["last_session"] = full_session("free")
        self.assertRule("observed.session.shape", doc)
        s = full_session(); del s["session_total"]["covered_turns"]; doc["routes"]["r"]["last_session"] = s
        self.assertRule("observed.session.shape", doc)
        doc["routes"]["r"]["last_session"] = {"skipped": ""}
        self.assertRule("observed.session.shape", doc)


class ContextTest(unittest.TestCase):
    """§7: min(declared, verified) when verified is present, else min(declared, configured, advertised);
    declared participates in both branches; verified only lowers; a tie names `declared`."""

    def tier(self, **kw):
        return {"configured": kw.get("configured"), "advertised": kw.get("advertised"), "verified": kw.get("verified"), "checked": None}

    def test_verified_never_lifts_the_declared_cap(self):
        self.assertEqual(compute_context(32768, self.tier(verified=131072)), (32768, "declared"))

    def test_verified_lowers(self):
        self.assertEqual(compute_context(131072, self.tier(verified=100000)), (100000, "verified"))
        self.assertEqual(compute_context(None, self.tier(verified=100000)), (100000, "verified"))

    def test_verified_branch_ignores_configured_and_advertised(self):
        self.assertEqual(compute_context(131072, self.tier(verified=131072, configured=8192, advertised=4096)), (131072, "declared"))

    def test_unverified_branch_takes_the_minimum_and_names_it(self):
        self.assertEqual(compute_context(200000, self.tier(configured=131072, advertised=262144)), (131072, "configured"))
        self.assertEqual(compute_context(200000, self.tier(advertised=100000)), (100000, "advertised"))
        self.assertEqual(compute_context(None, self.tier(configured=131072, advertised=262144)), (131072, "configured"))

    def test_tie_names_declared(self):
        self.assertEqual(compute_context(131072, self.tier(configured=131072, advertised=262144)), (131072, "declared"))

    def test_nothing_known_is_null_not_zero(self):
        self.assertEqual(compute_context(None, self.tier()), (None, None))


if __name__ == "__main__":
    unittest.main()
