# agent-on

Run Claude Code on any model from any source that speaks the Anthropic wire — OpenRouter, Splash, a local oMLX
server, or another Mac's oMLX over the tailnet — and keep what each session measured for the next one. Native
Anthropic backends stay direct; new oMLX Claude launches use a route-pinned loopback adapter for effort only.

    ./bin/claude-on huihui                       # Claude Code on a local oMLX route; the cost line prints first
    ./bin/claude-on glm -p 'Reply with exactly: OK'
    ./bin/agent-on status glm                    # declared beside measured: served, limits, cost model, last session, traps

The design is `docs/superpowers/specs/2026-09-07-agent-on-design.md`. This README is the operator's page.

## Install

Requirements: macOS or Linux, Python ≥ 3.11 (standard library only — nothing is pip-installed), `git`,
`zsh` (the three shims are zsh), Claude Code (`claude` on `PATH`).

    git clone https://github.com/xz0831/agent-on.git
    # until the GitHub rename lands, use the repository's previous name (GitHub redirects it afterwards)
    cd agent-on
    ./bin/agent-on install                       # links agent-on, claude-on, and codex-on here; creates the state root

The checkout is the installation (D9): `install` puts three symlinks in `~/.local/bin` and creates the state root.
Pull to upgrade. `agent-on status --check` reports drift as `copy.dirty` (uncommitted changes) and `copy.single`
(the shim points here). `AGENT_ON_STATE=<dir>` runs the checkout against a scratch state root.
The shim checks the active `python3` first and then the standard Homebrew locations, so a macOS system Python older
than 3.11 does not hide a suitable Homebrew Python. See [multi-host operation](docs/MULTI_HOST.md) for Rick, Morty,
and xz0831 installation and update steps.

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

### Continue normal Claude Code sessions

Agent-on keeps sessions isolated by default under `$AGENT_ON_STATE/claude-config`. Select the native store when a
launch must use the same picker, transcript, history, session environment, and auto-memory as normal Claude Code:

    ./bin/claude-on --session-store native glm --resume <session-uuid>
    ./bin/claude-on --session-store native glm --continue

Native mode leaves `CLAUDE_CONFIG_DIR` unset; Claude Code therefore reads and appends the original
`~/.claude/projects/...` transcript in place. Do not run the same session concurrently from normal Claude Code and
Agent-on. The route binding and per-launch credential helper still come from Agent-on. The selected store is shown
as `session_store` in JSON launch output. This is local machine state and is never pushed to GitHub.

### Per-host source addresses

Tracked `routes.toml` is the shared route identity and policy. A host whose endpoint differs writes only the address
override to `$AGENT_ON_STATE/routes.local.toml`; the file is outside Git and may override `base_url` only:

```toml
version = 1
[sources."omlx@morty"]
base_url = "http://127.0.0.1:1238"
```

`status`, `sync`, `add`, `qualify`, and both launchers use the effective local address. The effective route hash
therefore changes with the override, so a qualification from a different endpoint is not treated as current.

### Claude effort

Claude Code sends its current `low|medium|high|xhigh|max` choice as `output_config.effort`. Splash and OpenRouter's
Anthropic Messages endpoints consume that field, so those backends remain direct and agent-on reports their path as
native pass-through rather than claiming that a provider used a particular internal budget. Splash's Qwen3.8
template has native `low`, `medium`, and `xhigh` levels and maps Claude `high|max` to `xhigh`; a positive
`thinking.budget_tokens` is not an enforceable Splash budget and agent-on does not reinterpret `max_tokens` as one.

oMLX does not consume `output_config.effort` on its Anthropic endpoint. For every new Claude launch whose source has
`backend = "omlx"`, agent-on binds an ephemeral loopback adapter to that one upstream and the launch's allowed main,
Sonnet, and Haiku wire-model IDs. It copies the effort into `chat_template_kwargs.reasoning_effort` and makes the
thinking state consistent. `thinking.type=disabled` wins and removes the backend effort. Missing effort preserves
the model's existing default, so launching without an effort does not turn thinking on.

