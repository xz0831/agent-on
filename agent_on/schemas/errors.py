"""Every field contract of the system, stated once (D5, F14). A validator may only raise a rule listed here;
`schema.complete` lints that every listed rule is raised somewhere."""
from __future__ import annotations

RULES: dict[str, str] = {
    # L1 — routes.toml / routes.discovered.toml (§6)
    "routes.version": "the file is valid TOML with version = 1 and only version/sources/routes at top level",
    "routes.source.shape": "a source has an http(s) base_url; optional auth_env, catalog, discover (bool), limits; nothing else — and only routes.toml declares sources",
    "routes.route.name": "a route name is <source>/<model> and the source is declared",
    "routes.route.shape": "a route table has only wire_model, aliases, limits, reasoning, price",
    "routes.route.wire_model": "wire_model is a non-empty string; it defaults to the name after the first '/'",
    "routes.limits.shape": "limits carry positive-integer input and/or output, a confidence in {provider, owned-policy, configured} and a source string",
    "routes.limits.no_globs": "no source or route key contains '*' or '?' — there are no globs (§6)",
    "routes.reasoning.shape": "reasoning has efforts / provider_efforts (lists of strings), an optional confidence in {provider, owned-policy, configured}, a source string, and an optional supported (bool; defaults to whether any efforts are listed) — it may stand alone when a catalog names only parameters, never invented levels",
    "routes.price.shape": "price has input_usd_per_mtok and output_usd_per_mtok (numbers ≥ 0), optional cache_read/cache_write, and a source string",
    "routes.alias.shape": "aliases is a list of non-empty strings without '/'",
    "routes.unique": "no two routes share a name, an alias, or (source, wire_model); a discovered route may not reuse a packaged alias",
    # L2 — observed.json (§7)
    "observed.shape": "observed.json has version, copy, sources, routes, last_check, last_gate_run, spend; each present record carries every key of its empty record",
    "observed.route.shape": "a route observation carries every key of the empty route record; unmeasured is null; caching is true, false or 'unknown'; served is true, false or null",
    "observed.no_claude_cost": "no key named total_cost_usd or costUSD anywhere — Claude Code's own cost figure is never copied (F11)",
    "observed.session.shape": "last_session is {skipped: reason} or the full record; this_run and session_total carry turns, usage (four fields) and cost_usd = number ≥ 0 or 'unknown'",
    "observed.qualification.shape": "qualifications is an object keyed by wire (messages, responses); each entry has pass, gates{name: bool}, thinking_block_seen, completed, at, wire (matching its key), and a fingerprint with effective_route_sha, wire_model, source_identity, harness_version",
    # L5 — knowledge/*.jsonl (§10)
    "knowledge.record": "a record has id (prefixed by its kind), ts, and the fields of its kind",
}


class SchemaError(ValueError):
    """A contract violation, named by the rule it breaks. Constructing one with an unregistered rule is a bug."""

    def __init__(self, rule: str, detail: str):
        if rule not in RULES:
            raise KeyError(f"unregistered schema rule {rule!r} — add it to RULES with its statement")
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail
