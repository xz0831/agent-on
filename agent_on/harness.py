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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .cost import attribute_run, fold_session
from .effort import OmlxEffortAdapter, explicit_claude_effort, launch_effort_metadata
from .ids import ulid
from .knowledge import append as knowledge_append, knowledge_view
from .paths import Paths, describe_copy, ensure_state, project_slug
from .schemas.observed import USAGE_FIELDS, empty_route
from .schemas.routes import Route, RouteTable, Source, load_routes
from .sources import probe_source
from .state import append_session_run, locked, read_observed, read_session_runs, resolve_secret, update_observed
from .util import parse_utc, utc_now

TIERS = ("FABLE", "OPUS", "SONNET", "HAIKU")
PLACEHOLDER_TOKEN = "agent-on"          # a keyless source still needs a non-empty token: an empty one prompts for login
DISCOVERY_ENV = "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"
FREE = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
SHARED_ITEMS = ("settings.json", "settings.local.json", "plugins", "skills", "keybindings.json", "CLAUDE.md")
# The routing denylist the old launcher scrubbed, kept whole: anything
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
    "GOOGLE_API_KEY", "GEMINI_API_KEY", "OLLAMA_HOST",
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

def child_env(parent: dict, table: RouteTable, route: Route, *, context: int | None, config_dir: Path | None,
              discover: bool = False, sonnet: Route | None = None, haiku: Route | None = None, harness: str = "claude") -> dict:
    """The environment the harness is spawned with. Every source's auth_env and the routing denylist are removed;
    a keyed source gets NO key variable (the apiKeyHelper supplies it); a keyless one gets the placeholder token.
    Every CODEX_* variable (the operator's own, not just CODEX_HOME) is dropped from BOTH branches — the launcher
    always sets its own CODEX_HOME last. `harness="codex"` scrubs the same way, plus every OPENAI_* variable, and
    sets only CODEX_HOME — no Anthropic variable, no PASS_THROUGH (that's Claude Code's own output-cap control, D12)."""
    for r in (sonnet, haiku):
        if r is not None and r.source != route.source:
            raise ValueError(f"--sonnet/--haiku must name a route on source {route.source!r}; {r.name!r} is on {r.source!r}")
    if harness == "codex":
        # final-fix minor: drop every CODEX_* variable (not just CODEX_HOME) — the operator's own CODEX_API_KEY,
        # honoured by `codex exec`, would otherwise reach every shell-tool child (§1.1c mechanism) — then set
        # CODEX_HOME last so the launcher's own value always wins.
        env = {k: v for k, v in parent.items()
               if k not in SCRUB_ENV and not k.startswith(("ANTHROPIC_", "CLAUDE_", "OPENAI_", "CODEX_"))}
        for src in table.sources.values():
            if src.auth_env:
                env.pop(src.auth_env, None)
        env["CODEX_HOME"] = str(config_dir)
        return env
    env = {k: v for k, v in parent.items()
           if k in PASS_THROUGH or (k not in SCRUB_ENV and k != "CODEX_HOME" and not k.startswith(("ANTHROPIC_", "CLAUDE_")))}
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
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


# ---- the isolated config dir (§11 item 1) --------------------------------------------------------------------

def prepare_config_dir(paths: Paths, cwd: str) -> Path:
    """$STATE/claude-config: the user's settings, plugins, skills, keybindings and CLAUDE.md are symlinks to
    ~/.claude (dangling links are fine — they light up when the native file appears); transcripts, history and
    auto-memory stay per-launcher. The project is marked trusted, because the apiKeyHelper only runs for a
    trusted project. Existing keys of .claude.json are preserved; the write is serialised under a state lock."""
    ensure_state(paths)
    cfg = paths.claude_config_dir
    cfg.mkdir(parents=True, exist_ok=True, mode=0o700)
    native = paths.home / ".claude"
    dotfile = cfg / ".claude.json"
    with locked(paths.state / "locks" / "config.lock"):
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


