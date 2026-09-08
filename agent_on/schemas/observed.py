"""L2 — the shape of $STATE/observed.json (§7). Unmeasured is null, never absent; caching is three-valued;
Claude Code's own cost figure is rejected anywhere (F11)."""
from __future__ import annotations

from .errors import SchemaError

OBSERVED_VERSION = 1
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
FORBIDDEN_KEYS = ("total_cost_usd", "costUSD")
CACHING_VALUES = (True, False, "unknown")
SESSION_KEYS = ("id", "at", "first_request", "this_run", "session_total", "scope_note", "duration_ms", "effort", "permission_mode", "claude_code")
CHECK_KEYS = ("at", "commit", "result", "skipped")
GATE_RUN_KEYS = ("at", "commit", "result", "tests", "verifiers", "invariants", "skipped", "skipped_reasons", "mock_port")
QUALIFICATION_KEYS = ("pass", "gates", "thinking_block_seen", "completed", "at", "fingerprint")
FINGERPRINT_KEYS = ("effective_route_sha", "wire_model", "source_identity", "claude_code")


def empty_tier() -> dict:
    return {"configured": None, "advertised": None, "verified": None, "checked": None}


def empty_cost_model() -> dict:
    return {"context": None, "context_basis": None, "harness_baseline_tokens": None, "tok_s": None,
            "usd_per_mtok": None, "caching": "unknown", "concurrency": None, "thinking": None, "checked": None}


def empty_route() -> dict:
    return {"served": None, "checked": None, "limits": {"input": empty_tier(), "output": empty_tier()},
            "cost_model": empty_cost_model(), "last_qualification": None, "last_session": None}


def empty_source() -> dict:
    return {"reachable": None, "checked": None, "error": None, "catalog": None, "catalog_count": None,
            "configured_limits": None, "identity": None}


def empty_observed() -> dict:
    return {"version": OBSERVED_VERSION, "copy": None, "sources": {}, "routes": {}, "last_check": None,
            "last_gate_run": None, "spend": {}}


def forbid_claude_cost(obj, path: str = "$") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                raise SchemaError("observed.no_claude_cost", f"{path}.{k} is Claude Code's own cost figure (F11)")
            forbid_claude_cost(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            forbid_claude_cost(v, f"{path}[{i}]")


def _require_keys(d, keys, where: str, rule: str) -> None:
    if not isinstance(d, dict):
        raise SchemaError(rule, f"{where} must be an object")
    missing = [k for k in keys if k not in d]
    if missing:
        raise SchemaError(rule, f"{where} lacks {missing} — unmeasured must be null, not absent")


def _is_cost(c) -> bool:
    return c == "unknown" or (isinstance(c, (int, float)) and not isinstance(c, bool) and c >= 0)


def validate_session(s, where: str) -> None:
    if not isinstance(s, dict):
        raise SchemaError("observed.session.shape", f"{where} must be an object")
    if set(s) == {"skipped"}:
        if not isinstance(s["skipped"], str) or not s["skipped"]:
            raise SchemaError("observed.session.shape", f"{where}.skipped must say why")
        return
    _require_keys(s, SESSION_KEYS, where, "observed.session.shape")
    if s["first_request"] is not None:
        _require_keys(s["first_request"], ("input_tokens_total", "usage"), f"{where}.first_request", "observed.session.shape")
    for part, extra in (("this_run", ("models_seen",)), ("session_total", ("covered_turns", "uncovered_turns"))):
        p = s[part]
        _require_keys(p, ("turns", "usage", "cost_usd") + extra, f"{where}.{part}", "observed.session.shape")
        _require_keys(p["usage"], USAGE_FIELDS, f"{where}.{part}.usage", "observed.session.shape")
        if not _is_cost(p["cost_usd"]):
            raise SchemaError("observed.session.shape", f"{where}.{part}.cost_usd must be a number ≥ 0 or the string 'unknown'")


def validate_route(r, where: str) -> None:
    _require_keys(r, tuple(empty_route()), where, "observed.route.shape")
    _require_keys(r["limits"], ("input", "output"), f"{where}.limits", "observed.route.shape")
    for k in ("input", "output"):
        _require_keys(r["limits"][k], tuple(empty_tier()), f"{where}.limits.{k}", "observed.route.shape")
    _require_keys(r["cost_model"], tuple(empty_cost_model()), f"{where}.cost_model", "observed.route.shape")
    if r["cost_model"]["caching"] not in CACHING_VALUES:
        raise SchemaError("observed.route.shape", f"{where}.cost_model.caching must be true, false or 'unknown'")
    if r["served"] not in (True, False, None):
        raise SchemaError("observed.route.shape", f"{where}.served must be true, false or null")
    q = r["last_qualification"]
    if q is not None:
        _require_keys(q, QUALIFICATION_KEYS, f"{where}.last_qualification", "observed.qualification.shape")
        _require_keys(q["fingerprint"], FINGERPRINT_KEYS, f"{where}.last_qualification.fingerprint", "observed.qualification.shape")
        if not isinstance(q["gates"], dict) or not all(isinstance(v, bool) for v in q["gates"].values()):
            raise SchemaError("observed.qualification.shape", f"{where}.last_qualification.gates must map gate names to booleans")
    if r["last_session"] is not None:
        validate_session(r["last_session"], f"{where}.last_session")


def validate_observed(doc) -> None:
    _require_keys(doc, tuple(empty_observed()), "observed", "observed.shape")
    if doc["version"] != OBSERVED_VERSION:
        raise SchemaError("observed.shape", f"observed.version must be {OBSERVED_VERSION}, got {doc['version']!r}")
    forbid_claude_cost(doc)
    for n, s in doc["sources"].items():
        _require_keys(s, tuple(empty_source()), f"sources.{n}", "observed.shape")
    for n, r in doc["routes"].items():
        validate_route(r, f"routes.{n}")
    if doc["last_check"] is not None:
        _require_keys(doc["last_check"], CHECK_KEYS, "last_check", "observed.shape")
    if doc["last_gate_run"] is not None:
        _require_keys(doc["last_gate_run"], GATE_RUN_KEYS, "last_gate_run", "observed.shape")


def compute_context(declared: int | None, tier: dict) -> tuple[int | None, str | None]:
    """§7: min(declared, verified) when verified is present, else min(declared, configured, advertised).
    The declared cap participates in both branches; `verified` only ever lowers. On a tie the basis is `declared`,
    because the operator's cap is the reason the number is what it is."""
    if tier.get("verified") is not None:
        cands = [("declared", declared), ("verified", tier["verified"])]
    else:
        cands = [("declared", declared), ("configured", tier.get("configured")), ("advertised", tier.get("advertised"))]
    cands = [(n, v) for n, v in cands if v is not None]
    if not cands:
        return None, None
    best = min(v for _, v in cands)
    for n, v in cands:            # first wins a tie, and `declared` is first
        if v == best:
            return best, n
    return None, None
