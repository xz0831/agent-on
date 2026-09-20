"""L1 — the route table (§6). The only place the routes.toml rules live (D5); the `RULES` ids name them."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit

from ..util import canonical_json, sha16
from .errors import SchemaError

L1_CONFIDENCES = ("provider", "owned-policy", "configured")   # `advertised` and `verified` are L2 tiers (§7)
SOURCE_BACKENDS = ("passthrough", "omlx", "splash", "openrouter")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_SOURCE_KEYS = ("base_url", "auth_env", "catalog", "discover", "backend", "billing", "available", "limits")
_ROUTE_KEYS = ("wire_model", "aliases", "limits", "reasoning", "price")
SOURCE_BILLING = ("free", "metered", "unknown")


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
    effort_map: tuple[tuple[str, str | int], ...] = ()

    def map_effort(self, effort: str) -> str | int:
        return dict(self.effort_map).get(effort, effort)


@dataclass(frozen=True)
class Source:
    name: str
    base_url: str | None
    auth_env: str | None
    catalog: str | None
    discover: bool
    limits: Limits | None
    backend: str = "passthrough"
    billing: str = "unknown"
    available: bool = True

    def catalog_url(self) -> str | None:
        if not self.available or self.base_url is None or self.catalog is None:
            return None
        if self.catalog.startswith(("http://", "https://")):
            return self.catalog                                            # absolute: verbatim
        return urljoin(self.base_url.rstrip("/") + "/", self.catalog.lstrip("/"))   # relative: joined

    def host(self) -> str:
        if self.base_url is None:
            return ""
        return urlsplit(self.base_url).hostname or ""

    def port(self) -> int:
        if self.base_url is None:
            return 0
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
    redirects: dict[str, str] | None = None

    def resolve(self, name_or_alias: str) -> Route:
        name_or_alias = (self.redirects or {}).get(name_or_alias, name_or_alias)
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
        doc = {"source": {"base_url": src.base_url, "auth_env": src.auth_env, "catalog": src.catalog,
                          "backend": src.backend, "billing": src.billing, "available": src.available},
               "route": {"wire_model": route.wire_model, "limits": lim.as_dict() if lim else None,
                         "reasoning": None if route.reasoning is None else {
                             "supported": route.reasoning.supported, "efforts": list(route.reasoning.efforts),
                             "provider_efforts": list(route.reasoning.provider_efforts),
                             "effort_map": dict(route.reasoning.effort_map)},
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
    if len(set(efforts)) != len(efforts):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.efforts contains a duplicate")
    raw_map = d.get("effort_map", {})
    if not isinstance(raw_map, dict):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.effort_map must be a table")
    effort_map: list[tuple[str, str | int]] = []
    for key, value in raw_map.items():
        if not isinstance(key, str) or not key:
            raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.effort_map keys must be non-empty strings")
        if isinstance(value, bool) or not ((isinstance(value, str) and value) or (isinstance(value, int) and 1 <= value <= 100)):
            raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.effort_map.{key} must be a non-empty string or integer 1..100")
        effort_map.append((key, value))
    if effort_map and set(dict(effort_map)) != set(efforts):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.effort_map must map every declared effort exactly once")
    if effort_map and not set(dict(effort_map)).issubset(CLAUDE_EFFORTS):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.effort_map keys must be Claude levels {CLAUDE_EFFORTS}")
    supported = d.get("supported", bool(efforts or provider_efforts))
    if not isinstance(supported, bool):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.supported must be a bool")
    confidence = d.get("confidence")
    if confidence is not None and confidence not in L1_CONFIDENCES:
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.confidence must be one of {L1_CONFIDENCES}")
    if not isinstance(d.get("source"), str) or not d["source"]:
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.source must say where it came from")
    for k in d:
        if k not in ("supported", "efforts", "provider_efforts", "effort_map", "confidence", "source"):
            raise SchemaError("routes.reasoning.shape", f"{where}: unknown reasoning key {k!r}")
    return Reasoning(supported, efforts, provider_efforts, confidence, d["source"], tuple(effort_map))


def _parse_source(name: str, d) -> Source:
    _no_globs(name, "source")
    if not isinstance(d, dict):
        raise SchemaError("routes.source.shape", f"source {name!r} must be a table")
    available = d.get("available", True)
    if not isinstance(available, bool):
        raise SchemaError("routes.source.shape", f"source {name!r}: available must be boolean")
    base = d.get("base_url")
    if base is not None and (not isinstance(base, str) or not base.startswith(("http://", "https://"))):
        raise SchemaError("routes.source.shape", f"source {name!r}: base_url must be an http(s) URL")
    if available and base is None:
        raise SchemaError("routes.source.shape", f"source {name!r}: an available source requires base_url")
    for k in ("auth_env", "catalog"):
        if d.get(k) is not None and (not isinstance(d[k], str) or not d[k]):
            raise SchemaError("routes.source.shape", f"source {name!r}: {k} must be a non-empty string")
    if not isinstance(d.get("discover", False), bool):
        raise SchemaError("routes.source.shape", f"source {name!r}: discover must be a bool")
    backend = d.get("backend", "passthrough")
    if backend not in SOURCE_BACKENDS:
        raise SchemaError("routes.source.shape", f"source {name!r}: backend must be one of {SOURCE_BACKENDS}")
    for k in d:
        if k not in _SOURCE_KEYS:
            raise SchemaError("routes.source.shape", f"source {name!r}: unknown key {k!r}")
    billing = d.get("billing", "unknown")
    if billing not in SOURCE_BILLING:
        raise SchemaError("routes.source.shape", f"source {name!r}: billing must be one of {SOURCE_BILLING}")
    return Source(name, base, d.get("auth_env"), d.get("catalog"), d.get("discover", False),
                  _parse_limits(d["limits"], f"source {name!r}") if "limits" in d else None,
                  backend, billing, available)


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
    reasoning = _parse_reasoning(d["reasoning"], f"route {name!r}") if "reasoning" in d else None
    if reasoning and reasoning.effort_map and sources[src].backend != "omlx":
        raise SchemaError("routes.reasoning.shape", f"route {name!r}: reasoning.effort_map is only used by backend='omlx'")
    return Route(name, src, wm, tuple(aliases),
                 _parse_limits(d["limits"], f"route {name!r}") if "limits" in d else None,
                 reasoning,
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
        if k not in ("version", "sources", "routes", "redirects"):
            raise SchemaError("routes.version", f"unknown top-level key {k!r}")
    if packaged:
        raw = doc.get("sources")
        if not isinstance(raw, dict) or not raw:
            raise SchemaError("routes.source.shape", "at least one [sources.<name>] table is required")
        srcs = {n: _parse_source(n, d) for n, d in raw.items()}
    else:
        if "sources" in doc:
            raise SchemaError("routes.source.shape", "routes.discovered.toml may not declare sources")
        if "redirects" in doc:
            raise SchemaError("routes.route.name", "routes.discovered.toml may not declare redirects")
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
    if packaged:
        _parse_redirects(doc.get("redirects"), routes)
    return srcs, routes, tuple(stale)


def _parse_redirects(raw, routes: dict[str, Route]) -> dict[str, str]:
    """Compatibility names for renamed routes.

    Redirects resolve only at the CLI boundary. They are not routes and never
    carry observations or qualifications to the target identity.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SchemaError("routes.route.name", "[redirects] must map old route names to current route names")
    aliases = {a for route in routes.values() for a in route.aliases}
    out: dict[str, str] = {}
    for old, new in raw.items():
        if not isinstance(old, str) or "/" not in old or not isinstance(new, str) or not new:
            raise SchemaError("routes.route.name", "redirect names and targets must be non-empty route names")
        if old in routes or old in aliases:
            raise SchemaError("routes.unique", f"redirect {old!r} collides with a route or alias")
        if new not in routes:
            raise SchemaError("routes.route.name", f"redirect {old!r} targets missing route {new!r}")
        out[old] = new
    return out


