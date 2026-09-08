# agent-on Plan D — Install as shims, docs from `routes.toml`, delete the old path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the checkout the installation (`agent-on install` links two shims and creates the state root), generate the route documentation from `routes.toml`, carry the last facts out of the old path into `knowledge/`, and delete everything the old `claude-litellm` gateway was — LiteLLM runtime, OAuth lanes, callbacks, integrity chain, zsh libraries, the old gate, its tests and docs — in one plan, so that a fresh clone plus `install` launches every reachable route with standard-library Python only.

**Architecture:** One new command (`install`, `agent_on/install.py`) and one renderer (`agent_on/docs.py`, run by `scripts/routes-doc.py` and checked by a new tree-lint invariant `docs.current`) are the only additions. The rest is subtraction: the old path is removed with `git rm`, the CI keeps the one job that exercises the tower and gains an install step, the README is rewritten for `agent-on` with a one-time upgrade note (D1: no compatibility shim). Facts that only lived in the deleted files land in `knowledge/` first (six observations from `context-observations.json`, two decisions), so nothing measured is lost. The rename of the directory and the GitHub repository is the owner's step after merge (outside the worktree) and is written down, not automated.

**Tech Stack:** Python ≥ 3.11 standard library only; zsh shims (≤ 20 lines); GitHub Actions (macOS runner).

**Spec:** `docs/superpowers/specs/2026-09-07-agent-on-design.md` (rev 8) — §9 `install` row, §13 (deletion ledger and size target), §14 row D, §15 (Q2/Q7/Q9 moot), §17, D1, D4, D9. Plans A–C are landed context; their ledgers hold inherited rulings.

## Global Constraints

