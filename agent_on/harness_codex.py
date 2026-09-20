"""Codex binding: durable isolated session homes, with per-launch credential files."""
from __future__ import annotations

import json
import fcntl
import os
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
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


def prepare_codex_home(paths: Paths, launch_id: str, home: Path, launch: dict, *, existing: Path | None = None) -> Path:
    d = paths.run_dir / launch_id
    d.mkdir(mode=0o700)
    (d / "pid").write_text(str(os.getpid()), encoding="utf-8")
    (d / "launch.json").write_text(json.dumps(launch, indent=1, sort_keys=True), encoding="utf-8")
    ch = existing or paths.codex_home_for(launch_id)
    ch.mkdir(parents=True, exist_ok=True, mode=0o700)
    native = home / ".codex"
    for item in CODEX_SHARED:
        if (native / item).exists() and not (ch / item).exists() and not (ch / item).is_symlink():
            (ch / item).symlink_to(native / item)
    return ch


def resume_target(paths: Paths, args: list[str]) -> tuple[Path | None, Path | None]:
    """Resolve explicit UUID resumes only within this launcher's durable homes.

    Pickers and --last are deliberately rejected: selecting a different home silently
    would lose the intended conversation. Native ~/.codex sessions are never imported.
    """
    valued = {"-c", "--config", "--enable", "--disable", "-m", "--model", "-s", "--sandbox",
              "-a", "--ask-for-approval", "-C", "--cd", "--add-dir", "-i", "--image",
              "-o", "--output-last-message", "--output-schema", "--local-provider", "--thread-source"}
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        i += 2 if args[i] in valued else 1
    if i < len(args) and args[i] in ("exec", "e"):
        i += 1
        while i < len(args) and args[i].startswith("-") and args[i] != "--":
            i += 2 if args[i] in valued else 1
    index = i + 1 if i < len(args) and args[i] == "resume" else None
    if index is None:
        return None, None
    try:
        session_id = str(uuid.UUID(args[index]))
    except (IndexError, ValueError):
        raise ValueError("codex resume requires an explicit session UUID immediately after resume; --last and session names are not supported") from None
    files = list((paths.state / "codex-homes").glob(f"*/codex-home/sessions/**/rollout-*-{session_id}.jsonl"))
    if len(files) != 1:
        raise ValueError(f"codex session {session_id} has {len(files)} saved rollouts in {paths.state / 'codex-homes'}; refusing a fresh or ambiguous resume")
    rollout = files[0]
    ch = next(p for p in rollout.parents if p.name == "codex-home")
    return ch, rollout