def redirects_from_text(text: str, routes: dict[str, Route]) -> dict[str, str]:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SchemaError("routes.version", f"not valid TOML: {e}") from None
    return _parse_redirects(doc.get("redirects"), routes)


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


def apply_source_overrides(text: str, sources: dict[str, Source]) -> dict[str, Source]:
    """Apply host-local source availability and addresses.

    The state file is intentionally narrow: it may only replace ``base_url`` and
    ``available`` on an already-declared source. Routes, credentials, limits, billing,
    and source identity remain governed by the tracked routes.toml.
    """
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SchemaError("routes.local.shape", f"routes.local.toml is not valid TOML: {e}") from None
    if doc.get("version") != 1:
        raise SchemaError("routes.local.shape", f"routes.local.toml version must be 1, got {doc.get('version')!r}")
    for key in doc:
        if key not in ("version", "sources"):
            raise SchemaError("routes.local.shape", f"routes.local.toml: unknown top-level key {key!r}")
    raw = doc.get("sources") or {}
    if not isinstance(raw, dict):
        raise SchemaError("routes.local.shape", "routes.local.toml: sources must be a table")
    out = dict(sources)
    for name, override in raw.items():
        if name not in out:
            raise SchemaError("routes.local.shape", f"routes.local.toml: source {name!r} is not declared in routes.toml")
        allowed = {"base_url", "available"}
        if not isinstance(override, dict) or not override or not set(override) <= allowed:
            raise SchemaError("routes.local.shape", f"routes.local.toml: source {name!r} may override base_url and available only")
        base_url = override.get("base_url", out[name].base_url)
        available = override.get("available", out[name].available)
        if base_url is not None and (not isinstance(base_url, str) or not base_url.startswith(("http://", "https://"))):
            raise SchemaError("routes.local.shape", f"routes.local.toml: source {name!r} base_url must be an http(s) URL")
        if not isinstance(available, bool):
            raise SchemaError("routes.local.shape", f"routes.local.toml: source {name!r} available must be boolean")
        if available and base_url is None:
            raise SchemaError("routes.local.shape", f"routes.local.toml: available source {name!r} requires base_url")
        out[name] = replace(out[name], base_url=base_url, available=available)
    return out