def write_run_dir(paths: Paths, launch_id: str, *, key: str | None, launch: dict,
                  user_settings: dict | None = None) -> tuple[Path, Path | None]:
    """Create run/<launch-id>/ with the launcher's pid, the launch record, and — for a keyed source — the key at
    mode 0600 plus the settings file whose apiKeyHelper reads it. `user_settings` (F1) is folded shallowly under
    that file so a user's --settings survives; any apiKeyHelper it carried is overwritten by ours last, on purpose —
    the caller is responsible for warning about that. Returns (run_dir, helper settings path or None)."""
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
        merged = {**(user_settings or {}), "apiKeyHelper": f"cat {shlex.quote(str(key_path))}"}
        helper.write_text(json.dumps(merged), encoding="utf-8")
    return d, helper


# ---- the user's --settings, folded under the launcher's (F1) ----------------------------------------------------

def extract_user_settings(claude_args: list[str]) -> tuple[list[str], dict | None]:
    """Pull every --settings/--settings=X out of the user's argv. Claude Code 2.1.263 does not merge repeated
    --settings — the last one wins — and that last-wins behaviour is exactly what let a user's --settings displace
    the launcher's apiKeyHelper file (measured 2026-09-08). X starting with `{` is inline JSON; anything else is a
    file path read as UTF-8 JSON. Several occurrences merge shallowly, later keys overriding earlier ones. Returns
    (args with every --settings removed, the merged dict, or None when there was none)."""
    remaining: list[str] = []
    merged: dict | None = None
    i = 0
    while i < len(claude_args):
        a = claude_args[i]
        if a == "--settings" and i + 1 < len(claude_args):
            value = claude_args[i + 1]
            i += 2
        elif a.startswith("--settings="):
            value = a[len("--settings="):]
            i += 1
        else:
            remaining.append(a)
            i += 1
            continue
        if value.lstrip().startswith("{"):
            try:
                obj = json.loads(value)
            except ValueError as e:
                raise ValueError(f"--settings {value!r} is not valid JSON: {e}") from e
        else:
            try:
                text = Path(value).read_text(encoding="utf-8")
            except OSError as e:
                raise ValueError(f"--settings {value!r}: {e}") from e
            try:
                obj = json.loads(text)
            except ValueError as e:
                raise ValueError(f"--settings {value!r} does not hold valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"--settings {value!r} must be a JSON object")
        merged = {**(merged or {}), **obj}
    return remaining, merged


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

def cost_line(route_name: str, observed_route: dict | None, harness: str = "claude") -> str:
    """One line before spawning. Every field comes from the cost model; a value the probes did not produce is `?`.
    `harness`'s own baseline is shown first; any other harness with a measured baseline is appended (Plan F)."""
    cm = (observed_route or {}).get("cost_model") or {}
    ctx = cm.get("context")
    hb = cm.get("harness_baseline_tokens") or {}
    base = (hb.get(harness) or {}).get("value")
    others = [(h, b) for h, b in hb.items() if h != harness and b.get("value")]
    ctx_s = f"ctx {ctx}" if ctx else "ctx ?"
    if others:                                                                    # more than one harness measured: name each, no "baseline" word
        parts = ([f"{harness} {base} = {round(100 * base / ctx)}%"] if ctx and base else ([f"{harness} {base}"] if base else []))
        parts += [f"{h} {b['value']} = {round(100 * b['value'] / ctx)}%" if ctx else f"{h} {b['value']}" for h, b in others]
        ctx_s += f" ({' · '.join(parts)})"
    elif ctx and base:
        ctx_s += f" ({harness} {base} baseline = {round(100 * base / ctx)}%)"
    elif base:
        ctx_s += f" ({harness} {base} baseline)"
    tok = cm.get("tok_s")
    tok_s = f"{tok:.0f} tok/s" if isinstance(tok, (int, float)) and not isinstance(tok, bool) else "? tok/s"
    usd = cm.get("usd_per_mtok")
    if isinstance(usd, dict) and usd.get("input") is not None and usd.get("output") is not None:
        usd_s = "$0" if not usd.get("input") and not usd.get("output") else f"${usd['input']}/{usd.get('output')} per Mtok"
    else:
        usd_s = "$?"
    cache = {True: "cache ✓", False: "cache ✗"}.get(cm.get("caching"), "cache ?")
    conc = cm.get("concurrency")
    conc_s = "serial" if conc == 1 else (f"{conc}× concurrent" if conc else "concurrency ?")
    th = cm.get("thinking") or {}
    # tokens_on_probe (§ qualify.run_gates, F-fix 2) is usage.output_tokens_details.thinking_tokens when the source
    # reports it, else the probe reply's whole output_tokens as a fallback — which then also counts the probe's
    # short "OK" answer, so the figure here can run a little high on a source without the detailed breakdown.
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
            # Claude Code 2.1.263 records an API error (429, provider error, "prompt too long") as an assistant
            # line with message.model == "<synthetic>" and an all-zero usage. It is not a turn — pricing it reports
            # "unknown" for a session whose only error cost nothing, and it must not be mistaken for first_request
            # (final-fix item 1). A synthetic line with non-zero usage — none observed — is kept, so nothing real
            # is dropped by this check.
            if msg.get("model") == "<synthetic>" and not any(u.values()):
                continue
            key = msg.get("id") or d.get("uuid") or f"line-{len(turns)}"
            turns[key] = {"timestamp": ts, "model": msg.get("model"), "usage": u}
            total = u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]
            if first is None and total > 0:
                first = {"input_tokens_total": total, "usage": u}
    return {"turns": list(turns.values()), "first_request": first, **meta}


