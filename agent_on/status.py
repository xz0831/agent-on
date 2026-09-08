"""`agent-on status [route] [--check]` (§9): L1 beside L2 for every route or one; with --check every invariant is
evaluated and `last_check` written — never `last_gate_run`, which only the gate runner writes (Q4)."""
from __future__ import annotations

from .cli import copy_line, invariant_lines
from .harness import cost_line
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
        if v["observed"]:
            lines.append("  " + cost_line(n, v["observed"]))
            ls = v["observed"].get("last_session")
            if ls:
                lines.append("  last session: " + (f"skipped ({ls['skipped']})" if "skipped" in ls else
                             f"{ls['id'][:8]} · this run {ls['this_run']['turns']} turns ${ls['this_run']['cost_usd']} · session {ls['session_total']['turns']} turns ${ls['session_total']['cost_usd']}"))
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
