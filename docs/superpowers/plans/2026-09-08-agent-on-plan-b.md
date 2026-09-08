# agent-on Plan B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Claude Code binding (L6): `claude-on <route>` launches Claude Code directly on a route with the source key never in the child environment, reads the session back into the cost ledger, and `agent-on qualify` measures each route's fidelity, throughput, concurrency, caching, thinking, harness baseline and enforced input limit — purely additive, beside the still-working `claude-litellm`.

**Architecture:** `agent_on/harness.py` is the one harness-specific file (the tower L0–L5 landed in Plan A never learns which harness asks). It computes the child environment from the route, prepares an isolated `CLAUDE_CONFIG_DIR` that shares the user's settings/plugins/skills by symlink, writes the per-launch `run/<launch-id>/` (key 0600 + `apiKeyHelper` settings file), spawns `claude` with signals forwarded, and after exit reads the transcript into `last_session` and the per-session run ledger through Plan A's `cost.py`. `agent_on/qualify.py` speaks the Anthropic wire directly with the stdlib and writes `last_qualification`, `cost_model` and `verified` limits with the §8 fingerprint. `agent_on/mock_source.py` grows a deterministic `/v1/messages` so every probe has an offline test; a fake `claude` binary gives the launcher an offline test of the credential contract.

**Tech Stack:** Python ≥ 3.11 stdlib (`subprocess`, `signal`, `http.server`, `urllib`, `json`, `os`), two ≤20-line zsh shims. Claude Code 2.1.263 on this machine (`claude` on PATH).

**Spec:** `docs/superpowers/specs/2026-09-07-agent-on-design.md` (rev 8): §9 launch row and session rules, §11 (all five items — the credential flow is D2 ⟲⟲), §12 cost line, §7 qualify rows and fingerprint, §7.1 `run/<launch-id>/`, §14 row **B** (verify column is the acceptance), S2. Plan A landed on `main` at `8610a33`; this plan builds on that code as merged, not on Plan A's document.

## Global Constraints

