"""An in-process source for tests and the gate: catalogs in either shape, OpenRouter's key endpoint, `/health`,
and — for the launcher and `qualify` — a deterministic Anthropic `/v1/messages` (JSON and SSE) plus
`/v1/messages/count_tokens`. Binds port 0 so the OS picks an ephemeral port (`gate.mock.ephemeral`)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARKERS = ("SYSTEM_BLOCK_ALPHA", "SYSTEM_BLOCK_BETA")
GATE_NAMES = ("text_sse", "claude_system_block_instructions", "forced_structured_tool", "streaming_input_json_delta",
              "tool_result_continuation", "claude_adaptive_effort_policy", "thinking")
# a provider quirk, not a failure: F2 measured GLM-5.2 through OpenRouter returning a correct tool_use block with
# stop_reason: "end_turn" — Claude Code completed the tool-call loop on that route regardless.
QUIRKS = ("end_turn_on_tool",)


def omlx_entry(model_id: str, max_model_len: int = 262144) -> dict:
    return {"id": model_id, "object": "model", "created": 1788723472, "owned_by": "omlx", "max_model_len": max_model_len}


def openrouter_entry(model_id: str, context_length: int = 1048576, max_out: int = 131072, prompt: str = "0.000000966",
                     completion: str = "0.000003036", cache_read: str | None = "0.0000001932", params: list[str] | None = None) -> dict:
    pricing = {"prompt": prompt, "completion": completion}
    if cache_read is not None:
        pricing["input_cache_read"] = cache_read
    return {"id": model_id, "context_length": context_length,
            "top_provider": {"context_length": context_length, "max_completion_tokens": max_out, "is_moderated": False},
            "pricing": pricing, "supported_parameters": params or ["reasoning", "reasoning_effort", "tools"]}


def _tokens(obj) -> int:
    """The mock's tokenizer: one token per four JSON characters, never below one."""
    return max(1, len(json.dumps(obj, ensure_ascii=False)) // 4)


def _chunks(text: str, n: int) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


def _system_text(system) -> str:
    if isinstance(system, str):
        return system
    return " ".join(b.get("text", "") for b in (system or []) if isinstance(b, dict))


class MockSource:
    def __init__(self, catalog: list[dict] | None = None, spend: dict | None = None, expect_key: str | None = None, *,
                 caching: bool = True, delay_s: float = 0.0, serialize: bool = False, max_context: int | None = None,
                 fail_gates: tuple[str, ...] = (), quirks: tuple[str, ...] = ()):
        bad = set(fail_gates) - set(GATE_NAMES)
        if bad:
            raise ValueError(f"unknown fail_gates {sorted(bad)}")
        bad = set(quirks) - set(QUIRKS)
        if bad:
            raise ValueError(f"unknown quirks {sorted(bad)}")
        self.catalog = list(catalog or [])
        self.spend = spend
        self.expect_key = expect_key
        self.caching, self.delay_s, self.serialize, self.max_context, self.fail_gates = caching, delay_s, serialize, max_context, tuple(fail_gates)
        self.quirks = tuple(quirks)
        self.requests: list[tuple[str, dict]] = []
        self.messages: list[dict] = []
        self._seen_system: set[str] = set()
        self._serial = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ---- the deterministic model ---------------------------------------------------------------------------------

    def _auth_ok(self, headers) -> bool:
        if not self.expect_key:
            return True
        return headers.get("x-api-key") == self.expect_key or headers.get("Authorization") == f"Bearer {self.expect_key}"

    def prompt_tokens(self, body: dict) -> int:
        return _tokens(body.get("messages") or []) + _tokens(_system_text(body.get("system"))) + _tokens(body.get("tools") or [])

    def reply(self, body: dict) -> tuple[int, dict]:
        prompt = self.prompt_tokens(body)
        if self.max_context is not None and prompt > self.max_context:
            return 400, {"type": "error", "error": {"type": "invalid_request_error",
                                                    "message": f"prompt is too long: {prompt} tokens > {self.max_context} maximum"}}
        if body.get("thinking") and "claude_adaptive_effort_policy" in self.fail_gates:
            return 400, {"type": "error", "error": {"type": "invalid_request_error", "message": "thinking is not supported"}}
        sys_text = _system_text(body.get("system"))
        cache_read = 0
        if sys_text:
            if sys_text in self._seen_system and self.caching:
                cache_read = _tokens(sys_text)
            self._seen_system.add(sys_text)
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else {}
        has_tool_result = isinstance(last.get("content"), list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in last["content"])
        content: list[dict] = []
        stop = "end_turn"
        if body.get("thinking") and "thinking" not in self.fail_gates:
            content.append({"type": "thinking", "thinking": "Considering the request briefly.", "signature": "mock-sig"})
        markers = [m for m in MARKERS if m in sys_text]
        if body.get("tools") and not has_tool_result and "forced_structured_tool" not in self.fail_gates:
            content.append({"type": "tool_use", "id": "toolu_mock_1", "name": body["tools"][0]["name"], "input": {"city": "Seoul"}})
            stop = "end_turn" if "end_turn_on_tool" in self.quirks else "tool_use"
        elif has_tool_result:
            if "tool_result_continuation" not in self.fail_gates:
                content.append({"type": "text", "text": "It is 18C and sunny in Seoul."})
        elif markers and "claude_system_block_instructions" not in self.fail_gates:
            content.append({"type": "text", "text": " ".join(markers)})
        elif "text_sse" not in self.fail_gates or body.get("thinking"):
            content.append({"type": "text", "text": "OK — the mock route is ready."})
        usage = {"input_tokens": prompt - cache_read, "output_tokens": 12, "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 0}
        return 200, {"id": "msg_mock", "type": "message", "role": "assistant", "model": body.get("model"), "content": content,
                     "stop_reason": stop, "stop_sequence": None, "usage": usage}

    def sse_events(self, resp: dict) -> list[dict]:
        u = resp["usage"]
        events = [{"type": "message_start", "message": {**resp, "content": [], "usage": {**u, "output_tokens": 0}}}]
        for i, block in enumerate(resp["content"]):
            if block["type"] == "text":
                events.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                for piece in _chunks(block["text"], 8):
                    events.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": piece}})
            elif block["type"] == "tool_use":
                if "streaming_input_json_delta" in self.fail_gates:
                    events.append({"type": "content_block_start", "index": i, "content_block": dict(block)})
                else:
                    events.append({"type": "content_block_start", "index": i, "content_block": {**block, "input": {}}})
                    for piece in _chunks(json.dumps(block["input"]), 6):
                        events.append({"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": piece}})
            elif block["type"] == "thinking":
                events.append({"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": ""}})
                events.append({"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": block["thinking"]}})
            events.append({"type": "content_block_stop", "index": i})
        events.append({"type": "message_delta", "delta": {"stop_reason": resp["stop_reason"], "stop_sequence": None}, "usage": {"output_tokens": u["output_tokens"]}})
        events.append({"type": "message_stop"})
        return events

    def _paced(self):
        """Sleep delay_s per request; under `serialize` hold one lock so concurrent requests queue."""
        if self.serialize:
            with self._serial:
                time.sleep(self.delay_s)
        elif self.delay_s:
            time.sleep(self.delay_s)

    # ---- the HTTP surface ----------------------------------------------------------------------------------------

    def start(self) -> "MockSource":
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_sse(self, events: list[dict]) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for e in events:
                    self.wfile.write(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode("utf-8"))
                    self.wfile.flush()

            def do_GET(self):
                mock.requests.append((self.path, dict(self.headers)))
                if self.path in ("/v1/models", "/api/v1/models"):
                    return self._send(200, {"object": "list", "data": mock.catalog})
                if self.path == "/health":
                    return self._send(200, {"status": "healthy"})
                if self.path in ("/v1/auth/key", "/api/v1/auth/key"):
                    if mock.expect_key and self.headers.get("Authorization") != f"Bearer {mock.expect_key}":
                        return self._send(401, {"error": {"message": "bad key"}})
                    return self._send(200, {"data": mock.spend or {}})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "body is not JSON"}})
                mock.requests.append((self.path, dict(self.headers)))
                if not mock._auth_ok(self.headers):
                    return self._send(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
                if self.path in ("/v1/messages/count_tokens", "/api/v1/messages/count_tokens"):
                    return self._send(200, {"input_tokens": mock.prompt_tokens(body)})
                if self.path in ("/v1/messages", "/api/v1/messages"):
                    mock.messages.append(body)
                    mock._paced()
                    code, resp = mock.reply(body)
                    if code != 200 or not body.get("stream"):
                        return self._send(code, resp)
                    return self._send_sse(mock.sse_events(resp))
                self._send(404, {"error": "not found"})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="mock-source")
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "MockSource":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
