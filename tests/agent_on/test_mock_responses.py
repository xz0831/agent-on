from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.mock_source import RESPONSES_GATE_NAMES, MockSource  # noqa: E402

TOOL = {"type": "function", "name": "get_weather", "description": "d", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}


def post(base, body, stream=False):
    body = {"model": "x", **body, **({"stream": True} if stream else {})}
    req = urllib.request.Request(base + "/v1/responses", data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        if not stream:
            return r.status, json.loads(r.read())
        events = []
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
        return r.status, events


class ResponsesMockTest(unittest.TestCase):
    def test_plain_reply_instructions_and_usage(self):
        with MockSource() as m:
            s, d = post(m.base_url, {"input": "Reply with exactly: OK", "max_output_tokens": 64})
            self.assertEqual((s, d["object"], d["status"]), (200, "response", "completed"))
            self.assertEqual([o["type"] for o in d["output"]], ["message"])
            self.assertTrue(d["output"][0]["content"][0]["text"])
            self.assertEqual(set(d["usage"]), {"input_tokens", "output_tokens", "total_tokens", "input_tokens_details", "output_tokens_details"})
            s, d = post(m.base_url, {"instructions": "Say SYSTEM_BLOCK_ALPHA and SYSTEM_BLOCK_BETA.", "input": "go"})
            text = d["output"][0]["content"][0]["text"]
            self.assertIn("SYSTEM_BLOCK_ALPHA", text)
            self.assertIn("SYSTEM_BLOCK_BETA", text)

    def test_forced_function_call_stream_and_continuation(self):
        with MockSource() as m:
            s, d = post(m.base_url, {"input": "Call get_weather for Seoul.", "tools": [TOOL], "tool_choice": {"type": "function", "name": "get_weather"}})
            call = d["output"][0]
            self.assertEqual((call["type"], call["name"], json.loads(call["arguments"])), ("function_call", "get_weather", {"city": "Seoul"}))
            self.assertTrue(call["call_id"])
            s, ev = post(m.base_url, {"input": "Call get_weather for Seoul.", "tools": [TOOL], "tool_choice": {"type": "function", "name": "get_weather"}}, stream=True)
            types = [e["type"] for e in ev]
            self.assertIn("response.function_call_arguments.delta", types)
            self.assertEqual(types[-1], "response.completed")
            done = [e for e in ev if e["type"] == "response.output_item.done"][0]["item"]
            self.assertEqual(done["call_id"], call["call_id"])
            s, d = post(m.base_url, {"input": [{"role": "user", "content": "Call get_weather for Seoul."}, call,
                                             {"type": "function_call_output", "call_id": call["call_id"], "output": "18C and sunny"}], "tools": [TOOL]})
            self.assertIn("sunny", d["output"][0]["content"][0]["text"])
            self.assertEqual(len(m.responses_bodies), 3)

    def test_reasoning_caching_and_streamed_text(self):
        with MockSource() as m:
            s, d = post(m.base_url, {"input": "Think then reply OK.", "reasoning": {"effort": "low"}})
            self.assertEqual([o["type"] for o in d["output"]], ["reasoning", "message"])
            self.assertEqual(d["usage"]["output_tokens_details"]["reasoning_tokens"], 9)
            prefix = "cache me " * 300
            post(m.base_url, {"instructions": prefix, "input": "OK"})
            s, d = post(m.base_url, {"instructions": prefix, "input": "OK"})
            self.assertGreater(d["usage"]["input_tokens_details"]["cached_tokens"], 0)
            s, ev = post(m.base_url, {"input": "Reply with one sentence."}, stream=True)
            self.assertIn("response.output_text.delta", [e["type"] for e in ev])
            self.assertEqual("".join(e["delta"] for e in ev if e["type"] == "response.output_text.delta"), "OK — the mock route is ready.")

    def test_each_broken_responses_gate_is_the_one_reported(self):
        for name in RESPONSES_GATE_NAMES:
            with MockSource(fail_gates=(name,)) as m:
                if name == "reasoning_effort":
                    with self.assertRaises(urllib.error.HTTPError):
                        post(m.base_url, {"input": "x", "reasoning": {"effort": "low"}})
                elif name == "text_stream":
                    s, d = post(m.base_url, {"input": "x"})
                    self.assertEqual(d["output"], [])
                elif name == "instructions":
                    s, d = post(m.base_url, {"instructions": "SYSTEM_BLOCK_ALPHA SYSTEM_BLOCK_BETA", "input": "x"})
                    self.assertNotIn("SYSTEM_BLOCK_ALPHA", d["output"][0]["content"][0]["text"])
                elif name == "forced_function_call":
                    s, d = post(m.base_url, {"input": "x", "tools": [TOOL], "tool_choice": {"type": "function", "name": "get_weather"}})
                    self.assertNotEqual(d["output"][0]["type"], "function_call")
                elif name == "function_call_arguments_stream":
                    s, ev = post(m.base_url, {"input": "x", "tools": [TOOL], "tool_choice": {"type": "function", "name": "get_weather"}}, stream=True)
                    self.assertNotIn("response.function_call_arguments.delta", [e["type"] for e in ev])
                else:
                    s, d = post(m.base_url, {"input": [{"role": "user", "content": "x"}, {"type": "function_call", "call_id": "c1", "name": "get_weather", "arguments": "{}"},
                                                     {"type": "function_call_output", "call_id": "c1", "output": "18C"}], "tools": [TOOL]})
                    self.assertEqual(d["output"], [])


if __name__ == "__main__":
    unittest.main()