- **Additive only.** No existing file under `bin/`, `config/`, `scripts/`, `tests/test_*.py`, or `docs/*.md` is modified or deleted. Files this plan *modifies* in the landed package: `agent_on/paths.py`, `agent_on/cli.py`, `agent_on/mock_source.py`, `agent_on/invariants.py`, `agent_on/schemas/observed.py`, `agent_on/schemas/errors.py`, `agent_on/status.py`, `.github/workflows/ci.yml` (one assertion), `tests/agent_on/{test_paths,test_invariants,test_status,test_gate}.py` (assertions that assumed Plan A's honest skip), `README.md` (append) — each named in its task. `routes.toml` is not edited. `claude-litellm` must still launch after every task.
- **Standard library only**; Python ≥ 3.11; run the suite with `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`.
- **D2 ⟲⟲ credential flow (§11):** the launcher resolves the key in the *parent* (environment wins over `$STATE/env`), writes it to `$STATE/run/<launch-id>/key` mode 0600, hands Claude Code a per-launch `--settings` file whose `apiKeyHelper` is `cat <that file>`, and scrubs **every** source's `auth_env` plus the routing denylist from the child environment. `ANTHROPIC_AUTH_TOKEN` is never the source key; a keyless source gets the fixed placeholder `agent-on`. The run directory is removed when the child exits; every launch first sweeps `run/*` whose recorded pid is dead.
- **D7:** all four tier slots and the subagent slot are bound to the launch route's `wire_model`; `--sonnet`/`--haiku` may override one slot with a route on the same source. **D8:** discovery only with `--discover`. **D6:** liveness and qualification are shown, never gate a launch. **D12:** no `thinking:` field anywhere; `qualify` reports what the template did.
- **Session rules (§9):** the launcher passes `--session-id <uuid4>` unless the user passed `--session-id` (theirs is used), `--resume`/`--continue` (the resumed file is read after exit), or `--no-session-persistence` (`last_session = {"skipped": "no-session-persistence"}`). Read-back is best-effort and never a reason to refuse arguments; `--model`, `--settings`, `--fallback-model` pass through (a user `--settings` is merged after the helper file).
- **§11 item 4 read-back:** `first_request` (raw first assistant usage + `input_tokens_total`), `this_run` (the ledger line from `cost.attribute_run` with the price snapshot taken at spawn), `session_total` (`cost.fold_session` over the whole transcript and every ledger line for the session); `total_cost_usd`/`costUSD` are never read (F11). Verified transcript fields only: per-line `timestamp`, `message.model`, `message.usage.{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens}`, top-level `version`, `effort`, `permissionMode` (recorded when present).
- **§7 qualify:** `verified` limits are written only by `qualify --limits`; `harness_baseline_tokens` only by `qualify --baseline` with the fixed prompt `Reply with exactly: OK`; `caching` becomes `true`/`false` only from the two-turn probe; the fingerprint is `{effective_route_sha, wire_model, source_identity, claude_code}`. A paid probe (`--limits` on a keyed source) is refused without `--allow-paid` and prints its estimated cost first.
- **State root**: `AGENT_ON_STATE`, else `$XDG_STATE_HOME/agent-on`, else `~/.local/state/agent-on`. Storage rules of §7.1 (locks, temp+rename, O_APPEND ledgers) are Plan A's `state.py` and are reused, never re-implemented.
- **Do not restart or stop oMLX on :8000**; the old proxy on :4000 is stopped and stays stopped (owner's decision 2026-09-08). Real launches in tests are forbidden: unit tests use the fake `claude` and the mock source; only Task 10 (acceptance) runs the real binary, against oMLX (free) first and OpenRouter (cents) second.
- **Commit style**: `<type>(agent-on): <imperative summary>`; one commit per task; end each message with the attribution trailer shown in Task 1.
- **Test discipline**: tests in `tests/agent_on/` (no `__init__.py`), the sys.path preamble, `helpers.Sandbox`; no route-name literal a test uses may be absent from `routes.toml` (the tree lint) — tests use the mock source names `mock`/`paid` and the fake-claude harness.

---

## File structure

| path | responsibility |
|---|---|
| `agent_on/ids.py` | `ulid()` — launch ids (26-char Crockford base32, time-ordered) |
| `agent_on/paths.py` (modify) | `run_dir`, `claude_config_dir`, `project_slug`, `transcript_path` |
| `agent_on/mock_source.py` (modify) | deterministic Anthropic `/v1/messages` (JSON + SSE) and `/v1/messages/count_tokens`; auth check; caching, delay, serialisation and context-limit knobs |
| `agent_on/harness.py` | L6: child env, scrub, config-dir farm + trust, run dir + sweep, session args, cost line, spawn with signal forwarding, transcript read-back, `run_launch` |
| `agent_on/qualify.py` | the six gates + throughput/concurrency/caching/thinking probes, `--baseline`, `--limits`, fingerprint, `run_qualify` |
| `agent_on/invariants.py` (modify) | `credential.not_in_child_env` becomes a real predicate over `harness.child_env` |
| `agent_on/schemas/observed.py` (modify) | `last_qualification` shape; `QUALIFICATION_KEYS` |
| `agent_on/schemas/errors.py` (modify) | one rule: `observed.qualification.shape` |
| `agent_on/status.py` (modify) | the §12 cost line and `last_session` in the text view |
| `agent_on/cli.py` (modify) | `launch` and `qualify` verbs; renderers; exit codes |
| `bin/claude-on` | `exec agent-on launch --harness claude "$@"` |
| `tests/agent_on/fakeclaude.py` | a stand-in `claude`: dumps its env, runs the apiKeyHelper, writes a transcript, honours `--session-id/--resume/--continue/--no-session-persistence`, exits with `FAKE_CLAUDE_EXIT` |
| `tests/agent_on/test_ids.py`, `test_mock_messages.py`, `test_harness_env.py`, `test_harness_launch.py`, `test_qualify.py`, `test_cli_launch.py` | one file per unit |
| `README.md` (append) | the launch section |

Public interfaces every later task relies on (exact names):

```python
# agent_on.ids
ulid(now_ms: int | None = None, rand: bytes | None = None) -> str            # 26 chars, sorts by time
# agent_on.paths (additions)
Paths.run_dir -> Path ; Paths.claude_config_dir -> Path ; project_slug(cwd: str) -> str ; Paths.transcript_path(session_id: str, cwd: str) -> Path
# agent_on.mock_source (additions)
MockSource(catalog=None, spend=None, expect_key=None, *, caching=True, delay_s=0.0, serialize=False, max_context=None, fail_gates=())
   .messages: list[dict]   # every /v1/messages request body, in order
# agent_on.harness
SCRUB_ENV: tuple[str, ...] ; SHARED_ITEMS: tuple[str, ...] ; TIERS = ("FABLE", "OPUS", "SONNET", "HAIKU") ; PLACEHOLDER_TOKEN = "agent-on"
child_env(parent: dict, table: RouteTable, route: Route, *, context: int | None, config_dir: Path, discover=False, sonnet: Route | None = None, haiku: Route | None = None) -> dict
prepare_config_dir(paths: Paths, cwd: str) -> Path
sweep_run_dirs(paths: Paths) -> list[str]
write_run_dir(paths: Paths, launch_id: str, *, key: str | None, launch: dict) -> tuple[Path, Path | None]   # (run_dir, helper settings path or None)
session_args(claude_args: list[str]) -> tuple[list[str], str | None, str]   # (args with --session-id injected when needed, session_id or None, mode: "fresh" | "user-session-id" | "resume" | "continue" | "no-persistence")
cost_line(route_name: str, observed_route: dict | None) -> str
read_transcript(path: Path) -> dict   # {"turns": [{"timestamp","model","usage"}], "first_request": {...} | None, "version", "effort", "permission_mode", "session_id"}
record_session(paths: Paths, launch: dict, *, ended: str, transcript: Path | None, mode: str) -> dict   # the last_session record (full or {"skipped"})
run_launch(paths: Paths, name: str, claude_args: list[str], *, harness="claude", discover=False, sonnet=None, haiku=None, dry_run=False, env=None, claude_bin=None, cwd=None, probe_timeout=2.0, announce=True) -> dict
# agent_on.qualify
GATES: tuple[str, ...] ; Wire(base_url: str, model: str, key: str | None, timeout: float) ; run_gates(wire) -> dict ; probe_throughput(wire) -> dict ; probe_concurrency(wire) -> dict ; probe_caching(wire) -> dict ; probe_limits(wire, lo: int, hi: int, *, count_tokens: bool) -> dict
run_qualify(paths: Paths, name: str, *, baseline=False, limits=False, allow_paid=False, env=None, timeout=90.0, claude_bin=None) -> dict
```

---
### Task 1: Launch ids and the paths the launcher needs

**Files:**
- Create: `agent_on/ids.py`
- Modify: `agent_on/paths.py` (add `project_slug`, `run_dir`, `claude_config_dir`, `transcript_path`; `ensure_state` also creates `run/`)
- Test: `tests/agent_on/test_ids.py`; extend `tests/agent_on/test_paths.py`

**Interfaces:**
- Produces: `ids.ulid(now_ms=None, rand=None) -> str`; `paths.project_slug(cwd) -> str`; `Paths.run_dir`, `Paths.claude_config_dir`, `Paths.transcript_path(session_id, cwd)`.

Why a slug function: Claude Code stores a session's transcript at `<config dir>/projects/<slug>/<session-id>.jsonl`, where the slug is the working directory with every character that is not a letter or digit replaced by `-` (observed on this machine: `/Users/rick/.openclaw` → `-Users-rick--openclaw`, `/Users/rick/Projects/claude-litellm` → `-Users-rick-Projects-claude-litellm`).

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_ids.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.ids import ulid  # noqa: E402

ALPHABET = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


class UlidTest(unittest.TestCase):
    def test_shape(self):
        u = ulid()
        self.assertEqual(len(u), 26)
        self.assertTrue(set(u) <= ALPHABET)

    def test_sorts_by_time_and_is_deterministic_for_fixed_inputs(self):
        a = ulid(now_ms=1_000, rand=bytes(10))
        b = ulid(now_ms=2_000, rand=bytes(10))
        self.assertLess(a, b)
        self.assertEqual(a, ulid(now_ms=1_000, rand=bytes(10)))
        self.assertEqual(ulid(now_ms=0, rand=bytes(10)), "0" * 26)

    def test_unique_in_a_burst(self):
        self.assertEqual(len({ulid() for _ in range(2000)}), 2000)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            ulid(now_ms=-1)
        with self.assertRaises(ValueError):
            ulid(rand=b"short")


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/agent_on/test_paths.py` (inside `PathsTest`, before `if __name__`):

```python
    def test_launch_paths_and_project_slug(self):
        from agent_on.paths import project_slug
        p = Paths(checkout=Path("/co"), state=Path("/s"), home=Path("/h"))
        self.assertEqual(p.run_dir, Path("/s/run"))
        self.assertEqual(p.claude_config_dir, Path("/s/claude-config"))
        self.assertEqual(project_slug("/Users/rick/.openclaw"), "-Users-rick--openclaw")
        self.assertEqual(project_slug("/Users/rick/Projects/claude-litellm"), "-Users-rick-Projects-claude-litellm")
        self.assertEqual(p.transcript_path("abc-123", "/Users/rick/x y"), Path("/s/claude-config/projects/-Users-rick-x-y/abc-123.jsonl"))

    def test_ensure_state_creates_the_run_dir(self):
        import tempfile, stat
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(checkout=Path(tmp), state=Path(tmp) / "st", home=Path(tmp))
            ensure_state(p)
            self.assertTrue(p.run_dir.is_dir())
            self.assertEqual(stat.S_IMODE(p.run_dir.stat().st_mode), 0o700)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_ids.py' -v; python3 -m unittest discover -s tests/agent_on -p 'test_paths.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.ids'`; `AttributeError: 'Paths' object has no attribute 'run_dir'`.

- [ ] **Step 3: Write the code**

`agent_on/ids.py`:

```python
"""Launch ids (§7.1): ULIDs from the standard library — 48-bit millisecond time + 80 random bits, 26 Crockford
base32 characters, lexically sortable by time. The launcher mints one per launch before spawning."""
from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms: int | None = None, rand: bytes | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    rb = os.urandom(10) if rand is None else rand
    if ms < 0 or ms >= (1 << 48) or len(rb) != 10:
        raise ValueError("ulid: time must fit 48 bits and rand must be 10 bytes")
    value = (ms << 80) | int.from_bytes(rb, "big")
    out = []
    for _ in range(26):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))
```

`agent_on/paths.py` — add `import re` at the top, then:

```python
def project_slug(cwd: str) -> str:
    """Claude Code names a project's transcript directory by its cwd with every non-alphanumeric character
    replaced by '-' (observed on 2.1.263: /Users/rick/.openclaw → -Users-rick--openclaw)."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)
```

and inside `class Paths` (after `shim`):

```python
    @property
    def run_dir(self) -> Path:
        return self.state / "run"                       # §7.1: run/<launch-id>/ — per-launch key, helper settings, launch record

    @property
    def claude_config_dir(self) -> Path:
        return self.state / "claude-config"             # §11 item 1: the isolated CLAUDE_CONFIG_DIR

    def transcript_path(self, session_id: str, cwd: str) -> Path:
        return self.claude_config_dir / "projects" / project_slug(cwd) / f"{session_id}.jsonl"
```

and in `ensure_state` change the tuple to `(paths.state, paths.observed_lock.parent, paths.sessions_dir, paths.run_dir)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: 99 + 6 = 105 tests OK.

- [ ] **Step 5: Commit**

```bash
git add agent_on/ids.py agent_on/paths.py tests/agent_on/test_ids.py tests/agent_on/test_paths.py
git commit -m "feat(agent-on): launch ids and the launcher's paths (run/, claude-config/, transcript slug)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 2: A deterministic Anthropic `/v1/messages` in the mock source

**Files:**
- Modify: `agent_on/mock_source.py`
- Test: `tests/agent_on/test_mock_messages.py`

**Interfaces:**
- Produces: `MockSource(catalog=None, spend=None, expect_key=None, *, caching=True, delay_s=0.0, serialize=False, max_context=None, fail_gates=())` — existing behaviour unchanged; new: `POST /v1/messages` and `/api/v1/messages` (JSON, or SSE when `"stream": true`), `POST /v1/messages/count_tokens`, `.messages` (every request body), 401 on a wrong `x-api-key`/`Authorization` when `expect_key` is set. Behaviour of the model: a forced tool → one `tool_use` block `toolu_mock_1` with `{"city": "Seoul"}` and `stop_reason: tool_use`; a `tool_result` in the last user turn → text `It is 18C and sunny in Seoul.`; system text containing `SYSTEM_BLOCK_ALPHA`/`SYSTEM_BLOCK_BETA` → a text block naming the markers found; a `thinking` field → a leading `thinking` block; else `OK — the mock route is ready.` Usage: `input_tokens` ≈ len(json)/4, `output_tokens` 12, `cache_read_input_tokens` = the system text's estimate on the second request with the same system text when `caching`; `max_context` → HTTP 400 `prompt is too long` above it; `delay_s` per request, held under one lock when `serialize` (two concurrent requests then take twice as long); `fail_gates` names which gate to break: `text_sse`, `claude_system_block_instructions`, `forced_structured_tool`, `streaming_input_json_delta`, `tool_result_continuation`, `claude_adaptive_effort_policy`, `thinking`.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_mock_messages.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_mock_messages.py' -v`
Expected: `TypeError: MockSource.__init__() got an unexpected keyword argument 'caching'` / 404s.

- [ ] **Step 3: Extend the mock**

Replace `agent_on/mock_source.py` with:

```python
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
                 fail_gates: tuple[str, ...] = ()):
        bad = set(fail_gates) - set(GATE_NAMES)
        if bad:
            raise ValueError(f"unknown fail_gates {sorted(bad)}")
        self.catalog = list(catalog or [])
        self.spend = spend
        self.expect_key = expect_key
        self.caching, self.delay_s, self.serialize, self.max_context, self.fail_gates = caching, delay_s, serialize, max_context, tuple(fail_gates)
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
            stop = "tool_use"
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: all pass (Plan A's mock-based tests are unaffected: the GET surface is unchanged).

- [ ] **Step 5: Commit**

```bash
git add agent_on/mock_source.py tests/agent_on/test_mock_messages.py
git commit -m "feat(agent-on): mock source speaks a deterministic Anthropic /v1/messages (JSON + SSE) and count_tokens

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---
### Task 3: The harness binding, pure parts — child env, config dir, run dir, session args, cost line, transcript

**Files:**
- Create: `agent_on/harness.py` (the pure functions; `spawn`/`run_launch` are Task 4 and are appended to the same file)
- Test: `tests/agent_on/test_harness_env.py`

**Interfaces:**
- Consumes: `paths.{Paths, ensure_state, project_slug}`, `schemas.routes.{Route, RouteTable}`, `schemas.observed.{USAGE_FIELDS, empty_route}`, `state.{locked, append_session_run, read_session_runs, update_observed}`, `cost.{attribute_run, fold_session, zero_usage}`, `util.{utc_now, parse_utc}`.
- Produces: `SCRUB_ENV`, `PASS_THROUGH`, `SHARED_ITEMS`, `TIERS`, `PLACEHOLDER_TOKEN`, `DISCOVERY_ENV`, `FREE`, `child_env(...)`, `prepare_config_dir(paths, cwd)`, `sweep_run_dirs(paths)`, `write_run_dir(paths, launch_id, *, key, launch)`, `session_args(claude_args)`, `cost_line(route_name, observed_route)`, `read_transcript(path)`, `record_session(paths, launch, *, ended, transcript, mode)`, `find_transcript(paths, session_id, cwd, mode, started)`.

Rulings recorded here (the spec leaves them open): (1) `ANTHROPIC_API_KEY` is *removed* for a keyed source rather than set to `""` — the scrub already guarantees no inherited key reaches the child, and the `apiKeyHelper` is consulted only when no key variable is present; (2) an assistant API response is written by Claude Code as one transcript line per content block with the same `message.id` and identical `usage`, so turns are de-duplicated by `message.id` (last line wins) — counting lines would double-bill; (3) the subagent slot is bound to the launch route (D7), `--sonnet`/`--haiku` override only their own tier slot.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_harness_env.py`:

```python
from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402
from agent_on.state import read_observed, read_session_runs  # noqa: E402

BASE = "http://127.0.0.1:1"


def table(sb):
    return load_routes(sb.paths)


class ChildEnvTest(unittest.TestCase):
    def test_keyed_source_scrubs_every_secret_and_sets_no_key_variable(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            t = table(sb)
            parent = {"PATH": "/usr/bin", "HOME": "/h", "MOCK_PAID_KEY": "sk-paid", "ANTHROPIC_API_KEY": "sk-ant", "ANTHROPIC_MODEL": "x",
                      "OPENROUTER_API_KEY": "sk-or", "HTTPS_PROXY": "keep-me", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
                      "CLAUDE_CODE_SESSION_ID": "parent-session", "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_MESSAGING_TOKEN": "t", "CLAUDE_EFFORT": "high", "CLAUDE_PID": "1"}
            env = harness.child_env(parent, t, t.routes["paid/vendor/model-x"], context=100000, config_dir=Path("/cfg"))
            for k in ("MOCK_PAID_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL", "OPENROUTER_API_KEY",
                      "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_EFFORT", "CLAUDE_PID"):
                self.assertNotIn(k, env, k)
            self.assertEqual(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "4096")                # the operator's output cap passes (D12)
            self.assertNotIn("sk-paid", json.dumps(env))
            self.assertEqual(env["PATH"], "/usr/bin")
            self.assertEqual(env["HTTPS_PROXY"], "keep-me")                        # not a routing variable: kept
            self.assertEqual(env["ANTHROPIC_BASE_URL"], BASE)
            for tier in harness.TIERS:
                self.assertEqual(env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"], "vendor/model-x")
            self.assertEqual(env["CLAUDE_CODE_SUBAGENT_MODEL"], "vendor/model-x")
            self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "100000")
            self.assertEqual(env["CLAUDE_CODE_ATTRIBUTION_HEADER"], "0")
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/cfg")
            self.assertNotIn(harness.DISCOVERY_ENV, env)

    def test_keyless_source_gets_the_placeholder_token_and_discover_is_opt_in(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            t = table(sb)
            env = harness.child_env({}, t, t.routes["mock/alpha"], context=None, config_dir=Path("/cfg"), discover=True)
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], harness.PLACEHOLDER_TOKEN)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("CLAUDE_CODE_MAX_CONTEXT_TOKENS", env)
            self.assertEqual(env[harness.DISCOVERY_ENV], "1")

    def test_tier_overrides_must_stay_on_the_same_source(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            t = table(sb)
            env = harness.child_env({}, t, t.routes["mock/alpha"], context=None, config_dir=Path("/c"), haiku=t.routes["mock/gone"])
            self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gone")
            self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "alpha")
            self.assertEqual(env["CLAUDE_CODE_SUBAGENT_MODEL"], "alpha")
            with self.assertRaises(ValueError):
                harness.child_env({}, t, t.routes["mock/alpha"], context=None, config_dir=Path("/c"), sonnet=t.routes["paid/vendor/model-x"])


class ConfigDirTest(unittest.TestCase):
    def test_shared_items_are_symlinked_and_the_project_is_trusted(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            native = sb.paths.home / ".claude"
            native.mkdir()
            (native / "settings.json").write_text("{}")
            cfg = harness.prepare_config_dir(sb.paths, "/work/dir")
            self.assertEqual(cfg, sb.paths.claude_config_dir)
            for item in harness.SHARED_ITEMS:
                self.assertTrue((cfg / item).is_symlink(), item)
                self.assertEqual(os.readlink(cfg / item), str(native / item))
            doc = json.loads((cfg / ".claude.json").read_text())
            self.assertTrue(doc["hasCompletedOnboarding"])
            self.assertTrue(doc["projects"]["/work/dir"]["hasTrustDialogAccepted"])
            # a second call with another cwd keeps the first project and existing keys
            doc["someKey"] = 1
            (cfg / ".claude.json").write_text(json.dumps(doc))
            harness.prepare_config_dir(sb.paths, "/other")
            doc = json.loads((cfg / ".claude.json").read_text())
            self.assertEqual(doc["someKey"], 1)
            self.assertEqual(set(doc["projects"]), {"/work/dir", "/other"})

    def test_a_real_file_in_the_way_is_moved_aside_never_deleted(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            cfg = sb.paths.claude_config_dir
            cfg.mkdir(parents=True)
            (cfg / "settings.json").write_text('{"was": "isolated"}')
            harness.prepare_config_dir(sb.paths, "/w")
            self.assertTrue((cfg / "settings.json").is_symlink())
            self.assertEqual((cfg / "settings.json.isolated.bak").read_text(), '{"was": "isolated"}')


class RunDirTest(unittest.TestCase):
    def test_write_run_dir_holds_the_key_privately_and_sweep_removes_dead_launches(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            d, helper = harness.write_run_dir(sb.paths, "01LAUNCHA", key="sk-secret", launch={"route": "paid/vendor/model-x"})
            self.assertEqual(d, sb.paths.run_dir / "01LAUNCHA")
            self.assertEqual(oct((d / "key").stat().st_mode & 0o777), "0o600")
            self.assertEqual((d / "key").read_text(), "sk-secret")
            self.assertEqual(json.loads(helper.read_text())["apiKeyHelper"], f"cat {shlex.quote(str(d / 'key'))}")
            self.assertEqual(int((d / "pid").read_text()), os.getpid())
            self.assertEqual(json.loads((d / "launch.json").read_text())["route"], "paid/vendor/model-x")
            d2, helper2 = harness.write_run_dir(sb.paths, "01LAUNCHB", key=None, launch={})
            self.assertIsNone(helper2)
            self.assertFalse((d2 / "key").exists())
            dead = sb.paths.run_dir / "01DEAD"
            dead.mkdir()
            (dead / "pid").write_text("999999")
            (dead / "key").write_text("stale")
            old = time.time() - 60
            os.utime(dead, (old, old))
            removed = harness.sweep_run_dirs(sb.paths)
            self.assertEqual(removed, ["01DEAD"])
            self.assertFalse(dead.exists())
            self.assertTrue(d.exists() and d2.exists())                             # live launcher pid → kept


class SessionArgsTest(unittest.TestCase):
    def test_modes(self):
        args, sid, mode = harness.session_args(["-p", "hi"])
        self.assertEqual((args[0], mode), ("--session-id", "fresh"))
        self.assertEqual(args[1], sid)
        self.assertEqual(args[2:], ["-p", "hi"])
        self.assertEqual(harness.session_args(["--session-id", "abc"]), (["--session-id", "abc"], "abc", "user-session-id"))
        self.assertEqual(harness.session_args(["--session-id=abc"]), (["--session-id=abc"], "abc", "user-session-id"))
        self.assertEqual(harness.session_args(["--resume", "r1", "-p", "x"]), (["--resume", "r1", "-p", "x"], "r1", "resume"))
        self.assertEqual(harness.session_args(["-r"]), (["-r"], None, "resume"))
        self.assertEqual(harness.session_args(["--continue"]), (["--continue"], None, "continue"))
        self.assertEqual(harness.session_args(["--no-session-persistence", "-p", "x"]), (["--no-session-persistence", "-p", "x"], None, "no-persistence"))


class CostLineTest(unittest.TestCase):
    def test_renders_measured_values_and_never_invents(self):
        self.assertEqual(harness.cost_line("mock/alpha", None), "mock/alpha  ctx ? · ? tok/s · $? · cache ? · concurrency ? · thinking ?")
        obs = {"cost_model": {"context": 131072, "harness_baseline_tokens": {"value": 48312}, "tok_s": 63.2,
                              "usd_per_mtok": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, "caching": True, "concurrency": 1,
                              "thinking": {"observed": True, "tokens_on_probe": 2600}}}
        self.assertEqual(harness.cost_line("mock/x", obs), "mock/x  ctx 131072 (48312 baseline = 37%) · 63 tok/s · $0 · cache ✓ · serial · thinking on (~2.6K tok/probe)")
        obs = {"cost_model": {"context": 200000, "harness_baseline_tokens": None, "tok_s": None, "usd_per_mtok": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": None},
                              "caching": False, "concurrency": 4, "thinking": {"observed": False, "tokens_on_probe": None}}}
        self.assertEqual(harness.cost_line("paid/x", obs), "paid/x  ctx 200000 · ? tok/s · $1.0/5.0 per Mtok · cache ✗ · 4× concurrent · thinking off")


class TranscriptTest(unittest.TestCase):
    def write(self, path, lines):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(l) + "\n" for l in lines))

    def test_read_dedups_by_message_id_and_takes_verified_fields_only(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.paths.transcript_path("s1", "/w")
            u1 = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5000, "service_tier": "x"}
            u2 = {"input_tokens": 20, "output_tokens": 30, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 0}
            self.write(p, [
                {"type": "user", "timestamp": "2026-09-08T00:00:00Z", "sessionId": "s1", "version": "2.1.263", "effort": "high", "permissionMode": None, "message": {"role": "user"}},
                {"type": "assistant", "timestamp": "2026-09-08T00:00:01Z", "sessionId": "s1", "version": "2.1.263", "message": {"id": "m1", "model": "alpha", "usage": u1, "total_cost_usd": 9}},
                {"type": "assistant", "timestamp": "2026-09-08T00:00:01Z", "message": {"id": "m1", "model": "alpha", "usage": u1}},      # same API response, second block
                {"type": "assistant", "timestamp": "2026-09-08T00:00:05Z", "message": {"id": "m2", "model": "alpha", "usage": u2}},
                "not json",
            ])
            t = harness.read_transcript(p)
            self.assertEqual(len(t["turns"]), 2)
            self.assertEqual(t["turns"][0]["usage"], {k: u1[k] for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")})
            self.assertEqual(t["first_request"]["input_tokens_total"], 5100)
            self.assertEqual((t["version"], t["effort"], t["permission_mode"], t["session_id"]), ("2.1.263", "high", None, "s1"))
            self.assertNotIn("total_cost_usd", json.dumps(t))

    def test_record_session_fresh_then_resumed_on_a_free_route_keeps_the_paid_cost(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.paths.transcript_path("s2", "/w")
            paid = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": None}
            usage = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
            self.write(p, [{"type": "assistant", "timestamp": "2026-09-08T01:00:01Z", "sessionId": "s2", "version": "2.1.263",
                            "message": {"id": "a", "model": "vendor/model-x", "usage": usage}}])
            launch1 = {"launch_id": "L1", "route": "paid/vendor/model-x", "source": "paid", "wire_model": "vendor/model-x", "started": "2026-09-08T01:00:00Z",
                       "session_id": "s2", "price": paid, "priced_models": {"vendor/model-x": paid}}
            rec = harness.record_session(sb.paths, launch1, ended="2026-09-08T01:00:10Z", transcript=p, mode="fresh")
            self.assertEqual(rec["this_run"]["cost_usd"], 1.0)
            self.assertEqual(rec["session_total"]["cost_usd"], 1.0)
            self.assertEqual(rec["scope_note"], "fresh session; this_run == session_total")
            self.assertEqual(rec["duration_ms"], 10000)
            self.assertEqual(read_observed(sb.paths)["routes"]["paid/vendor/model-x"]["last_session"]["id"], "s2")
            # resumed later on the free mock route: the paid turn keeps its price
            with open(p, "a") as f:
                f.write(json.dumps({"type": "assistant", "timestamp": "2026-09-08T02:00:01Z", "message": {"id": "b", "model": "alpha", "usage": usage}}) + "\n")
            launch2 = {"launch_id": "L2", "route": "mock/alpha", "source": "mock", "wire_model": "alpha", "started": "2026-09-08T02:00:00Z",
                       "session_id": "s2", "price": harness.FREE, "priced_models": {"alpha": harness.FREE}}
            rec = harness.record_session(sb.paths, launch2, ended="2026-09-08T02:00:10Z", transcript=p, mode="resume")
            self.assertEqual(rec["this_run"]["cost_usd"], 0.0)
            self.assertEqual(rec["this_run"]["turns"], 1)
            self.assertEqual(rec["session_total"]["turns"], 2)
            self.assertEqual(rec["session_total"]["cost_usd"], 1.0)                 # rev-6 P2: paid + 0, never 0
            self.assertIn("2 run(s)", rec["scope_note"])
            self.assertEqual(len(read_session_runs(sb.paths, "s2")), 2)

    def test_skipped_records(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            launch = {"launch_id": "L", "route": "mock/alpha", "source": "mock", "wire_model": "alpha", "started": "2026-09-08T01:00:00Z", "session_id": None, "price": harness.FREE, "priced_models": {}}
            rec = harness.record_session(sb.paths, launch, ended="2026-09-08T01:00:01Z", transcript=None, mode="no-persistence")
            self.assertEqual(rec, {"skipped": "no-session-persistence"})
            rec = harness.record_session(sb.paths, launch, ended="2026-09-08T01:00:01Z", transcript=sb.paths.transcript_path("zz", "/w"), mode="fresh")
            self.assertIn("no transcript", rec["skipped"])
            self.assertEqual(read_observed(sb.paths)["routes"]["mock/alpha"]["last_session"]["skipped"], rec["skipped"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_harness_env.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.harness'`

- [ ] **Step 3: Write the module (pure parts)**

`agent_on/harness.py`:

```python
"""L6 — the Claude Code binding (§11). The one file that knows which harness is being launched: it computes the
child environment from a route, isolates CLAUDE_CONFIG_DIR while sharing the user's settings by symlink, keeps
the per-launch run directory (the key, the apiKeyHelper settings file, the launch record), spawns `claude` and
reads the session back into the cost ledger. Nothing here writes `routes.toml` or reads a transcript cost figure."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .cost import attribute_run, fold_session, zero_usage
from .ids import ulid
from .paths import Paths, describe_copy, ensure_state, project_slug
from .schemas.observed import USAGE_FIELDS, empty_route
from .schemas.routes import Route, RouteTable, load_routes
from .sources import probe_source
from .state import append_session_run, locked, read_observed, read_session_runs, resolve_secret, update_observed
from .util import parse_utc, utc_now

TIERS = ("FABLE", "OPUS", "SONNET", "HAIKU")
PLACEHOLDER_TOKEN = "agent-on"          # a keyless source still needs a non-empty token: an empty one prompts for login
DISCOVERY_ENV = "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"
FREE = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
SHARED_ITEMS = ("settings.json", "settings.local.json", "plugins", "skills", "keybindings.json", "CLAUDE.md")
# The routing denylist the old launcher scrubbed (config/ai-litellm/harnesses/claude.json), kept whole: anything
# here in the parent would re-route or re-authenticate the child behind the launcher's back.
SCRUB_ENV = (
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "OPENAI_API_BASE", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_SUPPORTED_CAPABILITIES", "ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES", "ANTHROPIC_DEFAULT_HAIKU_MODEL_SUPPORTED_CAPABILITIES",
    "CLAUDE_CODE_ATTRIBUTION_HEADER", "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
    "CLAUDE_CODE_SKIP_FAST_MODE_ORG_CHECK", "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    "GOOGLE_API_KEY", "GEMINI_API_KEY", "OLLAMA_HOST", "LITELLM_API_KEY", "LITELLM_MASTER_KEY",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH",
    "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL", "AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_CUSTOM_HEADERS",
    "CLAUDE_CONFIG_DIR",
)
# Beyond the list, every ANTHROPIC_* and CLAUDE_* variable of the parent is dropped: a launch from inside another
# Claude Code session (an agent launching agent-on) otherwise hands the child its parent's session plumbing —
# CLAUDE_CODE_SESSION_ID, CLAUDE_CODE_CHILD_SESSION, CLAUDE_CODE_MESSAGING_SOCKET/TOKEN, CLAUDE_EFFORT, CLAUDE_PID were
# all observed inherited on 2026-09-08. The operator's output cap is the one deliberate control that passes (D12).
PASS_THROUGH = ("CLAUDE_CODE_MAX_OUTPUT_TOKENS",)


# ---- child environment (§11 item 2) --------------------------------------------------------------------------

def child_env(parent: dict, table: RouteTable, route: Route, *, context: int | None, config_dir: Path,
              discover: bool = False, sonnet: Route | None = None, haiku: Route | None = None) -> dict:
    """The environment Claude Code is spawned with. Every source's auth_env and the routing denylist are removed;
    a keyed source gets NO key variable (the apiKeyHelper supplies it); a keyless one gets the placeholder token."""
    for r in (sonnet, haiku):
        if r is not None and r.source != route.source:
            raise ValueError(f"--sonnet/--haiku must name a route on source {route.source!r}; {r.name!r} is on {r.source!r}")
    env = {k: v for k, v in parent.items()
           if k in PASS_THROUGH or (k not in SCRUB_ENV and not k.startswith(("ANTHROPIC_", "CLAUDE_")))}
    for src in table.sources.values():
        if src.auth_env:
            env.pop(src.auth_env, None)
    source = table.sources[route.source]
    env["ANTHROPIC_BASE_URL"] = source.base_url
    if source.auth_env is None:
        env["ANTHROPIC_AUTH_TOKEN"] = PLACEHOLDER_TOKEN
    slots = {"FABLE": route, "OPUS": route, "SONNET": sonnet or route, "HAIKU": haiku or route}
    for tier, r in slots.items():
        env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"] = r.wire_model
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = route.wire_model
    if context:
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(context)
    env["CLAUDE_CODE_ATTRIBUTION_HEADER"] = "0"
    if discover:
        env[DISCOVERY_ENV] = "1"
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


# ---- the isolated config dir (§11 item 1) --------------------------------------------------------------------

def prepare_config_dir(paths: Paths, cwd: str) -> Path:
    """$STATE/claude-config: the user's settings, plugins, skills, keybindings and CLAUDE.md are symlinks to
    ~/.claude (dangling links are fine — they light up when the native file appears); transcripts, history and
    auto-memory stay per-launcher. The project is marked trusted, because the apiKeyHelper only runs for a
    trusted project. Existing keys of .claude.json are preserved; the write is serialised under a state lock."""
    cfg = paths.claude_config_dir
    cfg.mkdir(parents=True, exist_ok=True, mode=0o700)
    native = paths.home / ".claude"
    for item in SHARED_ITEMS:
        link, target = cfg / item, native / item
        if link.is_symlink():
            if os.readlink(link) != str(target):
                link.unlink()
                link.symlink_to(target)
            continue
        if link.exists():
            link.rename(link.with_name(f"{item}.isolated.bak"))
        link.symlink_to(target)
    dotfile = cfg / ".claude.json"
    with locked(paths.state / "locks" / "config.lock"):
        doc: dict = {}
        if dotfile.exists():
            try:
                doc = json.loads(dotfile.read_text(encoding="utf-8"))
            except ValueError:
                doc = {}
        changed = False
        if doc.get("hasCompletedOnboarding") is not True:
            doc["hasCompletedOnboarding"] = True
            changed = True
        entry = doc.setdefault("projects", {}).setdefault(cwd, {})
        if entry.get("hasTrustDialogAccepted") is not True:
            entry["hasTrustDialogAccepted"] = True
            changed = True
        if changed or not dotfile.exists():
            tmp = dotfile.with_name(".claude.json.tmp")
            tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, dotfile)
    return cfg


# ---- run/<launch-id>/ (§7.1, §11 item 2) ---------------------------------------------------------------------

def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_run_dirs(paths: Paths, min_age_s: float = 5.0) -> list[str]:
    """Remove run directories whose launcher pid is dead (a crash left the key behind). A directory younger than
    min_age_s is left alone: another launch may be between mkdir and its pid file."""
    removed: list[str] = []
    if not paths.run_dir.exists():
        return removed
    now = time.time()
    for d in sorted(paths.run_dir.iterdir()):
        if not d.is_dir() or now - d.stat().st_mtime < min_age_s:
            continue
        try:
            pid = int((d / "pid").read_text().strip())
        except (OSError, ValueError):
            pid = None
        if pid is None or not _alive(pid):
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    return removed


def write_run_dir(paths: Paths, launch_id: str, *, key: str | None, launch: dict) -> tuple[Path, Path | None]:
    """Create run/<launch-id>/ with the launcher's pid, the launch record, and — for a keyed source — the key at
    mode 0600 plus the settings file whose apiKeyHelper reads it. Returns (run_dir, helper settings path or None)."""
    ensure_state(paths)
    d = paths.run_dir / launch_id
    d.mkdir(mode=0o700)
    (d / "pid").write_text(str(os.getpid()), encoding="utf-8")
    (d / "launch.json").write_text(json.dumps(launch, indent=1, sort_keys=True), encoding="utf-8")
    helper = None
    if key is not None:
        key_path = d / "key"
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key.encode("utf-8"))
        finally:
            os.close(fd)
        helper = d / "settings.json"
        helper.write_text(json.dumps({"apiKeyHelper": f"cat {shlex.quote(str(key_path))}"}), encoding="utf-8")
    return d, helper


# ---- session rules (§9) ----------------------------------------------------------------------------------------

def session_args(claude_args: list[str]) -> tuple[list[str], str | None, str]:
    """Inject --session-id unless the user chose the session themselves. Returns (args, session_id or None, mode)."""
    args = list(claude_args)
    if "--no-session-persistence" in args:
        return args, None, "no-persistence"
    for i, a in enumerate(args):
        if a == "--session-id":
            return args, (args[i + 1] if i + 1 < len(args) else None), "user-session-id"
        if a.startswith("--session-id="):
            return args, a.split("=", 1)[1], "user-session-id"
    for i, a in enumerate(args):
        if a in ("--resume", "-r"):
            nxt = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("-") else None
            return args, nxt, "resume"
        if a.startswith("--resume="):
            return args, a.split("=", 1)[1], "resume"
    if "--continue" in args or "-c" in args:
        return args, None, "continue"
    sid = str(uuid.uuid4())
    return ["--session-id", sid, *args], sid, "fresh"


# ---- the §12 line ----------------------------------------------------------------------------------------------

def cost_line(route_name: str, observed_route: dict | None) -> str:
    """One line before spawning. Every field comes from the cost model; a value the probes did not produce is `?`."""
    cm = (observed_route or {}).get("cost_model") or {}
    ctx = cm.get("context")
    base = (cm.get("harness_baseline_tokens") or {}).get("value")
    ctx_s = f"ctx {ctx}" if ctx else "ctx ?"
    if ctx and base:
        ctx_s += f" ({base} baseline = {round(100 * base / ctx)}%)"
    elif base:
        ctx_s += f" ({base} baseline)"
    tok = cm.get("tok_s")
    tok_s = f"{tok:.0f} tok/s" if isinstance(tok, (int, float)) and not isinstance(tok, bool) else "? tok/s"
    usd = cm.get("usd_per_mtok")
    if isinstance(usd, dict) and usd.get("input") is not None:
        usd_s = "$0" if not usd.get("input") and not usd.get("output") else f"${usd['input']}/{usd.get('output')} per Mtok"
    else:
        usd_s = "$?"
    cache = {True: "cache ✓", False: "cache ✗"}.get(cm.get("caching"), "cache ?")
    conc = cm.get("concurrency")
    conc_s = "serial" if conc == 1 else (f"{conc}× concurrent" if conc else "concurrency ?")
    th = cm.get("thinking") or {}
    if th.get("observed") is True:
        th_s = "thinking on" + (f" (~{th['tokens_on_probe'] / 1000:.1f}K tok/probe)" if th.get("tokens_on_probe") else "")
    elif th.get("observed") is False:
        th_s = "thinking off"
    else:
        th_s = "thinking ?"
    return f"{route_name}  {ctx_s} · {tok_s} · {usd_s} · {cache} · {conc_s} · {th_s}"


# ---- session read-back (§11 item 4) --------------------------------------------------------------------------

def read_transcript(path: Path) -> dict:
    """Only the verified fields (§7). Claude Code writes one line per content block of an API response, all with
    the same message.id and identical usage — turns are keyed by message.id so a response is counted once.
    Claude Code's own cost figure is never read (F11)."""
    turns: dict[str, dict] = {}
    meta = {"version": None, "effort": None, "permission_mode": None, "session_id": None}
    first = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if meta["version"] is None and d.get("version"):
                meta["version"] = d["version"]
            if meta["session_id"] is None and d.get("sessionId"):
                meta["session_id"] = d["sessionId"]
            if meta["effort"] is None and d.get("effort") is not None:
                meta["effort"] = d["effort"]
            if meta["permission_mode"] is None and d.get("permissionMode") is not None:
                meta["permission_mode"] = d["permissionMode"]
            if d.get("type") != "assistant":
                continue
            msg = d.get("message") or {}
            usage = msg.get("usage")
            ts = d.get("timestamp")
            if not isinstance(usage, dict) or not isinstance(ts, str):
                continue
            u = {k: int(usage.get(k) or 0) for k in USAGE_FIELDS}
            key = msg.get("id") or d.get("uuid") or f"line-{len(turns)}"
            turns[key] = {"timestamp": ts, "model": msg.get("model"), "usage": u}
            if first is None:
                first = {"input_tokens_total": u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"], "usage": u}
    return {"turns": list(turns.values()), "first_request": first, **meta}


def find_transcript(paths: Paths, session_id: str | None, cwd: str, mode: str, started: str) -> Path | None:
    """The file to read after exit: the known session id, else (resume without id / continue) the newest transcript
    of this project modified since the launch started."""
    if mode == "no-persistence":
        return None
    if session_id:
        return paths.transcript_path(session_id, cwd)
    pdir = paths.claude_config_dir / "projects" / project_slug(cwd)
    if not pdir.exists():
        return None
    since = parse_utc(started).timestamp() - 1
    files = [p for p in pdir.glob("*.jsonl") if p.stat().st_mtime >= since]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def record_session(paths: Paths, launch: dict, *, ended: str, transcript: Path | None, mode: str) -> dict:
    """Write last_session for the route and one ledger line for the session (§11 item 4). Best-effort: a missing
    transcript is recorded as {skipped}, never raised."""
    route = launch["route"]
    if mode == "no-persistence":
        rec: dict = {"skipped": "no-session-persistence"}
    elif transcript is None or not transcript.exists():
        rec = {"skipped": f"no transcript at {transcript}"}
    else:
        t = read_transcript(transcript)
        session_id = t["session_id"] or launch.get("session_id") or transcript.stem
        run = {"launch_id": launch["launch_id"], "route": route, "source": launch["source"], "wire_model": launch["wire_model"],
               "started": launch["started"], "ended": ended, "price": launch["price"], "priced_models": launch.get("priced_models") or {}}
        this_run = attribute_run(t["turns"], run)
        append_session_run(paths, session_id, {**this_run, "session_id": session_id, "mode": mode})
        runs = read_session_runs(paths, session_id)
        total = fold_session(t["turns"], runs)
        fresh = mode in ("fresh", "user-session-id") and len(runs) == 1
        rec = {"id": session_id, "at": ended,
               "first_request": t["first_request"] or {"input_tokens_total": 0, "usage": zero_usage()},
               "this_run": this_run, "session_total": total,
               "scope_note": "fresh session; this_run == session_total" if fresh else f"{mode}: this_run is this launch's turns; session_total folds {len(runs)} run(s)",
               "duration_ms": int((parse_utc(ended) - parse_utc(launch["started"])).total_seconds() * 1000),
               "effort": t["effort"], "permission_mode": t["permission_mode"], "claude_code": t["version"]}

    def mutate(doc: dict) -> None:
        doc["routes"].setdefault(route, empty_route())["last_session"] = rec

    update_observed(paths, mutate)
    return rec
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/harness.py tests/agent_on/test_harness_env.py
git commit -m "feat(agent-on): harness binding — child env, isolated config dir, run dir, session rules, cost line, read-back

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 4: Spawn and `run_launch`, proven with a fake `claude`

**Files:**
- Modify: `agent_on/harness.py` (append `spawn`, `run_launch`)
- Create: `tests/agent_on/fakeclaude.py` (a stand-in `claude`; not collected — no `test_` prefix)
- Test: `tests/agent_on/test_harness_launch.py`

**Interfaces:**
- Produces: `utc_ceil() -> str`; `spawn(argv, env, cwd) -> int`; `run_launch(paths, name, claude_args, *, harness="claude", discover=False, sonnet=None, haiku=None, dry_run=False, env=None, claude_bin=None, cwd=None, probe_timeout=2.0, announce=True) -> dict` with keys `command, copy, route, wire_model, base_url, launch_id, session{id, mode}, cost_line, invariants[], env_keys[], swept[], warnings[]`, plus `dry_run, argv` when dry, else `exit_code, last_session, transcript`.

Rulings: run windows are second-precision — `started` is floored, `ended` is rounded up (`utc_ceil`) so the last turn's milliseconds are inside the window; a relaunch of the same session within the same second would overlap and the fold reports `unknown` (honest, and not a real scenario). With a controlling terminal the child receives Ctrl-C from the tty itself, so the launcher **ignores SIGINT** (it must survive to do the read-back) and forwards **SIGTERM** only; forwarding SIGINT too would deliver a double interrupt, which Claude Code treats as "exit now".

- [ ] **Step 1: Write the fake `claude` and the failing tests**

`tests/agent_on/fakeclaude.py`:

```python
#!/usr/bin/env python3
"""A stand-in for the `claude` binary, for the launcher's unit tests. It records what it received (its environment
and argv), runs the apiKeyHelper it was handed exactly as Claude Code would (a shell command), writes a transcript
shaped like Claude Code's into $CLAUDE_CONFIG_DIR/projects/<slug>/, honours --session-id / --resume / --continue /
--no-session-persistence, and exits with $FAKE_CLAUDE_EXIT."""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

args = sys.argv[1:]


def opt(flag):
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


out = os.environ.get("FAKE_CLAUDE_OUT")
if out:
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "env.json"), "w") as f:
        json.dump(dict(os.environ), f)
    with open(os.path.join(out, "argv.json"), "w") as f:
        json.dump(args, f)
    settings = opt("--settings")
    if settings and os.path.exists(settings):
        with open(settings) as f:
            helper = json.load(f).get("apiKeyHelper")
        if helper:
            key = subprocess.run(helper, shell=True, capture_output=True, text=True).stdout.strip()
            with open(os.path.join(out, "helper_key.txt"), "w") as f:
                f.write(key)

