"""L1 — the route table (§6). The only place the routes.toml rules live (D5); the `RULES` ids name them."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from ..util import canonical_json, sha16
from .errors import SchemaError

L1_CONFIDENCES = ("provider", "owned-policy", "configured")   # `advertised` and `verified` are L2 tiers (§7)
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_SOURCE_KEYS = ("base_url", "auth_env", "catalog", "discover", "limits")
_ROUTE_KEYS = ("wire_model", "aliases", "limits", "reasoning", "price")


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


@dataclass(frozen=True)
class Source:
    name: str
    base_url: str
    auth_env: str | None
    catalog: str | None
    discover: bool
    limits: Limits | None

    def catalog_url(self) -> str | None:
        if self.catalog is None:
            return None
        if self.catalog.startswith(("http://", "https://")):
            return self.catalog                                            # absolute: verbatim
        return urljoin(self.base_url.rstrip("/") + "/", self.catalog.lstrip("/"))   # relative: joined

    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def port(self) -> int:
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

    def resolve(self, name_or_alias: str) -> Route:
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
        doc = {"source": {"base_url": src.base_url, "auth_env": src.auth_env, "catalog": src.catalog},
               "route": {"wire_model": route.wire_model, "limits": lim.as_dict() if lim else None,
                         "reasoning": None if route.reasoning is None else {
                             "supported": route.reasoning.supported, "efforts": list(route.reasoning.efforts),
                             "provider_efforts": list(route.reasoning.provider_efforts)},
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
    supported = d.get("supported", bool(efforts or provider_efforts))
    if not isinstance(supported, bool):
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.supported must be a bool")
    confidence = d.get("confidence")
    if confidence is not None and confidence not in L1_CONFIDENCES:
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.confidence must be one of {L1_CONFIDENCES}")
    if not isinstance(d.get("source"), str) or not d["source"]:
        raise SchemaError("routes.reasoning.shape", f"{where}: reasoning.source must say where it came from")
    for k in d:
        if k not in ("supported", "efforts", "provider_efforts", "confidence", "source"):
            raise SchemaError("routes.reasoning.shape", f"{where}: unknown reasoning key {k!r}")
    return Reasoning(supported, efforts, provider_efforts, confidence, d["source"])


def _parse_source(name: str, d) -> Source:
    _no_globs(name, "source")
    if not isinstance(d, dict):
        raise SchemaError("routes.source.shape", f"source {name!r} must be a table")
    base = d.get("base_url")
    if not isinstance(base, str) or not base.startswith(("http://", "https://")):
        raise SchemaError("routes.source.shape", f"source {name!r}: base_url must be an http(s) URL")
    for k in ("auth_env", "catalog"):
        if d.get(k) is not None and (not isinstance(d[k], str) or not d[k]):
            raise SchemaError("routes.source.shape", f"source {name!r}: {k} must be a non-empty string")
    if not isinstance(d.get("discover", False), bool):
        raise SchemaError("routes.source.shape", f"source {name!r}: discover must be a bool")
    for k in d:
        if k not in _SOURCE_KEYS:
            raise SchemaError("routes.source.shape", f"source {name!r}: unknown key {k!r}")
    return Source(name, base, d.get("auth_env"), d.get("catalog"), d.get("discover", False),
                  _parse_limits(d["limits"], f"source {name!r}") if "limits" in d else None)


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
    return Route(name, src, wm, tuple(aliases),
                 _parse_limits(d["limits"], f"route {name!r}") if "limits" in d else None,
                 _parse_reasoning(d["reasoning"], f"route {name!r}") if "reasoning" in d else None,
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
        if k not in ("version", "sources", "routes"):
            raise SchemaError("routes.version", f"unknown top-level key {k!r}")
    if packaged:
        raw = doc.get("sources")
        if not isinstance(raw, dict) or not raw:
            raise SchemaError("routes.source.shape", "at least one [sources.<name>] table is required")
        srcs = {n: _parse_source(n, d) for n, d in raw.items()}
    else:
        if "sources" in doc:
            raise SchemaError("routes.source.shape", "routes.discovered.toml may not declare sources")
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
    return srcs, routes, tuple(stale)


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


def load_routes(paths) -> RouteTable:
    srcs, packaged, _ = parse_routes_text(paths.routes_toml.read_text(encoding="utf-8"), packaged=True)
    discovered: dict[str, Route] = {}
    if paths.discovered_toml.exists():
        _, discovered, _ = parse_routes_text(paths.discovered_toml.read_text(encoding="utf-8"), packaged=False, sources=srcs)
    routes, shadowed = merge_tables(packaged, discovered)
    return RouteTable(srcs, routes, shadowed)


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
