from __future__ import annotations

import http.client
import io
import json
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.effort import (  # noqa: E402
    EffortRequestError, OmlxEffortAdapter, adapt_omlx_body, explicit_claude_effort, omlx_profile,
)
from agent_on.schemas.routes import Reasoning, Route, load_routes  # noqa: E402

FAKE = str(REPO / "tests" / "agent_on" / "fakeclaude.py")


def route(model: str, reasoning: Reasoning | None = None) -> Route:
    source = "omlx"
    return Route(f"{source}/{model}", source, model, (), None, reasoning, None, True)


class _Upstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler):
        super().__init__(("127.0.0.1", 0), handler)
        self.requests = []
        self.first = threading.Event()
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"

    def close(self):
        self.release.set()
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


class _JSONHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        payload = json.dumps({"data": [{"id": "DeepSeek-V4.1-Flash"}]}).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", "0")))
        self.server.requests.append((self.path, json.loads(raw), dict(self.headers)))  # type: ignore[attr-defined]
        payload = json.dumps({"ok": True}).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload))); self.end_headers(); self.wfile.write(payload)


class _StreamHandler(_JSONHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", "0")))
        self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
        self.wfile.write(b"data: first\n\n"); self.wfile.flush()
        self.server.first.set()  # type: ignore[attr-defined]
        self.server.release.wait(5)  # type: ignore[attr-defined]
        self.wfile.write(b"data: second\n\n"); self.wfile.flush()


class _RejectHandler(_JSONHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", "0")))
        payload = b'{"error":"fixture"}'
        self.send_response(422); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload))); self.end_headers(); self.wfile.write(payload)


