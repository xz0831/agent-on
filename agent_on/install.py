"""`agent-on install` (§9, D9): the checkout is the installation. Link the three shims into ~/.local/bin, create the
state root, check the interpreter, report copy.*. Nothing is copied, hashed or pinned — drift is `git status` plus
"does the shim point here" (copy.single)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .invariants import build_context, evaluate
from .paths import Paths, describe_copy, ensure_state

SHIMS = ("agent-on", "claude-on", "codex-on")
MIN_PYTHON = (3, 11)


def _link(path: Path, target: Path, *, dry_run: bool) -> tuple[str, str | None]:
    if path.is_symlink():
        old_target = os.readlink(path)
        if old_target == str(target):
            return "unchanged", None
        if dry_run:
            return "dry-run", f"would replace symlink -> {old_target}"
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        os.symlink(target, tmp)
        os.replace(tmp, path)                                   # atomic: a shell mid-exec sees the old or the new link
        return "replaced", f"was -> {old_target}"
    if path.exists():
        return "refused", f"{path} exists and is not a symlink — remove it yourself, then re-run install"
    if dry_run:
        return "dry-run", None
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)
    return "linked", None


def run_install(paths: Paths, *, bin_dir: Path | None = None, dry_run: bool = False) -> dict:
    bd = (Path(bin_dir) if bin_dir else paths.bin_dir).resolve()
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
        # Controller ruling (Plan D task 1): the link target is paths.code_tree / "bin" / name, resolved — not
        # paths.checkout. copy.single compares the shim against `tree / "bin" / "agent-on"` (invariants.py);
        # in production checkout == tree, so this only matters for the sandboxed tests (Sandbox(tree=REPO) with a
        # checkout that is a bare temp dir with no bin/).
        target = (paths.code_tree / "bin" / name).resolve()
        state, reason = _link(bd / name, target, dry_run=dry_run)
        doc["links"][name] = {"path": str(bd / name), "target": str(target), "state": state, "reason": reason}
    on_path = str(bd) in [str(Path(p).resolve()) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    doc["on_path"] = on_path
    if not on_path:
        doc["warnings"].append(f'{bd} is not on PATH — add: export PATH="{bd}:$PATH"')
    doc["written"] = all(l["state"] in ("linked", "replaced", "unchanged") for l in doc["links"].values())
    doc["copy"] = describe_copy(paths)                          # after linking: copy.shim shows the link
    # copy.single (invariants.py) only ever checks paths.bin_dir (~/.local/bin) via paths.shim — a custom
    # --bin-dir install would otherwise print a misleading "skip … no shim" line for a link that isn't even there.
    custom_bin_dir = bd != paths.bin_dir.resolve()
    if custom_bin_dir:
        doc["warnings"].append(f"copy.single checks ~/.local/bin only; installed to {bd} instead")
    doc["invariants"] = [] if dry_run or custom_bin_dir else [r.as_dict() for r in evaluate(build_context(paths), ids=["copy.single"])]
    return doc
