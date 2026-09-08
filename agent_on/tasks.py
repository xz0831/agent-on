"""L5 §10.1 — the task ledger as events in knowledge/tasks.jsonl (Task 6 fills this in)."""
from __future__ import annotations

from .paths import Paths, describe_copy


def run_task_verb(paths: Paths, argv: list[str]) -> tuple[dict, int]:
    return {"command": "learn", "copy": describe_copy(paths), "error": "learn task: not landed yet", "hint": "learn task lands in Task 6"}, 2
