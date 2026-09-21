# agent-on

Run Claude Code on any model from any source that speaks the Anthropic wire — OpenRouter, Splash, a local oMLX
server, or another Mac's oMLX over the tailnet — and keep what each session measured for the next one. Native
Anthropic backends stay direct; new oMLX Claude launches use a route-pinned loopback adapter for effort only.

    ./bin/claude-on 'omlx@rick/Qwen3.8-27B-Uncensored-8bit'  # full family, build, and source; cost line prints first
    ./bin/agent-on status 'omlx@rick/Qwen3.8-27B-Uncensored-8bit'

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

Keys: put each declared source key, such as `OPENROUTER_API_KEY`, `OMLX_RICK_API_KEY`, or
`OMLX_MORTY_API_KEY`, in `~/.local/state/agent-on/env` (mode 0600) or in the environment. The key never
enters Claude Code's environment: the launcher writes it to a per-launch 0600 file and hands Claude Code an
`apiKeyHelper` that reads it.

## Use

    ./bin/claude-on <route|alias> [claude args…]         # launch options (--dry-run, --sonnet, --haiku, --task, --discover) go before the route
    ./bin/claude-on --dry-run 'omlx@rick/Qwen3.8-27B-Uncensored-8bit'  # environment keys, argv and cost line; spawns nothing
    ./bin/codex-on 'omlx@rick/Qwen3.8-27B-Uncensored-8bit'  # Codex CLI on the same full route
    ./bin/agent-on qualify 'omlx@rick/Qwen3.8-27B-Uncensored-8bit' --wire responses
    ./bin/agent-on status [route] [--check]               # L1 beside L2; --check evaluates every invariant
    ./bin/agent-on sync                                   # probe every source: served, limits, spend; rewrite routes.discovered.toml
    ./bin/agent-on add openrouter/<vendor>/<full-model-id>
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

Current public model selectors use the exact `<source>/<model-id>` route, retaining the publisher/build/quantization
in the ID. Do not use short family aliases such as `qwen27`, `flash-next`, `huihui`, `morty-qwen`, or `glm`.
`status` and the generated routes page show the complete family name separately from the unchanged backend wire ID.
Retired `GLM-5.2`, `Qwen3.5`, and `Qwen3.6` routes were removed from the current declarations and host discovery
state; this is not a permanent ban on a future owner-approved installation. Existing session transcripts and backend
model files are not rewritten. The runtime architecture name `qwen3_5` does not identify a Qwen3.5 model. A model
absent from the source catalog is not made available by naming it here.

One Claude Code process is pinned to one route. Agent-on sets every tier and subagent slot and passes an explicit
`--model <wire_model>`, so a literal `model` in the user's Claude settings cannot displace the route. A conflicting
user `--model` is refused. Several processes may run concurrently on different routes; each has its own launch ID,
session ID, credential file, and child environment. This process isolation does not reserve GPU memory or schedule
requests inside a serving engine.

Persistent user or project settings that set routing environment variables or `apiKeyHelper` are refused before
spawn with the path and conflicting fields. The one supported preference is `CLAUDE_CODE_SUBAGENT_MODEL`: ordinary
`claude` keeps that value, while every `claude-on` launch overrides it in a temporary highest-priority `--settings`
overlay with the selected route model. Agent-on never edits the persistent file. Safe explicit `--settings` content
is merged into that overlay; routing or credential fields in explicit settings are refused. Managed settings have
higher priority than CLI settings, so conflicting managed route controls are refused rather than bypassed. To change
model, exit and relaunch on another route.

### Continue normal Claude Code sessions

Agent-on keeps sessions isolated by default under `$AGENT_ON_STATE/claude-config`. Select the native store when a
launch must use the same picker, transcript, history, session environment, and auto-memory as normal Claude Code:

    ./bin/claude-on --session-store native 'omlx@rick/Qwen3.8-27B-Uncensored-8bit' --resume <session-uuid>
    ./bin/claude-on --session-store native 'omlx@rick/Qwen3.8-27B-Uncensored-8bit' --continue

Native mode leaves `CLAUDE_CONFIG_DIR` unset; Claude Code therefore reads and appends the original
`~/.claude/projects/...` transcript in place. Do not run the same session concurrently from normal Claude Code and
Agent-on. The route binding and per-launch credential helper still come from Agent-on. The selected store is shown
as `session_store` in JSON launch output. This is local machine state and is never pushed to GitHub.

### Per-host source addresses

Tracked `routes.toml` is the shared route identity and policy. Host-qualified sources that have no universally valid
transport are declared unavailable. A host activates only endpoints it can actually reach in
`$AGENT_ON_STATE/routes.local.toml`; the file is outside Git and may override `base_url` and `available` only:

```toml
version = 1
[sources."omlx@morty"]
base_url = "http://127.0.0.1:1238"
available = true
```

`status`, `sync`, `add`, `qualify`, and both launchers use the effective local address. The effective route hash
therefore changes with the override, so a qualification from a different endpoint is not treated as current. The
old `omlx/...` full route names redirect to their `omlx@rick/...` replacements for CLI compatibility only. Historical
observations and qualifications retain the old identity and are not promoted to the new endpoint.

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

Source names are arbitrary: `backend = "omlx"` selects the adapter for `omlx@rick`, `omlx@morty`, or any custom name;
`backend = "splash"` and `backend = "openrouter"` document native pass-through. An omitted backend is transparent
`passthrough` for compatibility and carries no effort-support claim. Each oMLX launch prints an `effort` object and
keeps a prompt-free, header-free receipt at `$AGENT_ON_STATE/effort/<launch-id>.jsonl` with requested and mapped
levels. Existing sessions keep their original connection; exit and launch again to gain this behavior.

### Host-qualified oMLX and Splash

The tracked identities are `omlx@rick`, `omlx@morty`, and `omlx@xz0831`. Their endpoints are host-local state.
On Rick, the existing `ai.clusterops.morty-model-forward` makes Morty's loopback `127.0.0.1:1238` reachable at
Rick loopback `127.0.0.1:18038`. Morty's current source cap is 32768 input tokens from its dedicated
`.omlx-dflash` settings; no 128K qualification is implied. xz0831's current loopback server is keyless and its
configured input/output caps are 32768. If that server later enables authentication, declare and provision a real
host key then; a placeholder must not be represented as a credential.

    ./bin/agent-on status 'omlx@morty/Huihui-Qwen3.8-27B-oQ4e-mtp'
    ./bin/claude-on --dry-run 'omlx@morty/Huihui-Qwen3.8-27B-oQ4e-mtp'
    ./bin/codex-on --dry-run 'omlx@morty/Huihui-Qwen3.8-27B-oQ4e-mtp'
    launchctl print gui/$(id -u)/ai.clusterops.morty-model-forward

Another checkout or host needs its own reachable source address or an explicitly configured forward; installing
agent-on creates neither a forward nor a model server. `splash@rick` and `splash@morty` are tracked unavailable
identities for the cluster-owned task runtime. They become launchable only after cluster operations authorizes an
endpoint and the host activates it. Agent-on consumes that endpoint; it does not reserve GPU resources, start or stop
Splash, or promote the task runtime to an always-on service.

Authentication and billing are independent declarations. An authenticated local oMLX source can still be `free`,
while a keyless source is not automatically treated as free. Catalog probes use the selected source key when one is
declared. Only OpenRouter sources use its spend endpoint.

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
