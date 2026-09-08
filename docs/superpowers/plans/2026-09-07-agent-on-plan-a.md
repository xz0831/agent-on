# agent-on Plan A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the `agent_on/` package (repo, package and tower CLI are `agent-on` — spec rev 8; `claude-on` and `codex-on` are the per-harness launchers of Plans B and F) with `routes.toml`, the observed-state layer, the invariant registry, and the four commands `status`, `sync`, `add`, `gate` — purely additive, beside the running `claude-litellm`, deleting nothing.

**Architecture:** One stdlib-only Python package is the whole system: L1 declarations in `routes.toml` (+ a machine-written `routes.discovered.toml` in the state root), L2 measurements in `$STATE/observed.json` written only by actions under one lock, L3 named predicates over `(routes, observed, tree, home)`, L4 the commands. Every command prints `copy.*`, accepts `--json`, and names the invariants it evaluated. The gate reproduces F1 on every run against an in-process mock source on an ephemeral port.

**Tech Stack:** Python ≥ 3.11 from `PATH` (`tomllib`, `fcntl`, `http.server`, `urllib`, `unittest`), a ≤20-line zsh shim. No third-party packages, no venv.

**Spec:** `docs/superpowers/specs/2026-09-07-agent-on-design.md` (rev 8). Section references below (§n, Dn, Fn, Qn) point into it. This plan is §14 row **A**, plus the two rev-6 P2s the owner asked to carry into Plan A's contract: the `add` lock location (§7.1) and per-run cost attribution (§11).

## Global Constraints

- **Additive only.** No existing file under `bin/`, `config/`, `scripts/`, `tests/test_*.py`, or `docs/*.md` is modified or deleted except the three named edits: `.gitignore` (two ignore lines), `.github/workflows/ci.yml` (one new job appended), `README.md` (one new section appended). `claude-litellm` must still launch after every task (§14: "Until this plan lands, `git revert` of any A–C commit restores the old path intact").
- **Standard library only** (D4). `import` of anything outside the stdlib in `agent_on/` or `tests/agent_on/` is a defect. Python floor is 3.11 (`tomllib`); CI runs 3.13; the machine's `python3` is 3.14.7.
- **One home per fact** (D5). Route names live only in `routes.toml`. No test or package file may contain a route-name literal that `routes.toml` does not declare (`test.names.derived`); tests derive names from the loaded table or use the mock source name `mock`.
- **Unmeasured is `null`, never absent; a skip is never a pass** (§7, §8). `caching` is `true | false | "unknown"`. `cost_usd` is a number or the string `"unknown"`.
- **Never copy Claude Code's own cost figure** (F11): the keys `total_cost_usd` and `costUSD` are rejected anywhere in `observed.json`.
- **Storage rules** (§7.1): `observed.json` and `routes.discovered.toml` are written under `$STATE/locks/observed.lock` by read-modify-write on the freshly re-read document, temp+fsync+rename; `routes.toml` is written only by `add` under `<checkout>/.routes.lock` (rev 6: keyed by the resource, so every `AGENT_ON_STATE` shares it); knowledge and session ledgers are `O_APPEND` single lines.
- **State root**: `AGENT_ON_STATE`, else `$XDG_STATE_HOME/agent-on`, else `~/.local/state/agent-on` (D13). `sync` never dirties a tracked file.
- **Secrets**: an environment variable, else a `KEY=value` line in `$STATE/env` (mode 0600 enforced); the environment wins (§9). No Keychain reads in this package.
- **Commit style**: this repository's messages are `<type>: <imperative summary>` (`feat:`, `test:`, `docs:`, `fix:`, `ci:`); one commit per task, tests and code together; end each message with the session's attribution trailer shown in Task 1.
- **Do not restart or stop oMLX on :8000** — another session uses it. Reads (`GET /v1/models`) are fine.
- **Test discipline**: every test lives in `tests/agent_on/` (no `__init__.py`, so the old `check.zsh` discovery does not pick them up), starts with the sys.path preamble in Task 1, and uses `helpers.Sandbox` for a throwaway checkout/state/home. Run the suite with `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`.

---

## File structure

| path | responsibility |
|---|---|
| `bin/agent-on` | zsh shim: find `python3 ≥ 3.11`, `exec python3 -m agent_on` with the checkout on `PYTHONPATH` |
| `agent_on/__init__.py`, `__main__.py` | package marker + `python -m` entry |
| `agent_on/util.py` | `utc_now`, `parse_utc`, `canonical_json`, `sha16` |
| `agent_on/paths.py` | `Paths` (checkout, state, home, code tree; every derived path), `default_paths`, `ensure_state`, `describe_copy` (§7 `copy.*`) |
| `agent_on/schemas/errors.py` | `RULES` registry + `SchemaError(rule, detail)` — F14: a rule must be registered to be raised |
| `agent_on/schemas/routes.py` | L1: dataclasses, TOML parse/validate, packaged-wins merge, inheritance, `effective_sha`, TOML emit |
| `agent_on/schemas/observed.py` | L2 shape: empty records, `validate_observed`, `compute_context`, `forbid_claude_cost` |
| `agent_on/schemas/knowledge.py` | L5 record kinds (§10) and `validate_file` for `knowledge.typed` |
| `agent_on/cost.py` | §11 cost attribution: `price_usage`, `attribute_run`, `fold_session` |
| `agent_on/state.py` | §7.1: locks, atomic writes, `update_observed`, `write_discovered`, `checkout_locked`, `$STATE/env`, session ledger |
| `agent_on/sources.py` | L0 reads: `probe_source`/`probe_all`, catalog normalisation, oMLX settings, OpenRouter spend |
| `agent_on/mock_source.py` | in-process HTTP source for tests and the gate (ephemeral port) |
| `agent_on/sync.py` | `sync` |
| `agent_on/invariants.py` | L3 registry + the fourteen predicates |
| `agent_on/status.py` | `status [route] [--check]` + text rendering |
| `agent_on/gate.py` | `gate`: unit tests → mock smoke (F1) → invariants → `last_gate_run` |
| `agent_on/add.py` | `add <source>/<model>` |
| `agent_on/cli.py` | argparse, `--json`, exit codes, renderers |
| `routes.toml` | the six packaged routes (four OpenRouter, two oMLX) and five sources |
| `tests/agent_on/helpers.py` | `REPO`, `Sandbox`, `MOCK_ROUTES` |
| `tests/agent_on/test_*.py` | one file per module |
| `.gitignore` | `+ .routes.lock`, `+ routes.toml.tmp.*` |
| `.github/workflows/ci.yml` | `+ agent-on` job |
| `README.md` | `+ ## agent-on (Plan A)` section |

