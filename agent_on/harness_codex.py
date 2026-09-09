"""L6 — the Codex binding (§11.1, D14). One file; the tower unchanged. Home isolation: a per-launch CODEX_HOME with the
operator's config, skills, plugins and hooks linked in and a 0600 profile file carrying the provider and the key."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .harness import child_env, cost_line, epilogue, prologue, spawn, utc_ceil
from .paths import Paths, describe_copy, ensure_state

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


def run_launch_codex(paths: Paths, name: str, codex_args: list[str], *, dry_run: bool = False, env: dict | None = None,
                     codex_bin: str | None = None, cwd: str | None = None, probe_timeout: float = 2.0,
                     announce: bool = True, task: str | None = None, handoff: str = "latest") -> dict:
    plan = prologue(paths, name, codex_args, env=env, cwd=cwd, task=task, handoff=handoff, probe_timeout=probe_timeout,
                    harness_bin=codex_bin, harness="codex")
    table, route, source = plan.table, plan.route, plan.source
    args, user_profile = extract_user_profile(plan.args)
    if user_profile is not None:
        plan.warnings.append(f"user --profile {user_profile} replaced by the launcher's profile {PROFILE}")
    if any("resume" in a.lower() for a in args):
        plan.warnings.append("codex resume is not supported by agent-on yet (Plan F Task 5); launching a fresh session")
    codex_home = paths.codex_home_for(plan.launch_id)
    cenv = child_env(plan.parent, table, route, context=plan.context, config_dir=codex_home, harness="codex")
    binary = codex_bin or shutil.which("codex") or "codex"
    argv = [binary, "--profile", PROFILE, *args]
    doc: dict = {"command": "launch", "copy": describe_copy(paths), "route": route.name, "wire_model": route.wire_model,
                 "base_url": source.base_url, "launch_id": plan.launch_id,
                 "cost_line": cost_line(route.name, plan.obs_route, harness="codex"), "invariants": [plan.served, *plan.lint],
                 "env_keys": sorted(k for k in cenv if k.startswith(("CODEX_", "OPENAI_"))), "swept": plan.swept,
                 "warnings": plan.warnings, "traps": plan.traps, "task": plan.task_doc}
    if dry_run:
        doc.update({"dry_run": True, "argv": argv})
        return doc
    launch = {"launch_id": plan.launch_id, "route": route.name, "source": route.source, "wire_model": route.wire_model,
              "started": plan.started, "session_id": None, "mode": "fresh", "cwd": plan.cwd, "price": plan.price,
              "priced_models": plan.priced_models, "context": plan.context, "codex_args": args}
    ensure_state(paths)
    ch = prepare_codex_home(paths, plan.launch_id, paths.home, launch)
    write_profile(ch, model=route.wire_model, base_url=source.base_url, key=plan.key, context=plan.context)
    if plan.task_doc:
        from .tasks import launched
        launched(paths, plan.task_doc["id"], handoff=str(plan.task_doc["handoff"]), launch_id=plan.launch_id, route=route.name)
    if announce:
        print(doc["cost_line"], file=sys.stderr)                                     # the §12 line, before spawning
    run_dir = paths.run_dir / plan.launch_id
    try:
        code = spawn(argv, cenv, plan.cwd)
        rollout_path = find_rollout(codex_home)
        rollout = read_rollout(rollout_path) if rollout_path else None               # read back BEFORE the home is removed (D14)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)                                   # the key never outlives the child
    ended = utc_ceil()
    launch["session_id"] = (rollout or {}).get("session_id") or plan.launch_id
    doc["transcript"] = str(rollout_path) if rollout_path else None
    return epilogue(paths, plan, launch, code=code, ended=ended, transcript=rollout, mode="fresh", harness="codex",
                    harness_version=(rollout or {}).get("version"), doc=doc)
