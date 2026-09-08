"""L5 §10.1 — the task ledger (PR #12) as events in knowledge/tasks.jsonl. Current state is the fold; `claude-on
<route> --task <id>` injects the rendered handoff prompt exactly as the old `task launch` did."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from .knowledge import append, read
from .paths import Paths, describe_copy
from .schemas.knowledge import TASK_ID
from .schemas.routes import load_routes

MAX_TEXT = 16_384
MAX_EVIDENCE = 8_192


def limited(value: str | None, label: str, maximum: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError(f"learn task: {label} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"learn task: {label} exceeds {maximum} characters")
    return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48].rstrip("-") or "task"


def fold(events: list[dict]) -> dict[str, dict]:
    """Event-sourced: replay tasks.jsonl in order; later events win."""
    tasks: dict[str, dict] = {}
    for e in events:
        t = tasks.get(e["task_id"])
        if e["event"] == "created":
            tasks[e["task_id"]] = {"id": e["task_id"], "name": e["name"], "goal": e["goal"], "worktree": e["worktree"], "status": "active",
                                   "created": e["ts"], "updated": e["ts"], "closed_summary": None, "handoffs": []}
            continue
        if t is None:
            continue                                                               # an event for an unknown task is ignored, not fatal
        t["updated"] = e["ts"]
        if e["event"] == "handoff":
            t["handoffs"].append({"index": e["index"], "from_route": e["from_route"], "to_route": e["to_route"], "objective": e["objective"],
                                  "summary": e["summary"], "commit": e["commit"], "tests": e["tests"], "status": "pending", "created": e["ts"],
                                  "launched": None, "launch_id": None, "completed_at": None, "result_summary": None, "result_commit": None, "result_tests": None})
        elif e["event"] == "launched":
            h = t["handoffs"][e["index"] - 1]
            h.update({"status": "launched", "launched": e["ts"], "launch_id": e["launch_id"]})
        elif e["event"] == "completed":
            h = t["handoffs"][e["index"] - 1]
            h.update({"status": "completed", "completed_at": e["ts"], "result_summary": e["summary"], "result_commit": e["commit"], "result_tests": e["tests"]})
            if e["close"]:
                t["status"], t["closed_summary"] = "completed", e["summary"]
    return tasks


def load(paths: Paths, task_id: str) -> dict:
    if not TASK_ID.fullmatch(task_id):
        raise ValueError(f"learn task: invalid task id: {task_id}")
    t = fold(read(paths, "tasks")).get(task_id)
    if t is None:
        raise ValueError(f"learn task: no such task: {task_id}")
    return t


def select_handoff(task: dict, requested: str) -> dict:
    hs = task["handoffs"]
    if not hs:
        raise ValueError("learn task: task has no handoff; add one before launching")
    if requested == "latest":
        return hs[-1]
    try:
        i = int(requested)
    except ValueError:
        raise ValueError("learn task: handoff must be 'latest' or a positive integer") from None
    if i < 1 or i > len(hs):
        raise ValueError(f"learn task: handoff does not exist: {requested}")
    return hs[i - 1]


def create(paths: Paths, name: str, goal: str, worktree: str) -> dict:
    title, goal_t = limited(name, "name", 256), limited(goal, "goal")
    # .absolute(), not .resolve(): the worktree is recorded as the path the caller gave (made absolute), not its
    # realpath — resolving symlinks would rewrite e.g. macOS's /var -> /private/var and surprise anyone reading
    # the ledger back.
    wt = Path(worktree).expanduser().absolute()
    if not wt.is_dir():
        raise ValueError(f"learn task: worktree is not a directory: {wt}")
    task_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{slugify(title)}-{secrets.token_hex(3)}"
    append(paths, "tasks", {"task_id": task_id, "event": "created", "name": title, "goal": goal_t, "worktree": str(wt)})
    return load(paths, task_id)


def handoff(paths: Paths, task_id: str, *, to_route: str, objective: str, from_route: str | None = None,
            summary: str | None = None, commit: str | None = None, tests: str | None = None) -> dict:
    t = load(paths, task_id)
    if t["status"] != "active":
        raise ValueError("learn task: cannot add a handoff to a closed task")
    route = load_routes(paths).resolve(to_route).name                             # KeyError → the CLI's usage envelope
    rec = {"task_id": task_id, "event": "handoff", "index": len(t["handoffs"]) + 1, "from_route": limited(from_route, "from route", 256),
           "to_route": route, "objective": limited(objective, "objective"), "summary": limited(summary, "summary"),
           "commit": limited(commit, "commit", 512), "tests": limited(tests, "tests", MAX_EVIDENCE)}
    append(paths, "tasks", rec)
    return load(paths, task_id)["handoffs"][-1]


def launched(paths: Paths, task_id: str, *, launch_id: str, route: str, handoff: str = "latest") -> dict:
    t = load(paths, task_id)
    h = select_handoff(t, handoff)
    append(paths, "tasks", {"task_id": task_id, "event": "launched", "index": h["index"], "launch_id": launch_id, "route": route})
    return load(paths, task_id)["handoffs"][h["index"] - 1]


def complete(paths: Paths, task_id: str, *, summary: str, handoff: str = "latest", commit: str | None = None,
             tests: str | None = None, close: bool = False) -> dict:
    t = load(paths, task_id)
    h = select_handoff(t, handoff)
    if h["status"] == "completed":
        raise ValueError(f"learn task: handoff {h['index']} is already completed")
    append(paths, "tasks", {"task_id": task_id, "event": "completed", "index": h["index"], "summary": limited(summary, "summary"),
                            "commit": limited(commit, "commit", 512), "tests": limited(tests, "tests", MAX_EVIDENCE), "close": bool(close)})
    return load(paths, task_id)


def render_prompt(task: dict, h: dict) -> str:
    evidence = [s for s in ((f"- Commit/base: {h['commit']}" if h.get("commit") else None), (f"- Test evidence: {h['tests']}" if h.get("tests") else None)) if s]
    evidence_text = "\n".join(evidence) if evidence else "- No commit or test evidence recorded."
    return f"""You are worker session {h['index']} for agent-on task {task['id']}.

