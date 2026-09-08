"""L5 record kinds (§10) — enough for `knowledge.typed`; `learn` (Plan C) validates with the same function."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import SchemaError

KINDS: dict[str, tuple[str, ...]] = {
    "observations": ("route", "kind", "values", "evidence"),
    "decisions": ("decision", "rationale", "by"),
    "traps": ("trap", "mechanism", "avoid", "evidence", "found_by", "applies_to"),
    "qualifications": ("route", "fingerprint", "gates", "thinking_block_seen", "completed", "commit"),
    "gate-runs": ("commit", "result", "tests", "verifiers", "invariants", "skipped_reasons", "mock_port"),
    "tasks": ("task_id", "event"),
}
OBSERVATION_KINDS = ("tokens", "throughput", "quality", "liveness", "cost")


def validate_record(kind: str, rec) -> None:
    if kind not in KINDS:
        raise SchemaError("knowledge.record", f"unknown kind {kind!r}; kinds: {sorted(KINDS)}")
    if not isinstance(rec, dict):
        raise SchemaError("knowledge.record", f"{kind}: a record must be an object")
    missing = [k for k in ("id", "ts") + KINDS[kind] if k not in rec]
    if missing:
        raise SchemaError("knowledge.record", f"{kind}: missing {missing}")
    if not str(rec["id"]).startswith(f"{kind}-"):
        raise SchemaError("knowledge.record", f"{kind}: id must start with '{kind}-', got {rec['id']!r}")
    if kind == "observations" and rec["kind"] not in OBSERVATION_KINDS:
        raise SchemaError("knowledge.record", f"observation kind must be one of {OBSERVATION_KINDS}, got {rec['kind']!r}")


def validate_file(path: Path) -> list[str]:
    """Every non-blank line of knowledge/<kind>.jsonl; returns `<file>:<line>: <error>` strings."""
    kind = path.stem
    errors: list[str] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            validate_record(kind, json.loads(line))
        except (ValueError, SchemaError) as e:
            errors.append(f"{path.name}:{n}: {e}")
    return errors