- **D4** One package `agent_on/`, Python ≥ 3.11 from `PATH`, standard library only; zsh survives only as the two ≤ 20-line shims in `bin/`.
- **D9** No installed copy: `install` links `~/.local/bin/agent-on` and `~/.local/bin/claude-on` to `<checkout>/bin/`, creates the state directory, checks the interpreter; drift detection is `git status --porcelain` plus "does the shim point here" (`copy.single`). No fingerprint, digest or symlink walk.
- **D1** Rename to `agent-on`: no compatibility shim beyond a one-time `mv` note. `bin/claude-litellm` is deleted, not aliased.
- **§14 row D** deletes: LiteLLM runtime, venv, requirements lock, OAuth code and routes, integrity chain, `lib.zsh`, `shell.zsh`, `check.zsh`, `harnesses/`, the budget/overlay/permission/callback layers, the context/reasoning ledgers, `model-qualifications.json`, all vestigial. Acceptance: a fresh clone + `install` launches every reachable route with stdlib Python only; **no hit for `litellm` under `agent_on/`, `bin/`, `routes.toml`, `tests/`**; Q2/Q7/Q9 moot and the peer check re-run; the line count recorded; gate green.
- **§13 size gate** is measured as `git ls-files | xargs wc -l`; the plan records the number as an observation and states plainly whether the 6,000 gate holds (see Self-review: it does not, because of test volume — the owner decides).
- **§10** `knowledge/` is append-only; deleted files' facts are appended before the files go. Records use stable human ids like the Plan C seeds.
- **Plan B/C rulings that bind:** tests use only `tests/agent_on/helpers.Sandbox`, `MockSource`, `fakeclaude.py` — never the real home, state, oMLX or `claude`; secrets never reach stdout/JSON/knowledge; every verb answers `--json`; JSON envelopes only gain keys; `observed.json` only via `update_observed`; do not run `gate`/`qualify`/`claude-on`/`learn` against the real checkout from a task (they append to the real `knowledge/`) except in the acceptance task.
- **Commit trailers** on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD
  ```

---

## File structure

| path | responsibility |
|---|---|
| `agent_on/install.py` | **new** — `run_install(paths, *, bin_dir=None, dry_run=False) -> dict` |
| `agent_on/docs.py` | **new** — `render_routes_doc(table) -> str` (pure; L1 only) |
| `scripts/routes-doc.py` | **new** — writes/checks `docs/ROUTES.md` from the renderer (the only file left in `scripts/`) |
| `agent_on/invariants.py` | `copy.single` skip text; new `docs.current` tree lint |
| `agent_on/cli.py` | `install [--bin-dir DIR] [--dry-run]` verb + renderer |
| `agent_on/paths.py` | `Paths.bin_dir` (`home/.local/bin`), `Paths.shim_for(name)` |
| `docs/ROUTES.md` | generated |
| `knowledge/observations.jsonl`, `knowledge/decisions.jsonl` | six migrated observations, two decisions (appended) |
| deleted | `config/` (all), `scripts/` (all old), `tests/*.py` (top level), `bin/claude-litellm`, `docs/ARCHITECTURE.md`, `docs/MODEL-RUNBOOK.md`, `docs/PROVIDERS.md`, `docs/MIGRATION.md` |
| `.github/workflows/ci.yml` | one job: gate + install + dry-run launches |
| `README.md` | rewritten for agent-on; "Upgrading from claude-litellm" note |
| `.gitignore`, `routes.toml` (header comment), `agent_on/harness.py:34`, `agent_on/qualify.py:3`, `tests/agent_on/test_paths.py:84` | wording that named the old path |
| tests | `tests/agent_on/test_install.py`, `test_docs_render.py`, `test_docs_plan_d.py`; edits in `test_invariants.py`, `test_status.py`, `test_knowledge_seeds.py` |

---

### Task 1: `agent-on install`

**Files:**
- Create: `agent_on/install.py`
- Modify: `agent_on/paths.py`, `agent_on/cli.py`, `agent_on/invariants.py` (`copy.single` skip text)
- Test: `tests/agent_on/test_install.py`; one edit in `tests/agent_on/test_invariants.py` (the skip reason string) and `tests/agent_on/test_status.py` if it asserts the reason text

**Interfaces:**
- Consumes: `paths.ensure_state`, `paths.describe_copy`, `invariants.{build_context, evaluate}`.
- Produces: `Paths.bin_dir -> Path` (`home / ".local" / "bin"`), `Paths.shim_for(name) -> Path` (`bin_dir / name`; `Paths.shim` stays `shim_for("agent-on")`). `run_install(paths, *, bin_dir: Path | None = None, dry_run: bool = False) -> dict` with keys `command: "install"`, `copy`, `python: {"executable", "version", "ok": bool}`, `state_root: str`, `bin_dir: str`, `links: {name: {"path", "target", "state": "linked"|"replaced"|"unchanged"|"refused"|"dry-run", "reason": str|None}}`, `on_path: bool`, `warnings: [..]`, `written: bool` (every link linked/replaced/unchanged), `invariants: [copy.single]`. Rules: Python < 3.11 → `python.ok False`, nothing linked, `written False`; an existing symlink is replaced atomically (`os.symlink` to `<path>.tmp-<pid>` then `os.replace`); an existing non-symlink is **refused** (state `refused`, reason names it) — the operator deletes it; the link target is the absolute `<checkout>/bin/<name>`; `bin_dir` is created with `parents=True`; `on_path` is whether `bin_dir` (resolved) is in `PATH`, and a warning names the `export PATH=` line when it is not; dry run reports states as `dry-run` and touches nothing (not even the state root). `copy.single` is evaluated after linking (with `tree` = the checkout). Exit code: 0 when `written`, 1 otherwise.

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_install.py`:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.install import run_install  # noqa: E402
from agent_on.paths import describe_copy  # noqa: E402

BASE = "http://127.0.0.1:1"


class InstallTest(unittest.TestCase):
    def test_install_links_both_shims_creates_the_state_root_and_copy_single_passes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            self.assertFalse(sb.paths.state.exists())
            doc = run_install(sb.paths)
            self.assertTrue(doc["written"], doc)
            for name in ("agent-on", "claude-on"):
                link = sb.paths.home / ".local" / "bin" / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), str((REPO / "bin" / name).resolve()))
                self.assertEqual(doc["links"][name]["state"], "linked")
            self.assertTrue(sb.paths.state.is_dir())
            self.assertTrue(doc["python"]["ok"])
            self.assertEqual([i["result"] for i in doc["invariants"] if i["id"] == "copy.single"], ["pass"])
            self.assertIn("~/.local/bin", describe_copy(sb.paths)["shim"].replace(str(sb.paths.home), "~"))
            again = run_install(sb.paths)
            self.assertEqual({v["state"] for v in again["links"].values()}, {"unchanged"})

    def test_a_stale_symlink_is_replaced_and_a_regular_file_is_refused(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            bd = sb.paths.home / ".local" / "bin"
            bd.mkdir(parents=True)
            (bd / "agent-on").symlink_to("/nonexistent/agent-on")
            (bd / "claude-on").write_text("#!/bin/sh\n", encoding="utf-8")
            doc = run_install(sb.paths)
            self.assertFalse(doc["written"])
            self.assertEqual(doc["links"]["agent-on"]["state"], "replaced")
            self.assertEqual(os.readlink(bd / "agent-on"), str((REPO / "bin" / "agent-on").resolve()))
            self.assertEqual(doc["links"]["claude-on"]["state"], "refused")
            self.assertIn("not a symlink", doc["links"]["claude-on"]["reason"])
            self.assertEqual((bd / "claude-on").read_text(encoding="utf-8"), "#!/bin/sh\n")            # untouched

    def test_dry_run_touches_nothing_and_a_custom_bin_dir_is_honoured(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            bd = sb.root / "elsewhere" / "bin"
            doc = run_install(sb.paths, bin_dir=bd, dry_run=True)
            self.assertEqual({v["state"] for v in doc["links"].values()}, {"dry-run"})
            self.assertFalse(bd.exists())
            self.assertFalse(sb.paths.state.exists())
            doc = run_install(sb.paths, bin_dir=bd)
            self.assertTrue((bd / "claude-on").is_symlink())
            self.assertFalse(doc["on_path"])
            self.assertTrue(any("PATH" in w for w in doc["warnings"]))

    def test_old_python_links_nothing(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            with mock.patch("agent_on.install.sys.version_info", (3, 10, 0)):
                doc = run_install(sb.paths)
            self.assertFalse(doc["python"]["ok"])
            self.assertFalse(doc["written"])
            self.assertFalse((sb.paths.home / ".local" / "bin").exists())


if __name__ == "__main__":
    unittest.main()
```

Edit `tests/agent_on/test_invariants.py` line ~108 (`copy.single` skip) if it asserts the reason text "install lands in Plan D": the new reason is `no shim at <path> — run agent-on install`; `tests/agent_on/test_status.py:59` asserts only membership in `skipped` and needs no change.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_install.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.install'`.

- [ ] **Step 3: Write the code**

`agent_on/paths.py` — replace the `shim` property with:

```python
    @property
    def bin_dir(self) -> Path:
        return self.home / ".local" / "bin"

    def shim_for(self, name: str) -> Path:
        return self.bin_dir / name

    @property
    def shim(self) -> Path:
        return self.shim_for("agent-on")
```

`agent_on/install.py`:

```python
"""`agent-on install` (§9, D9): the checkout is the installation. Link the two shims into ~/.local/bin, create the
state root, check the interpreter, report copy.*. Nothing is copied, hashed or pinned — drift is `git status` plus
"does the shim point here" (copy.single)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .invariants import build_context, evaluate
from .paths import Paths, describe_copy, ensure_state

SHIMS = ("agent-on", "claude-on")
MIN_PYTHON = (3, 11)


def _link(path: Path, target: Path, *, dry_run: bool) -> tuple[str, str | None]:
    if path.is_symlink():
        if os.readlink(path) == str(target):
            return "unchanged", None
        if dry_run:
            return "dry-run", f"would replace symlink -> {os.readlink(path)}"
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        os.symlink(target, tmp)
        os.replace(tmp, path)                                   # atomic: a shell mid-exec sees the old or the new link
        return "replaced", None
    if path.exists():
        return "refused", f"{path} exists and is not a symlink — remove it yourself, then re-run install"
    if dry_run:
        return "dry-run", None
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)
    return "linked", None


def run_install(paths: Paths, *, bin_dir: Path | None = None, dry_run: bool = False) -> dict:
    bd = Path(bin_dir) if bin_dir else paths.bin_dir
    v = sys.version_info
    py_ok = tuple(v[:2]) >= MIN_PYTHON
    doc: dict = {"command": "install", "copy": describe_copy(paths),
                 "python": {"executable": sys.executable, "version": f"{v[0]}.{v[1]}.{v[2]}", "ok": py_ok},
                 "state_root": str(paths.state), "bin_dir": str(bd), "links": {}, "warnings": [], "written": False}
    if not py_ok:
        doc["warnings"].append(f"python3 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} required; {sys.executable} is {doc['python']['version']} — set AGENT_ON_PYTHON")
        doc["invariants"] = []
        return doc
    if not dry_run:
        ensure_state(paths)
    for name in SHIMS:
        target = (paths.checkout / "bin" / name).resolve()
        state, reason = _link(bd / name, target, dry_run=dry_run)
        doc["links"][name] = {"path": str(bd / name), "target": str(target), "state": state, "reason": reason}
    on_path = str(bd.resolve()) in [str(Path(p).resolve()) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    doc["on_path"] = on_path
    if not on_path:
        doc["warnings"].append(f'{bd} is not on PATH — add: export PATH="{bd}:$PATH"')
    doc["written"] = all(l["state"] in ("linked", "replaced", "unchanged") for l in doc["links"].values())
    doc["copy"] = describe_copy(paths)                          # after linking: copy.shim shows the link
    doc["invariants"] = [] if dry_run else [r.as_dict() for r in evaluate(build_context(paths), ids=["copy.single"])]
    return doc
```

Note `copy.single` compares the shim at `paths.shim` (`home/.local/bin/agent-on`); with a custom `bin_dir` it will report the default location — that is correct (the invariant asks about the canonical shim) and the test with a custom dir does not assert on it.

`agent_on/invariants.py` `copy_single`: change the skip text to `f"no shim at {shim} — run agent-on install"` and the `fix` to `"agent-on install"`.

`agent_on/cli.py`: parser

```python
    i = sub.add_parser("install", parents=[common], help="link ~/.local/bin/agent-on and claude-on to this checkout, create the state root, check python3 (D9)")
    i.add_argument("--bin-dir", metavar="DIR", help="where to put the shims (default ~/.local/bin)")
    i.add_argument("--dry-run", action="store_true")
```

renderer

```python
def render_install(doc: dict) -> str:
    lines = [copy_line(doc["copy"]), f"python: {doc['python']['executable']} {doc['python']['version']} {'ok' if doc['python']['ok'] else 'TOO OLD'}",
             f"state root: {doc['state_root']}"]
    for n, l in doc["links"].items():
        lines.append(f"  {l['state']:9} {l['path']} -> {l['target']}" + (f"  ({l['reason']})" if l["reason"] else ""))
    lines += [f"warning: {w}" for w in doc["warnings"]]
    return "\n".join(lines + invariant_lines(doc["invariants"]))
```

and the `main` branch: `from .install import run_install; doc = run_install(paths, bin_dir=Path(args.bin_dir) if args.bin_dir else None, dry_run=args.dry_run); code = EXIT_OK if doc["written"] or args.dry_run else EXIT_FAIL; text = render_install(doc)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass (204 + 4).

- [ ] **Step 5: Commit**

```bash
git add agent_on/install.py agent_on/paths.py agent_on/cli.py agent_on/invariants.py tests/agent_on/test_install.py tests/agent_on/test_invariants.py
git commit -m "feat(agent-on): install — link the two shims into ~/.local/bin, create the state root, check python3 (D9)"
```

---

### Task 2: `docs/ROUTES.md` generated from `routes.toml`, checked by `docs.current`

**Files:**
- Create: `agent_on/docs.py`, `scripts/routes-doc.py`, `docs/ROUTES.md` (generated)
- Modify: `agent_on/invariants.py` (new invariant), `tests/agent_on/test_invariants.py` (`EXPECTED_IDS`)
- Test: `tests/agent_on/test_docs_render.py`

**Interfaces:**
- Consumes: `schemas.routes.{load_routes, RouteTable}`.
- Produces: `docs.render_routes_doc(table: RouteTable) -> str` — deterministic Markdown from L1 only (no observed values, so the page is a pure function of `routes.toml`): a header line naming the generator, one `## Sources` table (name, base_url, auth_env or "none", catalog or "—", discover, source limits `input/output (confidence)` or "—"), one `## Routes` table per source (route name, aliases, wire model, effective input/output limit with confidence and where it came from — route or source, price per Mtok in/out or "free", reasoning `supported`/efforts or "—", packaged or discovered). `scripts/routes-doc.py [--check]`: writes `docs/ROUTES.md` from the checkout's `routes.toml`; with `--check` exits 1 and prints a diff summary when the committed file differs. Invariant `docs.current` (tree lint, per tree): `skip` when `<tree>/docs/ROUTES.md` is absent; `fail("docs/ROUTES.md is stale — run scripts/routes-doc.py")` when `render_routes_doc(load_routes(Paths(checkout=tree, …)))` differs from the file; `ok` otherwise. It renders from the **tree's** `routes.toml`, not the context's routes (a sandbox lints the real tree).

- [ ] **Step 1: Write the failing tests**

`tests/agent_on/test_docs_render.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.docs import render_routes_doc  # noqa: E402
from agent_on.invariants import build_context, evaluate  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

BASE = "http://127.0.0.1:1"


def one(paths, ident):
    return next(r for r in evaluate(build_context(paths), ids=[ident]))


class RenderTest(unittest.TestCase):
    def test_render_is_deterministic_and_names_every_source_and_route(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            table = load_routes(sb.paths)
            text = render_routes_doc(table)
            self.assertEqual(text, render_routes_doc(table))
            self.assertTrue(text.startswith("<!-- generated by scripts/routes-doc.py from routes.toml — do not edit -->\n# Routes\n"))
            for s in table.sources:
                self.assertIn(f"### {s}", text)
            for r in table.routes.values():
                self.assertIn(f"`{r.name}`", text)
                for a in r.aliases:
                    self.assertIn(f"`{a}`", text)
            self.assertIn("| free |", text)                                              # a keyless source's routes are free

    def test_the_real_page_is_current_and_the_invariant_sees_staleness(self):
        real = (REPO / "docs" / "ROUTES.md").read_text(encoding="utf-8")
        self.assertEqual(real, render_routes_doc(load_routes(__import__("agent_on.paths", fromlist=["default_paths"]).default_paths({"HOME": str(REPO), "AGENT_ON_CHECKOUT": str(REPO)}))))
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            self.assertEqual(one(sb.paths, "docs.current").result, "skip")                  # no page in the sandbox tree
            (sb.paths.checkout / "docs").mkdir()
            (sb.paths.checkout / "docs" / "ROUTES.md").write_text("stale\n", encoding="utf-8")
            r = one(sb.paths, "docs.current")
            self.assertEqual(r.result, "fail")
            self.assertIn("routes-doc.py", r.reason)
            (sb.paths.checkout / "docs" / "ROUTES.md").write_text(render_routes_doc(load_routes(sb.paths)), encoding="utf-8")
            self.assertEqual(one(sb.paths, "docs.current").result, "pass")

    def test_the_script_checks_and_writes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            (sb.paths.checkout / "docs").mkdir()
            env = {"PATH": "/usr/bin:/bin", "HOME": str(sb.paths.home), "AGENT_ON_CHECKOUT": str(sb.paths.checkout), "PYTHONPATH": str(REPO)}
            p = subprocess.run([sys.executable, str(REPO / "scripts" / "routes-doc.py"), "--check"], capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 1, p.stderr)
            p = subprocess.run([sys.executable, str(REPO / "scripts" / "routes-doc.py")], capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue((sb.paths.checkout / "docs" / "ROUTES.md").exists())
            p = subprocess.run([sys.executable, str(REPO / "scripts" / "routes-doc.py"), "--check"], capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
```

Add `"docs.current"` to `EXPECTED_IDS` in `tests/agent_on/test_invariants.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_docs_render.py' -v`
Expected: `ModuleNotFoundError: No module named 'agent_on.docs'`.

- [ ] **Step 3: Write the code**

`agent_on/docs.py`:

```python
"""docs/ROUTES.md from routes.toml (§14 row D, §17): a pure function of L1, so the page can be checked (docs.current)."""
from __future__ import annotations

from .schemas.routes import Limits, Route, RouteTable

HEADER = "<!-- generated by scripts/routes-doc.py from routes.toml — do not edit -->\n# Routes\n"


def _lim(l: Limits | None) -> str:
    if l is None:
        return "—"
    return f"{l.input or '?'} / {l.output or '?'} ({l.confidence})"


def _price(r: Route, keyless: bool) -> str:
    if r.price is None:
        return "free" if keyless else "?"
    p = r.price.per_mtok()
    return f"${p['input']} / ${p['output']} per Mtok"


def _reasoning(r: Route) -> str:
    if r.reasoning is None:
        return "—"
    return ("supported" if r.reasoning.supported else "no") + (f" ({', '.join(r.reasoning.efforts)})" if r.reasoning.efforts else "")


def render_routes_doc(table: RouteTable) -> str:
    out = [HEADER, "", "Declared in `routes.toml` (L1). Measured values — served, limits verified, cost model, qualification — are in",
           "`agent-on status`, never here.", "", "## Sources", "", "| source | base_url | auth_env | catalog | discover | limits in / out |", "|---|---|---|---|---|---|"]
    for name, s in sorted(table.sources.items()):
        out.append(f"| `{name}` | {s.base_url} | {s.auth_env or 'none'} | {s.catalog or '—'} | {'yes' if s.discover else 'no'} | {_lim(s.limits)} |")
    out += ["", "## Routes", ""]
    for sname in sorted(table.sources):
        routes = sorted(table.by_source(sname), key=lambda r: r.name)
        out += [f"### {sname}", "", "| route | aliases | wire model | limits in / out | from | price | reasoning | kind |", "|---|---|---|---|---|---|---|---|"]
        keyless = table.sources[sname].auth_env is None
        for r in routes:
            lim = table.effective_limits(r)
            origin = "route" if r.limits is not None else ("source" if lim else "—")
            out.append(f"| `{r.name}` | {', '.join(f'`{a}`' for a in r.aliases) or '—'} | {r.wire_model} | {_lim(lim)} | {origin} | {_price(r, keyless)} | {_reasoning(r)} | {'packaged' if r.packaged else 'discovered'} |")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"
```

(Read `schemas/routes.py` for the exact attribute names of `Limits` (`input`, `output`, `confidence`), `Price.per_mtok()` keys and `Reasoning.efforts` before writing; adjust only names, not shape.)

`scripts/routes-doc.py`:

```python
#!/usr/bin/env python3
"""Write (or --check) docs/ROUTES.md from routes.toml. Standard library only; run from anywhere."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_on.docs import render_routes_doc  # noqa: E402
from agent_on.paths import default_paths  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402


def main(argv: list[str]) -> int:
    paths = default_paths()
    page = paths.checkout / "docs" / "ROUTES.md"
    text = render_routes_doc(load_routes(paths))
    if "--check" in argv:
        current = page.read_text(encoding="utf-8") if page.exists() else None
        if current == text:
            print(f"{page}: current")
            return 0
        print(f"{page}: stale — run scripts/routes-doc.py", file=sys.stderr)
        return 1
    page.parent.mkdir(exist_ok=True)
    page.write_text(text, encoding="utf-8")
    print(f"wrote {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

(`chmod 0755`.) `agent_on/invariants.py`:

```python
@invariant("docs.current",
           statement="docs/ROUTES.md is the render of routes.toml (a stale page is a lie about L1)",
           fix="run scripts/routes-doc.py and commit docs/ROUTES.md")
def docs_current(ctx: Context):
    page = ctx.tree / "docs" / "ROUTES.md"
    if not page.exists():
        return skip("no docs/ROUTES.md in this tree")
    from .docs import render_routes_doc
    from .paths import Paths
    try:
        table = load_routes(Paths(checkout=ctx.tree, state=ctx.paths.state, home=ctx.home, tree=ctx.tree))
    except (SchemaError, OSError) as e:
        return fail(f"routes.toml unreadable: {e}")
    return ok("current") if page.read_text(encoding="utf-8") == render_routes_doc(table) else fail("docs/ROUTES.md is stale — run scripts/routes-doc.py")
```

Then `python3 scripts/routes-doc.py` on the real checkout to create `docs/ROUTES.md`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4; ./bin/agent-on status --check | grep docs.current`
Expected: all pass; `pass docs.current: current`.

- [ ] **Step 5: Commit**

```bash
git add agent_on/docs.py scripts/routes-doc.py docs/ROUTES.md agent_on/invariants.py tests/agent_on/test_docs_render.py tests/agent_on/test_invariants.py
git commit -m "feat(agent-on): docs/ROUTES.md generated from routes.toml; docs.current keeps it honest"
```

---

### Task 3: Carry the last facts out of the old path into `knowledge/`

**Files:**
- Modify: `knowledge/observations.jsonl` (append 6), `knowledge/decisions.jsonl` (append 2), `tests/agent_on/test_knowledge_seeds.py` (`REQUIRED`)

**Interfaces:** stable ids as below. Append the lines verbatim to the end of each file (one JSON object per line, files already end with a newline; do not re-serialise). `validate_file` and `knowledge.typed` are the gate.

- [ ] **Step 1: Extend the seeds test**

In `REQUIRED["observations"]` add `"observations-2026-06-08-deepseek-211580-lower-bound"`, `"observations-2026-06-08-glm51-204800-lower-bound"`, `"observations-2026-08-23-huihui-reasoning-leak"`, `"observations-2026-08-23-qwen3-vl-text-baseline"`, `"observations-2026-08-23-local-tokenizer-delta-819-vs-768"`, `"observations-2026-08-23-reasoning-leak-is-the-thinking-flag"`; in `REQUIRED["decisions"]` add `"decisions-verifier-folded-into-qualify"`, `"decisions-old-path-deleted"`. Run the seeds test; expect the missing-id assertion to fail.

- [ ] **Step 2: Append the records**

`knowledge/observations.jsonl`:

```jsonl
{"id": "observations-2026-06-08-deepseek-211580-lower-bound", "ts": "2026-06-08T00:00:00Z", "route": "openrouter/deepseek/deepseek-v4-pro", "kind": "tokens", "values": {"accepted_input_tokens": 211580, "output_tokens": 46, "cost_usd": 1.05905, "basis": "lower_bound"}, "evidence": "Through the old gateway a 210K-word prompt was accepted and answered with the tail marker; the full 1M window was never probed. Lower bound only. Source: config/ai-litellm/context-observations.json 2026-06-08-claude-opus-deepseek-211580-lower-bound (deleted in Plan D).", "session": null}
{"id": "observations-2026-06-08-glm51-204800-lower-bound", "ts": "2026-06-08T00:00:00Z", "route": "openrouter/z-ai/glm-5.1", "kind": "tokens", "values": {"accepted_input_tokens": 204800, "provider_cap_then": 202752, "basis": "lower_bound"}, "evidence": "An OpenRouter boundary probe accepted 1 input token plus max_tokens 204799 on glm-5.1 while the provider-published cap was 202752 — enforcement stayed conservative. The route is glm-5.2 now; kept as history of how a verified bound can exceed a published one. Source: context-observations.json 2026-06-08-glm51-204800-lower-bound.", "session": null}
{"id": "observations-2026-08-23-huihui-reasoning-leak", "ts": "2026-08-23T00:00:00Z", "route": "omlx/Huihui-Qwen3.8-27B-oQ4e-mtp", "kind": "quality", "values": {"output_budgets": [700, 2200, 6000], "answered": false, "wall_s": [11.5, 35.5, 92.2]}, "evidence": "Direct on oMLX, three escalating output budgets on the same interpretation task: all three spent 100% of the budget as chain-of-thought and never emitted an answer; /no_think in the prompt was ignored; reasoning surfaced in content, not a separate channel. Superseded in interpretation by observations-2026-08-23-reasoning-leak-is-the-thinking-flag. Source: context-observations.json 2026-08-23-huihui-qwen38-27b-reasoning-leak.", "session": null}
{"id": "observations-2026-08-23-qwen3-vl-text-baseline", "ts": "2026-08-23T00:00:00Z", "route": "omlx/mlx-community--Qwen3-VL-32B-Instruct-4bit", "kind": "quality", "values": {"wall_s": 20.1, "model_load_s": 6.1, "input_tokens": 768, "output_tokens": 347, "answered": true}, "evidence": "The same small interpretation task completed normally with no reasoning leakage; the local text-task baseline and the contrast case for the Huihui run the same day. Raw: ~/Projects/ls-sizing-study/results/smoke_c_arm/smoke_20260823_attempt4.json. Source: context-observations.json 2026-08-23-qwen3-vl-32b-text-baseline.", "session": null}
{"id": "observations-2026-08-23-local-tokenizer-delta-819-vs-768", "ts": "2026-08-23T00:00:00Z", "route": "omlx/mlx-community--Qwen3-VL-32B-Instruct-4bit", "kind": "tokens", "values": {"huihui_prompt_tokens": 819, "qwen3_vl_prompt_tokens": 768, "spread_pct": 6.6}, "evidence": "The identical prompt counted 819 prompt tokens on Huihui-Qwen3.8-27B and 768 on Qwen3-VL-32B on the same runtime — first measured local tokenizer datapoint. Corrected by observations-2026-08-23-tokenizer-delta (most of the gap was the thinking template, the tokenizer spread is ~2%). Source: context-observations.json 2026-08-23-local-tokenizer-delta-819-vs-768.", "session": null}
{"id": "observations-2026-08-23-reasoning-leak-is-the-thinking-flag", "ts": "2026-08-23T00:00:00Z", "route": "omlx/Huihui-Qwen3.8-27B-oQ4e-mtp", "kind": "quality", "values": {"thinking_on_output_tokens": 476, "thinking_off_output_tokens": 53, "siblings_off_output_tokens": 45}, "evidence": "Re-measured with chat_template_kwargs.enable_thinking toggled: thinking ON spent 476 output tokens, OFF answered in 53; two abliterated 4-bit siblings that exhausted 800 tokens with thinking ON answered in 45 with it OFF. The earlier leak was the missing enable_thinking=false, not the model; the old runtime globs that injected it matched 0 of 17 live models. On the direct wire there is no per-request switch (D12). Source: context-observations.json 2026-08-23-huihui-reasoning-leak-is-thinking-flag-not-model.", "session": null}
```

`knowledge/decisions.jsonl`:

```jsonl
{"id": "decisions-verifier-folded-into-qualify", "ts": "2026-09-09T00:00:00Z", "decision": "scripts/verify_tool_call_fidelity.py and its test are deleted in Plan D rather than kept and retargeted as §13 planned: Plan B ported its six gates 1:1 into agent_on/qualify.py (run_gates), which is the surviving verifier.", "rationale": "Two homes for the gate definitions would be D5's drift; the Plan B Task 5 review confirmed the port matches the script's status, stream, tool-id and replay semantics.", "by": "Plan D, controller ruling"}
{"id": "decisions-old-path-deleted", "ts": "2026-09-09T00:00:00Z", "decision": "The old claude-litellm path is deleted in one commit (§14 row D): LiteLLM runtime and lock, OAuth lanes, callbacks, integrity chain, lib.zsh/shell.zsh/check.zsh, harness descriptors, budget/overlay/permission layers, context and reasoning ledgers, model-qualifications.json, the old tests and docs, bin/claude-litellm. No compatibility shim (D1). The one-time note for an installed copy: `rm ~/.local/bin/claude-litellm; rm -rf ~/.local/share/claude-litellm` (the venv, ~830 MB); the OpenRouter key goes in $STATE/env or the environment; old proxy sessions are not migrated.", "rationale": "Every surviving source speaks /v1/messages natively; nothing runs between Claude Code and the source; `git revert` of the deletion commit restores the old path if ever needed.", "by": "rick (D3, D9, D11), Plan D"}
```

- [ ] **Step 3: Verify and commit**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_knowledge_seeds.py' -v; ./bin/agent-on status --check | grep knowledge.typed`
Expected: pass; `pass knowledge.typed: 6 file(s) valid`.

```bash
git add knowledge/observations.jsonl knowledge/decisions.jsonl tests/agent_on/test_knowledge_seeds.py
git commit -m "knowledge: the six context observations and two decisions the old path still held, before it goes"
```

---

### Task 4: Delete the old path

**Files:**
- Delete: `config/` (entire directory), `scripts/install.zsh`, `scripts/check.zsh`, `scripts/uninstall.zsh`, `scripts/migrate-legacy.zsh`, `scripts/render-user-config.py`, `scripts/verify-install.py`, `scripts/runtime-fingerprint.py`, `scripts/task-ledger.py`, `scripts/verify_oauth_adapters.py`, `scripts/verify_tool_call_fidelity.py`, `scripts/verify_budget_consistency.py`, `scripts/verify_litellm_token_clamp.py`, `scripts/verify_user_config_overlay.py`, `tests/test_output_clamp.py`, `tests/test_verify_tool_call_fidelity.py`, `tests/test_task_ledger.py`, `tests/test_runtime_fingerprint.py`, `bin/claude-litellm`, `docs/ARCHITECTURE.md`, `docs/MODEL-RUNBOOK.md`, `docs/PROVIDERS.md`, `docs/MIGRATION.md`
- Modify: `.gitignore`, `routes.toml` (line 3 comment), `agent_on/harness.py` (line 34 comment), `agent_on/qualify.py` (line 3 docstring), `tests/agent_on/test_paths.py` (line 84 example path), `.github/workflows/ci.yml`
- Test: `tests/agent_on/test_docs_plan_d.py` (first half: the tree lint)

**Interfaces:** none new. After this task `scripts/` holds only `routes-doc.py`; `tests/` holds only `agent_on/`; `docs/` holds `ROUTES.md` and `superpowers/`.

- [ ] **Step 1: Write the failing test**

`tests/agent_on/test_docs_plan_d.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

OLD = ["config", "scripts/check.zsh", "scripts/install.zsh", "scripts/task-ledger.py", "scripts/verify_tool_call_fidelity.py",
       "bin/claude-litellm", "docs/ARCHITECTURE.md", "docs/MODEL-RUNBOOK.md", "docs/PROVIDERS.md", "docs/MIGRATION.md",
       "tests/test_task_ledger.py", "tests/test_output_clamp.py"]


def tracked() -> list[str]:
    return subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split()


class OldPathGoneTest(unittest.TestCase):
    def test_nothing_of_the_old_path_is_tracked(self):
        files = tracked()
        for p in OLD:
            self.assertFalse(any(f == p or f.startswith(p + "/") for f in files), p)
        self.assertEqual([f for f in files if f.startswith("scripts/")], ["scripts/routes-doc.py"])
        self.assertEqual([f for f in files if f.startswith("tests/") and "/" not in f[len("tests/"):]], [])

    def test_no_litellm_under_the_surviving_trees(self):
        hits = subprocess.run(["git", "-C", str(REPO), "grep", "-il", "litellm", "--", "agent_on", "bin", "routes.toml", "tests", "scripts", ".github"],
                              capture_output=True, text=True)
        self.assertEqual(hits.stdout.strip(), "", hits.stdout)

    def test_readme_names_the_old_path_only_in_the_upgrade_note(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        head, _, tail = text.partition("## Upgrading from claude-litellm")
        self.assertNotIn("litellm", head.lower())
        self.assertIn("rm -rf ~/.local/share/claude-litellm", tail)


if __name__ == "__main__":
    unittest.main()
```

(The third test passes only after Task 5; run the first two now.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3.13 -m unittest discover -s tests/agent_on -p 'test_docs_plan_d.py' -v`
Expected: the first two fail (old files tracked; `litellm` hits).

- [ ] **Step 3: Delete and reword**

```bash
git rm -r -q config tests/test_output_clamp.py tests/test_verify_tool_call_fidelity.py tests/test_task_ledger.py tests/test_runtime_fingerprint.py bin/claude-litellm docs/ARCHITECTURE.md docs/MODEL-RUNBOOK.md docs/PROVIDERS.md docs/MIGRATION.md
git rm -q scripts/install.zsh scripts/check.zsh scripts/uninstall.zsh scripts/migrate-legacy.zsh scripts/render-user-config.py scripts/verify-install.py scripts/runtime-fingerprint.py scripts/task-ledger.py scripts/verify_oauth_adapters.py scripts/verify_tool_call_fidelity.py scripts/verify_budget_consistency.py scripts/verify_litellm_token_clamp.py scripts/verify_user_config_overlay.py
```

`.gitignore` — replace the whole file with:

```
.DS_Store
__pycache__/
*.pyc
# agent-on: the routes.toml / knowledge writer locks and their temp files live in the checkout (§7.1 rev 6, §10)
.routes.lock
.knowledge.lock
routes.toml.tmp.*
# Local scratch
.tmp/
```

(`claude-config/` is under `$STATE`, never in the checkout; `.claude/worktrees/` is ignored by Claude Code's own global rules — verify with `git check-ignore .claude/worktrees` before dropping it; if it is not ignored globally, keep `.claude/worktrees/` in the list.)

`routes.toml` line 3 → `# The GPT and xAI OAuth routes the old gateway packaged are deliberately absent (D3).`
`agent_on/harness.py:34` → `# The routing denylist the old launcher scrubbed, kept whole: anything …` (drop the file path).
`agent_on/qualify.py:3` → `fingerprint it was valid for. The six gates are the old verifier's, ported 1:1 (decisions-verifier-folded-into-qualify); here`.
`tests/agent_on/test_paths.py:84` → use `"/Users/rick/Projects/agent-on"` → `"-Users-rick-Projects-agent-on"` (a path example, not a name).

`.github/workflows/ci.yml` — replace the whole file with:

```yaml
name: CI

on:
  push:
    branches:
      - main
  pull_request:

jobs:
  agent-on:
    # docs/superpowers/specs/2026-09-07-agent-on-design.md: stdlib only. Sources are unreachable on CI; the gate
    # reports those as listed skips, never as passes.
    runs-on: macos-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"

      # Reports land in RUNNER_TEMP, not the checkout: a file written beside the code would make copy.dirty true.
      - name: agent-on gate
        run: AGENT_ON_STATE="$RUNNER_TEMP/agent-on-state" ./bin/agent-on gate --json | tee "$RUNNER_TEMP/gate.json"

      - name: Assert the gate passed with its skips listed
        run: |
          python - <<'PY'
          import json, os
          g = json.load(open(os.path.join(os.environ["RUNNER_TEMP"], "gate.json")))
          assert g["result"] == "pass", g["last_gate_run"]
          assert g["tests"]["ok"] is True and g["tests"]["ran"] > 200, g["tests"]
          assert g["smoke"]["ok"] is True, g["smoke"]
          inv = g["last_gate_run"]["invariants"]
          assert inv["credential.not_in_child_env"] == "pass"
          assert inv["knowledge.typed"] == "pass"
          assert inv["docs.current"] == "pass"
          PY

      - name: install into a scratch bin dir, then dry-run every packaged route through the shim
        run: |
          set -euo pipefail
          export AGENT_ON_STATE="$RUNNER_TEMP/agent-on-state"
          ./bin/agent-on install --bin-dir "$RUNNER_TEMP/bin" --json | tee "$RUNNER_TEMP/install.json"
          python - <<'PY'
          import json, os
          d = json.load(open(os.path.join(os.environ["RUNNER_TEMP"], "install.json")))
          assert d["written"], d
          assert {l["state"] for l in d["links"].values()} == {"linked"}, d["links"]
          PY
          for r in $(./bin/agent-on status --json | python -c 'import json,sys; print(" ".join(json.load(sys.stdin)["routes"]))'); do
            "$RUNNER_TEMP/bin/claude-on" --dry-run "$r" -p hi --json > /dev/null
          done
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4; git grep -il litellm -- agent_on bin routes.toml tests scripts .github | wc -l`
Expected: all pass except `test_readme_names_the_old_path_only_in_the_upgrade_note` (Task 5); `0`.

- [ ] **Step 5: Commit**

```bash
git add -A .gitignore routes.toml agent_on/harness.py agent_on/qualify.py tests/agent_on/test_paths.py .github/workflows/ci.yml tests/agent_on/test_docs_plan_d.py
git commit -m "chore!: delete the old claude-litellm path — LiteLLM runtime and lock, OAuth lanes, callbacks, integrity chain, zsh libraries, the old gate, tests and docs (§14 row D)

git revert of this commit restores the old path intact."
```

(The commit's `-A` picks up the `git rm` staging; check `git status` shows nothing unexpected before committing.)

---

### Task 5: README for `agent-on`, with the one-time upgrade note

**Files:**
- Modify: `README.md` (rewrite), `.claude/skills/agent-on/SKILL.md` (one line: `install`)
- Test: `tests/agent_on/test_docs_plan_d.py` third test (exists)

- [ ] **Step 1: Run the failing test**

Run: `python3.13 -m unittest tests.agent_on.test_docs_plan_d -k readme -v` (from the checkout with `PYTHONPATH=.`; or `-p 'test_docs_plan_d.py'`)
Expected: fails (`litellm` appears before the upgrade section; no section).

- [ ] **Step 2: Write the README**

Replace `README.md` entirely with:

```markdown
# agent-on

Run Claude Code on any model from any source that speaks the Anthropic wire — OpenRouter, a local oMLX server,
another Mac's oMLX over the tailnet — with nothing between Claude Code and the source, and with what each
session measured kept for the next one.

    ./bin/claude-on huihui                       # Claude Code on a local oMLX route; the cost line prints first
    ./bin/claude-on glm -p 'Reply with exactly: OK'
    ./bin/agent-on status glm                    # declared beside measured: served, limits, cost model, last session, traps

The design is `docs/superpowers/specs/2026-09-07-agent-on-design.md`. This README is the operator's page.

## Install

Requirements: macOS or Linux, `python3` ≥ 3.11 on `PATH` (standard library only — nothing is pip-installed), `git`,
Claude Code (`claude` on `PATH`).

    git clone https://github.com/xz0831/agent-on.git
    cd agent-on
    ./bin/agent-on install                       # links ~/.local/bin/agent-on and claude-on here; creates ~/.local/state/agent-on

The checkout is the installation (D9): `install` puts two symlinks in `~/.local/bin` and creates the state root.
Pull to upgrade. `agent-on status --check` reports drift as `copy.dirty` (uncommitted changes) and `copy.single`
(the shim points here). `AGENT_ON_STATE=<dir>` runs the checkout against a scratch state root.

Keys: put `OPENROUTER_API_KEY=…` in `~/.local/state/agent-on/env` (mode 0600) or in the environment. The key never
enters Claude Code's environment: the launcher writes it to a per-launch 0600 file and hands Claude Code an
`apiKeyHelper` that reads it.

## Use

    ./bin/claude-on <route|alias> [claude args…]         # launch options (--dry-run, --sonnet, --haiku, --task, --discover) go before the route
    ./bin/claude-on --dry-run glm                         # environment keys, argv and cost line; spawns nothing
    ./bin/agent-on status [route] [--check]               # L1 beside L2; --check evaluates every invariant
    ./bin/agent-on sync                                   # probe every source: served, limits, spend; rewrite routes.discovered.toml
    ./bin/agent-on add openrouter/<vendor>/<model> --alias <a>
    ./bin/agent-on qualify <route> [--baseline] [--limits] [--allow-paid]
    ./bin/agent-on learn <kind> --json-record '{…}'       # append a typed record to knowledge/
    ./bin/agent-on learn task create|handoff|complete|show|list|prompt
    ./bin/agent-on gate                                   # unit tests + mock-source smoke + every invariant

Every command answers `--json`. Everything after the route belongs to Claude Code; give list-valued Claude options
as `--opt=value` when a task prompt is injected.

Routes are `<source>/<model>` with optional aliases, declared only in `routes.toml`; `docs/ROUTES.md` is generated
from it (`scripts/routes-doc.py`, checked by `docs.current`). Measured values — served, verified limits, tok/s,
concurrency, caching, thinking, the last session's cost — live in `~/.local/state/agent-on/observed.json` and are
shown by `status`, never copied into declarations.

One Claude Code process is pinned to one route; the tier slots and the subagent slot all resolve to it. To change
model, exit and relaunch. Qualification results and traps are shown before a launch; they never block it.

## Knowledge

`knowledge/` is git-tracked, append-only JSONL beside `routes.toml`: decisions (with supersession), traps (with
`applies_to`), observations, and the durable twins of qualifications and gate runs. `qualify`, the gate and the
launch append to it; `learn` is the write verb for everything else; `.claude/skills/agent-on/SKILL.md` tells an
agent inside Claude Code how to read and write it. Commit `knowledge/` with the work that produced it.

Tasks across sessions: `learn task create … / handoff … --to <route>`, then `claude-on --task <id> <route>` runs in
the task's worktree with the handoff prompt injected; `learn task complete` records the outcome.

## Verify

    ./bin/agent-on gate                          # what CI runs: tests/agent_on, the F1 smoke on a mock source, every invariant
    ./bin/agent-on status --check                # the invariants alone, with skips shown as skips

Sources that are unreachable are reported as unreachable, never as passing.

## Upgrading from claude-litellm

The previous gateway (LiteLLM proxy, OAuth lanes, the `claude-litellm` command) is gone; `git revert` of its
deletion commit restores it. One-time cleanup of an installed copy:

    rm ~/.local/bin/claude-litellm
    rm -rf ~/.local/share/claude-litellm          # the hash-locked venv and its state, about 830 MB

Keys move to `~/.local/state/agent-on/env`; proxy-era sessions are not migrated. The ChatGPT/xAI OAuth routes are
not coming back (D3); GPT is used through Codex.
```

`.claude/skills/agent-on/SKILL.md` — in "Read first" add one line after the `status --check` bullet:
`- `./bin/agent-on install` — links the two shims into `~/.local/bin` and creates the state root; idempotent.`

- [ ] **Step 3: Run the tests to verify they pass**

Run: `python3.13 -m unittest discover -s tests/agent_on -v 2>&1 | tail -4`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add README.md .claude/skills/agent-on/SKILL.md
git commit -m "docs: README for agent-on — install, use, knowledge, verify, and the one-time note for an installed claude-litellm copy"
```

---

### Task 6: Acceptance on the real machine (§14 row D)

**Files:** none (records go through the commands into `knowledge/`).

- [ ] **Step 1: The tower on the deleted tree**

```bash
./bin/agent-on status --check | grep -E '^  fail|docs.current|knowledge.typed|copy.single'
./bin/agent-on gate | tail -3
git ls-files | xargs wc -l | tail -1
git ls-files | grep -v '^docs/superpowers/' | xargs wc -l | tail -1
```

Expected: no `fail` lines; `docs.current` pass; `copy.single` skip (no shim yet) or pass; gate pass. Record both line counts (the §13 measure with and without the design documents).

- [ ] **Step 2: A fresh clone installs and launches with stdlib Python only**

```bash
T=$(mktemp -d); git clone -q "$PWD" "$T/agent-on"
( cd "$T/agent-on" && AGENT_ON_STATE="$T/state" HOME="$T/home" ./bin/agent-on install --bin-dir "$T/bin" | tail -4 )
AGENT_ON_STATE="$T/state" "$T/bin/claude-on" --dry-run huihui -p hi | grep -E 'dry run|copy:'
AGENT_ON_STATE="$T/state" "$T/bin/agent-on" status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["routes"]), "routes;", d["copy"]["checkout"])'
for r in $(AGENT_ON_STATE="$T/state" "$T/bin/agent-on" status --json | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["routes"]))'); do AGENT_ON_STATE="$T/state" "$T/bin/claude-on" --dry-run "$r" -p hi >/dev/null || echo "DRY-RUN FAILED: $r"; done; echo "dry runs done"
AGENT_ON_STATE="$T/state" "$T/bin/claude-on" huihui -p 'Reply with exactly: OK'; echo "exit $?"
```

Expected: install links both; `copy:` names the clone; every packaged route dry-runs (exit 0); the real launch on the free route prints `OK`, exit 0 — from a clone that contains no venv, no lock file, no LiteLLM.

- [ ] **Step 3: Install for real on this machine**

```bash
./bin/agent-on install | tail -5
which agent-on claude-on; ls -l ~/.local/bin/agent-on ~/.local/bin/claude-on
./bin/agent-on status --check | grep copy.single
claude-on --dry-run glm -p hi | head -3
```

Expected: both links → this checkout; `pass copy.single`; the shim on PATH works. (The old `~/.local/bin/claude-litellm` file and `~/.local/share/claude-litellm` are the owner's to remove — the README note; do not delete them in this task.)

- [ ] **Step 4: S4/S5 — the other oMLX sources, when reachable**

```bash
./bin/agent-on sync | grep -E 'omlx-tp2|omlx@morty'
```

If either is reachable: `./bin/agent-on qualify <its first route>`; otherwise record nothing (the spec says "when reachable") and note it in the commit.

- [ ] **Step 5: The peer check, re-run for Q2/Q7/Q9**

Dispatch a fresh subagent (sonnet) with only `./bin/agent-on status --json` output, the six `knowledge/*.jsonl`, `README.md` and `docs/ROUTES.md`, and ask: Q2 "Is the process on :4000 running the code I see in the checkout?", Q7 "Does anything phone home?", Q9 "When does the OAuth token expire?", plus Q3 and Q5 again. Expected: Q2 — nothing runs between Claude Code and the source, `copy.*` names the checkout and commit; Q7 — the only network calls are the sources declared in `routes.toml` and Claude Code's own; Q9 — there is no OAuth (D3); Q3/Q5 as before. An answer that needs the spec is a finding: fix the README or a record in this task's series.

- [ ] **Step 6: Record and commit**

```bash
./bin/agent-on learn observations --json-record '{"route": "harness/agent-on", "kind": "tokens", "values": {"tracked_lines": <N>, "without_design_docs": <M>, "python": <P>, "tests": <T>, "gate_6000": <true|false>}, "evidence": "git ls-files | xargs wc -l at <commit>, Plan D acceptance (§13 measure)", "session": null}'
git add knowledge/
git commit -m "knowledge: Plan D acceptance on <date> — fresh clone + install launches huihui with stdlib Python; line count <N> (<M> without design docs); S4/S5 <reachable|unreachable>; peer check Q2 Q7 Q9 moot as designed

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fv3KyERBe3WtKsNJmpu1YD"
```

- [ ] **Step 7: Owner steps after merge (not automated — checked with the mac-cluster orchestrator session on 2026-09-09)**

What is bound to the path, and what moves with it: Claude Code keys project memory and resumable transcripts by cwd
under `~/.claude/projects/<cwd with / → ->` — four keys exist (the checkout and the three finished
`.claude/worktrees/agent-on-plan-{a,b,c}` sessions); `~/.claude.json` holds a per-path entry (trust dialog,
`allowedTools`, last session id); `.claude/skills` and any `.claude/settings.local.json` live inside the checkout and
move with it; mac-cluster's `docs/session-registry.json` names this session's cwd (its orchestrator updates that
entry and resumes the session from the new cwd). Nothing in launchd, shell rc files, Orca or worker contracts
references the path or the `claude-litellm` command.

Order matters: the session working in `~/Projects/claude-litellm` must exit first (the `mv` would pull the
directory out from under it). Then, in a fresh shell:

```bash
set -e
mv ~/Projects/claude-litellm ~/Projects/agent-on
cd ~/Projects/agent-on && git worktree prune && git worktree repair            # registrations store absolute paths
for k in "" --claude-worktrees-agent-on-plan-a --claude-worktrees-agent-on-plan-b --claude-worktrees-agent-on-plan-c; do
  [ -d ~/.claude/projects/-Users-rick-Projects-claude-litellm$k ] && mv ~/.claude/projects/-Users-rick-Projects-claude-litellm$k ~/.claude/projects/-Users-rick-Projects-agent-on$k
done
python3 - <<'PY'                                                                 # trust + allowedTools follow the path
import json; p = "/Users/rick/.claude.json"; d = json.load(open(p)); pr = d["projects"]
old, new = "/Users/rick/Projects/claude-litellm", "/Users/rick/Projects/agent-on"
if old in pr and new not in pr:
    pr[new] = pr[old]; json.dump(d, open(p, "w"), indent=2)
PY
./bin/agent-on install                                                           # re-links ~/.local/bin/agent-on and claude-on
```

Then: rename the GitHub repository to `agent-on` and `git remote set-url origin git@github.com:xz0831/agent-on.git`;
tell the orchestrator the `mv` is done (it renames the registry entry to `agent-on` and resumes the session with
`bash bin/session-resume.sh agent-on` — `--remote-control` keeps the bridge session id); finally
`rm ~/.local/bin/claude-litellm; rm -rf ~/.local/share/claude-litellm` when the old copy is no longer wanted.

---

## Self-review

**Spec coverage — §14 row D:**

| requirement | task |
|---|---|
| `install` as shims + state root (§9 row, D9) | 1 |
| `copy.single` real | 1 (the predicate existed; the shim now exists) |
| docs generated from `routes.toml` (§17: ARCHITECTURE.md replaced) | 2 |
| delete everything old, in one plan | 4 (one commit, revertable) |
| `omlx-tp2` / `omlx@morty` qualified when reachable (S4, S5) | 6 step 4 |
| fresh clone + `install` launches every reachable route with stdlib Python only | 6 step 2 |
| no hit for `litellm` under `agent_on/`, `bin/`, `routes.toml`, `tests/` | 4 (test) |
| Q2/Q7/Q9 moot and the peer check re-run | 6 step 5 |
| line count recorded; gate green | 6 steps 1, 6 |
| rename to `agent-on` (D1) | in-repo names done in 4–5; directory and GitHub rename are owner steps (6 step 7) |
| facts in deleted files preserved (§10 append-only knowledge) | 3 |

**Size gate, stated plainly:** the §13 hard gate is ≤ 6,000 lines by `git ls-files | xargs wc -l`. After Task 4 the tree is roughly: `agent_on/` ~3,950, `tests/agent_on/` ~3,700, `knowledge/` ~70, `routes.toml` ~150, `README.md` ~110, `docs/ROUTES.md` ~120, `bin/` ~30, `.claude/skills` ~50, CI ~60, `scripts/routes-doc.py` ~35 — about **8,300 without `docs/superpowers/`** (the design documents add ~9,600 more). Non-test code is ~4,500, under the gate; the tests are 3.7× the spec's ~1,000 estimate because every measured behaviour got a test. The plan does not delete tests to hit a number. Task 6 records the measure; the owner decides whether to amend the gate to "non-test lines ≤ 6,000" or to prune tests in a later plan.

**Deviations, stated:** `verify_tool_call_fidelity.py` is deleted, not "kept and retargeted" (§13) — its gates already live in `qualify.py` (Task 3's decision record). The directory/GitHub rename is not automated (a side effect outside the worktree; it also changes Claude Code's project memory key). `docs.current` is an added invariant (the spec's table has 14; a generated page needs a check or it lies — D5). `install` gains `--bin-dir` for tests and CI.

**Placeholder scan:** the `<N>`/`<M>`/`<P>`/`<T>`/`<date>`/`<commit>` tokens in Task 6's record and commit template are filled from the measurement; Task 2 tells the implementer to read `schemas/routes.py` for attribute names before writing the renderer (shape fixed, names verified).

**Type consistency:** `run_install(paths, *, bin_dir, dry_run)` matches the CLI call; `Paths.shim` still resolves to `home/.local/bin/agent-on` so `copy.single` and `describe_copy` are unchanged in meaning; `render_routes_doc(table)` is called identically by the script and the invariant; `docs.current` reads `ctx.tree`, consistent with the other tree lints; `test_docs_plan_d.py`'s third test names the README section header exactly as Task 5 writes it.
