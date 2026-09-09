from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry  # noqa: E402
from agent_on.qualify import GATES_RESPONSES, Wire, probe_caching, probe_throughput, run_gates_responses, run_qualify  # noqa: E402
from agent_on.state import read_observed  # noqa: E402


class ResponsesGatesTest(unittest.TestCase):
    def test_all_six_pass_on_the_mock_and_reasoning_is_seen(self):
        with MockSource() as m:
            r = run_gates_responses(Wire(m.base_url, "x", timeout=10, wire="responses"))
            self.assertEqual(set(r["gates"]), set(GATES_RESPONSES))
            self.assertTrue(r["all_pass"], r)
            self.assertTrue(r["thinking_block_seen"])
            self.assertTrue(r["completed"])
            self.assertEqual(r["thinking_tokens"], 9)
            cont = [b for b in m.responses_bodies if any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in (b.get("input") if isinstance(b.get("input"), list) else []))]
            self.assertEqual(cont[0]["input"][-1]["call_id"], "call_mock_1")                       # the model's own call_id was replayed

    def test_each_broken_gate_is_the_one_reported(self):
        allowed = {"forced_function_call": {"forced_function_call", "function_call_arguments_stream", "function_call_output_continuation"}}
        for name in GATES_RESPONSES:
            with MockSource(fail_gates=(name,)) as m:
                r = run_gates_responses(Wire(m.base_url, "x", timeout=10, wire="responses"))
                failed = {g for g, ok in r["gates"].items() if not ok}
                self.assertIn(name, failed)
                self.assertTrue(failed <= allowed.get(name, {name}), (name, failed))

    def test_incomplete_status_with_a_correct_call_still_passes(self):
        with MockSource(quirks=("responses_incomplete_status",)) as m:
            r = run_gates_responses(Wire(m.base_url, "x", timeout=10, wire="responses"))
            self.assertTrue(r["gates"]["forced_function_call"])
            self.assertEqual(r["details"]["forced_function_call_status_field"], "incomplete")

    def test_probes_on_the_responses_wire(self):
        with MockSource() as m:
            w = Wire(m.base_url, "x", timeout=10, wire="responses")
            self.assertGreater(probe_throughput(w)["tok_s"], 0)
            self.assertTrue(probe_caching(w)["caching"])
        with MockSource(caching=False) as m:
            self.assertFalse(probe_caching(Wire(m.base_url, "x", timeout=10, wire="responses"))["caching"])
        w = Wire("http://127.0.0.1:9", "x", timeout=2, wire="responses")
        self.assertEqual(probe_caching(w)["caching"], "unknown")

    def test_run_qualify_records_the_responses_wire_beside_messages(self):
        with MockSource(catalog=[omlx_entry("alpha")]) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_qualify(sb.paths, "a", env={}, timeout=10)
            doc = run_qualify(sb.paths, "a", env={}, timeout=10, wire="responses", codex_bin="/nonexistent/codex")
            self.assertEqual(doc["wire"], "responses")
            self.assertTrue(all(doc["gates"].values()))
            qs = read_observed(sb.paths)["routes"]["mock/alpha"]["qualifications"]
            self.assertEqual(set(qs), {"messages", "responses"})
            self.assertEqual(qs["responses"]["wire"], "responses")
            self.assertIsNone(qs["responses"]["fingerprint"]["harness_version"])                       # no codex binary: unmeasured, not invented
            self.assertEqual(qs["messages"]["gates"].keys() ^ qs["responses"]["gates"].keys(), set(qs["messages"]["gates"]) ^ set(GATES_RESPONSES))
            with self.assertRaises(ValueError):
                run_qualify(sb.paths, "a", env={}, timeout=10, wire="responses", baseline=True)


if __name__ == "__main__":
    unittest.main()