cfg = os.environ.get("CLAUDE_CONFIG_DIR")
if cfg and "--no-session-persistence" not in args:
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    pdir = os.path.join(cfg, "projects", slug)
    os.makedirs(pdir, exist_ok=True)
    sid = opt("--session-id") or opt("--resume") or opt("-r")
    if sid is None:
        existing = sorted((os.path.join(pdir, f) for f in os.listdir(pdir) if f.endswith(".jsonl")), key=os.path.getmtime)
        if ("--continue" in args or "-c" in args) and existing:
            path = existing[-1]
        else:
            path = os.path.join(pdir, f"{uuid.uuid4()}.jsonl")
    else:
        path = os.path.join(pdir, f"{sid}.jsonl")
    session_id = os.path.basename(path)[:-6]
    model = os.environ.get("FAKE_CLAUDE_MODEL") or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "unknown")
    turns = int(os.environ.get("FAKE_CLAUDE_TURNS", "2"))
    with open(path, "a") as f:
        for i in range(turns):
            time.sleep(0.002)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"      # real milliseconds, like Claude Code
            usage = {"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 20000 if i else 0, "cache_creation_input_tokens": 0 if i else 20000}
            mid = f"msg_{uuid.uuid4().hex[:8]}"
            line = {"type": "assistant", "timestamp": ts, "sessionId": session_id, "version": "0.0.0-fake", "effort": "high", "permissionMode": "default",
                    "message": {"id": mid, "model": model, "role": "assistant", "usage": usage, "content": [], "total_cost_usd": 0.24}}
            f.write(json.dumps(line) + "\n")
            f.write(json.dumps({**line, "message": {**line["message"], "content": [{"type": "text", "text": "second block"}]}}) + "\n")

sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
```

`tests/agent_on/test_harness_launch.py`:

```python
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.state import read_observed, read_session_runs  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fakeclaude.py")
BASE = "http://127.0.0.1:1"      # every source unreachable: route.served skips, the launch proceeds (D6)


class LaunchTest(unittest.TestCase):
    def launch(self, sb, name, args, env=None, **kw):
        out = sb.root / "fake-out"
        base_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "FAKE_CLAUDE_OUT": str(out), **(env or {})}
        doc = harness.run_launch(sb.paths, name, args, env=base_env, claude_bin=FAKE, cwd=str(sb.paths.checkout), probe_timeout=0.5, announce=False, **kw)
        return doc, out

    def test_keyed_launch_hands_the_key_to_the_helper_and_never_to_the_environment(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "x", ["-p", "hi"], env={"MOCK_PAID_KEY": "sk-from-env", "ANTHROPIC_API_KEY": "sk-inherited"})
            self.assertEqual(doc["exit_code"], 0)
            env = json.loads((out / "env.json").read_text())
            self.assertNotIn("MOCK_PAID_KEY", env)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
            self.assertNotIn("sk-from-env", json.dumps(env))
            self.assertEqual((out / "helper_key.txt").read_text(), "sk-from-env")      # the helper got it
            argv = json.loads((out / "argv.json").read_text())
            self.assertEqual(argv[0], "--settings")
            self.assertTrue(argv[1].endswith("/settings.json"))
            self.assertEqual(argv[2], "--session-id")
            self.assertEqual(argv[3], doc["session"]["id"])
            self.assertEqual(argv[4:], ["-p", "hi"])
            self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "vendor/model-x")
            self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "100000")               # declared limit: nothing measured yet
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(sb.paths.claude_config_dir))
            self.assertEqual(list(sb.paths.run_dir.iterdir()), [])                      # run dir removed after exit
            rec = doc["last_session"]
            self.assertEqual(rec["id"], doc["session"]["id"])
            self.assertEqual(rec["this_run"]["turns"], 2)                                # 4 lines, 2 message ids
            # the first message carries cache_creation tokens and the paid fixture publishes no cache-write price:
            # an absent price is not 0 (§11), so the run is "unknown" and says why
            self.assertEqual(rec["this_run"]["cost_usd"], "unknown")
            self.assertTrue(any("cache_write" in r for r in rec["this_run"]["unknown_reasons"]))
            self.assertEqual(rec["session_total"]["cost_usd"], "unknown")
            self.assertEqual(rec["first_request"]["input_tokens_total"], 21000)
            self.assertEqual(rec["claude_code"], "0.0.0-fake")
            self.assertEqual(rec["effort"], "high")
            self.assertNotIn("total_cost_usd", json.dumps(read_observed(sb.paths)))
            self.assertEqual(len(read_session_runs(sb.paths, rec["id"])), 1)
            self.assertEqual([i["id"] for i in doc["invariants"]], ["route.served"])
            self.assertEqual(doc["invariants"][0]["result"], "skip")
            self.assertTrue(doc["cost_line"].startswith("paid/vendor/model-x  ctx ?"))

    def test_key_from_the_env_file_when_the_environment_has_none(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir(parents=True, exist_ok=True)
            sb.paths.env_file.write_text("MOCK_PAID_KEY=sk-from-file\n")
            os.chmod(sb.paths.env_file, 0o600)
            doc, out = self.launch(sb, "paid/vendor/model-x", ["-p", "hi"])
            self.assertEqual((out / "helper_key.txt").read_text(), "sk-from-file")
            self.assertFalse(any("MOCK_PAID_KEY" in w for w in doc["warnings"]))          # the D6 "unreachable" warning may be present

    def test_keyless_launch_uses_the_placeholder_and_no_settings_file(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["-p", "hi"])
            env = json.loads((out / "env.json").read_text())
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "agent-on")
            self.assertNotIn("--settings", json.loads((out / "argv.json").read_text()))
            self.assertFalse((out / "helper_key.txt").exists())
            self.assertEqual(doc["last_session"]["this_run"]["cost_usd"], 0.0)

    def test_session_modes_exit_code_and_dry_run(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["--no-session-persistence", "-p", "hi"])
            self.assertEqual(doc["last_session"], {"skipped": "no-session-persistence"})
            doc, out = self.launch(sb, "a", ["--session-id", "11111111-1111-1111-1111-111111111111"])
            self.assertEqual(doc["session"], {"id": "11111111-1111-1111-1111-111111111111", "mode": "user-session-id"})
            self.assertEqual(doc["last_session"]["this_run"]["turns"], 2)
            time.sleep(1.1)   # run windows are second-precision (floor start, ceil end): a relaunch of the same session within
            #                   the same second would overlap the previous window, and the fold would honestly say "unknown"
            doc, out = self.launch(sb, "a", ["--resume", "11111111-1111-1111-1111-111111111111"])
            self.assertEqual(doc["session"]["mode"], "resume")
            self.assertEqual(doc["last_session"]["this_run"]["turns"], 2)
            self.assertEqual(doc["last_session"]["session_total"]["turns"], 4)
            self.assertEqual(doc["last_session"]["session_total"]["cost_usd"], 0.0)
            self.assertIn("2 run(s)", doc["last_session"]["scope_note"])
            time.sleep(1.1)
            doc, out = self.launch(sb, "a", ["--continue"])
            self.assertEqual(doc["session"]["mode"], "continue")
            self.assertEqual(doc["last_session"]["session_total"]["turns"], 6)          # the newest transcript was continued
            doc, out = self.launch(sb, "a", ["-p", "x"], env={"FAKE_CLAUDE_EXIT": "3"})
            self.assertEqual(doc["exit_code"], 3)
            (out / "env.json").unlink()                                                  # left by the launches above
            doc, out = self.launch(sb, "a", ["-p", "x"], dry_run=True)
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["argv"][0], FAKE)
            self.assertIn("--session-id", doc["argv"])
            self.assertFalse((out / "env.json").exists())                                # nothing was spawned
            self.assertIn("ANTHROPIC_BASE_URL", doc["env_keys"])

    def test_tier_override_and_a_missing_key_are_reported(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["-p", "x"], haiku="mock/gone")
            self.assertEqual(json.loads((out / "env.json").read_text())["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gone")
            with self.assertRaises(ValueError):
                self.launch(sb, "a", ["-p", "x"], sonnet="x")
            doc, out = self.launch(sb, "x", ["-p", "x"])                                   # keyed source, no key anywhere
            self.assertTrue(any("MOCK_PAID_KEY" in w for w in doc["warnings"]))
            self.assertEqual(doc["exit_code"], 0)                                          # D6: informed, not gated
            self.assertFalse((out / "helper_key.txt").exists())


if __name__ == "__main__":
    unittest.main()
```

After writing `tests/agent_on/fakeclaude.py`, make it executable — the launcher runs it as the `claude` binary: `chmod +x tests/agent_on/fakeclaude.py` (git records the mode; the commit below adds it). The fake's keyed run is priced `"unknown"` on purpose: the `paid` fixture publishes no cache-write price and the first message carries `cache_creation_input_tokens`, which is the §11 case "a price that is absent is not 0".

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_harness_launch.py' -v`
Expected: `AttributeError: module 'agent_on.harness' has no attribute 'run_launch'`

- [ ] **Step 3: Append to `agent_on/harness.py`**

```python
# ---- spawn and the launch (§9 launch row) ---------------------------------------------------------------------

def utc_ceil() -> str:
    """Now, rounded UP to the next whole second: transcript timestamps carry milliseconds, so a run's window must end
    no earlier than the last turn Claude Code wrote just before exiting."""
    now = datetime.now(timezone.utc)
    if now.microsecond:
        now = now.replace(microsecond=0) + timedelta(seconds=1)
    return now.isoformat().replace("+00:00", "Z")


def spawn(argv: list[str], env: dict, cwd: str) -> int:
    """Run Claude Code as a child with inherited stdio. The tty delivers Ctrl-C to the child directly, so the launcher
    ignores SIGINT (it must outlive the child to do the read-back) and forwards SIGTERM. Returns the exit status."""
    proc = subprocess.Popen(argv, env=env, cwd=cwd)

    def forward(signum, frame):
        try:
            proc.send_signal(signum)
        except ProcessLookupError:
            pass

    old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
    old_term = signal.signal(signal.SIGTERM, forward)
    try:
        return proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)


def _price_of(route: Route, keyless: bool) -> dict | None:
    if route.price is not None:
        return route.price.per_mtok()
    return dict(FREE) if keyless else None


def run_launch(paths: Paths, name: str, claude_args: list[str], *, harness: str = "claude", discover: bool = False,
               sonnet: str | None = None, haiku: str | None = None, dry_run: bool = False, env: dict | None = None,
               claude_bin: str | None = None, cwd: str | None = None, probe_timeout: float = 2.0, announce: bool = True) -> dict:
    if harness != "claude":
        raise ValueError(f"harness {harness!r} is not bound yet (Plan F adds codex)")
    parent = dict(os.environ if env is None else env)
    # the physical path: Claude Code derives the transcript slug from process.cwd(), which resolves symlinks
    # (macOS: /var/… is /private/var/…); the trust entry and the transcript lookup must use the same string
    cwd = os.path.realpath(cwd or os.getcwd())
    table = load_routes(paths)
    route = table.resolve(name)
    source = table.sources[route.source]
    sonnet_r = table.resolve(sonnet) if sonnet else None
    haiku_r = table.resolve(haiku) if haiku else None
    observed = read_observed(paths)
    obs_route = observed["routes"].get(route.name)
    warnings: list[str] = []
    # D6: one ≤2 s probe; unreachable → skip + warning, the launch proceeds
    probe = probe_source(source, timeout=probe_timeout)
    if not probe.reachable:
        served = {"id": "route.served", "result": "skip", "reason": f"{route.source} unreachable: {probe.error}", "subject": route.name, "fix": None}
        warnings.append(f"{route.source} did not answer ({probe.error}); launching anyway (D6)")
    elif route.wire_model in probe.catalog:
        served = {"id": "route.served", "result": "pass", "reason": "served", "subject": route.name, "fix": None}
    else:
        served = {"id": "route.served", "result": "fail", "reason": f"{route.wire_model!r} not in {route.source} catalog", "subject": route.name, "fix": "run `agent-on sync`"}
        warnings.append(f"{route.wire_model!r} is not in the {route.source} catalog right now; launching anyway (D6)")
    context = ((obs_route or {}).get("cost_model") or {}).get("context")
    if context is None:                                                            # never synced: the declared cap is still better than
        lim = table.effective_limits(route)                                        # Claude Code's 200k assumption for an unknown model
        context = lim.input if lim else None
    key = resolve_secret(paths, source.auth_env, parent) if source.auth_env else None
    if source.auth_env and key is None:
        warnings.append(f"no {source.auth_env} in the environment or {paths.env_file}; Claude Code will not be able to authenticate to {route.source}")
    swept = sweep_run_dirs(paths)
    config_dir = prepare_config_dir(paths, cwd)
    launch_id = ulid()
    started = utc_now()
    args, session_id, mode = session_args(claude_args)
    keyless = source.auth_env is None
    priced = {r.wire_model: _price_of(r, keyless) for r in table.by_source(route.source)}
    launch = {"launch_id": launch_id, "route": route.name, "source": route.source, "wire_model": route.wire_model, "started": started,
              "session_id": session_id, "mode": mode, "cwd": cwd, "price": _price_of(route, keyless),
              "priced_models": {m: p for m, p in priced.items() if p is not None}, "context": context, "claude_args": args}
    cenv = child_env(parent, table, route, context=context, config_dir=config_dir, discover=discover, sonnet=sonnet_r, haiku=haiku_r)
    line = cost_line(route.name, obs_route)
    doc = {"command": "launch", "copy": describe_copy(paths), "route": route.name, "wire_model": route.wire_model, "base_url": source.base_url,
           "launch_id": launch_id, "session": {"id": session_id, "mode": mode}, "cost_line": line, "invariants": [served],
           "env_keys": sorted(k for k in cenv if k.startswith(("ANTHROPIC_", "CLAUDE_"))), "swept": swept, "warnings": warnings}
    binary = claude_bin or shutil.which("claude") or "claude"
    if dry_run:
        doc.update({"dry_run": True, "argv": [binary, *(["--settings", "<run-dir>/settings.json"] if key is not None else []), *args]})
        return doc
    run_dir, helper = write_run_dir(paths, launch_id, key=key, launch=launch)
    argv = [binary, *(["--settings", str(helper)] if helper else []), *args]   # the helper file first: a user --settings merges after it
    if announce:
        print(line, file=sys.stderr)                                              # the §12 line, before spawning
    try:
        code = spawn(argv, cenv, cwd)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)                                 # the key never outlives the child
    ended = utc_ceil()                                                            # inclusive of the last turn's milliseconds
    transcript = find_transcript(paths, session_id, cwd, mode, started)
    rec = record_session(paths, launch, ended=ended, transcript=transcript, mode=mode)
    doc.update({"exit_code": code, "last_session": rec, "transcript": str(transcript) if transcript else None})
    return doc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: all pass. The four-line fixture yields two turns (two message ids).

- [ ] **Step 5: Commit**

```bash
git add agent_on/harness.py tests/agent_on/fakeclaude.py tests/agent_on/test_harness_launch.py
git commit -m "feat(agent-on): run_launch — spawn Claude Code with the key in the helper, never the environment; read the session back

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---
### Task 5: `qualify` — the six gates and the probes, against the mock

**Files:**
- Modify: `agent_on/schemas/errors.py` (one rule), `agent_on/schemas/observed.py` (`last_qualification` shape)
- Create: `agent_on/qualify.py` (the wire, the gates, the probes; `run_qualify` is Task 6)
- Test: `tests/agent_on/test_qualify.py`

**Interfaces:**
- Produces: `errors.RULES["observed.qualification.shape"]`; `observed.QUALIFICATION_KEYS`, `observed.FINGERPRINT_KEYS`, validation of `last_qualification`; `qualify.GATES`, `qualify.Wire(base_url, model, key=None, timeout=90.0)` with `.post(payload) -> (status, body)`, `.stream(payload) -> (status, events)`, `.count_tokens(payload) -> int | None`; `run_gates(wire) -> {"gates": {name: bool}, "details": {…}, "thinking_block_seen": bool, "completed": bool, "thinking_tokens": int | None, "all_pass": bool}`; `probe_throughput(wire) -> {"tok_s", "output_tokens", "seconds"}`; `probe_concurrency(wire) -> {"concurrency", "serial_s", "pair_s", "ratio"}`; `probe_caching(wire) -> {"caching": bool, "cache_read_second": int, "status": int}`; `probe_limits(wire, lo, hi, *, count_tokens=True, max_probes=10) -> {"verified": int | None, "basis": "count_tokens" | "estimate" | None, "probes": [...]}` — `verified` is the *counted* size of the largest accepted probe when the source serves `count_tokens`, else the requested size.

The six gates are the ones `scripts/verify_tool_call_fidelity.py` has run since 2026-08 (text SSE, Claude's list-valued system blocks, forced native tool call, streamed `input_json_delta`, exact `tool_result` continuation, adaptive-effort request shape), ported to the direct wire: the request goes to `<base_url>/v1/messages` with both `x-api-key` and `Authorization: Bearer` when the source has a key (OpenRouter honours either; oMLX ignores both). `concurrency` is a two-level probe: two concurrent requests against one; a pair that completes in under 1.5× the single request's time reports `2`, else `1` — the 2026-09-08 measurement showed batching gain is per model, so this is measured per route and never inherited. `caching` needs a cacheable prefix: the probe sends a ~1,500-token system block with `cache_control` twice and reads `cache_read_input_tokens` on the second reply. `probe_limits` bisects the enforced input boundary with `max_tokens: 1` requests of a repeated word, calibrated with `count_tokens` where the source serves it (oMLX does; the mock does), otherwise one word ≈ one token; a 4xx whose message mentions `long`/`context`/`maximum`/`exceed` counts as "over".

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_qualify.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

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
            self.assertIsInstance(r["thinking_tokens"], int)
            self.assertEqual(r["details"]["forced_structured_tool_status"], 200)
            # the tool_result continuation replayed the model's own tool_use id
            replay = [b for b in m.messages if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in (b["messages"][-1].get("content") or []) if isinstance(b["messages"][-1].get("content"), list))]
            self.assertEqual(replay[0]["messages"][-1]["content"][0]["tool_use_id"], "toolu_mock_1")

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
        self.assertEqual(set(GATE_NAMES) - {"thinking"}, set(GATES))

    def test_auth_and_unreachable_are_statuses_not_exceptions(self):
        with MockSource(expect_key="k") as m:
            r = run_gates(Wire(m.base_url, "x", key="wrong", timeout=10))
            self.assertFalse(r["all_pass"])
            self.assertEqual(r["details"]["text_sse_status"], 401)
            self.assertTrue(run_gates(Wire(m.base_url, "x", key="k", timeout=10))["all_pass"])
        r = run_gates(Wire("http://127.0.0.1:9", "x", timeout=2))
        self.assertFalse(r["all_pass"])
        self.assertEqual(r["details"]["text_sse_status"], 0)


class ProbesTest(unittest.TestCase):
    def test_throughput_and_concurrency(self):
        with MockSource(delay_s=0.2) as m:
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
        with MockSource() as m:                                                          # nothing enforced below hi
            r = probe_limits(Wire(m.base_url, "x", timeout=10), 100, 400, count_tokens=False)
            self.assertEqual(r["verified"], 400)
            self.assertEqual(r["basis"], "estimate")


class QualificationShapeTest(unittest.TestCase):
    def test_last_qualification_must_carry_gates_and_a_fingerprint(self):
        doc = empty_observed()
        doc["routes"]["r"] = empty_route()
        doc["routes"]["r"]["last_qualification"] = {"pass": True, "gates": {g: True for g in GATES}, "thinking_block_seen": False, "completed": True,
                                                   "at": "2026-09-08T00:00:00Z", "fingerprint": {"effective_route_sha": "a", "wire_model": "m", "source_identity": None, "claude_code": None}}
        validate_observed(doc)
        doc["routes"]["r"]["last_qualification"]["fingerprint"] = {"wire_model": "m"}
        with self.assertRaises(SchemaError) as cm:
            validate_observed(doc)
        self.assertEqual(cm.exception.rule, "observed.qualification.shape")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_qualify.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.qualify'`

- [ ] **Step 3: Write the code**

`agent_on/schemas/errors.py` — add to `RULES`, after `observed.session.shape`:

```python
    "observed.qualification.shape": "last_qualification has pass, gates{name: bool}, thinking_block_seen, completed, at, and a fingerprint with effective_route_sha, wire_model, source_identity, claude_code",
```

In `tests/agent_on/test_invariants.py` (`test_qualification_goes_stale_when_the_effective_config_changes`), the planted record must carry the full shape now — replace
`doc["routes"]["mock/alpha"]["last_qualification"] = {"pass": True, "at": "2026-09-07T00:00:00Z",` with
`doc["routes"]["mock/alpha"]["last_qualification"] = {"pass": True, "at": "2026-09-07T00:00:00Z", "gates": {}, "thinking_block_seen": False, "completed": True,` (the rest of the line unchanged).

`agent_on/schemas/observed.py` — add the constants after `GATE_RUN_KEYS`:

```python
QUALIFICATION_KEYS = ("pass", "gates", "thinking_block_seen", "completed", "at", "fingerprint")
FINGERPRINT_KEYS = ("effective_route_sha", "wire_model", "source_identity", "claude_code")
```

and in `validate_route`, before the `last_session` check:

```python
    q = r["last_qualification"]
    if q is not None:
        _require_keys(q, QUALIFICATION_KEYS, f"{where}.last_qualification", "observed.qualification.shape")
        _require_keys(q["fingerprint"], FINGERPRINT_KEYS, f"{where}.last_qualification.fingerprint", "observed.qualification.shape")
        if not isinstance(q["gates"], dict) or not all(isinstance(v, bool) for v in q["gates"].values()):
            raise SchemaError("observed.qualification.shape", f"{where}.last_qualification.gates must map gate names to booleans")
```

`agent_on/qualify.py`:

```python
"""`agent-on qualify <route>` (§7, §8, §9): the six fidelity gates on the direct wire, the throughput, concurrency,
caching and thinking probes, the harness baseline and the enforced input limit. Every result is recorded with the
fingerprint it was valid for. The gates are those scripts/verify_tool_call_fidelity.py ran through LiteLLM; here
they hit the source itself."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

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
    gates["forced_structured_tool"] = bool(status == 200 and resp.get("stop_reason") == "tool_use" and tool and isinstance(tool_id, str) and tool_id.strip()
                                           and tool.get("name") == "get_weather" and _valid_city(tool.get("input")))
    details["forced_structured_tool_status"] = status

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
    thinking_chars = sum(len(b.get("thinking", "")) for b in thinking)
    completed = status == 200 and resp.get("stop_reason") == "end_turn" and bool(text.strip())

    return {"gates": gates, "details": details, "thinking_block_seen": bool(thinking), "completed": completed,
            "thinking_tokens": (thinking_chars // 4) if thinking else None, "all_pass": all(gates.values())}


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
    """A cacheable system prefix (~1,500 tokens) sent twice; caching is true when the second reply reports cache reads."""
    prefix = ("This system prompt exists only to be long enough to be cached by the provider. " * 90).strip()
    payload = {"max_tokens": 8, "system": [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}],
               "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}
    wire.post(payload)
    status, resp = wire.post(payload)
    read = int((resp.get("usage") or {}).get("cache_read_input_tokens") or 0)
    return {"caching": status == 200 and read > 0, "cache_read_second": read, "status": status}


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
    if status == 200:
        return {"verified": verified_size(hi), "basis": "count_tokens" if hi in counted else "estimate", "probes": probes}
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
    return {"verified": verified_size(accepted), "basis": "count_tokens" if accepted in counted else "estimate", "probes": probes}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: all pass (`test_schema_rules_registry_is_complete_and_alive` still passes because the new rule is raised literally in `observed.py`).

- [ ] **Step 5: Commit**

```bash
git add agent_on/schemas/errors.py agent_on/schemas/observed.py agent_on/qualify.py tests/agent_on/test_qualify.py
git commit -m "feat(agent-on): qualify — six fidelity gates and the throughput, concurrency, caching, limit probes on the direct wire

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---
### Task 6: `run_qualify`, the credential invariant for real, and the cost line in `status`

**Files:**
- Modify: `agent_on/qualify.py` (append `run_qualify`), `agent_on/invariants.py` (`credential.not_in_child_env`), `agent_on/status.py` (cost line + last session in the text view), `.github/workflows/ci.yml` (one assertion)
- Test: `tests/agent_on/test_qualify_run.py`; extend `tests/agent_on/test_invariants.py`; adjust `tests/agent_on/test_status.py` and `tests/agent_on/test_gate.py`

**Interfaces:**
- Consumes: Task 3–5 modules, `invariants.{build_context, evaluate, claude_code_version}`, `state.{read_observed, update_observed, resolve_secret}`, `schemas.observed.{compute_context, empty_route}`, `schemas.knowledge.validate_record`, `ids.ulid`, `paths.describe_copy`.
- Produces: `run_qualify(paths, name, *, baseline=False, limits=False, allow_paid=False, env=None, timeout=90.0, claude_bin=None) -> dict` with keys `command, copy, route, refused (str|None), gates{}, details{}, probes{throughput, concurrency, caching, limits|None}, baseline (int|None), fingerprint{}, written (bool), invariants[]`. `credential.not_in_child_env` becomes a real predicate: for every route it computes `harness.child_env` from a parent that carries a marker value for every source's `auth_env` and an inherited `ANTHROPIC_API_KEY`, and fails if any marker survives.

Rulings: a paid probe is one that runs Claude Code (`--baseline`, ~48K input tokens) or bisects the context (`--limits`, up to ~2× the limit in input tokens) on a source with an `auth_env`; both need `--allow-paid` and the estimate is printed first. The six gates and the three short probes on a keyed source cost well under a cent (spec §7) and run without the flag. `knowledge/qualifications.jsonl` is appended only when `knowledge/` exists (Plan C creates it); until then the record lives in `observed.json` only, and the doc says so.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_qualify_run.py`:

```python
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
            run_qualify(sb.paths, "a", limits=True, env={}, timeout=10)
            r = read_observed(sb.paths)["routes"]["mock/alpha"]
            self.assertEqual(r["cost_model"]["context_basis"], "declared")                    # verified ≥ declared: the cap stands

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


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/agent_on/test_invariants.py` a new class before `if __name__`:

```python
class CredentialTest(unittest.TestCase):
    def test_no_source_credential_reaches_any_route_child_env(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            r = one(sb.paths, "credential.not_in_child_env")
            self.assertEqual(r.result, "pass")
            self.assertIn("MOCK_PAID_KEY", r.reason)
```

and update the Plan A tests and CI assertion that assumed the honest skip — the predicate is real now:
- `tests/agent_on/test_invariants.py` `RegistryTest.test_a_skip_is_reported_as_skip_and_listed`: last assertion → `self.assertEqual([r.result for r in res if r.id == "credential.not_in_child_env"], ["pass"])`.
- `tests/agent_on/test_status.py` `test_check_writes_last_check_never_last_gate_run`: replace `self.assertIn("credential.not_in_child_env", obs["last_check"]["skipped"])` with `self.assertNotIn("credential.not_in_child_env", obs["last_check"]["skipped"])` followed by `self.assertIn("copy.single", obs["last_check"]["skipped"])`; and `self.assertIn("skip credential.not_in_child_env", text)` → `self.assertIn("pass credential.not_in_child_env", text)`.
- `tests/agent_on/test_gate.py` `test_gate_records_last_gate_run_with_skips_and_an_ephemeral_port`: replace `self.assertIn("credential.not_in_child_env", g["skipped"])` with `self.assertNotIn("credential.not_in_child_env", g["skipped"])` followed by `self.assertEqual(g["invariants"]["credential.not_in_child_env"], "pass")`.
- `.github/workflows/ci.yml`, the `agent-on` job's assertion step: replace `assert "credential.not_in_child_env" in g["last_gate_run"]["skipped"]` with `assert g["last_gate_run"]["invariants"]["credential.not_in_child_env"] == "pass"` (same indentation).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_qualify_run.py' -v; python3 -m unittest discover -s tests/agent_on -p 'test_invariants.py' -v`
Expected: `ImportError: cannot import name 'run_qualify'`; the credential test fails with `skip`.

- [ ] **Step 3: Write the code**

Append to `agent_on/qualify.py` (add these imports at its top: `import os`, `from .harness import run_launch`, `from .ids import ulid`, `from .invariants import build_context, claude_code_version, evaluate`, `from .paths import Paths, describe_copy`, `from .schemas.knowledge import validate_record`, `from .schemas.observed import compute_context, empty_route`, `from .schemas.routes import load_routes`, `from .sources import probe_source`, `from .state import read_observed, resolve_secret, update_observed`, `from .util import utc_now`):

```python
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
          "source_identity": probe.identity if probe.reachable else None, "claude_code": claude_code_version()}
    qual = {"pass": gates["all_pass"], "gates": gates["gates"], "thinking_block_seen": gates["thinking_block_seen"],
            "completed": gates["completed"], "at": now, "fingerprint": fp}
    base_tokens = None
    if baseline:
        launch = run_launch(paths, route.name, ["-p", BASELINE_PROMPT], env=parent, claude_bin=claude_bin, announce=False)
        first = (launch.get("last_session") or {}).get("first_request")
        base_tokens = first["input_tokens_total"] if first else None
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
    kdir = paths.checkout / "knowledge"
    if kdir.is_dir():                                                              # Plan C creates it; until then observed.json is the record
        record = {"id": f"qualifications-{ulid()}", "ts": now, "route": route.name, "fingerprint": fp, "gates": gates["gates"],
                  "thinking_block_seen": gates["thinking_block_seen"], "completed": gates["completed"], "tok_s": thr["tok_s"],
                  "concurrency": conc["concurrency"], "caching": cache["caching"], "commit": doc["copy"]["commit"]}
        validate_record("qualifications", record)
        with open(kdir / "qualifications.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        doc["knowledge"] = str(kdir / "qualifications.jsonl")
    doc["invariants"] = [r.as_dict() for r in evaluate(build_context(paths, with_claude_code=True), ids=["route.served", "qualification.current"], route=route.name)]
    return doc
```

`agent_on/invariants.py` — add `from .harness import child_env` to the imports and replace the `credential_not_in_child_env` body:

```python
@invariant("credential.not_in_child_env",
           statement="no source credential reaches the child environment of any route's launch",
           fix="the launcher must scrub every source's auth_env and the routing denylist before spawn (§11)")
def credential_not_in_child_env(ctx: Context):
    if ctx.routes is None:
        return skip(f"routes did not load: {ctx.routes_error}")
    markers = {src.auth_env: f"SECRET-{src.auth_env}" for src in ctx.routes.sources.values() if src.auth_env}
    parent = {**markers, "ANTHROPIC_API_KEY": "SECRET-inherited", "ANTHROPIC_AUTH_TOKEN": "SECRET-inherited", "PATH": "/usr/bin"}
    leaks: list[str] = []
    for route in ctx.routes.routes.values():
        env = child_env(parent, ctx.routes, route, context=None, config_dir=Path("/nonexistent"))
        leaks += [f"{route.name}:{k}" for k, v in env.items() if "SECRET-" in str(v)]
    if leaks:
        return fail(f"a credential reached the child environment: {leaks[:5]}")
    names = ", ".join(sorted(markers)) or "none declared"
    return ok(f"{len(ctx.routes.routes)} routes: no source credential ({names}) reaches the child environment")
```

`agent_on/status.py` — add `from .harness import cost_line` to the imports and, in `render_text`, right after the `lines.append(f"route {n}" …)` statement inside the routes loop:

```python
        if v["observed"]:
            lines.append("  " + cost_line(n, v["observed"]))
            ls = v["observed"].get("last_session")
            if ls:
                lines.append("  last session: " + (f"skipped ({ls['skipped']})" if "skipped" in ls else
                             f"{ls['id'][:8]} · this run {ls['this_run']['turns']} turns ${ls['this_run']['cost_usd']} · session {ls['session_total']['turns']} turns ${ls['session_total']['cost_usd']}"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: all pass. `schema.complete` still passes (`observed.qualification.shape` is raised literally).

- [ ] **Step 5: Commit**

```bash
git add agent_on/qualify.py agent_on/invariants.py agent_on/status.py .github/workflows/ci.yml tests/agent_on/test_qualify_run.py tests/agent_on/test_invariants.py tests/agent_on/test_status.py tests/agent_on/test_gate.py
git commit -m "feat(agent-on): run_qualify with fingerprint, baseline and limits; credential invariant made real; cost line in status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 7: The `launch` and `qualify` verbs and the `claude-on` shim

**Files:**
- Modify: `agent_on/cli.py`
- Create: `bin/claude-on`
- Test: `tests/agent_on/test_cli_launch.py`

**Interfaces:**
- Produces: `agent-on launch [--harness claude] [--discover] [--sonnet R] [--haiku R] [--dry-run] <route> [claude args…]` (everything after the route goes to Claude Code verbatim); `agent-on qualify <route> [--baseline] [--limits] [--allow-paid] [--timeout S]`; `bin/claude-on` = `agent-on launch --harness claude "$@"`. Exit codes: `launch` returns the child's exit status (0 for a dry run); `qualify` returns 0 when every gate passed, 1 otherwise (a refused paid probe is 1). In `--json` mode a real launch prints its envelope as **one line after the child's own stdout** (a consumer takes the last line); a dry run prints the indented envelope alone; the §12 cost line goes to stderr before spawning.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_cli_launch.py`:

```python
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from agent_on import cli  # noqa: E402
from agent_on.paths import default_paths  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

FAKE = str(REPO / "tests" / "agent_on" / "fakeclaude.py")


def first_route() -> str:
    table = load_routes(default_paths())
    return sorted(n for n, r in table.routes.items() if r.packaged)[0]   # derived, never a literal; packaged so a scratch state root knows it


class LaunchCliTest(unittest.TestCase):
    def test_parser_splits_launch_options_from_claude_args(self):
        p = cli.build_parser()
        a = p.parse_args(["launch", "--dry-run", "--haiku", "h", "some/route", "-p", "hi", "--model", "x"])
        self.assertEqual((a.command, a.route, a.dry_run, a.haiku, a.harness), ("launch", "some/route", True, "h", "claude"))
        self.assertEqual(a.claude_args, ["-p", "hi", "--model", "x"])
        q = p.parse_args(["qualify", "some/route", "--limits", "--allow-paid"])
        self.assertEqual((q.command, q.route, q.limits, q.allow_paid, q.baseline), ("qualify", "some/route", True, True, False))

    def test_dry_run_prints_the_plan_and_spawns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AGENT_ON_STATE": tmp, "FAKE_CLAUDE_OUT": tmp + "/out"}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--json", "launch", "--dry-run", first_route(), "-p", "hi"])
            self.assertEqual(code, 0)
            doc = json.loads(out.getvalue())
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["route"], first_route())
            self.assertIn("ANTHROPIC_BASE_URL", doc["env_keys"])
            self.assertFalse(Path(tmp, "out").exists())

    def test_shim_delegates_to_launch(self):
        shim = REPO / "bin" / "claude-on"
        self.assertTrue(shim.stat().st_mode & 0o111)
        self.assertLessEqual(len(shim.read_text().splitlines()), 20)
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([str(shim), "--json", "--dry-run", first_route(), "-p", "hi"], capture_output=True, text=True,
                                  env={**os.environ, "AGENT_ON_STATE": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["dry_run"])

    def test_real_launch_through_the_cli_returns_the_child_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AGENT_ON_STATE": tmp, "FAKE_CLAUDE_OUT": tmp + "/out", "FAKE_CLAUDE_EXIT": "4", "AGENT_ON_CLAUDE_BIN": FAKE}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--json", "launch", first_route(), "-p", "hi"])
            self.assertEqual(code, 4)
            doc = json.loads(out.getvalue().strip().splitlines()[-1])                 # the envelope is the last line; the child's stdout precedes it
            self.assertEqual(doc["exit_code"], 4)
            self.assertIn("last_session", doc)
            self.assertTrue(Path(tmp, "out", "env.json").exists())


