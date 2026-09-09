# agent-on Plan F — `codex-on`: the second harness on the Responses wire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `codex-on <route>` runs Codex CLI on any route through the OpenAI Responses wire with the key in a per-launch config file, `qualify --wire responses` measures that wire with six gate analogues, and `observed.json` keys qualifications by wire and baselines by harness — without the tower (L0–L5) learning which harness asked.

**Architecture:** One schema bump (observed v2, upgraded in memory on read), one new mock endpoint (`/v1/responses`), one new gate set in `qualify.py` selected by `--wire`, one harness-agnostic prologue/epilogue extracted from `run_launch`, and one new file `agent_on/harness_codex.py` that builds the per-launch `CODEX_HOME` (symlinks to the operator's `~/.codex` items plus a 0600 profile file carrying the provider and key), spawns `codex --profile agent-on …`, and reads the rollout back into the same `last_session` shape. A fake Codex binary mirrors `fakeclaude.py` so every launch test stays offline. Measured facts from spikes S6–S8 (2026-09-09) fix every value below.

**Tech Stack:** Python ≥ 3.11 standard library (`tomllib` for reading, hand-written TOML for the profile file); zsh shims; Codex CLI 0.153.4 (`codex exec`, `--profile`, `CODEX_HOME`).

**Spec:** `docs/superpowers/specs/2026-09-07-agent-on-design.md` rev 9 — D14, §7.2, §8.1, §9 (rev 9 additions), §11.1, §14 row F. Plans A–D are landed context; their ledgers hold inherited rulings.

## Global Constraints

- **D4** Python ≥ 3.11 stdlib only; run suites with `/opt/homebrew/bin/python3.13`; zsh shims ≤ 20 lines.
- **D14** The Codex key travels only in the per-launch 0600 profile file under `$STATE/run/<launch-id>/codex-home/`; never `env_key`, never the environment, never the command line (a `-c` override would show in `ps`). The directory is removed when the child exits; the run-dir sweep covers a crash.
- **§7.2** `observed.version` is 2; a v1 file is upgraded in memory by `read_observed` and written as v2 by the next `update_observed`; nothing else migrates on disk. Field names: `qualifications.<wire>`, `harness_baseline_tokens.<harness>`, `last_session.harness` / `harness_version`, fingerprint `harness_version`.
- **§8.1** Responses-wire gate names and pass conditions exactly as the spec table; every probe uses `max_output_tokens` 512; SSE readers skip non-`data:` lines.
- **§11.1** The tower never learns the harness: `harness_codex.py` reuses the same prologue, scrub (`child_env`), price snapshot, task handoff, ledger line and observation write as the Claude binding; only home isolation, argv and the rollout reader differ.
- **D5** one home per fact: `WIRES`, `HARNESSES`, `WIRE_OF` live in `agent_on/schemas/observed.py`; the gate names live in `qualify.py`; the mock's fail-gate names are imported from there.
- **D6** traps and qualifications inform, never gate; a launch proceeds on a stale or failed qualification.
- **Plan B/C/D rulings that bind:** tests use only `Sandbox`, `MockSource`, `fakeclaude.py` and the new `fakecodex.py` — never the real home, `~/.codex`, oMLX, OpenRouter, `claude` or `codex`; secrets never reach stdout/JSON/knowledge/rollouts; JSON envelopes only gain keys; `observed.json` only via `update_observed`; `knowledge/` append-only; do not run `gate`/`qualify`/`claude-on`/`codex-on`/`learn` against the real checkout from a task (they append to the real `knowledge/`) — the acceptance task does.
- **Commit trailers** on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD
  ```

---

## File structure

| path | responsibility |
|---|---|
| `agent_on/schemas/observed.py` | v2 shape, `WIRES`, `HARNESSES`, `WIRE_OF`, `migrate_observed`, validators |
| `agent_on/state.py` | `read_observed` calls `migrate_observed` |
| `agent_on/invariants.py` | `qualification.current` per wire; `codex_version()`; `Context.codex_version` |
| `agent_on/status.py` | one `qualified[<wire>]` line per wire |
| `agent_on/harness.py` | `cost_line(…, harness)`, `record_session(…)` taking a parsed transcript, `child_env(…, harness)`, `_prologue`/`_epilogue` extracted from `run_launch`, dispatch to codex |
| `agent_on/mock_source.py` | `/v1/responses` JSON + SSE; `RESPONSES_GATE_NAMES`; fail gates and quirks for the new wire |
| `agent_on/qualify.py` | `Wire(…, wire=)`, request builders per wire, `GATES_RESPONSES`, `run_gates_responses`, probes per wire, `run_qualify(…, wire=)` |
| `agent_on/harness_codex.py` | **new** — `prepare_codex_home`, `write_profile`, `read_rollout`, `run_launch_codex`, `codex_version` |
| `agent_on/install.py` | `SHIMS` gains `codex-on` |
| `agent_on/cli.py` | `launch --harness codex`, `qualify --wire`, renderers |
| `bin/codex-on` | **new** shim |
| `tests/agent_on/fakecodex.py` | **new** fake Codex binary |
| tests | `test_observed_v2.py`, `test_mock_responses.py`, `test_qualify_responses.py`, `test_harness_codex.py`; edits in `test_invariants.py`, `test_status.py`, `test_qualify.py`, `test_qualify_run.py`, `test_harness_env.py`, `test_harness_launch.py`, `test_install.py`, `test_cli_launch.py`, `test_knowledge_seeds.py` |
| `README.md`, `.claude/skills/agent-on/SKILL.md`, `docs/superpowers/specs/…` (§9 one word) | docs |

---

### Task 1: `observed.json` version 2 — qualifications by wire, baselines by harness, sessions by harness

**Files:**
- Modify: `agent_on/schemas/observed.py`, `agent_on/state.py`, `agent_on/qualify.py` (the `mutate` block and the fingerprint), `agent_on/invariants.py` (`qualification_current`, `claude_code_version` sibling `codex_version`, `Context`), `agent_on/status.py`, `agent_on/harness.py` (`cost_line`, `record_session`), `agent_on/schemas/knowledge.py` (qualifications `wire`), `agent_on/schemas/errors.py` (rule text)
- Test: `tests/agent_on/test_observed_v2.py`; edits in `test_invariants.py`, `test_status.py`, `test_qualify_run.py`, `test_harness_env.py`, `test_harness_launch.py`, `test_qualify.py`

**Interfaces:**
- Produces in `schemas/observed.py`:
  ```python
  OBSERVED_VERSION = 2
  WIRES = ("messages", "responses")
  HARNESSES = ("claude", "codex")
  WIRE_OF = {"claude": "messages", "codex": "responses"}
  HARNESS_OF = {"messages": "claude", "responses": "codex"}
  SESSION_KEYS = ("id", "at", "first_request", "this_run", "session_total", "scope_note", "duration_ms", "effort", "permission_mode", "harness", "harness_version")
  QUALIFICATION_KEYS = ("pass", "gates", "thinking_block_seen", "completed", "at", "fingerprint", "wire")
  FINGERPRINT_KEYS = ("effective_route_sha", "wire_model", "source_identity", "harness_version")
  BASELINE_KEYS = ("value", "measured_by", "harness_version", "at")
  ```
  `empty_route()` has `"qualifications": {}` instead of `last_qualification`; `empty_cost_model()["harness_baseline_tokens"]` is `{}`. `migrate_observed(doc) -> dict` upgrades v1 → v2 in place and returns it; `validate_route` validates every `qualifications[wire]` (wire ∈ `WIRES`, keys, fingerprint, gates dict of bools, `record["wire"] == wire`), every `harness_baseline_tokens[harness]` (harness ∈ `HARNESSES`, `BASELINE_KEYS`), and `last_session.harness ∈ HARNESSES`.
- `state.read_observed` runs `migrate_observed` before `validate_observed`.
- `harness.cost_line(route_name, observed_route, harness="claude")` shows that harness's baseline as today, and when other harnesses have one, appends them: `ctx 131072 (claude 54380 = 41% · codex 6859 = 5%)`.
- `harness.record_session(paths, launch, *, ended, transcript: dict | None, mode, harness: str, harness_version: str | None)` — takes the **parsed** transcript (`{"session_id", "turns", "first_request", "effort", "permission_mode"}`) or `None`; the Claude caller parses with `read_transcript(path)` first; a `None` transcript records `{"skipped": …}` as before. The record gains `harness` and `harness_version` (Claude: `t["version"]`).
- `invariants.codex_version(binary=None)` — `codex --version` → `codex-cli 0.153.4` → `"0.153.4"`; `Context` gains `codex_version: str | None` (filled with `with_claude_code=True`, same flag). `qualification_current` evaluates every wire in `qualifications`: `skip("never qualified")` when empty; per wire compares `effective_route_sha`, `wire_model`, `source_identity`, and `harness_version` against `ctx.claude_code` for `messages` / `ctx.codex_version` for `responses`; result `fail` naming `<wire>: stale [fields]` for any stale wire, else `ok` listing `<wire>: current` per wire.
- `status.render_text`: after the cost line, one line per wire in `WIRES` order: `qualified[messages] ✓ <at>` / `qualified[responses] ✗ <at> (<failed gates>)`; `qualified: never` when the map is empty.
- `qualify.run_qualify` writes `r["qualifications"]["messages"] = {**qual, "wire": "messages"}` with fingerprint `harness_version` (from `claude_code_version`), and `cm["harness_baseline_tokens"]["claude"] = {value, measured_by, harness_version, at}`; the knowledge twin gains `"wire": "messages"`. `schemas/knowledge.py`: `validate_record("qualifications", …)` accepts a missing `wire` (old seeds/records) and rejects a `wire` outside `WIRES`.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_observed_v2.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import (OBSERVED_VERSION, empty_observed, empty_route, migrate_observed,  # noqa: E402
                                       validate_observed)
from agent_on.state import read_observed, update_observed  # noqa: E402

BASE = "http://127.0.0.1:1"
V1_ROUTE = {"served": True, "checked": "2026-09-08T00:00:00Z",
            "limits": {"input": {"configured": 131072, "advertised": None, "verified": None, "checked": None},
                       "output": {"configured": None, "advertised": None, "verified": None, "checked": None}},
            "cost_model": {"context": 131072, "context_basis": "declared", "tok_s": 50.0, "usd_per_mtok": None, "caching": True,
                           "concurrency": 1, "thinking": None, "checked": "2026-09-08T00:00:00Z",
                           "harness_baseline_tokens": {"value": 54380, "measured_by": "qualify --baseline", "claude_code": "2.1.263", "at": "2026-09-08T00:00:00Z"}},
            "last_qualification": {"pass": True, "gates": {"text_sse": True}, "thinking_block_seen": False, "completed": True, "at": "2026-09-08T00:00:00Z",
                                   "fingerprint": {"effective_route_sha": "abc", "wire_model": "alpha", "source_identity": None, "claude_code": "2.1.263"}},
            "last_session": {"id": "s1", "at": "2026-09-08T00:00:00Z", "first_request": None,
                             "this_run": {"turns": 1, "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "cost_usd": 0.0, "models_seen": ["alpha"]},
                             "session_total": {"turns": 1, "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "cost_usd": 0.0, "covered_turns": 1, "uncovered_turns": 0},
                             "scope_note": "fresh", "duration_ms": 10, "effort": None, "permission_mode": None, "claude_code": "2.1.263"}}


def v1_doc() -> dict:
    d = empty_observed()
    d["version"] = 1
    d["routes"]["mock/alpha"] = json.loads(json.dumps(V1_ROUTE))
    return d


class MigrationTest(unittest.TestCase):
    def test_v1_upgrades_in_memory_and_is_written_back_as_v2(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir(parents=True)
            sb.paths.observed_json.write_text(json.dumps(v1_doc()), encoding="utf-8")
            doc = read_observed(sb.paths)
            self.assertEqual(doc["version"], OBSERVED_VERSION)
            r = doc["routes"]["mock/alpha"]
            self.assertNotIn("last_qualification", r)
            q = r["qualifications"]["messages"]
            self.assertEqual(q["wire"], "messages")
            self.assertEqual(q["fingerprint"]["harness_version"], "2.1.263")
            self.assertNotIn("claude_code", q["fingerprint"])
            b = r["cost_model"]["harness_baseline_tokens"]
            self.assertEqual(b, {"claude": {"value": 54380, "measured_by": "qualify --baseline", "harness_version": "2.1.263", "at": "2026-09-08T00:00:00Z"}})
            ls = r["last_session"]
            self.assertEqual((ls["harness"], ls["harness_version"]), ("claude", "2.1.263"))
            self.assertNotIn("claude_code", ls)
            self.assertEqual(json.loads(sb.paths.observed_json.read_text())["version"], 1)             # read alone rewrites nothing
            update_observed(sb.paths, lambda d: None)
            self.assertEqual(json.loads(sb.paths.observed_json.read_text())["version"], 2)

    def test_migrate_is_idempotent_and_v2_validates(self):
        d = migrate_observed(v1_doc())
        again = migrate_observed(json.loads(json.dumps(d)))
        self.assertEqual(d, again)
        validate_observed(d)

    def test_v2_rejects_an_unknown_wire_or_harness(self):
        d = migrate_observed(v1_doc())
        r = d["routes"]["mock/alpha"]
        r["qualifications"]["chat"] = dict(r["qualifications"]["messages"], wire="chat")
        with self.assertRaises(SchemaError):
            validate_observed(d)
        del r["qualifications"]["chat"]
        r["cost_model"]["harness_baseline_tokens"]["goose"] = r["cost_model"]["harness_baseline_tokens"]["claude"]
        with self.assertRaises(SchemaError):
            validate_observed(d)
        del r["cost_model"]["harness_baseline_tokens"]["goose"]
        r["qualifications"]["responses"] = dict(r["qualifications"]["messages"], wire="messages")            # wire must equal its key
        with self.assertRaises(SchemaError):
            validate_observed(d)

    def test_empty_route_is_v2_shaped(self):
        r = empty_route()
        self.assertEqual(r["qualifications"], {})
        self.assertEqual(r["cost_model"]["harness_baseline_tokens"], {})
        self.assertNotIn("last_qualification", r)


if __name__ == "__main__":
    unittest.main()
```

Test edits (each names the exact assertion to change):
- `tests/agent_on/test_invariants.py`: every planted `last_qualification` record → `"qualifications": {"messages": {…, "wire": "messages", "fingerprint": {…, "harness_version": …}}}` (the fingerprint key `claude_code` → `harness_version`); the `qualification.current` stale test expects the reason to contain `messages: stale` and `effective_route_sha`.
- `tests/agent_on/test_status.py`: `last_qualification` plants → `qualifications.messages`; text needles `qualified ✓` → `qualified[messages] ✓`, `qualified ✗` → `qualified[messages] ✗`; `qualified: never` unchanged.
- `tests/agent_on/test_qualify_run.py`: `obs["last_qualification"]` → `obs["qualifications"]["messages"]`; `q["fingerprint"]["claude_code"]` → `["harness_version"]`; `cm["harness_baseline_tokens"]` → `cm["harness_baseline_tokens"].get("claude")` (None before `--baseline`, a `BASELINE_KEYS` dict after); `launch["last_session"]["claude_code"]` → `["harness_version"]` and `["harness"] == "claude"`.
- `tests/agent_on/test_harness_env.py` / `test_harness_launch.py`: `rec["claude_code"]` → `rec["harness_version"]`, plus `rec["harness"] == "claude"`; `cost_line` tests that plant `harness_baseline_tokens` as a flat record → `{"claude": {...}}` and expect `(claude 48312 baseline = 37%)`; add one assertion that two harnesses render `(claude 54380 = 41% · codex 6859 = 5%)`.
- `tests/agent_on/test_qualify.py`: `empty_route()` planted docs → v2 keys.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_observed_v2.py' -v`
Expected: `ImportError: cannot import name 'migrate_observed'`.

- [ ] **Step 3: Write the code**

`agent_on/schemas/observed.py` — constants as in Interfaces; `empty_route`/`empty_cost_model` as stated; then:

```python
def migrate_observed(doc: dict) -> dict:
    """v1 → v2 in place (§7.2): qualifications keyed by wire, baselines by harness, sessions carry the harness.
    Idempotent; a v2 document is returned untouched."""
    if not isinstance(doc, dict) or doc.get("version") != 1:
        return doc
    for r in (doc.get("routes") or {}).values():
        q = r.pop("last_qualification", None)
        r.setdefault("qualifications", {})
        if q:
            fp = dict(q.get("fingerprint") or {})
            fp["harness_version"] = fp.pop("claude_code", None)
            r["qualifications"]["messages"] = {**q, "wire": "messages", "fingerprint": fp}
        cm = r.get("cost_model") or {}
        hb = cm.get("harness_baseline_tokens")
        if isinstance(hb, dict) and "value" in hb:                                 # the flat v1 record
            cm["harness_baseline_tokens"] = {"claude": {"value": hb.get("value"), "measured_by": hb.get("measured_by"),
                                                         "harness_version": hb.get("claude_code"), "at": hb.get("at")}}
        elif hb is None:
            cm["harness_baseline_tokens"] = {}
        ls = r.get("last_session")
        if isinstance(ls, dict) and "skipped" not in ls:
            ls.setdefault("harness", "claude")
            ls["harness_version"] = ls.pop("claude_code", ls.get("harness_version"))
    doc["version"] = 2
    return doc
```

`validate_route` additions:

```python
    qs = r["qualifications"]
    if not isinstance(qs, dict):
        raise SchemaError("observed.qualification.shape", f"{where}.qualifications must be an object keyed by wire")
    for wire, q in qs.items():
        if wire not in WIRES:
            raise SchemaError("observed.qualification.shape", f"{where}.qualifications.{wire}: unknown wire; wires: {WIRES}")
        _require_keys(q, QUALIFICATION_KEYS, f"{where}.qualifications.{wire}", "observed.qualification.shape")
        _require_keys(q["fingerprint"], FINGERPRINT_KEYS, f"{where}.qualifications.{wire}.fingerprint", "observed.qualification.shape")
        if q["wire"] != wire:
            raise SchemaError("observed.qualification.shape", f"{where}.qualifications.{wire}.wire must be {wire!r}")
        if not isinstance(q["gates"], dict) or not all(isinstance(v, bool) for v in q["gates"].values()):
            raise SchemaError("observed.qualification.shape", f"{where}.qualifications.{wire}.gates must map gate names to booleans")
    hb = r["cost_model"]["harness_baseline_tokens"]
    if not isinstance(hb, dict):
        raise SchemaError("observed.route.shape", f"{where}.cost_model.harness_baseline_tokens must be an object keyed by harness")
    for h, b in hb.items():
        if h not in HARNESSES:
            raise SchemaError("observed.route.shape", f"{where}.cost_model.harness_baseline_tokens.{h}: unknown harness; harnesses: {HARNESSES}")
        _require_keys(b, BASELINE_KEYS, f"{where}.cost_model.harness_baseline_tokens.{h}", "observed.route.shape")
```

and in `validate_session`, after the key check: `if s["harness"] not in HARNESSES: raise SchemaError("observed.session.shape", f"{where}.harness must be one of {HARNESSES}")`. Remove the old `last_qualification` block. `state.read_observed`: `doc = migrate_observed(doc)` before `validate_observed(doc)`.

`agent_on/invariants.py`:

```python
def codex_version(binary: str | None = None) -> str | None:
    """`codex --version` prints `codex-cli 0.153.4`; the launch's own binary when given (AGENT_ON_CODEX_BIN)."""
    exe = binary or shutil.which("codex")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None
```

`Context` gains `codex_version: str | None`; `build_context(..., with_claude_code=False, claude_bin=None, codex_bin=None)` fills it alongside `claude_code`. `qualification_current`:

```python
def qualification_current(ctx: Context, route):
    r = ctx.observed["routes"].get(route.name)
    qs = (r or {}).get("qualifications") or {}
    if not qs:
        return skip("never qualified")
    versions = {"messages": ctx.claude_code, "responses": ctx.codex_version}
    stale, current = [], []
    for wire, q in sorted(qs.items()):
        fp = q.get("fingerprint") or {}
        now = {"effective_route_sha": ctx.routes.effective_sha(route), "wire_model": route.wire_model,
               "source_identity": (ctx.observed["sources"].get(route.source) or {}).get("identity"), "harness_version": versions.get(wire)}
        bad = [k for k, v in now.items() if v is not None and fp.get(k) != v]
        (stale if bad else current).append(f"{wire}: {'stale ' + str(bad) if bad else 'current'} (qualified {q.get('at')})")
    if stale:
        return fail("; ".join(stale + current))
    return ok("; ".join(current))
```

`status.render_text`: replace the three-way `last_qualification` block with a loop over `WIRES` reading `v["observed"].get("qualifications") or {}`, and `qualified: never` when the map is empty. `harness.cost_line`: `hb = cm.get("harness_baseline_tokens") or {}`; `base = (hb.get(harness) or {}).get("value")`; the parenthetical lists `harness` first then the others: `" · ".join(f"{h} {b['value']} = {round(100*b['value']/ctx)}%" for h, b in ordered if b.get("value"))` when `ctx`, else `(<h> <value> baseline)`. `harness.record_session`: new signature per Interfaces; `run_launch` calls `record_session(paths, launch, ended=ended, transcript=read_transcript(path) if path and path.exists() else None, mode=mode, harness="claude", harness_version=None)` and the function sets `harness_version = (transcript or {}).get("version")` when the caller passes `None`. `qualify.run_qualify` per Interfaces (`fp["harness_version"] = claude_code_version(claude_bin)`; `r["qualifications"]["messages"] = {**qual, "wire": "messages"}`; baseline under `["claude"]` with `harness_version`); knowledge twin gains `"wire": "messages"`. `schemas/knowledge.py`: in `validate_record` for `qualifications`, `if "wire" in rec and rec["wire"] not in WIRES: raise …` (import `WIRES` from `.observed`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4; ./bin/agent-on status --json > /dev/null && echo ok`
Expected: all pass; the real `observed.json` (v1) reads as v2 without error (do not write it: `status` without `--check` writes nothing).

- [ ] **Step 5: Commit**

```bash
git add agent_on/schemas/observed.py agent_on/schemas/knowledge.py agent_on/schemas/errors.py agent_on/state.py agent_on/invariants.py agent_on/status.py agent_on/harness.py agent_on/qualify.py tests/agent_on/test_observed_v2.py tests/agent_on/test_invariants.py tests/agent_on/test_status.py tests/agent_on/test_qualify_run.py tests/agent_on/test_harness_env.py tests/agent_on/test_harness_launch.py tests/agent_on/test_qualify.py
git commit -m "feat(agent-on): observed v2 — qualifications by wire, baselines by harness, sessions by harness; v1 upgrades in memory"
```

---

### Task 2: The mock serves `/v1/responses`

**Files:**
- Modify: `agent_on/mock_source.py`
- Test: `tests/agent_on/test_mock_responses.py`

**Interfaces:**
- Produces: `RESPONSES_GATE_NAMES = ("text_stream", "instructions", "forced_function_call", "function_call_arguments_stream", "function_call_output_continuation", "reasoning_effort")` (the mock's copy is imported from `qualify.GATES_RESPONSES` in Task 3 — for this task define it in `mock_source.py` and Task 3 replaces the definition with the import). `MockSource(fail_gates=…)` accepts these names too; `quirks` gains `"responses_incomplete_status"` (the forced call's `status` is `"incomplete"` — GLM through OpenRouter does that). `MockSource.reply_responses(body) -> (status, dict)` and `.responses_events(resp) -> list[dict]`; `POST /v1/responses` (and `/api/v1/responses`) answer JSON, or SSE when `body["stream"]` is true. Requests are recorded in `mock.requests` like the others, and `mock.responses_bodies` keeps the parsed bodies (as `mock.messages` does for the Anthropic wire).
- Reply rules (deterministic): estimate prompt tokens from `instructions` + `input` (string or items) + `tools`; over `max_context` → 400 `{"error": {"message": "…too long…"}}`; `instructions` containing the two `MARKERS` → message text with both markers (unless `instructions` in fail_gates); `tools` present and no `function_call_output` in `input` → output `[{"type": "function_call", "id": "fc_mock_1", "call_id": "call_mock_1", "name": <tool name>, "arguments": "{\"city\": \"Seoul\"}"}]` (unless `forced_function_call` in fail_gates → a plain message instead), `status` `"completed"` (or `"incomplete"` with the quirk); a `function_call_output` item in `input` → message `"It is 18C and sunny in Seoul."` (unless `function_call_output_continuation` in fail_gates → empty output); `reasoning` in body → a `reasoning` item first plus message `"OK"` and `usage.output_tokens_details.reasoning_tokens = 9` (unless `reasoning_effort` in fail_gates → 400 `{"error": {"message": "reasoning is not supported"}}`); otherwise message `"OK — the mock route is ready."` (unless `text_stream` in fail_gates → empty output). Caching: an `instructions` string seen before with `caching` on → `usage.input_tokens_details.cached_tokens = <its token estimate>`. Usage shape: `{"input_tokens", "output_tokens": 12, "input_tokens_details": {"cached_tokens"}, "output_tokens_details": {"reasoning_tokens"}}`; `total_tokens` set.
- SSE events, in order: `response.created`, then per output item `response.output_item.added`; for a message `response.content_part.added`, `response.output_text.delta` × chunks, `response.output_text.done`, `response.content_part.done`; for a function call `response.function_call_arguments.delta` × chunks (unless `function_call_arguments_stream` in fail_gates → no deltas, the item appears whole) then `response.function_call_arguments.done`; then `response.output_item.done` with the full item; finally `response.completed` with the full response (including `usage`). The server writes each as `event: <type>\ndata: <json>\n\n`, and one `: keepalive` comment line before the first event (so readers must skip non-`data:` lines, as OpenRouter's stream demands).

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_mock_responses.py`:

```python
from __future__ import annotations

import json
import sys
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
```

(`urllib.error` must be imported; the implementer adds it.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_mock_responses.py' -v`
Expected: `ImportError: cannot import name 'RESPONSES_GATE_NAMES'`.

- [ ] **Step 3: Write the code**

In `agent_on/mock_source.py`: add `RESPONSES_GATE_NAMES` (and extend the `fail_gates` validation to `set(GATE_NAMES) | set(RESPONSES_GATE_NAMES)`, `QUIRKS` to include `"responses_incomplete_status"`), `self.responses_bodies: list[dict] = []`, then:

```python
    def _responses_prompt_tokens(self, body: dict) -> int:
        inp = body.get("input")
        text = inp if isinstance(inp, str) else json.dumps(inp or [])
        return _tokens(text) + _tokens(body.get("instructions") or "") + _tokens(body.get("tools") or [])

    def reply_responses(self, body: dict) -> tuple[int, dict]:
        prompt = self._responses_prompt_tokens(body)
        if self.max_context is not None and prompt > self.max_context:
            return 400, {"error": {"message": f"input is too long: {prompt} tokens > {self.max_context} maximum", "type": "invalid_request_error"}}
        if body.get("reasoning") and "reasoning_effort" in self.fail_gates:
            return 400, {"error": {"message": "reasoning is not supported by this model", "type": "invalid_request_error"}}
        instructions = body.get("instructions") or ""
        cached = 0
        if instructions:
            if instructions in self._seen_system and self.caching:
                cached = _tokens(instructions)
            self._seen_system.add(instructions)
        items = body.get("input") if isinstance(body.get("input"), list) else []
        has_output = any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in items)
        output: list[dict] = []
        reasoning_tokens = 0
        if body.get("reasoning"):
            output.append({"type": "reasoning", "id": "rs_mock_1", "summary": [{"type": "summary_text", "text": "Considering briefly."}]})
            reasoning_tokens = 9
        markers = [m for m in MARKERS if m in instructions]
        status = "completed"
        if body.get("tools") and not has_output and "forced_function_call" not in self.fail_gates:
            output.append({"type": "function_call", "id": "fc_mock_1", "call_id": "call_mock_1", "name": body["tools"][0]["name"], "arguments": json.dumps({"city": "Seoul"})})
            if "responses_incomplete_status" in self.quirks:
                status = "incomplete"
        elif has_output:
            if "function_call_output_continuation" not in self.fail_gates:
                output.append(_message("It is 18C and sunny in Seoul."))
        elif markers and "instructions" not in self.fail_gates:
            output.append(_message(" ".join(markers)))
        elif body.get("reasoning"):
            output.append(_message("OK"))
        elif "text_stream" not in self.fail_gates:
            output.append(_message("OK — the mock route is ready."))
        usage = {"input_tokens": prompt, "output_tokens": 12, "total_tokens": prompt + 12,
                 "input_tokens_details": {"cached_tokens": cached}, "output_tokens_details": {"reasoning_tokens": reasoning_tokens}}
        return 200, {"id": "resp_mock", "object": "response", "status": status, "model": body.get("model"), "output": output, "usage": usage}
```

with `def _message(text): return {"type": "message", "id": "msg_mock_1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}`. `responses_events(resp)`:

```python
    def responses_events(self, resp: dict) -> list[tuple[str, dict]]:
        ev: list[tuple[str, dict]] = [("response.created", {"type": "response.created", "response": {**resp, "output": [], "status": "in_progress"}})]
        for i, item in enumerate(resp["output"]):
            ev.append(("response.output_item.added", {"type": "response.output_item.added", "output_index": i, "item": {k: v for k, v in item.items() if k not in ("content", "arguments")}}))
            if item["type"] == "message":
                text = item["content"][0]["text"]
                ev.append(("response.content_part.added", {"type": "response.content_part.added", "output_index": i, "content_index": 0, "part": {"type": "output_text", "text": ""}}))
                for piece in _chunks(text, 8):
                    ev.append(("response.output_text.delta", {"type": "response.output_text.delta", "output_index": i, "content_index": 0, "delta": piece}))
                ev.append(("response.output_text.done", {"type": "response.output_text.done", "output_index": i, "content_index": 0, "text": text}))
                ev.append(("response.content_part.done", {"type": "response.content_part.done", "output_index": i, "content_index": 0, "part": item["content"][0]}))
            elif item["type"] == "function_call":
                if "function_call_arguments_stream" not in self.fail_gates:
                    for piece in _chunks(item["arguments"], 6):
                        ev.append(("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "output_index": i, "item_id": item["id"], "delta": piece}))
                ev.append(("response.function_call_arguments.done", {"type": "response.function_call_arguments.done", "output_index": i, "item_id": item["id"], "arguments": item["arguments"]}))
            ev.append(("response.output_item.done", {"type": "response.output_item.done", "output_index": i, "item": item}))
        ev.append(("response.completed", {"type": "response.completed", "response": resp}))
        return ev
```

and in `do_POST`, before the messages branch:

```python
                if self.path in ("/v1/responses", "/api/v1/responses"):
                    mock.responses_bodies.append(body)
                    status, resp = mock.reply_responses(body)
                    if status == 200 and body.get("stream"):
                        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
                        self.wfile.write(b": keepalive\n\n")
                        for name, payload in mock.responses_events(resp):
                            self.wfile.write(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode("utf-8"))
                        return
                    self._json(status, resp)
                    return
```

(the existing `delay_s`/`serialize` handling applies before replying, exactly as the messages branch does — read it and reuse the same code path so the concurrency probe works on both wires). Any key-checking (`expect_key`) applies to this path too.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/mock_source.py tests/agent_on/test_mock_responses.py
git commit -m "feat(agent-on): the mock source serves /v1/responses — JSON and SSE, six fail-gates for the Responses wire"
```

---

### Task 3: `qualify --wire responses`

**Files:**
- Modify: `agent_on/qualify.py`, `agent_on/cli.py` (`qualify --wire`), `agent_on/mock_source.py` (import the gate names from `qualify`)
- Test: `tests/agent_on/test_qualify_responses.py`; extend `tests/agent_on/test_qualify_run.py`

**Interfaces:**
- `Wire(base_url, model, key=None, timeout=90.0, wire="messages")`: `self.path` is `/v1/messages` or `/v1/responses`; `post`/`stream` use it; `stream` already skips non-`data:` lines. Request builders as methods: `wire.simple(prompt: str, max_out: int) -> dict` (`{"max_tokens", "messages": [...]}` vs `{"max_output_tokens", "input": prompt}`), `wire.with_prefix(prefix: str, prompt: str, max_out: int) -> dict` (system block with `cache_control` vs `instructions`), `wire.cache_read(resp) -> int` (`usage.cache_read_input_tokens` vs `usage.input_tokens_details.cached_tokens`), `wire.output_tokens(resp) -> int`. `probe_throughput`, `probe_concurrency`, `probe_caching`, `probe_limits` use the builders (behaviour on the messages wire unchanged; `probe_limits(count_tokens=…)` is forced `False` on `responses` — no count endpoint — so `basis` is `estimate` and `verified` stays `None`).
- `GATES_RESPONSES` (the six names from §8.1) and `run_gates_responses(wire) -> dict` with the same return shape as `run_gates` (`gates`, `details`, `thinking_block_seen` = a `reasoning` item or `reasoning_tokens > 0` in the effort probe, `completed` = a final message with text, `thinking_tokens` = `usage.output_tokens_details.reasoning_tokens` or `None`, `all_pass`). Details record each probe's status and `forced_function_call_status_field` (the response `status`, `completed`/`incomplete`).
- `run_qualify(paths, name, *, wire="messages", baseline=False, limits=False, allow_paid=False, env=None, timeout=90.0, claude_bin=None, codex_bin=None)`: chooses the gate runner and builders by `wire`; fingerprint `harness_version` is `claude_code_version(claude_bin)` for `messages` and `codex_version(codex_bin)` for `responses`; writes `qualifications[wire]`; `--baseline` on `responses` runs the Codex harness (Task 5 — until then `run_qualify` raises `ValueError("--baseline on the responses wire lands with the codex harness")`; Task 5 replaces that line); the knowledge twin carries `wire`; `doc["wire"] = wire`.
- CLI: `qualify --wire {messages,responses}` (default `messages`); `render_qualify` prints `wire: responses` on its second line when not messages. `mock_source.RESPONSES_GATE_NAMES = GATES_RESPONSES` (imported) — D5.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_qualify_responses.py`:

```python
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
```

Extend `tests/agent_on/test_qualify_run.py` with a CLI-level check that `["--json", "qualify", "a", "--wire", "responses"]` exits 0 and the envelope carries `"wire": "responses"` (use the file's existing CLI idiom if it has one; else the `cli.main` + `redirect_stdout` idiom from `test_cli_learn.py`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_qualify_responses.py' -v`
Expected: `ImportError: cannot import name 'GATES_RESPONSES'`.

- [ ] **Step 3: Write the code**

`agent_on/qualify.py` — `Wire.__init__` gains `wire: str = "messages"`, sets `self.wire`, `self.path = "/v1/messages" if wire == "messages" else "/v1/responses"`; `post`/`stream` use `self.path`; add the builders:

```python
    def simple(self, prompt: str, max_out: int) -> dict:
        if self.wire == "messages":
            return {"max_tokens": max_out, "messages": [{"role": "user", "content": prompt}]}
        return {"max_output_tokens": max_out, "input": prompt}

    def with_prefix(self, prefix: str, prompt: str, max_out: int) -> dict:
        if self.wire == "messages":
            return {"max_tokens": max_out, "system": [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": prompt}]}
        return {"max_output_tokens": max_out, "instructions": prefix, "input": prompt}

    def cache_read(self, resp: dict) -> int:
        u = resp.get("usage") or {}
        if self.wire == "messages":
            return int(u.get("cache_read_input_tokens") or 0)
        return int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0)

    def output_tokens(self, resp: dict) -> int:
        return int((resp.get("usage") or {}).get("output_tokens") or 0)
```

`_timed`, `probe_throughput`, `probe_concurrency`, `probe_caching`, `probe_limits` switch to `wire.simple(...)`, `wire.with_prefix(...)`, `wire.cache_read(resp)`, `wire.output_tokens(resp)`; `probe_limits` sets `count_tokens = count_tokens and wire.wire == "messages"`. Then:

```python
GATES_RESPONSES = ("text_stream", "instructions", "forced_function_call", "function_call_arguments_stream",
                   "function_call_output_continuation", "reasoning_effort")
FUNCTION_TOOL = {"type": "function", "name": "get_weather", "description": "Get current weather for a city",
                 "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}


def _items(resp, kind: str) -> list[dict]:
    return [o for o in (resp.get("output") or []) if isinstance(o, dict) and o.get("type") == kind]


def _message_text(resp) -> str:
    return "".join(c.get("text", "") for o in _items(resp, "message") for c in (o.get("content") or []) if isinstance(c, dict) and c.get("type") == "output_text")


def _stream_completed(events: list[dict]) -> dict | None:
    done = [e for e in events if e.get("type") == "response.completed"]
    return done[-1].get("response") if done else None


def run_gates_responses(wire: Wire) -> dict:
    """§8.1: the six analogues on the Responses wire. Every probe budgets 512 output tokens — a reasoning model spends
    a small budget before the message (measured on glm-5.2 at 64)."""
    gates: dict[str, bool] = {}
    details: dict = {}
    status, events = wire.stream(wire.simple("Reply with one short sentence confirming this route is ready.", RESPONSE_MAX_TOKENS))
    text = "".join(e.get("delta", "") for e in events if e.get("type") == "response.output_text.delta")
    gates["text_stream"] = status == 200 and _stream_completed(events) is not None and bool(text.strip())
    details.update({"text_stream_status": status, "text_stream_chars": len(text)})

    status, resp = wire.post({"max_output_tokens": RESPONSE_MAX_TOKENS,
                              "instructions": f"Include the marker {MARKERS[0]} and the marker {MARKERS[1]} in the final reply.",
                              "input": "Apply the instructions and reply with only their markers."})
    text = _message_text(resp)
    gates["instructions"] = status == 200 and all(m in text for m in MARKERS)
    details["instructions_status"] = status

    tool_prompt = "Call get_weather exactly once for Seoul. Put the city in the structured city argument."
    forced = {"max_output_tokens": RESPONSE_MAX_TOKENS, "tools": [FUNCTION_TOOL], "tool_choice": {"type": "function", "name": "get_weather"}, "input": tool_prompt}
    status, resp = wire.post(forced)
    call = _items(resp, "function_call")[0] if status == 200 and _items(resp, "function_call") else None
    call_id = call.get("call_id") if call else None
    args = None
    if call:
        try:
            args = json.loads(call.get("arguments") or "")
        except ValueError:
            args = None
    gates["forced_function_call"] = bool(status == 200 and call and isinstance(call_id, str) and call_id.strip()
                                         and call.get("name") == "get_weather" and _valid_city(args))
    details["forced_function_call_status"] = status
    details["forced_function_call_status_field"] = resp.get("status")

    status, events = wire.stream(forced)
    deltas = [e for e in events if e.get("type") == "response.function_call_arguments.delta"]
    done_items = [e.get("item") or {} for e in events if e.get("type") == "response.output_item.done" and (e.get("item") or {}).get("type") == "function_call"]
    streamed_args = None
    if done_items:
        try:
            streamed_args = json.loads(done_items[0].get("arguments") or "")
        except ValueError:
            streamed_args = None
    gates["function_call_arguments_stream"] = bool(status == 200 and _stream_completed(events) is not None and deltas and done_items
                                                   and done_items[0].get("name") == "get_weather" and str(done_items[0].get("call_id") or "").strip()
                                                   and _valid_city(streamed_args))
    details["function_call_arguments_stream_status"] = status

    cont_status, cont_text = 0, ""
    if call and isinstance(call_id, str) and call_id.strip():
        cont_status, cont = wire.post({"max_output_tokens": RESPONSE_MAX_TOKENS, "tools": [FUNCTION_TOOL], "input": [
            {"role": "user", "content": tool_prompt},
            {k: v for k, v in call.items() if k in ("type", "id", "call_id", "name", "arguments")},   # replay the model's own item
            {"type": "function_call_output", "call_id": call_id, "output": "18C and sunny"}]})
        cont_text = _message_text(cont)
    gates["function_call_output_continuation"] = cont_status == 200 and bool(cont_text.strip())
    details["function_call_output_continuation_status"] = cont_status

    status, resp = wire.post({"max_output_tokens": RESPONSE_MAX_TOKENS, "reasoning": {"effort": "low"},
                              "input": "Think briefly as the selected provider normally would, then reply exactly OK."})
    text = _message_text(resp)
    reasoning_items = _items(resp, "reasoning")
    rt = ((resp.get("usage") or {}).get("output_tokens_details") or {}).get("reasoning_tokens")
    seen = (bool(reasoning_items) or (isinstance(rt, int) and rt > 0)) if status == 200 else None
    gates["reasoning_effort"] = status == 200 and bool(text.strip())
    details["reasoning_effort_status"] = status
    completed = status == 200 and bool(text.strip())
    tokens_on_probe = rt if (status == 200 and seen and isinstance(rt, int)) else None
    return {"gates": gates, "details": details, "thinking_block_seen": seen, "completed": completed,
            "thinking_tokens": tokens_on_probe, "all_pass": all(gates.values())}
```

`run_qualify`: add `wire: str = "messages"` and `codex_bin: str | None = None`; `Wire(source.base_url, route.wire_model, key, timeout, wire=wire)`; `gates = run_gates(wire_obj) if wire == "messages" else run_gates_responses(wire_obj)`; `harness_version = claude_code_version(claude_bin) if wire == "messages" else codex_version(codex_bin)`; `if baseline and wire == "responses": raise ValueError("--baseline on the responses wire lands with the codex harness")` (Task 5 replaces); `r["qualifications"][wire] = {**qual, "wire": wire}`; the `doc` gains `"wire": wire`; knowledge twin `"wire": wire`. The refusal estimate text stays. `mock_source.py`: `from .qualify import GATES_RESPONSES as RESPONSES_GATE_NAMES` — check for an import cycle (`qualify` imports `mock_source`? it does not; `gate.py` imports both — fine). CLI: `q.add_argument("--wire", choices=["messages", "responses"], default="messages")`, pass `wire=args.wire, codex_bin=os.environ.get("AGENT_ON_CODEX_BIN")`; `render_qualify` second line `wire: responses` when so.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/qualify.py agent_on/cli.py agent_on/mock_source.py tests/agent_on/test_qualify_responses.py tests/agent_on/test_qualify_run.py
git commit -m "feat(agent-on): qualify --wire responses — six gate analogues and the probes on the Responses wire"
```

---

### Task 4: Extract the harness-agnostic prologue and epilogue from `run_launch` (no behaviour change)

**Files:**
- Modify: `agent_on/harness.py`
- Test: existing suites (`test_harness_launch.py`, `test_harness_env.py`, `test_cli_launch.py`, `test_qualify_run.py`) must pass unchanged; one new test in `test_harness_env.py` for `child_env(harness="codex")`.

**Interfaces:**
- `LaunchPlan` dataclass (frozen=False): `parent, table, route, source, cwd, args, task_doc, obs_route, warnings, traps, served, lint, context, key, keyless, price, priced_models, launch_id, started`.
- `prologue(paths, name, args, *, env, cwd, task, handoff, probe_timeout, harness_bin, harness) -> LaunchPlan` — everything `run_launch` does today from `parent = …` down to the `launch_id`/`started` lines except the Claude-specific `extract_user_settings`, `prepare_config_dir`, `session_args`, `child_env`; the lint evaluation passes `claude_bin=harness_bin` for `claude` and `codex_bin=harness_bin` for `codex`.
- `epilogue(paths, plan, launch, *, code, ended, transcript, mode, harness, harness_version, doc) -> dict` — `record_session`, the cost observation, `doc.update(exit_code, last_session, knowledge)`.
- `child_env(parent, table, route, *, context, config_dir, discover=False, sonnet=None, haiku=None, harness="claude")` — for `codex`: the same scrub (plus every `OPENAI_*`, `CODEX_HOME`), sets only `CODEX_HOME = config_dir` and no Anthropic variables.
- `run_launch` keeps its signature (plus `codex_bin=None`) and, for `harness == "codex"`, imports and returns `harness_codex.run_launch_codex(...)` (Task 5; until then keep the `ValueError`).

- [ ] **Step 1: Write the failing test**

Append to `tests/agent_on/test_harness_env.py`:

```python
    def test_child_env_for_codex_scrubs_everything_and_sets_only_codex_home(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            table = load_routes(sb.paths)
            parent = {"PATH": "/usr/bin", "HOME": "/h", "OPENROUTER_API_KEY": "sk-x", "OPENAI_API_KEY": "sk-o", "ANTHROPIC_API_KEY": "sk-a",
                      "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1", "CODEX_HOME": "/elsewhere", "MOCK_PAID_KEY": "sk-p", "TERM": "xterm"}
            env = harness.child_env(parent, table, table.resolve("x"), context=100000, config_dir=Path("/run/codex-home"), harness="codex")
            self.assertEqual(env["CODEX_HOME"], "/run/codex-home")
            for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MOCK_PAID_KEY", "CLAUDE_CODE_MAX_OUTPUT_TOKENS"):
                self.assertNotIn(k, env)
            self.assertFalse(any(k.startswith(("ANTHROPIC_", "CLAUDE_", "OPENAI_")) for k in env))
            self.assertEqual(env["TERM"], "xterm")
```

(adjust `load_routes`/`harness` imports to the file's existing ones.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_harness_env.py' -v`
Expected: `TypeError: child_env() got an unexpected keyword argument 'harness'`.

- [ ] **Step 3: Refactor**

Move the body of `run_launch` from `parent = …` through the `launch = {...}` construction into `prologue` (returning `LaunchPlan`) and everything after `spawn` into `epilogue`; `run_launch` becomes: prologue → Claude-specific middle (settings extraction, `prepare_config_dir`, `session_args`, `child_env`, doc assembly, dry run, `write_run_dir`, task `launched`, argv, announce, spawn) → epilogue. Behaviour, doc keys and warnings must be identical: the existing tests are the proof. `child_env` for `codex`:

```python
    if harness == "codex":
        env = {k: v for k, v in parent.items()
               if k not in SCRUB_ENV and k != "CODEX_HOME" and not k.startswith(("ANTHROPIC_", "CLAUDE_", "OPENAI_"))}
        for src in table.sources.values():
            if src.auth_env:
                env.pop(src.auth_env, None)
        env["CODEX_HOME"] = str(config_dir)
        return env
```

(`PASS_THROUGH` is Claude-only.) `_price_of`, `cost_line(…, harness)` (Task 1) and `record_session` stay where they are.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass, same count + 1.

- [ ] **Step 5: Commit**

```bash
git add agent_on/harness.py tests/agent_on/test_harness_env.py
git commit -m "refactor(agent-on): run_launch = prologue + harness middle + epilogue; child_env knows the codex harness"
```

---

### Task 5: `agent_on/harness_codex.py`, `fakecodex.py`, `bin/codex-on`, `install` links three shims, `--baseline` on the Responses wire

**Files:**
- Create: `agent_on/harness_codex.py`, `bin/codex-on` (0755), `tests/agent_on/fakecodex.py` (0755)
- Modify: `agent_on/harness.py` (dispatch), `agent_on/cli.py` (`--harness codex`, `AGENT_ON_CODEX_BIN`), `agent_on/install.py` (`SHIMS`), `agent_on/qualify.py` (`--baseline` on `responses`), `agent_on/paths.py` (`Paths.codex_home_for(launch_id)`)
- Test: `tests/agent_on/test_harness_codex.py`; extend `test_install.py` (three links), `test_cli_launch.py` (`--harness codex --dry-run`), `test_qualify_responses.py` (baseline)

**Interfaces:**
- `paths.codex_home_for(launch_id) -> Path` = `run_dir / launch_id / "codex-home"`.
- `harness_codex.CODEX_SHARED = ("config.toml", "skills", "plugins", "hooks.json")`, `PROFILE = "agent-on"`.
- `prepare_codex_home(paths, launch_id, home: Path) -> Path` — creates `run/<id>/` (0700, with `pid` and `launch.json` like `write_run_dir`) and `codex-home/` (0700); for each `CODEX_SHARED` item present under `home/.codex`, a symlink; returns the codex-home path.
- `write_profile(codex_home, *, model, base_url, key, context) -> Path` — writes `agent-on.config.toml` (0600) with `model`, `model_provider = "agent-on"`, `model_context_window = <context>` (only when known), `[model_providers.agent-on]` `name`, `base_url` (the source's `base_url` + `/v1` unless it already ends with `/v1`), `wire_api = "responses"`, and `http_headers = { Authorization = "Bearer <key>" }` only when `key` is not None. Strings are TOML basic strings (escape `\` and `"`).
- `extract_user_profile(args) -> (args, name | None)` — strips `--profile X` / `--profile=X` / `-p X`? No: Codex's `-p` is `--profile`; strip both forms, return the name (the launcher warns and uses its own).
- `read_rollout(path) -> dict` — `{"session_id", "version", "model", "turns": [{"timestamp", "model", "usage": {four tower fields}, "id"}], "first_request": {"usage", "input_tokens_total"} | None, "effort", "permission_mode"}` from `session_meta` (`id`/`session_id`, `cli_version`), `turn_context` (`model`, and `effort`/`reasoning_effort`, `sandbox_policy`/`sandbox` when present, else `None`), and every `event_msg` `token_count` with `info.last_token_usage` → one turn with `input_tokens = input − cached_input`, `cache_read_input_tokens = cached_input`, `cache_creation_input_tokens = cache_write_input`, `output_tokens = output`; `first_request` from the first such turn with `input_tokens_total = input_tokens (raw, cached included)`.
- `find_rollout(codex_home) -> Path | None` — the newest `sessions/**/rollout-*.jsonl`.
- `run_launch_codex(paths, name, codex_args, *, dry_run, env, codex_bin, cwd, probe_timeout, announce, task, handoff) -> dict` — `prologue(harness="codex")`; strip a user profile (warning `"user --profile <x> replaced by the launcher's profile agent-on"`); `codex_home = paths.codex_home_for(launch_id)`; `cenv = child_env(..., config_dir=codex_home, harness="codex")`; argv `[binary, "--profile", PROFILE, *args]`; dry run: `argv` with `<run-dir>/codex-home` placeholder, `env_keys` = keys starting with `CODEX_`/`OPENAI_`; real run: `prepare_codex_home`, `write_profile`, task `launched`, announce the cost line (`harness="codex"`), `spawn`, `rmtree(run/<id>)` in `finally`, `ended`, `read_rollout(find_rollout(codex_home))` **before** the rmtree (read it inside the `try`/`finally` after spawn returns, then remove), `epilogue(..., harness="codex", harness_version=rollout["version"])`. Since the home is removed, the read-back happens before removal; `mode` is always `"fresh"` (no resume support — a warning if `resume` appears in the args).
- `harness.run_launch(..., harness="codex", codex_bin=…)` dispatches; `cli.launch --harness {claude,codex}`; `AGENT_ON_CODEX_BIN` read in `cli.py` only. `bin/codex-on`: `exec "${0:A:h}/agent-on" launch --harness codex "$@"` with a 2-line comment. `install.SHIMS = ("agent-on", "claude-on", "codex-on")`.
- `qualify --wire responses --baseline` runs `run_launch_codex(paths, route, ["exec", "--skip-git-repo-check", "-s", "read-only", BASELINE_PROMPT], env=parent, codex_bin=codex_bin, announce=False)` and takes `first_request.input_tokens_total` → `harness_baseline_tokens["codex"]` with `harness_version = codex_version(codex_bin)` and `measured_by = "qualify --wire responses --baseline"`.
- `tests/agent_on/fakecodex.py`: answers `--version` with `codex-cli 0.0.0 (fake)`; records `env.json`, `argv.json`, `cwd.txt` under `$FAKE_CODEX_OUT`; parses `--profile <name>` and reads `$CODEX_HOME/<name>.config.toml` with `tomllib`, dumping it as `profile.json`; writes a rollout under `$CODEX_HOME/sessions/2026/09/09/rollout-2026-09-09T00-00-00-<uuid>.jsonl` with `session_meta` (`id`, `cli_version: "0.0.0"`, `model_provider` from the profile, `cwd`), one `turn_context` (`model` from the profile), and `$FAKE_CODEX_TURNS` (default 1) `token_count` events whose `last_token_usage` is `{"input_tokens": 7000, "cached_input_tokens": 6000, "cache_write_input_tokens": 0, "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 7020}` and `total_token_usage` the running sum; writes `-o <file>` with `OK`; exits `$FAKE_CODEX_EXIT` (default 0).

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_harness_codex.py`:

```python
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.harness_codex import read_rollout, write_profile  # noqa: E402
from agent_on.state import read_observed, read_session_runs  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fakecodex.py")
BASE = "http://127.0.0.1:1"


class CodexLaunchTest(unittest.TestCase):
    def launch(self, sb, name, args, env=None, **kw):
        out = sb.root / "fake-out"
        (sb.paths.home / ".codex").mkdir(parents=True, exist_ok=True)
        (sb.paths.home / ".codex" / "config.toml").write_text('model = "user-default"\n', encoding="utf-8")
        (sb.paths.home / ".codex" / "skills").mkdir(exist_ok=True)
        base_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "FAKE_CODEX_OUT": str(out), **(env or {})}
        doc = harness.run_launch(sb.paths, name, args, harness="codex", env=base_env, codex_bin=FAKE, cwd=str(sb.paths.checkout),
                                 probe_timeout=0.5, announce=False, **kw)
        return doc, out

    def test_keyed_launch_puts_the_key_in_the_profile_and_nowhere_else(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "x", ["exec", "Reply OK"], env={"MOCK_PAID_KEY": "sk-from-env", "OPENAI_API_KEY": "sk-inherited"})
            self.assertEqual(doc["exit_code"], 0)
            env = json.loads((out / "env.json").read_text())
            self.assertNotIn("MOCK_PAID_KEY", env)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("sk-from-env", json.dumps(env))
            self.assertTrue(env["CODEX_HOME"].endswith("/codex-home"))
            profile = json.loads((out / "profile.json").read_text())
            self.assertEqual(profile["model_provider"], "agent-on")
            self.assertEqual(profile["model"], "vendor/model-x")
            p = profile["model_providers"]["agent-on"]
            self.assertEqual((p["wire_api"], p["base_url"]), ("responses", BASE + "/v1"))
            self.assertEqual(p["http_headers"]["Authorization"], "Bearer sk-from-env")
            self.assertEqual(profile["model_context_window"], 100000)
            argv = json.loads((out / "argv.json").read_text())
            self.assertEqual(argv[:2], ["--profile", "agent-on"])
            self.assertEqual(argv[2:], ["exec", "Reply OK"])
            self.assertFalse(list(sb.paths.run_dir.glob("*")))                                          # the home never outlives the child
            ls = doc["last_session"]
            self.assertEqual((ls["harness"], ls["harness_version"]), ("codex", "0.0.0"))
            self.assertEqual(ls["this_run"]["turns"], 1)
            self.assertEqual(ls["this_run"]["usage"], {"input_tokens": 1000, "output_tokens": 20, "cache_read_input_tokens": 6000, "cache_creation_input_tokens": 0})
            self.assertEqual(ls["first_request"]["input_tokens_total"], 7000)
            self.assertEqual(len(read_session_runs(sb.paths, ls["id"])), 1)
            self.assertEqual(read_observed(sb.paths)["routes"]["paid/vendor/model-x"]["last_session"]["harness"], "codex")

    def test_keyless_launch_has_no_header_and_shares_the_user_items(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["exec", "hi"])
            profile = json.loads((out / "profile.json").read_text())
            self.assertNotIn("http_headers", profile["model_providers"]["agent-on"])
            env = json.loads((out / "env.json").read_text())
            home = Path(env["CODEX_HOME"])
            # the fake ran while the home existed; it recorded what the links pointed at
            links = json.loads((out / "home_links.json").read_text())
            self.assertEqual(links["config.toml"], str(sb.paths.home / ".codex" / "config.toml"))
            self.assertEqual(links["skills"], str(sb.paths.home / ".codex" / "skills"))
            self.assertNotIn("plugins", links)                                                          # absent in the user's home: no dangling link

    def test_dry_run_and_user_profile_are_reported(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, _ = self.launch(sb, "a", ["--profile", "mine", "exec", "hi"], dry_run=True)
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["argv"][1:3], ["--profile", "agent-on"])
            self.assertNotIn("mine", doc["argv"])
            self.assertTrue(any("user --profile mine replaced" in w for w in doc["warnings"]))
            self.assertIn("CODEX_HOME", doc["env_keys"])
            self.assertFalse(sb.paths.run_dir.exists() and list(sb.paths.run_dir.glob("*")))

    def test_task_handoff_appends_the_prompt_last_and_marks_launched(self):
        from agent_on import tasks
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "Ship it", str(wt))
            tasks.handoff(sb.paths, t["id"], to_route="a", objective="Do the thing")
            doc, out = self.launch(sb, "a", ["exec"], task=t["id"])
            argv = json.loads((out / "argv.json").read_text())
            self.assertTrue(argv[-1].startswith("You are worker session 1 for agent-on task"))
            self.assertEqual((out / "cwd.txt").read_text().strip(), str(wt.resolve()))
            self.assertEqual(tasks.load(sb.paths, t["id"])["handoffs"][0]["status"], "launched")


class RolloutTest(unittest.TestCase):
    def test_read_rollout_maps_usage_and_reads_meta(self):
        lines = [{"timestamp": "2026-09-09T00:00:00.000Z", "type": "session_meta", "payload": {"id": "sid-1", "cli_version": "0.153.4", "model_provider": "agent-on", "cwd": "/w"}},
                 {"timestamp": "2026-09-09T00:00:01.000Z", "type": "turn_context", "payload": {"model": "m1", "effort": "low", "sandbox_policy": {"mode": "read-only"}}},
                 {"timestamp": "2026-09-09T00:00:02.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 3, "output_tokens": 10, "reasoning_output_tokens": 4}, "total_token_usage": {}}}},
                 {"timestamp": "2026-09-09T00:00:03.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 200, "cached_input_tokens": 150, "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0}, "total_token_usage": {}}}},
                 {"timestamp": "2026-09-09T00:00:04.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": None}}]
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.root / "rollout-x.jsonl"
            p.write_text("\n".join(json.dumps(l) for l in lines) + "\nnot json\n", encoding="utf-8")
            r = read_rollout(p)
            self.assertEqual((r["session_id"], r["version"], r["model"], r["effort"], r["permission_mode"]), ("sid-1", "0.153.4", "m1", "low", "read-only"))
            self.assertEqual([t["usage"] for t in r["turns"]],
                             [{"input_tokens": 60, "output_tokens": 10, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 3},
                              {"input_tokens": 50, "output_tokens": 5, "cache_read_input_tokens": 150, "cache_creation_input_tokens": 0}])
            self.assertEqual(r["first_request"]["input_tokens_total"], 100)
            self.assertTrue(all(t["model"] == "m1" for t in r["turns"]))

    def test_profile_toml_escapes_and_omits_what_is_unknown(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            home = sb.root / "ch"; home.mkdir()
            p = write_profile(home, model='we"ird', base_url="http://h:1/v1", key='k\\"y', context=None)
            import tomllib
            d = tomllib.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(d["model"], 'we"ird')
            self.assertEqual(d["model_providers"]["agent-on"]["http_headers"]["Authorization"], 'Bearer k\\"y')
            self.assertEqual(d["model_providers"]["agent-on"]["base_url"], "http://h:1/v1")
            self.assertNotIn("model_context_window", d)
            self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
```

`fakecodex.py` additionally writes `home_links.json` = `{item: os.readlink(path)}` for every symlink in `$CODEX_HOME` (so the test above can check the farm). `tests/agent_on/test_install.py`: the first test's loop covers `("agent-on", "claude-on", "codex-on")` and `doc["links"]` has three entries. `tests/agent_on/test_cli_launch.py`: `["--json", "launch", "--harness", "codex", "--dry-run", "a", "exec", "hi"]` with `AGENT_ON_CODEX_BIN=FAKE` in the cleared env → exit 0, `doc["dry_run"]`, `doc["argv"][1:3] == ["--profile", "agent-on"]`. `tests/agent_on/test_qualify_responses.py`: replace the `ValueError` assertion with a real baseline through the fake: `run_qualify(sb.paths, "a", env={"PATH": …, "HOME": str(sb.paths.home), "FAKE_CODEX_OUT": …}, timeout=10, wire="responses", baseline=True, codex_bin=FAKE)` → `doc["baseline"] == 7000` and `read_observed(...)["cost_model"]["harness_baseline_tokens"]["codex"]["value"] == 7000` with `harness_version == "0.0.0"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_harness_codex.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.harness_codex'`.

- [ ] **Step 3: Write the code**

`agent_on/harness_codex.py` (the shape; the implementer fills the bodies from the Interfaces, reusing `harness.prologue/epilogue/child_env/spawn/cost_line/sweep_run_dirs`):

```python
"""L6 — the Codex binding (§11.1, D14). One file; the tower unchanged. Home isolation: a per-launch CODEX_HOME with the
operator's config, skills, plugins and hooks linked in and a 0600 profile file carrying the provider and the key."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .harness import child_env, cost_line, epilogue, prologue, spawn, utc_ceil
from .paths import Paths, describe_copy

CODEX_SHARED = ("config.toml", "skills", "plugins", "hooks.json")
PROFILE = "agent-on"


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_profile(codex_home: Path, *, model: str, base_url: str, key: str | None, context: int | None) -> Path:
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    lines = [f"model = {_toml_str(model)}", f'model_provider = "{PROFILE}"']
    if context:
        lines.append(f"model_context_window = {int(context)}")
    lines += ["", f"[model_providers.{PROFILE}]", f'name = "{PROFILE}"', f"base_url = {_toml_str(base)}", 'wire_api = "responses"']
    if key is not None:
        lines.append(f"http_headers = {{ Authorization = {_toml_str('Bearer ' + key)} }}")
    p = codex_home / f"{PROFILE}.config.toml"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, ("\n".join(lines) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return p


def prepare_codex_home(paths: Paths, launch_id: str, home: Path, launch: dict) -> Path:
    d = paths.run_dir / launch_id
    d.mkdir(mode=0o700)
    (d / "pid").write_text(str(os.getpid()), encoding="utf-8")
    (d / "launch.json").write_text(json.dumps(launch, indent=1, sort_keys=True), encoding="utf-8")
    ch = d / "codex-home"
    ch.mkdir(mode=0o700)
    native = home / ".codex"
    for item in CODEX_SHARED:
        if (native / item).exists():
            (ch / item).symlink_to(native / item)
    return ch


def extract_user_profile(args: list[str]) -> tuple[list[str], str | None]:
    out, name, i = [], None, 0
    while i < len(args):
        a = args[i]
        if a in ("--profile", "-p") and i + 1 < len(args):
            name, i = args[i + 1], i + 2
            continue
        if a.startswith("--profile="):
            name, i = a.split("=", 1)[1], i + 1
            continue
        out.append(a)
        i += 1
    return out, name


def _usage(u: dict) -> dict:
    inp, cached = int(u.get("input_tokens") or 0), int(u.get("cached_input_tokens") or 0)
    return {"input_tokens": max(0, inp - cached), "output_tokens": int(u.get("output_tokens") or 0),
            "cache_read_input_tokens": cached, "cache_creation_input_tokens": int(u.get("cache_write_input_tokens") or 0)}


def read_rollout(path: Path) -> dict:
    session_id = version = model = effort = permission = None
    turns: list[dict] = []
    first = None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if e.get("type") == "session_meta":
            session_id, version = p.get("id") or p.get("session_id"), p.get("cli_version")
        elif e.get("type") == "turn_context":
            model = p.get("model") or model
            effort = p.get("effort") or p.get("reasoning_effort") or effort
            sp = p.get("sandbox_policy") or p.get("sandbox")
            permission = (sp.get("mode") if isinstance(sp, dict) else sp) or permission
        elif e.get("type") == "event_msg" and p.get("type") == "token_count":
            last = (p.get("info") or {}).get("last_token_usage") if isinstance(p.get("info"), dict) else None
            if not last:
                continue
            usage = _usage(last)
            turns.append({"timestamp": e.get("timestamp"), "model": model, "usage": usage, "id": f"turn-{n}"})
            if first is None:
                first = {"usage": usage, "input_tokens_total": int(last.get("input_tokens") or 0)}
    return {"session_id": session_id, "version": version, "model": model, "turns": turns, "first_request": first,
            "effort": effort, "permission_mode": permission}


def find_rollout(codex_home: Path) -> Path | None:
    files = sorted(codex_home.glob("sessions/**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None
```

`run_launch_codex` follows the Interfaces bullet exactly (prologue → strip profile → env/argv/doc → dry run → home + profile → task `launched` → announce → spawn → read rollout → rmtree in `finally` → epilogue). The `launch` record's `claude_args` key is named `args` for both harnesses? Keep `claude_args` for Claude; use `codex_args` for Codex (additive). `turns[*].model` is the rollout's `turn_context.model`, which equals the route's `wire_model` — `attribute_run` prices it from the snapshot. The `timestamp` of a turn must be an ISO string `parse_utc` accepts (rollouts use `2026-09-09T00:21:44.936Z`; check `util.parse_utc` handles fractional seconds and add that if it does not — with a test).

`harness.run_launch`: `if harness == "codex": from .harness_codex import run_launch_codex; return run_launch_codex(paths, name, claude_args, dry_run=dry_run, env=env, codex_bin=codex_bin, cwd=cwd, probe_timeout=probe_timeout, announce=announce, task=task, handoff=handoff)`. `cli.py`: `--harness` choices `["claude", "codex"]`; pass `codex_bin=os.environ.get("AGENT_ON_CODEX_BIN")`. `install.SHIMS` gains `"codex-on"`. `bin/codex-on`:

```zsh
#!/usr/bin/env zsh
# codex-on <route> [codex args…] — the Codex launcher shim (spec rev 9): agent-on launch --harness codex.
# Launch options (--dry-run, --task, --handoff, --json) go before the route; everything after it is Codex's.
set -u
exec "${0:A:h}/agent-on" launch --harness codex "$@"
```

`qualify.run_qualify`: replace the `ValueError` with the Codex baseline call from the Interfaces; `measured_by = f"qualify --wire {wire} --baseline"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/harness_codex.py agent_on/harness.py agent_on/cli.py agent_on/install.py agent_on/qualify.py agent_on/paths.py bin/codex-on tests/agent_on/fakecodex.py tests/agent_on/test_harness_codex.py tests/agent_on/test_install.py tests/agent_on/test_cli_launch.py tests/agent_on/test_qualify_responses.py
git commit -m "feat(agent-on): codex-on — the Codex binding: per-launch CODEX_HOME with a 0600 profile carrying the key, rollout read-back, three shims"
```

---

### Task 6: Docs — README, the skill, the spec's one word

**Files:**
- Modify: `README.md`, `.claude/skills/agent-on/SKILL.md`, `docs/superpowers/specs/2026-09-07-agent-on-design.md` (§9 rev 9 additions: `--harness` on `qualify` is implied by `--wire`)
- Test: `tests/agent_on/test_docs_plan_f.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402


class DocsTest(unittest.TestCase):
    def test_readme_and_skill_name_codex_on_and_the_wire_flag(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for needle in ("./bin/codex-on huihui", "--wire responses", "## Harnesses", "CODEX_HOME"):
            self.assertIn(needle, readme)
        skill = (REPO / ".claude" / "skills" / "agent-on" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("codex-on", skill)
        self.assertIn("--wire responses", skill)

    def test_spec_says_the_harness_is_implied_by_the_wire(self):
        spec = (REPO / "docs" / "superpowers" / "specs" / "2026-09-07-agent-on-design.md").read_text(encoding="utf-8")
        self.assertIn("`--baseline` measures the harness implied by the wire", spec)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Write the docs**

`README.md` — in "Use", after the `claude-on` lines add `./bin/codex-on huihui                        # Codex CLI on the same route; options before the route, everything after it is Codex's` and `./bin/agent-on qualify huihui --wire responses   # the six gate analogues on the Responses wire (what Codex speaks)`; add a section before "## Knowledge":

```markdown
## Harnesses

Two harnesses bind to the same routes: Claude Code (`claude-on`, the Anthropic Messages wire) and Codex CLI
(`codex-on`, the OpenAI Responses wire). Both take the key from a per-launch file the launcher writes and removes —
Claude Code through `apiKeyHelper` in a per-launch settings file, Codex through `http_headers` in a per-launch
profile under a per-launch `CODEX_HOME` (your `~/.codex` config, skills, plugins and hooks are linked in; sessions
stay per launch). Neither harness ever sees the key in its environment. Qualify each wire separately
(`--wire messages|responses`); `status` shows one `qualified[<wire>]` line per wire and one baseline per harness.
```

`.claude/skills/agent-on/SKILL.md` — in "Read first" mention `qualified[<wire>]`; in "Write when you learn" nothing; add under "Tasks across sessions": `./bin/codex-on --task <id> <route> exec` as the Codex form; add one line `./bin/agent-on qualify <route> --wire responses` in the read section. Spec §9 rev 9 additions: replace `[--harness claude|codex]` with nothing and add the sentence `--baseline measures the harness implied by the wire (messages → Claude Code, responses → Codex)`.

- [ ] **Step 3: Run the tests and commit**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`

```bash
git add README.md .claude/skills/agent-on/SKILL.md docs/superpowers/specs/2026-09-07-agent-on-design.md tests/agent_on/test_docs_plan_f.py
git commit -m "docs(agent-on): codex-on and the Responses wire in the README, the skill and the spec"
```

---

### Task 7: Acceptance on the real machine (§14 row F)

- [ ] **Step 1: The v1 → v2 upgrade on the real state**

```bash
python3 -c 'import json; print(json.load(open("/Users/rick/.local/state/agent-on/observed.json"))["version"])'
./bin/agent-on status huihui | grep -E 'qualified|baseline'
./bin/agent-on status --check | grep -cE '^  fail'
python3 -c 'import json; print(json.load(open("/Users/rick/.local/state/agent-on/observed.json"))["version"])'
```

Expected: `1`, then `qualified[messages] ✓ …` and the cost line with `(claude 54380 = 41%)`, `0` fails, and `2` after `--check` wrote `last_check`.

- [ ] **Step 2: The free lane through Codex**

```bash
./bin/codex-on --dry-run huihui exec 'hi' | grep -E 'argv|env:'
./bin/codex-on huihui exec --skip-git-repo-check -s read-only 'Reply with exactly: OK'; echo "exit $?"
./bin/codex-on huihui exec --skip-git-repo-check -s read-only 'Read README.md in this directory and reply with only its first line.'; echo "exit $?"
./bin/agent-on status huihui --json | python3 -c 'import json,sys; v=next(iter(json.load(sys.stdin)["routes"].values()))["observed"]["last_session"]; print(v["harness"], v["harness_version"], v["first_request"]["input_tokens_total"], v["this_run"]["cost_usd"])'
ls ~/.local/state/agent-on/run/
```

Expected: `OK` and `# agent-on`, both exit 0; `codex 0.153.4 <~7000> 0.0`; `run/` empty.

- [ ] **Step 3: Qualify the Responses wire (free, then cents)**

```bash
./bin/agent-on qualify huihui --wire responses --baseline; echo "exit $?"
./bin/agent-on qualify glm --wire responses; echo "exit $?"
./bin/agent-on status huihui | grep -E 'qualified|baseline'
```

Expected: 6/6 on both (huihui: `reasoning_effort` passes with a reasoning item; glm: `forced_function_call_status_field` may be `incomplete`), `harness_baseline_tokens.codex` ≈ 6,900, status shows `qualified[messages] ✓` and `qualified[responses] ✓` and `(claude 54380 = 41% · codex 6900 = 5%)`.

- [ ] **Step 4: The credential contract through Codex (cents)**

```bash
./bin/codex-on glm exec --skip-git-repo-check -s read-only 'Run the shell command `printenv` and reply with only the names of any variables among OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY that are present, or the word NONE.'; echo "exit $?"
```

Expected: `NONE`, exit 0; `run/` empty afterwards.

- [ ] **Step 5: A task handoff through `codex-on`**

```bash
TID=$(./bin/agent-on learn task create 'Plan F smoke' --goal 'Read README.md and reply with only its first line' --worktree "$PWD")
./bin/agent-on learn task handoff "$TID" --to huihui --objective 'Read README.md in this directory and reply with only its first line.' --summary 'Plan F acceptance' --commit "$(git rev-parse HEAD)"
./bin/codex-on --task "$TID" huihui exec --skip-git-repo-check -s read-only; echo "exit $?"
./bin/agent-on learn task complete "$TID" --summary 'answered' --close
```

Expected: `# agent-on`, exit 0; the handoff `launched` with a launch id, then `completed`.

- [ ] **Step 6: Gate, tests, knowledge**

```bash
./bin/agent-on gate | tail -2; ./bin/agent-on status --check | grep -cE '^  fail'
git add knowledge/ && git commit -m "knowledge: Plan F acceptance on <date> — codex-on on huihui and glm, the Responses wire qualified, observed v2 in place

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

## Self-review

**Spec coverage — §14 row F:** `harness_codex.py` (Task 5), `codex-on` shim + three-shim install (5), `qualify --wire responses` (3), observed v2 (1), mock `/v1/responses` (2), Read task on huihui and `printenv` on glm through Codex (7), both wires qualified with baselines (7), `--task` through `codex-on` (5, 7), v1 upgrade in place (1, 7), `status` shows both (1), gate green (7). D14 credential path (5), §8.1 gates (3), §11.1 read-back mapping (5), D5 single homes for wires/harnesses/gate names (1, 3).

**Deviations, stated:** `qualify` has no `--harness` flag; the wire implies the harness (spec §9 corrected in Task 6). `--resume` inside `codex-on` is unsupported (a per-launch home has one rollout). The Codex sandbox flag is the user's (D6). `experimental_bearer_token` is not used (works, but discouraged by the docs; `http_headers` is documented).

**Placeholder scan:** `<~7000>`, `<date>` in Task 7 are filled from the measurement; every code step shows its code or names the exact function to mirror.

**Type consistency:** `Wire(..., wire=)` is used identically in Tasks 3 and 5; `run_gates_responses` returns the `run_gates` shape so `run_qualify` treats both alike; `child_env(..., harness=)` (Task 4) is what `run_launch_codex` (Task 5) calls; `record_session(..., transcript=<parsed>, harness=, harness_version=)` (Task 1) is what both bindings call through `epilogue` (Task 4); `read_rollout` returns the fields `record_session` reads (`session_id`, `turns`, `first_request`, `effort`, `permission_mode`, `version`); `harness_baseline_tokens[harness]` uses `BASELINE_KEYS` everywhere; `WIRES`/`HARNESSES`/`WIRE_OF` are imported from `schemas.observed` by `qualify`, `invariants`, `status`, `mock_source`.