Public interfaces every later task relies on (exact names; a task's implementer sees only their task):

```python
# agent_on.paths
Paths(checkout: Path, state: Path, home: Path, tree: Path | None = None)   # .code_tree, .routes_toml, .routes_lock, .discovered_toml, .observed_json, .observed_lock, .sessions_dir, .env_file, .shim
default_paths(env=None) -> Paths ; ensure_state(paths) -> None ; describe_copy(paths) -> dict
# agent_on.schemas.routes
parse_routes_text(text, *, packaged: bool, sources=None) -> (dict[str, Source], dict[str, Route], tuple[str, ...])
load_routes(paths) -> RouteTable        # .sources .routes .shadowed .resolve() .effective_limits() .effective_sha() .by_source()
route_block(route) -> str ; discovered_text(routes, written_at) -> str
# agent_on.schemas.observed
empty_observed() ; empty_source() ; empty_route() ; validate_observed(doc) ; compute_context(declared, tier) -> (int|None, str|None) ; forbid_claude_cost(obj)
# agent_on.state
update_observed(paths, mutate) -> dict ; read_observed(paths) -> dict ; write_discovered(paths, text) ; checkout_locked(paths) ; atomic_write(path, text)
resolve_secret(paths, name, env=None) -> str|None ; append_session_run(paths, session_id, record) ; read_session_runs(paths, session_id) -> list
# agent_on.sources
probe_source(source, timeout=5.0, headers=None) -> Probe ; probe_all(sources, timeout=5.0) -> dict[str, Probe] ; read_configured_limits(path, home) ; fetch_openrouter_spend(base_url, key, timeout)
# agent_on.invariants
build_context(paths, *, with_claude_code=False) -> Context ; evaluate(ctx, ids=None, route=None) -> list[Result] ; skipped_ids(results) -> list[str] ; REGISTRY
# agent_on.sync / status / gate / add
run_sync(paths, *, timeout=5.0, env=None) -> dict ; build_status(paths, *, route=None, check=False) -> dict ; run_gate(paths) -> dict ; run_add(paths, name, *, alias=None, timeout=5.0) -> dict
```

---
### Task 1: Package skeleton, paths, `copy.*`, shim, CLI parser

**Files:**
- Create: `bin/agent-on`, `agent_on/__init__.py`, `agent_on/__main__.py`, `agent_on/util.py`, `agent_on/paths.py`, `agent_on/cli.py`
- Create: `tests/agent_on/helpers.py`, `tests/agent_on/test_paths.py`, `tests/agent_on/test_cli.py`
- Modify: `.gitignore` (append two lines)

**Interfaces:**
- Produces: `Paths`, `default_paths`, `ensure_state`, `describe_copy`, `CHECKOUT`; `util.utc_now/parse_utc/canonical_json/sha16`; `cli.main(argv) -> int` with exit codes `0 ok · 1 invariant/gate failure · 2 usage · 3 schema`. `cli.py` is written complete here with lazy imports; the `status`/`sync`/`add`/`gate` modules it imports land in Tasks 7–11 and until then those subcommands fail with `ImportError` — expected.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/helpers.py` (not collected — no `test_` prefix; every test file imports it after the preamble):

```python
"""Shared fixtures for the agent-on tests."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_on.paths import Paths  # noqa: E402

# Two sources on one mock server: `mock` is oMLX-shaped and discoverable, `paid` is OpenRouter-shaped and keyed.
MOCK_ROUTES = """version = 1

[sources.mock]
base_url = "{base}"
catalog = "/v1/models"
discover = true

[sources.mock.limits]
input = 8192
output = 2048
confidence = "owned-policy"
source = "test fixture"

[sources.paid]
base_url = "{base}"
auth_env = "MOCK_PAID_KEY"
catalog = "{base}/api/v1/models"

[routes."mock/alpha"]
aliases = ["a"]

[routes."mock/gone"]

[routes."paid/vendor/model-x"]
wire_model = "vendor/model-x"
aliases = ["x"]

[routes."paid/vendor/model-x".limits]
input = 100000
output = 4000
confidence = "provider"
source = "fixture"

[routes."paid/vendor/model-x".price]
input_usd_per_mtok = 1.0
output_usd_per_mtok = 2.0
cache_read_usd_per_mtok = 0.1
source = "fixture"
"""


class Sandbox:
    """A throwaway checkout (routes.toml only) + state root + home. `tree` defaults to the real code tree so
    the tree lints (schema.complete, test.names.derived) scan real code; pass tree=None to lint the sandbox."""

    def __init__(self, routes_text: str, *, tree: Path | None = REPO):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "co").mkdir()
        (root / "home").mkdir()
        (root / "co" / "routes.toml").write_text(routes_text, encoding="utf-8")
        self.root = root
        self.paths = Paths(checkout=root / "co", state=root / "state", home=root / "home",
                           tree=tree if tree is not None else root / "co")

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
```

`tests/agent_on/test_paths.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

from agent_on.paths import CHECKOUT, Paths, default_paths, describe_copy, ensure_state  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_default_state_root_follows_xdg_then_home(self):
        p = default_paths(env={"HOME": "/h"})
        self.assertEqual(p.state, Path("/h/.local/state/agent-on"))
        p = default_paths(env={"HOME": "/h", "XDG_STATE_HOME": "/x"})
        self.assertEqual(p.state, Path("/x/agent-on"))
        p = default_paths(env={"HOME": "/h", "XDG_STATE_HOME": "/x", "AGENT_ON_STATE": "/s"})
        self.assertEqual(p.state, Path("/s"))
        self.assertEqual(p.checkout, CHECKOUT)
        self.assertEqual(p.code_tree, CHECKOUT)

    def test_routes_lock_is_keyed_by_the_checkout_not_the_state_root(self):
        # rev-6 P2: two runs with different AGENT_ON_STATE must take the same lock for the same routes.toml
        a = Paths(checkout=Path("/co"), state=Path("/s1"), home=Path("/h"))
        b = Paths(checkout=Path("/co"), state=Path("/s2"), home=Path("/h"))
        self.assertEqual(a.routes_lock, b.routes_lock)
        self.assertEqual(a.routes_lock, Path("/co/.routes.lock"))
        self.assertNotEqual(a.observed_lock, b.observed_lock)
        self.assertEqual(a.observed_lock, Path("/s1/locks/observed.lock"))

    def test_derived_paths(self):
        p = Paths(checkout=Path("/co"), state=Path("/s"), home=Path("/h"))
        self.assertEqual(p.routes_toml, Path("/co/routes.toml"))
        self.assertEqual(p.discovered_toml, Path("/s/routes.discovered.toml"))
        self.assertEqual(p.observed_json, Path("/s/observed.json"))
        self.assertEqual(p.sessions_dir, Path("/s/sessions"))
        self.assertEqual(p.env_file, Path("/s/env"))
        self.assertEqual(p.shim, Path("/h/.local/bin/agent-on"))

    def test_ensure_state_creates_private_dirs(self):
        import tempfile, stat
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(checkout=Path(tmp), state=Path(tmp) / "st", home=Path(tmp))
            ensure_state(p)
            for d in (p.state, p.observed_lock.parent, p.sessions_dir):
                self.assertTrue(d.is_dir())
                self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)

    def test_describe_copy_reports_real_git_facts(self):
        p = default_paths()
        c = describe_copy(p)
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(c["commit"], head)
        self.assertIn(c["dirty"], (True, False))
        self.assertTrue(c["python"].startswith(sys.executable))
        self.assertEqual(set(c), {"checkout", "commit", "dirty", "shim", "python", "state"})

    def test_describe_copy_without_git_is_honest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            c = describe_copy(Paths(checkout=Path(tmp), state=Path(tmp) / "s", home=Path(tmp)))
            self.assertIsNone(c["commit"])
            self.assertIsNone(c["dirty"])
            self.assertIsNone(c["shim"])


if __name__ == "__main__":
    unittest.main()
```

`tests/agent_on/test_cli.py`:

```python
from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

from agent_on import cli  # noqa: E402


class CliTest(unittest.TestCase):
    def test_help_lists_the_four_plan_a_commands(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            cli.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        for verb in ("status", "sync", "add", "gate"):
            self.assertIn(verb, out.getvalue())

    def test_json_is_accepted_before_or_after_the_verb(self):
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["status", "--json"]).json)
        self.assertTrue(parser.parse_args(["--json", "status"]).json)
        self.assertFalse(parser.parse_args(["status"]).json)
        self.assertTrue(parser.parse_args(["add", "mock/x", "--json", "--alias", "a"]).json)
        self.assertFalse(parser.parse_args(["gate"]).json)

    def test_unknown_command_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cli.main(["frobnicate"])
        self.assertEqual(cm.exception.code, 2)

    def test_shim_runs_the_package_and_checks_the_interpreter(self):
        shim = REPO / "bin" / "agent-on"
        self.assertTrue(shim.exists() and shim.stat().st_mode & 0o111, "bin/agent-on must be executable")
        self.assertLessEqual(len(shim.read_text().splitlines()), 20, "the shim is ≤ 20 lines (D4)")
        proc = subprocess.run([str(shim), "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("status", proc.stdout)
        bad = subprocess.run([str(shim), "--help"], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "AGENT_ON_PYTHON": "/bin/false"})
        self.assertEqual(bad.returncode, 3)
        self.assertIn("3.11", bad.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on'`

- [ ] **Step 3: Write the package**

`agent_on/__init__.py`:

```python
"""agent-on — an agent-operated model-source layer for Claude Code (spec: docs/superpowers/specs/2026-09-07-agent-on-design.md)."""

__version__ = "0.1.0a"   # Plan A
```

`agent_on/__main__.py`:

```python
import sys

from .cli import main

sys.exit(main())
```

`agent_on/util.py`:

```python
"""Helpers shared by every layer: RFC 3339 time, canonical JSON, short hashes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def utc_now() -> str:
    """RFC 3339 UTC to the second — the form of every `checked` / `at` / `ts` field (§7)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
```

`agent_on/paths.py`:

```python
"""Where everything lives (D9, D13). One checkout, one state root; `AGENT_ON_STATE` overrides the root."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
CHECKOUT = PACKAGE_DIR.parent


@dataclass(frozen=True)
class Paths:
    checkout: Path          # holds routes.toml (and knowledge/ from Plan C)
    state: Path             # D13: machine-written state, outside git
    home: Path              # ~ — for the shim and the shared ~/.claude/settings.json lint
    tree: Path | None = None  # the code tree the lints scan; defaults to `checkout` (they coincide in production)

    @property
    def code_tree(self) -> Path:
        return self.tree or self.checkout

    @property
    def routes_toml(self) -> Path:
        return self.checkout / "routes.toml"

    @property
    def routes_lock(self) -> Path:
        # rev-6 P2: keyed by the resource it protects, never by the state root, so every AGENT_ON_STATE shares it
        return self.checkout / ".routes.lock"

    @property
    def discovered_toml(self) -> Path:
        return self.state / "routes.discovered.toml"

    @property
    def observed_json(self) -> Path:
        return self.state / "observed.json"

    @property
    def observed_lock(self) -> Path:
        return self.state / "locks" / "observed.lock"

    @property
    def sessions_dir(self) -> Path:
        return self.state / "sessions"

    @property
    def env_file(self) -> Path:
        return self.state / "env"

    @property
    def shim(self) -> Path:
        return self.home / ".local" / "bin" / "agent-on"


def default_paths(env: dict | None = None) -> Paths:
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    if env.get("AGENT_ON_STATE"):
        state = Path(env["AGENT_ON_STATE"])
    else:
        state = Path(env.get("XDG_STATE_HOME") or (home / ".local" / "state")) / "agent-on"
    return Paths(checkout=CHECKOUT, state=state, home=home, tree=CHECKOUT)


def ensure_state(paths: Paths) -> None:
    for d in (paths.state, paths.observed_lock.parent, paths.sessions_dir):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(d, 0o700)


def describe_copy(paths: Paths) -> dict:
    """§7 `copy.*`: which checkout, which commit, dirty or not, where the shim points, which Python, which state root."""
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", str(paths.checkout), *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = git("rev-parse", "--short", "HEAD")
    porcelain = git("status", "--porcelain")
    shim: str | None = None
    if paths.shim.is_symlink():
        shim = f"{paths.shim} -> {os.readlink(paths.shim)}"
    elif paths.shim.exists():
        shim = f"{paths.shim} (not a symlink)"
    v = sys.version_info
    return {"checkout": str(paths.checkout), "commit": commit,
            "dirty": None if porcelain is None else bool(porcelain),
            "shim": shim, "python": f"{sys.executable} {v.major}.{v.minor}.{v.micro}", "state": str(paths.state)}
```

`agent_on/cli.py` (complete; later tasks add nothing here):

```python
"""L4 — the commands. Plan A ships status, sync, add, gate. Every command accepts --json and prints copy.* (§9)."""
from __future__ import annotations

import argparse
import json
import sys

from .paths import default_paths, describe_copy
from .schemas.errors import SchemaError

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_SCHEMA = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    # `--json` is accepted before or after the verb. The per-verb copy defaults to SUPPRESS so that, when absent,
    # it does not overwrite a `--json` given before the verb (argparse lets subparser defaults clobber parent values).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    p = argparse.ArgumentParser(prog="agent-on", description="run the Claude Code harness on any model from any source")
    p.add_argument("--json", action="store_true", help="machine-readable output (every command; before or after the verb)")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status", parents=[common], help="L1 beside L2; --check evaluates every invariant and writes last_check")
    s.add_argument("route", nargs="?", help="a route name or alias; default: every route")
    s.add_argument("--check", action="store_true")
    y = sub.add_parser("sync", parents=[common], help="probe every source; refresh catalogs, served flags, limits, spend; rewrite routes.discovered.toml")
    y.add_argument("--timeout", type=float, default=5.0, help="seconds per source (default 5)")
    a = sub.add_parser("add", parents=[common], help="declare a packaged route in routes.toml (limits, reasoning, price filled from the catalog)")
    a.add_argument("name", metavar="<source>/<model>")
    a.add_argument("--alias")
    a.add_argument("--timeout", type=float, default=5.0)
    sub.add_parser("gate", parents=[common], help="unit tests + mock-source smoke + every invariant; writes last_gate_run")
    return p


def copy_line(c: dict) -> str:
    return (f"copy: {c['checkout']} @ {c['commit'] or '?'}{' (dirty)' if c['dirty'] else ''}"
            f" · state {c['state']} · {c['python']}" + (f" · shim {c['shim']}" if c["shim"] else " · no shim"))


def invariant_lines(results: list[dict]) -> list[str]:
    return [f"  {r['result']:4} {r['id']}" + (f"[{r['subject']}]" if r.get("subject") else "") + f": {r['reason']}"
            + (f" — fix: {r['fix']}" if r.get("fix") else "") for r in results]


def render_sync(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    for n, s in doc["sources"].items():
        lines.append(f"source {n}: " + ("reachable, catalog " + str(s["catalog_count"]) if s["reachable"] else f"unreachable ({s['error']})"))
    lines.append(f"discovered {len(doc['discovered'])} route(s); shadowed {len(doc['shadowed'])}; orphaned packaged: {doc['orphans'] or 'none'}")
    for n, sp in doc["spend"].items():
        lines.append(f"spend {n}: " + (f"error {sp['error']}" if sp.get("error") else f"used ${sp['usd_used']} · limit ${sp['usd_limit']}/{sp['limit_reset']} · remaining ${sp['usd_remaining']} · today ${sp['usd_used_daily']}"))
    return "\n".join(lines + invariant_lines(doc["invariants"]))


def render_add(doc: dict) -> str:
    lines = [copy_line(doc["copy"]), f"{'added' if doc['written'] else 'NOT added'}: {doc['route']}"]
    if doc["written"]:
        lines.append(doc["block"].rstrip())
    return "\n".join(lines + invariant_lines(doc["invariants"]))


def render_gate(doc: dict) -> str:
    t = doc["tests"]
    lines = [copy_line(doc["copy"]),
             "tests: " + (f"skipped ({t['skipped']})" if t["skipped"] else f"ran {t['ran']} — {'ok' if t['ok'] else 'FAILED: ' + ' | '.join(t['tail'])}"),
             f"smoke (F1 on the mock source): {'ok' if doc['smoke']['ok'] else 'FAILED ' + str(doc['smoke']['results'])}"]
    lines += invariant_lines(doc["invariants"])
    g = doc["last_gate_run"]
    lines.append(f"result: {g['result']} · skipped {g['skipped']} · mock port {g['mock_port']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = default_paths()
    try:
        if args.command == "status":
            from .status import build_status, render_text
            doc = build_status(paths, route=args.route, check=args.check)
            code = EXIT_FAIL if args.check and any(i["result"] == "fail" for i in doc["invariants"]) else EXIT_OK
            text = render_text(doc)
        elif args.command == "sync":
            from .sync import run_sync
            doc = run_sync(paths, timeout=args.timeout)
            code = EXIT_FAIL if any(i["result"] == "fail" for i in doc["invariants"]) else EXIT_OK
            text = render_sync(doc)
        elif args.command == "add":
            from .add import run_add
            doc = run_add(paths, args.name, alias=args.alias, timeout=args.timeout)
            code = EXIT_OK if doc["written"] else EXIT_FAIL
            text = render_add(doc)
        else:
            from .gate import run_gate
            doc = run_gate(paths)
            code = EXIT_OK if doc["result"] == "pass" else EXIT_FAIL
            text = render_gate(doc)
    except SchemaError as e:
        doc = {"command": args.command, "copy": describe_copy(paths), "error": str(e), "rule": e.rule}
        code, text = EXIT_SCHEMA, f"{copy_line(doc['copy'])}\nschema: {e}"
    except KeyError as e:  # RouteTable.resolve(): unknown route or alias
        doc = {"command": args.command, "copy": describe_copy(paths), "error": str(e.args[0])}
        code, text = EXIT_USAGE, f"{copy_line(doc['copy'])}\nerror: {e.args[0]}"
    print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) if args.json else text)
    return code


if __name__ == "__main__":
    sys.exit(main())
```

`cli.py` imports `SchemaError` from `agent_on/schemas/errors.py`, which Task 2 writes. For this task to pass, create the minimal version now — Task 2 replaces it whole:

`agent_on/schemas/__init__.py`: empty file.

`agent_on/schemas/errors.py` (Task 1 stub — Task 2 writes the real one):

```python
RULES: dict[str, str] = {}


class SchemaError(ValueError):
    def __init__(self, rule: str, detail: str):
        super().__init__(f"{rule}: {detail}")
        self.rule, self.detail = rule, detail
```

`bin/agent-on` (then `chmod +x bin/agent-on`):

```zsh
#!/usr/bin/env zsh
# agent-on shim. The checkout is the installation (D9): nothing here but "find python3 >= 3.11 and exec the package".
set -u
checkout="${0:A:h:h}"
py="${AGENT_ON_PYTHON:-$(command -v python3 2>/dev/null || true)}"
if [[ -z "$py" ]] || ! "$py" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  print -u2 -- "agent-on: python3 >= 3.11 not found on PATH (or AGENT_ON_PYTHON is not one)"
  exit 3
fi
export PYTHONPATH="$checkout${PYTHONPATH:+:$PYTHONPATH}"
exec "$py" -m agent_on "$@"
```

Append to `.gitignore`:

```
# agent-on: the routes.toml writer lock and its temp file live in the checkout (§7.1 rev 6)
.routes.lock
routes.toml.tmp.*
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: `Ran 10 tests … OK`. Also run `./bin/agent-on --help` by hand and `./bin/claude-litellm --help` (or `claude-litellm status`) to confirm the old path is untouched.

- [ ] **Step 5: Commit**

```bash
git add bin/agent-on agent_on tests/agent_on .gitignore
git commit -m "feat(agent-on): package skeleton, paths, copy.* and the zsh shim

Plan A task 1 of docs/superpowers/plans/2026-09-07-agent-on-plan-a.md.
Additive: nothing the old launcher reads is touched.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 2: L1 — the route schema, TOML emit, and the seed `routes.toml`

**Files:**
- Create: `agent_on/schemas/routes.py`, `routes.toml`
- Replace: `agent_on/schemas/errors.py` (the Task 1 stub)
- Test: `tests/agent_on/test_schema_routes.py`

**Interfaces:**
- Consumes: `util.canonical_json`, `util.sha16`, `Paths.routes_toml`, `Paths.discovered_toml`
- Produces: dataclasses `Limits(input, output, confidence, source)`, `Price(input, output, cache_read, cache_write, source)`, `Reasoning(supported, efforts, provider_efforts, source)`, `Source(name, base_url, auth_env, catalog, discover, limits)`, `Route(name, source, wire_model, aliases, limits, reasoning, price, packaged)`, `RouteTable(sources, routes, shadowed)`; functions `parse_routes_text`, `merge_tables`, `load_routes`, `route_block`, `discovered_text`; `errors.RULES`, `errors.SchemaError`.

Why the seed's numbers differ from `config/litellm_config.yaml`: the live OpenRouter catalog on 2026-09-07 says DeepSeek-V4-Pro's top provider serves **1,024,000** input (the yaml declares 1,048,576 — declared > advertised, an R1 drift), Kimi-K2.7-Code caps output at **235,929** (yaml: 262,144), GLM-5.2 at **131,072** (yaml: 32,768 labelled `provider`), Mimo-V2.5 now publishes 1,048,576 / 131,072 (yaml: 262,144 / 16,384 `owned-policy` "unpublished"). The seed carries the live provider figures with the date in `source`; the old yaml's oMLX output cap of 16,384 was a LiteLLM clamp policy and is not carried — oMLX routes inherit the source's `configured` 131,072 / 32,768 (§6 example, rev-6 inheritance rule). The three unreachable sources carry `owned-policy` limits labelled as pending measurement (S4, S5, S3) so their discovered routes are never uncapped. The reasoning tables carry `supported = true` with `confidence = "provider"` and no `efforts` list: OpenRouter's `supported_parameters` names parameters (`reasoning`, `reasoning_effort`), never effort levels, so a level list would be invented (spec §6, rev 7). The GPT and xAI OAuth routes are deliberately absent (D3; the decision record is seeded in Plan C).

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_schema_routes.py`:

```python
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.schemas.errors import RULES, SchemaError  # noqa: E402
from agent_on.schemas.routes import (  # noqa: E402
    Route, discovered_text, load_routes, merge_tables, parse_routes_text, route_block,
)

BASE = "http://127.0.0.1:1"


def routes(text: str):
    return parse_routes_text(text, packaged=True)


class ParseTest(unittest.TestCase):
    def test_fixture_parses_and_wire_model_defaults_to_the_name_tail(self):
        srcs, rts, stale = routes(MOCK_ROUTES.format(base=BASE))
        self.assertEqual(set(srcs), {"mock", "paid"})
        self.assertEqual(rts["mock/alpha"].wire_model, "alpha")
        self.assertEqual(rts["paid/vendor/model-x"].wire_model, "vendor/model-x")
        self.assertEqual(rts["mock/alpha"].aliases, ("a",))
        self.assertTrue(rts["mock/alpha"].packaged)
        self.assertEqual(stale, ())
        self.assertEqual(srcs["mock"].catalog_url(), f"{BASE}/v1/models")
        self.assertEqual(srcs["paid"].catalog_url(), f"{BASE}/api/v1/models")
        self.assertEqual(srcs["mock"].port(), 1)

    def assertRule(self, rule: str, text: str):
        with self.assertRaises(SchemaError) as cm:
            routes(text)
        self.assertEqual(cm.exception.rule, rule, str(cm.exception))

    def test_every_rule_is_stated_once_and_raised_with_its_id(self):
        head = 'version = 1\n[sources.mock]\nbase_url = "http://127.0.0.1:1"\n'
        self.assertRule("routes.version", 'version = 2\n[sources.mock]\nbase_url = "http://x"\n')
        self.assertRule("routes.version", "this is not toml [[[")
        self.assertRule("routes.source.shape", 'version = 1\n[sources.mock]\nbase_url = "ftp://x"\n')
        self.assertRule("routes.source.shape", head + "discover = 1\n")
        self.assertRule("routes.route.name", head + '[routes."nosource"]\n')
        self.assertRule("routes.route.name", head + '[routes."other/m"]\n')
        self.assertRule("routes.route.shape", head + '[routes."mock/m"]\nthinking = true\n')
        self.assertRule("routes.route.wire_model", head + '[routes."mock/m"]\nwire_model = ""\n')
        self.assertRule("routes.limits.shape", head + '[routes."mock/m".limits]\ninput = 10\n')
        self.assertRule("routes.limits.shape", head + '[routes."mock/m".limits]\ninput = 10\nconfidence = "verified"\nsource = "x"\n')
        self.assertRule("routes.limits.no_globs", head + '[routes."mock/Qwen*"]\n')
        self.assertRule("routes.reasoning.shape", head + '[routes."mock/m".reasoning]\nefforts = "low"\nsource = "x"\n')
        self.assertRule("routes.reasoning.shape", head + '[routes."mock/m".reasoning]\nsupported = true\n')
        self.assertRule("routes.price.shape", head + '[routes."mock/m".price]\ninput_usd_per_mtok = 1\nsource = "x"\n')
        self.assertRule("routes.alias.shape", head + '[routes."mock/m"]\naliases = ["a/b"]\n')
        self.assertRule("routes.unique", head + '[routes."mock/m"]\naliases = ["z"]\n[routes."mock/n"]\naliases = ["z"]\n')
        self.assertRule("routes.unique", head + '[routes."mock/m"]\nwire_model = "same"\n[routes."mock/n"]\nwire_model = "same"\n')
        for rule in ("routes.version", "routes.source.shape", "routes.route.name", "routes.route.shape", "routes.route.wire_model",
                     "routes.limits.shape", "routes.limits.no_globs", "routes.reasoning.shape", "routes.price.shape",
                     "routes.alias.shape", "routes.unique"):
            self.assertIn(rule, RULES)

    def test_reasoning_accepts_the_spec_shape_and_supported_alone(self):
        head = 'version = 1\n[sources.mock]\nbase_url = "http://127.0.0.1:1"\n'
        _, rts, _ = routes(head + '[routes."mock/m".reasoning]\nefforts = ["low", "high"]\nprovider_efforts = ["xhigh", "high"]\nconfidence = "provider"\nsource = "x"\n')
        r = rts["mock/m"].reasoning
        self.assertEqual((r.supported, r.efforts, r.provider_efforts, r.confidence), (True, ("low", "high"), ("xhigh", "high"), "provider"))
        _, rts, _ = routes(head + '[routes."mock/m".reasoning]\nsupported = true\nsource = "x"\n')
        r = rts["mock/m"].reasoning
        self.assertEqual((r.supported, r.efforts, r.confidence), (True, (), None))

    def test_unregistered_rule_cannot_be_raised(self):
        with self.assertRaises(KeyError):
            SchemaError("not.a.rule", "x")

    def test_discovered_file_may_not_declare_sources_and_drops_stale_sources(self):
        srcs, _, _ = routes(MOCK_ROUTES.format(base=BASE))
        with self.assertRaises(SchemaError) as cm:
            parse_routes_text('version = 1\n[sources.x]\nbase_url = "http://x"\n', packaged=False, sources=srcs)
        self.assertEqual(cm.exception.rule, "routes.source.shape")
        _, rts, stale = parse_routes_text('version = 1\n[routes."mock/new"]\n[routes."vanished/m"]\n', packaged=False, sources=srcs)
        self.assertEqual(set(rts), {"mock/new"})
        self.assertFalse(rts["mock/new"].packaged)
        self.assertEqual(stale, ("vanished/m",))


class MergeAndTableTest(unittest.TestCase):
    def test_packaged_wins_by_source_and_wire_model(self):
        srcs, packaged, _ = routes(MOCK_ROUTES.format(base=BASE))
        disc = {"mock/alpha": Route("mock/alpha", "mock", "alpha", (), None, None, None, False),
                "mock/beta": Route("mock/beta", "mock", "beta", (), None, None, None, False)}
        merged, shadowed = merge_tables(packaged, disc)
        self.assertEqual(shadowed, ("mock/alpha",))
        self.assertTrue(merged["mock/alpha"].packaged)
        self.assertIn("mock/beta", merged)
        with self.assertRaises(SchemaError):  # a discovered alias may not reuse a packaged alias
            merge_tables(packaged, {"mock/z": Route("mock/z", "mock", "z", ("a",), None, None, None, False)})

    def test_load_routes_merges_the_state_file_and_inherits_source_limits(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir()
            sb.paths.discovered_toml.write_text('version = 1\n[routes."mock/beta"]\n', encoding="utf-8")
            table = load_routes(sb.paths)
            self.assertEqual(set(table.routes), {"mock/alpha", "mock/gone", "paid/vendor/model-x", "mock/beta"})
            beta = table.routes["mock/beta"]
            self.assertIsNone(beta.limits)
            self.assertEqual(table.effective_limits(beta).input, 8192)        # inherited (§6, rev 6)
            self.assertEqual(table.effective_limits(table.routes["paid/vendor/model-x"]).input, 100000)
            self.assertIs(table.resolve("a"), table.routes["mock/alpha"])
            self.assertIs(table.resolve("mock/beta"), beta)
            with self.assertRaises(KeyError):
                table.resolve("nope")

    def test_effective_sha_tracks_the_source_entry_and_inherited_limits(self):
        # rev-5 P2: the fingerprint must change when the *source* changes, not only the route entry
        text = MOCK_ROUTES.format(base=BASE)
        with Sandbox(text) as sb:
            before = load_routes(sb.paths)
            sha_alpha = before.effective_sha(before.routes["mock/alpha"])
            sha_x = before.effective_sha(before.routes["paid/vendor/model-x"])
            sb.paths.routes_toml.write_text(text.replace("input = 8192", "input = 4096"), encoding="utf-8")
            after = load_routes(sb.paths)
            self.assertNotEqual(sha_alpha, after.effective_sha(after.routes["mock/alpha"]))   # inherited limit changed
            self.assertEqual(sha_x, after.effective_sha(after.routes["paid/vendor/model-x"]))  # unrelated route unchanged
            sb.paths.routes_toml.write_text(text.replace(f'base_url = "{BASE}"\nauth_env', 'base_url = "http://127.0.0.1:2"\nauth_env'), encoding="utf-8")
            moved = load_routes(sb.paths)
            self.assertNotEqual(sha_x, moved.effective_sha(moved.routes["paid/vendor/model-x"]))  # source URL changed


class EmitTest(unittest.TestCase):
    def test_route_block_round_trips_through_the_parser(self):
        srcs, rts, _ = routes(MOCK_ROUTES.format(base=BASE))
        r = rts["paid/vendor/model-x"]
        text = 'version = 1\n[sources.paid]\nbase_url = "http://127.0.0.1:1"\nauth_env = "K"\n\n' + route_block(r)
        _, again, _ = routes(text)
        self.assertEqual(again["paid/vendor/model-x"], r)

    def test_discovered_text_is_machine_state_with_no_sources(self):
        text = discovered_text([Route("mock/beta", "mock", "beta", (), None, None, None, False)], "2026-09-07T00:00:00Z")
        self.assertIn("never edit, never commit", text)
        self.assertNotIn("[sources", text)
        srcs, _, _ = routes(MOCK_ROUTES.format(base=BASE))
        _, rts, _ = parse_routes_text(text, packaged=False, sources=srcs)
        self.assertEqual(list(rts), ["mock/beta"])


class SeedTest(unittest.TestCase):
    """The checkout's routes.toml is data; these assertions are the only place its content is checked in code."""

    def test_seed_loads_and_carries_the_five_sources_and_no_oauth_routes(self):
        text = (REPO / "routes.toml").read_text(encoding="utf-8")
        srcs, rts, _ = routes(text)
        self.assertEqual(set(srcs), {"openrouter", "omlx", "omlx@morty", "omlx-tp2", "exo"})
        self.assertEqual(len(rts), 6)
        self.assertEqual(sum(r.source == "openrouter" for r in rts.values()), 4)
        self.assertEqual(sum(r.source == "omlx" for r in rts.values()), 2)
        self.assertFalse(any("chatgpt" in n or "xai" in n or "gpt-" in n for n in rts))  # D3
        for r in rts.values():
            if r.source == "openrouter":
                self.assertIsNotNone(r.price, r.name)
                self.assertEqual(r.limits.confidence, "provider", r.name)
        for s in srcs.values():
            if s.discover:
                self.assertIsNotNone(s.limits, f"{s.name}: a discoverable source must declare limits or its routes are uncapped")
        self.assertEqual(srcs["omlx"].limits.confidence, "configured")
        self.assertEqual(srcs["openrouter"].auth_env, "OPENROUTER_API_KEY")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests/agent_on/test_schema_routes.py -v` (from the checkout; or the discover form)
Expected: `ImportError: cannot import name 'RULES'` / `No module named 'agent_on.schemas.routes'`

- [ ] **Step 3: Write the schema**

`agent_on/schemas/errors.py` (replaces the Task 1 stub):

```python
"""Every field contract of the system, stated once (D5, F14). A validator may only raise a rule listed here;
`schema.complete` lints that every listed rule is raised somewhere."""
from __future__ import annotations

RULES: dict[str, str] = {
    # L1 — routes.toml / routes.discovered.toml (§6)
    "routes.version": "the file is valid TOML with version = 1 and only version/sources/routes at top level",
    "routes.source.shape": "a source has an http(s) base_url; optional auth_env, catalog, discover (bool), limits; nothing else — and only routes.toml declares sources",
    "routes.route.name": "a route name is <source>/<model> and the source is declared",
    "routes.route.shape": "a route table has only wire_model, aliases, limits, reasoning, price",
    "routes.route.wire_model": "wire_model is a non-empty string; it defaults to the name after the first '/'",
    "routes.limits.shape": "limits carry positive-integer input and/or output, a confidence in {provider, owned-policy, configured} and a source string",
    "routes.limits.no_globs": "no source or route key contains '*' or '?' — there are no globs (§6)",
    "routes.reasoning.shape": "reasoning has efforts / provider_efforts (lists of strings), an optional confidence in {provider, owned-policy, configured}, a source string, and an optional supported (bool; defaults to whether any efforts are listed) — it may stand alone when a catalog names only parameters, never invented levels",
    "routes.price.shape": "price has input_usd_per_mtok and output_usd_per_mtok (numbers ≥ 0), optional cache_read/cache_write, and a source string",
    "routes.alias.shape": "aliases is a list of non-empty strings without '/'",
    "routes.unique": "no two routes share a name, an alias, or (source, wire_model); a discovered route may not reuse a packaged alias",
    # L2 — observed.json (§7)
    "observed.shape": "observed.json has version, copy, sources, routes, last_check, last_gate_run, spend; each present record carries every key of its empty record",
    "observed.route.shape": "a route observation carries every key of the empty route record; unmeasured is null; caching is true, false or 'unknown'; served is true, false or null",
    "observed.no_claude_cost": "no key named total_cost_usd or costUSD anywhere — Claude Code's own cost figure is never copied (F11)",
    "observed.session.shape": "last_session is {skipped: reason} or the full record; this_run and session_total carry turns, usage (four fields) and cost_usd = number ≥ 0 or 'unknown'",
    # L5 — knowledge/*.jsonl (§10)
    "knowledge.record": "a record has id (prefixed by its kind), ts, and the fields of its kind",
}


class SchemaError(ValueError):
    """A contract violation, named by the rule it breaks. Constructing one with an unregistered rule is a bug."""

    def __init__(self, rule: str, detail: str):
        if rule not in RULES:
            raise KeyError(f"unregistered schema rule {rule!r} — add it to RULES with its statement")
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail
```

`agent_on/schemas/routes.py`:

```python
"""L1 — the route table (§6). The only place the routes.toml rules live (D5); the `RULES` ids name them."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from ..util import canonical_json, sha16
from .errors import SchemaError

L1_CONFIDENCES = ("provider", "owned-policy", "configured")   # `advertised` and `verified` are L2 tiers (§7)
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_SOURCE_KEYS = ("base_url", "auth_env", "catalog", "discover", "limits")
_ROUTE_KEYS = ("wire_model", "aliases", "limits", "reasoning", "price")


@dataclass(frozen=True)
class Limits:
    input: int | None
    output: int | None
    confidence: str
    source: str

    def as_dict(self) -> dict:
        return {"input": self.input, "output": self.output, "confidence": self.confidence, "source": self.source}


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None
    cache_write: float | None
    source: str

    def per_mtok(self) -> dict:
        return {"input": self.input, "output": self.output, "cache_read": self.cache_read, "cache_write": self.cache_write}


@dataclass(frozen=True)
class Reasoning:
    supported: bool
    efforts: tuple[str, ...]
    provider_efforts: tuple[str, ...]
    confidence: str | None
    source: str


@dataclass(frozen=True)
class Source:
    name: str
    base_url: str
    auth_env: str | None
    catalog: str | None
    discover: bool
    limits: Limits | None

    def catalog_url(self) -> str | None:
        if self.catalog is None:
            return None
        if self.catalog.startswith(("http://", "https://")):
            return self.catalog                                            # absolute: verbatim
        return urljoin(self.base_url.rstrip("/") + "/", self.catalog.lstrip("/"))   # relative: joined

    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def port(self) -> int:
        parts = urlsplit(self.base_url)
        return parts.port or (443 if parts.scheme == "https" else 80)


@dataclass(frozen=True)
class Route:
    name: str
    source: str
    wire_model: str
    aliases: tuple[str, ...]
    limits: Limits | None
    reasoning: Reasoning | None
    price: Price | None
    packaged: bool


@dataclass(frozen=True)
class RouteTable:
    sources: dict[str, Source]
    routes: dict[str, Route]
    shadowed: tuple[str, ...] = ()

    def resolve(self, name_or_alias: str) -> Route:
        if name_or_alias in self.routes:
            return self.routes[name_or_alias]
        for r in self.routes.values():
            if name_or_alias in r.aliases:
                return r
        raise KeyError(f"no route or alias {name_or_alias!r}; routes: {', '.join(sorted(self.routes))}")

    def effective_limits(self, route: Route) -> Limits | None:
        """A route's own limits, else its source's (§6 rev 6: inheritance is by declaring none, packaged or not)."""
        return route.limits if route.limits is not None else self.sources[route.source].limits

    def effective_sha(self, route: Route) -> str:
        """§8 `qualification.current`: the hash of the configuration a request actually uses — the route merged
        with its source (base_url, auth_env, catalog, inherited limits) — not HEAD and not the route entry alone."""
        src = self.sources[route.source]
        lim = self.effective_limits(route)
        doc = {"source": {"base_url": src.base_url, "auth_env": src.auth_env, "catalog": src.catalog},
               "route": {"wire_model": route.wire_model, "limits": lim.as_dict() if lim else None,
                         "reasoning": None if route.reasoning is None else {
                             "supported": route.reasoning.supported, "efforts": list(route.reasoning.efforts),
                             "provider_efforts": list(route.reasoning.provider_efforts)},
                         "price": None if route.price is None else route.price.per_mtok()}}
        return sha16(canonical_json(doc))

    def by_source(self, source: str) -> list[Route]:
        return [r for r in self.routes.values() if r.source == source]


# ---- parsing ---------------------------------------------------------------------------------------------------

def _no_globs(key: str, where: str) -> None:
    if "*" in key or "?" in key:
        raise SchemaError("routes.limits.no_globs", f"{where} {key!r} contains a glob character")


def _is_posint(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _parse_limits(d, where: str) -> Limits:
    if not isinstance(d, dict):
        raise SchemaError("routes.limits.shape", f"{where}: limits must be a table")
    for k in ("input", "output"):
        if d.get(k) is not None and not _is_posint(d[k]):
            raise SchemaError("routes.limits.shape", f"{where}: limits.{k} must be a positive integer")
    if d.get("input") is None and d.get("output") is None:
        raise SchemaError("routes.limits.shape", f"{where}: limits must carry input and/or output")
    if d.get("confidence") not in L1_CONFIDENCES:
        raise SchemaError("routes.limits.shape", f"{where}: limits.confidence must be one of {L1_CONFIDENCES}, got {d.get('confidence')!r}")
    if not isinstance(d.get("source"), str) or not d["source"]:
        raise SchemaError("routes.limits.shape", f"{where}: limits.source must say where the figure came from")
    return Limits(d.get("input"), d.get("output"), d["confidence"], d["source"])


def _parse_price(d, where: str) -> Price:
    if not isinstance(d, dict):
        raise SchemaError("routes.price.shape", f"{where}: price must be a table")

    def num(k: str, required: bool) -> float | None:
        v = d.get(k)
        if v is None:
            if required:
                raise SchemaError("routes.price.shape", f"{where}: price.{k} is required")
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise SchemaError("routes.price.shape", f"{where}: price.{k} must be a number ≥ 0")
        return float(v)

    if not isinstance(d.get("source"), str) or not d["source"]:
        raise SchemaError("routes.price.shape", f"{where}: price.source is required")
    return Price(num("input_usd_per_mtok", True), num("output_usd_per_mtok", True),
                 num("cache_read_usd_per_mtok", False), num("cache_write_usd_per_mtok", False), d["source"])


def _parse_reasoning(d, where: str) -> Reasoning:
    """§6: efforts / provider_efforts, confidence, source. `supported` may stand alone: OpenRouter's
    supported_parameters names parameters (`reasoning`, `reasoning_effort`), never levels, so `add` writes
    `supported` + `confidence = "provider"` and no invented effort list."""
    if not isinstance(d, dict):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning must be a table")

    def strs(k: str) -> tuple[str, ...]:
        v = d.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.{k} must be a list of strings")
        return tuple(v)

    efforts, provider_efforts = strs("efforts"), strs("provider_efforts")
    supported = d.get("supported", bool(efforts or provider_efforts))
    if not isinstance(supported, bool):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.supported must be a bool")
    confidence = d.get("confidence")
    if confidence is not None and confidence not in L1_CONFIDENCES:
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.confidence must be one of {L1_CONFIDENCES}")
    if not isinstance(d.get("source"), str) or not d["source"]:
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.source must say where it came from")
    for k in d:
        if k not in ("supported", "efforts", "provider_efforts", "confidence", "source"):
            raise SchemaError("routes.reasoning.shape", f"{where}: unknown reasoning key {k!r}")
    return Reasoning(supported, efforts, provider_efforts, confidence, d["source"])


def _parse_source(name: str, d) -> Source:
    _no_globs(name, "source")
    if not isinstance(d, dict):
        raise SchemaError("routes.source.shape", f"source {name!r} must be a table")
    base = d.get("base_url")
    if not isinstance(base, str) or not base.startswith(("http://", "https://")):
        raise SchemaError("routes.source.shape", f"source {name!r}: base_url must be an http(s) URL")
    for k in ("auth_env", "catalog"):
        if d.get(k) is not None and (not isinstance(d[k], str) or not d[k]):
            raise SchemaError("routes.source.shape", f"source {name!r}: {k} must be a non-empty string")
    if not isinstance(d.get("discover", False), bool):
        raise SchemaError("routes.source.shape", f"source {name!r}: discover must be a bool")
    for k in d:
        if k not in _SOURCE_KEYS:
            raise SchemaError("routes.source.shape", f"source {name!r}: unknown key {k!r}")
    return Source(name, base, d.get("auth_env"), d.get("catalog"), d.get("discover", False),
                  _parse_limits(d["limits"], f"source {name!r}") if "limits" in d else None)


def _parse_route(name: str, d, sources: dict[str, Source], packaged: bool) -> Route:
    _no_globs(name, "route")
    src, _, rest = name.partition("/")
    if not src or not rest:
        raise SchemaError("routes.route.name", f"route {name!r} must be <source>/<model>")
    if src not in sources:
        raise SchemaError("routes.route.name", f"route {name!r}: source {src!r} is not declared under [sources]")
    if not isinstance(d, dict):
        raise SchemaError("routes.route.shape", f"route {name!r} must be a table")
    for k in d:
        if k not in _ROUTE_KEYS:
            raise SchemaError("routes.route.shape", f"route {name!r}: unknown key {k!r} (allowed: {_ROUTE_KEYS})")
    wm = d.get("wire_model", rest)
    if not isinstance(wm, str) or not wm:
        raise SchemaError("routes.route.wire_model", f"route {name!r}: wire_model must be a non-empty string")
    aliases = d.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a and "/" not in a for a in aliases):
        raise SchemaError("routes.alias.shape", f"route {name!r}: aliases must be non-empty strings without '/'")
    return Route(name, src, wm, tuple(aliases),
                 _parse_limits(d["limits"], f"route {name!r}") if "limits" in d else None,
                 _parse_reasoning(d["reasoning"], f"route {name!r}") if "reasoning" in d else None,
                 _parse_price(d["price"], f"route {name!r}") if "price" in d else None, packaged)


def parse_routes_text(text: str, *, packaged: bool, sources: dict[str, Source] | None = None):
    """Parse one file. A packaged file (routes.toml) declares sources; a discovered file may only reference them
    (pass `sources`). Returns (sources, routes, stale): `stale` names discovered routes whose source is no longer
    declared — dropped, not fatal, because `sync` rewrites that file."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SchemaError("routes.version", f"not valid TOML: {e}") from None
    if doc.get("version") != 1:
        raise SchemaError("routes.version", f"version must be 1, got {doc.get('version')!r}")
    for k in doc:
        if k not in ("version", "sources", "routes"):
            raise SchemaError("routes.version", f"unknown top-level key {k!r}")
    if packaged:
        raw = doc.get("sources")
        if not isinstance(raw, dict) or not raw:
            raise SchemaError("routes.source.shape", "at least one [sources.<name>] table is required")
        srcs = {n: _parse_source(n, d) for n, d in raw.items()}
    else:
        if "sources" in doc:
            raise SchemaError("routes.source.shape", "routes.discovered.toml may not declare sources")
        srcs = dict(sources or {})
    routes: dict[str, Route] = {}
    seen_alias: dict[str, str] = {}
    seen_key: dict[tuple[str, str], str] = {}
    stale: list[str] = []
    raw_routes = doc.get("routes") or {}
    if not isinstance(raw_routes, dict):
        raise SchemaError("routes.route.name", "[routes] must be a table of <source>/<model> tables")
    for n, d in raw_routes.items():
        if not packaged and n.partition("/")[0] not in srcs:
            stale.append(n)
            continue
        r = _parse_route(n, d, srcs, packaged)
        for a in r.aliases:
            if a in seen_alias:
                raise SchemaError("routes.unique", f"alias {a!r} on {n!r} is already on {seen_alias[a]!r}")
            seen_alias[a] = n
        key = (r.source, r.wire_model)
        if key in seen_key:
            raise SchemaError("routes.unique", f"{n!r} and {seen_key[key]!r} both serve {key}")
        seen_key[key] = n
        routes[n] = r
    return srcs, routes, tuple(stale)


def merge_tables(packaged: dict[str, Route], discovered: dict[str, Route]) -> tuple[dict[str, Route], tuple[str, ...]]:
    """Read-time dedup, packaged wins, keyed by (source, wire_model) (§6)."""
    keys = {(r.source, r.wire_model) for r in packaged.values()}
    aliases = {a for r in packaged.values() for a in r.aliases}
    merged = dict(packaged)
    shadowed: list[str] = []
    for n, r in discovered.items():
        if n in merged or (r.source, r.wire_model) in keys:
            shadowed.append(n)
            continue
        if any(a in aliases for a in r.aliases):
            raise SchemaError("routes.unique", f"discovered {n!r} reuses a packaged alias")
        merged[n] = r
    return merged, tuple(shadowed)


def load_routes(paths) -> RouteTable:
    srcs, packaged, _ = parse_routes_text(paths.routes_toml.read_text(encoding="utf-8"), packaged=True)
    discovered: dict[str, Route] = {}
    if paths.discovered_toml.exists():
        _, discovered, _ = parse_routes_text(paths.discovered_toml.read_text(encoding="utf-8"), packaged=False, sources=srcs)
    routes, shadowed = merge_tables(packaged, discovered)
    return RouteTable(srcs, routes, shadowed)


# ---- emitting ----------------------------------------------------------------------------------------------------
# tomllib has no writer; this covers exactly the subset the schema admits.

def _key(k: str) -> str:
    return k if _BARE_KEY.match(k) else '"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    raise TypeError(f"cannot emit {type(v).__name__}")


def route_block(route: Route) -> str:
    """The TOML for one route — what `add` appends to routes.toml and what `sync` writes per discovered route."""
    head = f"routes.{_key(route.name)}"
    lines = [f"[{head}]", f"wire_model = {_val(route.wire_model)}"]
    if route.aliases:
        lines.append(f"aliases = {_val(list(route.aliases))}")
    if route.limits:
        lines += ["", f"[{head}.limits]"] + [f"{k} = {_val(v)}" for k, v in route.limits.as_dict().items() if v is not None]
    if route.reasoning:
        r = route.reasoning
        lines += ["", f"[{head}.reasoning]", f"supported = {_val(r.supported)}"]
        if r.efforts:
            lines.append(f"efforts = {_val(list(r.efforts))}")
        if r.provider_efforts:
            lines.append(f"provider_efforts = {_val(list(r.provider_efforts))}")
        if r.confidence:
            lines.append(f"confidence = {_val(r.confidence)}")
        lines.append(f"source = {_val(r.source)}")
    if route.price:
        p = route.price
        lines += ["", f"[{head}.price]", f"input_usd_per_mtok = {_val(p.input)}", f"output_usd_per_mtok = {_val(p.output)}"]
        if p.cache_read is not None:
            lines.append(f"cache_read_usd_per_mtok = {_val(p.cache_read)}")
        if p.cache_write is not None:
            lines.append(f"cache_write_usd_per_mtok = {_val(p.cache_write)}")
        lines.append(f"source = {_val(p.source)}")
    return "\n".join(lines) + "\n"


def discovered_text(routes: list[Route], written_at: str) -> str:
    head = (f"# Written by `agent-on sync` at {written_at}. Machine state (D13): never edit, never commit.\n"
            "# A packaged route in routes.toml with the same (source, wire_model) shadows an entry here.\n"
            "version = 1\n")
    return head + "".join("\n" + route_block(r) for r in routes)
```

`routes.toml` (checkout root):

```toml
# agent-on route table — L1, the only declarations (spec §6). Git-tracked; edited by hand or by `agent-on add`.
# Route names are <source>/<model> (D10). Every numeric limit carries a confidence and a source.
# The GPT and xAI OAuth routes packaged in litellm_config.yaml are deliberately absent (D3).
version = 1

[sources.openrouter]
base_url = "https://openrouter.ai/api"
auth_env = "OPENROUTER_API_KEY"
catalog  = "https://openrouter.ai/api/v1/models"

[sources.omlx]
base_url = "http://127.0.0.1:8000"
catalog  = "/v1/models"
discover = true

[sources.omlx.limits]
input      = 131072
output     = 32768
confidence = "configured"
source     = "~/.omlx/settings.json sampling.max_context_window / sampling.max_tokens (read 2026-09-07)"

[sources."omlx@morty"]
base_url = "http://mortys-mac-studio:8000"
catalog  = "/v1/models"
discover = true

[sources."omlx@morty".limits]
input      = 131072
output     = 32768
confidence = "owned-policy"
source     = "assumed equal to the local oMLX settings until S5 measures morty; the remote settings file is not readable from here"

[sources.omlx-tp2]
base_url = "http://127.0.0.1:8003"
catalog  = "/v1/models"
discover = true

[sources.omlx-tp2.limits]
input      = 131072
output     = 32768
confidence = "owned-policy"
source     = "assumed equal to the single-node oMLX settings until S4 measures the TP2 endpoint (down on 2026-09-07)"

[sources.exo]
base_url = "http://127.0.0.1:52415"
catalog  = "/v1/models"
discover = true

[sources.exo.limits]
input      = 131072
output     = 32768
confidence = "owned-policy"
source     = "placeholder cap until S3 measures exo (not installed on 2026-09-07)"

# ---- OpenRouter: limits and prices from the live catalog on 2026-09-07 (top_provider.*, pricing.*) --------------

[routes."openrouter/deepseek/deepseek-v4-pro"]
wire_model = "deepseek/deepseek-v4-pro"
aliases    = ["deepseek"]

[routes."openrouter/deepseek/deepseek-v4-pro".limits]
input      = 1024000
output     = 384000
confidence = "provider"
source     = "openrouter.top_provider.context_length / max_completion_tokens (2026-09-07)"

[routes."openrouter/deepseek/deepseek-v4-pro".reasoning]
supported  = true
confidence = "provider"
source     = "openrouter.supported_parameters: reasoning, reasoning_effort (2026-09-07)"

[routes."openrouter/deepseek/deepseek-v4-pro".price]
input_usd_per_mtok      = 0.63684
output_usd_per_mtok     = 1.27368
cache_read_usd_per_mtok = 0.05307
source                  = "openrouter.pricing (2026-09-07); no cache-write price published"

[routes."openrouter/moonshotai/kimi-k2.7-code"]
wire_model = "moonshotai/kimi-k2.7-code"
aliases    = ["kimi"]

[routes."openrouter/moonshotai/kimi-k2.7-code".limits]
input      = 262144
output     = 235929
confidence = "provider"
source     = "openrouter.top_provider.context_length / max_completion_tokens (2026-09-07)"

[routes."openrouter/moonshotai/kimi-k2.7-code".reasoning]
supported  = true
confidence = "provider"
source     = "openrouter.supported_parameters: reasoning (2026-09-07)"

[routes."openrouter/moonshotai/kimi-k2.7-code".price]
input_usd_per_mtok      = 0.66
output_usd_per_mtok     = 3.4
cache_read_usd_per_mtok = 0.18
source                  = "openrouter.pricing (2026-09-07); no cache-write price published"

[routes."openrouter/xiaomi/mimo-v2.5"]
wire_model = "xiaomi/mimo-v2.5"
aliases    = ["mimo"]

[routes."openrouter/xiaomi/mimo-v2.5".limits]
input      = 1048576
output     = 131072
confidence = "provider"
source     = "openrouter.top_provider.context_length / max_completion_tokens (2026-09-07)"

[routes."openrouter/xiaomi/mimo-v2.5".reasoning]
supported  = true
confidence = "provider"
source     = "openrouter.supported_parameters: reasoning (2026-09-07)"

[routes."openrouter/xiaomi/mimo-v2.5".price]
input_usd_per_mtok      = 0.14
output_usd_per_mtok     = 0.28
cache_read_usd_per_mtok = 0.0028
source                  = "openrouter.pricing (2026-09-07); no cache-write price published"

[routes."openrouter/z-ai/glm-5.2"]
wire_model = "z-ai/glm-5.2"
aliases    = ["glm"]

[routes."openrouter/z-ai/glm-5.2".limits]
input      = 1048576
output     = 131072
confidence = "provider"
source     = "openrouter.top_provider.context_length / max_completion_tokens (2026-09-07)"

[routes."openrouter/z-ai/glm-5.2".reasoning]
supported  = true
confidence = "provider"
source     = "openrouter.supported_parameters: reasoning, reasoning_effort (2026-09-07)"

[routes."openrouter/z-ai/glm-5.2".price]
input_usd_per_mtok      = 0.966
output_usd_per_mtok     = 3.036
cache_read_usd_per_mtok = 0.1932
source                  = "openrouter.pricing (2026-09-07); no cache-write price published"

# ---- oMLX on this machine: limits inherited from [sources.omlx.limits]; free ---------------------------------------

[routes."omlx/root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp"]
wire_model = "root4k--Huihui-Qwen3.8-27B-abliterated-oQ4e-mtp"
aliases    = ["huihui"]

[routes."omlx/Qwen3.8-27B-Uncensored-8bit"]
wire_model = "Qwen3.8-27B-Uncensored-8bit"
aliases    = ["uncensored8"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass (Task 1's 10 + this file's 9). Also: `python3 -c "import tomllib; tomllib.load(open('routes.toml','rb'))"` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add agent_on/schemas routes.toml tests/agent_on/test_schema_routes.py
git commit -m "feat(agent-on): L1 route schema, TOML emit, and the seed routes.toml

Six packaged routes (four OpenRouter with live 2026-09-07 provider limits
and prices, two oMLX inheriting the configured source limits); five sources.
GPT/xAI OAuth routes deliberately absent (D3).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---
### Task 3: L2 — the observed schema, `compute_context`, and the F11 guard

**Files:**
- Create: `agent_on/schemas/observed.py`
- Test: `tests/agent_on/test_schema_observed.py`

**Interfaces:**
- Consumes: `errors.SchemaError`
- Produces: `USAGE_FIELDS`, `empty_observed()`, `empty_source()`, `empty_route()`, `empty_tier()`, `empty_cost_model()`, `validate_observed(doc)`, `validate_session(s, where)`, `compute_context(declared, tier) -> (int|None, str|None)`, `forbid_claude_cost(obj)`.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_schema_observed.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import (  # noqa: E402
    USAGE_FIELDS, compute_context, empty_observed, empty_route, empty_source, forbid_claude_cost, validate_observed,
)


def usage(**kw) -> dict:
    return {k: kw.get(k, 0) for k in USAGE_FIELDS}


def full_session(cost="unknown") -> dict:
    return {"id": "s", "at": "2026-09-07T00:00:00Z",
            "first_request": {"input_tokens_total": 10, "usage": usage(input_tokens=10)},
            "this_run": {"turns": 1, "usage": usage(input_tokens=10), "cost_usd": cost, "models_seen": ["m"]},
            "session_total": {"turns": 1, "usage": usage(input_tokens=10), "cost_usd": cost, "covered_turns": 1, "uncovered_turns": 0},
            "scope_note": "fresh", "duration_ms": 1, "effort": None, "permission_mode": None, "claude_code": "2.1.263"}


class ShapeTest(unittest.TestCase):
    def test_empty_document_validates_and_every_unmeasured_field_is_null_not_absent(self):
        doc = empty_observed()
        validate_observed(doc)
        r = empty_route()
        self.assertIsNone(r["served"])
        self.assertEqual(r["cost_model"]["caching"], "unknown")
        self.assertEqual(set(r["limits"]["input"]), {"configured", "advertised", "verified", "checked"})
        self.assertIn("identity", empty_source())

    def assertRule(self, rule, doc):
        with self.assertRaises(SchemaError) as cm:
            validate_observed(doc)
        self.assertEqual(cm.exception.rule, rule, str(cm.exception))

    def test_missing_keys_and_bad_values_are_rejected_by_name(self):
        doc = empty_observed(); del doc["spend"]
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["version"] = 2
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["sources"]["s"] = {"reachable": True}
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["routes"]["r"] = empty_route(); del doc["routes"]["r"]["cost_model"]["caching"]
        self.assertRule("observed.route.shape", doc)
        doc = empty_observed(); doc["routes"]["r"] = empty_route(); doc["routes"]["r"]["cost_model"]["caching"] = None
        self.assertRule("observed.route.shape", doc)
        doc = empty_observed(); doc["routes"]["r"] = empty_route(); doc["routes"]["r"]["served"] = "yes"
        self.assertRule("observed.route.shape", doc)
        doc = empty_observed(); doc["last_check"] = {"at": "x"}
        self.assertRule("observed.shape", doc)
        doc = empty_observed(); doc["last_gate_run"] = {"at": "x", "result": "pass"}
        self.assertRule("observed.shape", doc)

    def test_claude_codes_own_cost_figure_is_rejected_anywhere(self):  # F11
        doc = empty_observed(); doc["routes"]["r"] = empty_route()
        doc["routes"]["r"]["last_session"] = {"skipped": "x", "total_cost_usd": 0.24}
        self.assertRule("observed.no_claude_cost", doc)
        doc = empty_observed(); doc["spend"]["x"] = [{"costUSD": 1}]
        self.assertRule("observed.no_claude_cost", doc)
        forbid_claude_cost({"a": [{"b": {"ok": 1}}]})  # no raise

    def test_last_session_is_skipped_or_full(self):
        doc = empty_observed(); doc["routes"]["r"] = empty_route()
        doc["routes"]["r"]["last_session"] = {"skipped": "no-session-persistence"}
        validate_observed(doc)
        doc["routes"]["r"]["last_session"] = full_session(0.0)
        validate_observed(doc)
        doc["routes"]["r"]["last_session"] = full_session("unknown")
        validate_observed(doc)
        doc["routes"]["r"]["last_session"] = full_session(-1)
        self.assertRule("observed.session.shape", doc)
        doc["routes"]["r"]["last_session"] = full_session("free")
        self.assertRule("observed.session.shape", doc)
        s = full_session(); del s["session_total"]["covered_turns"]; doc["routes"]["r"]["last_session"] = s
        self.assertRule("observed.session.shape", doc)
        doc["routes"]["r"]["last_session"] = {"skipped": ""}
        self.assertRule("observed.session.shape", doc)


class ContextTest(unittest.TestCase):
    """§7: min(declared, verified) when verified is present, else min(declared, configured, advertised);
    declared participates in both branches; verified only lowers; a tie names `declared`."""

    def tier(self, **kw):
        return {"configured": kw.get("configured"), "advertised": kw.get("advertised"), "verified": kw.get("verified"), "checked": None}

    def test_verified_never_lifts_the_declared_cap(self):
        self.assertEqual(compute_context(32768, self.tier(verified=131072)), (32768, "declared"))

    def test_verified_lowers(self):
        self.assertEqual(compute_context(131072, self.tier(verified=100000)), (100000, "verified"))
        self.assertEqual(compute_context(None, self.tier(verified=100000)), (100000, "verified"))

    def test_verified_branch_ignores_configured_and_advertised(self):
        self.assertEqual(compute_context(131072, self.tier(verified=131072, configured=8192, advertised=4096)), (131072, "declared"))

    def test_unverified_branch_takes_the_minimum_and_names_it(self):
        self.assertEqual(compute_context(200000, self.tier(configured=131072, advertised=262144)), (131072, "configured"))
        self.assertEqual(compute_context(200000, self.tier(advertised=100000)), (100000, "advertised"))
        self.assertEqual(compute_context(None, self.tier(configured=131072, advertised=262144)), (131072, "configured"))

    def test_tie_names_declared(self):
        self.assertEqual(compute_context(131072, self.tier(configured=131072, advertised=262144)), (131072, "declared"))

    def test_nothing_known_is_null_not_zero(self):
        self.assertEqual(compute_context(None, self.tier()), (None, None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_schema_observed.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.schemas.observed'`

- [ ] **Step 3: Write the module**

`agent_on/schemas/observed.py`:

```python
"""L2 — the shape of $STATE/observed.json (§7). Unmeasured is null, never absent; caching is three-valued;
Claude Code's own cost figure is rejected anywhere (F11)."""
from __future__ import annotations

from .errors import SchemaError

OBSERVED_VERSION = 1
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
FORBIDDEN_KEYS = ("total_cost_usd", "costUSD")
CACHING_VALUES = (True, False, "unknown")
SESSION_KEYS = ("id", "at", "first_request", "this_run", "session_total", "scope_note", "duration_ms", "effort", "permission_mode", "claude_code")
CHECK_KEYS = ("at", "commit", "result", "skipped")
GATE_RUN_KEYS = ("at", "commit", "result", "tests", "verifiers", "invariants", "skipped", "skipped_reasons", "mock_port")


def empty_tier() -> dict:
    return {"configured": None, "advertised": None, "verified": None, "checked": None}


def empty_cost_model() -> dict:
    return {"context": None, "context_basis": None, "harness_baseline_tokens": None, "tok_s": None,
            "usd_per_mtok": None, "caching": "unknown", "concurrency": None, "thinking": None, "checked": None}


def empty_route() -> dict:
    return {"served": None, "checked": None, "limits": {"input": empty_tier(), "output": empty_tier()},
            "cost_model": empty_cost_model(), "last_qualification": None, "last_session": None}


def empty_source() -> dict:
    return {"reachable": None, "checked": None, "error": None, "catalog": None, "catalog_count": None,
            "configured_limits": None, "identity": None}


def empty_observed() -> dict:
    return {"version": OBSERVED_VERSION, "copy": None, "sources": {}, "routes": {}, "last_check": None,
            "last_gate_run": None, "spend": {}}


def forbid_claude_cost(obj, path: str = "$") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                raise SchemaError("observed.no_claude_cost", f"{path}.{k} is Claude Code's own cost figure (F11)")
            forbid_claude_cost(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            forbid_claude_cost(v, f"{path}[{i}]")


def _require_keys(d, keys, where: str, rule: str) -> None:
    if not isinstance(d, dict):
        raise SchemaError(rule, f"{where} must be an object")
    missing = [k for k in keys if k not in d]
    if missing:
        raise SchemaError(rule, f"{where} lacks {missing} — unmeasured must be null, not absent")


def _is_cost(c) -> bool:
    return c == "unknown" or (isinstance(c, (int, float)) and not isinstance(c, bool) and c >= 0)


def validate_session(s, where: str) -> None:
    if not isinstance(s, dict):
        raise SchemaError("observed.session.shape", f"{where} must be an object")
    if set(s) == {"skipped"}:
        if not isinstance(s["skipped"], str) or not s["skipped"]:
            raise SchemaError("observed.session.shape", f"{where}.skipped must say why")
        return
    _require_keys(s, SESSION_KEYS, where, "observed.session.shape")
    _require_keys(s["first_request"], ("input_tokens_total", "usage"), f"{where}.first_request", "observed.session.shape")
    for part, extra in (("this_run", ("models_seen",)), ("session_total", ("covered_turns", "uncovered_turns"))):
        p = s[part]
        _require_keys(p, ("turns", "usage", "cost_usd") + extra, f"{where}.{part}", "observed.session.shape")
        _require_keys(p["usage"], USAGE_FIELDS, f"{where}.{part}.usage", "observed.session.shape")
        if not _is_cost(p["cost_usd"]):
            raise SchemaError("observed.session.shape", f"{where}.{part}.cost_usd must be a number ≥ 0 or the string 'unknown'")


def validate_route(r, where: str) -> None:
    _require_keys(r, tuple(empty_route()), where, "observed.route.shape")
    _require_keys(r["limits"], ("input", "output"), f"{where}.limits", "observed.route.shape")
    for k in ("input", "output"):
        _require_keys(r["limits"][k], tuple(empty_tier()), f"{where}.limits.{k}", "observed.route.shape")
    _require_keys(r["cost_model"], tuple(empty_cost_model()), f"{where}.cost_model", "observed.route.shape")
    if r["cost_model"]["caching"] not in CACHING_VALUES:
        raise SchemaError("observed.route.shape", f"{where}.cost_model.caching must be true, false or 'unknown'")
    if r["served"] not in (True, False, None):
        raise SchemaError("observed.route.shape", f"{where}.served must be true, false or null")
    if r["last_session"] is not None:
        validate_session(r["last_session"], f"{where}.last_session")


def validate_observed(doc) -> None:
    _require_keys(doc, tuple(empty_observed()), "observed", "observed.shape")
    if doc["version"] != OBSERVED_VERSION:
        raise SchemaError("observed.shape", f"observed.version must be {OBSERVED_VERSION}, got {doc['version']!r}")
    forbid_claude_cost(doc)
    for n, s in doc["sources"].items():
        _require_keys(s, tuple(empty_source()), f"sources.{n}", "observed.shape")
    for n, r in doc["routes"].items():
        validate_route(r, f"routes.{n}")
    if doc["last_check"] is not None:
        _require_keys(doc["last_check"], CHECK_KEYS, "last_check", "observed.shape")
    if doc["last_gate_run"] is not None:
        _require_keys(doc["last_gate_run"], GATE_RUN_KEYS, "last_gate_run", "observed.shape")


def compute_context(declared: int | None, tier: dict) -> tuple[int | None, str | None]:
    """§7: min(declared, verified) when verified is present, else min(declared, configured, advertised).
    The declared cap participates in both branches; `verified` only ever lowers. On a tie the basis is `declared`,
    because the operator's cap is the reason the number is what it is."""
    if tier.get("verified") is not None:
        cands = [("declared", declared), ("verified", tier["verified"])]
    else:
        cands = [("declared", declared), ("configured", tier.get("configured")), ("advertised", tier.get("advertised"))]
    cands = [(n, v) for n, v in cands if v is not None]
    if not cands:
        return None, None
    best = min(v for _, v in cands)
    for n, v in cands:            # first wins a tie, and `declared` is first
        if v == best:
            return best, n
    return None, None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/schemas/observed.py tests/agent_on/test_schema_observed.py
git commit -m "feat(agent-on): L2 observed schema, the context formula, and the F11 guard

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 4: §11 cost attribution — pure functions and the per-session fold (rev-6 P2)

**Files:**
- Create: `agent_on/cost.py`
- Test: `tests/agent_on/test_cost.py`

**Interfaces:**
- Consumes: `observed.USAGE_FIELDS`, `util.parse_utc`
- Produces: `PRICE_FOR`, `zero_usage()`, `sum_usage(usages)`, `price_usage(usage, price) -> (float|None, reasons)`, `turns_in(turns, started, ended)`, `attribute_run(turns, run) -> ledger line`, `fold_session(turns, runs) -> session_total`. A *turn* is `{"timestamp": rfc3339, "model": wire_model, "usage": {four fields}}` (the verified transcript fields, §7). A *run* is `{"launch_id", "route", "source", "wire_model", "started", "ended", "price", "priced_models"}` where `price` is the L1 price snapshot at spawn and `priced_models` maps other wire_models on the same source to their prices. Plan B's launcher builds turns from the transcript and runs from `run/<launch-id>/`; this task fixes the arithmetic and the `unknown` rule.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_cost.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.cost import attribute_run, fold_session, price_usage, sum_usage  # noqa: E402

PAID = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": None}   # USD per Mtok; no cache-write price published
FREE = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def u(i=0, o=0, cr=0, cw=0):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}


def turn(ts, model, usage):
    return {"timestamp": ts, "model": model, "usage": usage}


def run(launch_id, wire, started, ended, price, source="paid", priced_models=None):
    return {"launch_id": launch_id, "route": f"{source}/{wire}", "source": source, "wire_model": wire,
            "started": started, "ended": ended, "price": price, "priced_models": priced_models or {}}


class PriceTest(unittest.TestCase):
    def test_usage_times_price_over_four_fields(self):
        usd, why = price_usage(u(i=1_000_000, o=500_000, cr=2_000_000), PAID)
        self.assertEqual((usd, why), (1.0 + 1.0 + 0.2, []))

    def test_an_absent_price_is_not_zero(self):
        usd, why = price_usage(u(i=10, cw=10), PAID)
        self.assertIsNone(usd)
        self.assertIn("cache_write", why[0])
        self.assertEqual(price_usage(u(i=10), None), (None, ["no price table"]))
        self.assertEqual(price_usage(u(cw=0), PAID), (0.0, []))      # a zero field needs no price

    def test_sum_usage(self):
        self.assertEqual(sum_usage([u(i=1, o=2), u(i=3, cr=4)]), u(i=4, o=2, cr=4))


class AttributionTest(unittest.TestCase):
    T = ["2026-09-07T01:00:00Z", "2026-09-07T01:01:00Z", "2026-09-07T01:02:00Z", "2026-09-07T01:03:00Z"]

    def test_a_run_prices_its_own_window_at_its_own_snapshot(self):
        turns = [turn(self.T[0], "m", u(i=1_000_000)), turn(self.T[1], "m", u(o=1_000_000)), turn(self.T[3], "m", u(i=9))]
        line = attribute_run(turns, run("L1", "m", self.T[0], self.T[2], PAID))
        self.assertEqual(line["turns"], 2)
        self.assertEqual(line["cost_usd"], 3.0)
        self.assertEqual(line["models_seen"], ["m"])
        self.assertEqual(line["usage"], u(i=1_000_000, o=1_000_000))

    def test_a_switched_model_without_a_price_makes_the_run_unknown(self):
        turns = [turn(self.T[0], "m", u(i=10)), turn(self.T[1], "other", u(i=10))]
        line = attribute_run(turns, run("L1", "m", self.T[0], None, PAID))
        self.assertEqual(line["cost_usd"], "unknown")
        self.assertEqual(line["models_seen"], ["m", "other"])
        self.assertTrue(any("other" in r for r in line["unknown_reasons"]))
        priced = attribute_run(turns, run("L1", "m", self.T[0], None, PAID, priced_models={"other": FREE}))
        self.assertEqual(priced["cost_usd"], 0.00001)

    def test_unpriced_field_makes_the_run_unknown(self):
        line = attribute_run([turn(self.T[0], "m", u(cw=5))], run("L1", "m", self.T[0], None, PAID))
        self.assertEqual(line["cost_usd"], "unknown")


class FoldTest(unittest.TestCase):
    T = ["2026-09-07T01:00:00Z", "2026-09-07T01:01:00Z", "2026-09-07T02:00:00Z", "2026-09-07T02:01:00Z"]

    def test_fresh_session_this_run_equals_session_total(self):
        turns = [turn(self.T[0], "m", u(i=1_000_000)), turn(self.T[1], "m", u(o=1_000_000))]
        line = attribute_run(turns, run("L1", "m", self.T[0], self.T[1], PAID))
        total = fold_session(turns, [line])
        self.assertEqual(total["cost_usd"], line["cost_usd"])
        self.assertEqual((total["turns"], total["covered_turns"], total["uncovered_turns"]), (2, 2, 0))

    def test_paid_then_free_resume_is_paid_plus_zero_not_zero(self):
        # the rev-6 P2: a session begun on a paid route and resumed on a free one keeps the paid cost
        turns = [turn(self.T[0], "paid-m", u(i=1_000_000)), turn(self.T[1], "paid-m", u(o=1_000_000)),
                 turn(self.T[2], "free-m", u(i=5_000_000)), turn(self.T[3], "free-m", u(o=5_000_000))]
        r1 = attribute_run(turns, run("L1", "paid-m", self.T[0], self.T[1], PAID))
        r2 = attribute_run(turns, run("L2", "free-m", self.T[2], self.T[3], FREE, source="mock"))
        total = fold_session(turns, [r1, r2])
        self.assertEqual(r1["cost_usd"], 3.0)
        self.assertEqual(r2["cost_usd"], 0.0)
        self.assertEqual(total["cost_usd"], 3.0)
        self.assertEqual(total["usage"], u(i=6_000_000, o=6_000_000))
        self.assertEqual((total["covered_turns"], total["uncovered_turns"]), (4, 0))

    def test_turns_no_ledger_line_covers_make_the_total_unknown(self):
        # e.g. a session begun under the old launcher, resumed under agent-on: the past price cannot be restored
        turns = [turn(self.T[0], "m", u(i=100)), turn(self.T[2], "m", u(i=100))]
        r2 = attribute_run(turns, run("L2", "m", self.T[2], self.T[3], FREE))
        total = fold_session(turns, [r2])
        self.assertEqual(total["cost_usd"], "unknown")
        self.assertEqual((total["covered_turns"], total["uncovered_turns"]), (1, 1))
        self.assertTrue(any("not covered" in r for r in total["unknown_reasons"]))

    def test_an_unknown_run_makes_the_total_unknown(self):
        turns = [turn(self.T[0], "m", u(cw=5))]
        total = fold_session(turns, [attribute_run(turns, run("L1", "m", self.T[0], None, PAID))])
        self.assertEqual(total["cost_usd"], "unknown")

    def test_overlapping_runs_are_unknown_not_double_counted(self):
        turns = [turn(self.T[0], "m", u(i=100))]
        r1 = attribute_run(turns, run("L1", "m", self.T[0], None, FREE))
        r2 = attribute_run(turns, run("L2", "m", self.T[0], None, FREE))
        total = fold_session(turns, [r1, r2])
        self.assertEqual(total["cost_usd"], "unknown")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_cost.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.cost'`

- [ ] **Step 3: Write the module**

`agent_on/cost.py`:

```python
"""§11 cost attribution, as pure functions. Cost is attributed per run at the price of that run; a price that is
absent is not 0; a turn no run covers cannot be priced. The launch (Plan B) feeds transcript turns and run
records in; the tests in tests/agent_on/test_cost.py are the contract."""
from __future__ import annotations

from .schemas.observed import USAGE_FIELDS
from .util import parse_utc

PRICE_FOR = {"input_tokens": "input", "output_tokens": "output",
             "cache_read_input_tokens": "cache_read", "cache_creation_input_tokens": "cache_write"}


def zero_usage() -> dict:
    return {k: 0 for k in USAGE_FIELDS}


def sum_usage(usages) -> dict:
    total = zero_usage()
    for usage in usages:
        for k in USAGE_FIELDS:
            total[k] += int(usage.get(k) or 0)
    return total


def price_usage(usage: dict, price: dict | None) -> tuple[float | None, list[str]]:
    """USD for one usage record at one price table (USD per Mtok for input, output, cache_read, cache_write).
    (None, reasons) when any non-zero field has no price."""
    if price is None:
        return None, ["no price table"]
    usd = 0.0
    reasons: list[str] = []
    for field, key in PRICE_FOR.items():
        n = int(usage.get(field) or 0)
        if n == 0:
            continue
        p = price.get(key)
        if p is None:
            reasons.append(f"{field}={n} but no {key} price")
            continue
        usd += n * float(p) / 1_000_000
    return (None, reasons) if reasons else (round(usd, 6), [])


def turns_in(turns, started: str, ended: str | None):
    s = parse_utc(started)
    e = parse_utc(ended) if ended else None
    for t in turns:
        ts = parse_utc(t["timestamp"])
        if ts >= s and (e is None or ts <= e):
            yield t


def attribute_run(turns: list[dict], run: dict) -> dict:
    """One launch's share of a transcript, as the ledger line `$STATE/sessions/<session-id>.jsonl` receives.
    Turns inside [started, ended] whose model is the run's wire_model are priced at `run["price"]` (the snapshot
    taken at spawn); a turn on another model is priced only if `run["priced_models"]` has it; anything else makes
    the run 'unknown' and is named in unknown_reasons."""
    mine = list(turns_in(turns, run["started"], run.get("ended")))
    usd = 0.0
    reasons: list[str] = []
    for t in mine:
        model = t["model"]
        price = run["price"] if model == run["wire_model"] else (run.get("priced_models") or {}).get(model)
        if price is None and model != run["wire_model"]:
            reasons.append(f"turn at {t['timestamp']} used {model!r}, which has no price on source {run['source']!r}")
            continue
        part, why = price_usage(t["usage"], price)
        if part is None:
            reasons.extend(why)
            continue
        usd += part
    return {"launch_id": run["launch_id"], "route": run["route"], "source": run["source"], "wire_model": run["wire_model"],
            "started": run["started"], "ended": run.get("ended"), "price": run["price"],
            "turns": len(mine), "usage": sum_usage(t["usage"] for t in mine),
            "cost_usd": "unknown" if reasons else round(usd, 6),
            "models_seen": sorted({t["model"] for t in mine}), "unknown_reasons": sorted(set(reasons))}


def fold_session(turns: list[dict], runs: list[dict]) -> dict:
    """session_total (§11): turns and usage from the whole transcript; cost_usd is the sum of the ledger lines only
    when every turn is covered by exactly one line and no line is unknown — else 'unknown' with the counts."""
    total = {"turns": len(turns), "usage": sum_usage(t["usage"] for t in turns)}
    covered = 0
    reasons: list[str] = []
    for t in turns:
        hits = [r for r in runs if any(True for _ in turns_in([t], r["started"], r.get("ended")))]
        if len(hits) == 1:
            covered += 1
        elif len(hits) > 1:
            reasons.append(f"turn at {t['timestamp']} is covered by {len(hits)} runs ({[r['launch_id'] for r in hits]})")
    uncovered = len(turns) - covered
    if uncovered:
        reasons.append(f"{uncovered} turn(s) not covered by any run ledger line — their price cannot be restored")
    for r in runs:
        if r.get("cost_usd") == "unknown":
            reasons.append(f"run {r['launch_id']} is unknown: " + "; ".join(r.get("unknown_reasons", [])))
    total["covered_turns"] = covered
    total["uncovered_turns"] = uncovered
    total["cost_usd"] = "unknown" if reasons else round(sum(float(r["cost_usd"]) for r in runs), 6)
    total["unknown_reasons"] = reasons
    return total
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/cost.py tests/agent_on/test_cost.py
git commit -m "feat(agent-on): per-run cost attribution with the unknown rule (§11, rev 6)

A paid session resumed on a free route folds to paid + 0; turns no ledger
line covers, and fields with no published price, fold to \"unknown\".

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 5: Storage rules — locks, atomic writes, the env file, the session ledger

**Files:**
- Create: `agent_on/state.py`
- Test: `tests/agent_on/test_state.py`

**Interfaces:**
- Consumes: `Paths`, `ensure_state`, `observed.empty_observed/validate_observed`
- Produces: `locked(lock_path)` (context manager), `atomic_write(path, text)`, `sweep_tmp(directory, stem) -> int`, `read_observed(paths) -> dict`, `update_observed(paths, mutate) -> dict`, `write_discovered(paths, text)`, `checkout_locked(paths)` (context manager), `read_env_file(paths) -> dict`, `resolve_secret(paths, name, env=None) -> str|None`, `append_session_run(paths, session_id, record) -> Path`, `read_session_runs(paths, session_id) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_state.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.paths import Paths  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.state import (  # noqa: E402
    append_session_run, atomic_write, checkout_locked, read_env_file, read_observed, read_session_runs,
    resolve_secret, sweep_tmp, update_observed, write_discovered,
)

ROUTES = 'version = 1\n[sources.mock]\nbase_url = "http://127.0.0.1:1"\n'

INCREMENT = """
import sys; sys.path.insert(0, {repo!r})
from pathlib import Path
from agent_on.paths import Paths
from agent_on.state import update_observed
p = Paths(checkout=Path({co!r}), state=Path({st!r}), home=Path({co!r}))
def bump(doc):
    doc["spend"].setdefault("counter", {{"n": 0}})["n"] += 1
for _ in range(50):
    update_observed(p, bump)
"""


class ObservedTest(unittest.TestCase):
    def test_missing_file_reads_as_the_empty_document(self):
        with Sandbox(ROUTES) as sb:
            self.assertEqual(read_observed(sb.paths)["routes"], {})

    def test_update_is_read_modify_write_and_validated(self):
        with Sandbox(ROUTES) as sb:
            update_observed(sb.paths, lambda d: d["spend"].__setitem__("x", {"n": 1}))
            update_observed(sb.paths, lambda d: d["spend"]["x"].__setitem__("n", d["spend"]["x"]["n"] + 1))
            self.assertEqual(read_observed(sb.paths)["spend"]["x"]["n"], 2)
            with self.assertRaises(SchemaError):
                update_observed(sb.paths, lambda d: d.__setitem__("routes", {"r": {"served": True}}))
            self.assertEqual(read_observed(sb.paths)["spend"]["x"]["n"], 2)   # the rejected write left the file alone
            self.assertEqual(list(sb.paths.state.glob("observed.json.tmp.*")), [])

    def test_two_processes_updating_concurrently_lose_nothing(self):
        with Sandbox(ROUTES) as sb:
            script = INCREMENT.format(repo=str(REPO), co=str(sb.paths.checkout), st=str(sb.paths.state))
            procs = [subprocess.Popen([sys.executable, "-c", script]) for _ in range(2)]
            self.assertEqual([p.wait() for p in procs], [0, 0])
            self.assertEqual(read_observed(sb.paths)["spend"]["counter"]["n"], 100)

    def test_stale_tmp_files_are_swept_and_ignored(self):
        with Sandbox(ROUTES) as sb:
            update_observed(sb.paths, lambda d: None)
            stale = sb.paths.state / "observed.json.tmp.99999"
            stale.write_text("{garbage", encoding="utf-8")
            self.assertEqual(read_observed(sb.paths)["version"], 1)
            update_observed(sb.paths, lambda d: None)
            self.assertFalse(stale.exists())
            self.assertEqual(sweep_tmp(sb.paths.state, "observed.json"), 0)

    def test_write_discovered_is_atomic_under_the_same_lock(self):
        with Sandbox(ROUTES) as sb:
            write_discovered(sb.paths, "version = 1\n")
            self.assertEqual(sb.paths.discovered_toml.read_text(), "version = 1\n")
            self.assertEqual(list(sb.paths.state.glob("routes.discovered.toml.tmp.*")), [])


class CheckoutLockTest(unittest.TestCase):
    def test_lock_file_lives_in_the_checkout_and_is_shared_across_state_roots(self):
        with Sandbox(ROUTES) as sb:
            other = Paths(checkout=sb.paths.checkout, state=sb.root / "other-state", home=sb.paths.home)
            with checkout_locked(sb.paths):
                self.assertTrue(sb.paths.routes_lock.exists())
                probe = subprocess.run([sys.executable, "-c", f"""
import fcntl, os, sys
fd = os.open({str(other.routes_lock)!r}, os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print("acquired")
except BlockingIOError:
    print("blocked")
"""], capture_output=True, text=True)
            self.assertEqual(probe.stdout.strip(), "blocked", "a run with another AGENT_ON_STATE must contend for the same lock")

    def test_atomic_write_replaces_in_place(self):
        with Sandbox(ROUTES) as sb:
            atomic_write(sb.paths.routes_toml, "version = 1\n")
            self.assertEqual(sb.paths.routes_toml.read_text(), "version = 1\n")
            self.assertEqual(list(sb.paths.checkout.glob("routes.toml.tmp.*")), [])


class SecretsTest(unittest.TestCase):
    def test_env_wins_over_the_env_file_and_the_file_must_be_private(self):
        with Sandbox(ROUTES) as sb:
            self.assertIsNone(resolve_secret(sb.paths, "K", env={}))
            sb.paths.state.mkdir()
            sb.paths.env_file.write_text("# comment\nK=from-file\nOTHER = spaced \n", encoding="utf-8")
            os.chmod(sb.paths.env_file, 0o600)
            self.assertEqual(read_env_file(sb.paths), {"K": "from-file", "OTHER": "spaced"})
            self.assertEqual(resolve_secret(sb.paths, "K", env={}), "from-file")
            self.assertEqual(resolve_secret(sb.paths, "K", env={"K": "from-env"}), "from-env")
            os.chmod(sb.paths.env_file, 0o644)
            with self.assertRaises(PermissionError):
                read_env_file(sb.paths)


class SessionLedgerTest(unittest.TestCase):
    def test_append_and_read_back_one_line_per_run(self):
        with Sandbox(ROUTES) as sb:
            p = append_session_run(sb.paths, "sess-1", {"launch_id": "L1", "cost_usd": 1.5})
            append_session_run(sb.paths, "sess-1", {"launch_id": "L2", "cost_usd": "unknown"})
            self.assertEqual(p, sb.paths.sessions_dir / "sess-1.jsonl")
            self.assertEqual([r["launch_id"] for r in read_session_runs(sb.paths, "sess-1")], ["L1", "L2"])
            self.assertEqual(read_session_runs(sb.paths, "nope"), [])
            self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
            self.assertEqual(len(p.read_text().splitlines()), 2)
            json.loads(p.read_text().splitlines()[1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_state.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.state'`

- [ ] **Step 3: Write the module**

`agent_on/state.py`:

```python
"""§7.1 storage rules. One advisory lock per state file; every writer re-reads under the lock; temp+fsync+rename;
one-line O_APPEND for ledgers. The routes.toml lock is keyed by the checkout (rev 6), never by the state root."""
from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .paths import Paths, ensure_state
from .schemas.observed import empty_observed, validate_observed


@contextmanager
def locked(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def sweep_tmp(directory: Path, stem: str) -> int:
    """Delete `<stem>.tmp.*` left by a crashed writer. Returns how many."""
    n = 0
    for p in directory.glob(f"{stem}.tmp.*"):
        try:
            p.unlink()
            n += 1
        except FileNotFoundError:
            pass
    return n


def atomic_write(path: Path, text: str) -> None:
    """Write `<path>.tmp.<pid>`, fsync, rename over `path`. The caller holds the lock that serialises writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_observed(paths: Paths) -> dict:
    if not paths.observed_json.exists():
        return empty_observed()
    doc = json.loads(paths.observed_json.read_text(encoding="utf-8"))
    validate_observed(doc)
    return doc


def update_observed(paths: Paths, mutate: Callable[[dict], None]) -> dict:
    """Read-modify-write under the observed lock. `mutate` edits the freshly re-read document in place; the result
    is validated before it is written, so a bad mutation leaves the file untouched."""
    ensure_state(paths)
    with locked(paths.observed_lock):
        sweep_tmp(paths.state, paths.observed_json.name)
        doc = read_observed(paths)
        mutate(doc)
        validate_observed(doc)
        atomic_write(paths.observed_json, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        return doc


def write_discovered(paths: Paths, text: str) -> None:
    """routes.discovered.toml is state and `sync` also writes observed.json: same lock (§7.1)."""
    ensure_state(paths)
    with locked(paths.observed_lock):
        sweep_tmp(paths.state, paths.discovered_toml.name)
        atomic_write(paths.discovered_toml, text)


@contextmanager
def checkout_locked(paths: Paths):
    """The routes.toml writer lock, `<checkout>/.routes.lock` — keyed by the resource it protects, so a default run
    and a AGENT_ON_STATE scratch run editing the same checkout contend for the same lock (§7.1, rev 6)."""
    with locked(paths.routes_lock):
        yield


def read_env_file(paths: Paths) -> dict[str, str]:
    """`KEY=value` lines in $STATE/env. Refused unless mode is 0600 — a secret readable by group/other is a defect."""
    p = paths.env_file
    if not p.exists():
        return {}
    mode = stat.S_IMODE(p.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"{p} is mode {oct(mode)}; it must be 0600 (chmod 600 {p})")
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def resolve_secret(paths: Paths, name: str, env: dict | None = None) -> str | None:
    """The environment wins over $STATE/env (§9), decided once in the parent (D2)."""
    env = os.environ if env is None else env
    if env.get(name):
        return env[name]
    return read_env_file(paths).get(name) or None


def append_session_run(paths: Paths, session_id: str, record: dict) -> Path:
    """One complete line, O_APPEND (§7.1). The per-session run ledger of §11."""
    ensure_state(paths)
    p = paths.sessions_dir / f"{session_id}.jsonl"
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return p


def read_session_runs(paths: Paths, session_id: str) -> list[dict]:
    p = paths.sessions_dir / f"{session_id}.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass. The two-process counter test proves the observed lock; the `blocked` probe proves the checkout lock is shared across state roots.

- [ ] **Step 5: Commit**

```bash
git add agent_on/state.py tests/agent_on/test_state.py
git commit -m "feat(agent-on): storage rules — locks, atomic writes, env file, session ledger (§7.1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---
### Task 6: L0 reads — source probing, catalog normalisation, oMLX settings, OpenRouter spend, and the mock source

**Files:**
- Create: `agent_on/sources.py`, `agent_on/mock_source.py`
- Test: `tests/agent_on/test_sources.py`

**Interfaces:**
- Consumes: `routes.Source`, `util.utc_now`
- Produces: `Probe(reachable, checked, error, catalog, catalog_count, identity)`, `is_loopback(url)`, `http_get_json(url, timeout, headers=None)`, `normalize_catalog(payload) -> dict[id, {max_input, max_output, owned_by, pricing, supported_parameters}]`, `probe_source(source, timeout=5.0, headers=None) -> Probe`, `probe_all(sources, timeout=5.0) -> dict[str, Probe]`, `omlx_settings_path(source, home) -> Path|None`, `read_configured_limits(path, home) -> dict|None`, `fetch_openrouter_spend(base_url, key, timeout=5.0) -> dict`; `MockSource(catalog=None, spend=None, expect_key=None)` with `.start()/.stop()`, context manager, `.port`, `.base_url`, `.requests`; `omlx_entry(id, max_model_len=262144)`, `openrouter_entry(id, context_length=…, max_out=…, prompt=…, completion=…, cache_read=…, params=None)`.

Measured shapes these encode (2026-09-07): oMLX `GET /v1/models` → `{"object": "list", "data": [{"id", "object", "created", "owned_by": "omlx", "max_model_len"}]}`; OpenRouter `GET /api/v1/models` → `data[].{id, context_length, top_provider{context_length, max_completion_tokens}, pricing{prompt, completion, input_cache_read, [input_cache_write]}, supported_parameters[]}` (prices are USD per token as strings); OpenRouter `GET /api/v1/auth/key` → `data.{usage, limit, limit_reset, limit_remaining, usage_daily, …}`; `~/.omlx/settings.json` → `sampling.max_context_window`, `sampling.max_tokens`.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_sources.py`:

```python
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.schemas.routes import Source  # noqa: E402
from agent_on.sources import (  # noqa: E402
    fetch_openrouter_spend, is_loopback, normalize_catalog, omlx_settings_path, probe_all, probe_source, read_configured_limits,
)


def src(name, base, catalog="/v1/models", auth_env=None, discover=False):
    return Source(name, base, auth_env, catalog, discover, None)


class NormalizeTest(unittest.TestCase):
    def test_both_catalog_shapes_normalise_to_one(self):
        cat = normalize_catalog({"object": "list", "data": [omlx_entry("local-a", 262144), openrouter_entry("v/m", 1048576, 131072)]})
        self.assertEqual(cat["local-a"], {"max_input": 262144, "max_output": None, "owned_by": "omlx", "pricing": None, "supported_parameters": None})
        self.assertEqual(cat["v/m"]["max_input"], 1048576)
        self.assertEqual(cat["v/m"]["max_output"], 131072)
        self.assertEqual(cat["v/m"]["pricing"]["prompt"], "0.000000966")
        self.assertIn("reasoning_effort", cat["v/m"]["supported_parameters"])

    def test_garbage_is_ignored_not_fatal(self):
        self.assertEqual(normalize_catalog({"data": [{"no": "id"}, "x", {"id": 3}]}), {})
        self.assertEqual(normalize_catalog([]), {})


class ProbeTest(unittest.TestCase):
    def test_reachable_source_yields_catalog_and_identity(self):
        with MockSource(catalog=[omlx_entry("a"), omlx_entry("b")]) as m:
            p = probe_source(src("mock", m.base_url), timeout=3)
            self.assertTrue(p.reachable)
            self.assertEqual(sorted(p.catalog), ["a", "b"])
            self.assertEqual(p.catalog_count, 2)
            self.assertEqual(p.identity, "owned_by=omlx")
            self.assertIsNone(p.error)
            self.assertTrue(p.checked.endswith("Z"))

    def test_unreachable_source_is_recorded_not_raised(self):
        p = probe_source(src("dead", "http://127.0.0.1:9"), timeout=1)   # port 9: discard, closed on macOS/Linux
        self.assertFalse(p.reachable)
        self.assertIn(":9", p.error)
        self.assertEqual(p.catalog, {})

    def test_http_error_and_missing_catalog_are_named(self):
        with MockSource() as m:
            p = probe_source(src("mock", m.base_url, catalog="/nope"), timeout=3)
            self.assertFalse(p.reachable)
            self.assertIn("HTTP 404", p.error)
        p = probe_source(Source("x", "http://127.0.0.1:1", None, None, False, None), timeout=1)
        self.assertEqual(p.error, "source declares no catalog")

    def test_probe_all_runs_every_source_and_times_out_the_stuck_one(self):
        with MockSource(catalog=[omlx_entry("a")]) as m:
            res = probe_all({"ok": src("ok", m.base_url), "dead": src("dead", "http://127.0.0.1:9")}, timeout=1)
            self.assertTrue(res["ok"].reachable)
            self.assertFalse(res["dead"].reachable)
            # a black-holed address (RFC 5737 TEST-NET) must come back within the bound, whether the network
            # answers with ICMP or with silence — never hang sync
            import time
            t0 = time.monotonic()
            res = probe_all({"hole": src("hole", "http://192.0.2.1:8000")}, timeout=1)
            self.assertFalse(res["hole"].reachable)
            self.assertIsNotNone(res["hole"].error)
            self.assertLess(time.monotonic() - t0, 5.0)

    def test_loopback_detection_and_settings_path(self):
        self.assertTrue(is_loopback("http://127.0.0.1:8000"))
        self.assertTrue(is_loopback("http://localhost:8000"))
        self.assertFalse(is_loopback("http://mortys-mac-studio:8000"))
        home = Path("/h")
        self.assertEqual(omlx_settings_path(src("omlx", "http://127.0.0.1:8000"), home), home / ".omlx" / "settings.json")
        self.assertIsNone(omlx_settings_path(src("omlx@morty", "http://mortys-mac-studio:8000"), home))


class ConfiguredLimitsTest(unittest.TestCase):
    def test_reads_sampling_caps_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            p = home / ".omlx" / "settings.json"
            p.parent.mkdir()
            p.write_text(json.dumps({"sampling": {"max_context_window": 131072, "max_tokens": 32768}}), encoding="utf-8")
            got = read_configured_limits(p, home)
            self.assertEqual((got["input"], got["output"]), (131072, 32768))
            self.assertEqual(got["source"], "~/.omlx/settings.json")
            self.assertTrue(got["read_at"].endswith("Z"))
            p.write_text("{broken", encoding="utf-8")
            self.assertIsNone(read_configured_limits(p, home))
            self.assertIsNone(read_configured_limits(home / "missing.json", home))


class SpendTest(unittest.TestCase):
    def test_key_endpoint_maps_to_the_five_spend_fields(self):
        data = {"usage": 77.848, "limit": 100, "limit_reset": "daily", "limit_remaining": 99.96, "usage_daily": 0.04, "label": "<key label, never recorded>"}
        with MockSource(spend=data, expect_key="k-1") as m:
            s = fetch_openrouter_spend(m.base_url, "k-1", timeout=3)
            self.assertEqual((s["usd_used"], s["usd_limit"], s["limit_reset"], s["usd_remaining"], s["usd_used_daily"]), (77.848, 100, "daily", 99.96, 0.04))
            self.assertIsNone(s["error"])
            self.assertNotIn("label", s)                     # the (masked) key label is never recorded
            bad = fetch_openrouter_spend(m.base_url, "wrong", timeout=3)
            self.assertIsNone(bad["usd_used"])
            self.assertIn("401", bad["error"])
            self.assertTrue(any(path.endswith("/v1/auth/key") for path, _ in m.requests))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_sources.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.mock_source'`

- [ ] **Step 3: Write the modules**

`agent_on/mock_source.py`:

```python
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
```

`agent_on/sources.py`:

```python
"""L0 reads (§5): catalog GETs, the local oMLX settings file, OpenRouter's key endpoint. Nothing here writes."""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .schemas.routes import Source
from .util import utc_now

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass
class Probe:
    reachable: bool
    checked: str
    error: str | None = None
    catalog: dict[str, dict] = field(default_factory=dict)
    catalog_count: int = 0
    identity: str | None = None


def is_loopback(url: str) -> bool:
    return (urlsplit(url).hostname or "") in LOOPBACK_HOSTS


def http_get_json(url: str, timeout: float, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_catalog(payload) -> dict[str, dict]:
    """One shape for both catalogs seen so far: oMLX (`max_model_len`, `owned_by`) and OpenRouter
    (`context_length`, `top_provider`, `pricing`, `supported_parameters`). Entries without a string id are skipped."""
    items = payload.get("data", []) if isinstance(payload, dict) else []
    out: dict[str, dict] = {}
    for m in items:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            continue
        top = m.get("top_provider") or {}
        max_in = m.get("max_model_len")
        if max_in is None:
            max_in = top.get("context_length") or m.get("context_length")
        out[m["id"]] = {"max_input": max_in, "max_output": top.get("max_completion_tokens"), "owned_by": m.get("owned_by"),
                        "pricing": m.get("pricing"), "supported_parameters": m.get("supported_parameters")}
    return out


def probe_source(source: Source, timeout: float = 5.0, headers: dict | None = None) -> Probe:
    url = source.catalog_url()
    checked = utc_now()
    if url is None:
        return Probe(False, checked, error="source declares no catalog")
    try:
        payload = http_get_json(url, timeout, headers)
    except urllib.error.HTTPError as e:
        e.close()
        return Probe(False, checked, error=f"HTTP {e.code} from {url}")
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return Probe(False, checked, error=f"{type(reason).__name__}: {reason} ({source.host()}:{source.port()})")
    catalog = normalize_catalog(payload)
    owners = sorted({v["owned_by"] for v in catalog.values() if v.get("owned_by")})
    return Probe(True, checked, catalog=catalog, catalog_count=len(catalog),
                 identity=f"owned_by={','.join(owners)}" if owners else None)


def probe_all(sources: dict[str, Source], timeout: float = 5.0) -> dict[str, Probe]:
    """Every source concurrently on daemon threads, so a stalled resolver or a black-holed host cannot pin `sync`:
    a probe that has not returned by timeout + 2 s is recorded unreachable ('timeout') and its thread dies with the
    process instead of blocking exit."""
    results: dict[str, Probe] = {}

    def run(name: str, src: Source) -> None:
        results[name] = probe_source(src, timeout)

    threads = [threading.Thread(target=run, args=(n, s), daemon=True, name=f"probe-{n}") for n, s in sources.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 2)
    for n in sources:
        results.setdefault(n, Probe(False, utc_now(), error=f"timeout: no answer within {timeout + 2:.0f}s"))
    return results


def omlx_settings_path(source: Source, home: Path) -> Path | None:
    """Only a loopback oMLX's settings file is ours to read; a tailnet host's file is its own (§7 `configured`)."""
    return home / ".omlx" / "settings.json" if is_loopback(source.base_url) else None


def read_configured_limits(path: Path, home: Path) -> dict | None:
    """What the settings file *says* (`sampling.max_context_window` / `sampling.max_tokens`) — not what the server applied."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    s = doc.get("sampling") or {}
    shown = str(path)
    if shown.startswith(str(home)):
        shown = "~" + shown[len(str(home)):]
    return {"input": s.get("max_context_window"), "output": s.get("max_tokens"), "source": shown, "read_at": utc_now()}


def fetch_openrouter_spend(base_url: str, key: str, timeout: float = 5.0) -> dict:
    """OpenRouter `GET <base>/v1/auth/key` (measured 2026-09-07): data.usage is lifetime USD, data.limit +
    limit_reset the cap and its period, limit_remaining and usage_daily what is left and spent today.
    Errors are recorded, not raised — spend is informational (D6). The key label is never recorded."""
    checked = utc_now()
    url = base_url.rstrip("/") + "/v1/auth/key"
    empty = {"usd_used": None, "usd_limit": None, "limit_reset": None, "usd_remaining": None, "usd_used_daily": None,
             "source": f"openrouter GET {url}", "checked": checked, "error": None}
    try:
        d = http_get_json(url, timeout, {"Authorization": f"Bearer {key}"}).get("data", {})
    except urllib.error.HTTPError as e:
        e.close()
        return {**empty, "error": f"HTTP {e.code}"}
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as e:
        return {**empty, "error": f"{type(e).__name__}: {getattr(e, 'reason', e)}"}
    return {**empty, "usd_used": d.get("usage"), "usd_limit": d.get("limit"), "limit_reset": d.get("limit_reset"),
            "usd_remaining": d.get("limit_remaining"), "usd_used_daily": d.get("usage_daily")}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass. The black-hole probe takes ~3 s (timeout 1 + 2); that is the designed bound.

- [ ] **Step 5: Commit**

```bash
git add agent_on/sources.py agent_on/mock_source.py tests/agent_on/test_sources.py
git commit -m "feat(agent-on): source probing, catalog normalisation, oMLX settings, OpenRouter spend, mock source

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 7: L3 — the knowledge record schema and the invariant registry (fourteen predicates)

**Files:**
- Create: `agent_on/schemas/knowledge.py`, `agent_on/invariants.py`
- Test: `tests/agent_on/test_invariants.py`

**Interfaces:**
- Consumes: `Paths`, `describe_copy`, `RULES`, `SchemaError`, `forbid_claude_cost`, `RouteTable`, `load_routes`, `read_observed`
- Produces: `knowledge.KINDS`, `knowledge.validate_record(kind, rec)`, `knowledge.validate_file(path) -> list[str]`; `invariants.Result(id, result, reason, subject, fix)` with `.as_dict()`, `Context(paths, routes, routes_error, observed, tree, home, claude_code)`, `REGISTRY`, `invariant(id, *, statement, fix, per_route=False)`, `build_context(paths, *, with_claude_code=False)`, `evaluate(ctx, ids=None, route=None) -> list[Result]`, `skipped_ids(results) -> list[str]`, `claude_code_version() -> str|None`, `ENV_DENY`, `TIER_NAMES`.

The fourteen ids and what each catches are §8's table. In Plan A `credential.not_in_child_env` is an honest `skip` (the launcher is Plan B). `test.names.derived` lints Python under `agent_on/` and `tests/agent_on/` here; docs join the lint in Plan D, when they are generated from `routes.toml` (§8 says "test or doc"). The reproduction for every other F is a test below.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_invariants.py`:

```python
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.invariants import REGISTRY, build_context, evaluate, skipped_ids  # noqa: E402
from agent_on.schemas.knowledge import validate_file, validate_record  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import empty_route, empty_source  # noqa: E402
from agent_on.state import update_observed  # noqa: E402

EXPECTED_IDS = {"route.served", "route.unique", "source.limits.propagated", "limits.declared_vs_observed", "copy.single",
                "credential.not_in_child_env", "harness.env.clean", "gate.no_silent_skip", "gate.mock.ephemeral",
                "test.names.derived", "knowledge.typed", "schema.complete", "cost.not_copied", "qualification.current"}
BASE = "http://127.0.0.1:1"
TS = "2026-09-07T00:00:00Z"


def one(paths, inv_id, route=None):
    res = [r for r in evaluate(build_context(paths), ids=[inv_id], route=route)]
    return res if route is None and REGISTRY[inv_id].per_route else res[0]


class RegistryTest(unittest.TestCase):
    def test_the_fourteen_predicates_are_registered_with_statement_and_fix(self):
        self.assertEqual(set(REGISTRY), EXPECTED_IDS)
        for inv in REGISTRY.values():
            self.assertTrue(inv.statement and inv.fix, inv.id)

    def test_a_skip_is_reported_as_skip_and_listed(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            res = evaluate(build_context(sb.paths))
            self.assertTrue(all(r.result in ("pass", "fail", "skip") for r in res))
            served = [r for r in res if r.id == "route.served"]
            self.assertTrue(served and all(r.result == "skip" for r in served))     # never synced → skip, not pass
            self.assertIn("route.served:mock/alpha", skipped_ids(res))
            self.assertEqual([r.result for r in res if r.id == "credential.not_in_child_env"], ["skip"])

    def test_broken_routes_toml_fails_every_route_predicate_by_name(self):
        with Sandbox('version = 1\n[sources.mock]\nbase_url = "http://x"\n[routes."mock/m"]\naliases=["z"]\n[routes."mock/n"]\naliases=["z"]\n') as sb:
            res = {r.id: r for r in evaluate(build_context(sb.paths), ids=["route.unique", "route.served"])}
            self.assertEqual(res["route.unique"].result, "fail")            # F4
            self.assertIn("routes.unique", res["route.unique"].reason)
            self.assertEqual(res["route.served"].result, "fail")


class F1ServedTest(unittest.TestCase):
    def test_planted_dead_wire_model_fails_and_live_passes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            def plant(doc):   # exactly what `sync` (Task 8) writes: the source's catalog and each route's served flag
                doc["sources"]["mock"] = {**empty_source(), "reachable": True, "checked": TS, "catalog": ["alpha"], "catalog_count": 1}
                doc["routes"]["mock/alpha"] = {**empty_route(), "served": True, "checked": TS}
                doc["routes"]["mock/gone"] = {**empty_route(), "served": False, "checked": TS}
            update_observed(sb.paths, plant)
            res = {r.subject: r for r in one(sb.paths, "route.served")}
            self.assertEqual(res["mock/alpha"].result, "pass")
            self.assertEqual(res["mock/gone"].result, "fail")
            self.assertIn("not in mock catalog", res["mock/gone"].reason)
            self.assertIn("sync", res["mock/gone"].fix)
            self.assertEqual(res["paid/vendor/model-x"].result, "skip")          # its source was never probed


class F2F12LimitsTest(unittest.TestCase):
    def test_globs_are_rejected_at_load_and_a_limitless_source_fails_its_discovered_routes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE).replace('[routes."mock/gone"]', '[routes."mock/Qwen*"]')) as sb:
            r = one(sb.paths, "source.limits.propagated")
            self.assertEqual(r[0].result, "fail")
            self.assertIn("no_globs", r[0].reason)
        text = 'version = 1\n[sources.mock]\nbase_url = "http://x"\ndiscover = true\n'
        with Sandbox(text) as sb:
            sb.paths.state.mkdir()
            sb.paths.discovered_toml.write_text('version = 1\n[routes."mock/found"]\n', encoding="utf-8")
            r = {x.subject: x for x in one(sb.paths, "source.limits.propagated")}
            self.assertEqual(r["mock/found"].result, "fail")
            self.assertIn("declares none", r["mock/found"].reason)
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            r = {x.subject: x for x in one(sb.paths, "source.limits.propagated")}
            self.assertEqual(r["mock/alpha"].result, "pass")                     # inherited
            self.assertIn("inherit", r["mock/alpha"].reason)
            self.assertEqual(r["paid/vendor/model-x"].result, "pass")            # its own

    def test_declared_above_observed_fails_and_verified_is_the_stronger_bound(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            def plant(doc):   # declared 8192 (inherited from the source) against an advertised 4096
                doc["routes"]["mock/alpha"] = empty_route()
                doc["routes"]["mock/alpha"]["limits"]["input"].update({"advertised": 4096, "checked": TS})
            update_observed(sb.paths, plant)
            r = {x.subject: x for x in one(sb.paths, "limits.declared_vs_observed")}
            self.assertEqual(r["mock/alpha"].result, "fail")
            self.assertIn("8192 > advertised 4096", r["mock/alpha"].reason)
            self.assertEqual(r["paid/vendor/model-x"].result, "skip")            # nothing observed for it → skip
            update_observed(sb.paths, lambda doc: doc["routes"]["mock/alpha"]["limits"]["input"].__setitem__("verified", 16384))
            r = {x.subject: x for x in one(sb.paths, "limits.declared_vs_observed")}
            self.assertEqual(r["mock/alpha"].result, "pass")
            self.assertIn("verified", r["mock/alpha"].reason)


class F7F8CopyTest(unittest.TestCase):
    def test_shim_elsewhere_fails_and_shim_here_passes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            self.assertEqual(one(sb.paths, "copy.single").result, "skip")            # no shim yet
            shim = sb.paths.shim
            shim.parent.mkdir(parents=True)
            shim.symlink_to(sb.root / "elsewhere" / "agent-on")
            r = one(sb.paths, "copy.single")
            self.assertEqual(r.result, "fail")
            self.assertIn("elsewhere", r.reason)
            shim.unlink()
            (sb.paths.checkout / "bin").mkdir()
            (sb.paths.checkout / "bin" / "agent-on").write_text("#!/bin/sh\n")
            shim.symlink_to(sb.paths.checkout / "bin" / "agent-on")
            self.assertEqual(one(sb.paths, "copy.single").result, "pass")


class HarnessEnvTest(unittest.TestCase):
    def write(self, sb, settings):
        p = sb.paths.home / ".claude" / "settings.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(settings), encoding="utf-8")

    def test_denylist_tier_name_and_literal_model(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "skip")
            self.write(sb, {"model": "fable", "env": {"EDITOR": "vim"}})
            r = one(sb.paths, "harness.env.clean")
            self.assertEqual(r.result, "pass")
            self.assertIn("tier name", r.reason)                                   # rev 6: this machine sets model: fable
            self.write(sb, {"model": "claude-opus-5"})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"env": {"ANTHROPIC_BASE_URL": "http://x"}})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"env": {"HTTPS_PROXY": "http://x"}})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"apiKeyHelper": "cat x"})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")


class GateRecordTest(unittest.TestCase):
    def gate_run(self, **over):
        base = {"at": "2026-09-07T00:00:00Z", "commit": "x", "result": "pass", "tests": 1, "verifiers": {"declared": [], "ran": []},
                "invariants": {"route.served:mock/alpha": "skip"}, "skipped": ["route.served:mock/alpha"], "skipped_reasons": [], "mock_port": 51873}
        return {**base, **over}

    def test_silent_skip_and_unrun_verifier_fail(self):  # F6
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "gate.no_silent_skip").result, "skip")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run()))
            self.assertEqual(one(sb.paths, "gate.no_silent_skip").result, "pass")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(skipped=[])))
            self.assertEqual(one(sb.paths, "gate.no_silent_skip").result, "fail")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(verifiers={"declared": ["fidelity"], "ran": []})))
            r = one(sb.paths, "gate.no_silent_skip")
            self.assertEqual(r.result, "fail")
            self.assertIn("fidelity", r.reason)

    def test_mock_on_a_configured_port_fails(self):  # F9
        with Sandbox(MOCK_ROUTES.format(base="http://127.0.0.1:8000")) as sb:
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(mock_port=8000)))
            self.assertEqual(one(sb.paths, "gate.mock.ephemeral").result, "fail")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(mock_port=51873)))
            self.assertEqual(one(sb.paths, "gate.mock.ephemeral").result, "pass")


class TreeLintTest(unittest.TestCase):
    def test_undeclared_route_literal_in_the_tree_fails(self):  # F5
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            (sb.paths.checkout / "agent_on").mkdir()
            (sb.paths.checkout / "agent_on" / "x.py").write_text('NAME = "mock/alpha"\n', encoding="utf-8")
            self.assertEqual(one(sb.paths, "test.names.derived").result, "pass")
            (sb.paths.checkout / "agent_on" / "x.py").write_text('NAME = "mock/does-not-exist"\n', encoding="utf-8")
            r = one(sb.paths, "test.names.derived")
            self.assertEqual(r.result, "fail")
            self.assertIn("does-not-exist", r.reason)

    def test_the_real_tree_has_no_undeclared_route_literals(self):
        from agent_on.paths import default_paths
        self.assertEqual(one(default_paths(), "test.names.derived").result, "pass")

    def test_schema_rules_registry_is_complete_and_alive(self):  # F14
        from agent_on.paths import default_paths
        r = one(default_paths(), "schema.complete")
        self.assertEqual(r.result, "pass", r.reason)
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            (sb.paths.checkout / "agent_on").mkdir()
            (sb.paths.checkout / "agent_on" / "y.py").write_text('raise SchemaError("not.a.rule", "x")\n', encoding="utf-8")
            r = one(sb.paths, "schema.complete")
            self.assertEqual(r.result, "fail")
            self.assertIn("not.a.rule", r.reason)


class KnowledgeTest(unittest.TestCase):
    def test_records_are_typed(self):  # F13
        validate_record("traps", {"id": "traps-01J", "ts": "2026-09-07T00:00:00Z", "trap": "t", "mechanism": "m", "avoid": "a",
                                  "evidence": "e", "found_by": "f", "applies_to": ["sync"]})
        with self.assertRaises(SchemaError):
            validate_record("traps", {"id": "traps-01J", "ts": "x", "trap": "t"})
        with self.assertRaises(SchemaError):
            validate_record("observations", {"id": "observations-1", "ts": "x", "route": "r", "kind": "vibes", "values": {}, "evidence": "e"})
        with self.assertRaises(SchemaError):
            validate_record("decisions", {"id": "wrong-1", "ts": "x", "decision": "d", "rationale": "r", "by": "b"})
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            self.assertEqual(one(sb.paths, "knowledge.typed").result, "skip")
            k = sb.paths.checkout / "knowledge"
            k.mkdir()
            (k / "decisions.jsonl").write_text('{"id": "decisions-1", "ts": "2026-09-07T00:00:00Z", "decision": "d", "rationale": "r", "by": "b"}\nnot json\n', encoding="utf-8")
            r = one(sb.paths, "knowledge.typed")
            self.assertEqual(r.result, "fail")
            self.assertIn("decisions.jsonl:2", r.reason)
            self.assertEqual(len(validate_file(k / "decisions.jsonl")), 1)


class CostAndQualificationTest(unittest.TestCase):
    def test_claude_cost_figure_in_observed_fails(self):  # F11
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "cost.not_copied").result, "pass")
            sb.paths.state.mkdir(parents=True, exist_ok=True)
            bad = {"version": 1, "copy": None, "sources": {}, "routes": {}, "last_check": None, "last_gate_run": None, "spend": {"x": {"total_cost_usd": 0.24}}}
            sb.paths.observed_json.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(SchemaError):
                update_observed(sb.paths, lambda d: None)                          # the schema refuses it at the door

    def test_qualification_goes_stale_when_the_effective_config_changes(self):  # F10
        text = MOCK_ROUTES.format(base=BASE)
        with Sandbox(text) as sb:
            r = {x.subject: x for x in one(sb.paths, "qualification.current")}
            self.assertEqual(r["mock/alpha"].result, "skip")
            ctx = build_context(sb.paths)
            sha = ctx.routes.effective_sha(ctx.routes.routes["mock/alpha"])
            def plant(doc):
                doc["routes"]["mock/alpha"] = empty_route()
                doc["routes"]["mock/alpha"]["last_qualification"] = {"pass": True, "at": "2026-09-07T00:00:00Z",
                    "fingerprint": {"effective_route_sha": sha, "wire_model": "alpha", "source_identity": None, "claude_code": None}}
            update_observed(sb.paths, plant)
            self.assertEqual({x.subject: x.result for x in one(sb.paths, "qualification.current")}["mock/alpha"], "pass")
            sb.paths.routes_toml.write_text(text.replace("input = 8192", "input = 4096"), encoding="utf-8")   # inherited limit changed
            r = {x.subject: x for x in one(sb.paths, "qualification.current")}
            self.assertEqual(r["mock/alpha"].result, "fail")
            self.assertIn("effective_route_sha", r["mock/alpha"].reason)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_invariants.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.invariants'`

- [ ] **Step 3: Write the modules**

`agent_on/schemas/knowledge.py`:

```python
"""L5 record kinds (§10) — enough for `knowledge.typed`; `learn` (Plan C) validates with the same function."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import SchemaError

KINDS: dict[str, tuple[str, ...]] = {
    "observations": ("route", "kind", "values", "evidence"),
    "decisions": ("decision", "rationale", "by"),
    "traps": ("trap", "mechanism", "avoid", "evidence", "found_by", "applies_to"),
    "qualifications": ("route", "fingerprint", "gates", "thinking_block_seen", "completed", "commit"),
    "gate-runs": ("commit", "result", "tests", "verifiers", "invariants", "skipped_reasons", "mock_port"),
    "tasks": ("task_id", "event"),
}
OBSERVATION_KINDS = ("tokens", "throughput", "quality", "liveness", "cost")


def validate_record(kind: str, rec) -> None:
    if kind not in KINDS:
        raise SchemaError("knowledge.record", f"unknown kind {kind!r}; kinds: {sorted(KINDS)}")
    if not isinstance(rec, dict):
        raise SchemaError("knowledge.record", f"{kind}: a record must be an object")
    missing = [k for k in ("id", "ts") + KINDS[kind] if k not in rec]
    if missing:
        raise SchemaError("knowledge.record", f"{kind}: missing {missing}")
    if not str(rec["id"]).startswith(f"{kind}-"):
        raise SchemaError("knowledge.record", f"{kind}: id must start with '{kind}-', got {rec['id']!r}")
    if kind == "observations" and rec["kind"] not in OBSERVATION_KINDS:
        raise SchemaError("knowledge.record", f"observation kind must be one of {OBSERVATION_KINDS}, got {rec['kind']!r}")


def validate_file(path: Path) -> list[str]:
    """Every non-blank line of knowledge/<kind>.jsonl; returns `<file>:<line>: <error>` strings."""
    kind = path.stem
    errors: list[str] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            validate_record(kind, json.loads(line))
        except (ValueError, SchemaError) as e:
            errors.append(f"{path.name}:{n}: {e}")
    return errors
```

`agent_on/invariants.py`:

```python
"""L3 — named predicates over (routes, observed, tree, home) (§8). Each has a stable id, a statement, a fix hint,
and returns pass | fail | skip with a reason. A skip is never printed as a pass."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .paths import Paths, describe_copy
from .schemas.errors import RULES, SchemaError
from .schemas.knowledge import validate_file
from .schemas.observed import forbid_claude_cost
from .schemas.routes import RouteTable, load_routes
from .state import read_observed


@dataclass
class Result:
    id: str
    result: str                 # pass | fail | skip
    reason: str
    subject: str | None = None  # the route, for per-route predicates
    fix: str | None = None      # only on fail

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    paths: Paths
    routes: RouteTable | None
    routes_error: str | None
    observed: dict
    tree: Path                  # the code tree the lints scan
    home: Path
    claude_code: str | None


@dataclass(frozen=True)
class Invariant:
    id: str
    statement: str
    fix: str
    per_route: bool
    fn: Callable


REGISTRY: dict[str, Invariant] = {}


def invariant(id: str, *, statement: str, fix: str, per_route: bool = False):
    def deco(fn):
        REGISTRY[id] = Invariant(id, statement, fix, per_route, fn)
        return fn
    return deco


def ok(reason: str = "ok"):
    return "pass", reason


def fail(reason: str):
    return "fail", reason


def skip(reason: str):
    return "skip", reason


def claude_code_version() -> str | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"\s*(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def build_context(paths: Paths, *, with_claude_code: bool = False) -> Context:
    try:
        table, err = load_routes(paths), None
    except (SchemaError, OSError) as e:
        table, err = None, str(e)
    try:
        observed = read_observed(paths)
    except SchemaError as e:
        observed = {"_error": str(e), "copy": None, "sources": {}, "routes": {}, "last_check": None, "last_gate_run": None, "spend": {}}
    return Context(paths, table, err, observed, paths.code_tree, paths.home, claude_code_version() if with_claude_code else None)


def evaluate(ctx: Context, ids: list[str] | None = None, route: str | None = None) -> list[Result]:
    out: list[Result] = []
    for inv in REGISTRY.values():
        if ids is not None and inv.id not in ids:
            continue
        if inv.per_route:
            if ctx.routes is None:
                out.append(Result(inv.id, "fail", f"routes did not load: {ctx.routes_error}", None, "fix routes.toml"))
                continue
            for name in ([route] if route else list(ctx.routes.routes)):
                res, reason = inv.fn(ctx, ctx.routes.routes[name])
                out.append(Result(inv.id, res, reason, name, inv.fix if res == "fail" else None))
        else:
            res, reason = inv.fn(ctx)
            out.append(Result(inv.id, res, reason, None, inv.fix if res == "fail" else None))
    return out


def skipped_ids(results: list[Result]) -> list[str]:
    return [f"{r.id}:{r.subject}" if r.subject else r.id for r in results if r.result == "skip"]


# ---- the predicates (§8 table) ---------------------------------------------------------------------------------

@invariant("route.served", per_route=True,
           statement="every route's wire_model is in its source's live catalog",
           fix="run `agent-on sync`; if still orphaned, the source renamed the model — update wire_model")
def route_served(ctx: Context, route):
    src = ctx.observed["sources"].get(route.source)
    if src is None or src.get("reachable") is None:
        return skip(f"{route.source} not probed yet — run `agent-on sync`")
    if not src["reachable"]:
        return skip(f"{route.source} unreachable: {src.get('error')}")
    r = ctx.observed["routes"].get(route.name)
    if r is None or r.get("served") is None:
        return skip("no observation for this route — run `agent-on sync`")
    if r["served"]:
        return ok(f"served (checked {r['checked']})")
    return fail(f"{route.wire_model!r} not in {route.source} catalog (checked {r['checked']})")


@invariant("route.unique",
           statement="no two routes share a name, an alias, or (source, wire_model); discovered routes dedup against packaged at read time, packaged wins",
           fix="rename or remove the colliding route or alias in routes.toml")
def route_unique(ctx: Context):
    if ctx.routes is None:
        return fail(ctx.routes_error) if "routes.unique" in (ctx.routes_error or "") else skip(f"routes did not load: {ctx.routes_error}")
    note = f"; {len(ctx.routes.shadowed)} discovered shadowed by packaged" if ctx.routes.shadowed else ""
    return ok(f"{len(ctx.routes.routes)} routes unique{note}")


@invariant("source.limits.propagated", per_route=True,
           statement="every route carries limits — its own, or its source's (propagation only; application is the verified tier)",
           fix="declare [sources.<source>.limits] with confidence and source, or limits on the route")
def source_limits_propagated(ctx: Context, route):
    if route.limits is not None:
        return ok(f"declares its own: input {route.limits.input} / output {route.limits.output} ({route.limits.confidence})")
    lim = ctx.routes.effective_limits(route)
    if lim is None:
        return fail(f"no limits: source {route.source!r} declares none and the route declares none")
    return ok(f"inherits source limits: input {lim.input} / output {lim.output} ({lim.confidence})")


@invariant("limits.declared_vs_observed", per_route=True,
           statement="declared input ≤ verified when present, else ≤ min(configured, advertised) and reported unverified",
           fix="lower the declared limit in routes.toml, or re-run `agent-on sync` if the source changed")
def limits_declared_vs_observed(ctx: Context, route):
    lim = ctx.routes.effective_limits(route)
    if lim is None or lim.input is None:
        return skip("no declared input limit")
    r = ctx.observed["routes"].get(route.name)
    tier = r["limits"]["input"] if r else None
    if not tier:
        return skip("no observation — run `agent-on sync`")
    if tier.get("verified") is not None:
        if lim.input <= tier["verified"]:
            return ok(f"declared {lim.input} ≤ verified {tier['verified']}")
        return fail(f"declared {lim.input} > verified {tier['verified']}")
    bounds = {k: tier[k] for k in ("configured", "advertised") if tier.get(k) is not None}
    if not bounds:
        return skip("no configured or advertised limit observed yet")
    k, v = min(bounds.items(), key=lambda kv: kv[1])
    if lim.input <= v:
        return ok(f"declared {lim.input} ≤ {k} {v} (unverified)")
    return fail(f"declared {lim.input} > {k} {v}")


@invariant("copy.single",
           statement="the shim resolves to this checkout and the tree is clean (dirty is reported, not failed)",
           fix="re-link: ln -sfn <checkout>/bin/agent-on ~/.local/bin/agent-on")
def copy_single(ctx: Context):
    shim = ctx.paths.shim
    if not shim.is_symlink():
        if shim.exists():
            return fail(f"{shim} exists but is not a symlink")
        return skip(f"no shim at {shim} (install lands in Plan D)")
    target = Path(os.readlink(shim))
    target = (target if target.is_absolute() else shim.parent / target).resolve()
    expected = (ctx.tree / "bin" / "agent-on").resolve()
    if target != expected:
        return fail(f"{shim} -> {target}, not {expected}")
    dirty = describe_copy(ctx.paths)["dirty"]
    return ok("shim points here" + (" (tree dirty — reported, not failed)" if dirty else ""))


@invariant("credential.not_in_child_env",
           statement="a launched child's environment contains no source auth_env value",
           fix="the launcher must scrub every source's auth_env before spawn (§11)")
def credential_not_in_child_env(ctx: Context):
    return skip("no launcher yet — asserted by the launch unit test in Plan B")


ENV_DENY = ("ANTHROPIC_*", "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_MAX_*", "*_PROXY")
TIER_NAMES = ("default", "fable", "opus", "sonnet", "haiku", "opusplan")


@invariant("harness.env.clean",
           statement="~/.claude/settings.json sets none of the routing denylist (a shared env block overrides the launcher's process env)",
           fix="move the key out of ~/.claude/settings.json; the launcher sets routing per launch")
def harness_env_clean(ctx: Context):
    p = ctx.home / ".claude" / "settings.json"
    if not p.exists():
        return skip(f"no shared settings at {p}")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        return fail(f"{p} is not JSON: {e}")
    bad = [k for k in (d.get("env") or {}) if any(fnmatch.fnmatchcase(k, pat) for pat in ENV_DENY)]
    if bad:
        return fail(f"env sets {bad}")
    if "apiKeyHelper" in d:
        return fail("apiKeyHelper is set in the shared settings")
    m = d.get("model")
    if m is not None and m not in TIER_NAMES:
        return fail(f"model = {m!r} is a literal model id; it bypasses the tier slots the launcher pins (D7)")
    return ok("clean" + (f" (model = {m!r} is a tier name; it resolves through the launcher's slots)" if m else ""))


@invariant("gate.no_silent_skip",
           statement="the last gate run lists every skip and ran every verifier it declared",
           fix="the gate runner must record `skipped` for each skip result and run each declared verifier")
def gate_no_silent_skip(ctx: Context):
    g = ctx.observed.get("last_gate_run")
    if not g:
        return skip("no gate run recorded yet — run `agent-on gate`")
    listed = set(g.get("skipped") or [])
    silent = [k for k, v in (g.get("invariants") or {}).items() if v == "skip" and k not in listed]
    if silent:
        return fail(f"skips not listed: {silent}")
    v = g.get("verifiers") or {}
    missing = [x for x in v.get("declared", []) if x not in v.get("ran", [])]
    if missing:
        return fail(f"declared verifiers never ran: {missing}")
    return ok(f"{len(listed)} skip(s) listed, {len(v.get('ran', []))} verifier(s) ran")


@invariant("gate.mock.ephemeral",
           statement="the gate's mock source binds an ephemeral port, never a configured one",
           fix="the mock must bind port 0 and record the port the OS assigned")
def gate_mock_ephemeral(ctx: Context):
    g = ctx.observed.get("last_gate_run")
    if not g or g.get("mock_port") is None:
        return skip("no gate run with a mock port recorded")
    port = g["mock_port"]
    configured = {s.port() for s in ctx.routes.sources.values()} if ctx.routes else set()
    if port in configured or port < 1024:
        return fail(f"mock port {port} collides with a configured source port {sorted(configured)} or is privileged")
    return ok(f"mock port {port}")


ROUTE_LITERAL_DIRS = ("agent_on", "tests/agent_on")


def route_literals(tree: Path, source_names) -> list[tuple[str, str]]:
    names = sorted(source_names, key=len, reverse=True)
    if not names:
        return []
    pat = re.compile(r"(?<![\w@./-])(" + "|".join(re.escape(s) for s in names) + r")/[A-Za-z0-9][A-Za-z0-9._/-]*")
    found: list[tuple[str, str]] = []
    for d in ROUTE_LITERAL_DIRS:
        base = tree / d
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.py")):
            for m in pat.finditer(f.read_text(encoding="utf-8")):
                found.append((str(f.relative_to(tree)), m.group(0).rstrip(".")))
    return found


@invariant("test.names.derived",
           statement="no test or package file contains a route-name literal that routes.toml does not declare",
           fix="derive the name from routes.toml (load_routes) or use the mock source name")
def test_names_derived(ctx: Context):
    if ctx.routes is None:
        return skip(f"routes did not load: {ctx.routes_error}")
    if ctx.tree.resolve() != ctx.paths.checkout.resolve():
        return skip("routes.toml and the code tree differ (scratch run); the lint applies to the checkout only")
    declared = set(ctx.routes.routes) | {f"{r.source}/{r.wire_model}" for r in ctx.routes.routes.values()}
    stray = [(f, lit) for f, lit in route_literals(ctx.tree, ctx.routes.sources) if lit not in declared]
    return fail(f"undeclared route literals: {stray[:5]}") if stray else ok("no undeclared route literals")


@invariant("knowledge.typed",
           statement="every knowledge record validates against its kind's schema",
           fix="fix or remove the offending line; `agent-on learn` validates before appending (Plan C)")
def knowledge_typed(ctx: Context):
    kdir = ctx.tree / "knowledge"
    if not kdir.exists():
        return skip("no knowledge/ yet — Plan C")
    files = sorted(kdir.glob("*.jsonl"))
    errors = [e for f in files for e in validate_file(f)]
    return fail("; ".join(errors[:5])) if errors else ok(f"{len(files)} file(s) valid")


SCHEMA_ERROR_USE = re.compile(r'SchemaError\(\s*"([^"]+)"')


def schema_rules_used(tree: Path) -> set[str]:
    base = tree / "agent_on"
    if not base.exists():
        return set()
    return {m.group(1) for f in base.rglob("*.py") for m in SCHEMA_ERROR_USE.finditer(f.read_text(encoding="utf-8"))}


@invariant("schema.complete",
           statement="every rule a validator raises is registered in schemas.errors.RULES, and every registered rule is raised somewhere",
           fix="add the rule to RULES with its statement, or delete the dead rule")
def schema_complete(ctx: Context):
    used = schema_rules_used(ctx.tree)
    unregistered = sorted(used - set(RULES))
    dead = sorted(set(RULES) - used)
    if unregistered or dead:
        return fail(f"unregistered: {unregistered}; registered but never raised: {dead}")
    return ok(f"{len(RULES)} rules, all registered and raised")


@invariant("cost.not_copied",
           statement="no L2 field is sourced from Claude Code's total_cost_usd",
           fix="compute cost from usage × the route's price (§12)")
def cost_not_copied(ctx: Context):
    if "_error" in ctx.observed:
        return fail(ctx.observed["_error"])
    try:
        forbid_claude_cost(ctx.observed)
    except SchemaError as e:
        return fail(str(e))
    return ok("no Claude Code cost figure in observed.json")


@invariant("qualification.current", per_route=True,
           statement="the route's last qualification fingerprint still matches the effective configuration, the wire model, the source identity and the Claude Code version",
           fix="re-run `agent-on qualify <route>`")
def qualification_current(ctx: Context, route):
    r = ctx.observed["routes"].get(route.name)
    q = r.get("last_qualification") if r else None
    if not q:
        return skip("never qualified")
    fp = q.get("fingerprint") or {}
    now = {"effective_route_sha": ctx.routes.effective_sha(route), "wire_model": route.wire_model,
           "source_identity": (ctx.observed["sources"].get(route.source) or {}).get("identity"), "claude_code": ctx.claude_code}
    stale = [k for k, v in now.items() if v is not None and fp.get(k) != v]
    if stale:
        return fail(f"stale: {stale} (qualified {q.get('at')})")
    unchecked = [k for k, v in now.items() if v is None]
    return ok(f"current (qualified {q.get('at')})" + (f"; not compared: {unchecked}" if unchecked else ""))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass. `test_schema_rules_registry_is_complete_and_alive` runs against the real tree: if it fails with "registered but never raised", a rule in `RULES` has no raiser — every rule listed in Task 2 is raised by the code in Tasks 2, 3 and 7 (`knowledge.record` by `schemas/knowledge.py`); do not delete rules to make it pass, find the missing raise. The tests plant observations with `update_observed` — exactly the records `sync` (Task 8) writes — so this task has no dependency on `sync`.

- [ ] **Step 5: Commit**

```bash
git add agent_on/schemas/knowledge.py agent_on/invariants.py tests/agent_on/test_invariants.py
git commit -m "feat(agent-on): the invariant registry — fourteen predicates with reproductions for F1–F14

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---
### Task 8: `sync`

**Files:**
- Create: `agent_on/sync.py`
- Test: `tests/agent_on/test_sync.py`

**Interfaces:**
- Consumes: `parse_routes_text`, `load_routes`, `Route`, `discovered_text`, `probe_all`, `omlx_settings_path`, `read_configured_limits`, `fetch_openrouter_spend`, `resolve_secret`, `update_observed`, `write_discovered`, `empty_route`, `empty_source`, `compute_context`, `describe_copy`, `invariants.build_context/evaluate` (Task 7)
- Produces: `run_sync(paths, *, timeout=5.0, env=None) -> dict` with keys `command, copy, sources{name: {reachable, error, catalog_count}}, discovered[], shadowed[], orphans[], spend{}, invariants[]`.

Rules encoded (§7 table, §9): `served = wire_model ∈ catalog`; `served` is `null` (unmeasured) when the source is unreachable — never a stale `true`; limits tiers `configured` (loopback oMLX settings) and `advertised` (catalog) refreshed, `verified` never touched; `cost_model.context/basis` recomputed by `compute_context`; `usd_per_mtok` = the route's price, else zeros when the source has no `auth_env` (nothing bills), else `null`; for a non-discover source only declared routes' catalog entries are kept plus the count; spend is fetched for every source with an `auth_env` (today: OpenRouter) or recorded with an error naming where the key was looked for; orphans = packaged routes whose reachable source does not serve them.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_sync.py`:

```python
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402
from agent_on.state import read_observed  # noqa: E402
from agent_on.sync import run_sync  # noqa: E402

CATALOG = [omlx_entry("alpha", 262144), omlx_entry("beta", 131072), openrouter_entry("vendor/model-x", 200000, 8000)]
SPEND = {"usage": 1.5, "limit": 10, "limit_reset": "daily", "limit_remaining": 8.5, "usage_daily": 0.5}


class SyncTest(unittest.TestCase):
    def test_sync_measures_served_limits_discovery_orphans_and_spend(self):
        with MockSource(catalog=CATALOG, spend=SPEND, expect_key="k-1") as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            settings = sb.paths.home / ".omlx" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"sampling": {"max_context_window": 131072, "max_tokens": 32768}}), encoding="utf-8")
            before = sb.paths.routes_toml.read_bytes()
            report = run_sync(sb.paths, timeout=3, env={"MOCK_PAID_KEY": "k-1"})
            self.assertEqual(sb.paths.routes_toml.read_bytes(), before, "sync never touches routes.toml")
            self.assertEqual(report["orphans"], ["mock/gone"])                      # F1: declared but not served
            # alpha is packaged → shadowed, not discovered; the OpenRouter-shaped entry is also in `mock`'s catalog (one mock, two sources)
            self.assertEqual(report["discovered"], ["mock/beta", "mock/vendor/model-x"])
            self.assertEqual(report["shadowed"], [])
            obs = read_observed(sb.paths)
            self.assertTrue(obs["sources"]["mock"]["reachable"])
            self.assertEqual(obs["sources"]["mock"]["catalog"], ["alpha", "beta", "vendor/model-x"])
            self.assertEqual(obs["sources"]["mock"]["identity"], "owned_by=omlx")
            self.assertEqual(obs["sources"]["mock"]["configured_limits"]["input"], 131072)
            self.assertEqual(set(obs["sources"]["paid"]["catalog"]), {"vendor/model-x"})   # non-discover: declared entries only
            self.assertEqual(obs["sources"]["paid"]["catalog_count"], 3)
            r = obs["routes"]["mock/alpha"]
            self.assertTrue(r["served"])
            self.assertEqual(r["limits"]["input"], {"configured": 131072, "advertised": 262144, "verified": None, "checked": r["checked"]})
            self.assertEqual(r["limits"]["output"]["configured"], 32768)
            self.assertEqual((r["cost_model"]["context"], r["cost_model"]["context_basis"]), (8192, "declared"))   # source limit 8192 wins
            self.assertEqual(r["cost_model"]["usd_per_mtok"], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
            self.assertEqual(r["cost_model"]["caching"], "unknown")                   # never inferred from a price
            self.assertFalse(obs["routes"]["mock/gone"]["served"])
            x = obs["routes"]["paid/vendor/model-x"]
            self.assertEqual((x["cost_model"]["context"], x["cost_model"]["context_basis"]), (100000, "declared"))
            self.assertEqual(x["limits"]["input"]["advertised"], 200000)
            self.assertEqual(x["cost_model"]["usd_per_mtok"]["input"], 1.0)
            self.assertEqual(obs["routes"]["mock/beta"]["cost_model"]["context"], 8192)   # discovered → inherited source limit
            self.assertEqual(obs["spend"]["paid"]["usd_used"], 1.5)
            self.assertIsNone(obs["spend"]["paid"]["error"])
            self.assertEqual([i["id"] for i in report["invariants"]], ["route.unique"])
            self.assertEqual(report["invariants"][0]["result"], "pass")
            table = load_routes(sb.paths)
            self.assertIn("mock/beta", table.routes)
            self.assertEqual(table.effective_limits(table.routes["mock/beta"]).input, 8192)
            self.assertEqual(list(sb.paths.state.glob("*.tmp.*")), [])

    def test_declared_over_advertised_is_visible_and_second_sync_shadows_a_promoted_route(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            self.assertIn("mock/beta", sb.paths.discovered_toml.read_text())
            # promote beta to packaged by hand (what `add` does), then sync again: it must drop out of the discovered file
            sb.paths.routes_toml.write_text(sb.paths.routes_toml.read_text() + '\n[routes."mock/beta"]\n', encoding="utf-8")
            report = run_sync(sb.paths, timeout=3, env={})
            self.assertNotIn("mock/beta", sb.paths.discovered_toml.read_text())
            self.assertEqual(report["discovered"], ["mock/vendor/model-x"])
            self.assertTrue(read_observed(sb.paths)["routes"]["mock/beta"]["served"])

    def test_unreachable_source_records_the_error_and_leaves_served_unmeasured(self):
        with Sandbox(MOCK_ROUTES.format(base="http://127.0.0.1:9")) as sb:
            report = run_sync(sb.paths, timeout=1, env={})
            obs = read_observed(sb.paths)
            self.assertFalse(obs["sources"]["mock"]["reachable"])
            self.assertIn(":9", obs["sources"]["mock"]["error"])
            self.assertIsNone(obs["routes"]["mock/alpha"]["served"])
            self.assertIsNone(obs["routes"]["mock/alpha"]["limits"]["input"]["advertised"])
            self.assertEqual(report["orphans"], [])
            self.assertEqual(report["discovered"], [])
            self.assertIn("MOCK_PAID_KEY", obs["spend"]["paid"]["error"])            # no key anywhere → said where it looked
            self.assertTrue(sb.paths.discovered_toml.exists())

    def test_a_source_that_goes_unreachable_loses_its_stale_catalog_and_identity(self):
        m = MockSource(catalog=CATALOG).start()
        with Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            self.assertEqual(read_observed(sb.paths)["sources"]["mock"]["identity"], "owned_by=omlx")
            m.stop()
            run_sync(sb.paths, timeout=1, env={})
            src = read_observed(sb.paths)["sources"]["mock"]
            self.assertFalse(src["reachable"])
            self.assertIsNone(src["catalog"])                                   # a stale list under a fresh `checked` is R1
            self.assertIsNone(src["identity"])
            self.assertIsNone(src["catalog_count"])
            self.assertIsNone(read_observed(sb.paths)["routes"]["mock/alpha"]["served"])

    def test_spend_key_comes_from_the_env_file_when_the_environment_has_none(self):
        with MockSource(catalog=CATALOG, spend=SPEND, expect_key="k-file") as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            sb.paths.state.mkdir()
            sb.paths.env_file.write_text("MOCK_PAID_KEY=k-file\n", encoding="utf-8")
            os.chmod(sb.paths.env_file, 0o600)
            run_sync(sb.paths, timeout=3, env={})
            self.assertEqual(read_observed(sb.paths)["spend"]["paid"]["usd_limit"], 10)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_sync.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.sync'`

- [ ] **Step 3: Write the module**

`agent_on/sync.py`:

```python
"""`agent-on sync` (§9): probe every source; refresh catalogs, served flags, configured/advertised limits and spend;
rewrite routes.discovered.toml; report orphans. Never writes `verified` (that is `qualify --limits`), never touches
routes.toml, never dirties a tracked file (D13)."""
from __future__ import annotations

import os

from .invariants import build_context, evaluate
from .paths import Paths, describe_copy
from .schemas.observed import compute_context, empty_route, empty_source
from .schemas.routes import Route, discovered_text, load_routes, parse_routes_text
from .sources import fetch_openrouter_spend, omlx_settings_path, probe_all, read_configured_limits
from .state import resolve_secret, update_observed, write_discovered
from .util import utc_now

FREE = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


def run_sync(paths: Paths, *, timeout: float = 5.0, env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    srcs, packaged, _ = parse_routes_text(paths.routes_toml.read_text(encoding="utf-8"), packaged=True)
    probes = probe_all(srcs, timeout)
    now = utc_now()

    # 1. discovered routes: every catalog id of a reachable discover=true source that no packaged route serves
    packaged_keys = {(r.source, r.wire_model) for r in packaged.values()}
    discovered: list[Route] = []
    for name, src in srcs.items():
        if not src.discover or not probes[name].reachable:
            continue
        for model_id in sorted(probes[name].catalog):
            if (name, model_id) not in packaged_keys:
                discovered.append(Route(f"{name}/{model_id}", name, model_id, (), None, None, None, packaged=False))
    write_discovered(paths, discovered_text(discovered, now))
    table = load_routes(paths)   # packaged + the file just written, dedup'd (packaged wins)

    # 2. side facts: the local oMLX settings file, and spend for every keyed source
    configured: dict[str, dict] = {}
    for name, src in srcs.items():
        p = omlx_settings_path(src, paths.home)
        if p is not None and p.exists():
            got = read_configured_limits(p, paths.home)
            if got is not None:
                configured[name] = got
    spend: dict[str, dict] = {}
    for name, src in srcs.items():
        if not src.auth_env:
            continue
        key = resolve_secret(paths, src.auth_env, env)
        if key:
            spend[name] = fetch_openrouter_spend(src.base_url, key, timeout)
        else:
            spend[name] = {"usd_used": None, "usd_limit": None, "limit_reset": None, "usd_remaining": None, "usd_used_daily": None,
                           "source": f"openrouter GET {src.base_url.rstrip('/')}/v1/auth/key", "checked": now,
                           "error": f"no {src.auth_env} in the environment or in {paths.env_file}"}

    orphans: list[str] = []

    def mutate(doc: dict) -> None:
        doc["copy"] = describe_copy(paths)
        for name, src in srcs.items():
            pr = probes[name]
            s = doc["sources"].setdefault(name, empty_source())
            s.update({"reachable": pr.reachable, "checked": pr.checked, "error": pr.error,
                      "catalog_count": pr.catalog_count if pr.reachable else None,
                      "identity": pr.identity if pr.reachable else None,        # not measured now → null, never stale (R1)
                      "configured_limits": configured.get(name)})
            if not pr.reachable:
                s["catalog"] = None
            elif src.discover:
                s["catalog"] = sorted(pr.catalog)
            else:   # keep only what declared routes need, plus the count (§7)
                declared = {r.wire_model for r in table.by_source(name)}
                s["catalog"] = {k: v for k, v in pr.catalog.items() if k in declared}
        for rname, route in table.routes.items():
            r = doc["routes"].setdefault(rname, empty_route())
            pr = probes[route.source]
            r["checked"] = now
            if pr.reachable:
                r["served"] = route.wire_model in pr.catalog
                if route.packaged and not r["served"]:
                    orphans.append(rname)
                entry = pr.catalog.get(route.wire_model) or {}
                advertised = {"input": entry.get("max_input"), "output": entry.get("max_output")}
            else:
                r["served"] = None                              # unmeasured now, never a stale true
                advertised = {"input": None, "output": None}
            conf = configured.get(route.source) or {}
            for k in ("input", "output"):
                r["limits"][k].update({"configured": conf.get(k), "advertised": advertised[k], "checked": now})   # never `verified`
            lim = table.effective_limits(route)
            context, basis = compute_context(lim.input if lim else None, r["limits"]["input"])
            if route.price is not None:
                usd = route.price.per_mtok()
            elif srcs[route.source].auth_env is None:
                usd = dict(FREE)                                # nothing bills a keyless source
            else:
                usd = None                                      # a keyed source with no price declared: unknown, not 0
            r["cost_model"].update({"context": context, "context_basis": basis, "usd_per_mtok": usd})
        for name, sp in spend.items():
            doc["spend"][name] = sp

    doc = update_observed(paths, mutate)
    invariants = [r.as_dict() for r in evaluate(build_context(paths), ids=["route.unique"])]
    return {"command": "sync", "copy": doc["copy"],
            "sources": {n: {"reachable": p.reachable, "error": p.error, "catalog_count": p.catalog_count} for n, p in probes.items()},
            "discovered": [r.name for r in discovered], "shadowed": list(table.shadowed), "orphans": sorted(orphans),
            "spend": spend, "invariants": invariants}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_on/sync.py tests/agent_on/test_sync.py
git commit -m "feat(agent-on): sync — served flags, limit tiers, discovery, orphans, spend

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 9: `status [route] [--check]`

**Files:**
- Create: `agent_on/status.py`
- Test: `tests/agent_on/test_status.py`

**Interfaces:**
- Consumes: `build_context`, `evaluate`, `skipped_ids`, `describe_copy`, `update_observed`, `utc_now`, `cli.copy_line`, `cli.invariant_lines`
- Produces: `build_status(paths, *, route=None, check=False) -> dict` with keys `command, copy, routes_error, routes{name: {declared, observed}}, shadowed[], orphaned[], sources{}, spend{}, last_check, last_gate_run, invariants (list | None)`; `render_text(doc) -> str`; `route_view(table, observed, route) -> dict`.

Rules: `status` reads and, only with an unscoped `--check`, writes `last_check` — never `last_gate_run` (Q4). `status <route> --check` evaluates the per-route predicates for that route only and *shows* them; it never persists a partial check as `last_check`, because a later `status` would print it as if every invariant had been evaluated. `declared` shows the effective limits and where they came from (`limits_from = route | source | None`), the price, the reasoning table, and the `effective_route_sha` the fingerprint uses; `observed` is the raw L2 record or `null`. `orphaned` lists packaged routes with `served == false`.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_status.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.state import read_observed  # noqa: E402
from agent_on.status import build_status, render_text  # noqa: E402
from agent_on.sync import run_sync  # noqa: E402

BASE = "http://127.0.0.1:1"


class StatusTest(unittest.TestCase):
    def test_declared_beside_observed_before_any_sync(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc = build_status(sb.paths)
            self.assertEqual(doc["command"], "status")
            self.assertEqual(set(doc["routes"]), {"mock/alpha", "mock/gone", "paid/vendor/model-x"})
            alpha = doc["routes"]["mock/alpha"]
            self.assertEqual(alpha["declared"]["limits"]["input"], 8192)
            self.assertEqual(alpha["declared"]["limits_from"], "source")
            self.assertEqual(doc["routes"]["paid/vendor/model-x"]["declared"]["limits_from"], "route")
            self.assertEqual(doc["routes"]["paid/vendor/model-x"]["declared"]["price"]["input"], 1.0)
            self.assertIsNone(alpha["observed"])                                  # never measured → null, not a guess
            self.assertEqual(len(alpha["declared"]["effective_route_sha"]), 16)
            self.assertIsNone(doc["invariants"])
            self.assertIsNone(doc["last_check"])
            self.assertEqual(doc["orphaned"], [])
            self.assertIn("copy:", render_text(doc).splitlines()[0])
            json.dumps(doc)                                                       # --json must serialise as-is

    def test_route_filter_accepts_aliases_and_rejects_unknown(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(list(build_status(sb.paths, route="a")["routes"]), ["mock/alpha"])
            with self.assertRaises(KeyError):
                build_status(sb.paths, route="nope")

    def test_check_writes_last_check_never_last_gate_run(self):  # Q4
        with MockSource(catalog=[omlx_entry("alpha"), openrouter_entry("vendor/model-x")]) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            doc = build_status(sb.paths, check=True)
            self.assertIsNotNone(doc["invariants"])
            ids = {i["id"] for i in doc["invariants"]}
            self.assertIn("route.served", ids)
            self.assertEqual(doc["last_check"]["result"], "fail")                 # mock/gone is orphaned (F1)
            self.assertEqual(doc["orphaned"], ["mock/gone"])
            obs = read_observed(sb.paths)
            self.assertEqual(obs["last_check"]["result"], "fail")
            self.assertIsNone(obs["last_gate_run"])
            self.assertIn("credential.not_in_child_env", obs["last_check"]["skipped"])
            text = render_text(doc)
            self.assertIn("fail route.served[mock/gone]", text)
            self.assertIn("skip credential.not_in_child_env", text)
            self.assertIn("ORPHANED", text)

    def test_check_on_one_route_is_shown_but_never_persisted(self):
        with MockSource(catalog=[omlx_entry("alpha"), openrouter_entry("vendor/model-x")]) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            doc = build_status(sb.paths, route="mock/alpha", check=True)
            subjects = {i["subject"] for i in doc["invariants"] if i["subject"]}
            self.assertEqual(subjects, {"mock/alpha"})
            self.assertIsNone(doc["last_check"])                                # a partial check must not stand as the last check (Q4)
            self.assertIsNone(read_observed(sb.paths)["last_check"])
            build_status(sb.paths, check=True)
            self.assertEqual(read_observed(sb.paths)["last_check"]["result"], "fail")   # the full check sees mock/gone

    def test_broken_routes_toml_is_reported_not_raised(self):
        with Sandbox("version = 7\n") as sb:
            doc = build_status(sb.paths)
            self.assertIn("routes.version", doc["routes_error"])
            self.assertEqual(doc["routes"], {})
            self.assertIn("ERROR", render_text(doc))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_status.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.status'`

- [ ] **Step 3: Write the module**

`agent_on/status.py`:

```python
"""`agent-on status [route] [--check]` (§9): L1 beside L2 for every route or one; with --check every invariant is
evaluated and `last_check` written — never `last_gate_run`, which only the gate runner writes (Q4)."""
from __future__ import annotations

from .cli import copy_line, invariant_lines
from .invariants import build_context, evaluate, skipped_ids
from .paths import Paths, describe_copy
from .state import update_observed
from .util import utc_now


def fmt(v) -> str:
    return "✓" if v is True else "✗" if v is False else "?"


def route_view(table, observed: dict, route) -> dict:
    lim = table.effective_limits(route)
    declared = {"source": route.source, "wire_model": route.wire_model, "aliases": list(route.aliases), "packaged": route.packaged,
                "limits": lim.as_dict() if lim else None,
                "limits_from": "route" if route.limits is not None else ("source" if lim else None),
                "price": route.price.per_mtok() if route.price else None,
                "reasoning": None if route.reasoning is None else {"supported": route.reasoning.supported,
                                                                    "efforts": list(route.reasoning.efforts),
                                                                    "provider_efforts": list(route.reasoning.provider_efforts)},
                "effective_route_sha": table.effective_sha(route)}
    return {"declared": declared, "observed": observed["routes"].get(route.name)}


def build_status(paths: Paths, *, route: str | None = None, check: bool = False) -> dict:
    ctx = build_context(paths, with_claude_code=check)
    doc = {"command": "status", "copy": describe_copy(paths), "routes_error": ctx.routes_error, "routes": {}, "shadowed": [],
           "orphaned": [], "sources": ctx.observed["sources"], "spend": ctx.observed["spend"],
           "last_check": ctx.observed["last_check"], "last_gate_run": ctx.observed["last_gate_run"], "invariants": None}
    selected: str | None = None
    if ctx.routes is not None:
        if route:
            selected = ctx.routes.resolve(route).name        # KeyError → exit 2 in cli
        names = [selected] if selected else list(ctx.routes.routes)
        doc["routes"] = {n: route_view(ctx.routes, ctx.observed, ctx.routes.routes[n]) for n in names}
        doc["shadowed"] = list(ctx.routes.shadowed)
        doc["orphaned"] = [n for n in names if ctx.routes.routes[n].packaged
                           and (ctx.observed["routes"].get(n) or {}).get("served") is False]
    if check:
        results = evaluate(ctx, route=selected)
        doc["invariants"] = [r.as_dict() for r in results]
        if selected is None:   # only a full check may stand as `last_check`; a scoped one is shown, never recorded (Q4)
            summary = {"at": utc_now(), "commit": doc["copy"]["commit"],
                       "result": "fail" if any(r.result == "fail" for r in results) else "pass",
                       "skipped": skipped_ids(results)}
            update_observed(paths, lambda d: d.__setitem__("last_check", summary))
            doc["last_check"] = summary
    return doc


def render_text(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    if doc.get("routes_error"):
        lines.append(f"routes.toml: ERROR {doc['routes_error']}")
    for n, s in doc["sources"].items():
        lines.append(f"source {n}: reachable={fmt(s.get('reachable'))} checked={s.get('checked') or '-'}"
                     + (f" error={s['error']}" if s.get("error") else "")
                     + (f" catalog={s['catalog_count']}" if s.get("catalog_count") is not None else ""))
    for n, v in doc["routes"].items():
        d, o = v["declared"], v["observed"] or {}
        lim = d["limits"] or {}
        cm = o.get("cost_model") or {}
        lines.append(f"route {n}" + (f" [{', '.join(d['aliases'])}]" if d["aliases"] else "")
                     + f": wire={d['wire_model']} declared_in={lim.get('input') or '?'} ({lim.get('confidence') or '-'})"
                     + f" ctx={cm.get('context') or '?'} ({cm.get('context_basis') or '-'}) served={fmt(o.get('served'))}"
                     + f" checked={o.get('checked') or '-'}")
    if doc.get("shadowed"):
        lines.append(f"shadowed discovered: {', '.join(doc['shadowed'])}")
    if doc.get("orphaned"):
        lines.append(f"ORPHANED packaged routes: {', '.join(doc['orphaned'])}")
    for n, s in doc["spend"].items():
        lines.append(f"spend {n}: used ${s.get('usd_used')} limit ${s.get('usd_limit')}/{s.get('limit_reset')}"
                     f" remaining ${s.get('usd_remaining')} today ${s.get('usd_used_daily')}" + (f" error={s['error']}" if s.get("error") else ""))
    for key in ("last_check", "last_gate_run"):
        g = doc.get(key)
        lines.append(f"{key}: " + (f"{g['result']} at {g['at']} commit {g.get('commit')} skipped={g.get('skipped') or []}" if g else "never"))
    if doc.get("invariants") is not None:
        lines += invariant_lines(doc["invariants"])
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass. Then, by hand on the real checkout: `./bin/agent-on status` prints the six routes with `served=?` (nothing measured yet) and `./bin/agent-on status --json | python3 -m json.tool >/dev/null`.

- [ ] **Step 5: Commit**

```bash
git add agent_on/status.py tests/agent_on/test_status.py
git commit -m "feat(agent-on): status — declared beside observed, --check writes last_check only

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 10: `gate` and the CI job

**Files:**
- Create: `agent_on/gate.py`
- Modify: `.github/workflows/ci.yml` (append one job)
- Test: `tests/agent_on/test_gate.py`

**Interfaces:**
- Consumes: `MockSource`, `omlx_entry`, `run_sync`, `build_context`, `evaluate`, `skipped_ids`, `update_observed`, `describe_copy`, `utc_now`
- Produces: `run_gate(paths) -> dict` with keys `command, copy, tests{ran, ok, tail, skipped}, smoke{ok, results, expected}, invariants[], last_gate_run{}, result`; `run_smoke(mock) -> {ok, results{"route.served:<route>": pass|fail}, expected}`; `VERIFIERS: list[str]` (empty in Plan A; Plan B appends the fidelity verifier); `INNER_ENV = "AGENT_ON_GATE_INNER"`. `last_gate_run.verifiers` is the object `{declared: [...], ran: [...]}` (spec §7/§10 rev 7) — a count could not let `gate.no_silent_skip` fail on a verifier declared but never run (F6).

The gate is: (1) the unit tests as a subprocess (`unittest discover -s tests/agent_on`), skipped with a stated reason when `AGENT_ON_GATE_INNER` is set (a test running the gate must not recurse); (2) the **smoke**: a temp checkout whose `routes.toml` points at the mock source with one live and one planted-dead packaged route, `sync`, then `route.served` must be `pass` for the live one, `fail` for the dead one, `pass` for the discovered extra — F1 reproduced on every gate run; (3) every invariant over the real checkout and state; (4) `last_gate_run` written with the skips listed and the mock's port. Result is `fail` if any of (1)–(3) failed. Exit 1 on fail.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_gate.py`:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from agent_on.gate import INNER_ENV, run_gate, run_smoke  # noqa: E402
from agent_on.mock_source import MockSource, omlx_entry  # noqa: E402
from agent_on.state import read_observed, update_observed  # noqa: E402

BASE = "http://127.0.0.1:1"


class GateTest(unittest.TestCase):
    def test_smoke_reproduces_f1_on_the_mock(self):
        with MockSource(catalog=[omlx_entry("alive"), omlx_entry("extra")]) as m:
            s = run_smoke(m)
            self.assertTrue(s["ok"], s)
            self.assertEqual(s["results"]["route.served:mock/dead"], "fail")
            self.assertEqual(s["results"]["route.served:mock/alive"], "pass")
            self.assertEqual(s["results"]["route.served:mock/extra"], "pass")
        with MockSource(catalog=[]) as m:                       # nothing served: the smoke itself must notice
            self.assertFalse(run_smoke(m)["ok"])

    def test_gate_records_last_gate_run_with_skips_and_an_ephemeral_port(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb, mock.patch.dict(os.environ, {INNER_ENV: "1"}):
            doc = run_gate(sb.paths)
            self.assertEqual(doc["tests"]["skipped"], "inner gate (tests already running)")
            self.assertTrue(doc["smoke"]["ok"])
            g = read_observed(sb.paths)["last_gate_run"]
            self.assertEqual(g["result"], "pass")
            self.assertGreaterEqual(g["mock_port"], 1024)
            self.assertNotEqual(g["mock_port"], 1)
            self.assertIn("route.served:mock/alpha", g["skipped"])             # never synced → skip, listed
            self.assertIn("credential.not_in_child_env", g["skipped"])
            self.assertTrue(any(s.startswith("tests:") for s in g["skipped"]))
            self.assertEqual(g["verifiers"], {"declared": [], "ran": []})
            self.assertEqual(g["invariants"]["route.served:mock/alpha"], "skip")
            self.assertIsNone(read_observed(sb.paths)["last_check"])           # the gate never writes last_check
            # and the gate's own record satisfies the two gate invariants on the next evaluation
            again = run_gate(sb.paths)
            byid = {(i["id"], i.get("subject")): i["result"] for i in again["invariants"]}
            self.assertEqual(byid[("gate.no_silent_skip", None)], "pass")
            self.assertEqual(byid[("gate.mock.ephemeral", None)], "pass")

    def test_a_failing_invariant_fails_the_gate(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb, mock.patch.dict(os.environ, {INNER_ENV: "1"}):
            def plant(doc):
                doc["last_gate_run"] = {"at": "x", "commit": "x", "result": "pass", "tests": 0, "verifiers": {"declared": ["v"], "ran": []},
                                        "invariants": {}, "skipped": [], "skipped_reasons": [], "mock_port": 51873}
            update_observed(sb.paths, plant)
            doc = run_gate(sb.paths)
            self.assertEqual(doc["result"], "fail")
            self.assertEqual({i["id"]: i["result"] for i in doc["invariants"]}["gate.no_silent_skip"], "fail")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_gate.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.gate'`

- [ ] **Step 3: Write the module and the CI job**

`agent_on/gate.py`:

```python
"""`agent-on gate` (§8): unit tests, the mock-source smoke that reproduces F1, every invariant; then
`last_gate_run` to L2 with every skip listed and the mock's port. (The knowledge/gate-runs.jsonl twin lands in Plan C.)"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .invariants import build_context, evaluate, skipped_ids
from .mock_source import MockSource, omlx_entry
from .paths import Paths, describe_copy
from .state import update_observed
from .sync import run_sync
from .util import utc_now

VERIFIERS: list[str] = []          # verifier processes join in Plan B; declared here so gate.no_silent_skip holds them to account
INNER_ENV = "AGENT_ON_GATE_INNER"

SMOKE_ROUTES = """version = 1
[sources.mock]
base_url = "{base}"
catalog = "/v1/models"
discover = true
[sources.mock.limits]
input = 4096
output = 1024
confidence = "owned-policy"
source = "gate smoke"
[routes."mock/alive"]
[routes."mock/dead"]
"""


def run_unit_tests(checkout: Path) -> dict:
    if os.environ.get(INNER_ENV):
        return {"ran": None, "ok": None, "tail": [], "skipped": "inner gate (tests already running)"}
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(checkout / "tests" / "agent_on"), "-p", "test_*.py"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(checkout), env={**os.environ, INNER_ENV: "1"}, timeout=900)
    m = re.search(r"Ran (\d+) tests?", proc.stderr)
    return {"ran": int(m.group(1)) if m else 0, "ok": proc.returncode == 0,
            "tail": proc.stderr.strip().splitlines()[-3:], "skipped": None}


def run_smoke(mock: MockSource) -> dict:
    """F1 on every gate run: a planted dead wire_model must fail route.served; a live one and a discovered one must pass."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "co").mkdir()
        (root / "home").mkdir()
        (root / "co" / "routes.toml").write_text(SMOKE_ROUTES.format(base=mock.base_url), encoding="utf-8")
        paths = Paths(checkout=root / "co", state=root / "state", home=root / "home")
        run_sync(paths, timeout=5, env={})
        results = {f"{r.id}:{r.subject}": r.result for r in evaluate(build_context(paths), ids=["route.served"])}
    expected = {"route.served:mock/alive": "pass", "route.served:mock/dead": "fail", "route.served:mock/extra": "pass"}
    return {"ok": all(results.get(k) == v for k, v in expected.items()), "results": results, "expected": expected}


def run_gate(paths: Paths) -> dict:
    with MockSource(catalog=[omlx_entry("alive"), omlx_entry("extra")]) as mock:
        tests = run_unit_tests(paths.checkout)
        smoke = run_smoke(mock)
        mock_port = mock.port
    ctx = build_context(paths, with_claude_code=True)
    results = evaluate(ctx)
    failed = tests["ok"] is False or not smoke["ok"] or any(r.result == "fail" for r in results)
    record = {"at": utc_now(), "commit": describe_copy(paths)["commit"], "result": "fail" if failed else "pass",
              "tests": tests["ran"], "tests_ok": tests["ok"], "smoke_ok": smoke["ok"],
              "verifiers": {"declared": list(VERIFIERS), "ran": []},
              "invariants": {f"{r.id}:{r.subject}" if r.subject else r.id: r.result for r in results},
              "skipped": skipped_ids(results) + ([f"tests:{tests['skipped']}"] if tests["skipped"] else []),
              "skipped_reasons": [f"{r.id}{'[' + r.subject + ']' if r.subject else ''}: {r.reason}" for r in results if r.result == "skip"],
              "mock_port": mock_port}
    update_observed(paths, lambda d: d.__setitem__("last_gate_run", record))
    return {"command": "gate", "copy": describe_copy(paths), "tests": tests, "smoke": smoke,
            "invariants": [r.as_dict() for r in results], "last_gate_run": record, "result": record["result"]}
```

Append to `.github/workflows/ci.yml` (a new top-level job under `jobs:`; the existing jobs are untouched):

```yaml
  agent-on:
    # Plan A of docs/superpowers/specs/2026-09-07-agent-on-design.md: stdlib only, no LiteLLM, no Rust.
    # Sources are unreachable on CI; the gate reports those as listed skips, never as passes.
    runs-on: macos-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"

      - name: agent-on gate
        run: AGENT_ON_STATE="$RUNNER_TEMP/agent-on-state" ./bin/agent-on gate --json | tee gate.json

      - name: Assert the gate passed with its skips listed
        run: |
          python - <<'PY'
          import json
          g = json.load(open("gate.json"))
          assert g["result"] == "pass", g["last_gate_run"]
          assert g["tests"]["ok"] is True and g["tests"]["ran"] > 50, g["tests"]
          assert g["smoke"]["ok"] is True, g["smoke"]
          assert "credential.not_in_child_env" in g["last_gate_run"]["skipped"]
          PY
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`, then the real thing: `./bin/agent-on gate` on the checkout.
Expected: tests pass; the gate prints `tests: ran N — ok`, `smoke (F1 on the mock source): ok`, every invariant line with its result, and `result: pass` with the skips listed: `route.served:*` until `sync` has run, one `qualification.current:<route>` per route until Plan B's `qualify` runs, `credential.not_in_child_env`, `copy.single` because no shim exists yet, `knowledge.typed`, and on the very first run `gate.no_silent_skip` and `gate.mock.ephemeral` (no record yet). `harness.env.clean` must read `pass … model = 'fable' is a tier name` on this machine. If `test.names.derived` or `schema.complete` fail on the real tree, that is a defect in the tree: fix the literal or the rule, never the lint.

- [ ] **Step 5: Commit**

```bash
git add agent_on/gate.py tests/agent_on/test_gate.py .github/workflows/ci.yml
git commit -m "feat(agent-on): the gate — unit tests, F1 smoke on the mock source, every invariant, last_gate_run

ci: add the agent-on job (stdlib only; sources unreachable on CI are listed skips)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 11: `add <source>/<model> [--alias a]` — the only writer of `routes.toml` (rev-6 P2 lock)

**Files:**
- Create: `agent_on/add.py`
- Test: `tests/agent_on/test_add.py`

**Interfaces:**
- Consumes: `parse_routes_text`, `route_block`, `Limits`, `Price`, `Reasoning`, `Route`, `probe_source`, `checkout_locked`, `atomic_write`, `build_context`, `evaluate`, `Result`, `describe_copy`, `utc_now`
- Produces: `run_add(paths, name, *, alias=None, timeout=5.0) -> dict` with keys `command, copy, route, written (bool), block (when written), invariants[]`; `route_from_catalog(name, source, entry, aliases, today) -> Route`; test hook `HOLD_ENV = "AGENT_ON_TEST_HOLD_MS"` (sleep inside the lock after the re-read; test-only, documented in the module).

Rules (§9, §7.1): probe the source first — reachable and the model absent from its catalog → `route.served` **fail**, nothing written, exit 1 (a packaged route that is orphaned from birth is the F1 shape); unreachable → `skip` with a warning and the add proceeds (D6). For a source with an `auth_env` and a catalog entry with limits/prices (OpenRouter), fill `limits` (`provider`), `reasoning.supported`, `price` from the entry with today's date in each `source`; a keyless source's route inherits its source limits and gets no price. Then: take `<checkout>/.routes.lock`, **re-read** `routes.toml`, append the block to that fresh text, validate the merged text (every rule including `routes.unique`), temp+fsync+rename. The existing text and its comments are preserved verbatim.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_add.py`:

```python
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.add import HOLD_ENV, run_add  # noqa: E402
from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.paths import Paths  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

CATALOG = [omlx_entry("alpha"), omlx_entry("beta", 131072), openrouter_entry("vendor/model-y", 200000, 8000, "0.000001", "0.000002", None)]

ADD_SCRIPT = """
import sys; sys.path.insert(0, {repo!r})
from pathlib import Path
from agent_on.paths import Paths
from agent_on.add import run_add
p = Paths(checkout=Path({co!r}), state=Path({st!r}), home=Path({home!r}))
r = run_add(p, {name!r}, timeout=3)
raise SystemExit(0 if r["written"] else 1)
"""


class AddTest(unittest.TestCase):
    def test_add_appends_a_block_preserving_the_file_and_fills_from_the_catalog(self):
        with MockSource(catalog=CATALOG) as m, Sandbox("# keep this comment\n" + MOCK_ROUTES.format(base=m.base_url)) as sb:
            before = sb.paths.routes_toml.read_text(encoding="utf-8")
            r = run_add(sb.paths, "mock/beta", alias="b", timeout=3)
            self.assertTrue(r["written"])
            self.assertEqual([i["id"] for i in r["invariants"]], ["route.served", "route.unique"])
            self.assertEqual([i["result"] for i in r["invariants"]], ["pass", "pass"])
            after = sb.paths.routes_toml.read_text(encoding="utf-8")
            self.assertTrue(after.startswith(before.rstrip("\n")))             # nothing above the new block changed
            table = load_routes(sb.paths)
            self.assertIs(table.resolve("b"), table.routes["mock/beta"])
            self.assertIsNone(table.routes["mock/beta"].limits)                 # keyless source: inherits, no price
            self.assertEqual(table.effective_limits(table.routes["mock/beta"]).input, 8192)
            r = run_add(sb.paths, "paid/vendor/model-y", timeout=3)
            y = load_routes(sb.paths).routes["paid/vendor/model-y"]
            self.assertEqual((y.limits.input, y.limits.output, y.limits.confidence), (200000, 8000, "provider"))
            self.assertEqual((y.price.input, y.price.output, y.price.cache_read, y.price.cache_write), (1.0, 2.0, None, None))
            self.assertTrue(y.reasoning.supported)
            self.assertEqual((y.reasoning.confidence, y.reasoning.efforts), ("provider", ()))
            self.assertIn("paid.pricing", y.price.source)
            self.assertEqual(list(sb.paths.checkout.glob("routes.toml.tmp.*")), [])

    def test_unserved_model_is_refused_and_unreachable_source_proceeds_with_a_skip(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            r = run_add(sb.paths, "mock/nope", timeout=3)
            self.assertFalse(r["written"])
            self.assertEqual(r["invariants"][0]["result"], "fail")
            self.assertNotIn("mock/nope", sb.paths.routes_toml.read_text())
        with Sandbox(MOCK_ROUTES.format(base="http://127.0.0.1:9")) as sb:
            r = run_add(sb.paths, "mock/blind", timeout=1)
            self.assertTrue(r["written"])
            self.assertEqual(r["invariants"][0]["result"], "skip")

    def test_duplicates_and_bad_names_are_schema_errors_and_write_nothing(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            before = sb.paths.routes_toml.read_text()
            with self.assertRaises(SchemaError) as cm:
                run_add(sb.paths, "mock/beta", alias="a", timeout=3)            # alias "a" already on mock/alpha
            self.assertEqual(cm.exception.rule, "routes.unique")
            with self.assertRaises(SchemaError):
                run_add(sb.paths, "nosuch/model", timeout=3)
            with self.assertRaises(SchemaError):
                run_add(sb.paths, "mock/alpha", timeout=3)                      # already packaged
            self.assertEqual(sb.paths.routes_toml.read_text(), before)

    def test_two_adds_under_different_state_roots_both_survive(self):
        # rev-6 P2: the writer lock is keyed by the checkout, so a scratch AGENT_ON_STATE run serialises with the default one.
        # Process A holds the lock ~600 ms after its re-read; B starts 150 ms later and must wait, then re-read A's result.
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            other_state = sb.root / "scratch-state"
            script = lambda st, name: ADD_SCRIPT.format(repo=str(REPO), co=str(sb.paths.checkout), st=str(st), home=str(sb.paths.home), name=name)
            a = subprocess.Popen([sys.executable, "-c", script(sb.paths.state, "mock/beta")], env={**os.environ, HOLD_ENV: "600"})
            time.sleep(0.15)
            b = subprocess.Popen([sys.executable, "-c", script(other_state, "paid/vendor/model-y")], env={**os.environ, HOLD_ENV: "0"})
            self.assertEqual((a.wait(), b.wait()), (0, 0))
            table = load_routes(sb.paths)
            self.assertIn("mock/beta", table.routes)
            self.assertIn("paid/vendor/model-y", table.routes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_add.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.add'`

- [ ] **Step 3: Write the module**

`agent_on/add.py`:

```python
"""`agent-on add <source>/<model> [--alias a]` (§9): declare a packaged route by appending one block to routes.toml
under the checkout lock (§7.1, rev 6): lock, re-read, validate the merged text, temp+fsync+rename."""
from __future__ import annotations

import os
import time

from .invariants import Result, build_context, evaluate
from .paths import Paths, describe_copy
from .schemas.errors import SchemaError
from .schemas.routes import Limits, Price, Reasoning, Route, Source, parse_routes_text, route_block
from .sources import Probe, probe_source
from .state import atomic_write, checkout_locked
from .util import utc_now

HOLD_ENV = "AGENT_ON_TEST_HOLD_MS"   # test hook: sleep this long inside the lock after the re-read, to make the lock observable


def route_from_catalog(name: str, source: Source, entry: dict | None, aliases: tuple[str, ...], today: str) -> Route:
    """Limits, reasoning and price from a catalog entry that publishes them (OpenRouter today), with `provider`
    confidence and the date; a keyless source's route inherits its source limits and carries no price."""
    src, _, model = name.partition("/")
    limits = reasoning = price = None
    if entry and source.auth_env:
        if entry.get("max_input") or entry.get("max_output"):
            limits = Limits(entry.get("max_input"), entry.get("max_output"), "provider",
                            f"{src}.top_provider.context_length / max_completion_tokens ({today})")
        pricing = entry.get("pricing") or {}
        if pricing.get("prompt") is not None and pricing.get("completion") is not None:
            def per_mtok(v):
                return None if v is None else round(float(v) * 1_000_000, 6)
            price = Price(per_mtok(pricing["prompt"]), per_mtok(pricing["completion"]), per_mtok(pricing.get("input_cache_read")),
                          per_mtok(pricing.get("input_cache_write")),
                          f"{src}.pricing ({today})" + ("" if pricing.get("input_cache_write") is not None else "; no cache-write price published"))
        params = entry.get("supported_parameters")
        if params is not None:
            reasoning_params = [p for p in params if p in ("reasoning", "reasoning_effort")]
            reasoning = Reasoning(bool(reasoning_params), (), (), "provider",
                                  f"{src}.supported_parameters: {', '.join(reasoning_params) or 'none'} ({today})")
    return Route(name, src, model, aliases, limits, reasoning, price, packaged=True)


def run_add(paths: Paths, name: str, *, alias: str | None = None, timeout: float = 5.0) -> dict:
    srcs, packaged, _ = parse_routes_text(paths.routes_toml.read_text(encoding="utf-8"), packaged=True)
    src_name, _, model = name.partition("/")
    if src_name not in srcs or not model:
        raise SchemaError("routes.route.name", f"{name!r} must be <source>/<model> with a declared source (sources: {sorted(srcs)})")
    if name in packaged:
        raise SchemaError("routes.unique", f"{name!r} is already packaged")
    source = srcs[src_name]
    probe: Probe = probe_source(source, timeout)
    if not probe.reachable:
        served = Result("route.served", "skip", f"{src_name} unreachable ({probe.error}); adding unverified — run `agent-on sync` later", name)
    elif model in probe.catalog:
        served = Result("route.served", "pass", f"{model!r} is in the {src_name} catalog", name)
    else:
        served = Result("route.served", "fail", f"{model!r} not in the {src_name} catalog ({probe.catalog_count} ids)", name,
                        "check the id against `agent-on sync` / the source's catalog; nothing was written")
    if served.result == "fail":
        return {"command": "add", "copy": describe_copy(paths), "route": name, "written": False, "invariants": [served.as_dict()]}
    route = route_from_catalog(name, source, probe.catalog.get(model), (alias,) if alias else (), utc_now()[:10])
    block = route_block(route)
    with checkout_locked(paths):
        current = paths.routes_toml.read_text(encoding="utf-8")   # re-read under the lock: another add may have landed
        hold = float(os.environ.get(HOLD_ENV, "0"))
        if hold:
            time.sleep(hold / 1000)
        candidate = current.rstrip("\n") + "\n\n" + block
        parse_routes_text(candidate, packaged=True)                # every rule, including routes.unique, on the merged text
        atomic_write(paths.routes_toml, candidate)
    unique = [r.as_dict() for r in evaluate(build_context(paths), ids=["route.unique"])]
    return {"command": "add", "copy": describe_copy(paths), "route": name, "written": True, "block": block,
            "invariants": [served.as_dict()] + unique}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests/agent_on -p 'test_*.py' -v`
Expected: all pass. The concurrent test proves the rev-6 lock: with the lock keyed under `$STATE` instead, process B would read the pre-A file during A's hold and its rename would discard A's block.

- [ ] **Step 5: Commit**

```bash
git add agent_on/add.py tests/agent_on/test_add.py
git commit -m "feat(agent-on): add — the only writer of routes.toml, under the checkout-keyed lock (§7.1 rev 6)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

---

### Task 12: Acceptance on the real machine, README, and the Plan A record

**Files:**
- Modify: `README.md` (append one section)
- No code changes unless acceptance finds a defect (fix it in the same task, with a test).

This task runs §14's Plan A verification column against the real sources and records what was measured. Every step is a command; write its observed output into the commit message of the final commit (numbers, not adjectives).

- [ ] **Step 1: Put the OpenRouter key where `sync` looks**

The key lives in Keychain today (`security find-generic-password -s openrouter-api-key -a "$USER" -w`); `agent-on` reads only the environment or `$STATE/env` (§9). Create the env file once, 0600, without echoing the key:

```bash
mkdir -p ~/.local/state/agent-on && chmod 700 ~/.local/state/agent-on
umask 077 && printf 'OPENROUTER_API_KEY=%s\n' "$(security find-generic-password -s openrouter-api-key -a "$USER" -w)" > ~/.local/state/agent-on/env
ls -l ~/.local/state/agent-on/env    # -rw-------
```

- [ ] **Step 2: `sync` against the real sources**

```bash
./bin/agent-on sync
./bin/agent-on sync --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print({k:(v["reachable"], v["error"]) for k,v in d["sources"].items()}); print("orphans", d["orphans"]); print("spend", d["spend"]["openrouter"])'
```

Expected on 2026-09-07: `openrouter` reachable (catalog ~430), `omlx` reachable (12 ids), `omlx@morty` / `omlx-tp2` / `exo` unreachable with their errors; `orphans == []` (both oMLX wire models are served); `spend.openrouter.usd_used` a number and `error: None` — **this is Q6 answered for the first time**; ~10 discovered `omlx/*` routes in `~/.local/state/agent-on/routes.discovered.toml`; `git status --porcelain` shows no tracked file changed by `sync`.

- [ ] **Step 3: `status --check` and the declared-vs-observed reading**

```bash
./bin/agent-on status --check
./bin/agent-on status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(n, v["declared"]["limits"]["input"], v["observed"]["limits"]["input"], v["observed"]["cost_model"]["context"], v["observed"]["cost_model"]["context_basis"]) for n,v in d["routes"].items()]'
```

Expected: `limits.declared_vs_observed` **pass** for all four OpenRouter routes (the seed carries the live figures — if any fails, the catalog moved since 2026-09-07: re-derive the number, do not loosen the check); for the oMLX routes: declared 131072 (configured) vs advertised 262144 → context 131072, basis `declared`; `harness.env.clean` pass with the `model = 'fable'` tier-name note; `copy.single` skip (no shim until Plan D); `credential.not_in_child_env` skip; `route.served` pass for the six packaged routes and the discovered ones, skip for the three unreachable sources' routes (none exist yet); `last_check` written, `last_gate_run` untouched.

- [ ] **Step 4: Plant F1 and watch it fail, then restore**

```bash
cp routes.toml /tmp/routes.toml.bak
sed -i '' 's/^wire_model = "Qwen3.8-27B-Uncensored-8bit"$/wire_model = "Qwen3.8-27B-Uncensored-8bit-RENAMED"/' routes.toml
./bin/agent-on sync | grep -i orphan
./bin/agent-on status --check | grep 'route.served'
cp /tmp/routes.toml.bak routes.toml && ./bin/agent-on sync >/dev/null && git diff --stat routes.toml
```

Expected: `orphaned packaged: ['omlx/Qwen3.8-27B-Uncensored-8bit']`, `fail route.served[omlx/Qwen3.8-27B-Uncensored-8bit]: 'Qwen3.8-27B-Uncensored-8bit-RENAMED' not in omlx catalog`, exit 1 from `status --check`; after restore, no diff. This is the check that would have caught F1 the day it happened.

- [ ] **Step 5: The gate, twice**

```bash
./bin/agent-on gate; echo "exit $?"
./bin/agent-on gate --json | python3 -c 'import json,sys; g=json.load(sys.stdin); print(g["result"], g["tests"], g["last_gate_run"]["skipped"], g["last_gate_run"]["mock_port"])'
```

Expected: `result: pass`, exit 0; tests ran ≥ 60 and ok; the second run's `gate.no_silent_skip` and `gate.mock.ephemeral` pass against the first run's record; skips listed are `credential.not_in_child_env`, `copy.single`, `knowledge.typed`, one `qualification.current:<route>` per route (sixteen on 2026-09-07: six packaged, ten discovered — until Plan B's `qualify` runs), `route.served:*` only for routes on unreachable sources (none yet), and never a `tests:` entry on an outer run.

- [ ] **Step 6: `add` a real OpenRouter route and revert it**

```bash
./bin/agent-on add openrouter/anthropic/claude-haiku-4.5 --alias haiku45; echo "exit $?"
git diff routes.toml | head -40
./bin/agent-on add openrouter/anthropic/claude-haiku-4.5; echo "exit $?"    # duplicate → exit 3, schema routes.unique
./bin/agent-on add openrouter/does/not-exist; echo "exit $?"                # exit 1, route.served fail, nothing written
git checkout routes.toml
```

Expected: the first add appends a block with `provider` limits and the catalog's prices (input/output/cache_read; `cache_write` present only if OpenRouter publishes `input_cache_write` for it), `route.served pass`, `route.unique pass`, exit 0; the duplicate is exit 3; the unknown id is exit 1 with the catalog count in the reason. `git checkout` restores the seed.

- [ ] **Step 7: The old path still works**

```bash
claude-litellm status 2>&1 | head -5
./scripts/check.zsh 2>&1 | tail -3     # stop the :4000 proxy first if it is running (port 4000 is not isolated)
```

Expected: the old CLI answers as before; the old gate exits 0 — it discovers only `tests/test_*.py` (no `__init__.py` under `tests/agent_on/`), so nothing new runs under it.

- [ ] **Step 8: README section**

Append to `README.md`:

```markdown
## agent-on (Plan A — additive preview)

`bin/agent-on` is the successor CLI designed in `docs/superpowers/specs/2026-09-07-agent-on-design.md`. Plan A lands
`status`, `sync`, `add` and `gate` beside `claude-litellm`; it reads `routes.toml` (the only route declarations),
writes only `${XDG_STATE_HOME:-~/.local/state}/agent-on/` (override with `AGENT_ON_STATE=<dir>` for a scratch run),
and needs nothing but `python3 ≥ 3.11`. Secrets come from the environment or a 0600 `$STATE/env` file.

    ./bin/agent-on sync            # probe every source; served flags, limit tiers, spend → observed.json
    ./bin/agent-on status --check  # declared beside observed; every invariant, with skips shown as skips
    ./bin/agent-on gate            # unit tests + F1 smoke on a mock source + every invariant
    ./bin/agent-on add openrouter/<vendor>/<model> --alias <a>

Nothing is launched yet (Plan B); the old `claude-litellm` path is untouched until Plan D.
```

- [ ] **Step 9: Final commit with the measurements**

```bash
git add README.md
git commit -m "docs: agent-on Plan A acceptance — measured on 2026-09-07

sync: openrouter reachable (catalog <N>), omlx reachable (<N> ids), omlx@morty /
omlx-tp2 / exo unreachable (<errors>); 0 orphans; <N> discovered omlx routes;
spend.openrouter usd_used <x> limit <y>/<period> remaining <z> (Q6 answered).
status --check: <pass/fail counts>, skips <list>.
F1 planted: route.served failed as expected; restored.
gate: pass, <N> tests, mock port <p>; second run passed gate.* predicates.
add: real OpenRouter route appended and reverted; duplicate exit 3; unknown id exit 1.
old path: claude-litellm status and check.zsh unaffected.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

Replace every `<…>` with the observed value before committing. If any step's expectation did not hold, the fix and its test go in this task's commit series, and the deviation is stated in the message.

---

## Self-review (run by the plan's author before handing off)

**Spec coverage — §14 row A, with the rev-6 additions:**

| requirement | task |
|---|---|
| `agent_on/` package, stdlib only, `python3 ≥ 3.11` shim ≤ 20 lines (D4, D9) | 1 |
| `routes.toml` + schema; rules stated once; TOML only (D4, D5, §6) | 2 |
| read-time dedup, packaged wins by `(source, wire_model)`; orphaned reported never deleted (§6) | 2, 8 |
| source limits inherited by any route declaring none (§6 rev 6) | 2, 7 |
| `observed.json` shape; null for unmeasured; three-valued caching; F11 rejected (§7) | 3 |
| `compute_context` = min(declared, verified) else min(declared, configured, advertised); tie → declared (§7) | 3, 8 |
| `spend.openrouter` from `/v1/auth/key`, five fields (§7 rev 6) | 6, 8, 12 |
| storage rules: observed lock, re-read, temp+rename, `.tmp.*` sweep; discovered under the same lock; checkout lock `<checkout>/.routes.lock` (§7.1 rev 6); O_APPEND ledgers | 5, 11 |
| §11 cost attribution per run, price snapshot, `unknown` rule, session fold (rev 6) | 4 (functions + tests); the launch that feeds them is Plan B |
| fourteen invariants with stable ids, statement, fix, pass/fail/skip; skip never a pass (§8) | 7 |
| reproduction for every F1–F14 except F3 (no quoted battery exists) and F11 (unit test) | 7 (F1, F2/F12, F4, F5 — code only; docs join in Plan D — F6, F7/F8, F9, F10, F13, F14), 3 (F11) |
| `harness.env.clean` broad denylist with the tier-name exception (§8 rev 6) | 7 |
| `status` declared beside observed; an unscoped `--check` writes `last_check` only, a scoped one is never persisted (§9, Q4) | 9 |
| `sync` refreshes served/configured/advertised/spend, never `verified`, never touches `routes.toml` (§9); an unreachable source keeps no stale catalog or identity (R1) | 8 |
| `add` fills from the catalog with `provider` confidence, never `verified`; refuses an unserved model (§6, §9) | 11 |
| gate: unit tests + mock source on an ephemeral port + every invariant → `last_gate_run` (§8) | 10 |
| every command `--json`, prints `copy.*`, names its invariants (§2, §9) | 1, 8, 9, 10, 11 |
| runs beside `claude-litellm`, deletes nothing; old gate unaffected | 1 (no `__init__.py`), 12 |
| §14 verify column: routes minus OAuth/xAI; planted dead wire_model fails; deliberate skip prints skip; spend exercised; concurrent adds survive; paid-then-free fold | 2, 12, 7/10, 12, 11, 4 |

Not in Plan A, by design: `knowledge/gate-runs.jsonl` (Plan C writes the durable twin of `last_gate_run`); `learn`; the launch, credential flow, read-back and `qualify` (Plan B); `install` (Plan D); `omlx-tp2` and `omlx@morty` measurement (S4, S5).

**Placeholder scan:** no TBD/TODO; every code step carries the code; the only `<…>` tokens are in Task 12's commit-message template and are explicitly to be replaced with measured values.

**Type consistency:** `parse_routes_text` returns a 3-tuple everywhere it is called (Tasks 2, 8, 11); `Result.as_dict()` is what every command puts under `invariants`; `evaluate(ctx, ids=…, route=…)` signature is identical in Tasks 7–11; Task 7 (invariants) depends on nothing from Task 8 (sync) — its tests plant the records `sync` would write; `Paths(checkout, state, home, tree)` and `Sandbox(routes_text, tree=REPO)` match; `MockSource(catalog, spend, expect_key)` and its `/v1/auth/key` + `/api/v1/auth/key` paths match `fetch_openrouter_spend`'s `<base>/v1/auth/key`; `compute_context(declared, tier)` is called with the observed `limits["input"]` dict in Task 8; the gate's `last_gate_run` record carries exactly the keys `observed.GATE_RUN_KEYS` requires (plus `tests_ok`, `smoke_ok`, which the schema tolerates).
