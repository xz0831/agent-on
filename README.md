# agent-on

Run Claude Code on any model from any source that speaks the Anthropic wire — OpenRouter, a local oMLX server,
another Mac's oMLX over the tailnet — with nothing between Claude Code and the source, and with what each
session measured kept for the next one.

    ./bin/claude-on huihui                       # Claude Code on a local oMLX route; the cost line prints first
    ./bin/claude-on glm -p 'Reply with exactly: OK'
    ./bin/agent-on status glm                    # declared beside measured: served, limits, cost model, last session, traps

The design is `docs/superpowers/specs/2026-09-07-agent-on-design.md`. This README is the operator's page.

## Install

Requirements: macOS or Linux, `python3` ≥ 3.11 on `PATH` (standard library only — nothing is pip-installed), `git`,
`zsh` (the three shims are zsh), Claude Code (`claude` on `PATH`).

    git clone https://github.com/xz0831/agent-on.git
    # until the GitHub rename lands, use the repository's previous name (GitHub redirects it afterwards)
    cd agent-on
    ./bin/agent-on install                       # links ~/.local/bin/agent-on and claude-on here; creates ~/.local/state/agent-on

The checkout is the installation (D9): `install` puts two symlinks in `~/.local/bin` and creates the state root.
Pull to upgrade. `agent-on status --check` reports drift as `copy.dirty` (uncommitted changes) and `copy.single`
(the shim points here). `AGENT_ON_STATE=<dir>` runs the checkout against a scratch state root.

Keys: put `OPENROUTER_API_KEY=…` in `~/.local/state/agent-on/env` (mode 0600) or in the environment. The key never
enters Claude Code's environment: the launcher writes it to a per-launch 0600 file and hands Claude Code an
`apiKeyHelper` that reads it.

## Use

    ./bin/claude-on <route|alias> [claude args…]         # launch options (--dry-run, --sonnet, --haiku, --task, --discover) go before the route
    ./bin/claude-on --dry-run glm                         # environment keys, argv and cost line; spawns nothing
    ./bin/codex-on huihui                        # Codex CLI on the same route; options before the route, everything after it is Codex's
    ./bin/agent-on qualify huihui --wire responses   # the six gate analogues on the Responses wire (what Codex speaks)
    ./bin/agent-on status [route] [--check]               # L1 beside L2; --check evaluates every invariant
    ./bin/agent-on sync                                   # probe every source: served, limits, spend; rewrite routes.discovered.toml
    ./bin/agent-on add openrouter/<vendor>/<model> --alias <a>
    ./bin/agent-on qualify <route> [--baseline] [--limits] [--allow-paid]
    ./bin/agent-on learn <kind> --json-record '{…}'       # append a typed record to knowledge/
    ./bin/agent-on learn task create|handoff|complete|show|list|prompt
    ./bin/agent-on gate                                   # unit tests + mock-source smoke + every invariant

Every command answers `--json`. Everything after the route belongs to Claude Code; give list-valued Claude options
as `--opt=value` when a task prompt is injected.

Routes are `<source>/<model>` with optional aliases, declared only in `routes.toml`; `docs/ROUTES.md` is generated
from it (`scripts/routes-doc.py`, checked by `docs.current`). Measured values — served, verified limits, tok/s,
concurrency, caching, thinking, the last session's cost — live in `~/.local/state/agent-on/observed.json` and are
shown by `status`, never copied into declarations.

One Claude Code process is pinned to one route; the tier slots and the subagent slot all resolve to it. To change
model, exit and relaunch. Qualification results and traps are shown before a launch; they never block it.

## Harnesses

Two harnesses bind to the same routes: Claude Code (`claude-on`, the Anthropic Messages wire) and Codex CLI
(`codex-on`, the OpenAI Responses wire). Both take the key from a per-launch file the launcher writes and removes —
Claude Code through `apiKeyHelper` in a per-launch settings file, Codex through `http_headers` in a per-launch
profile under a per-launch `CODEX_HOME` (your `~/.codex` config, skills, plugins and hooks are linked in; sessions
stay per launch). Neither harness ever sees the key in its environment. Qualify each wire separately
(`--wire messages|responses`); `status` shows one `qualified[<wire>]` line per wire and one baseline per harness.

## Knowledge

`knowledge/` is git-tracked, append-only JSONL beside `routes.toml`: decisions (with supersession), traps (with
`applies_to`), observations, and the durable twins of qualifications and gate runs. `qualify`, the gate and the
launch append to it; `learn` is the write verb for everything else; `.claude/skills/agent-on/SKILL.md` tells an
agent inside Claude Code how to read and write it. Commit `knowledge/` with the work that produced it.

Tasks across sessions: `learn task create … / handoff … --to <route>`, then `claude-on --task <id> <route>` runs in
the task's worktree with the handoff prompt injected; `learn task complete` records the outcome.

## Verify

    ./bin/agent-on gate                          # what CI runs: tests/agent_on, the F1 smoke on a mock source, every invariant
    ./bin/agent-on status --check                # the invariants alone, with skips shown as skips

Sources that are unreachable are reported as unreachable, never as passing.

## Upgrading from claude-litellm

The previous gateway (LiteLLM proxy, OAuth lanes, the `claude-litellm` command) is gone; `git revert` of its
deletion commit restores it. One-time cleanup of an installed copy:

    rm ~/.local/bin/claude-litellm
    rm -rf ~/.local/share/claude-litellm          # the hash-locked venv and its state, about 830 MB
    rm -rf ~/.config/claude-litellm               # the overlay settings and lock, no secret

Keys move to `~/.local/state/agent-on/env`; proxy-era sessions are not migrated. The ChatGPT/xAI OAuth routes are
not coming back (D3); GPT is used through Codex.
