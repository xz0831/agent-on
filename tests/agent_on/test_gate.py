from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from agent_on.gate import INNER_ENV, run_gate, run_smoke  # noqa: E402
from agent_on.mock_source import MockSource, omlx_entry  # noqa: E402
from agent_on.state import read_observed, update_observed  # noqa: E402

BASE = "http://127.0.0.1:1"


class GateTest(unittest.TestCase):
    def test_smoke_reproduces_f1_on_the_mock(self):
        with MockSource(catalog=[omlx_entry("alive"), omlx_entry("extra")]) as m:
            s = run_smoke(m)
            self.assertTrue(s["ok"], s)
            self.assertEqual(s["results"]["route.served:mock/dead"], "fail")
            self.assertEqual(s["results"]["route.served:mock/alive"], "pass")
            self.assertEqual(s["results"]["route.served:mock/extra"], "pass")
        with MockSource(catalog=[]) as m:                       # nothing served: the smoke itself must notice
            self.assertFalse(run_smoke(m)["ok"])

    def test_gate_records_last_gate_run_with_skips_and_an_ephemeral_port(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb, mock.patch.dict(os.environ, {INNER_ENV: "1"}):
            doc = run_gate(sb.paths)
            self.assertEqual(doc["tests"]["skipped"], "inner gate (tests already running)")
            self.assertTrue(doc["smoke"]["ok"])
            g = read_observed(sb.paths)["last_gate_run"]
            self.assertEqual(g["result"], "pass")
            self.assertGreaterEqual(g["mock_port"], 1024)
            self.assertNotEqual(g["mock_port"], 1)
            self.assertIn("route.served:mock/alpha", g["skipped"])             # never synced → skip, listed
            self.assertIn("credential.not_in_child_env", g["skipped"])
            self.assertTrue(any(s.startswith("tests:") for s in g["skipped"]))
            self.assertEqual(g["verifiers"], {"declared": [], "ran": []})
            self.assertEqual(g["invariants"]["route.served:mock/alpha"], "skip")
            self.assertIsNone(read_observed(sb.paths)["last_check"])           # the gate never writes last_check
            # and the gate's own record satisfies the two gate invariants on the next evaluation
            again = run_gate(sb.paths)
            byid = {(i["id"], i.get("subject")): i["result"] for i in again["invariants"]}
            self.assertEqual(byid[("gate.no_silent_skip", None)], "pass")
            self.assertEqual(byid[("gate.mock.ephemeral", None)], "pass")

    def test_a_failing_invariant_fails_the_gate(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb, mock.patch.dict(os.environ, {INNER_ENV: "1"}):
            def plant(doc):
                doc["last_gate_run"] = {"at": "x", "commit": "x", "result": "pass", "tests": 0, "verifiers": {"declared": ["v"], "ran": []},
                                        "invariants": {}, "skipped": [], "skipped_reasons": [], "mock_port": 51873}
            update_observed(sb.paths, plant)
            doc = run_gate(sb.paths)
            self.assertEqual(doc["result"], "fail")
            self.assertEqual({i["id"]: i["result"] for i in doc["invariants"]}["gate.no_silent_skip"], "fail")


if __name__ == "__main__":
    unittest.main()