@contextmanager
def session_lock(codex_home: Path):
    """Do not allow concurrent writers to the same resumed session home."""
    fd = os.open(codex_home / ".agent-on.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f"codex session is already active: {codex_home}") from None
        yield
    finally:
        os.close(fd)


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


_TOTAL_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")


def read_rollout(path: Path) -> dict:
    """Final-fix item 1: Codex re-emits `token_count` events with no new model call, so summing every event's
    `last_token_usage` overcounts by up to 25% on real rollouts. Each event's `info.total_token_usage` is
    cumulative, so a turn is the delta between consecutive totals; a re-emit (zero delta) adds no turn. Falls
    back to the old per-event `last_token_usage` mapping only when NO event in the file carries a usable
    `total_token_usage` (older Codex)."""
    session_id = version = model = effort = permission = None
    events: list[tuple[int, str | None, str | None, dict]] = []   # (line no, timestamp, model at that point, info)
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
            permission = ((sp.get("mode") or sp.get("type")) if isinstance(sp, dict) else sp) or permission
        elif e.get("type") == "event_msg" and p.get("type") == "token_count":
            info = p.get("info") if isinstance(p.get("info"), dict) else None
            if info is not None:
                events.append((n, e.get("timestamp"), model, info))
    turns: list[dict] = []
    first = None
    has_total = any(isinstance(info.get("total_token_usage"), dict) and info["total_token_usage"] for _, _, _, info in events)
    if has_total:
        prev = {f: 0 for f in _TOTAL_FIELDS}
        for n, ts, m, info in events:
            total = info.get("total_token_usage")
            if not isinstance(total, dict) or not total:
                continue
            cur = {f: int(total.get(f) or 0) for f in _TOTAL_FIELDS}
            delta = {f: max(0, cur[f] - prev[f]) for f in _TOTAL_FIELDS}
            prev = cur
            if not any(delta.values()):
                continue                                          # a re-emit: no new model call, no turn
            usage = _usage(delta)
            turns.append({"timestamp": ts, "model": m, "usage": usage, "id": f"turn-{n}"})
            if first is None:
                first = {"usage": usage, "input_tokens_total": delta["input_tokens"]}
    else:
        for n, ts, m, info in events:
            last = info.get("last_token_usage")
            if not last:
                continue
            usage = _usage(last)
            turns.append({"timestamp": ts, "model": m, "usage": usage, "id": f"turn-{n}"})
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
    existing_home, previous_rollout = resume_target(paths, args)
    mode = "resume" if existing_home else "fresh"
    codex_home = existing_home or paths.codex_home_for(plan.launch_id)
    cenv = child_env(plan.parent, table, route, context=plan.context, config_dir=codex_home, harness="codex")
    binary = codex_bin or shutil.which("codex") or "codex"
    argv = [binary, "--profile", PROFILE, *args]
    doc: dict = {"command": "launch", "copy": describe_copy(paths), "route": route.name, "wire_model": route.wire_model,
                 "base_url": source.base_url, "launch_id": plan.launch_id,
                 "cost_line": cost_line(route.name, plan.obs_route, harness="codex"), "invariants": [plan.served, *plan.lint],
                 "env_keys": sorted(k for k in cenv if k.startswith(("CODEX_", "OPENAI_"))), "swept": plan.swept,
                 "warnings": plan.warnings, "traps": plan.traps, "task": plan.task_doc,
                 "codex_home": str(codex_home)}
    if dry_run:
        doc.update({"dry_run": True, "argv": argv})
        return doc
    # Subsecond precision prevents a quick resume from re-attributing earlier turns.
    plan.started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    launch = {"launch_id": plan.launch_id, "route": route.name, "source": route.source, "wire_model": route.wire_model,
              "started": plan.started, "session_id": None, "mode": mode, "cwd": plan.cwd, "price": plan.price,
              "priced_models": plan.priced_models, "context": plan.context, "codex_args": args}
    ensure_state(paths)
    run_dir = paths.run_dir / plan.launch_id
    try:
        ch = prepare_codex_home(paths, plan.launch_id, paths.home, launch, existing=existing_home)
        with session_lock(ch):
            profile_link = ch / f"{PROFILE}.config.toml"
            # A crashed launcher can leave a dangling link; only replace launcher links.
            if profile_link.is_symlink():
                profile_link.unlink()
            elif profile_link.exists():
                raise ValueError(f"refusing to replace non-launcher profile: {profile_link}")
            try:
                profile = write_profile(run_dir, model=route.wire_model, base_url=source.base_url, key=plan.key, context=plan.context)
                profile_link.symlink_to(profile.resolve())
                if plan.task_doc:
                    from .tasks import launched
                    launched(paths, plan.task_doc["id"], handoff=str(plan.task_doc["handoff"]), launch_id=plan.launch_id, route=route.name)
                if announce:
                    print(doc["cost_line"], file=sys.stderr)
                code = spawn(argv, cenv, plan.cwd)
                rollout_path = previous_rollout or find_rollout(codex_home)
                rollout = read_rollout(rollout_path) if rollout_path else None
            finally:
                if profile_link.is_symlink():
                    profile_link.unlink()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)                                   # the key never outlives the child
    ended = utc_ceil()
    launch["session_id"] = (rollout or {}).get("session_id") or plan.launch_id
    doc["session"] = {"id": launch["session_id"], "mode": mode}
    doc["transcript"] = str(rollout_path) if rollout_path else None
    return epilogue(paths, plan, launch, code=code, ended=ended, transcript=rollout, mode=mode, harness="codex",
                    harness_version=(rollout or {}).get("version"), doc=doc)
