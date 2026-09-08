"""`agent-on qualify <route>` (§7, §8, §9): the six fidelity gates on the direct wire, the throughput, concurrency,
caching and thinking probes, the harness baseline and the enforced input limit. Every result is recorded with the
fingerprint it was valid for. The six gates are the old verifier's, ported 1:1 (decisions-verifier-folded-into-qualify); here
they hit the source itself."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request

from .harness import run_launch
from .invariants import build_context, claude_code_version, evaluate
from .paths import Paths, describe_copy
from .schemas.observed import compute_context, empty_route
from .schemas.routes import load_routes
from .sources import probe_source
from .state import read_observed, resolve_secret, update_observed
from .util import utc_now

GATES = ("text_sse", "claude_system_block_instructions", "forced_structured_tool", "streaming_input_json_delta",
         "tool_result_continuation", "claude_adaptive_effort_policy")
WEATHER_TOOL = {"name": "get_weather", "description": "Get current weather for a city",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}
MAX_TOKENS = 128
RESPONSE_MAX_TOKENS = 512
MARKERS = ("SYSTEM_BLOCK_ALPHA", "SYSTEM_BLOCK_BETA")
THROUGHPUT_PROMPT = "Write a numbered list of 25 distinct English nouns, one per line, nothing else."
OVER_LIMIT_WORDS = ("long", "context", "maximum", "exceed", "too many", "limit")


class Wire:
    """One route's Anthropic endpoint. Both auth headers are sent when there is a key: OpenRouter honours either."""

    def __init__(self, base_url: str, model: str, key: str | None = None, timeout: float = 90.0):
        self.base = base_url.rstrip("/")
        self.model = model
        self.key = key
        self.timeout = timeout

    def _request(self, path: str, payload: dict) -> urllib.request.Request:
        headers = {"Content-Type": "application/json", "Accept": "application/json", "anthropic-version": "2023-06-01"}
        if self.key:
            headers["x-api-key"] = self.key
            headers["Authorization"] = f"Bearer {self.key}"
        return urllib.request.Request(self.base + path, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    def post(self, payload: dict) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self._request("/v1/messages", {"model": self.model, **payload}), timeout=self.timeout) as resp:
                body = json.loads(resp.read() or b"{}")
                return resp.status, body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            e.close()
            return e.code, body if isinstance(body, dict) else {}
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError):
            return 0, {}

    def stream(self, payload: dict) -> tuple[int, list[dict]]:
        try:
            with urllib.request.urlopen(self._request("/v1/messages", {"model": self.model, **payload, "stream": True}), timeout=self.timeout) as resp:
                events: list[dict] = []
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError:
                        return resp.status, [{"type": "invalid_sse_json"}]
                    if not isinstance(event, dict):
                        return resp.status, [{"type": "invalid_sse_json"}]
                    events.append(event)
                return resp.status, events
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, []
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError):
            return 0, []

    def count_tokens(self, payload: dict) -> int | None:
        try:
            with urllib.request.urlopen(self._request("/v1/messages/count_tokens", {"model": self.model, **payload}), timeout=self.timeout) as resp:
                body = json.loads(resp.read() or b"{}")
                n = body.get("input_tokens") if isinstance(body, dict) else None
                return int(n) if isinstance(n, int) else None
        except urllib.error.HTTPError as e:
            e.close()
            return None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError):
            return None


# ---- response readers (ported from the verifier) --------------------------------------------------------------

def _blocks(content, kind: str) -> list[dict]:
    return [b for b in (content or []) if isinstance(b, dict) and b.get("type") == kind]


def _text(content) -> str:
    return " ".join(b.get("text", "") for b in _blocks(content, "text"))