def load_packaged_routes(paths) -> tuple[dict[str, Source], dict[str, Route]]:
    srcs, packaged, _ = parse_routes_text(paths.routes_toml.read_text(encoding="utf-8"), packaged=True)
    if paths.local_routes_toml.exists():
        srcs = apply_source_overrides(paths.local_routes_toml.read_text(encoding="utf-8"), srcs)
    return srcs, packaged


def load_declared_routes(paths) -> RouteTable:
    """Tracked L1 only: no discovered routes and no host-local address overrides."""
    text = paths.routes_toml.read_text(encoding="utf-8")
    srcs, packaged, _ = parse_routes_text(text, packaged=True)
    return RouteTable(srcs, packaged, redirects=redirects_from_text(text, packaged))


def load_routes(paths) -> RouteTable:
    packaged_text = paths.routes_toml.read_text(encoding="utf-8")
    srcs, packaged, _ = parse_routes_text(packaged_text, packaged=True)
    if paths.local_routes_toml.exists():
        srcs = apply_source_overrides(paths.local_routes_toml.read_text(encoding="utf-8"), srcs)
    discovered: dict[str, Route] = {}
    if paths.discovered_toml.exists():
        _, discovered, _ = parse_routes_text(paths.discovered_toml.read_text(encoding="utf-8"), packaged=False, sources=srcs)
    routes, shadowed = merge_tables(packaged, discovered)
    return RouteTable(srcs, routes, shadowed, redirects_from_text(packaged_text, packaged))


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
        if r.effort_map:
            body = ", ".join(f"{_key(k)} = {_val(v)}" for k, v in r.effort_map)
            lines.append(f"effort_map = {{ {body} }}")
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
