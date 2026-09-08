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
        pricing = entry.get("pricing")
        pricing = pricing if isinstance(pricing, dict) else {}

        def per_mtok(v):
            """A catalog price we cannot read as a number is an absent price, not a crash (some entries say 'n/a')."""
            try:
                return None if v is None else round(float(v) * 1_000_000, 6)
            except (TypeError, ValueError):
                return None

        if per_mtok(pricing.get("prompt")) is not None and per_mtok(pricing.get("completion")) is not None:
            price = Price(per_mtok(pricing["prompt"]), per_mtok(pricing["completion"]), per_mtok(pricing.get("input_cache_read")),
                          per_mtok(pricing.get("input_cache_write")),
                          f"{src}.pricing ({today})" + ("" if per_mtok(pricing.get("input_cache_write")) is not None else "; no cache-write price published"))
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
        return {"command": "add", "copy": describe_copy(paths), "route": name, "written": False, "block": None,
                "invariants": [served.as_dict()]}
    route = route_from_catalog(name, source, probe.catalog.get(model), (alias,) if alias else (), utc_now()[:10])
    block = route_block(route)
    with checkout_locked(paths):
        current = paths.routes_toml.read_text(encoding="utf-8")   # re-read under the lock: another add may have landed
        _, packaged_now, _ = parse_routes_text(current, packaged=True)
        if name in packaged_now:
            raise SchemaError("routes.unique", f"{name!r} is already packaged (added concurrently)")
        hold = float(os.environ.get(HOLD_ENV, "0"))
        if hold:
            time.sleep(hold / 1000)
        candidate = current.rstrip("\n") + "\n\n" + block
        parse_routes_text(candidate, packaged=True)                # every rule, including routes.unique, on the merged text
        atomic_write(paths.routes_toml, candidate)
    unique = [r.as_dict() for r in evaluate(build_context(paths), ids=["route.unique"])]
    return {"command": "add", "copy": describe_copy(paths), "route": name, "written": True, "block": block,
            "invariants": [served.as_dict()] + unique}