class ProfileTest(unittest.TestCase):
    def test_explicit_cli_effort_parser_is_last_wins_and_validated(self):
        self.assertIsNone(explicit_claude_effort(["-p", "hi"]))
        self.assertEqual(explicit_claude_effort(["--effort", "low", "--effort=high"]), "high")
        self.assertEqual(explicit_claude_effort(["-p", "--effort", "high", "task"]), "high")
        self.assertIsNone(explicit_claude_effort(["--system-prompt", "--effort=low", "-p", "task"]))
        self.assertIsNone(explicit_claude_effort(["-p", "--", "--effort=low"]))
        self.assertIsNone(explicit_claude_effort(["-p", "literal --effort=low prompt"]))
        with self.assertRaisesRegex(ValueError, "requires a value"):
            explicit_claude_effort(["--effort"])
        with self.assertRaisesRegex(ValueError, "not one of"):
            explicit_claude_effort(["--effort=minimal"])

    def test_only_evidenced_model_families_are_inferred(self):
        ds = omlx_profile(route("DeepSeek-V4.1-Flash-oQ3e"))
        self.assertEqual([ds.map(x) for x in ("low", "medium", "high", "xhigh", "max")],
                         ["low", "high", "high", "max", "max"])
        qwen = omlx_profile(route("Qwen3.8-27B-Splash"))
        self.assertEqual([qwen.map(x) for x in ("low", "medium", "high", "xhigh", "max")],
                         ["low", "medium", "xhigh", "xhigh", "xhigh"])
        self.assertIsNone(omlx_profile(route("unknown-model")))
        self.assertIsNone(omlx_profile(route("Qwen3.8-7B")))
        disabled = Reasoning(False, (), (), "configured", "operator disabled")
        self.assertIsNone(omlx_profile(route("DeepSeek-V4.1-Flash", disabled)))

    def test_explicit_route_profile_wins_and_can_use_numeric_values(self):
        r = Reasoning(True, ("low", "high"), (), "configured", "fixture", (("low", 25), ("high", 90)))
        profile = omlx_profile(route("unknown-model", r))
        self.assertEqual((profile.map("low"), profile.map("high"), profile.source), (25, 90, "fixture"))

    def test_adaptation_maps_effort_and_disabled_thinking_wins_consistently(self):
        profile = omlx_profile(route("DeepSeek-V4.1-Flash"))
        body = {"model": "DeepSeek-V4.1-Flash", "thinking": {"type": "adaptive"},
                "output_config": {"effort": "medium", "format": {"type": "json"}},
                "messages": [{"role": "user", "content": "한글"}]}
        adapted, meta = adapt_omlx_body(body, profile)
        self.assertEqual(adapted["chat_template_kwargs"], {"reasoning_effort": "high", "enable_thinking": True})
        self.assertEqual(meta["effective"], "high")
        self.assertEqual(adapted["messages"], body["messages"])
        self.assertEqual(adapted["output_config"], body["output_config"])

        disabled, meta = adapt_omlx_body({**body, "thinking": {"type": "disabled"},
                                          "chat_template_kwargs": {"reasoning_effort": "max"}}, profile)
        self.assertEqual(disabled["thinking"]["type"], "disabled")
        self.assertEqual(disabled["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(meta["result"], "thinking-disabled-overrode-effort")

    def test_absent_effort_preserves_default_and_unknown_profile_rejects_selection(self):
        body = {"model": "unknown", "messages": []}
        adapted, meta = adapt_omlx_body(body, None)
        self.assertIs(adapted, body)
        self.assertEqual(meta["result"], "default-preserved")
        with self.assertRaisesRegex(EffortRequestError, "no declared effort profile"):
            adapt_omlx_body({**body, "output_config": {"effort": "high"}}, None)
        forwarded, meta = adapt_omlx_body({**body, "output_config": {"effort": "high"}}, None,
                                           allow_unprofiled_passthrough=True)
        self.assertNotIn("chat_template_kwargs", forwarded)
        self.assertEqual(meta["result"], "unsupported-profile-passthrough")


class AdapterTest(unittest.TestCase):
    def test_forwards_tools_unicode_auth_and_injects_only_template_kwargs(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\nbackend = "omlx"\n') as sb:
                receipt = sb.root / "effort.jsonl"
                adapter = OmlxEffortAdapter(upstream.url, [route("DeepSeek-V4.1-Flash")], receipt).start()
                try:
                    body = {"model": "DeepSeek-V4.1-Flash", "stream": True, "thinking": {"type": "adaptive"},
                            "output_config": {"effort": "high"}, "messages": [{"role": "user", "content": "안녕"}],
                            "tools": [{"name": "echo", "input_schema": {"type": "object"}}]}
                    conn = http.client.HTTPConnection("127.0.0.1", int(adapter.base_url.rsplit(":", 1)[1]))
                    conn.request("POST", "/v1/messages?beta=true", json.dumps(body).encode(),
                                 {"content-type": "application/json", "x-api-key": "secret-not-in-receipt"})
                    response = conn.getresponse(); self.assertEqual(response.status, 200); response.read(); conn.close()
                finally:
                    adapter.close()
                path, captured, headers = upstream.requests[0]
                self.assertEqual(path, "/v1/messages?beta=true")
                self.assertEqual(captured["messages"], body["messages"])
                self.assertEqual(captured["tools"], body["tools"])
                self.assertEqual(captured["chat_template_kwargs"], {"reasoning_effort": "high", "enable_thinking": True})
                self.assertEqual(headers["x-api-key"], "secret-not-in-receipt")
                self.assertNotIn("secret-not-in-receipt", receipt.read_text())
                self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
                self.assertEqual(adapter.records()[0]["model"], "DeepSeek-V4.1-Flash")
                self.assertEqual([x["result"] for x in adapter.records()], ["mapped", "delivered", "accepted", "completed"])
                self.assertTrue(all(x["request_id"] == adapter.records()[0]["request_id"] for x in adapter.records()))
        finally:
            upstream.close()

    def test_rejects_a_model_outside_the_launch_allowlist(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\n') as sb:
                adapter = OmlxEffortAdapter(upstream.url, [route("DeepSeek-V4.1-Flash")], sb.root / "r.jsonl").start()
                try:
                    port = int(adapter.base_url.rsplit(":", 1)[1])
                    conn = http.client.HTTPConnection("127.0.0.1", port)
                    body = {"model": "Qwen3.8-27B", "messages": [], "output_config": {"effort": "high"}}
                    conn.request("POST", "/v1/messages", json.dumps(body).encode(), {"content-type": "application/json"})
                    response = conn.getresponse(); payload = response.read(); conn.close()
                    self.assertEqual(response.status, 400)
                    self.assertIn(b"route-pinned", payload)
                    self.assertEqual(upstream.requests, [])
                finally:
                    adapter.close()
        finally:
            upstream.close()

    def test_explicit_effort_on_allowlisted_unknown_model_is_rejected_locally(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox('version = 1\n[sources.local]\nbase_url = "http://127.0.0.1:1"\n') as sb:
                adapter = OmlxEffortAdapter(upstream.url, [route("unknown-model")], sb.root / "r.jsonl",
                                            strict_unknown=True).start()
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", int(adapter.base_url.rsplit(":", 1)[1]))
                    body = {"model": "unknown-model", "messages": [], "output_config": {"effort": "high"}}
                    conn.request("POST", "/v1/messages", json.dumps(body).encode(), {"content-type": "application/json"})
                    response = conn.getresponse(); payload = response.read(); conn.close()
                    self.assertEqual(response.status, 400)
                    self.assertIn(b"no declared effort profile", payload)
                    self.assertEqual(upstream.requests, [])
                finally:
                    adapter.close()
        finally:
            upstream.close()

    def test_disabled_thinking_is_consistent_on_the_forwarded_wire(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox('version = 1\n[sources.local]\nbase_url = "http://127.0.0.1:1"\n') as sb:
                adapter = OmlxEffortAdapter(upstream.url, [route("DeepSeek-V4.1-Flash")], sb.root / "r.jsonl").start()
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", int(adapter.base_url.rsplit(":", 1)[1]))
                    body = {"model": "DeepSeek-V4.1-Flash", "messages": [], "thinking": {"type": "adaptive"},
                            "output_config": {"effort": "max"}, "chat_template_kwargs": {"enable_thinking": False}}
                    conn.request("POST", "/v1/messages", json.dumps(body).encode(), {"content-type": "application/json"})
                    response = conn.getresponse(); response.read(); conn.close()
                    self.assertEqual(response.status, 200)
                finally:
                    adapter.close()
                forwarded = upstream.requests[0][1]
                self.assertEqual(forwarded["thinking"]["type"], "disabled")
                self.assertEqual(forwarded["chat_template_kwargs"], {"enable_thinking": False})
                self.assertEqual(adapter.records()[0]["mapping_result"], "thinking-disabled-overrode-effort")
        finally:
            upstream.close()

    def test_catalog_get_is_forwarded_but_other_gets_are_not(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\n') as sb:
                adapter = OmlxEffortAdapter(upstream.url, [route("DeepSeek-V4.1-Flash")], sb.root / "r.jsonl").start()
                try:
                    port = int(adapter.base_url.rsplit(":", 1)[1])
                    conn = http.client.HTTPConnection("127.0.0.1", port)
                    conn.request("GET", "/v1/models"); response = conn.getresponse(); payload = response.read(); conn.close()
                    self.assertEqual(response.status, 200)
                    self.assertIn(b"DeepSeek-V4.1-Flash", payload)
                    conn = http.client.HTTPConnection("127.0.0.1", port)
                    conn.request("GET", "/status"); response = conn.getresponse(); response.read(); conn.close()
                    self.assertEqual(response.status, 404)
                finally:
                    adapter.close()
        finally:
            upstream.close()

    def test_conflicting_profiles_for_one_wire_model_are_rejected(self):
        one = route("same", Reasoning(True, ("high",), (), "configured", "one", (("high", "high"),)))
        two = route("same", Reasoning(True, ("high",), (), "configured", "two", (("high", "xhigh"),)))
        with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\n') as sb:
            with self.assertRaisesRegex(ValueError, "conflicting effort profiles"):
                OmlxEffortAdapter("http://127.0.0.1:1", [one, two], sb.root / "r.jsonl")

    def test_upstream_rejection_is_distinct_from_mapping_and_delivery(self):
        upstream = _Upstream(_RejectHandler)
        try:
            with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\n') as sb:
                adapter = OmlxEffortAdapter(upstream.url, [route("DeepSeek-V4.1-Flash")], sb.root / "r.jsonl").start()
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", int(adapter.base_url.rsplit(":", 1)[1]))
                    body = {"model": "DeepSeek-V4.1-Flash", "messages": [], "output_config": {"effort": "high"}}
                    conn.request("POST", "/v1/messages", json.dumps(body).encode(), {"content-type": "application/json"})
                    response = conn.getresponse(); response.read(); conn.close()
                    self.assertEqual(response.status, 422)
                finally:
                    adapter.close()
                records = adapter.records()
                self.assertEqual([x["result"] for x in records], ["mapped", "delivered", "upstream-rejected", "completed"])
                self.assertEqual(records[2]["upstream_status"], 422)
        finally:
            upstream.close()

    def test_sse_first_chunk_arrives_before_upstream_finishes(self):
        upstream = _Upstream(_StreamHandler)
        try:
            with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\n') as sb:
                adapter = OmlxEffortAdapter(upstream.url, [route("DeepSeek-V4.1-Flash")], sb.root / "r.jsonl").start()
                port = int(adapter.base_url.rsplit(":", 1)[1])
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                body = {"model": "DeepSeek-V4.1-Flash", "messages": [], "output_config": {"effort": "low"}}
                conn.request("POST", "/v1/messages", json.dumps(body).encode(), {"content-type": "application/json"})
                response = conn.getresponse()
                self.assertTrue(upstream.first.wait(1))
                first = response.readline()
                self.assertEqual(first, b"data: first\n")
                upstream.release.set()
                self.assertIn(b"data: second", response.read())
                conn.close(); adapter.close()
        finally:
            upstream.close()

    def test_unreachable_upstream_is_a_clean_502(self):
        probe = ThreadingHTTPServer(("127.0.0.1", 0), _JSONHandler)
        port = probe.server_port
        probe.server_close()
        with Sandbox('version = 1\n[sources.omlx]\nbase_url = "http://127.0.0.1:1"\n') as sb:
            adapter = OmlxEffortAdapter(f"http://127.0.0.1:{port}", [route("DeepSeek-V4.1-Flash")], sb.root / "r.jsonl").start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", int(adapter.base_url.rsplit(":", 1)[1]))
                body = {"model": "DeepSeek-V4.1-Flash", "messages": []}
                conn.request("POST", "/v1/messages", json.dumps(body).encode(), {"content-type": "application/json"})
                response = conn.getresponse(); response.read(); conn.close()
                self.assertEqual(response.status, 502)
            finally:
                adapter.close()


class HarnessLifecycleTest(unittest.TestCase):
    ROUTES = '''version = 1
[sources.local]
base_url = "{base}"
catalog = "/v1/models"
backend = "omlx"
[routes."local/DeepSeek-V4.1-Flash"]
aliases = ["ds"]
'''

    def test_new_omlx_launch_uses_loopback_and_reports_metadata(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox(self.ROUTES.format(base=upstream.url)) as sb:
                out = sb.root / "child"
                env = {"PATH": "/usr/bin:/bin", "FAKE_CLAUDE_OUT": str(out)}
                doc = harness.run_launch(sb.paths, "ds", ["-p", "hi"], env=env, claude_bin=FAKE,
                                         cwd=str(sb.root), probe_timeout=1, announce=False)
                child = json.loads((out / "env.json").read_text())
                self.assertRegex(child["ANTHROPIC_BASE_URL"], r"^http://127\.0\.0\.1:\d+$")
                self.assertNotEqual(child["ANTHROPIC_BASE_URL"], upstream.url)
                self.assertEqual(doc["effort"]["transport"], "loopback-chat-template-adapter")
                self.assertEqual(doc["effort"]["requests"], [])
                self.assertTrue(Path(doc["effort"]["receipt"]).exists())
                self.assertTrue(str(Path(doc["effort"]["receipt"]).parent).startswith(str(sb.paths.state)))
                self.assertEqual(list(sb.paths.run_dir.iterdir()), [])
        finally:
            upstream.close()

    def test_spawn_failure_closes_adapter_and_removes_run_directory(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox(self.ROUTES.format(base=upstream.url)) as sb:
                with mock.patch.object(harness, "spawn", side_effect=RuntimeError("fixture spawn failure")):
                    with self.assertRaisesRegex(RuntimeError, "fixture spawn failure"):
                        harness.run_launch(sb.paths, "ds", ["-p", "hi"], env={"PATH": "/usr/bin:/bin"},
                                           claude_bin=FAKE, cwd=str(sb.root), probe_timeout=1, announce=False)
                self.assertEqual(list(sb.paths.run_dir.iterdir()), [])
        finally:
            upstream.close()

    def test_harness_passes_raw_tier_bindings_to_adapter_conflict_validation(self):
        upstream = _Upstream(_JSONHandler)
        try:
            with Sandbox(self.ROUTES.format(base=upstream.url)) as sb:
                seen = []

                def reject(_upstream, routes, _receipt, **_kwargs):
                    seen.extend(routes)
                    raise ValueError("fixture conflicting effort profiles")

                with mock.patch.object(harness, "OmlxEffortAdapter", side_effect=reject):
                    with self.assertRaisesRegex(ValueError, "conflicting effort profiles"):
                        harness.run_launch(sb.paths, "ds", ["-p", "hi"], sonnet="ds", haiku="ds",
                                           env={"PATH": "/usr/bin:/bin"}, claude_bin=FAKE, cwd=str(sb.root),
                                           probe_timeout=1, announce=False)
                self.assertEqual(len(seen), 3)
                self.assertEqual(list(sb.paths.run_dir.iterdir()), [])
        finally:
            upstream.close()

    def test_unknown_profile_warning_is_visible_before_spawn(self):
        upstream = _Upstream(_JSONHandler)
        try:
            text = f'''version = 1
[sources.local]
base_url = "{upstream.url}"
catalog = "/v1/models"
backend = "omlx"
[routes."local/unknown-model"]
aliases = ["unknown"]
'''
            with Sandbox(text) as sb:
                doc = harness.run_launch(sb.paths, "unknown", [], dry_run=True, env={"PATH": "/usr/bin:/bin"},
                                         claude_bin=FAKE, cwd=str(sb.root), probe_timeout=1, announce=False)
                self.assertTrue(any("default/UI effort passes through un-applied" in w for w in doc["warnings"]))
                self.assertIsNone(doc["effort"]["profile"])
        finally:
            upstream.close()

    def test_unknown_profile_warning_is_printed_before_child_spawn(self):
        upstream = _Upstream(_JSONHandler)
        try:
            text = f'''version = 1
[sources.local]
base_url = "{upstream.url}"
catalog = "/v1/models"
backend = "omlx"
[routes."local/unknown-model"]
aliases = ["unknown"]
'''
            with Sandbox(text) as sb:
                stderr = io.StringIO()

                def observe_spawn(*_args, **_kwargs):
                    self.assertIn("warning: oMLX model has no effort profile", stderr.getvalue())
                    return 0

                with redirect_stderr(stderr), mock.patch.object(harness, "spawn", side_effect=observe_spawn):
                    harness.run_launch(sb.paths, "unknown", [], env={"PATH": "/usr/bin:/bin"}, claude_bin=FAKE,
                                       cwd=str(sb.root), probe_timeout=1, announce=True)
                self.assertLess(stderr.getvalue().index("local/unknown-model"),
                                stderr.getvalue().index("warning: oMLX model has no effort profile"))
        finally:
            upstream.close()

    def test_splash_and_openrouter_stay_direct(self):
        upstream = _Upstream(_JSONHandler)
        try:
            for backend in ("splash", "openrouter"):
                with self.subTest(backend=backend):
                    text = f'''version = 1
[sources.native]
base_url = "{upstream.url}"
catalog = "/v1/models"
backend = "{backend}"
[routes."native/DeepSeek-V4.1-Flash"]
aliases = ["native"]
'''
                    with Sandbox(text) as sb:
                        out = sb.root / "child"
                        env = {"PATH": "/usr/bin:/bin", "FAKE_CLAUDE_OUT": str(out)}
                        doc = harness.run_launch(sb.paths, "native", ["-p", "hi"], env=env, claude_bin=FAKE,
                                                 cwd=str(sb.root), probe_timeout=1, announce=False)
                        child = json.loads((out / "env.json").read_text())
                        self.assertEqual(child["ANTHROPIC_BASE_URL"], upstream.url)
                        self.assertEqual(doc["effort"]["transport"], "direct-anthropic-output_config")
                        self.assertNotIn("receipt", doc["effort"])
        finally:
            upstream.close()


if __name__ == "__main__":
    unittest.main()
