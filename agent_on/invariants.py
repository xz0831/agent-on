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

from .harness import child_env
from .paths import Paths, describe_copy
from .schemas.errors import RULES, SchemaError
from .schemas.knowledge import validate_file
from .schemas.observed import HARNESSES, forbid_claude_cost
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
    codex_version: str | None


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


def claude_code_version(binary: str | None = None) -> str | None:
    """The `claude --version` a launch will actually run: `binary` when given (a launch's own claude_bin, e.g.
    AGENT_ON_CLAUDE_BIN), else the same PATH lookup as before (final-fix item 5)."""
    exe = binary or shutil.which("claude")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"\s*(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


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


def build_context(paths: Paths, *, with_claude_code: bool = False, claude_bin: str | None = None,
                  codex_bin: str | None = None) -> Context:
    try:
        table, err = load_routes(paths), None
    except (SchemaError, OSError) as e:
        table, err = None, str(e)
    try:
        observed = read_observed(paths)
    except (SchemaError, ValueError, OSError) as e:
        observed = {"_error": str(e), "copy": None, "sources": {}, "routes": {}, "last_check": None, "last_gate_run": None, "spend": {}}
    return Context(paths, table, err, observed, paths.code_tree, paths.home,
                   claude_code_version(claude_bin) if with_claude_code else None,
                   codex_version(codex_bin) if with_claude_code else None)


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
           fix="agent-on install")
def copy_single(ctx: Context):
    shim = ctx.paths.shim
    if not shim.is_symlink():
        if shim.exists():
            return fail(f"{shim} exists but is not a symlink")
        return skip(f"no shim at {shim} — run agent-on install")
    target = Path(os.readlink(shim))
    target = (target if target.is_absolute() else shim.parent / target).resolve()
    expected = (ctx.tree / "bin" / "agent-on").resolve()
    if target != expected:
        return fail(f"{shim} -> {target}, not {expected}")
    dirty = describe_copy(ctx.paths)["dirty"]
    return ok("shim points here" + (" (tree dirty — reported, not failed)" if dirty else ""))


@invariant("credential.not_in_child_env",
           statement="no source credential reaches the child environment of any route's launch, on either harness",
           fix="the launcher must scrub every source's auth_env and the routing denylist before spawn, for both harness branches of child_env (§11)")
def credential_not_in_child_env(ctx: Context):
    # final-fix item 3: the old check computed child_env for the claude harness only, so a regression in the
    # separate codex branch would still report pass. Loop both harnesses; a marker parent that also carries
    # OPENAI_API_KEY and CODEX_HOME proves the codex branch scrubs them too.
    if ctx.routes is None:
        return skip(f"routes did not load: {ctx.routes_error}")
    markers = {src.auth_env: f"SECRET-{src.auth_env}" for src in ctx.routes.sources.values() if src.auth_env}
    parent = {**markers, "ANTHROPIC_API_KEY": "SECRET-inherited", "ANTHROPIC_AUTH_TOKEN": "SECRET-inherited",
              "OPENAI_API_KEY": "SECRET-inherited", "CODEX_HOME": "SECRET-inherited", "PATH": "/usr/bin"}
    leaks: list[str] = []
    checked = 0
    for route in ctx.routes.routes.values():
        if not ctx.routes.sources[route.source].available:
            continue
        for h in HARNESSES:
            checked += 1
            env = child_env(parent, ctx.routes, route, context=None, config_dir=Path("/nonexistent"), harness=h)
            leaks += [f"{h}:{route.name}:{k}" for k, v in env.items() if "SECRET-" in str(v)]
    if leaks:
        return fail(f"a credential reached the child environment: {leaks[:5]}")
    names = ", ".join(sorted(markers)) or "none declared"
    return ok(f"{checked} available route/harness pair(s): no source credential ({names}) reaches the child environment")


ENV_DENY = ("ANTHROPIC_*", "CLAUDE_CODE_MAX_*", "*_PROXY")


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
    bad = [k for k in (d.get("env") or {}) if any(fnmatch.fnmatchcase(k.upper(), pat) for pat in ENV_DENY)]
    if bad:
        return fail(f"env sets {bad}")
    if "apiKeyHelper" in d:
        return fail("apiKeyHelper is set in the shared settings")
    m = d.get("model")
    subagent = (d.get("env") or {}).get("CLAUDE_CODE_SUBAGENT_MODEL")
    details = []
    if m:
        details.append(f"model = {m!r} is overridden by explicit --model")
    if subagent:
        details.append(f"CLAUDE_CODE_SUBAGENT_MODEL = {subagent!r} is overridden by the per-launch settings overlay")
    return ok("clean" + (f" ({'; '.join(details)})" if details else ""))


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
           fix="fix or remove the offending line; `agent-on learn` validates before appending")
def knowledge_typed(ctx: Context):
    kdir = ctx.paths.knowledge_dir                     # §10: beside routes.toml, never the code tree (a sandbox lints real code but owns its knowledge)
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


@invariant("docs.current",
           statement="docs/ROUTES.md is the render of routes.toml (a stale page is a lie about L1)",
           fix="run scripts/routes-doc.py and commit docs/ROUTES.md")
def docs_current(ctx: Context):
    page = ctx.tree / "docs" / "ROUTES.md"
    if not page.exists():
        return skip("no docs/ROUTES.md in this tree")
    from .docs import render_routes_doc
    from .schemas.routes import load_declared_routes
    try:
        table = load_declared_routes(ctx.paths.__class__(checkout=ctx.tree, state=ctx.paths.state, home=ctx.home, tree=ctx.tree))
    except (SchemaError, OSError) as e:
        return fail(f"routes.toml unreadable: {e}")
    return ok("current") if page.read_text(encoding="utf-8") == render_routes_doc(table) else fail("docs/ROUTES.md is stale — run scripts/routes-doc.py")


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
           statement="every wire's last qualification fingerprint still matches the effective configuration, the wire model, the source identity and the harness version",
           fix="re-run `agent-on qualify <route>`")
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
