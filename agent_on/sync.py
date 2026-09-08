"""`agent-on sync` (§9): probe every source; refresh catalogs, served flags, configured/advertised limits and spend;
rewrite routes.discovered.toml; report orphaned packaged routes. Never writes `verified` (that is `qualify --limits`), never touches
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

    orphaned: list[str] = []
    copy = describe_copy(paths)   # resolved here, outside the lock: `mutate` never spawns a subprocess while holding it

    def mutate(doc: dict) -> None:
        doc["copy"] = copy
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
                    orphaned.append(rname)
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
            "discovered": [r.name for r in discovered], "shadowed": list(table.shadowed), "orphaned": sorted(orphaned),
            "spend": spend, "invariants": invariants}
