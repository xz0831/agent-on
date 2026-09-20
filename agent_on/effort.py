"""Per-launch Claude→oMLX effort adapter.

Claude Code sends its current effort in ``output_config.effort`` on the
Anthropic Messages wire.  Splash and OpenRouter consume that field natively;
oMLX's Anthropic endpoint currently does not.  This module provides the narrow
oMLX-only bridge: a route-pinned loopback forwarder that copies the selected
effort into the model's chat-template kwargs and records metadata only.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .schemas.routes import CLAUDE_EFFORTS, Route, Source
from .util import utc_now

_BODY_LIMIT = 64 * 1024 * 1024
_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
                "transfer-encoding", "upgrade", "host", "content-length"}


@dataclass(frozen=True)
class EffortProfile:
    efforts: tuple[str, ...]
    mapping: tuple[tuple[str, str | int], ...]
    source: str

    def map(self, effort: str) -> str | int | None:
        return dict(self.mapping).get(effort)

    def as_dict(self) -> dict:
        return {"efforts": list(self.efforts), "map": dict(self.mapping), "source": self.source}


def omlx_profile(route: Route) -> EffortProfile | None:
    """Resolve only evidenced profiles. Unknown model names stay unsupported.

    A packaged/discovered route may carry an explicit reasoning effort list;
    otherwise the only built-in family rule is DeepSeek V4.1's published
    low/high/max template, with Claude's five labels mapped deliberately.
    """
    if route.reasoning:
        if not route.reasoning.supported:
            return None
        if route.reasoning.efforts:
            pairs = route.reasoning.effort_map or tuple((name, name) for name in route.reasoning.efforts)
            return EffortProfile(route.reasoning.efforts, pairs, route.reasoning.source)
    model = route.wire_model.lower().replace("_", "-")
    if "deepseek" in model and any(mark in model for mark in ("v4.1", "v41", "4.1")):
        pairs = (("low", "low"), ("medium", "high"), ("high", "high"), ("xhigh", "max"), ("max", "max"))
        return EffortProfile(CLAUDE_EFFORTS, pairs, "DeepSeek V4.1 encoding: low=50, high=75, max=100")
    if "qwen3.8-27b" in model or "qwen38-27b" in model:
        pairs = (("low", "low"), ("medium", "medium"), ("high", "xhigh"), ("xhigh", "xhigh"), ("max", "xhigh"))
        return EffortProfile(CLAUDE_EFFORTS, pairs, "Qwen3.8 native levels: low, medium, xhigh")
    return None


def launch_effort_metadata(source: Source, route: Route) -> dict:
    """Explain the path before a request exists; never claim native application."""
    if source.backend == "omlx":
        profile = omlx_profile(route)
        return {"backend": "omlx", "transport": "loopback-chat-template-adapter",
                "profile": profile.as_dict() if profile else None,
                "status": "ready" if profile else "default-only; explicit effort unsupported until a model profile is declared"}
    if source.backend in ("splash", "openrouter"):
        return {"backend": source.backend, "transport": "direct-anthropic-output_config",
                "profile": None if route.reasoning is None else {
                    "efforts": list(route.reasoning.efforts), "source": route.reasoning.source},
                "status": "native pass-through; backend acceptance is not inferred by agent-on"}
    return {"backend": source.backend, "transport": "direct-anthropic",
            "profile": None, "status": "transparent custom backend; effort support is unverified"}


class EffortRequestError(ValueError):
    pass


_CLAUDE_VALUE_OPTIONS = {
    "--agent", "--agents", "--append-system-prompt", "--autocompact", "--debug-file", "--environment",
    "--fallback-model", "--input-format", "--json-schema", "--max-budget-usd", "--model", "-n", "--name",
    "--output-format", "--permission-mode", "--permission-prompts", "--plugin-dir", "--plugin-url",
    "--remote-control-session-name-prefix", "--session-id", "--setting-sources", "--settings", "--system-prompt",
    "--system-prompt-file", "--append-system-prompt-file", "--system-prompt-snapshot",
}


def explicit_claude_effort(args: list[str]) -> str | None:
    """Return the last explicit CLI effort without interpreting option values or prompt text."""
    selected = None
    i = 0
    while i < len(args):
        value = None
        if args[i] == "--":
            break
        if args[i] == "--effort":
            if i + 1 >= len(args):
                raise ValueError("--effort requires a value")
            value = args[i + 1]
            i += 2
        elif args[i].startswith("--effort="):
            value = args[i].split("=", 1)[1]
            i += 1
        elif args[i] in _CLAUDE_VALUE_OPTIONS:
            i += 2
            continue
        elif any(args[i].startswith(option + "=") for option in _CLAUDE_VALUE_OPTIONS if option.startswith("--")):
            i += 1
            continue
        else:
            i += 1
        if value is not None:
            if value not in CLAUDE_EFFORTS:
                raise ValueError(f"--effort {value!r} is not one of {CLAUDE_EFFORTS}")
            selected = value
    return selected


def adapt_omlx_body(body: dict, profile: EffortProfile | None, *, allow_unprofiled_passthrough: bool = False) -> tuple[dict, dict]:
    """Translate one Anthropic request while preserving thinking precedence."""
    if not isinstance(body, dict):
        raise EffortRequestError("request body must be a JSON object")
    output = body.get("output_config")
    requested = output.get("effort") if isinstance(output, dict) else None
    thinking = body.get("thinking")
    thinking_type = thinking.get("type") if isinstance(thinking, dict) else None
    kwargs = body.get("chat_template_kwargs")
    if kwargs is not None and not isinstance(kwargs, dict):
        raise EffortRequestError("chat_template_kwargs must be an object")
    kwargs = dict(kwargs or {})

    disabled = thinking_type == "disabled" or kwargs.get("enable_thinking") is False
    if disabled:
        kwargs["enable_thinking"] = False
        kwargs.pop("reasoning_effort", None)
        adapted = dict(body)
        adapted["thinking"] = {**(thinking if isinstance(thinking, dict) else {}), "type": "disabled"}
        adapted["chat_template_kwargs"] = kwargs
        return adapted, {"requested": requested, "effective": None, "thinking": "disabled",
                         "result": "thinking-disabled-overrode-effort" if requested is not None else "thinking-disabled"}

    if requested is None:
        return body, {"requested": None, "effective": kwargs.get("reasoning_effort"),
                      "thinking": thinking_type, "result": "default-preserved" if "reasoning_effort" not in kwargs else "existing-backend-effort"}
    if not isinstance(requested, str) or requested not in CLAUDE_EFFORTS:
        raise EffortRequestError(f"Claude effort {requested!r} is not one of {CLAUDE_EFFORTS}")
    if profile is None:
        if allow_unprofiled_passthrough:
            return body, {"requested": requested, "effective": None, "thinking": thinking_type,
                          "result": "unsupported-profile-passthrough"}
        raise EffortRequestError("this oMLX model has no declared effort profile; its template levels are unknown")
    effective = profile.map(requested)
    if effective is None:
        raise EffortRequestError(f"effort {requested!r} is not supported by this model profile ({', '.join(profile.efforts)})")
    existing = kwargs.get("reasoning_effort")
    if existing is not None and existing != effective:
        raise EffortRequestError(f"request reasoning_effort {existing!r} conflicts with selected effort {requested!r} -> {effective!r}")
    kwargs["reasoning_effort"] = effective
    kwargs["enable_thinking"] = True
    adapted = dict(body)
    adapted["chat_template_kwargs"] = kwargs
    return adapted, {"requested": requested, "effective": effective,
                     "thinking": "enabled" if thinking_type in (None, "enabled", "adaptive") else thinking_type,
                     "result": "injected"}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, owner: "OmlxEffortAdapter"):
        self.owner = owner
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):
        return

    def do_POST(self):
        self.server.owner.handle(self)  # type: ignore[attr-defined]

    def do_GET(self):
        self.server.owner.handle_get(self)  # type: ignore[attr-defined]


class OmlxEffortAdapter:
    """A fixed-upstream, fixed-path forwarder. It is not a general HTTP proxy."""

    def __init__(self, upstream: str, routes: list[Route], receipt: Path, *, strict_unknown: bool = False):
        self.upstream = upstream.rstrip("/")
        self.routes: dict[str, Route] = {}
        for route in routes:
            previous = self.routes.get(route.wire_model)
            if previous is not None and omlx_profile(previous) != omlx_profile(route):
                raise ValueError(f"wire model {route.wire_model!r} has conflicting effort profiles in one launch")
            self.routes[route.wire_model] = route
        self.strict_unknown = strict_unknown
        self.receipt = receipt
        self._lock = threading.Lock()
        self._connections: set[http.client.HTTPConnection] = set()
        self._server = _Server(self)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="agent-on-effort-adapter")
        self._started = False

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> "OmlxEffortAdapter":
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        self._thread.start()
        self._started = True
        return self

    def close(self) -> None:
        with self._lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                if connection.sock is not None:
                    connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        if self._started:
            self._server.shutdown()
            self._thread.join(timeout=2)
        self._server.server_close()

    def records(self) -> list[dict]:
        try:
            lines = self.receipt.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def _record(self, path: str, metadata: dict) -> None:
        item = {"at": utc_now(), "path": path.partition("?")[0], "backend": "omlx", **metadata}
        raw = (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with self._lock:
            with open(self.receipt, "ab", buffering=0) as out:
                out.write(raw)

    def _error(self, handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
        payload = json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": message}}).encode()
        handler.send_response(status)
        handler.send_header("content-type", "application/json")
        handler.send_header("content-length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    def _connection(self):
        target = urlsplit(self.upstream)
        connection_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        return target, connection_cls(target.hostname, target.port, timeout=None)

    def _forward_response(self, handler: BaseHTTPRequestHandler, connection: http.client.HTTPConnection,
                          *, metadata: dict | None = None) -> None:
        response_started = False
        status = None
        try:
            response = connection.getresponse()
            status = response.status
            if metadata is not None:
                self._record(handler.path, {**metadata, "result": "accepted" if 200 <= status < 300 else "upstream-rejected",
                                            "upstream_status": status})
            handler.send_response(status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in _HOP_HEADERS:
                    handler.send_header(key, value)
            handler.send_header("connection", "close")
            handler.end_headers()
            response_started = True
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
            if metadata is not None:
                self._record(handler.path, {**metadata, "result": "completed", "upstream_status": status})
        except (OSError, http.client.HTTPException) as exc:
            event = {"result": "upstream-error", "reason": type(exc).__name__}
            if metadata is not None:
                event = {**metadata, **event, "upstream_status": status}
            self._record(handler.path, event)
            if not response_started:
                self._error(handler, 502, "agent-on effort adapter: upstream connection failed")

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        if handler.path.partition("?")[0] != "/v1/models":
            self._error(handler, 404, "route-pinned adapter only forwards the configured model catalog")
            return
        target, connection = self._connection()
        upstream_path = (target.path.rstrip("/") + handler.path) or "/"
        headers = {k: v for k, v in handler.headers.items() if k.lower() not in _HOP_HEADERS}
        with self._lock:
            self._connections.add(connection)
        try:
            try:
                connection.request("GET", upstream_path, headers=headers)
            except (OSError, http.client.HTTPException) as exc:
                self._record(handler.path, {"result": "upstream-error", "reason": type(exc).__name__})
                self._error(handler, 502, "agent-on effort adapter: upstream connection failed")
                return
            self._forward_response(handler, connection)
        finally:
            with self._lock:
                self._connections.discard(connection)
            connection.close()

    def handle(self, handler: BaseHTTPRequestHandler) -> None:
        path_only = handler.path.partition("?")[0]
        if path_only not in ("/v1/messages", "/v1/messages/count_tokens"):
            self._error(handler, 404, "route-pinned adapter only forwards Anthropic Messages endpoints")
            return
        try:
            length = int(handler.headers.get("content-length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > _BODY_LIMIT:
            self._error(handler, 413, "request body exceeds adapter limit")
            return
        raw = handler.rfile.read(length)
        try:
            body = json.loads(raw)
            model = body.get("model") if isinstance(body, dict) else None
            route = self.routes.get(model)
            if route is None:
                raise EffortRequestError(f"model {model!r} is not one of this launch's route-pinned models")
            body, metadata = adapt_omlx_body(body, omlx_profile(route), allow_unprofiled_passthrough=not self.strict_unknown)
            metadata["model"] = model
        except (ValueError, EffortRequestError) as exc:
            self._record(handler.path, {"result": "rejected", "reason": str(exc)})
            self._error(handler, 400, f"agent-on effort adapter: {exc}")
            return
        request_id = uuid.uuid4().hex[:16]
        metadata = {**metadata, "request_id": request_id, "mapping_result": metadata["result"]}
        self._record(handler.path, {**metadata, "result": "mapped"})
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        target, connection = self._connection()
        upstream_path = (target.path.rstrip("/") + handler.path) or "/"
        headers = {k: v for k, v in handler.headers.items() if k.lower() not in _HOP_HEADERS}
        headers["content-length"] = str(len(data))
        with self._lock:
            self._connections.add(connection)
        try:
            try:
                connection.request("POST", upstream_path, body=data, headers=headers)
            except (OSError, http.client.HTTPException) as exc:
                self._record(handler.path, {**metadata, "result": "upstream-error", "reason": type(exc).__name__,
                                            "upstream_status": None})
                self._error(handler, 502, "agent-on effort adapter: upstream connection failed")
                return
            self._record(handler.path, {**metadata, "result": "delivered"})
            self._forward_response(handler, connection, metadata=metadata)
        finally:
            with self._lock:
                self._connections.discard(connection)
            connection.close()