if __name__ == "__main__":
    unittest.main()
```

The last test needs one small hook: `AGENT_ON_CLAUDE_BIN` names the binary the CLI launches (default `claude` on PATH). It exists for tests and for an operator who keeps several Claude Code versions; it is read by `cli.py`, not by `harness.run_launch` (which takes `claude_bin` explicitly).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_cli_launch.py' -v`
Expected: `argparse.ArgumentError`/`SystemExit: 2` (no `launch` verb), `FileNotFoundError` for the shim.

- [ ] **Step 3: Write the code**

`agent_on/cli.py` — in `build_parser`, after the `gate` parser:

```python
    l = sub.add_parser("launch", parents=[common], help="bind Claude Code to a route and run it; `claude-on <route>` is this verb (everything after the route goes to Claude Code)")
    l.add_argument("--harness", default="claude", choices=["claude"])
    l.add_argument("--discover", action="store_true", help="set CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1 (D8: off by default)")
    l.add_argument("--sonnet", metavar="ROUTE", help="bind the SONNET slot to another route on the same source")
    l.add_argument("--haiku", metavar="ROUTE", help="bind the HAIKU slot to another route on the same source")
    l.add_argument("--dry-run", action="store_true", help="print the environment keys, argv and cost line; spawn nothing")
    l.add_argument("route", help="a route name or alias")
    l.add_argument("claude_args", nargs=argparse.REMAINDER, help="passed to Claude Code unchanged")
    q = sub.add_parser("qualify", parents=[common], help="six fidelity gates + throughput/concurrency/caching/thinking probes; --baseline and --limits (paid sources need --allow-paid)")
    q.add_argument("route")
    q.add_argument("--baseline", action="store_true")
    q.add_argument("--limits", action="store_true")
    q.add_argument("--allow-paid", action="store_true")
    q.add_argument("--timeout", type=float, default=90.0)
```