def find_transcript(paths: Paths, session_id: str | None, cwd: str, mode: str, started: str,
                    *, config_dir: Path | None = None) -> Path | None:
    """The file to read after exit: the known session id, else (resume without id / continue) the newest transcript
    of this project modified since the launch started."""
    if mode == "no-persistence":
        return None
    root = config_dir or paths.claude_config_dir
    if session_id:
        return root / "projects" / project_slug(cwd) / f"{session_id}.jsonl"
    pdir = root / "projects" / project_slug(cwd)
    if not pdir.exists():
        return None
    since = parse_utc(started).timestamp() - 1
    files = [p for p in pdir.glob("*.jsonl") if p.stat().st_mtime >= since]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def record_session(paths: Paths, launch: dict, *, ended: str, transcript: dict | None, mode: str,
                   harness: str = "claude", harness_version: str | None = None) -> dict:
    """Write last_session for the route and one ledger line for the session (§11 item 4). Best-effort: a missing
    transcript is recorded as {skipped}, never raised. `transcript` is the already-parsed dict (`read_transcript`'s
    result) — the caller resolves the path and reads it first, because a non-Claude harness parses its own
    transcript format. `harness_version` defaults to the transcript's own `version` field when not given."""
    route = launch["route"]
    session_id = None
    this_line = None
    if mode == "no-persistence":
        rec: dict = {"skipped": "no-session-persistence"}
    elif transcript is None:
        rec = {"skipped": "no transcript"}
    else:
        t = transcript
        session_id = t["session_id"] or launch.get("session_id") or launch["launch_id"]
        run = {"launch_id": launch["launch_id"], "route": route, "source": launch["source"], "wire_model": launch["wire_model"],
               "started": launch["started"], "ended": ended, "price": launch["price"], "priced_models": launch.get("priced_models") or {}}
        this_run = attribute_run(t["turns"], run)
        this_line = {**this_run, "session_id": session_id, "mode": mode}
        runs = read_session_runs(paths, session_id) + [this_line]
        total = fold_session(t["turns"], runs)
        fresh = mode in ("fresh", "user-session-id") and len(runs) == 1
        rec = {"id": session_id, "at": ended,
               "first_request": t["first_request"],                                    # null when the transcript had no assistant turn
               "this_run": this_run, "session_total": total,
               "scope_note": "fresh session; this_run == session_total" if fresh else f"{mode}: this_run is this launch's turns; session_total folds {len(runs)} run(s)",
               "duration_ms": int((parse_utc(ended) - parse_utc(launch["started"])).total_seconds() * 1000),
               "effort": t["effort"], "permission_mode": t["permission_mode"], "harness": harness,
               "harness_version": harness_version if harness_version is not None else t.get("version")}

    def mutate(doc: dict) -> None:
        doc["routes"].setdefault(route, empty_route())["last_session"] = rec

    update_observed(paths, mutate)
    if this_line is not None:
        append_session_run(paths, session_id, this_line)
    return rec


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


