"""An in-process source for tests and the gate: `/v1/models` (or `/api/v1/models`) in either catalog shape,
OpenRouter's key endpoint, `/health`. Binds port 0 so the OS picks an ephemeral port (`gate.mock.ephemeral`)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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


class MockSource:
    def __init__(self, catalog: list[dict] | None = None, spend: dict | None = None, expect_key: str | None = None):
        self.catalog = list(catalog or [])
        self.spend = spend
        self.expect_key = expect_key
        self.requests: list[tuple[str, dict]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "MockSource":
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):   # keep the test output clean
                pass

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

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