new renderers (after `render_gate`):

```python
def render_launch(doc: dict) -> str:
    lines = [copy_line(doc["copy"]), doc["cost_line"]]
    lines += [f"warning: {w}" for w in doc["warnings"]]
    if doc.get("dry_run"):
        lines.append("dry run — argv: " + " ".join(doc["argv"]))
        lines.append("env: " + ", ".join(doc["env_keys"]))
        return "\n".join(lines + invariant_lines(doc["invariants"]))
    ls = doc.get("last_session") or {}
    lines.append(f"exit {doc['exit_code']} · session {doc['session']['id'] or '?'} ({doc['session']['mode']})")
    if "skipped" in ls:
        lines.append(f"read-back skipped: {ls['skipped']}")
    elif ls:
        lines.append(f"this run: {ls['this_run']['turns']} turns, ${ls['this_run']['cost_usd']} · session: {ls['session_total']['turns']} turns, ${ls['session_total']['cost_usd']}")
    return "\n".join(lines)


def render_qualify(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    if doc["refused"]:
        return "\n".join(lines + [f"refused: {doc['refused']}"])
    lines += [f"  {'pass' if ok else 'FAIL'} {g}" for g, ok in doc["gates"].items()]
    p = doc["probes"]
    lines.append(f"tok/s {p['throughput']['tok_s'] and round(p['throughput']['tok_s'])} · concurrency {p['concurrency']['concurrency']} (pair/serial {p['concurrency']['ratio']})"
                 f" · caching {p['caching']['caching']} (cache_read {p['caching']['cache_read_second']})")
    if doc["baseline"] is not None:
        lines.append(f"harness baseline: {doc['baseline']} input tokens")
    if p.get("limits"):
        lines.append(f"verified input limit: {p['limits']['verified']} ({len(p['limits']['probes'])} probes)")
    lines.append("fingerprint: " + json.dumps(doc["fingerprint"], sort_keys=True))
    return "\n".join(lines + invariant_lines(doc["invariants"]))
```