@dataclass
class LaunchPlan:
    """Everything a launch works out before it's known which harness-specific middle will use it — same
    computation for Claude and Codex (Task 5). Built by `prologue`; `run_launch` (or its Codex counterpart) reads
    it to build the harness-specific launch record, and passes it straight through to `epilogue`."""
    parent: dict
    table: RouteTable
    route: Route
    source: Source
    cwd: str
    args: list[str]
    task_doc: dict | None
    obs_route: dict | None
    warnings: list[str]
    traps: list
    served: dict
    lint: list[dict]
    context: int | None
    key: str | None
    keyless: bool
    price: dict | None
    priced_models: dict
    launch_id: str
    started: str
    swept: list[str]


def prologue(paths: Paths, name: str, args: list[str], *, env: dict | None, cwd: str | None, task: str | None,
            handoff: str, probe_timeout: float, harness_bin: str | None, harness: str) -> LaunchPlan:
    """The harness-agnostic half of a launch: resolve the task handoff (if any) and the route, read the D6
    traps/probe/lint story, resolve the auth key, price the source's models, and sweep dead run directories.
    `harness_bin` feeds `build_context` as `claude_bin` for the `claude` harness or `codex_bin` for `codex` —
    that's the only place `harness` changes this function's behaviour."""
    parent = dict(os.environ if env is None else env)
    task_doc = None
    if task:
        from .tasks import load as load_task, render_prompt, select_handoff
        t = load_task(paths, task)
        h = select_handoff(t, handoff)
        if not os.path.isdir(t["worktree"]):
            raise ValueError(f"launch: task worktree is no longer a directory: {t['worktree']}")
        cwd = t["worktree"]                                                        # the handoff's worktree, as the old task launch did
        args = [*args, render_prompt(t, h)]                                        # the initial prompt is the harness's last positional
        task_doc = {"id": t["id"], "handoff": h["index"], "worktree": os.path.realpath(t["worktree"]), "to_route": h["to_route"]}
    # the physical path: Claude Code derives the transcript slug from process.cwd(), which resolves symlinks
    # (macOS: /var/… is /private/var/…); the trust entry and the transcript lookup must use the same string
    cwd = os.path.realpath(cwd or os.getcwd())
    table = load_routes(paths)
    route = table.resolve(name)
    if task_doc and task_doc.pop("to_route") != route.name:
        raise ValueError(f"launch: route {route.name} is not the handoff's route")
    source = table.sources[route.source]
    observed = read_observed(paths)
    obs_route = observed["routes"].get(route.name)
    warnings: list[str] = []
    kview = knowledge_view(paths, route=route.name, source=route.source, action="launch")             # D6: shown, never gating
    traps = kview["traps"]
    if kview.get("error"):
        warnings.append(f"knowledge unreadable: {kview['error']}")
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
    from .invariants import build_context, evaluate                                # local: invariants imports this module
    bin_kwargs = {"claude_bin": harness_bin} if harness == "claude" else {"codex_bin": harness_bin}
    lint = [r.as_dict() for r in evaluate(build_context(paths, **bin_kwargs), ids=["harness.env.clean", "credential.not_in_child_env"])]
    for r in lint:
        if r["result"] == "fail":
            warnings.append(f"{r['id']}: {r['reason']} — launching anyway (D6)")
    context = ((obs_route or {}).get("cost_model") or {}).get("context")
    if context is None:                                                            # never synced: the declared cap is still better than
        lim = table.effective_limits(route)                                        # Claude Code's 200k assumption for an unknown model
        context = lim.input if lim else None
    key = resolve_secret(paths, source.auth_env, parent) if source.auth_env else None
    if source.auth_env and key is None:
        warnings.append(f"no {source.auth_env} in the environment or {paths.env_file}; Claude Code will not be able to authenticate to {route.source}")
    keyless = source.auth_env is None
    priced = {r.wire_model: _price_of(r, keyless) for r in table.by_source(route.source)}
    price = _price_of(route, keyless)
    priced_models = {m: p for m, p in priced.items() if p is not None}
    swept = sweep_run_dirs(paths)
    launch_id = ulid()
    started = utc_now()
    return LaunchPlan(parent=parent, table=table, route=route, source=source, cwd=cwd, args=args, task_doc=task_doc,
                      obs_route=obs_route, warnings=warnings, traps=traps, served=served, lint=lint, context=context,
                      key=key, keyless=keyless, price=price, priced_models=priced_models, launch_id=launch_id,
                      started=started, swept=swept)


