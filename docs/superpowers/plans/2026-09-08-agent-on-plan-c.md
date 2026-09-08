# agent-on Plan C — Knowledge (`knowledge/`, `learn`, seeds, the task ledger, the skill) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land L5 — a git-tracked, append-only, typed `knowledge/` that every action writes and every session (and peer) reads — so the next session starts from what the last one learned.

**Architecture:** One new module `agent_on/knowledge.py` owns the JSONL contract (mint id + ts, validate, lock, append, read, fold supersession, select observations and traps). Actions that already run (`qualify`, the gate, the launch) append their records through it; `agent-on learn` is the operator's/agent's write verb; `status` and the launch show the last observations and the traps that apply to the route and the action in hand. The old task ledger (`scripts/task-ledger.py`, PR #12) is re-expressed as event-sourced `tasks.jsonl` under `learn task …`, and `claude-on <route> --task <id>` injects the handoff prompt as the old `task launch` did. Seeds carry the measured facts, the thirteen decisions and the traps this repo has paid for, with **stable human-readable ids**; `learn` mints ULIDs. A project skill tells an agent inside Claude Code how to read and write it.

**Tech Stack:** Python ≥ 3.11 standard library only (`json`, `fcntl`, `tomllib`, `argparse`, `unittest`); zsh shims; JSONL under git.

**Spec:** `docs/superpowers/specs/2026-09-07-agent-on-design.md` (rev 8) — §9 (`learn`, `status` rows), §10 (L5 files and seeds), §10.1 (task ledger), §14 row C, §15 (Q1, Q3–Q6, Q8, Q10), §17 (memory-note migration). Plan A (`docs/superpowers/plans/2026-09-07-agent-on-plan-a.md`) and Plan B (`docs/superpowers/plans/2026-09-08-agent-on-plan-b.md`) are the landed context; their ledgers hold the rulings this plan inherits.

## Global Constraints

- **D4** One package `agent_on/`, Python ≥ 3.11 from `PATH`, standard library only. On this machine run suites with `/opt/homebrew/bin/python3.13` (CI pins 3.13).
- **§10** `knowledge/` is git-tracked, append-only JSONL **in the checkout** (`<checkout>/knowledge/<kind>.jsonl`), one file per kind, every line validated against its kind's schema, **every record with `id` and `ts`**, `id` prefixed by its kind.
- **§9** `agent-on learn <kind> --json '<record>'` (or stdin) validates and appends; assigns `id = <kind>-<ULID>` and `ts` when absent; validates `supersedes`.
- **D5** One home per fact: route names come from `routes.toml`; no constant is duplicated; the invariant `knowledge.typed` is the only judge of a record's shape and it calls `agent_on/schemas/knowledge.py`.
- **D6** Inform, don't gate: traps and observations are shown; they never block a launch.
- **D13** Machine-written state lives outside git in `$STATE` — `knowledge/` is the one deliberate exception (§10), and its writer lock is `<checkout>/.knowledge.lock` (keyed by the resource it protects, like `.routes.lock`), git-ignored.
- **Plan B rulings that bind here:** every value written is a measurement or `null`/`"unknown"`, never inferred; secrets never reach stdout/stderr/JSON/knowledge; tests use only `tests/agent_on/helpers.Sandbox`, `MockSource` and `tests/agent_on/fakeclaude.py` — never the real checkout's state, home, oMLX or `claude`; `observed.json` is written only through `update_observed`; JSON envelopes only gain keys; every verb answers `--json` before or after the verb.
- **§14 row C deletes nothing.** `scripts/task-ledger.py`, `tests/test_task_ledger.py`, `config/claude-litellm/shell.zsh` and everything the old `claude-litellm` path uses stay untouched until Plan D. The one doc edit the spec names (§10.1: drop the Orca paragraph from `docs/ARCHITECTURE.md`) is a deletion of prose, not code.
- **Commit trailers** on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD
  ```

---

## File structure

| path | responsibility |
|---|---|
| `agent_on/paths.py` | `Paths.knowledge_dir` (`checkout/knowledge`), `Paths.knowledge_lock` (`checkout/.knowledge.lock`) |
| `agent_on/schemas/knowledge.py` | record shape per kind (exists); gains `APPLIES_TO_VERBS`, `TASK_EVENTS`, per-event required fields, and `validate_file` reporting duplicate ids and dangling `supersedes` |
| `agent_on/knowledge.py` | **new** — `append`, `read`, `active`, `latest`, `applicable_traps`, `knowledge_view` |
| `agent_on/tasks.py` | **new** — event-sourced task ledger: `fold`, `create`, `handoff`, `complete`, `launched`, `render_prompt`, `TASK_ID` |
| `agent_on/cli.py` | `learn` verb (records and `learn task …`), `launch --task/--handoff`, renderers |
| `agent_on/qualify.py` | appends a `throughput` observation beside its qualification record |
| `agent_on/gate.py` | appends the `gate-runs.jsonl` twin |
| `agent_on/harness.py` | `run_launch(..., task=None, handoff="latest")`: worktree cwd + injected prompt + `launched` event; `cost` observation after read-back; `traps` in the doc |
| `agent_on/status.py` | `routes.*.knowledge = {observations, traps}` and the text lines |
| `agent_on/invariants.py` | `knowledge.typed` scans `paths.knowledge_dir` (not `tree`) and is real once the seeds land |
| `knowledge/*.jsonl` | seeds (six files) |
| `.claude/skills/agent-on/SKILL.md` | the project skill |
| `README.md`, `docs/ARCHITECTURE.md`, `.gitignore`, `.github/workflows/ci.yml` | docs, lock ignore, CI assertion |
| `tests/agent_on/test_knowledge.py`, `test_cli_learn.py`, `test_knowledge_seeds.py`, `test_tasks.py`; extended `test_qualify_run.py`, `test_gate.py`, `test_harness_launch.py`, `test_status.py`, `test_invariants.py` | tests |

Knowledge lives beside `routes.toml`: `Sandbox` gives every test its own `checkout`, so no test touches the real `knowledge/`; the seeds test reads the real files read-only.

---

### Task 1: `agent_on/knowledge.py` — the JSONL contract (append, read, supersession, selection)

**Files:**
- Modify: `agent_on/paths.py` (two properties), `agent_on/schemas/knowledge.py`, `agent_on/invariants.py` (`knowledge.typed`), `.gitignore`
- Create: `agent_on/knowledge.py`
- Test: `tests/agent_on/test_knowledge.py`; one edit in `tests/agent_on/test_invariants.py`

**Interfaces:**
- Consumes: `agent_on.ids.ulid`, `agent_on.util.utc_now`, `agent_on.state.locked`, `agent_on.schemas.knowledge.{KINDS, validate_record, validate_file}`, `agent_on.schemas.errors.SchemaError`.
- Produces:
  - `Paths.knowledge_dir -> Path` (`checkout / "knowledge"`), `Paths.knowledge_lock -> Path` (`checkout / ".knowledge.lock"`).
  - `knowledge.append(paths, kind: str, rec: dict, *, now: str | None = None) -> dict` — fills `id` (`f"{kind}-{ulid()}"`) and `ts` (`utc_now()`) when absent, validates the record, validates `supersedes` (must name an existing id **of the same kind**), takes `paths.knowledge_lock`, creates `knowledge/` if missing, appends one `json.dumps(rec, sort_keys=True)` line, `flush` + `fsync`, returns the record as written. Raises `SchemaError("knowledge.record", …)` on any violation; nothing is written on error.
  - `knowledge.read(paths, kind) -> list[dict]` — every record in file order; a missing file is `[]`; a malformed line raises `SchemaError("knowledge.record", "<file>:<line>: …")`.
  - `knowledge.active(records) -> list[dict]` — records not named by any other record's `supersedes`.
  - `knowledge.latest(records, *, route: str | None, n: int = 3) -> list[dict]` — the last `n` records (file order = time order) whose `route` equals `route` (or all when `route` is None).
  - `knowledge.applicable_traps(traps, *, route, source, action) -> list[dict]` — active traps whose `applies_to` contains `"*"`, `action`, `source`, or `route`.
  - `knowledge.knowledge_view(paths, *, route, source, action, n=3) -> dict` — `{"observations": latest(read("observations"), route=route, n=n), "traps": applicable_traps(active(read("traps")), …)}`; when `knowledge/` is absent returns `{"observations": [], "traps": [], "missing": True}`.
  - `schemas.knowledge.APPLIES_TO_VERBS = ("status", "sync", "add", "gate", "launch", "qualify", "learn", "install")`; `validate_record("traps", …)` requires `applies_to` to be a non-empty list of strings.
  - `schemas.knowledge.validate_file(path)` additionally reports `duplicate id <id>` and `supersedes <id> not found in <file>` (dangling within the same file).

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_knowledge.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import knowledge  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.knowledge import validate_file  # noqa: E402

BASE = "http://127.0.0.1:1"
TRAP = {"trap": "t", "mechanism": "m", "avoid": "a", "evidence": "e", "found_by": "f", "applies_to": ["launch", "mock"]}


class AppendReadTest(unittest.TestCase):
    def test_append_mints_id_and_ts_creates_the_dir_and_reads_back_in_order(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            self.assertFalse(sb.paths.knowledge_dir.exists())
            a = knowledge.append(sb.paths, "traps", dict(TRAP))
            b = knowledge.append(sb.paths, "traps", dict(TRAP, trap="u"), now="2026-09-08T00:00:00Z")
            self.assertTrue(a["id"].startswith("traps-") and len(a["id"]) == len("traps-") + 26)
            self.assertRegex(a["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertEqual(b["ts"], "2026-09-08T00:00:00Z")
            self.assertEqual([r["trap"] for r in knowledge.read(sb.paths, "traps")], ["t", "u"])
            self.assertEqual(knowledge.read(sb.paths, "decisions"), [])
            lines = (sb.paths.knowledge_dir / "traps.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0]), a)                                   # one line per record, sorted keys
            self.assertTrue(sb.paths.knowledge_lock.exists())

    def test_an_invalid_record_writes_nothing(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "traps", {"trap": "t"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "vibes", {"x": 1})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=[]))
            self.assertFalse((sb.paths.knowledge_dir / "traps.jsonl").exists())

    def test_supersedes_must_name_an_existing_id_of_the_same_kind(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            d1 = knowledge.append(sb.paths, "decisions", {"decision": "a", "rationale": "r", "by": "rick"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "decisions", {"decision": "b", "rationale": "r", "by": "rick", "supersedes": "decisions-nope"})
            t = knowledge.append(sb.paths, "traps", dict(TRAP))
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "decisions", {"decision": "b", "rationale": "r", "by": "rick", "supersedes": t["id"]})
            d2 = knowledge.append(sb.paths, "decisions", {"decision": "b", "rationale": "r", "by": "rick", "supersedes": d1["id"]})
            self.assertEqual([r["id"] for r in knowledge.active(knowledge.read(sb.paths, "decisions"))], [d2["id"]])

    def test_a_malformed_line_is_a_schema_error_naming_file_and_line(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            knowledge.append(sb.paths, "traps", dict(TRAP))
            with open(sb.paths.knowledge_dir / "traps.jsonl", "a", encoding="utf-8") as f:
                f.write("not json\n")
            with self.assertRaises(SchemaError) as cm:
                knowledge.read(sb.paths, "traps")
            self.assertIn("traps.jsonl:2", str(cm.exception))
            errors = validate_file(sb.paths.knowledge_dir / "traps.jsonl")
            self.assertEqual(len(errors), 1)

    def test_validate_file_reports_duplicate_ids_and_dangling_supersedes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            sb.paths.knowledge_dir.mkdir()
            p = sb.paths.knowledge_dir / "decisions.jsonl"
            p.write_text('{"id": "decisions-1", "ts": "2026-09-08T00:00:00Z", "decision": "a", "rationale": "r", "by": "b"}\n'
                         '{"id": "decisions-1", "ts": "2026-09-08T00:00:00Z", "decision": "a", "rationale": "r", "by": "b"}\n'
                         '{"id": "decisions-2", "ts": "2026-09-08T00:00:00Z", "decision": "a", "rationale": "r", "by": "b", "supersedes": "decisions-9"}\n',
                         encoding="utf-8")
            errors = validate_file(p)
            self.assertTrue(any("duplicate id decisions-1" in e for e in errors), errors)
            self.assertTrue(any("supersedes decisions-9 not found" in e for e in errors), errors)


class SelectionTest(unittest.TestCase):
    def test_latest_and_applicable_traps(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            for i in range(5):
                knowledge.append(sb.paths, "observations", {"route": "mock/alpha" if i % 2 == 0 else "mock/beta", "kind": "cost",
                                                            "values": {"i": i}, "evidence": "e"})
            obs = knowledge.read(sb.paths, "observations")
            self.assertEqual([o["values"]["i"] for o in knowledge.latest(obs, route="mock/alpha", n=2)], [2, 4])
            self.assertEqual([o["values"]["i"] for o in knowledge.latest(obs, route=None, n=2)], [3, 4])
            t_launch = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["launch"]))
            t_src = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["mock"]))
            t_route = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["mock/beta"]))
            t_star = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["*"]))
            t_old = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["*"]))
            knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["sync"], supersedes=t_old["id"]))
            traps = knowledge.active(knowledge.read(sb.paths, "traps"))
            got = knowledge.applicable_traps(traps, route="mock/alpha", source="mock", action="launch")
            self.assertEqual({t["id"] for t in got}, {t_launch["id"], t_src["id"], t_star["id"]})
            got = knowledge.applicable_traps(traps, route="mock/beta", source="mock", action="status")
            self.assertEqual({t["id"] for t in got}, {t_src["id"], t_route["id"], t_star["id"]})
            self.assertNotIn(t_old["id"], {t["id"] for t in traps})

    def test_knowledge_view_reports_missing_when_there_is_no_directory(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            v = knowledge.knowledge_view(sb.paths, route="mock/alpha", source="mock", action="status")
            self.assertEqual(v, {"observations": [], "traps": [], "missing": True})


if __name__ == "__main__":
    unittest.main()
```

Edit `tests/agent_on/test_invariants.py` — in the `knowledge.typed` test (around line 213) the planted directory is already `sb.paths.checkout / "knowledge"` with `tree=None`; add, after the existing `assertIn("decisions.jsonl:2", r.reason)`, a second sandbox that plants a valid file with a duplicate id and asserts `one(sb.paths, "knowledge.typed").result == "fail"` with `"duplicate id"` in the reason. Also change the test's `Sandbox(..., tree=None)` to the default `Sandbox(...)` (tree = real code tree): the invariant must scan `paths.knowledge_dir`, **not** `tree`, so a sandbox that lints the real code tree must still see only its own knowledge.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_knowledge.py' -v; python3.13 -m unittest tests.agent_on.test_invariants -k knowledge -v 2>&1 | tail -5`
Expected: `ImportError: cannot import name 'knowledge'` / `AttributeError: 'Paths' object has no attribute 'knowledge_dir'`; the invariants edit fails because the invariant scans `tree`.

- [ ] **Step 3: Write the code**

`agent_on/paths.py` — after `routes_lock`:

```python
    @property
    def knowledge_dir(self) -> Path:
        return self.checkout / "knowledge"            # §10: git-tracked, beside routes.toml — never under $STATE

    @property
    def knowledge_lock(self) -> Path:
        return self.checkout / ".knowledge.lock"      # keyed by the resource it protects, like .routes.lock (D13)
```

`.gitignore` — add `.knowledge.lock` on the line after `.routes.lock`.

`agent_on/schemas/knowledge.py` — add after `OBSERVATION_KINDS`:

```python
APPLIES_TO_VERBS = ("status", "sync", "add", "gate", "launch", "qualify", "learn", "install")
```

and extend `validate_record`:

```python
    if kind == "traps":
        at = rec["applies_to"]
        if not isinstance(at, list) or not at or not all(isinstance(a, str) and a for a in at):
            raise SchemaError("knowledge.record", "traps: applies_to must be a non-empty list of verbs, sources, routes or '*'")
    if "supersedes" in rec and not (isinstance(rec["supersedes"], str) and rec["supersedes"].startswith(f"{kind}-")):
        raise SchemaError("knowledge.record", f"{kind}: supersedes must name an id of the same kind")
```

Replace `validate_file` with:

```python
def validate_file(path: Path) -> list[str]:
    """Every non-blank line of knowledge/<kind>.jsonl; returns `<file>:<line>: <error>` strings. Cross-line rules:
    ids are unique within the file and `supersedes` names an id that appears in it."""
    kind = path.stem
    errors: list[str] = []
    seen: dict[str, int] = {}
    supersedes: list[tuple[int, str]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            validate_record(kind, rec)
        except (ValueError, SchemaError) as e:
            errors.append(f"{path.name}:{n}: {e}")
            continue
        if rec["id"] in seen:
            errors.append(f"{path.name}:{n}: duplicate id {rec['id']} (first at line {seen[rec['id']]})")
        seen.setdefault(rec["id"], n)
        if "supersedes" in rec:
            supersedes.append((n, rec["supersedes"]))
    for n, target in supersedes:
        if target not in seen:
            errors.append(f"{path.name}:{n}: supersedes {target} not found in {path.name}")
    return errors
```

`agent_on/knowledge.py`:

```python
"""L5 — knowledge/ (§10): git-tracked, append-only JSONL in the checkout, one file per kind, every record typed and
carrying id + ts. This module is the only writer path: `learn`, `qualify`, the gate and the launch all append here."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .ids import ulid
from .paths import Paths
from .schemas.errors import SchemaError
from .schemas.knowledge import KINDS, validate_record
from .state import locked
from .util import utc_now


def _path(paths: Paths, kind: str) -> Path:
    if kind not in KINDS:
        raise SchemaError("knowledge.record", f"unknown kind {kind!r}; kinds: {sorted(KINDS)}")
    return paths.knowledge_dir / f"{kind}.jsonl"


def read(paths: Paths, kind: str) -> list[dict]:
    """Every record of one kind in file order (append order is time order). A missing file is empty."""
    p = _path(paths, kind)
    if not p.exists():
        return []
    out: list[dict] = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            validate_record(kind, rec)
        except (ValueError, SchemaError) as e:
            raise SchemaError("knowledge.record", f"{p.name}:{n}: {e}") from None
        out.append(rec)
    return out


def append(paths: Paths, kind: str, rec: dict, *, now: str | None = None) -> dict:
    """Validate, then append one line under the knowledge lock. id and ts are minted when absent (§9); a caller that
    brings its own id (the seeds) keeps it. `supersedes` must name an existing id of the same kind. Nothing is
    written when validation fails."""
    p = _path(paths, kind)
    rec = dict(rec)
    rec.setdefault("id", f"{kind}-{ulid()}")
    rec.setdefault("ts", now or utc_now())
    validate_record(kind, rec)
    with locked(paths.knowledge_lock):
        existing = read(paths, kind)
        if any(r["id"] == rec["id"] for r in existing):
            raise SchemaError("knowledge.record", f"{kind}: id {rec['id']} already exists")
        if "supersedes" in rec and not any(r["id"] == rec["supersedes"] for r in existing):
            raise SchemaError("knowledge.record", f"{kind}: supersedes {rec['supersedes']} not found")
        p.parent.mkdir(exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return rec


def active(records: list[dict]) -> list[dict]:
    """Records not superseded by a later one."""
    dead = {r["supersedes"] for r in records if "supersedes" in r}
    return [r for r in records if r["id"] not in dead]


def latest(records: list[dict], *, route: str | None, n: int = 3) -> list[dict]:
    sel = [r for r in records if route is None or r.get("route") == route]
    return sel[-n:] if n else []


def applicable_traps(traps: list[dict], *, route: str | None, source: str | None, action: str) -> list[dict]:
    keys = {"*", action, source, route} - {None}
    return [t for t in traps if keys.intersection(t["applies_to"])]


def knowledge_view(paths: Paths, *, route: str | None, source: str | None, action: str, n: int = 3) -> dict:
    """What status and the launch show for one route: the last n observations and the traps for the action in hand."""
    if not paths.knowledge_dir.is_dir():
        return {"observations": [], "traps": [], "missing": True}
    return {"observations": latest(read(paths, "observations"), route=route, n=n),
            "traps": applicable_traps(active(read(paths, "traps")), route=route, source=source, action=action)}
```

`agent_on/invariants.py` — `knowledge_typed` scans the checkout's knowledge dir:

```python
def knowledge_typed(ctx: Context):
    kdir = ctx.paths.knowledge_dir                     # §10: beside routes.toml, never the code tree (a sandbox lints real code but owns its knowledge)
    if not kdir.exists():
        return skip("no knowledge/ yet — Plan C")
    files = sorted(kdir.glob("*.jsonl"))
    errors = [e for f in files for e in validate_file(f)]
    return fail("; ".join(errors[:5])) if errors else ok(f"{len(files)} file(s) valid")
```

(`Context` already carries `paths`.) Keep the `fix` text but drop "(Plan C)".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass (166 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add agent_on/paths.py agent_on/schemas/knowledge.py agent_on/knowledge.py agent_on/invariants.py .gitignore tests/agent_on/test_knowledge.py tests/agent_on/test_invariants.py
git commit -m "feat(agent-on): knowledge — append/read/supersede/select over knowledge/*.jsonl; knowledge.typed scans the checkout"
```

---

### Task 2: `agent-on learn <kind>` — the write verb

**Files:**
- Modify: `agent_on/cli.py`
- Test: `tests/agent_on/test_cli_learn.py`

**Interfaces:**
- Consumes: `knowledge.append`, `SchemaError`, `EXIT_OK/EXIT_SCHEMA/EXIT_USAGE`.
- Produces: `agent-on learn <kind> [--json-record '<json>']` — the record comes from `--json-record` or, when that flag is absent, from stdin (one JSON object). The global `--json` flag keeps its meaning (machine-readable output), which is why the record flag is `--json-record` (the spec's row writes `--json '<record>'`; the two flags would collide — ruling recorded here). Envelope: `{"command": "learn", "copy": …, "kind", "written": bool, "record": <as written> | null, "path": "<file>", "invariants": [knowledge.typed]}`. Exit 0 when written; 3 on a schema error (envelope carries `error` and `rule`); 2 on usage (unknown kind is a schema error, empty stdin is usage). `kind == "task"` is routed to Task 6's parser (a stub in this task returns usage exit 2 with `hint: "learn task lands in Task 6"`).
- Text rendering: the copy line, `learned <id> → knowledge/<kind>.jsonl`, then the invariant lines.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_cli_learn.py`:

```python
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import cli, knowledge  # noqa: E402

BASE = "http://127.0.0.1:1"
DECISION = json.dumps({"decision": "d", "rationale": "r", "by": "test"})


def run(sb, argv, stdin: str | None = None) -> tuple[int, dict]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "AGENT_ON_STATE": str(sb.paths.state), "AGENT_ON_CHECKOUT": str(sb.paths.checkout)}
    out = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin or "")):
        code = cli.main(["--json", *argv])
    return code, json.loads(out.getvalue())


class LearnTest(unittest.TestCase):
    def test_learn_appends_a_validated_record_from_the_flag(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions", "--json-record", DECISION])
            self.assertEqual(code, 0, doc)
            self.assertTrue(doc["written"])
            self.assertTrue(doc["record"]["id"].startswith("decisions-"))
            self.assertEqual(doc["path"], str(sb.paths.knowledge_dir / "decisions.jsonl"))
            self.assertEqual([i["result"] for i in doc["invariants"]], ["pass"])
            self.assertEqual(knowledge.read(sb.paths, "decisions")[0]["id"], doc["record"]["id"])

    def test_learn_reads_stdin_when_the_flag_is_absent(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions"], stdin=DECISION)
            self.assertEqual(code, 0, doc)
            self.assertTrue(doc["written"])

    def test_a_bad_record_is_a_schema_error_exit_3_and_nothing_is_written(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions", "--json-record", '{"decision": "d"}'])
            self.assertEqual(code, 3)
            self.assertEqual(doc["rule"], "knowledge.record")
            self.assertFalse((sb.paths.knowledge_dir / "decisions.jsonl").exists())
            code, doc = run(sb, ["learn", "vibes", "--json-record", DECISION])
            self.assertEqual(code, 3)
            code, doc = run(sb, ["learn", "decisions", "--json-record", "not json"])
            self.assertEqual(code, 2)
            self.assertIn("error", doc)

    def test_empty_stdin_is_usage(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions"], stdin="")
            self.assertEqual(code, 2)

    def test_learn_task_is_routed_to_the_task_parser(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "task"])
            self.assertEqual(code, 2)                                                   # Task 6 replaces the stub


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_cli_learn.py' -v`
Expected: `SystemExit: 2` from argparse (no `learn` verb).

- [ ] **Step 3: Write the code**

`agent_on/cli.py` — in `build_parser`, after the `qualify` parser:

```python
    n = sub.add_parser("learn", parents=[common], help="validate and append one record to knowledge/<kind>.jsonl (id and ts minted when absent); `learn task …` is the task ledger")
    n.add_argument("kind", help="observations | decisions | traps | qualifications | gate-runs | tasks — or `task` for the ledger verbs")
    n.add_argument("--json-record", metavar="JSON", help="the record; when absent, one JSON object is read from stdin")
    n.add_argument("rest", nargs=argparse.REMAINDER, help="`learn task` arguments")
```

Add a renderer:

```python
def render_learn(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    lines.append(f"learned {doc['record']['id']} → {doc['path']}" if doc["written"] else "NOT learned")
    return "\n".join(lines + invariant_lines(doc["invariants"]))
```

In `main`, before the `else:` gate branch:

```python
        elif args.command == "learn":
            if args.kind == "task":
                from .tasks import run_task_verb                     # Task 6; until then a usage error
                doc, code = run_task_verb(paths, args.rest)
                text = doc.get("text") or json.dumps(doc, indent=1, sort_keys=True)
            else:
                from .knowledge import append
                from .invariants import build_context, evaluate
                raw = args.json_record if args.json_record is not None else sys.stdin.read()
                if not raw.strip():
                    raise ValueError("learn: no record given (use --json-record or stdin)")     # → exit 1? no: usage, see below
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    doc = {"command": "learn", "copy": describe_copy(paths), "error": f"record is not JSON: {e}", "hint": "pass one JSON object"}
                    print(json.dumps(doc, indent=1, sort_keys=True) if args.json else f"{copy_line(doc['copy'])}\nerror: {doc['error']}")
                    return EXIT_USAGE
                written = append(paths, args.kind, rec)
                doc = {"command": "learn", "copy": describe_copy(paths), "kind": args.kind, "written": True, "record": written,
                       "path": str(paths.knowledge_dir / f"{args.kind}.jsonl"),
                       "invariants": [r.as_dict() for r in evaluate(build_context(paths), ids=["knowledge.typed"])]}
                code, text = EXIT_OK, render_learn(doc)
```

Empty input must be **usage (2)**, not 1: replace the `raise ValueError(...)` line with the same early-return pattern as the JSON error (`error: "learn: no record given"`, `return EXIT_USAGE`). Until Task 6 lands, create `agent_on/tasks.py` with only:

```python
"""L5 §10.1 — the task ledger as events in knowledge/tasks.jsonl (Task 6 fills this in)."""
from __future__ import annotations

from .paths import Paths, describe_copy


def run_task_verb(paths: Paths, argv: list[str]) -> tuple[dict, int]:
    return {"command": "learn", "copy": describe_copy(paths), "error": "learn task: not landed yet", "hint": "learn task lands in Task 6"}, 2
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/cli.py agent_on/tasks.py tests/agent_on/test_cli_learn.py
git commit -m "feat(agent-on): learn — validate and append one knowledge record from --json-record or stdin"
```

---

### Task 3: The seeds — `knowledge/` lands with what the repo has paid for

**Files:**
- Create: `knowledge/decisions.jsonl`, `knowledge/observations.jsonl`, `knowledge/traps.jsonl`, `knowledge/qualifications.jsonl` (empty), `knowledge/gate-runs.jsonl` (empty), `knowledge/tasks.jsonl` (empty)
- Modify: `.github/workflows/ci.yml` (one assertion)
- Test: `tests/agent_on/test_knowledge_seeds.py`

**Interfaces:**
- Produces: stable ids `decisions-D1` … `decisions-D13`, `decisions-D3-2026-08-20`, `decisions-D3-2026-09-06` (superseded chain ending in `decisions-D3`), `decisions-D7-haiku-history`, `decisions-Q8-attribution-deferred`, `decisions-Q10-dependency-ledger`, `decisions-delegate-cheaper-models`, `decisions-fix-on-contact`; observations and traps ids as listed below. `learn` mints ULIDs for everything after.

Every line below is one JSON object; write the files **exactly** (one record per line, no blank lines except that the three empty files are zero bytes). Timestamps are the dates the fact was established. Seeds do not pass through `append` (their ids are chosen); `validate_file` is their gate.

- [ ] **Step 1: Write the failing test**

`tests/agent_on/test_knowledge_seeds.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

from agent_on import knowledge  # noqa: E402
from agent_on.paths import Paths  # noqa: E402
from agent_on.schemas.knowledge import APPLIES_TO_VERBS, KINDS, validate_file  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

REQUIRED = {"decisions": ["decisions-D1", "decisions-D2", "decisions-D3", "decisions-D3-2026-08-20", "decisions-D3-2026-09-06", "decisions-D6",
                          "decisions-D13", "decisions-Q8-attribution-deferred", "decisions-delegate-cheaper-models", "decisions-fix-on-contact"],
            "observations": ["observations-2026-08-23-tokenizer-delta", "observations-2026-08-23-huihui-quality", "observations-2026-09-06-omlx-serialises",
                             "observations-2026-09-08-omlx-concurrency-per-model", "observations-2026-09-06-baseline-48312", "observations-2026-09-08-baseline-54380",
                             "observations-2026-09-07-thinking-two-arm", "observations-2026-09-08-direct-cache", "observations-2026-09-08-limits-huihui-260671"],
            "traps": ["traps-single-quoted-battery", "traps-installed-copy-selector", "traps-promotion-deadlock", "traps-budget-formula-in-code",
                      "traps-port-4000-collision", "traps-fabricated-cost-field", "traps-discovery-filter", "traps-child-env-credential",
                      "traps-exo-thunderbolt-hijack", "traps-settings-last-wins", "traps-synthetic-error-turns"]}


class SeedsTest(unittest.TestCase):
    """Read-only over the real checkout's knowledge/: the seeds are data the repo ships, and this pins their shape."""

    def setUp(self):
        self.paths = Paths(checkout=REPO, state=REPO / "does-not-exist", home=REPO / "does-not-exist")

    def test_every_kind_has_a_file_and_every_file_validates(self):
        for kind in KINDS:
            p = self.paths.knowledge_dir / f"{kind}.jsonl"
            self.assertTrue(p.exists(), p)
            self.assertEqual(validate_file(p), [], kind)

    def test_required_seed_ids_are_present_and_the_d3_chain_ends_at_d3(self):
        for kind, ids in REQUIRED.items():
            have = {r["id"] for r in knowledge.read(self.paths, kind)}
            self.assertTrue(set(ids) <= have, sorted(set(ids) - have))
        d = {r["id"]: r for r in knowledge.read(self.paths, "decisions")}
        self.assertEqual(d["decisions-D3-2026-09-06"]["supersedes"], "decisions-D3-2026-08-20")
        self.assertEqual(d["decisions-D3"]["supersedes"], "decisions-D3-2026-09-06")
        self.assertIn("decisions-D3", {r["id"] for r in knowledge.active(list(d.values()))})
        self.assertNotIn("decisions-D3-2026-09-06", {r["id"] for r in knowledge.active(list(d.values()))})

    def test_trap_targets_are_verbs_sources_routes_or_star(self):
        table = load_routes(self.paths)
        allowed = set(APPLIES_TO_VERBS) | {"*"} | set(table.sources) | set(table.routes)
        for t in knowledge.read(self.paths, "traps"):
            for a in t["applies_to"]:
                self.assertIn(a, allowed, f"{t['id']}: {a}")

    def test_observation_routes_name_a_source_of_this_system(self):
        table = load_routes(self.paths)
        for o in knowledge.read(self.paths, "observations"):
            self.assertIn(o["route"].split("/", 1)[0], set(table.sources) | {"harness"}, o["id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_knowledge_seeds.py' -v`
Expected: `AssertionError: …/knowledge/observations.jsonl` (no files).

- [ ] **Step 3: Write the seed files**

`knowledge/decisions.jsonl` (the decision text is the spec's bold statement; the rationale is one sentence from its rationale cell; `by` names who settled it):

```jsonl
{"id": "decisions-D1", "ts": "2026-09-08T00:00:00Z", "decision": "Rename to agent-on: repo, package, tower binary, config dir, state dir; claude-on survives as the Claude Code launcher shim beside it.", "rationale": "The previous name encoded an implementation; the tower never learns which harness asks, so a second harness (codex-on, Plan F) is one L6 file, not a second system.", "by": "rick, spec rev 8"}
{"id": "decisions-D2", "ts": "2026-09-07T00:00:00Z", "decision": "No proxy: nothing runs between Claude Code and the source, and no source credential is ever placed in the child environment. The launcher writes the key to a per-launch 0600 file and hands Claude Code an apiKeyHelper that reads it.", "rationale": "Every surviving source speaks /v1/messages natively (30/30 direct on OpenRouter, 6/6 on oMLX); §1.1c measured the exported key reaching the model's printenv and the transcript.", "by": "rick, spec rev 4"}
{"id": "decisions-D3-2026-08-20", "ts": "2026-08-20T00:00:00Z", "decision": "LiteLLM is unnecessary and the ChatGPT/xAI OAuth lanes should go.", "rationale": "The 2026-08-20 artifact: the gateway duplicated what Claude Code and the sources already did.", "by": "rick"}
{"id": "decisions-D3-2026-09-06", "ts": "2026-09-06T00:00:00Z", "decision": "Reversed: keep the OAuth lane and broaden it; four GPT-*-chatgpt-oauth routes packaged (00b3fa5).", "rationale": "\"까짓거 뭐, 지원하게 해보죠\" — it could be wired through LiteLLM, so it was.", "by": "rick", "supersedes": "decisions-D3-2026-08-20"}
{"id": "decisions-D3", "ts": "2026-09-07T00:00:00Z", "decision": "The ChatGPT OAuth lane is dropped; the four GPT-*-chatgpt-oauth routes are deleted in Plan D. GPT is used through Codex.", "rationale": "\"gpt는 안하면 그만 … 실제로 굳이 필요없었는데 litellm으로 붙일 수 있다고 하니까 했던거\" — it was the only source needing a translator.", "by": "rick", "supersedes": "decisions-D3-2026-09-06"}
{"id": "decisions-D4", "ts": "2026-09-07T00:00:00Z", "decision": "One implementation language, zero dependencies: one package agent_on/, Python ≥ 3.11 from PATH, standard library only; declarations in TOML; zsh survives as a ≤20-line shim.", "rationale": "An agent modifying the system should hold one language; import yaml fails on this machine's python3.", "by": "rick, spec rev 3"}
{"id": "decisions-D5", "ts": "2026-09-07T00:00:00Z", "decision": "One home per fact: versions are read from the runtime, route names live only in routes.toml, constants live once.", "rationale": "The replication-as-drift-guard pattern existed only because there were four implementations (R3).", "by": "rick"}
{"id": "decisions-D6", "ts": "2026-09-07T00:00:00Z", "decision": "Inform, don't gate: qualification results, cost models, liveness and traps are shown; they never block a launch.", "rationale": "Operated by competent agents; the old launch gates produced false confidence without preventing any observed failure.", "by": "rick"}
{"id": "decisions-D7", "ts": "2026-09-07T00:00:00Z", "decision": "Tier aliases are not user configuration: the launcher binds Claude Code's four tier slots and the subagent slot to the launch route; --sonnet/--haiku override one slot with a route on the same source.", "rationale": "Effort, context and output controls are process-global; a cross-source slot would carry the wrong budget.", "by": "rick, spec rev 3"}
{"id": "decisions-D7-haiku-history", "ts": "2026-09-07T00:00:00Z", "decision": "History behind D7: the haiku alias was a user-editable tier target in the old launcher, and a test hardcoded its target (failure 5 in §1), which broke when the alias moved.", "rationale": "Recorded so the alias is never reintroduced as configuration.", "by": "spec §1"}
{"id": "decisions-D8", "ts": "2026-09-07T00:00:00Z", "decision": "Gateway model discovery is OFF by default; --discover opts in.", "rationale": "Measured on 2.1.263: the binary keeps only ids matching /(claude|anthropic)/i — 0 on local sources, 27 paid Anthropic models on OpenRouter (§1.1b).", "by": "rick, spec rev 3"}
{"id": "decisions-D9", "ts": "2026-09-07T00:00:00Z", "decision": "No installed copy: the checkout is the installation; install links ~/.local/bin/agent-on and claude-on to <checkout>/bin/, creates the state directory and checks the interpreter.", "rationale": "The fingerprint chain and shim digest pin protected against drift that only existed because there was a copy (§1 failures 7 and 8).", "by": "rick, confirmed 2026-09-07"}
{"id": "decisions-D10", "ts": "2026-09-07T00:00:00Z", "decision": "Route names are <source>/<model>; optional short aliases live in routes.toml.", "rationale": "The source is then visible in the name (half of Q3 by convention); retires the -openrouter/-omlx suffix idiom.", "by": "rick"}
{"id": "decisions-D11", "ts": "2026-09-07T00:00:00Z", "decision": "Strangler migration in five plans (A tower, B launcher, C knowledge, D install + delete, E exo) plus F codex-on.", "rationale": "55e17e3 deleted direct mode and its rationale in one commit; irreversible big steps have failed here twice.", "by": "rick"}
{"id": "decisions-D12", "ts": "2026-09-07T00:00:00Z", "decision": "Thinking on a local model is whatever the source's template does; agent-on measures and reports its cost and does not pretend to control it. No thinking: field in routes.toml.", "rationale": "No per-request field reaches a non-Anthropic model from Claude Code; the cost is real (1.9–3.3K thinking tokens on a five-sentence task) and is what the cost model shows (§1.1a).", "by": "rick, spec rev 3"}
{"id": "decisions-D13", "ts": "2026-09-07T00:00:00Z", "decision": "Machine-written state lives in one place outside git: $XDG_STATE_HOME/agent-on/ holds routes.discovered.toml, observed.json, locks, sessions/, run/. knowledge/ is the one deliberate exception: git-tracked in the checkout, append-only, because it is meant to be read by the next session and by peers.", "rationale": "Q5 and Q2: one copy, one state root, AGENT_ON_STATE for a scratch run.", "by": "rick"}
{"id": "decisions-Q8-attribution-deferred", "ts": "2026-09-08T00:00:00Z", "decision": "Q8 (which shared ~/.claude items account for the pre-task tokens) is answered only as a total: harness_baseline_tokens per route, measured by qualify --baseline from the checkout's cwd. Per-item attribution is deferred.", "rationale": "Attribution needs a launch per shared item with the rest unlinked; the total (54,380 on 2.1.263 from this checkout, 48,312 on 2026-09-06) already decides whether a 131K route is comfortable (41%).", "by": "spec §15, Plan B acceptance"}
{"id": "decisions-Q10-dependency-ledger", "ts": "2026-09-08T00:00:00Z", "decision": "Q10 (what must change together to delete X) is answered by the tower's invariant registry (status --check lists what an action touches) and by spec §13, the deletion ledger for Plan D; a generated dependency page follows in Plan D.", "rationale": "Nothing in the repo maps dependencies today; the invariants are the executable half of that map.", "by": "spec §15"}
{"id": "decisions-delegate-cheaper-models", "ts": "2026-09-07T00:00:00Z", "decision": "Delegate mechanical stages (lookups, extraction, verbatim implementation, scoped re-review) to cheaper models — haiku for pure lookups, sonnet for structured reads and transcription — and keep judgment (spec, refutation, synthesis, final review, merge decisions) on the session's top model.", "rationale": "\"모두가 Fable 5.1일 필요는 없다고 생각합니다\": 26 top-model agents in one day hit the usage limit mid-review and eight had to be re-run; most were mechanical.", "by": "rick"}
{"id": "decisions-fix-on-contact", "ts": "2026-08-23T00:00:00Z", "decision": "A defect found in passing is work to do in the same session, not a finding to hand back; state which copy you measured; correct earlier claims in the record when a later measurement overturns them.", "rationale": "Every substantive defect this repo surfaced was found sideways (dead routes, globs matching 0 of 17 models, an installer that could not start, a promotion deadlock); its failures are quiet, so the moment something misbehaves is the cheapest moment to find them.", "by": "rick"}
```

`knowledge/observations.jsonl`:

```jsonl
{"id": "observations-2026-08-23-tokenizer-delta", "ts": "2026-08-23T00:00:00Z", "route": "omlx/Huihui-Qwen3.8-27B-oQ4e-mtp", "kind": "tokens", "values": {"prompt_tokens_thinking_on": 77, "prompt_tokens_thinking_off": 37, "template_constant": 40, "long_prompt_off": 783, "long_prompt_reference": 768, "tokenizer_spread_pct": 2}, "evidence": "Most of the earlier 819-vs-768 gap was a fixed thinking-template preamble (+40 tokens), not the tokenizer: Qwen3-VL-32B-Instruct counts 33 either way (no thinking template). The real tokenizer spread is ~2%, not 6.6%. A constant per-request offset and a percentage scale differently with prompt size. Source: config/ai-litellm/context-observations.json 2026-08-23-tokenizer-delta-was-mostly-thinking-template.", "session": null}
{"id": "observations-2026-08-23-huihui-quality", "ts": "2026-08-23T00:00:00Z", "route": "omlx/Huihui-Qwen3.8-27B-oQ4e-mtp", "kind": "quality", "values": {"task_seconds": 10.3, "outranked": "omlx/mlx-community--Qwen3-VL-32B-Instruct-4bit"}, "evidence": "With thinking off the model completed the circuit-lab interpretation task in 10.3 s and outranked Qwen3-VL-32B-Instruct-4bit on accuracy (separated a stuck-high failure from contention where the Instruct model misread; boundary, operating-region and signature rows right). Raw in ~/Projects/ls-sizing-study/results/smoke_c_arm/.", "session": null}
{"id": "observations-2026-09-06-omlx-serialises", "ts": "2026-09-06T00:00:00Z", "route": "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp", "kind": "throughput", "values": {"tok_s": 63, "serial_two_s": 3.5, "concurrent_two_s": 4.4, "pair_over_serial": 1.26}, "evidence": "Through the old proxy, 28-token prompt, 110 output tokens: two concurrent identical requests took 4.4 s wall versus ~3.5 s back to back — concurrency ~26% worse than serial on this model. Superseded in scope by observations-2026-09-08-omlx-concurrency-per-model (model-specific, not an oMLX property).", "session": null}
{"id": "observations-2026-09-08-omlx-concurrency-per-model", "ts": "2026-09-08T06:35:00Z", "route": "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp", "kind": "throughput", "values": {"huihui_mtp": {"n1_tok_s": 53, "n8_aggregate_tok_s": 83.1, "n8_speedup": 1.6}, "glm_flash_4bit": {"n1_tok_s": 25.7, "n8_aggregate_tok_s": 73.4, "n8_speedup": 2.9}, "mixed_wires_penalty": 0}, "evidence": "Direct /v1/messages on oMLX 0.6.4 (max_concurrent_requests 8, decode_fairness true), 20-token prompt, 120 output tokens, N identical requests in flight. Huihui (MTP speculative decoding) gains nothing at N=2 and 1.6× aggregate at N=8; GLM-5.3-Flash-Alis-4bit gains 2.9× at N=8. Two /v1/messages + two /v1/chat/completions on GLM took the same 8.8 s as four same-wire: Anthropic and OpenAI wires share one engine with no penalty. Consequence: size workers per (host, model), which is what the per-route concurrency probe measures.", "session": null}
{"id": "observations-2026-09-06-baseline-48312", "ts": "2026-09-06T00:00:00Z", "route": "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp", "kind": "tokens", "values": {"input_tokens": 48312, "output_tokens": 1, "wall_s": 157, "share_of_131072_pct": 37}, "evidence": "A single -p 'Reply with exactly: OK' through the old launcher spent 48,312 input tokens for 1 output token in 157 s: Claude Code's own baseline prompt before any task content. Claude Code also reported total_cost_usd 0.2416 for a free local model — its own price table, never cost telemetry (F11).", "session": null}
{"id": "observations-2026-09-08-baseline-54380", "ts": "2026-09-08T12:36:26Z", "route": "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp", "kind": "tokens", "values": {"input_tokens": 54380, "claude_code": "2.1.263", "share_of_131072_pct": 41, "glm_baseline": 56746}, "evidence": "qualify --baseline from this checkout's cwd (CLAUDE.md, memory and skills content included) on 2.1.263: 54,380 input tokens on huihui, 56,746 on openrouter/z-ai/glm-5.2. Plan B acceptance, commit 0d67776.", "session": null}
{"id": "observations-2026-09-07-thinking-two-arm", "ts": "2026-09-07T00:00:00Z", "route": "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp", "kind": "quality", "values": {"gates_direct": "6/6", "gates_via_litellm": "6/6", "thinking": "on", "thinking_tokens_five_sentence_task": "1900-3300"}, "evidence": "Two-arm test with thinking ON: all six fidelity gates pass both direct on oMLX and through LiteLLM 1.92.0. The recorded breakage was on Qwen3.5/3.6 models no longer served; the 2026-08-23 'never answers' leak was budget exhaustion on the direct wire. On the direct wire there is no per-request thinking-off switch: Claude Code sends neither thinking:{type:disabled} nor chat_template_kwargs for a non-Anthropic model (spec §1.1a, D12). On 2026-09-08 qualify measured thinking OFF on the abliterated build (thinking_block_seen false).", "session": null}
{"id": "observations-2026-09-08-direct-cache", "ts": "2026-09-08T12:38:00Z", "route": "openrouter/z-ai/glm-5.2", "kind": "cost", "values": {"glm_cache_read": [6400, 6400, 0], "deepseek_cache_read": 0, "kimi_cache_read": 0, "mimo_cache_read": 0, "omlx_cache_read": 4096, "omlx_block": 4096}, "evidence": "qualify's two-turn caching probe (~6,500-token shared prefix) on the direct wire, 2026-09-08: glm-5.2 returned 6,400 cache-read tokens twice and 0 on a third run; deepseek-v4-pro, kimi-k2.7-code and mimo-v2.5 returned 0; oMLX returned 4,096 (its prefix cache works in 4,096-token blocks). Recorded as measured, never inferred from a price table.", "session": null}
{"id": "observations-2026-09-08-limits-huihui-260671", "ts": "2026-09-08T13:05:00Z", "route": "omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp", "kind": "tokens", "values": {"verified_input": 260671, "advertised": 262144, "configured": 131072, "probes": 9, "wall_min": 30}, "evidence": "qualify --limits bisected the enforced input boundary to 260,671 tokens in 9 probes (30 min of prefill): oMLX applies the model's native 262,144 for this model, not the 131,072 the route declares. cost_model.context stays min(declared, verified) = 131,072 (§7: verified only lowers).", "session": null}
```

`knowledge/traps.jsonl`:

```jsonl
{"id": "traps-single-quoted-battery", "ts": "2026-09-07T00:00:00Z", "trap": "A verification battery written as one single-quoted zsh -fc string under set -e reports ok for not having checked.", "mechanism": "An apostrophe inside the string closes it and truncates the battery silently; negated pipelines (! cmd) are exempt from ERR_EXIT, so bare assertions cannot fail; skips print ok:.", "avoid": "Predicates are functions in one language with three results (pass/fail/skip) and every skip listed; the gate writes last_gate_run with skipped_reasons.", "evidence": "spec §1 R4 and failure 3; scripts/check.zsh in the old path", "found_by": "rev-3 review", "applies_to": ["gate"]}
{"id": "traps-installed-copy-selector", "ts": "2026-08-20T00:00:00Z", "trap": "Sourcing the old lib.zsh from a checkout silently measured the installed copy.", "mechanism": "lib.zsh force-overrode AI_LITELLM_CONFIG and the harness dir to the installed prefix unless AI_LITELLM_HOME pointed at the checkout; three confident conclusions in one session were wrong because of it.", "avoid": "There is no installed copy any more (D9). Every command prints copy.* (checkout, commit, dirty, state); state which copy you measured before reporting a dynamic measurement.", "evidence": "memory note measure-the-installed-copy-not-the-checkout; spec §1 failure 8", "found_by": "rick's session 2026-08-20", "applies_to": ["*"]}
{"id": "traps-promotion-deadlock", "ts": "2026-08-23T00:00:00Z", "trap": "Promoting a discovered model to a packaged route deadlocked the old installer on a duplicate.", "mechanism": "The discovered and the packaged declaration named the same model; the installer refused the duplicate and could not proceed.", "avoid": "A packaged route shadows its discovered twin at read time and the next sync drops the twin (§6); route.unique is checked after every write.", "evidence": "spec §1 failure 4 (twice)", "found_by": "rick's session 2026-08-23", "applies_to": ["add", "sync"]}
{"id": "traps-budget-formula-in-code", "ts": "2026-08-20T00:00:00Z", "trap": "Hand-computing Claude Code's context budget, or mistaking the 200K cost guardrail for a context window.", "mechanism": "The old derivation lived in four implementations in three languages; the 200000 figure was a spend guardrail using a 4-chars-per-token estimate, not a window.", "avoid": "cost_model.context is min(declared, verified) computed by schemas.observed.compute_context; CLAUDE_CODE_MAX_CONTEXT_TOKENS is set from it at launch; never arithmetic on a remembered context size.", "evidence": "memory note budget-formula-lives-in-code-not-docs", "found_by": "rick's session 2026-08-20", "applies_to": ["launch", "qualify"]}
{"id": "traps-port-4000-collision", "ts": "2026-08-20T00:00:00Z", "trap": "The old gate needed port 4000 free and failed with the advice 'run sync' when a proxy held it; that proxy and oMLX on :8000 were shared by other sessions.", "mechanism": "check.zsh isolated HOME but not the port; the error text pointed at the wrong cause.", "avoid": "The proxy is stopped for good (2026-09-08). Never restart oMLX on :8000 to run a check — it evicts a loaded model every consumer pays to reload; the agent-on gate uses an ephemeral mock port.", "evidence": "memory note measure-the-installed-copy-not-the-checkout (environment trap); spec §1 failure 9", "found_by": "rick's session 2026-08-20", "applies_to": ["gate", "omlx"]}
{"id": "traps-fabricated-cost-field", "ts": "2026-09-06T00:00:00Z", "trap": "Claude Code's total_cost_usd is its own price table, not what the route cost.", "mechanism": "It reported $0.24 for a free local model; a gateway that copied it would fabricate spend.", "avoid": "cost.not_copied: no L2 field is sourced from total_cost_usd; cost_usd comes from the route's price snapshot at launch, and is \"unknown\" when a turn's price cannot be restored.", "evidence": "spec §1 failure 11, F11; observations-2026-09-06-baseline-48312", "found_by": "rick's session 2026-09-06", "applies_to": ["launch", "status"]}
{"id": "traps-discovery-filter", "ts": "2026-09-07T00:00:00Z", "trap": "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1 does not list the bound source's catalog.", "mechanism": "Claude Code 2.1.263 fetches /v1/models?limit=1000 and keeps only ids matching /(claude|anthropic)/i: 0 on local sources, 27 paid Anthropic models on OpenRouter — the escape hatch the tier pin exists to close.", "avoid": "Discovery is off by default (D8); --discover opts in knowingly.", "evidence": "spec §1.1b", "found_by": "rev-3 measurement", "applies_to": ["launch"]}
{"id": "traps-child-env-credential", "ts": "2026-09-07T00:00:00Z", "trap": "Exporting the source key as ANTHROPIC_AUTH_TOKEN puts it in every Bash-tool child, the model's printenv and the on-disk transcript.", "mechanism": "Claude Code passes its environment to tool subprocesses and records command output in the transcript.", "avoid": "The launcher writes the key to a per-launch 0600 file and hands Claude Code an apiKeyHelper; every source's auth_env, the routing denylist and every ANTHROPIC_*/CLAUDE_* variable except the output cap are scrubbed; credential.not_in_child_env checks it for every route on every launch. Measured NONE in both key-supply modes on 2026-09-08.", "evidence": "spec §1.1c, D2; Plan B acceptance step 5", "found_by": "rev-3 measurement, rev-4 review", "applies_to": ["launch"]}
{"id": "traps-exo-thunderbolt-hijack", "ts": "2026-08-26T00:00:00Z", "trap": "exo's launchd daemon took over the Thunderbolt service and reverted static TB IPs to DHCP mid-benchmark, breaking rank 1 of the oMLX tensor-parallel pair.", "mechanism": "exo manages networking on the link that oMLX tensor-parallel (jaccl ring, 13.86 GB/s) uses.", "avoid": "If exo returns it must not manage Thunderbolt networking; the exo source row stays unmeasured until then (S3).", "evidence": "spec §5 exo row; mac-cluster/docs/CLUSTER_OPERATIONS.md", "found_by": "cluster bench 2026-08-26", "applies_to": ["exo", "omlx-tp2"]}
{"id": "traps-settings-last-wins", "ts": "2026-09-08T12:38:00Z", "trap": "Claude Code 2.1.263 keeps only the last --settings on its command line.", "mechanism": "A user --settings after the launcher's displaced the apiKeyHelper file: 'Not logged in · Please run /login'.", "avoid": "The launcher folds a user --settings object into the per-launch settings file on a keyed route (its apiKeyHelper wins, with a warning) and passes exactly one --settings; on a keyless route the user's flag passes through.", "evidence": "Plan B acceptance step 4, fix F1 (commit e2d079f)", "found_by": "Plan B acceptance 2026-09-08", "applies_to": ["launch"]}
{"id": "traps-synthetic-error-turns", "ts": "2026-09-08T14:00:00Z", "trap": "Claude Code records API errors as assistant turns with model <synthetic> and zero usage.", "mechanism": "429s, provider errors and 'prompt too long' appear as type: assistant lines with a message.id; priced naively they make a run's cost unknown and can record a zero baseline as measured.", "avoid": "read_transcript skips <synthetic> lines whose usage is all zero; a zero first request is unmeasured (None), never 0.", "evidence": "Plan B final review, fix item 1 (commit 0b7a962); 67 transcripts under ~/.claude/projects carried them", "found_by": "Plan B final review 2026-09-08", "applies_to": ["launch", "qualify"]}
```

`knowledge/qualifications.jsonl`, `knowledge/gate-runs.jsonl`, `knowledge/tasks.jsonl`: create empty (zero bytes): `: > knowledge/qualifications.jsonl` etc.

`.github/workflows/ci.yml` — in the assertion step add, after the credential line:

```python
          assert g["last_gate_run"]["invariants"]["knowledge.typed"] == "pass"
```

- [ ] **Step 4: Run the tests and the invariant on the real tree**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4; ./bin/agent-on status --check | grep knowledge`
Expected: all pass; `pass knowledge.typed: 6 file(s) valid`.

- [ ] **Step 5: Commit**

```bash
git add knowledge/ .github/workflows/ci.yml tests/agent_on/test_knowledge_seeds.py
git commit -m "feat(agent-on): knowledge/ lands with its seeds — 21 decisions, 9 observations, 11 traps; knowledge.typed is real"
```

---

### Task 4: `qualify` and the gate write their durable twins

**Files:**
- Modify: `agent_on/qualify.py` (the knowledge block), `agent_on/gate.py`
- Test: extend `tests/agent_on/test_qualify_run.py`, `tests/agent_on/test_gate.py`

**Interfaces:**
- Consumes: `knowledge.append`.
- Produces: `run_qualify` appends, when `paths.knowledge_dir.is_dir()`, its qualification record **through `knowledge.append`** (replacing the hand-written open/append) and one observation `{"route", "kind": "throughput", "values": {"tok_s", "concurrency", "caching", "thinking_observed"}, "evidence": "qualify <qualification id>", "session": null}`; `doc["knowledge"]` becomes `{"qualification": <id>, "observation": <id>}`. `run_gate` appends, when the dir exists, `gate-runs` `{commit, result, tests, verifiers, invariants, skipped_reasons, mock_port}` (same values as `last_gate_run`) and returns `doc["knowledge"] = {"gate_run": <id>} | None`. When `knowledge/` is absent (a bare sandbox) nothing is written and `doc["knowledge"]` is `None` — never an error.

- [ ] **Step 1: Write the failing tests**

Append to `tests/agent_on/test_qualify_run.py` (inside `RunQualifyTest`; reuse its imports and `CATALOG`):

```python
    def test_qualify_appends_its_qualification_and_a_throughput_observation_when_knowledge_exists(self):
        from agent_on import knowledge
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            self.assertIsNone(run_qualify(sb.paths, "a", env={}, timeout=10).get("knowledge"))          # no knowledge/: nothing written, no error
            sb.paths.knowledge_dir.mkdir()
            doc = run_qualify(sb.paths, "a", env={}, timeout=10)
            q = knowledge.read(sb.paths, "qualifications")
            o = knowledge.read(sb.paths, "observations")
            self.assertEqual(len(q), 1)
            self.assertEqual(doc["knowledge"], {"qualification": q[0]["id"], "observation": o[0]["id"]})
            self.assertEqual(q[0]["route"], "mock/alpha")
            self.assertEqual(o[0]["kind"], "throughput")
            self.assertEqual(o[0]["values"]["caching"], True)
            self.assertIn(q[0]["id"], o[0]["evidence"])
```

Append to `tests/agent_on/test_gate.py` (read the file first for its sandbox idiom; the existing gate test runs `run_gate` against a sandbox with `AGENT_ON_GATE_INNER` set so the inner unit tests are skipped — reuse exactly that):

```python
    def test_gate_writes_the_gate_runs_twin_only_when_knowledge_exists(self):
        from agent_on import knowledge
        # same sandbox + AGENT_ON_GATE_INNER idiom as the test above
        ... doc = run_gate(sb.paths); self.assertIsNone(doc["knowledge"])
        sb.paths.knowledge_dir.mkdir()
        doc = run_gate(sb.paths)
        recs = knowledge.read(sb.paths, "gate-runs")
        self.assertEqual(doc["knowledge"], {"gate_run": recs[0]["id"]})
        self.assertEqual(recs[0]["result"], doc["last_gate_run"]["result"])
        self.assertEqual(recs[0]["invariants"], doc["last_gate_run"]["invariants"])
        self.assertEqual(recs[0]["verifiers"], {"declared": [], "ran": []})
```

(The `...` marks the sandbox setup copied from the neighbouring test; the assertions are exact.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_qualify_run.py' -v; python3.13 -m unittest discover -s tests/agent_on -p 'test_gate.py' -v`
Expected: `KeyError: 'knowledge'` / the old `doc["knowledge"]` string.

- [ ] **Step 3: Write the code**

`agent_on/qualify.py` — replace the block from `kdir = paths.checkout / "knowledge"` to `doc["knowledge"] = …` with:

```python
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
```

and drop the now-unused `validate_record`/`ulid` imports if nothing else uses them (check with grep).

`agent_on/gate.py` — after `update_observed(...)`:

```python
    kn = None
    if paths.knowledge_dir.is_dir():                                               # the durable twin of last_gate_run (§10, Q4)
        from .knowledge import append
        rec = append(paths, "gate-runs", {"commit": record["commit"], "result": record["result"], "tests": record["tests"],
                                          "verifiers": record["verifiers"], "invariants": record["invariants"],
                                          "skipped_reasons": record["skipped_reasons"], "mock_port": record["mock_port"]}, now=record["at"])
        kn = {"gate_run": rec["id"]}
    return {"command": "gate", "copy": describe_copy(paths), "tests": tests, "smoke": smoke,
            "invariants": [r.as_dict() for r in results], "last_gate_run": record, "result": record["result"], "knowledge": kn}
```

Update the module docstring's "(lands in Plan C)" remark. In `cli.render_gate` add, when `doc["knowledge"]`, a line `knowledge: gate-runs <id>`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/qualify.py agent_on/gate.py agent_on/cli.py tests/agent_on/test_qualify_run.py tests/agent_on/test_gate.py
git commit -m "feat(agent-on): qualify and the gate append their knowledge twins (qualifications + throughput observation, gate-runs)"
```

---

### Task 5: `status` and the launch show the knowledge for the action in hand; the launch records a cost observation

**Files:**
- Modify: `agent_on/status.py`, `agent_on/harness.py`, `agent_on/cli.py` (`render_launch`)
- Test: extend `tests/agent_on/test_status.py`, `tests/agent_on/test_harness_launch.py`

**Interfaces:**
- Consumes: `knowledge.knowledge_view`, `knowledge.append`.
- Produces:
  - `build_status`: each `routes.<name>` gains `"knowledge": knowledge_view(paths, route=<name>, source=<source>, action="status", n=3)`. `render_text` prints, after the `last session` line, one line per observation `  observation <ts> <kind>: <values as compact json>` and one per trap `  trap: <trap> — avoid: <avoid>`.
  - `run_launch`: `doc["traps"] = knowledge_view(..., action="launch")["traps"]` computed before the cost line (dry run included); `render_launch` prints `trap: <trap> — avoid: <avoid>` lines after the warnings. After a successful read-back (`rec` has `this_run`) and when `knowledge/` exists, append one observation `{"route", "kind": "cost", "values": {"turns", "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "cost_usd"}, "evidence": "session <session id> run <launch_id>", "session": <session id>}`; `doc["knowledge"] = {"observation": <id>} | None`. Dry runs and read-back-skipped runs write nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/agent_on/test_status.py` (read the file for its sandbox idiom and `render_text` import):

```python
    def test_status_shows_the_last_observations_and_the_traps_for_the_route(self):
        from agent_on import knowledge
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            for i in range(4):
                knowledge.append(sb.paths, "observations", {"route": "mock/alpha", "kind": "cost", "values": {"i": i}, "evidence": "e"})
            knowledge.append(sb.paths, "traps", {"trap": "mind the gap", "mechanism": "m", "avoid": "step over", "evidence": "e", "found_by": "f", "applies_to": ["mock"]})
            knowledge.append(sb.paths, "traps", {"trap": "launch only", "mechanism": "m", "avoid": "a", "evidence": "e", "found_by": "f", "applies_to": ["launch"]})
            doc = build_status(sb.paths, route="a")
            k = doc["routes"]["mock/alpha"]["knowledge"]
            self.assertEqual([o["values"]["i"] for o in k["observations"]], [1, 2, 3])
            self.assertEqual([t["trap"] for t in k["traps"]], ["mind the gap"])
            text = render_text(doc)
            self.assertIn("trap: mind the gap — avoid: step over", text)
            self.assertIn('observation', text)
            self.assertNotIn("launch only", text)
```

Append to `tests/agent_on/test_harness_launch.py` inside `LaunchTest` (use its `self.launch(sb, name, args, env=None, **kw)` helper, which sets `FAKE_CLAUDE_OUT`, `claude_bin=FAKE`, `cwd`, `probe_timeout` and `announce=False`; `BASE` is an unreachable source, so `route.served` skips and the launch proceeds):

```python
    def test_launch_shows_launch_traps_and_records_a_cost_observation_after_read_back(self):
        from agent_on import knowledge
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            knowledge.append(sb.paths, "traps", {"trap": "launch trap", "mechanism": "m", "avoid": "a", "evidence": "e", "found_by": "f", "applies_to": ["launch"]})
            knowledge.append(sb.paths, "traps", {"trap": "status trap", "mechanism": "m", "avoid": "a", "evidence": "e", "found_by": "f", "applies_to": ["status"]})
            dry, _ = self.launch(sb, "a", ["-p", "hi"], dry_run=True)
            self.assertEqual([t["trap"] for t in dry["traps"]], ["launch trap"])
            self.assertIsNone(dry.get("knowledge"))
            doc, _ = self.launch(sb, "a", ["-p", "hi"])
            self.assertEqual([t["trap"] for t in doc["traps"]], ["launch trap"])
            obs = knowledge.read(sb.paths, "observations")
            self.assertEqual(doc["knowledge"], {"observation": obs[-1]["id"]})
            self.assertEqual(obs[-1]["kind"], "cost")
            self.assertEqual(obs[-1]["session"], doc["session"]["id"])
            self.assertEqual(obs[-1]["values"]["turns"], doc["last_session"]["this_run"]["turns"])
            self.assertEqual(obs[-1]["values"]["cost_usd"], doc["last_session"]["this_run"]["cost_usd"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_status.py' -v; python3.13 -m unittest discover -s tests/agent_on -p 'test_harness_launch.py' -v`
Expected: `KeyError: 'knowledge'` / `KeyError: 'traps'`.

- [ ] **Step 3: Write the code**

`agent_on/status.py` — in `build_status`, after `doc["routes"] = {...}`:

```python
        for n, v in doc["routes"].items():
            v["knowledge"] = knowledge_view(paths, route=n, source=ctx.routes.routes[n].source, action="status")
```

(import `from .knowledge import knowledge_view`, and add `import json` — `status.py` has none today). In `render_text`, after the `last session` block:

```python
            k = v.get("knowledge") or {}
            for o in k.get("observations", []):
                lines.append(f"  observation {o['ts']} {o['kind']}: {json.dumps(o['values'], sort_keys=True, ensure_ascii=False)}")
            for t in k.get("traps", []):
                lines.append(f"  trap: {t['trap']} — avoid: {t['avoid']}")
```

`agent_on/harness.py` — in `run_launch`, right after `warnings: list[str] = []`:

```python
    traps = knowledge_view(paths, route=route.name, source=route.source, action="launch")["traps"]   # D6: shown, never gating
```

add `"traps": traps` to `doc`, and after `doc.update({"exit_code": code, "last_session": rec, ...})`:

```python
    doc["knowledge"] = None
    if paths.knowledge_dir.is_dir() and "this_run" in rec:
        tr = rec["this_run"]
        u = tr["usage"]
        o = knowledge_append(paths, "observations", {"route": route.name, "kind": "cost",
                                                     "values": {"turns": tr["turns"], "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                                                                "cache_read_input_tokens": u["cache_read_input_tokens"], "cache_creation_input_tokens": u["cache_creation_input_tokens"],
                                                                "cost_usd": tr["cost_usd"]},
                                                     "evidence": f"session {session_id} run {launch_id}", "session": session_id}, now=ended)
        doc["knowledge"] = {"observation": o["id"]}
```

with `from .knowledge import append as knowledge_append, knowledge_view` at the top (no cycle: `knowledge` imports `paths`, `state`, `ids`, `util`, `schemas` only). `cli.render_launch`: after the warnings, `lines += [f"trap: {t['trap']} — avoid: {t['avoid']}" for t in doc.get("traps", [])]`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/status.py agent_on/harness.py agent_on/cli.py tests/agent_on/test_status.py tests/agent_on/test_harness_launch.py
git commit -m "feat(agent-on): status and the launch show the route's last observations and the traps for the action; the launch records its cost"
```

---

### Task 6: The task ledger as events — `learn task create|handoff|complete|show|list|prompt`

**Files:**
- Modify: `agent_on/tasks.py` (replace the stub), `agent_on/schemas/knowledge.py` (task event fields)
- Test: `tests/agent_on/test_tasks.py`

**Interfaces:**
- Consumes: `knowledge.append/read`, `ids.ulid`, `utc_now`.
- Produces (`agent_on/tasks.py`):
  - `TASK_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}-[0-9a-f]{6}")`, `MAX_TEXT = 16_384`, `MAX_EVIDENCE = 8_192` (verbatim from `scripts/task-ledger.py`).
  - Events in `tasks.jsonl` (all carry `task_id`, `event`): `created {name, goal, worktree}`, `handoff {index, from_route, to_route, objective, summary, commit, tests}`, `launched {index, launch_id, route}`, `completed {index, summary, commit, tests, close}`.
  - `fold(events) -> dict[str, dict]` — per task: `{"id", "name", "goal", "worktree", "status": "active"|"completed", "created", "updated", "closed_summary", "handoffs": [ {"index", "from_route", "to_route", "objective", "summary", "commit", "tests", "status": "pending"|"launched"|"completed", "created", "launched", "launch_id", "completed_at", "result_summary", "result_commit", "result_tests"} ]}`.
  - `create(paths, name, goal, worktree) -> dict` (the folded task), `handoff(paths, task_id, *, to_route, objective, from_route=None, summary=None, commit=None, tests=None) -> dict` (the handoff), `complete(paths, task_id, *, summary, handoff="latest", commit=None, tests=None, close=False) -> dict`, `launched(paths, task_id, *, handoff="latest", launch_id, route) -> dict`, `load(paths, task_id) -> dict`, `select_handoff(task, requested) -> dict`, `render_prompt(task, handoff) -> str` — the old `prompt_for` text verbatim with `claude-litellm` → `agent-on` and the field names above.
  - Rules ported from the old ledger: `limited()` text bounds; a handoff on a completed task is a `ValueError`; `to_route` must resolve in `routes.toml` (`load_routes(paths).resolve`), the worktree must be a directory; `complete` on a handoff already completed is a `ValueError`; every `ValueError` message starts with `learn task:`.
  - `run_task_verb(paths, argv) -> tuple[dict, int]` — an `argparse` parser over `create|handoff|complete|show|list|prompt`; returns `(doc, exit)` with `doc["text"]` for the text view; errors are `ValueError` (caught by `cli.main`'s envelope → exit 1) except usage (2).
  - `schemas.knowledge`: `TASK_EVENTS = {"created": ("name", "goal", "worktree"), "handoff": ("index", "from_route", "to_route", "objective", "summary", "commit", "tests"), "launched": ("index", "launch_id", "route"), "completed": ("index", "summary", "commit", "tests", "close")}`; `validate_record("tasks", …)` requires `TASK_ID.fullmatch(task_id)` (import the pattern from `agent_on.tasks`? no — cycles: keep the regex in `schemas/knowledge.py` as `TASK_ID` and have `tasks.py` import it from there) and the event's fields.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_tasks.py`:

```python
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import cli, knowledge, tasks  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402

BASE = "http://127.0.0.1:1"


class LedgerTest(unittest.TestCase):
    def test_create_handoff_launched_complete_lifecycle_is_a_fold_over_events(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "Gateway review", "Review the migration", str(wt))
            self.assertRegex(t["id"], tasks.TASK_ID.pattern)
            self.assertEqual(t["status"], "active")
            h = tasks.handoff(sb.paths, t["id"], to_route="a", objective="Run the focused tests", from_route=None, summary="Migration done", commit="abc", tests="31 ok")
            self.assertEqual((h["index"], h["to_route"], h["status"]), (1, "mock/alpha", "pending"))     # alias resolved to the route name
            self.assertEqual(tasks.launched(sb.paths, t["id"], launch_id="01LAUNCH", route="mock/alpha")["status"], "launched")
            done = tasks.complete(sb.paths, t["id"], summary="Reviewed", commit="def", tests="32 ok", close=True)
            self.assertEqual(done["status"], "completed")
            self.assertEqual(done["closed_summary"], "Reviewed")
            self.assertEqual(done["handoffs"][0]["result_commit"], "def")
            events = knowledge.read(sb.paths, "tasks")
            self.assertEqual([e["event"] for e in events], ["created", "handoff", "launched", "completed"])
            self.assertTrue(all(e["id"].startswith("tasks-") for e in events))
            with self.assertRaises(ValueError):
                tasks.handoff(sb.paths, t["id"], to_route="a", objective="again")                       # closed task
            with self.assertRaises(ValueError):
                tasks.complete(sb.paths, t["id"], summary="twice")                                       # handoff already completed

    def test_handoff_route_must_exist_and_worktree_must_be_a_directory_and_text_is_bounded(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            with self.assertRaises(ValueError):
                tasks.create(sb.paths, "x", "goal", str(sb.root / "missing"))
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "goal", str(wt))
            with self.assertRaises(KeyError):
                tasks.handoff(sb.paths, t["id"], to_route="nope/nothing", objective="o")
            with self.assertRaises(ValueError):
                tasks.create(sb.paths, "x", "g" * (tasks.MAX_TEXT + 1), str(wt))
            self.assertEqual(knowledge.read(sb.paths, "tasks")[-1]["event"], "created")                 # nothing written by the failures

    def test_prompt_renders_the_bounded_handoff(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "Ship it", str(wt))
            tasks.handoff(sb.paths, t["id"], to_route="a", objective="Do the thing", summary="Context here", commit="abc")
            task = tasks.load(sb.paths, t["id"])
            p = tasks.render_prompt(task, tasks.select_handoff(task, "latest"))
            for needle in ("worker session 1 for agent-on task", "Ship it", str(wt), "To route: mock/alpha", "Do the thing", "Context here", "Commit/base: abc",
                           "Do not assume the previous model transcript"):
                self.assertIn(needle, p)
            with self.assertRaises(ValueError):
                tasks.select_handoff(task, "7")

    def test_task_event_schema_is_enforced_by_learn(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "tasks", {"task_id": "bad id", "event": "created", "name": "n", "goal": "g", "worktree": "w"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "tasks", {"task_id": "20260908T000000Z-x-abcdef", "event": "created", "name": "n"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "tasks", {"task_id": "20260908T000000Z-x-abcdef", "event": "vanished"})


class CliTest(unittest.TestCase):
    def run_cli(self, sb, argv):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "AGENT_ON_STATE": str(sb.paths.state), "AGENT_ON_CHECKOUT": str(sb.paths.checkout)}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
            code = cli.main(["--json", "learn", "task", *argv])
        return code, json.loads(out.getvalue())

    def test_learn_task_verbs_through_the_cli(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            code, doc = self.run_cli(sb, ["create", "Gateway review", "--goal", "Review", "--worktree", str(wt)])
            self.assertEqual(code, 0, doc)
            tid = doc["task"]["id"]
            code, doc = self.run_cli(sb, ["handoff", tid, "--to", "a", "--objective", "Run tests", "--summary", "s"])
            self.assertEqual(code, 0, doc)
            code, doc = self.run_cli(sb, ["prompt", tid])
            self.assertIn("Run tests", doc["prompt"])
            self.assertEqual(doc["route"], "mock/alpha")
            self.assertEqual(doc["worktree"], str(wt))
            code, doc = self.run_cli(sb, ["complete", tid, "--summary", "done", "--close"])
            self.assertEqual(doc["task"]["status"], "completed")
            code, doc = self.run_cli(sb, ["list"])
            self.assertEqual([t["id"] for t in doc["tasks"]], [tid])
            code, doc = self.run_cli(sb, ["show", tid])
            self.assertEqual(doc["task"]["handoffs"][0]["status"], "completed")
            code, doc = self.run_cli(sb, ["show", "20260908T000000Z-nope-abcdef"])
            self.assertEqual(code, 1)
            code, doc = self.run_cli(sb, ["bogus"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_tasks.py' -v`
Expected: `AttributeError: module 'agent_on.tasks' has no attribute 'create'`.

- [ ] **Step 3: Write the code**

`agent_on/schemas/knowledge.py` — add:

```python
TASK_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}-[0-9a-f]{6}")
TASK_EVENTS: dict[str, tuple[str, ...]] = {
    "created": ("name", "goal", "worktree"),
    "handoff": ("index", "from_route", "to_route", "objective", "summary", "commit", "tests"),
    "launched": ("index", "launch_id", "route"),
    "completed": ("index", "summary", "commit", "tests", "close"),
}
```

and in `validate_record`:

```python
    if kind == "tasks":
        if not (isinstance(rec["task_id"], str) and TASK_ID.fullmatch(rec["task_id"])):
            raise SchemaError("knowledge.record", f"tasks: invalid task_id {rec['task_id']!r}")
        if rec["event"] not in TASK_EVENTS:
            raise SchemaError("knowledge.record", f"tasks: event must be one of {sorted(TASK_EVENTS)}, got {rec['event']!r}")
        missing = [k for k in TASK_EVENTS[rec["event"]] if k not in rec]
        if missing:
            raise SchemaError("knowledge.record", f"tasks/{rec['event']}: missing {missing}")
```

`agent_on/tasks.py`:

```python
"""L5 §10.1 — the task ledger (PR #12) as events in knowledge/tasks.jsonl. Current state is the fold; `claude-on
<route> --task <id>` injects the rendered handoff prompt exactly as the old `task launch` did."""
from __future__ import annotations

import argparse
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from .knowledge import append, read
from .paths import Paths, describe_copy
from .schemas.knowledge import TASK_ID
from .schemas.routes import load_routes
from .util import utc_now

MAX_TEXT = 16_384
MAX_EVIDENCE = 8_192


def limited(value: str | None, label: str, maximum: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError(f"learn task: {label} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"learn task: {label} exceeds {maximum} characters")
    return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48].rstrip("-") or "task"


def fold(events: list[dict]) -> dict[str, dict]:
    """Event-sourced: replay tasks.jsonl in order; later events win."""
    tasks: dict[str, dict] = {}
    for e in events:
        t = tasks.get(e["task_id"])
        if e["event"] == "created":
            tasks[e["task_id"]] = {"id": e["task_id"], "name": e["name"], "goal": e["goal"], "worktree": e["worktree"], "status": "active",
                                   "created": e["ts"], "updated": e["ts"], "closed_summary": None, "handoffs": []}
            continue
        if t is None:
            continue                                                               # an event for an unknown task is ignored, not fatal
        t["updated"] = e["ts"]
        if e["event"] == "handoff":
            t["handoffs"].append({"index": e["index"], "from_route": e["from_route"], "to_route": e["to_route"], "objective": e["objective"],
                                  "summary": e["summary"], "commit": e["commit"], "tests": e["tests"], "status": "pending", "created": e["ts"],
                                  "launched": None, "launch_id": None, "completed_at": None, "result_summary": None, "result_commit": None, "result_tests": None})
        elif e["event"] == "launched":
            h = t["handoffs"][e["index"] - 1]
            h.update({"status": "launched", "launched": e["ts"], "launch_id": e["launch_id"]})
        elif e["event"] == "completed":
            h = t["handoffs"][e["index"] - 1]
            h.update({"status": "completed", "completed_at": e["ts"], "result_summary": e["summary"], "result_commit": e["commit"], "result_tests": e["tests"]})
            if e["close"]:
                t["status"], t["closed_summary"] = "completed", e["summary"]
    return tasks


def load(paths: Paths, task_id: str) -> dict:
    if not TASK_ID.fullmatch(task_id):
        raise ValueError(f"learn task: invalid task id: {task_id}")
    t = fold(read(paths, "tasks")).get(task_id)
    if t is None:
        raise ValueError(f"learn task: no such task: {task_id}")
    return t


def select_handoff(task: dict, requested: str) -> dict:
    hs = task["handoffs"]
    if not hs:
        raise ValueError("learn task: task has no handoff; add one before launching")
    if requested == "latest":
        return hs[-1]
    try:
        i = int(requested)
    except ValueError:
        raise ValueError("learn task: handoff must be 'latest' or a positive integer") from None
    if i < 1 or i > len(hs):
        raise ValueError(f"learn task: handoff does not exist: {requested}")
    return hs[i - 1]


def create(paths: Paths, name: str, goal: str, worktree: str) -> dict:
    title, goal_t = limited(name, "name", 256), limited(goal, "goal")
    wt = Path(worktree).expanduser().resolve()
    if not wt.is_dir():
        raise ValueError(f"learn task: worktree is not a directory: {wt}")
    task_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{slugify(title)}-{secrets.token_hex(3)}"
    append(paths, "tasks", {"task_id": task_id, "event": "created", "name": title, "goal": goal_t, "worktree": str(wt)})
    return load(paths, task_id)


def handoff(paths: Paths, task_id: str, *, to_route: str, objective: str, from_route: str | None = None,
            summary: str | None = None, commit: str | None = None, tests: str | None = None) -> dict:
    t = load(paths, task_id)
    if t["status"] != "active":
        raise ValueError("learn task: cannot add a handoff to a closed task")
    route = load_routes(paths).resolve(to_route).name                             # KeyError → the CLI's usage envelope
    rec = {"task_id": task_id, "event": "handoff", "index": len(t["handoffs"]) + 1, "from_route": limited(from_route, "from route", 256),
           "to_route": route, "objective": limited(objective, "objective"), "summary": limited(summary, "summary"),
           "commit": limited(commit, "commit", 512), "tests": limited(tests, "tests", MAX_EVIDENCE)}
    append(paths, "tasks", rec)
    return load(paths, task_id)["handoffs"][-1]


def launched(paths: Paths, task_id: str, *, launch_id: str, route: str, handoff: str = "latest") -> dict:
    t = load(paths, task_id)
    h = select_handoff(t, handoff)
    append(paths, "tasks", {"task_id": task_id, "event": "launched", "index": h["index"], "launch_id": launch_id, "route": route})
    return load(paths, task_id)["handoffs"][h["index"] - 1]


def complete(paths: Paths, task_id: str, *, summary: str, handoff: str = "latest", commit: str | None = None,
             tests: str | None = None, close: bool = False) -> dict:
    t = load(paths, task_id)
    h = select_handoff(t, handoff)
    if h["status"] == "completed":
        raise ValueError(f"learn task: handoff {h['index']} is already completed")
    append(paths, "tasks", {"task_id": task_id, "event": "completed", "index": h["index"], "summary": limited(summary, "summary"),
                            "commit": limited(commit, "commit", 512), "tests": limited(tests, "tests", MAX_EVIDENCE), "close": bool(close)})
    return load(paths, task_id)


def render_prompt(task: dict, h: dict) -> str:
    evidence = [s for s in ((f"- Commit/base: {h['commit']}" if h.get("commit") else None), (f"- Test evidence: {h['tests']}" if h.get("tests") else None)) if s]
    evidence_text = "\n".join(evidence) if evidence else "- No commit or test evidence recorded."
    return f"""You are worker session {h['index']} for agent-on task {task['id']}.

Task goal:
{task['goal']}

Worktree:
{task['worktree']}

Model-session handoff:
- From route: {h.get('from_route') or 'unassigned/initial'}
- To route: {h['to_route']}
- Objective: {h['objective']}

Prior decisions and context:
{h.get('summary') or 'No prior-session summary was supplied.'}

Recorded evidence:
{evidence_text}

Working contract:
1. Work only on the objective above and inspect the current worktree before changing it.
2. Preserve unrelated user changes and treat the worktree, commit, and tests as source of truth.
3. Do not assume the previous model transcript or token budget is available.
4. Before exiting, report Outcome, Changes, Tests, Risks, and Recommended next handoff.
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-on learn task", add_help=True)
    sub = p.add_subparsers(dest="verb", required=True)
    c = sub.add_parser("create"); c.add_argument("name"); c.add_argument("--goal", required=True); c.add_argument("--worktree", default=None)
    h = sub.add_parser("handoff"); h.add_argument("task_id"); h.add_argument("--to", required=True); h.add_argument("--objective", required=True)
    h.add_argument("--from", dest="from_route"); h.add_argument("--summary"); h.add_argument("--commit"); h.add_argument("--tests")
    d = sub.add_parser("complete"); d.add_argument("task_id"); d.add_argument("--handoff", default="latest"); d.add_argument("--summary", required=True)
    d.add_argument("--commit"); d.add_argument("--tests"); d.add_argument("--close", action="store_true")
    s = sub.add_parser("show"); s.add_argument("task_id")
    sub.add_parser("list")
    r = sub.add_parser("prompt"); r.add_argument("task_id"); r.add_argument("--handoff", default="latest")
    return p


def run_task_verb(paths: Paths, argv: list[str]) -> tuple[dict, int]:
    """`agent-on learn task <verb> …`: returns (envelope, exit). Usage errors are exit 2; rule violations raise ValueError."""
    try:
        a = _parser().parse_args(argv)
    except SystemExit:
        return {"command": "learn", "copy": describe_copy(paths), "error": "learn task: usage", "hint": "create|handoff|complete|show|list|prompt"}, 2
    doc: dict = {"command": "learn", "copy": describe_copy(paths), "kind": "task", "verb": a.verb}
    if a.verb == "create":
        import os
        t = create(paths, a.name, a.goal, a.worktree or os.getcwd())
        doc.update({"task": t, "text": t["id"]})
    elif a.verb == "handoff":
        h = handoff(paths, a.task_id, to_route=a.to, objective=a.objective, from_route=a.from_route, summary=a.summary, commit=a.commit, tests=a.tests)
        doc.update({"handoff": h, "text": f"{a.task_id} handoff {h['index']} -> {h['to_route']}"})
    elif a.verb == "complete":
        t = complete(paths, a.task_id, summary=a.summary, handoff=a.handoff, commit=a.commit, tests=a.tests, close=a.close)
        doc.update({"task": t, "text": f"{a.task_id} {'closed' if a.close else 'handoff completed'}"})
    elif a.verb == "show":
        t = load(paths, a.task_id)
        doc.update({"task": t, "text": json.dumps(t, indent=1, sort_keys=True)})
    elif a.verb == "list":
        ts = list(fold(read(paths, "tasks")).values())
        doc.update({"tasks": ts, "text": "\n".join(f"{t['id']} {t['status']} {t['name']} ({len(t['handoffs'])} handoffs)" for t in ts) or "no tasks"})
    else:
        t = load(paths, a.task_id)
        h = select_handoff(t, a.handoff)
        doc.update({"task_id": t["id"], "handoff": h["index"], "route": h["to_route"], "worktree": t["worktree"], "prompt": render_prompt(t, h)})
        doc["text"] = doc["prompt"]
    return doc, 0
```

`cli.main`'s `learn task` branch (Task 2) needs one change: print `doc["text"]` in text mode, `json.dumps(doc)` in `--json` mode, and let a `ValueError` fall into the existing `(OSError, ValueError)` envelope (exit 1) and a `KeyError` (unknown route) into the usage envelope (exit 2) — both already exist in `main`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass (the Task 2 stub test `test_learn_task_is_routed_to_the_task_parser` still passes: no verb → usage exit 2).

- [ ] **Step 5: Commit**

```bash
git add agent_on/tasks.py agent_on/schemas/knowledge.py agent_on/cli.py tests/agent_on/test_tasks.py
git commit -m "feat(agent-on): learn task — the task ledger as events in knowledge/tasks.jsonl, folded on read; the handoff prompt as before"
```

---

### Task 7: `claude-on <route> --task <id> [--handoff n|latest]` injects the handoff

**Files:**
- Modify: `agent_on/harness.py` (`run_launch`), `agent_on/cli.py` (two options + render), `tests/agent_on/fakeclaude.py` (record cwd)
- Test: extend `tests/agent_on/test_harness_launch.py`

**Interfaces:**
- Consumes: `tasks.load/select_handoff/render_prompt/launched`.
- Produces: `run_launch(..., task: str | None = None, handoff: str = "latest")`. With `task`: the task is loaded before anything else; `cwd` becomes the task's worktree (a missing directory is a `ValueError`); the route named on the command line must equal the handoff's `to_route` (after alias resolution) — otherwise `ValueError("launch: route X is not the handoff's route Y")`; the rendered prompt is appended as the **last** Claude argument (Claude Code's positional initial prompt, exactly what the old `task launch` did); on a real launch a `launched` event is appended with the launch id **before** spawning. `doc["task"] = {"id", "handoff", "worktree"}`; dry run shows the prompt's first line in `argv` and writes no event. `render_launch` prints `task <id> handoff <n> in <worktree>`.
- `fakeclaude.py` additionally writes `cwd.txt` (its `os.getcwd()`) under `FAKE_CLAUDE_OUT` if it does not already.

- [ ] **Step 1: Write the failing test**

Append to `tests/agent_on/test_harness_launch.py`:

```python
    def test_task_launch_runs_in_the_worktree_with_the_prompt_last_and_marks_the_handoff_launched(self):
        from agent_on import knowledge, tasks
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "Ship it", str(wt))
            tasks.handoff(sb.paths, t["id"], to_route="a", objective="Do the thing")
            with self.assertRaises(ValueError):
                self.launch(sb, "x", ["-p", "hi"], task=t["id"], dry_run=True)                                                # wrong route
            dry, _ = self.launch(sb, "a", ["-p", "hi"], task=t["id"], dry_run=True)
            self.assertEqual(dry["task"], {"id": t["id"], "handoff": 1, "worktree": str(wt.resolve())})
            self.assertTrue(dry["argv"][-1].startswith("You are worker session 1 for agent-on task"))
            self.assertEqual([e["event"] for e in knowledge.read(sb.paths, "tasks")], ["created", "handoff"])                  # dry run: no event
            doc, out = self.launch(sb, "a", ["-p", "hi"], task=t["id"])
            argv = json.loads((out / "argv.json").read_text())
            self.assertTrue(argv[-1].startswith("You are worker session 1"))
            self.assertEqual((out / "cwd.txt").read_text().strip(), str(wt.resolve()))
            h = tasks.load(sb.paths, t["id"])["handoffs"][0]
            self.assertEqual((h["status"], h["launch_id"]), ("launched", doc["launch_id"]))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_harness_launch.py' -v`
Expected: `TypeError: run_launch() got an unexpected keyword argument 'task'`.

- [ ] **Step 3: Write the code**

`agent_on/harness.py` — signature gains `task: str | None = None, handoff: str = "latest"`. Right after `parent = dict(...)` and before `cwd = os.path.realpath(...)`:

```python
    task_doc = None
    if task:
        from .tasks import load as load_task, render_prompt, select_handoff
        t = load_task(paths, task)
        h = select_handoff(t, handoff)
        if not os.path.isdir(t["worktree"]):
            raise ValueError(f"launch: task worktree is no longer a directory: {t['worktree']}")
        cwd = t["worktree"]                                                        # the handoff's worktree, as the old task launch did
        claude_args = [*claude_args, render_prompt(t, h)]                          # the initial prompt is Claude Code's last positional
        task_doc = {"id": t["id"], "handoff": h["index"], "worktree": os.path.realpath(t["worktree"]), "to_route": h["to_route"]}
```

After `route = table.resolve(name)`:

```python
    if task_doc and task_doc.pop("to_route") != route.name:
        raise ValueError(f"launch: route {route.name} is not the handoff's route")
```

(add `"task": task_doc` to `doc`). Just before `spawn(argv, cenv, cwd)` (inside the real-launch path, after `write_run_dir`):

```python
    if task_doc:
        from .tasks import launched
        launched(paths, task_doc["id"], handoff=str(task_doc["handoff"]), launch_id=launch_id, route=route.name)
```

`cli.py`: `l.add_argument("--task", metavar="ID", help="inject the task's handoff prompt and run in its worktree (§10.1)")`, `l.add_argument("--handoff", default="latest")`; pass `task=args.task, handoff=args.handoff` to `run_launch`; in `render_launch`, after the cost line: `if doc.get("task"): lines.append(f"task {doc['task']['id']} handoff {doc['task']['handoff']} in {doc['task']['worktree']}")`.

`tests/agent_on/fakeclaude.py`: beside `argv.json`, write `cwd.txt` with `os.getcwd()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/harness.py agent_on/cli.py tests/agent_on/fakeclaude.py tests/agent_on/test_harness_launch.py
git commit -m "feat(agent-on): claude-on --task injects the handoff prompt, runs in the worktree and marks the handoff launched"
```

---

### Task 8: The skill, the README, the ARCHITECTURE paragraph, the memory migration note

**Files:**
- Create: `.claude/skills/agent-on/SKILL.md`
- Modify: `README.md` (Plan C section after Plan B), `docs/ARCHITECTURE.md` (drop the Orca/dispatcher paragraph, §10.1), `docs/superpowers/specs/2026-09-07-agent-on-design.md` (§9 `learn` row: the flag is `--json-record`)
- Test: `tests/agent_on/test_docs_plan_c.py`

**Interfaces:** none new. The skill is data an agent inside Claude Code reads; it must not restate values that live in code (D5) — it names the commands and the files and says when to write.

- [ ] **Step 1: Write the failing test**

`tests/agent_on/test_docs_plan_c.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402


class DocsTest(unittest.TestCase):
    def test_skill_exists_names_the_verbs_and_the_files_and_no_literal_values(self):
        p = REPO / ".claude" / "skills" / "agent-on" / "SKILL.md"
        self.assertTrue(p.exists())
        text = p.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: agent-on\n"))
        for needle in ("agent-on status --json", "agent-on learn", "knowledge/observations.jsonl", "knowledge/traps.jsonl", "knowledge/decisions.jsonl",
                       "learn task", "claude-on", "--task", "Q1", "Q10"):
            self.assertIn(needle, text)
        self.assertNotIn("131072", text)                                            # values live in routes.toml / observed.json, never in the skill (D5)

    def test_readme_has_the_plan_c_section_and_architecture_lost_the_orca_paragraph(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("### Knowledge (Plan C)", readme)
        self.assertIn("agent-on learn", readme)
        arch = (REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertNotIn("consumed by Orca", arch)

    def test_spec_learn_row_names_the_real_flag(self):
        spec = (REPO / "docs" / "superpowers" / "specs" / "2026-09-07-agent-on-design.md").read_text(encoding="utf-8")
        self.assertIn("`agent-on learn <kind> --json-record", spec)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_docs_plan_c.py' -v`
Expected: `AssertionError` (no skill file).

- [ ] **Step 3: Write the files**

`.claude/skills/agent-on/SKILL.md`:

```markdown
---
name: agent-on
description: Use when working in this checkout on models, routes, costs, launches or qualifications — how to read what the tower already knows (status --json and knowledge/) and how to record what you learn (agent-on learn) so the next session starts from it.
---

# agent-on — read the tower, write what you learn

The launch cannot be a skill (it sets the child's environment before Claude Code starts), and a skill does not
accumulate; this one only tells you where the accumulated facts are and how to add to them.

## Read first

- `./bin/agent-on status --json` — every route's declared limits beside what was measured (`observed`), the cost
  model, the last session's cost (Q1), whether the route is served (Q3), the last gate run (Q4), OpenRouter spend
  (Q6), the harness baseline tokens (Q8), and per route `knowledge.observations` (last three) and
  `knowledge.traps` (what applies to `status` on that route).
- `./bin/agent-on status --check` — every invariant with its result and fix; `last_check` is written. What an
  action must not break is the list of invariants that name it (Q10).
- `knowledge/decisions.jsonl` — the settled decisions with rationale; a record with `supersedes` replaces the one it
  names. Read the active set before proposing a change that touches one.
- `knowledge/traps.jsonl` — mechanisms that have bitten this repo, with `applies_to` (a verb, a source, a route or
  `*`) and how to avoid them. `status` and the launch show the ones for the action in hand.
- `knowledge/observations.jsonl` — measurements (`tokens | throughput | quality | liveness | cost`) with evidence.
- `knowledge/qualifications.jsonl`, `knowledge/gate-runs.jsonl` — the durable twins of the last qualification and gate run.
- `knowledge/tasks.jsonl` — the task ledger as events; `agent-on learn task list|show <id>` folds it.

Every command prints a `copy:` line (checkout, commit, dirty, state root) — say which copy you measured.

## Write when you learn

    ./bin/agent-on learn observations --json-record '{"route": "<source>/<model>", "kind": "throughput", "values": {…}, "evidence": "<how it was measured>", "session": null}'
    ./bin/agent-on learn traps --json-record '{"trap": "…", "mechanism": "…", "avoid": "…", "evidence": "…", "found_by": "…", "applies_to": ["launch"]}'
    ./bin/agent-on learn decisions --json-record '{"decision": "…", "rationale": "…", "by": "rick", "supersedes": "decisions-…"}'

`learn` validates, mints `id` and `ts`, and appends one line; nothing is written on a schema error (exit 3). A
value you did not measure is `null` or `"unknown"`, never a guess. `knowledge/` is git-tracked: commit it with the
work that produced it.

## Tasks across sessions

    ./bin/agent-on learn task create <name> --goal '…' [--worktree <dir>]
    ./bin/agent-on learn task handoff <id> --to <route> --objective '…' [--from <route>] [--summary '…'] [--commit <sha>] [--tests '…']
    ./bin/claude-on <route> --task <id> [--handoff n|latest] [claude args…]      # runs in the worktree with the handoff prompt injected
    ./bin/agent-on learn task complete <id> --summary '…' [--commit <sha>] [--tests '…'] [--close]

A dispatcher (Orca or another) reads `learn task prompt <id> --json` to pick a host and invokes the same launcher.
```

`README.md` — after the Plan B section:

```markdown
### Knowledge (Plan C)

    ./bin/agent-on status glm                    # … plus the last observations and the traps that apply
    ./bin/agent-on learn traps --json-record '{…}'
    ./bin/agent-on learn task create … / handoff … / complete …
    ./bin/claude-on huihui --task <id>           # the handoff prompt, in the task's worktree

`knowledge/` is git-tracked, append-only JSONL beside `routes.toml`: decisions (with supersession), traps (with
`applies_to`), observations, and the durable twins of qualifications and gate runs. `qualify`, the gate and the
launch append to it; `learn` is the write verb for everything else; `.claude/skills/agent-on/SKILL.md` tells an
agent inside Claude Code how to read and write it. The seeds carry the decisions D1–D13, the measured facts from
2026-08-23 to 2026-09-08 and eleven traps. Commit `knowledge/` with the work that produced it.
```

`docs/ARCHITECTURE.md` — delete the paragraph beginning "This layer intentionally does not schedule machines." (§10.1: nothing consumes it).

Spec §9 `learn` row: change `` `agent-on learn <kind> --json '<record>'` (or stdin) `` to `` `agent-on learn <kind> --json-record '<record>'` (or stdin; `--json` stays the output switch — Plan C) ``.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/agent-on/SKILL.md README.md docs/ARCHITECTURE.md docs/superpowers/specs/2026-09-07-agent-on-design.md tests/agent_on/test_docs_plan_c.py
git commit -m "docs(agent-on): the agent-on skill, the Plan C README section, ARCHITECTURE without the dispatcher paragraph"
```

---

### Task 9: Acceptance — the tower on the real machine, and a peer answers the questions from `status --json` and `knowledge/` alone

**Files:** none new (measurements go into `knowledge/` through the commands themselves).

- [ ] **Step 1: The seeds and the invariants on the real checkout**

```bash
./bin/agent-on status --check | grep -E 'knowledge|result|last_check'
./bin/agent-on gate | tail -2
tail -n 1 knowledge/gate-runs.jsonl | python3 -c 'import json,sys; g=json.loads(sys.stdin.read()); print(g["id"], g["result"], g["invariants"]["knowledge.typed"])'
```

Expected: `pass knowledge.typed: 6 file(s) valid`; gate `pass`; the twin line names the same result with `knowledge.typed == "pass"`.

- [ ] **Step 2: `qualify` and a launch write their twins (free lane)**

```bash
./bin/agent-on qualify huihui | tail -3
./bin/claude-on huihui -p 'Reply with exactly: OK'; echo "exit $?"
tail -n 2 knowledge/observations.jsonl | cut -c1-160
./bin/agent-on status huihui | grep -E 'observation|trap:'
```

Expected: one `throughput` and one `cost` observation appended (route `omlx/root4k--Huihui…`, `cost_usd` 0.0, `session` = the printed session id); `status huihui` shows the last three observations and the traps whose `applies_to` names `status`, `omlx`, `*` or the route (installed-copy-selector, port-4000-collision, fabricated-cost-field at least). The launch printed `trap:` lines for `launch` (child-env-credential, settings-last-wins, discovery-filter, budget-formula, synthetic-error-turns, installed-copy-selector).

- [ ] **Step 3: A task handoff through the launcher (free lane)**

```bash
TID=$(./bin/agent-on learn task create 'Plan C smoke' --goal 'Read README.md and reply with only its first heading line' --worktree "$PWD")
./bin/agent-on learn task handoff "$TID" --to huihui --objective 'Use the Read tool to read README.md in this directory and reply with only its first heading line.' --summary 'Plan C acceptance' --commit "$(git rev-parse HEAD)"
./bin/claude-on huihui --task "$TID" -p --allowedTools Read; echo "exit $?"
./bin/agent-on learn task complete "$TID" --summary 'answered' --close
./bin/agent-on learn task show "$TID" | python3 -c 'import json,sys; t=json.load(sys.stdin)["task"]; print(t["status"], t["handoffs"][0]["status"], t["handoffs"][0]["launch_id"])'
```

Expected: `# claude-litellm` printed, exit 0; `completed launched→completed <launch id>` — the `launched` event carries the launch id the launch printed. (`-p` with no prompt text: the injected handoff prompt is the positional prompt, which is what `-p` reads; if Claude Code refuses that form, pass `-p ''` and record the form that worked.)

- [ ] **Step 4: The peer check (§14 row C acceptance)**

Dispatch a fresh subagent (sonnet) with **only** these inputs: the output of `./bin/agent-on status --json`, the six `knowledge/*.jsonl` files, and the seven questions below — not the spec, not the code — and ask for one-line answers with the field or record id that answers each:

- Q1 What did the last session on `openrouter/z-ai/glm-5.2` consume and cost?
- Q3 Which backend id does the `huihui` alias hit right now, and is it served?
- Q4 When did the gate last pass, on which mock port, with which skips?
- Q5 How do I run this checkout against a scratch state root?
- Q6 How much OpenRouter money has been spent?
- Q8 How many tokens does Claude Code spend before task content on `huihui`, and why is per-item attribution not available?
- Q10 What must change together to delete a route?

Expected: each answered from a named field (`routes.*.last_session.*`, `routes.*.observed.served` + `wire_model`, `last_gate_run.*` or the `gate-runs` record, `copy.state` + `decisions-D13`, `spend.openrouter.*`, `cost_model.harness_baseline_tokens` + `decisions-Q8-attribution-deferred`, `decisions-Q10-dependency-ledger` + the invariant list). An unanswerable question is a finding: fix the seed or the field in this task's series and say so.

- [ ] **Step 5: Commit the knowledge the acceptance produced**

```bash
git status --porcelain knowledge/
git add knowledge/
git commit -m "knowledge: Plan C acceptance on 2026-09-08 — gate run, huihui qualification and cost observations, the smoke task

peer check: Q1 Q3 Q4 Q5 Q6 Q8 Q10 answered from status --json and knowledge/ alone (<list any that needed a fix>).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

## Self-review

**Spec coverage — §14 row C and §10/§10.1/§15:**

| requirement | task |
|---|---|
| `knowledge/` git-tracked append-only JSONL, one file per kind, validated, `id` + `ts` | 1, 3 |
| `learn <kind>` validates, appends, mints id/ts, validates `supersedes` | 1, 2 |
| written by `qualify` (qualifications + observations), the gate (gate-runs), the launch (observations) | 4, 5 |
| `status` shows the last N observations and applicable traps for the selected route | 5 |
| seeds: tokenizer-vs-template, Huihui-outranks-Instruct, serialisation, 48K baseline, two-arm thinking, direct-wire cache; D1–D13 with D3's three turns and D7's history; the nine traps | 3 (plus two traps and three observations Plan B added) |
| memory-note migration (`measure-the-installed-copy`, `budget-formula`, `fix-on-contact`, `scope-openrouter`, `delegate-cheaper-models`) | 3 (`traps-installed-copy-selector`, `traps-budget-formula-in-code`, `decisions-fix-on-contact`, `decisions-D3*`, `decisions-delegate-cheaper-models`); the controller then points each out-of-repo note at its record |
| task ledger as `tasks.jsonl` events under `learn task …`; `claude-on --task` injects the prompt; local pre-probe replaced by `route.served` | 6, 7 |
| the Orca paragraph dropped from ARCHITECTURE.md | 8 |
| the skill | 8 |
| acceptance: a peer answers Q1, Q3–Q6, Q8, Q10 from `status --json` and `knowledge/` | 9 |
| nothing deleted | all |

**Deviations, stated:** the record flag is `--json-record` (the global `--json` is the output switch on every verb; the spec's row is corrected in Task 8). `qualify`'s knowledge write moves from a hand-rolled append to `knowledge.append` (same file, same shape). `knowledge.typed` now scans `paths.knowledge_dir` instead of `tree` (§10 says the checkout; a sandbox lints real code but owns its knowledge). Per-launch appends make `copy.dirty` true until `knowledge/` is committed — that is the accretive property, by design; the skill says to commit it with the work. The seeds use human-readable stable ids (L5: "stable ids"); `learn` mints ULIDs.

**Placeholder scan:** the `...` in Tasks 4, 5 and 7 mark the neighbouring test's sandbox/env idiom to copy verbatim; every assertion is written out. `<list any that needed a fix>` in Task 9's commit template is filled from the measurement.

**Type consistency:** `knowledge.append(paths, kind, rec, *, now)` is used identically in Tasks 4–7; `knowledge_view(paths, *, route, source, action, n)` in Tasks 5 (status: `action="status"`; launch: `action="launch"`); `tasks.handoff(...)` returns the handoff dict and `tasks.complete(...)` the task, as Tasks 6 and 7 use them; `run_launch(..., task=, handoff=)` matches `cli.main`'s call; `TASK_ID` lives in `schemas/knowledge.py` and is re-exported by `tasks.py` (Task 6's test reads `tasks.TASK_ID`); `doc["knowledge"]` is `None` or a dict of ids on `qualify`, the gate and the launch.
