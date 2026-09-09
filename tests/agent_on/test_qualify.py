from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on import mock_source  # noqa: E402
from agent_on.mock_source import GATE_NAMES, MockSource  # noqa: E402
from agent_on.qualify import GATES, Wire, probe_caching, probe_concurrency, probe_limits, probe_throughput, run_gates  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import empty_observed, empty_route, validate_observed  # noqa: E402


class GatesTest(unittest.TestCase):
    def test_all_six_pass_on_the_mock_and_thinking_is_seen(self):
        with MockSource() as m:
            r = run_gates(Wire(m.base_url, "x", timeout=10))
            self.assertEqual(set(r["gates"]), set(GATES))
            self.assertTrue(r["all_pass"], r)
            self.assertTrue(r["thinking_block_seen"])
            self.assertTrue(r["completed"])
            # F-fix 2: the preferred path — usage.output_tokens_details.thinking_tokens, a real measurement,
            # never a chars // 4 estimate. THINKING_TOKENS_DETAIL is the mock's fixed measured value.
            self.assertEqual(r["thinking_tokens"], mock_source.THINKING_TOKENS_DETAIL)
            self.assertEqual(r["details"]["forced_structured_tool_status"], 200)
            # the tool_result continuation replayed the model's own tool_use id
            replay = [b for b in m.messages if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in (b["messages"][-1].get("content") or []) if isinstance(b["messages"][-1].get("content"), list))]
            self.assertEqual(replay[0]["messages"][-1]["content"][0]["tool_use_id"], "toolu_mock_1")

    def test_thinking_tokens_falls_back_to_output_tokens_when_the_source_reports_no_detail(self):
        # F-fix 2: a source that doesn't report output_tokens_details.thinking_tokens (not every Anthropic-wire
        # source does; OpenRouter does) falls back to the whole reply's output_tokens — which also counts the
        # probe's short "OK" answer, never a character estimate.
        with MockSource(quirks=("thinking_no_usage_detail",)) as m:
            r = run_gates(Wire(m.base_url, "x", timeout=10))
            self.assertTrue(r["thinking_block_seen"])
            self.assertEqual(r["thinking_tokens"], 12)                                    # the mock's fixed output_tokens

    def test_thinking_tokens_is_none_when_the_probe_did_not_return_200(self):
        r = run_gates(Wire("http://127.0.0.1:9", "x", timeout=2))
        self.assertIsNone(r["thinking_tokens"])

    def test_each_broken_gate_is_the_one_reported(self):
        for name in GATES:
            with MockSource(fail_gates=(name,)) as m:
                r = run_gates(Wire(m.base_url, "x", timeout=10))
                self.assertFalse(r["gates"][name], name)
                others = [g for g in GATES if g != name and not r["gates"][g]]
                # breaking the forced tool also starves the streamed-tool and continuation gates: that is real, not a test artefact
                allowed = {"forced_structured_tool": {"streaming_input_json_delta", "tool_result_continuation"}}.get(name, set())
                self.assertTrue(set(others) <= allowed, (name, others))
        with MockSource(fail_gates=("thinking",)) as m:
            r = run_gates(Wire(m.base_url, "x", timeout=10))
            self.assertTrue(r["all_pass"])
            self.assertFalse(r["thinking_block_seen"])
            self.assertIsNone(r["thinking_tokens"])                                       # no thinking block: nothing to measure
        self.assertEqual(set(GATE_NAMES) - {"thinking"}, set(GATES))

    def test_forced_structured_tool_ignores_stop_reason_but_records_it(self):  # F2
        # GLM-5.2 through OpenRouter's Anthropic wire returned a correct tool_use block with stop_reason: "end_turn"
        # (measured 2026-09-08); Claude Code completed the tool-call loop on that route regardless. The gate is
        # stricter than Claude Code — drop the stop_reason requirement, but keep recording what was seen.
        with MockSource() as m:
            r = run_gates(Wire(m.base_url, "x", timeout=10))
            self.assertEqual(r["details"]["forced_structured_tool_stop_reason"], "tool_use")
        with MockSource(quirks=("end_turn_on_tool",)) as m:
            r = run_gates(Wire(m.base_url, "x", timeout=10))
            self.assertTrue(r["all_pass"], r)
            self.assertTrue(r["gates"]["forced_structured_tool"])
            self.assertEqual(r["details"]["forced_structured_tool_stop_reason"], "end_turn")

    def test_auth_and_unreachable_are_statuses_not_exceptions(self):
        with MockSource(expect_key="k") as m:
            r = run_gates(Wire(m.base_url, "x", key="wrong", timeout=10))
            self.assertFalse(r["all_pass"])
            self.assertEqual(r["details"]["text_sse_status"], 401)
            self.assertTrue(run_gates(Wire(m.base_url, "x", key="k", timeout=10))["all_pass"])
        r = run_gates(Wire("http://127.0.0.1:9", "x", timeout=2))
        self.assertFalse(r["all_pass"])
        self.assertEqual(r["details"]["text_sse_status"], 0)
        self.assertIsNone(r["thinking_block_seen"])


