---
name: agent-on
description: Use when working in this checkout on models, routes, costs, launches or qualifications — how to read what the tower already knows (status --json and knowledge/) and how to record what you learn (agent-on learn) so the next session starts from it.
---

# agent-on — read the tower, write what you learn

The launch cannot be a skill (it sets the child's environment before Claude Code starts), and a skill does not
accumulate; this one only tells you where the accumulated facts are and how to add to them.

## Read first

- `./bin/agent-on status --json` — every route's declared limits beside what was measured (`observed`), the cost
  model, the last session's cost (Q1), whether the route is served (Q3), the last gate run (Q4), OpenRouter spend
  (Q6), the harness baseline tokens (Q8), and per route `knowledge.observations` (last three) and
  `knowledge.traps` (what applies to `status` on that route).
- `./bin/agent-on status --check` — every invariant with its result and fix; `last_check` is written. What an
  action must not break is the list of invariants that name it (Q10).
- `./bin/agent-on install` — links the two shims into `~/.local/bin` and creates the state root; idempotent.
- `knowledge/decisions.jsonl` — the settled decisions with rationale; a record with `supersedes` replaces the one it
  names. Read the active set before proposing a change that touches one.
- `knowledge/traps.jsonl` — mechanisms that have bitten this repo, with `applies_to` (a verb, a source, a route or
  `*`) and how to avoid them. `status` and the launch show the ones for the action in hand.
- `knowledge/observations.jsonl` — measurements (`tokens | throughput | quality | liveness | cost`) with evidence.
- `knowledge/qualifications.jsonl`, `knowledge/gate-runs.jsonl` — the durable twins of the last qualification and gate run.
- `knowledge/tasks.jsonl` — the task ledger as events; `agent-on learn task list|show <id>` folds it.

Every command prints a `copy:` line (checkout, commit, dirty, state root) — say which copy you measured.

## Write when you learn

    ./bin/agent-on learn observations --json-record '{"route": "<source>/<model>", "kind": "throughput", "values": {…}, "evidence": "<how it was measured>", "session": null}'
    ./bin/agent-on learn traps --json-record '{"trap": "…", "mechanism": "…", "avoid": "…", "evidence": "…", "found_by": "…", "applies_to": ["launch"]}'
    ./bin/agent-on learn decisions --json-record '{"decision": "…", "rationale": "…", "by": "rick", "supersedes": "decisions-…"}'

`learn` validates, mints `id` and `ts`, and appends one line; nothing is written on a schema error (exit 3). A
value you did not measure is `null` or `"unknown"`, never a guess. `knowledge/` is git-tracked: commit it with the
work that produced it.

## Tasks across sessions

    ./bin/agent-on learn task create <name> --goal '…' [--worktree <dir>]
    ./bin/agent-on learn task handoff <id> --to <route> --objective '…' [--from <route>] [--summary '…'] [--commit <sha>] [--tests '…']
    ./bin/claude-on --task <id> [--handoff n|latest] <route> [claude args…]      # runs in the worktree; the handoff prompt is Claude's last argument — give list options as --opt=value
    ./bin/agent-on learn task complete <id> --summary '…' [--commit <sha>] [--tests '…'] [--close]

A dispatcher (Orca or another) reads `learn task prompt <id> --json` to pick a host and invokes the same launcher.
`launched` is recorded before Claude Code starts; a launch that fails to spawn leaves the handoff `launched` — record
the outcome with `learn task complete`.