and in `main`, before the final `else:` (gate):

```python
        elif args.command == "launch":
            from .harness import run_launch
            doc = run_launch(paths, args.route, args.claude_args, harness=args.harness, discover=args.discover, sonnet=args.sonnet,
                             haiku=args.haiku, dry_run=args.dry_run, claude_bin=os.environ.get("AGENT_ON_CLAUDE_BIN"))
            code = 0 if args.dry_run else int(doc["exit_code"])
            text = render_launch(doc)
        elif args.command == "qualify":
            from .qualify import run_qualify
            doc = run_qualify(paths, args.route, baseline=args.baseline, limits=args.limits, allow_paid=args.allow_paid, timeout=args.timeout,
                              claude_bin=os.environ.get("AGENT_ON_CLAUDE_BIN"))
            code = EXIT_OK if doc["written"] and all(doc["gates"].values()) else EXIT_FAIL
            text = render_qualify(doc)
```

and replace `main`'s final print statement — the landed line `print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) if args.json else text)` — with:

```python
    if args.json and args.command == "launch" and not getattr(args, "dry_run", False):
        print("\n" + json.dumps(doc, sort_keys=True, ensure_ascii=False))          # one line after the child's own stdout: take the last line
    else:
        print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) if args.json else text)
```

(add `import os` to `cli.py`; a `ValueError` from a cross-source `--sonnet` already lands in the `(OSError, ValueError)` envelope with exit 1).