Task goal:
{task['goal']}

Worktree:
{task['worktree']}

Model-session handoff:
- From route: {h.get('from_route') or 'unassigned/initial'}
- To route: {h['to_route']}
- Objective: {h['objective']}

Prior decisions and context:
{h.get('summary') or 'No prior-session summary was supplied.'}

Recorded evidence:
{evidence_text}

Working contract:
1. Work only on the objective above and inspect the current worktree before changing it.
2. Preserve unrelated user changes and treat the worktree, commit, and tests as source of truth.
3. Do not assume the previous model transcript or token budget is available.
4. Before exiting, report Outcome, Changes, Tests, Risks, and Recommended next handoff.
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-on learn task", add_help=True)
    sub = p.add_subparsers(dest="verb", required=True)
    c = sub.add_parser("create"); c.add_argument("name"); c.add_argument("--goal", required=True); c.add_argument("--worktree", default=None)
    h = sub.add_parser("handoff"); h.add_argument("task_id"); h.add_argument("--to", required=True); h.add_argument("--objective", required=True)
    h.add_argument("--from", dest="from_route"); h.add_argument("--summary"); h.add_argument("--commit"); h.add_argument("--tests")
    d = sub.add_parser("complete"); d.add_argument("task_id"); d.add_argument("--handoff", default="latest"); d.add_argument("--summary", required=True)
    d.add_argument("--commit"); d.add_argument("--tests"); d.add_argument("--close", action="store_true")
    s = sub.add_parser("show"); s.add_argument("task_id")
    sub.add_parser("list")
    r = sub.add_parser("prompt"); r.add_argument("task_id"); r.add_argument("--handoff", default="latest")
    return p


def run_task_verb(paths: Paths, argv: list[str]) -> tuple[dict, int]:
    """`agent-on learn task <verb> …`: returns (envelope, exit). Usage errors are exit 2; rule violations raise ValueError."""
    try:
        a = _parser().parse_args(argv)
    except SystemExit:
        return {"command": "learn", "copy": describe_copy(paths), "error": "learn task: usage", "hint": "create|handoff|complete|show|list|prompt"}, 2
    doc: dict = {"command": "learn", "copy": describe_copy(paths), "kind": "task", "verb": a.verb}
    if a.verb == "create":
        t = create(paths, a.name, a.goal, a.worktree or os.getcwd())
        doc.update({"task": t, "text": t["id"]})
    elif a.verb == "handoff":
        h = handoff(paths, a.task_id, to_route=a.to, objective=a.objective, from_route=a.from_route, summary=a.summary, commit=a.commit, tests=a.tests)
        doc.update({"handoff": h, "text": f"{a.task_id} handoff {h['index']} -> {h['to_route']}"})
    elif a.verb == "complete":
        t = complete(paths, a.task_id, summary=a.summary, handoff=a.handoff, commit=a.commit, tests=a.tests, close=a.close)
        doc.update({"task": t, "text": f"{a.task_id} {'closed' if a.close else 'handoff completed'}"})
    elif a.verb == "show":
        t = load(paths, a.task_id)
        doc.update({"task": t, "text": json.dumps(t, indent=1, sort_keys=True)})
    elif a.verb == "list":
        ts = list(fold(read(paths, "tasks")).values())
        doc.update({"tasks": ts, "text": "\n".join(f"{t['id']} {t['status']} {t['name']} ({len(t['handoffs'])} handoffs)" for t in ts) or "no tasks"})
    else:
        t = load(paths, a.task_id)
        h = select_handoff(t, a.handoff)
        doc.update({"task_id": t["id"], "handoff": h["index"], "route": h["to_route"], "worktree": t["worktree"], "prompt": render_prompt(t, h)})
        doc["text"] = doc["prompt"]
    return doc, 0
