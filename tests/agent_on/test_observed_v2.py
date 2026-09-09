from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import (OBSERVED_VERSION, empty_observed, empty_route, migrate_observed,  # noqa: E402
                                       validate_observed)
from agent_on.state import read_observed, update_observed  # noqa: E402

BASE = "http://127.0.0.1:1"
V1_ROUTE = {"served": True, "checked": "2026-09-08T00:00:00Z",
            "limits": {"input": {"configured": 131072, "advertised": None, "verified": None, "checked": None},
                       "output": {"configured": None, "advertised": None, "verified": None, "checked": None}},
            "cost_model": {"context": 131072, "context_basis": "declared", "tok_s": 50.0, "usd_per_mtok": None, "caching": True,
                           "concurrency": 1, "thinking": None, "checked": "2026-09-08T00:00:00Z",
                           "harness_baseline_tokens": {"value": 54380, "measured_by": "qualify --baseline", "claude_code": "2.1.263", "at": "2026-09-08T00:00:00Z"}},
            "last_qualification": {"pass": True, "gates": {"text_sse": True}, "thinking_block_seen": False, "completed": True, "at": "2026-09-08T00:00:00Z",
                                   "fingerprint": {"effective_route_sha": "abc", "wire_model": "alpha", "source_identity": None, "claude_code": "2.1.263"}},
            "last_session": {"id": "s1", "at": "2026-09-08T00:00:00Z", "first_request": None,
                             "this_run": {"turns": 1, "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "cost_usd": 0.0, "models_seen": ["alpha"]},
                             "session_total": {"turns": 1, "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "cost_usd": 0.0, "covered_turns": 1, "uncovered_turns": 0},
                             "scope_note": "fresh", "duration_ms": 10, "effort": None, "permission_mode": None, "claude_code": "2.1.263"}}


def v1_doc() -> dict:
    d = empty_observed()
    d["version"] = 1
    d["routes"]["mock/alpha"] = json.loads(json.dumps(V1_ROUTE))
    return d


class MigrationTest(unittest.TestCase):
    def test_v1_upgrades_in_memory_and_is_written_back_as_v2(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir(parents=True)
            sb.paths.observed_json.write_text(json.dumps(v1_doc()), encoding="utf-8")
            doc = read_observed(sb.paths)
            self.assertEqual(doc["version"], OBSERVED_VERSION)
            r = doc["routes"]["mock/alpha"]
            self.assertNotIn("last_qualification", r)
            q = r["qualifications"]["messages"]
            self.assertEqual(q["wire"], "messages")
            self.assertEqual(q["fingerprint"]["harness_version"], "2.1.263")
            self.assertNotIn("claude_code", q["fingerprint"])
            b = r["cost_model"]["harness_baseline_tokens"]
            self.assertEqual(b, {"claude": {"value": 54380, "measured_by": "qualify --baseline", "harness_version": "2.1.263", "at": "2026-09-08T00:00:00Z"}})
            ls = r["last_session"]
            self.assertEqual((ls["harness"], ls["harness_version"]), ("claude", "2.1.263"))
            self.assertNotIn("claude_code", ls)
            self.assertEqual(json.loads(sb.paths.observed_json.read_text())["version"], 1)             # read alone rewrites nothing
            update_observed(sb.paths, lambda d: None)
            self.assertEqual(json.loads(sb.paths.observed_json.read_text())["version"], 2)

    def test_migrate_is_idempotent_and_v2_validates(self):
        d = migrate_observed(v1_doc())
        again = migrate_observed(json.loads(json.dumps(d)))
        self.assertEqual(d, again)
        validate_observed(d)

    def test_v2_rejects_an_unknown_wire_or_harness(self):
        d = migrate_observed(v1_doc())
        r = d["routes"]["mock/alpha"]
        r["qualifications"]["chat"] = dict(r["qualifications"]["messages"], wire="chat")
        with self.assertRaises(SchemaError):
            validate_observed(d)
        del r["qualifications"]["chat"]
        r["cost_model"]["harness_baseline_tokens"]["goose"] = r["cost_model"]["harness_baseline_tokens"]["claude"]
        with self.assertRaises(SchemaError):
            validate_observed(d)
        del r["cost_model"]["harness_baseline_tokens"]["goose"]
        r["qualifications"]["responses"] = dict(r["qualifications"]["messages"], wire="messages")            # wire must equal its key
        with self.assertRaises(SchemaError):
            validate_observed(d)

    def test_empty_route_is_v2_shaped(self):
        r = empty_route()
        self.assertEqual(r["qualifications"], {})
        self.assertEqual(r["cost_model"]["harness_baseline_tokens"], {})
        self.assertNotIn("last_qualification", r)


if __name__ == "__main__":
    unittest.main()