`bin/claude-on` (then `chmod +x bin/claude-on`):

```zsh
#!/usr/bin/env zsh
# claude-on <route> [claude args…] — the Claude Code launcher shim (spec rev 8): agent-on launch --harness claude.
# Launch options (--discover, --sonnet, --haiku, --dry-run, --json) go before the route; everything after it is Claude Code's.
set -u
exec "${0:A:h}/agent-on" launch --harness claude "$@"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -W error::ResourceWarning -m unittest discover -s tests/agent_on -p 'test_*.py'`
Expected: all pass; the last test spawns the fake binary through the real CLI and returns 4.

- [ ] **Step 5: Commit**

```bash
git add agent_on/cli.py bin/claude-on tests/agent_on/test_cli_launch.py
git commit -m "feat(agent-on): launch and qualify verbs; claude-on shim

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 8: Acceptance on the real machine (§14 row B), S2, README

**Files:**
- Modify: `README.md` (append)
- No code changes unless a step exposes a defect (then a fix with a test, its own commit, stated in the report).

Run in order from the checkout; put each step's observed output in the report and the measured numbers in the final commit message. The state root is the real one (`~/.local/state/agent-on`, key already in `$STATE/env`). oMLX on `:8000` must be running (read-only use); OpenRouter steps cost cents and are marked.

- [ ] **Step 1: Dry run and the credential contract, offline**

```bash
./bin/claude-on --dry-run huihui -p 'Reply with exactly: OK'
./bin/claude-on --json --dry-run glm -p x | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["argv"][:3], sorted(k for k in d["env_keys"]))'
./bin/agent-on status --check | grep credential
```

Expected: the cost line for `omlx/root4k--Huihui…` (`ctx 131072 · ? tok/s · $0 · cache ? · concurrency ? · thinking ?` — nothing qualified yet), `argv` beginning `claude --settings <run-dir>/settings.json`, `env_keys` without any `*_API_KEY`; `pass credential.not_in_child_env: 16 routes: no source credential (OPENROUTER_API_KEY) reaches the child environment`.

- [ ] **Step 2: The free lane, for real (oMLX)**

```bash
./bin/claude-on huihui -p 'Reply with exactly: OK'; echo "exit $?"
./bin/claude-on huihui -p 'Use the Read tool to read README.md in this directory and reply with only its first heading line.'; echo "exit $?"
./bin/agent-on status huihui --json | python3 -c 'import json,sys; r=json.load(sys.stdin)["routes"]; v=next(iter(r.values())); ls=v["observed"]["last_session"]; print(ls["id"], ls["first_request"]["input_tokens_total"], ls["this_run"], ls["claude_code"])'
ls ~/.local/state/agent-on/sessions/ | tail -2; ls ~/.local/state/agent-on/run/
```

Expected: `OK` printed and exit 0 (a `-p` on Huihui takes 2–3 minutes: the ~50K-token harness prefill on a 27B model — 53,844 input tokens were read back on 2026-09-08 from this checkout; Claude Code also prints an `unrecognized_model` notice for any model its catalog does not know — harmless, the launcher's `CLAUDE_CODE_MAX_CONTEXT_TOKENS` is what keeps its window right); the second run prints the README's first heading (a Read-tool loop completed on the direct wire — the S1 result, now through the launcher); `last_session.first_request.input_tokens_total` in the tens of thousands (the harness baseline shape; 48,312 was measured on 2.1.263), `this_run.cost_usd == 0.0`, `claude_code == "2.1.263"`; one ledger file per session; `run/` empty after exit.

- [ ] **Step 3: Qualify the free route, with baseline and limits**

```bash
./bin/agent-on qualify huihui; echo "exit $?"
./bin/agent-on qualify huihui --baseline --limits; echo "exit $?"
./bin/agent-on status huihui | sed -n '1,8p'
```

Expected: six `pass` lines (S1 measured 6/6 on this model); `tok/s` around 50–65 and `concurrency 1` (Huihui gains nothing at 2 — measured 2026-09-08), `caching True` (real session showed `cache_read 20,480`) or `False` — either is a measurement; `thinking on`; `harness baseline: ~48K`; `verified input limit` near 131072 (oMLX enforces `max_context_window`); the status line now shows `ctx 131072 (48xxx baseline = 37%) · … · thinking on`; `qualification.current` passes. Exit 0 both times.

- [ ] **Step 4: The paid lane (OpenRouter, cents)**

```bash
./bin/agent-on qualify glm; echo "exit $?"                                 # six gates + short probes: < $0.01
./bin/agent-on qualify glm --baseline --allow-paid; echo "exit $?"         # one Claude Code -p run: ~48K input ≈ $0.05
./bin/claude-on glm -p 'Reply with exactly: OK'; echo "exit $?"
./bin/agent-on status glm --json | python3 -c 'import json,sys; v=next(iter(json.load(sys.stdin)["routes"].values()))["observed"]; print(v["cost_model"]["caching"], v["last_session"]["this_run"]["cost_usd"], v["last_session"]["session_total"]["cost_usd"])'
```

Expected: gates pass (30/30 direct on 2026-08-20; `[thinking, text]` on 2026-09-07); `caching` recorded as `true` or `false` — **never inferred**: if the second probe reply shows no cache reads it is `false` and that is the finding; the `-p` session's `cost_usd` is a number (all four price fields present? GLM publishes no cache-write price — if the first request carries `cache_creation_input_tokens`, the run is `"unknown"` with the reason; record whichever happened).

- [ ] **Step 5: The credential contract with the real binary (cents)**

```bash
./bin/claude-on glm -p 'Run the shell command `printenv` and reply with only the names of any variables among OPENROUTER_API_KEY, ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN that are present, or the word NONE.' --allowedTools 'Bash(printenv)'; echo "exit $?"
( unset OPENROUTER_API_KEY; ./bin/claude-on glm -p 'Reply with exactly: OK' ); echo "exit $?"               # key only in $STATE/env
mv ~/.local/state/agent-on/env /tmp/agent-on-env.bak; OPENROUTER_API_KEY="$(security find-generic-password -s openrouter-api-key -a rick -w)" ./bin/claude-on glm -p 'Reply with exactly: OK'; echo "exit $?"; mv /tmp/agent-on-env.bak ~/.local/state/agent-on/env   # key only in the environment
```

Expected: `NONE` (the model's own `printenv` finds no key — §1.1c closed on the direct wire), then `OK` twice: the key reached the helper from the file alone and from the environment alone (the rev-4 P1). Never print the key.

- [ ] **Step 6: S2 — an in-session model switch is process-global**

```bash
./bin/claude-on huihui --model Qwen3.8-27B-Uncensored-8bit -p 'Reply with exactly: OK'; echo "exit $?"
./bin/agent-on status huihui --json | python3 -c 'import json,sys; v=next(iter(json.load(sys.stdin)["routes"].values()))["observed"]["last_session"]; print(v["this_run"]["models_seen"], v["this_run"]["cost_usd"])'
```

Expected: `models_seen` names the other oMLX model; `cost_usd` `0.0` because both are priced (free) on the same source; `CLAUDE_CODE_MAX_CONTEXT_TOKENS` stayed the launch route's 131072 (the same on both routes today, so nothing breaks — record the observation: the budget is process-global, a `--model` switch to a route with a different context would keep the launch route's cap; the launcher prints no warning today — note it for Plan C's traps).

- [ ] **Step 7: Everything still true**

```bash
./bin/agent-on status --check | tail -3; ./bin/agent-on gate | tail -2
claude-litellm status 2>&1 | head -3
```

Expected: `last_check: pass`, gate `pass` (the old launcher's `status` still answers; its proxy is stopped by the owner's decision).

- [ ] **Step 8: README**

Append to `README.md`, after the Plan A section:

```markdown
### Launching (Plan B)

    ./bin/claude-on huihui                       # Claude Code on the local oMLX route; the cost line prints first
    ./bin/claude-on glm -p 'Reply with exactly: OK'
    ./bin/claude-on --dry-run glm                # show the environment keys and argv, spawn nothing
    ./bin/agent-on qualify huihui --baseline --limits
    ./bin/agent-on qualify glm                   # six gates + probes on a paid route: under a cent; --baseline/--limits need --allow-paid