def _streamed_text(events: list[dict]) -> str:
    return "".join(e.get("delta", {}).get("text", "") for e in events
                   if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta")


def _stream_ok(events: list[dict]) -> bool:
    types = [e.get("type") for e in events if isinstance(e, dict)]
    return bool(types) and types[-1] == "message_stop" and "error" not in types and "invalid_sse_json" not in types


def _streamed_tool(events: list[dict]) -> tuple[dict | None, dict | None, bool]:
    starts = [e.get("content_block", {}) for e in events if e.get("type") == "content_block_start"]
    tool_starts = [b for b in starts if isinstance(b, dict) and b.get("type") == "tool_use"]
    fragments = [e.get("delta", {}).get("partial_json", "") for e in events
                 if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "input_json_delta"]
    fragments = [f for f in fragments if isinstance(f, str)]
    try:
        streamed = json.loads("".join(fragments)) if fragments else None
    except ValueError:
        streamed = None
    return (tool_starts[0] if tool_starts else None), streamed, bool(fragments)


def _valid_city(value) -> bool:
    return isinstance(value, dict) and isinstance(value.get("city"), str) and bool(value["city"].strip())


# ---- the six gates ------------------------------------------------------------------------------------------------

def run_gates(wire: Wire) -> dict:
    gates: dict[str, bool] = {}
    details: dict = {}

    status, events = wire.stream({"max_tokens": RESPONSE_MAX_TOKENS, "messages": [{"role": "user", "content": "Reply with one short sentence confirming this route is ready."}]})
    text = _streamed_text(events)
    gates["text_sse"] = status == 200 and _stream_ok(events) and bool(text.strip())
    details.update({"text_sse_status": status, "text_sse_chars": len(text)})

    status, events = wire.stream({"max_tokens": RESPONSE_MAX_TOKENS,
                                  "system": [{"type": "text", "text": "Include the marker SYSTEM_BLOCK_ALPHA in the final reply.", "cache_control": {"type": "ephemeral"}},
                                             {"type": "text", "text": "Also include the marker SYSTEM_BLOCK_BETA in the final reply."}],
                                  "messages": [{"role": "user", "content": "Apply both system instructions and reply with only their markers."}]})
    text = _streamed_text(events)
    gates["claude_system_block_instructions"] = status == 200 and _stream_ok(events) and all(m in text for m in MARKERS)
    details["claude_system_block_instructions_status"] = status

    tool_prompt = "Call get_weather exactly once for Seoul. Put the city in the structured city argument."
    forced = {"max_tokens": MAX_TOKENS, "tools": [WEATHER_TOOL], "tool_choice": {"type": "tool", "name": "get_weather"},
              "messages": [{"role": "user", "content": tool_prompt}]}
    status, resp = wire.post(forced)
    tool = _blocks(resp.get("content"), "tool_use")[0] if status == 200 and _blocks(resp.get("content"), "tool_use") else None
    tool_id = tool.get("id") if tool else None
    # F2: stop_reason is not checked — GLM-5.2 through OpenRouter's Anthropic wire returned a correct tool_use block
    # (id present, input == {"city": "Seoul"}) with stop_reason: "end_turn" twice in a row (measured 2026-09-08), and
    # Claude Code completed the tool-call loop on that route regardless. The gate judges the tool block, not the
    # stop reason; the raw value is still recorded so the observation is not lost.
    gates["forced_structured_tool"] = bool(status == 200 and tool and isinstance(tool_id, str) and tool_id.strip()
                                           and tool.get("name") == "get_weather" and _valid_city(tool.get("input")))
    details["forced_structured_tool_status"] = status
    details["forced_structured_tool_stop_reason"] = resp.get("stop_reason")   # raw value; may be None

    status, events = wire.stream(forced)
    start, streamed_input, saw_delta = _streamed_tool(events)
    sid = start.get("id") if start else None
    gates["streaming_input_json_delta"] = bool(status == 200 and _stream_ok(events) and start and isinstance(sid, str) and sid.strip()
                                               and start.get("name") == "get_weather" and saw_delta and _valid_city(streamed_input))
    details["streaming_input_json_delta_status"] = status

    cont_status, cont_text = 0, ""
    if tool and isinstance(tool_id, str) and tool_id.strip() and isinstance(resp.get("content"), list):
        cont_status, cont = wire.post({"max_tokens": RESPONSE_MAX_TOKENS, "tools": [WEATHER_TOOL], "messages": [
            {"role": "user", "content": tool_prompt},
            {"role": "assistant", "content": resp["content"]},                   # replay exactly what the model produced
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "18C and sunny"}]}]})
        cont_text = _text(cont.get("content"))
    gates["tool_result_continuation"] = cont_status == 200 and bool(cont_text.strip())
    details["tool_result_continuation_status"] = cont_status

    status, resp = wire.post({"max_tokens": RESPONSE_MAX_TOKENS, "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"},
                              "messages": [{"role": "user", "content": "Think briefly as the selected provider normally would, then reply exactly OK."}]})
    text = _text(resp.get("content"))
    gates["claude_adaptive_effort_policy"] = status == 200 and bool(text.strip())
    details["claude_adaptive_effort_policy_status"] = status
    thinking = _blocks(resp.get("content"), "thinking")
    completed = status == 200 and resp.get("stop_reason") == "end_turn" and bool(text.strip())

    seen = bool(thinking) if status == 200 else None                              # the request never ran: unmeasured, not "off"
    # F-fix 2: tokens_on_probe is a measurement, never a chars // 4 estimate. Preferred: OpenRouter (and some other
    # sources) report usage.output_tokens_details.thinking_tokens. Fallback: the whole reply's output_tokens, which
    # then also counts the probe's short "OK" answer — still a real number, never an estimate. None when the probe
    # never returned 200, or returned no thinking block to measure.
    thinking_detail = ((resp.get("usage") or {}).get("output_tokens_details") or {}).get("thinking_tokens")
    if status != 200 or not thinking:
        tokens_on_probe = None
    elif isinstance(thinking_detail, int):
        tokens_on_probe = thinking_detail
    else:
        tokens_on_probe = (resp.get("usage") or {}).get("output_tokens")
    return {"gates": gates, "details": details, "thinking_block_seen": seen, "completed": completed,
            "thinking_tokens": tokens_on_probe, "all_pass": all(gates.values())}


