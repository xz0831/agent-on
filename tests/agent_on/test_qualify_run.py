from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.invariants import build_context, evaluate  # noqa: E402
from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.qualify import GATES, run_qualify  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402
from agent_on.state import read_observed  # noqa: E402
from agent_on.status import build_status, render_text  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fakeclaude.py")
CATALOG = [omlx_entry("alpha"), openrouter_entry("vendor/model-x")]


class RunQualifyTest(unittest.TestCase):
    def test_free_route_is_qualified_and_the_fingerprint_is_current_until_the_config_changes(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            doc = run_qualify(sb.paths, "a", env={}, timeout=10)
            self.assertTrue(doc["written"])
            self.assertTrue(all(doc["gates"].values()))
            obs = read_observed(sb.paths)["routes"]["mock/alpha"]
            q = obs["last_qualification"]
            self.assertTrue(q["pass"])
            self.assertEqual(set(q["gates"]), set(GATES))
            self.assertTrue(q["thinking_block_seen"])
            table = load_routes(sb.paths)
            self.assertEqual(q["fingerprint"]["effective_route_sha"], table.effective_sha(table.routes["mock/alpha"]))
            self.assertEqual(q["fingerprint"]["wire_model"], "alpha")
            self.assertEqual(q["fingerprint"]["source_identity"], "owned_by=omlx")
            cm = obs["cost_model"]
            self.assertGreater(cm["tok_s"], 0)
            self.assertIn(cm["concurrency"], (1, 2))
            self.assertTrue(cm["caching"])
            self.assertEqual(cm["thinking"]["observed"], True)
            self.assertIsNotNone(cm["checked"])
            self.assertIsNone(cm["harness_baseline_tokens"])                             # not asked for → not invented
            self.assertEqual([i["result"] for i in doc["invariants"] if i["id"] == "qualification.current"], ["pass"])
            text = MOCK_ROUTES.format(base=m.base_url).replace("input = 8192", "input = 4096")
            sb.paths.routes_toml.write_text(text, encoding="utf-8")
            res = {r.id: r for r in evaluate(build_context(sb.paths), ids=["qualification.current"], route="mock/alpha")}
            self.assertEqual(res["qualification.current"].result, "fail")
            self.assertIn("effective_route_sha", res["qualification.current"].reason)
            status = build_status(sb.paths)
            self.assertIn("cache ✓", render_text(status))                                   # the §12 line is in the text view

    def test_a_failing_gate_is_recorded_as_a_failure_not_hidden(self):
        with MockSource(catalog=CATALOG, fail_gates=("tool_result_continuation",)) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            doc = run_qualify(sb.paths, "a", env={}, timeout=10)
            self.assertFalse(doc["gates"]["tool_result_continuation"])
            self.assertFalse(read_observed(sb.paths)["routes"]["mock/alpha"]["last_qualification"]["pass"])

    def test_baseline_uses_the_launcher_and_records_the_first_request(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "FAKE_CLAUDE_OUT": str(sb.root / "out")}
            doc = run_qualify(sb.paths, "a", baseline=True, env=env, timeout=10, claude_bin=FAKE)
            self.assertEqual(doc["baseline"], 21000)
            hb = read_observed(sb.paths)["routes"]["mock/alpha"]["cost_model"]["harness_baseline_tokens"]
            self.assertEqual((hb["value"], hb["measured_by"]), (21000, "qualify --baseline"))
            argv = json.loads((sb.root / "out" / "argv.json").read_text())
            self.assertEqual(argv[-2:], ["-p", "Reply with exactly: OK"])

    def test_limits_bisects_and_lowers_the_context_never_lifting_the_declared_cap(self):
        with MockSource(catalog=CATALOG, max_context=3000) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            doc = run_qualify(sb.paths, "a", limits=True, env={}, timeout=10)
            v = doc["probes"]["limits"]["verified"]
            self.assertTrue(2700 <= v <= 3000, v)
            r = read_observed(sb.paths)["routes"]["mock/alpha"]
            self.assertEqual(r["limits"]["input"]["verified"], v)
            self.assertEqual((r["cost_model"]["context"], r["cost_model"]["context_basis"]), (v, "verified"))   # declared 8192 > verified
        with MockSource(catalog=CATALOG, max_context=100000) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            doc = run_qualify(sb.paths, "a", limits=True, env={}, timeout=10)
            r = read_observed(sb.paths)["routes"]["mock/alpha"]
            self.assertIsNone(r["limits"]["input"]["verified"])                              # nothing refused: no boundary, nothing written
            self.assertIsNotNone(doc["probes"]["limits"]["accepted_up_to"])
            self.assertEqual(r["cost_model"]["context_basis"], "declared")                    # the cap stands

    def test_paid_probes_need_allow_paid_and_gates_alone_do_not(self):
        with MockSource(catalog=CATALOG, expect_key="k-1") as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            doc = run_qualify(sb.paths, "x", limits=True, env={"MOCK_PAID_KEY": "k-1"}, timeout=10)
            self.assertFalse(doc["written"])
            self.assertIn("--allow-paid", doc["refused"])
            self.assertIsNone(read_observed(sb.paths)["routes"].get("paid/vendor/model-x"))
            doc = run_qualify(sb.paths, "x", env={"MOCK_PAID_KEY": "k-1"}, timeout=10)
            self.assertTrue(doc["written"])
            self.assertTrue(all(doc["gates"].values()))
            doc = run_qualify(sb.paths, "x", env={"MOCK_PAID_KEY": "wrong"}, timeout=10)
            self.assertFalse(doc["gates"]["text_sse"])
            self.assertEqual(doc["details"]["text_sse_status"], 401)
            cm = read_observed(sb.paths)["routes"]["paid/vendor/model-x"]["cost_model"]
            self.assertEqual(cm["caching"], "unknown")                                     # a probe that got 401 measured nothing
            self.assertIsNone(cm["thinking"]["observed"])
            self.assertIsNone(cm["tok_s"])


if __name__ == "__main__":
    unittest.main()