The source key never enters Claude Code's environment: the launcher writes it to a per-launch 0600 file and hands
Claude Code an `apiKeyHelper` that reads it; every source's key variable and the routing denylist are removed
from the child. After exit the session transcript is read back into `status` (`last_session`) and the per-session
ledger under `$STATE/sessions/` — costs are attributed per run at the price snapshotted at launch, and `"unknown"`
where a turn's price cannot be restored. `claude-litellm` is untouched until Plan D.
```

- [ ] **Step 9: Commit with the measurements**

```bash
git add README.md
git commit -m "docs: agent-on Plan B acceptance — measured on <date>

huihui: -p OK exit 0; Read-tool loop exit 0; first_request <N> tokens; qualify 6/6, <tok/s> tok/s,
concurrency <1|2>, caching <true|false>, thinking on (~<n> tok/probe), baseline <N>, verified <N>.
glm: qualify 6/6, caching <true|false>, baseline <N> ($<x>); -p OK cost $<y>|unknown (<reason>).
credential: printenv → NONE; key from $STATE/env alone OK; key from environment alone OK.
S2: --model switch recorded in models_seen; context is process-global (noted for Plan C traps).
status --check pass; gate pass; claude-litellm status unaffected.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

Replace every `<…>` with the observed value. If a step's expectation does not hold, the fix and its test go in this task's series and the deviation is stated.

---

## Self-review

**Spec coverage — §14 row B verify column and §9/§11/§12:**

| requirement | task |
|---|---|
| `credential.not_in_child_env` passes with the key only in the environment and, separately, only in `$STATE/env` (child `printenv` empty) | 4 (fake binary: `env.json` + `helper_key.txt`), 6 (the predicate), 8 step 5 (real binary) |
| parent-resolved key file + helper; every `auth_env` scrubbed; keyless placeholder (§11 item 2, D2 ⟲⟲) | 3, 4 |
| config-dir isolation with the shared symlink farm and project trust (§11 item 1) | 3 |
| tier slots + subagent slot bound to the route, `--sonnet`/`--haiku` same-source (D7); `CLAUDE_CODE_MAX_CONTEXT_TOKENS` from `cost_model.context`; discovery opt-in (D8); attribution header off | 3 |
| session rules `--session-id`/`--resume`/`--continue`/`--no-session-persistence`; read-back best-effort (§9) | 3 (`session_args`, `find_transcript`), 4 |
| `first_request`/`this_run`/`session_total`, per-run ledger, `unknown` rule, F11 never read (§11 item 4) | 3 (`read_transcript`, `record_session` over Plan A's `cost.py`) |
| `run/<launch-id>/` 0600, removed on exit, dead-pid sweep (§7.1) | 3, 4 |
| the §12 cost line before spawning; `?` never invented | 3 (`cost_line`), 4 |
| `huihui` launch completes a Read-tool loop | 8 step 2 |
| `harness_baseline_tokens` by `qualify --baseline` with the fixed prompt | 6, 8 step 3 |
| six gates direct per packaged OpenRouter route; two-turn cache probe records true/false, never inferred | 5, 6, 8 steps 3–4 |
| `verified` only from `qualify --limits`; context = min(declared, verified) (§7) | 5 (`probe_limits`), 6 (`compute_context` re-run) |
| fingerprint `{effective_route_sha, wire_model, source_identity, claude_code}` and `qualification.current` | 5 (schema), 6 |
| S2 measured | 8 step 6 |
| both launchers coexist; `claude-litellm` still launches | 8 step 7 |
| `claude-on <route>` = `agent-on launch --harness claude` (rev 8) | 7 |

Deferred by design: `knowledge/qualifications.jsonl` is written only once `knowledge/` exists (Plan C); the `sonnet[1m]` tier-alias minor from Plan A's ledger belongs to the harness lint and stays deferred; no `--task <id>` injection yet (§10.1, Plan C).

**Placeholder scan:** none; the `<…>` tokens are only in Task 8's commit template.

**Type consistency:** `run_launch` returns `exit_code` only for real launches and `argv` only for dry runs — `cli.main` reads them accordingly; `record_session` takes `launch["price"]` and `launch["priced_models"]` exactly as `run_launch` builds them and as `cost.attribute_run` expects (`price`, `priced_models`); `Wire.post` prepends `model` so probes pass payloads without it; `MockSource.fail_gates` names equal `qualify.GATES` plus `thinking`; `harness.FREE` and `sync.FREE` are the same literal; `observed.QUALIFICATION_KEYS` matches the record `run_qualify` writes; `invariants` imports `harness` and `harness` imports neither `invariants` nor `status` nor `cli` (no cycle); `status` imports `harness.cost_line` and `cli` imports `status` lazily.