def epilogue(paths: Paths, plan: LaunchPlan, launch: dict, *, code: int, ended: str, transcript: dict | None,
            mode: str, harness: str, harness_version: str | None, doc: dict) -> dict:
    """Read the session back into the cost ledger (`record_session`), fold `exit_code`/`last_session` into `doc`,
    and append a knowledge cost observation when there's a completed run to observe. `transcript` is the
    already-parsed transcript (`record_session`'s own contract) — the caller finds and parses it, and sets
    `doc["transcript"]` (the path), before calling this: finding that path is harness-specific."""
    rec = record_session(paths, launch, ended=ended, transcript=transcript, mode=mode, harness=harness, harness_version=harness_version)
    doc.update({"exit_code": code, "last_session": rec})
    doc["knowledge"] = None
    if paths.knowledge_dir.is_dir() and "this_run" in rec:
        tr = rec["this_run"]
        u = tr["usage"]
        o = knowledge_append(paths, "observations", {"route": plan.route.name, "kind": "cost",
                                                     "values": {"turns": tr["turns"], "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                                                                "cache_read_input_tokens": u["cache_read_input_tokens"], "cache_creation_input_tokens": u["cache_creation_input_tokens"],
                                                                "cost_usd": tr["cost_usd"]},
                                                     "evidence": f"session {launch['session_id']} run {launch['launch_id']}", "session": launch["session_id"]}, now=ended)
        doc["knowledge"] = {"observation": o["id"]}
    return doc