Built-in evidenced mappings are model-family specific:

| oMLX model | Claude low | medium | high | xhigh | max |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4.1 | low (50) | high (75) | high (75) | max (100) | max (100) |
| Qwen3.8-27B | low | medium | xhigh | xhigh | xhigh |

An unknown oMLX model continues unchanged while no explicit CLI effort is selected. Claude Code currently emits a
default `output_config.effort=high` even without the flag; the adapter forwards that unmodified and records
`unsupported-profile-passthrough`, rather than breaking an ordinary GLM/custom-model launch or claiming high was
applied. An explicit `--effort` returns a clear local 400 until the route declares an exact model profile. For the
same reason, an in-session UI change on an unknown model remains visible but un-applied. Agent-on never assumes every
model supports five levels:

```toml
[routes."omlx/vendor--model".reasoning]
supported = true
efforts = ["low", "medium", "high", "xhigh", "max"]
effort_map = { low = "low", medium = "medium", high = "xhigh", xhigh = "xhigh", max = "xhigh" }
confidence = "configured"
source = "model chat-template documentation and local CPU render check"
```

Source names are arbitrary: `backend = "omlx"` selects the adapter for `omlx`, `omlx@morty`, or any custom name;
`backend = "splash"` and `backend = "openrouter"` document native pass-through. An omitted backend is transparent
`passthrough` for compatibility and carries no effort-support claim. Each oMLX launch prints an `effort` object and
keeps a prompt-free, header-free receipt at `$AGENT_ON_STATE/effort/<launch-id>.jsonl` with requested and mapped
levels. Existing sessions keep their original connection; exit and launch again to gain this behavior.

### Morty from Rick

Rick's `omlx@morty` source uses `http://127.0.0.1:18038`, forwarded by the existing SSH host alias `studio2`
to Morty's loopback `127.0.0.1:1238`. The owned LaunchAgent `ai.clusterops.morty-model-forward` maintains
this transport. Morty's oMLX stays bound to loopback. The explicit route alias is `morty-qwen`; the 1237
recovery service is a separate operating decision and is not selected by this source.

    ./bin/agent-on status morty-qwen
    ./bin/claude-on --dry-run morty-qwen
    ./bin/codex-on --dry-run morty-qwen
    launchctl print gui/$(id -u)/ai.clusterops.morty-model-forward

Another checkout or host needs its own reachable source address or an explicitly configured forward;
installing agent-on does not create this LaunchAgent. The `@morty` source remains remote even though its
address is loopback, so `sync` never reads Rick's oMLX settings as Morty's configured limits. Its existing
131072 input / 32768 output operator caps are retained. Catalog reachability, a generated launch profile,
and each wire's actual qualification are distinct observations.

## Harnesses

Two harnesses bind to the same routes: Claude Code (`claude-on`, the Anthropic Messages wire) and Codex CLI
(`codex-on`, the OpenAI Responses wire). Both take the key from a per-launch file the launcher writes and removes —
Claude Code through `apiKeyHelper` in a per-launch settings file, Codex through `http_headers` in a per-launch
profile linked into a durable isolated `CODEX_HOME` (your `~/.codex` config, skills, plugins and hooks are linked in).
Codex session homes survive under `$AGENT_ON_STATE/codex-homes/`; only per-launch credential files are removed
on exit. Resume one with `codex-on <route> exec resume <session-uuid> "follow-up"` or
`codex-on <route> resume <session-uuid>`. The UUID must belong to this state root; session names and `--last`
are refused, and concurrent resumes of the same home are rejected. Native `~/.codex` sessions are not moved
or imported. Sessions deleted by older launcher versions cannot be recovered by this change.
Neither harness ever sees the key in its environment. Qualify each wire separately
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