class ProbesTest(unittest.TestCase):
    def test_throughput_and_concurrency(self):
        # De-flake (final review, Plan C): concurrency==2 needs pair_s/serial_s < 1.5. At delay_s=0.2 the fixed
        # per-request overhead (thread start + TCP connect for the pair) was itself close to 0.2*0.5=0.1s, putting
        # the ratio right on the 1.5 boundary — that is what flaked on a loaded machine. 0.8s gives that assertion
        # ~4x the margin (overhead is a fixed cost, not a fraction of delay_s) while keeping the whole test's wall
        # time under 5s. The serialize=True arm's ratio (~2, forced by the lock queuing the pair back-to-back) has
        # a wide margin at any delay_s and was not the flaky assertion, so it stays at 0.2s.
        with MockSource(delay_s=0.8) as m:
            t = probe_throughput(Wire(m.base_url, "x", timeout=10))
            self.assertGreater(t["tok_s"], 0)
            self.assertEqual(t["output_tokens"], 12)
            c = probe_concurrency(Wire(m.base_url, "x", timeout=10))
            self.assertEqual(c["concurrency"], 2)
        with MockSource(delay_s=0.2, serialize=True) as m:
            c = probe_concurrency(Wire(m.base_url, "x", timeout=10))
            self.assertEqual(c["concurrency"], 1)
            self.assertGreater(c["ratio"], 1.5)

    def test_caching_true_and_false_are_measurements(self):
        with MockSource() as m:
            c = probe_caching(Wire(m.base_url, "x", timeout=10))
            self.assertTrue(c["caching"])
            self.assertGreater(c["cache_read_second"], 1000)
        with MockSource(caching=False) as m:
            self.assertFalse(probe_caching(Wire(m.base_url, "x", timeout=10))["caching"])

    def test_limits_bisection_finds_the_enforced_boundary(self):
        with MockSource(max_context=500) as m:
            r = probe_limits(Wire(m.base_url, "x", timeout=10), 100, 2000, count_tokens=True)
            self.assertIsNotNone(r["verified"])
            self.assertTrue(450 <= r["verified"] <= 500, r)
            self.assertEqual(r["basis"], "count_tokens")
            self.assertLessEqual(len(r["probes"]), 10)
            self.assertEqual(r["probes"][1]["tokens"], 100)                                   # lo is verified, not assumed
            self.assertTrue(all(p["status"] in (200, 400) for p in r["probes"]))
        with MockSource() as m:                                                          # nothing enforced below hi: no boundary measured
            r = probe_limits(Wire(m.base_url, "x", timeout=10), 100, 400, count_tokens=False)
            self.assertIsNone(r["verified"])
            self.assertEqual((r["accepted_up_to"], r["basis"]), (400, "estimate"))
        with MockSource(max_context=500) as m:                                           # refused, but only estimated: still not `verified`
            r = probe_limits(Wire(m.base_url, "x", timeout=10), 100, 2000, count_tokens=False)
            self.assertIsNone(r["verified"])
            self.assertTrue(200 <= r["accepted_up_to"] < 500, r)                              # requested units (one word ≈ one token): an estimate, so never `verified`


class QualificationShapeTest(unittest.TestCase):
    def test_last_qualification_must_carry_gates_and_a_fingerprint(self):
        doc = empty_observed()
        doc["routes"]["r"] = empty_route()
        doc["routes"]["r"]["qualifications"]["messages"] = {"pass": True, "gates": {g: True for g in GATES}, "thinking_block_seen": False, "completed": True, "wire": "messages",
                                                   "at": "2026-09-08T00:00:00Z", "fingerprint": {"effective_route_sha": "a", "wire_model": "m", "source_identity": None, "harness_version": None}}
        validate_observed(doc)
        doc["routes"]["r"]["qualifications"]["messages"]["fingerprint"] = {"wire_model": "m"}
        with self.assertRaises(SchemaError) as cm:
            validate_observed(doc)
        self.assertEqual(cm.exception.rule, "observed.qualification.shape")


if __name__ == "__main__":
    unittest.main()