def run_launch(paths: Paths, name: str, claude_args: list[str], *, harness: str = "claude", discover: bool = False,
               sonnet: str | None = None, haiku: str | None = None, dry_run: bool = False, env: dict | None = None,
               claude_bin: str | None = None, codex_bin: str | None = None, cwd: str | None = None, probe_timeout: float = 2.0,
               announce: bool = True, task: str | None = None, handoff: str = "latest",
               session_store: str = "isolated") -> dict:
    if session_store not in ("isolated", "native"):
        raise ValueError("session_store must be 'isolated' or 'native'")
    if harness == "codex":
        if session_store != "isolated":
            raise ValueError("--session-store applies to Claude Code only")
        from .harness_codex import run_launch_codex
        return run_launch_codex(paths, name, claude_args, dry_run=dry_run, env=env, codex_bin=codex_bin, cwd=cwd,
                                probe_timeout=probe_timeout, announce=announce, task=task, handoff=handoff)
    if harness != "claude":
        raise ValueError(f"harness {harness!r} is not bound yet (Plan F adds codex)")
    plan = prologue(paths, name, claude_args, env=env, cwd=cwd, task=task, handoff=handoff, probe_timeout=probe_timeout,
                    harness_bin=claude_bin, harness=harness)
    table, route, source = plan.table, plan.route, plan.source
    sonnet_r = table.resolve(sonnet) if sonnet else None
    haiku_r = table.resolve(haiku) if haiku else None
    # F1: Claude Code does not merge repeated --settings — the last one wins — so a user's --settings would silently
    # displace the launcher's apiKeyHelper file. A keyed source therefore extracts it and folds it under ours
    # (write_run_dir); a keyless source has no helper file to displace, so the user's --settings is left untouched.
    stripped_args, user_settings = extract_user_settings(plan.args)
    settings_merged = plan.key is not None and user_settings is not None
    claude_args = stripped_args if plan.key is not None else plan.args
    if settings_merged and "apiKeyHelper" in user_settings:
        plan.warnings.append("user --settings apiKeyHelper replaced by the launcher's credential helper")
    # Native mode deliberately leaves CLAUDE_CONFIG_DIR unset. Claude Code then uses
    # ~/.claude directly, so its picker, --continue, --resume, history, session-env,
    # and auto-memory all address the same store as a normal `claude` launch.
    if session_store == "isolated":
        config_dir = prepare_config_dir(paths, plan.cwd)
    else:
        ensure_state(paths)
        config_dir = None
    transcript_root = paths.claude_config_dir if config_dir is not None else paths.home / ".claude"
    args, session_id, mode = session_args(claude_args)
    explicit_effort = explicit_claude_effort(args)
    effort = launch_effort_metadata(source, route)
    effort = {**effort, "explicit_cli_effort": explicit_effort}
    if source.backend == "omlx":
        effort = {**effort, "receipt": str(paths.state / "effort" / f"{plan.launch_id}.jsonl")}
        if effort["profile"] is None:
            plan.warnings.append("oMLX model has no effort profile: Claude default/UI effort passes through un-applied; explicit --effort is rejected")
    launch = {"launch_id": plan.launch_id, "route": route.name, "source": route.source, "wire_model": route.wire_model, "started": plan.started,
              "session_id": session_id, "mode": mode, "cwd": plan.cwd, "price": plan.price,
              "priced_models": plan.priced_models, "context": plan.context, "claude_args": args, "effort": effort,
              "session_store": session_store}
    cenv = child_env(plan.parent, table, route, context=plan.context, config_dir=config_dir, discover=discover, sonnet=sonnet_r, haiku=haiku_r)
    line = cost_line(route.name, plan.obs_route)
    doc = {"command": "launch", "copy": describe_copy(paths), "route": route.name, "wire_model": route.wire_model, "base_url": source.base_url,
           "launch_id": plan.launch_id, "session": {"id": session_id, "mode": mode}, "cost_line": line, "invariants": [plan.served, *plan.lint],
           "env_keys": sorted(k for k in cenv if k.startswith(("ANTHROPIC_", "CLAUDE_"))), "swept": plan.swept, "warnings": plan.warnings,
           "settings_merged": settings_merged, "traps": plan.traps, "task": plan.task_doc, "effort": effort,
           "session_store": session_store}
    binary = claude_bin or shutil.which("claude") or "claude"
    if dry_run:
        doc.update({"dry_run": True, "argv": [binary, *(["--settings", "<run-dir>/settings.json"] if plan.key is not None else []), *args]})
        return doc
    run_dir, helper = write_run_dir(paths, plan.launch_id, key=plan.key, launch=launch, user_settings=user_settings)
    argv = [binary, *(["--settings", str(helper)] if helper else []), *args]   # a keyed source's --settings is always ours (F1): the user's was folded into it, or there is none
    adapter = None
    try:
        if source.backend == "omlx":
            adapter_routes = [r for r in (route, sonnet_r, haiku_r) if r is not None]
            adapter = OmlxEffortAdapter(source.base_url, adapter_routes, Path(effort["receipt"]),
                                        strict_unknown=explicit_effort is not None)
            adapter.start()
            cenv["ANTHROPIC_BASE_URL"] = adapter.base_url
        if plan.task_doc:
            from .tasks import launched
            launched(paths, plan.task_doc["id"], handoff=str(plan.task_doc["handoff"]), launch_id=plan.launch_id, route=route.name)
        if announce:
            print(line, file=sys.stderr)                                          # the §12 line, before spawning
            for warning in plan.warnings:
                print(f"warning: {warning}", file=sys.stderr)
        code = spawn(argv, cenv, plan.cwd)
    finally:
        if adapter is not None:
            adapter.close()
            doc["effort"] = {**effort, "requests": adapter.records()}
        shutil.rmtree(run_dir, ignore_errors=True)                                 # the key never outlives the child
    ended = utc_ceil()                                                            # inclusive of the last turn's milliseconds
    transcript_path = find_transcript(paths, session_id, plan.cwd, mode, plan.started, config_dir=transcript_root)
    parsed = read_transcript(transcript_path) if transcript_path and transcript_path.exists() else None
    doc["transcript"] = str(transcript_path) if transcript_path else None
    return epilogue(paths, plan, launch, code=code, ended=ended, transcript=parsed, mode=mode, harness="claude",
                    harness_version=None, doc=doc)
