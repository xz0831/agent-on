from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.mock_source import MockSource  # noqa: E402

TOOL = {"name": "get_weather", "description": "weather", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}


def post(base, path, body, headers=None, stream=False):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if stream:
                events = [json.loads(l[5:].strip()) for l in resp.read().decode().splitlines() if l.startswith("data:")]
                return resp.status, events
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
        e.close()
        return e.code, body


class MessagesTest(unittest.TestCase):
    def test_text_reply_json_and_stream(self):
        with MockSource() as m:
            st, r = post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(st, 200)
            self.assertEqual(r["content"][0]["type"], "text")
            self.assertEqual(r["stop_reason"], "end_turn")
            self.assertEqual(set(r["usage"]), {"input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"})
            st, ev = post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 64, "messages": [{"role": "user", "content": "hi"}], "stream": True}, stream=True)
            types = [e["type"] for e in ev]
            self.assertEqual(types[0], "message_start")
            self.assertEqual(types[-1], "message_stop")
            self.assertIn("content_block_delta", types)
            text = "".join(e["delta"]["text"] for e in ev if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta")
            self.assertIn("ready", text)
            self.assertEqual(len(m.messages), 2)
            self.assertEqual(m.messages[1]["stream"], True)

    def test_forced_tool_json_and_streamed_input_json_delta_then_continuation(self):
        with MockSource() as m:
            body = {"model": "x", "max_tokens": 64, "tools": [TOOL], "tool_choice": {"type": "tool", "name": "get_weather"},
                    "messages": [{"role": "user", "content": "Call get_weather for Seoul."}]}
            st, r = post(m.base_url, "/v1/messages", body)
            block = r["content"][0]
            self.assertEqual((r["stop_reason"], block["type"], block["name"], block["input"]), ("tool_use", "tool_use", "get_weather", {"city": "Seoul"}))
            st, ev = post(m.base_url, "/v1/messages", {**body, "stream": True}, stream=True)
            starts = [e["content_block"] for e in ev if e["type"] == "content_block_start"]
            self.assertEqual(starts[0]["type"], "tool_use")
            self.assertEqual(starts[0]["input"], {})
            partial = "".join(e["delta"]["partial_json"] for e in ev if e["type"] == "content_block_delta" and e["delta"]["type"] == "input_json_delta")
            self.assertEqual(json.loads(partial), {"city": "Seoul"})
            st, r2 = post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 64, "tools": [TOOL], "messages": [
                {"role": "user", "content": "Call get_weather for Seoul."},
                {"role": "assistant", "content": r["content"]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block["id"], "content": "18C and sunny"}]}]})
            self.assertIn("18C", r2["content"][0]["text"])

    def test_system_markers_thinking_caching_and_count_tokens(self):
        system = [{"type": "text", "text": "Include SYSTEM_BLOCK_ALPHA.", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "Also SYSTEM_BLOCK_BETA."}]
        with MockSource() as m:
            body = {"model": "x", "max_tokens": 64, "system": system, "messages": [{"role": "user", "content": "markers"}]}
            st, r = post(m.base_url, "/v1/messages", body)
            self.assertIn("SYSTEM_BLOCK_ALPHA", r["content"][0]["text"])
            self.assertIn("SYSTEM_BLOCK_BETA", r["content"][0]["text"])
            self.assertEqual(r["usage"]["cache_read_input_tokens"], 0)
            st, r = post(m.base_url, "/v1/messages", body)
            self.assertGreater(r["usage"]["cache_read_input_tokens"], 0)          # second identical system → cache hit
            st, r = post(m.base_url, "/v1/messages", {**body, "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}})
            self.assertEqual(r["content"][0]["type"], "thinking")
            self.assertEqual(r["content"][1]["type"], "text")
            st, c = post(m.base_url, "/v1/messages/count_tokens", body)
            self.assertEqual(st, 200)
            self.assertGreater(c["input_tokens"], 0)
        with MockSource(caching=False) as m:
            post(m.base_url, "/v1/messages", body)
            st, r = post(m.base_url, "/v1/messages", body)
            self.assertEqual(r["usage"]["cache_read_input_tokens"], 0)

    def test_auth_context_limit_and_fail_gates(self):
        with MockSource(expect_key="k-1") as m:
            body = {"model": "x", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}
            self.assertEqual(post(m.base_url, "/v1/messages", body)[0], 401)
            self.assertEqual(post(m.base_url, "/v1/messages", body, {"x-api-key": "k-1"})[0], 200)
            self.assertEqual(post(m.base_url, "/api/v1/messages", body, {"Authorization": "Bearer k-1"})[0], 200)
        with MockSource(max_context=50) as m:
            st, r = post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 1, "messages": [{"role": "user", "content": "word " * 200}]})
            self.assertEqual(st, 400)
            self.assertIn("too long", r["error"]["message"])
            self.assertEqual(post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]})[0], 200)
        with MockSource(fail_gates=("forced_structured_tool", "thinking")) as m:
            st, r = post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 8, "tools": [TOOL], "tool_choice": {"type": "tool", "name": "get_weather"},
                                                        "messages": [{"role": "user", "content": "x"}], "thinking": {"type": "adaptive"}})
            self.assertNotEqual(r["content"][0]["type"], "tool_use")
            self.assertNotIn("thinking", [b["type"] for b in r["content"]])
        with MockSource(fail_gates=("claude_adaptive_effort_policy",)) as m:
            st, _ = post(m.base_url, "/v1/messages", {"model": "x", "max_tokens": 8, "messages": [{"role": "user", "content": "x"}], "thinking": {"type": "adaptive"}})
            self.assertEqual(st, 400)

    def test_serialize_makes_concurrent_requests_queue(self):
        body = {"model": "x", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}

        def wall(m):
            t = time.monotonic()
            th = [threading.Thread(target=post, args=(m.base_url, "/v1/messages", body)) for _ in range(2)]
            [x.start() for x in th]
            [x.join() for x in th]
            return time.monotonic() - t

        with MockSource(delay_s=0.3) as m:
            self.assertLess(wall(m), 0.55)
        with MockSource(delay_s=0.3, serialize=True) as m:
            self.assertGreaterEqual(wall(m), 0.6)


if __name__ == "__main__":
    unittest.main()
