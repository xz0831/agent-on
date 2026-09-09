"""L5 record kinds (§10) — enough for `knowledge.typed`; `learn` (Plan C) validates with the same function."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import SchemaError
from .observed import WIRES

KINDS: dict[str, tuple[str, ...]] = {
    "observations": ("route", "kind", "values", "evidence"),
    "decisions": ("decision", "rationale", "by"),
    "traps": ("trap", "mechanism", "avoid", "evidence", "found_by", "applies_to"),
    "qualifications": ("route", "fingerprint", "gates", "thinking_block_seen", "completed", "commit"),
    "gate-runs": ("commit", "result", "tests", "verifiers", "invariants", "skipped_reasons", "mock_port"),
    "tasks": ("task_id", "event"),
}
OBSERVATION_KINDS = ("tokens", "throughput", "quality", "liveness", "cost")
APPLIES_TO_VERBS = ("status", "sync", "add", "gate", "launch", "qualify", "learn", "install")

# Task 6 — the task ledger (PR #12) as events in knowledge/tasks.jsonl. Kept here (not in agent_on.tasks) so
# `tasks.py` can import it without a cycle (tasks -> knowledge -> schemas).
TASK_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}-[0-9a-f]{6}")
TASK_EVENTS: dict[str, tuple[str, ...]] = {
    "created": ("name", "goal", "worktree"),
    "handoff": ("index", "from_route", "to_route", "objective", "summary", "commit", "tests"),
    "launched": ("index", "launch_id", "route"),
    "completed": ("index", "summary", "commit", "tests", "close"),
}


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
    if kind == "qualifications" and "wire" in rec and rec["wire"] not in WIRES:
        raise SchemaError("knowledge.record", f"qualifications: wire must be one of {WIRES}, got {rec['wire']!r}")
    if kind == "traps":
        at = rec["applies_to"]
        if not isinstance(at, list) or not at or not all(isinstance(a, str) and a for a in at):
            raise SchemaError("knowledge.record", "traps: applies_to must be a non-empty list of verbs, sources, routes or '*'")
    if "supersedes" in rec and not (isinstance(rec["supersedes"], str) and rec["supersedes"].startswith(f"{kind}-")):
        raise SchemaError("knowledge.record", f"{kind}: supersedes must name an id of the same kind")
    if kind == "tasks":
        if not (isinstance(rec["task_id"], str) and TASK_ID.fullmatch(rec["task_id"])):
            raise SchemaError("knowledge.record", f"tasks: invalid task_id {rec['task_id']!r}")
        if rec["event"] not in TASK_EVENTS:
            raise SchemaError("knowledge.record", f"tasks: event must be one of {sorted(TASK_EVENTS)}, got {rec['event']!r}")
        missing = [k for k in TASK_EVENTS[rec["event"]] if k not in rec]
        if missing:
            raise SchemaError("knowledge.record", f"tasks/{rec['event']}: missing {missing}")


def validate_file(path: Path) -> list[str]:
    """Every non-blank line of knowledge/<kind>.jsonl; returns `<file>:<line>: <error>` strings. Cross-line rules:
    ids are unique within the file and `supersedes` names an id that appears in it."""
    kind = path.stem
    errors: list[str] = []
    seen: dict[str, int] = {}
    supersedes: list[tuple[int, str]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            validate_record(kind, rec)
        except (ValueError, SchemaError) as e:
            errors.append(f"{path.name}:{n}: {e}")
            continue
        if rec["id"] in seen:
            errors.append(f"{path.name}:{n}: duplicate id {rec['id']} (first at line {seen[rec['id']]})")
        seen.setdefault(rec["id"], n)
        if "supersedes" in rec:
            supersedes.append((n, rec["supersedes"]))
    for n, target in supersedes:
        if target not in seen:
            errors.append(f"{path.name}:{n}: supersedes {target} not found in {path.name}")
    return errors