# ---- probes ---------------------------------------------------------------------------------------------------------

def _timed(wire: Wire) -> tuple[float, dict]:
    t = time.monotonic()
    status, resp = wire.post({"max_tokens": 120, "messages": [{"role": "user", "content": THROUGHPUT_PROMPT}]})
    return time.monotonic() - t, (resp if status == 200 else {})


def probe_throughput(wire: Wire) -> dict:
    """Output tokens per second at short context, one request."""
    seconds, resp = _timed(wire)
    out = int((resp.get("usage") or {}).get("output_tokens") or 0)
    return {"tok_s": (out / seconds) if out and seconds > 0 else None, "output_tokens": out or None, "seconds": round(seconds, 3)}


def probe_concurrency(wire: Wire) -> dict:
    """Two in flight against one: a pair under 1.5× the single request's time means the engine batched them."""
    serial, resp = _timed(wire)
    if not resp:
        return {"concurrency": None, "serial_s": round(serial, 3), "pair_s": None, "ratio": None}
    results: list[float] = []
    lock = threading.Lock()

    def one():
        s, _ = _timed(wire)
        with lock:
            results.append(s)

    t = time.monotonic()
    threads = [threading.Thread(target=one) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    pair = time.monotonic() - t
    ratio = pair / serial if serial > 0 else None
    return {"concurrency": (2 if ratio is not None and ratio < 1.5 else 1), "serial_s": round(serial, 3), "pair_s": round(pair, 3), "ratio": round(ratio, 3) if ratio else None}


def probe_caching(wire: Wire) -> dict:
    """A cacheable system prefix (~6,500 tokens) sent twice; caching is true when the second reply reports cache reads.
    The prefix is large on purpose: oMLX caches in 4,096-token blocks (measured 2026-09-08 — a 1,770-token prefix is
    never reported cached, a 4,618-token one reads back 4,096), and Anthropic-style providers need ≥ 1,024."""
    prefix = ("This system prompt exists only to be long enough to be cached by the provider. " * 400).strip()
    payload = {"max_tokens": 8, "system": [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}],
               "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}
    first_status, _ = wire.post(payload)
    status, resp = wire.post(payload)
    if first_status != 200:
        status = first_status
    read = int((resp.get("usage") or {}).get("cache_read_input_tokens") or 0)
    if status != 200:
        return {"caching": "unknown", "cache_read_second": None, "status": status}   # the probe did not run: not a measurement
    return {"caching": read > 0, "cache_read_second": read, "status": status}


def _over_limit(status: int, body: dict) -> bool:
    if status in (413, 400, 422):
        msg = json.dumps(body).lower()
        return any(w in msg for w in OVER_LIMIT_WORDS)
    return False


def probe_limits(wire: Wire, lo: int, hi: int, *, count_tokens: bool = True, max_probes: int = 10) -> dict:
    """Bisect the largest input the source accepts between lo and hi with max_tokens: 1 requests. hi is tried first
    (accepted → verified = hi); lo is then verified and halved until accepted; then the boundary is bisected to within
    1% or max_probes. Returns the largest accepted size as `verified`, or None when a refusal is not a limit error."""
    word = "lorem "
    calib = 1.0
    if count_tokens:
        n = wire.count_tokens({"messages": [{"role": "user", "content": word * 1000}]})
        if n:
            calib = 1000 / n                                                        # words per token

    counted: dict[int, int] = {}                                                 # requested size → counted size

    def attempt(tokens: int) -> tuple[int, dict]:
        payload = {"max_tokens": 1, "messages": [{"role": "user", "content": (word * int(tokens * calib)).strip()}]}
        if count_tokens:
            n = wire.count_tokens(payload)
            if n:
                counted[tokens] = n
        return wire.post(payload)

    def verified_size(accepted: int) -> int:
        return counted.get(accepted, accepted)                                  # the counted size when the source counts

    probes: list[dict] = []
    status, body = attempt(hi)
    probes.append({"tokens": hi, "status": status, "counted": counted.get(hi)})
    if status == 200:                                                              # nothing refused: no boundary was measured
        return {"verified": None, "accepted_up_to": verified_size(hi), "basis": "count_tokens" if hi in counted else "estimate", "probes": probes}
    if not _over_limit(status, body):
        return {"verified": None, "basis": None, "probes": probes}
    accepted, refused = lo, hi
    status, body = attempt(accepted)                                             # lo is verified, never assumed
    probes.append({"tokens": accepted, "status": status, "counted": counted.get(accepted)})
    while status != 200 and _over_limit(status, body) and accepted > 64:
        refused, accepted = accepted, accepted // 2
        status, body = attempt(accepted)
        probes.append({"tokens": accepted, "status": status, "counted": counted.get(accepted)})
    if status != 200:
        return {"verified": None, "basis": None, "probes": probes}
    while len(probes) < max_probes and refused - accepted > max(1, refused // 100):
        mid = (accepted + refused) // 2
        status, body = attempt(mid)
        probes.append({"tokens": mid, "status": status, "counted": counted.get(mid)})
        if status == 200:
            accepted = mid
        elif _over_limit(status, body):
            refused = mid
        else:
            return {"verified": None, "basis": None, "probes": probes}
    basis = "count_tokens" if accepted in counted else "estimate"
    return {"verified": verified_size(accepted) if basis == "count_tokens" else None, "accepted_up_to": verified_size(accepted), "basis": basis, "probes": probes}


# ---- the command (§9 qualify row) ----------------------------------------------------------------------------

BASELINE_PROMPT = "Reply with exactly: OK"
BASELINE_TOKENS_ESTIMATE = 50_000


def _estimate_paid_usd(price: dict | None, tokens: int) -> float | None:
    if not price or price.get("input") is None:
        return None
    return round(tokens * float(price["input"]) / 1_000_000, 4)


def run_qualify(paths: Paths, name: str, *, baseline: bool = False, limits: bool = False, allow_paid: bool = False,
                env: dict | None = None, timeout: float = 90.0, claude_bin: str | None = None) -> dict:
    parent = dict(os.environ if env is None else env)
    table = load_routes(paths)
    route = table.resolve(name)
    source = table.sources[route.source]
    paid = source.auth_env is not None
    price = route.price.per_mtok() if route.price else None
    doc: dict = {"command": "qualify", "copy": describe_copy(paths), "route": route.name, "refused": None, "gates": {}, "details": {},
                 "probes": {}, "baseline": None, "fingerprint": None, "written": False, "invariants": []}
    if paid and (baseline or limits) and not allow_paid:
        lim = table.effective_limits(route)
        est = _estimate_paid_usd(price, (BASELINE_TOKENS_ESTIMATE if baseline else 0) + (2 * (lim.input or 0) if limits and lim else 0))
        doc["refused"] = (f"{route.source} bills per token: --baseline runs Claude Code (~{BASELINE_TOKENS_ESTIMATE} input tokens) and --limits "
                          f"sends up to ~2× the input limit; estimated ${est if est is not None else '?'} — re-run with --allow-paid")
        return doc
    key = resolve_secret(paths, source.auth_env, parent) if source.auth_env else None
    wire = Wire(source.base_url, route.wire_model, key, timeout)
    probe = probe_source(source, timeout=5)
    gates = run_gates(wire)
    thr = probe_throughput(wire)
    conc = probe_concurrency(wire)
    cache = probe_caching(wire)
    now = utc_now()
    fp = {"effective_route_sha": table.effective_sha(route), "wire_model": route.wire_model,
          "source_identity": probe.identity if probe.reachable else None, "claude_code": claude_code_version(claude_bin)}
    qual = {"pass": gates["all_pass"], "gates": gates["gates"], "thinking_block_seen": gates["thinking_block_seen"],
            "completed": gates["completed"], "at": now, "fingerprint": fp}
    base_tokens = None
    if baseline:
        launch = run_launch(paths, route.name, ["-p", BASELINE_PROMPT], env=parent, claude_bin=claude_bin, announce=False)
        first = (launch.get("last_session") or {}).get("first_request")
        # a transcript whose only turn was a synthetic API-error line has no first_request (or one with 0 total):
        # never record that as a measured baseline of 0 (final-fix item 1).
        base_tokens = first["input_tokens_total"] if first and first.get("input_tokens_total") else None
    lim_result = None
    if limits:
        obs_route = read_observed(paths)["routes"].get(route.name) or {}
        tier = (obs_route.get("limits") or {}).get("input") or {}
        declared = (table.effective_limits(route).input if table.effective_limits(route) else None)
        cands = [v for v in (declared, tier.get("configured"), tier.get("advertised")) if v]
        lo = max(1024, min(cands) // 2) if cands else 1024
        hi = int(max(cands) * 1.1) if cands else 262144
        lim_result = probe_limits(wire, lo, hi, count_tokens=True)
    doc.update({"gates": gates["gates"], "details": gates["details"], "fingerprint": fp, "baseline": base_tokens,
                "probes": {"throughput": thr, "concurrency": conc, "caching": cache, "limits": lim_result}})

    def mutate(d: dict) -> None:
        r = d["routes"].setdefault(route.name, empty_route())
        r["last_qualification"] = qual
        cm = r["cost_model"]
        cm.update({"tok_s": thr["tok_s"], "concurrency": conc["concurrency"], "caching": cache["caching"],
                   "thinking": {"observed": gates["thinking_block_seen"], "tokens_on_probe": gates["thinking_tokens"]}, "checked": now})
        if baseline:
            cm["harness_baseline_tokens"] = {"value": base_tokens, "measured_by": "qualify --baseline", "claude_code": fp["claude_code"], "at": now}
        if lim_result and lim_result["verified"] is not None:
            r["limits"]["input"]["verified"] = lim_result["verified"]
            r["limits"]["input"]["checked"] = now
        lim = table.effective_limits(route)
        ctx, basis = compute_context(lim.input if lim else None, r["limits"]["input"])
        cm.update({"context": ctx, "context_basis": basis})

    update_observed(paths, mutate)
    doc["written"] = True
    doc["knowledge"] = None
    if paths.knowledge_dir.is_dir():                                               # §10: qualify writes L5 when it exists
        from .knowledge import append
        q = append(paths, "qualifications", {"route": route.name, "fingerprint": fp, "gates": gates["gates"],
                                             "thinking_block_seen": gates["thinking_block_seen"], "completed": gates["completed"],
                                             "tok_s": thr["tok_s"], "concurrency": conc["concurrency"], "caching": cache["caching"],
                                             "commit": doc["copy"]["commit"]}, now=now)
        o = append(paths, "observations", {"route": route.name, "kind": "throughput",
                                           "values": {"tok_s": thr["tok_s"], "concurrency": conc["concurrency"], "caching": cache["caching"],
                                                      "thinking_observed": gates["thinking_block_seen"]},
                                           "evidence": f"qualify {q['id']}", "session": None}, now=now)
        doc["knowledge"] = {"qualification": q["id"], "observation": o["id"]}
    doc["invariants"] = [r.as_dict() for r in evaluate(build_context(paths, with_claude_code=True, claude_bin=claude_bin), ids=["route.served", "qualification.current"], route=route.name)]
    return doc
