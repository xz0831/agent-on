# Multi-host operation

`https://github.com/xz0831/agent-on` is the canonical code and route-policy repository for Rick, Morty, and xz0831.
Each host has its own checkout, state root, credentials, observed measurements, and Claude/Codex sessions.

## Install

```sh
git clone https://github.com/xz0831/agent-on.git ~/Projects/agent-on
cd ~/Projects/agent-on
./bin/agent-on install
./bin/agent-on status --check
```

The checkout itself is the installation. The installer links `agent-on`, `claude-on`, and `codex-on` from
`~/.local/bin` to that checkout. Python 3.11 or newer is required; the shim checks the active `python3` and standard
Homebrew locations. Credentials belong in `~/.local/state/agent-on/env` with mode `0600`, never in Git.

## Update

On a clean checkout:

```sh
git -C ~/Projects/agent-on pull --ff-only
~/Projects/agent-on/bin/agent-on install
agent-on status --check
```

Do not pull over local source-code edits. Commit and push a reviewed change from one host, then fast-forward the
other two hosts. Machine observations and sessions remain local, so a pull does not overwrite them.

## Host-local endpoints

`routes.toml` names shared sources, models, limits, credentials, billing, and aliases. Host-qualified local sources
are unavailable in the tracked file because one loopback address cannot identify the same host from all three Macs.
Activate only sources that this host can actually reach in `~/.local/state/agent-on/routes.local.toml`.

Rick can activate its local oMLX and the existing Morty forward:

```toml
version = 1

[sources."omlx@rick"]
base_url = "http://127.0.0.1:8000"
available = true

[sources."omlx@morty"]
base_url = "http://127.0.0.1:18038"
available = true
```

Morty activates its dedicated DFlash service directly:

```toml
version = 1
[sources."omlx@morty"]
base_url = "http://127.0.0.1:1238"
available = true
```

xz0831 activates its current keyless loopback service:

```toml
version = 1
[sources."omlx@xz0831"]
base_url = "http://127.0.0.1:8000"
available = true
```

Only `base_url` and `available` may be overridden, and only for a source already declared in the tracked route table.
Credentials remain in the mode-0600 state env. Rick and Morty use their distinct real oMLX keys; xz0831 currently
declares no key because its server currently requires none. Splash stays unavailable until cluster operations
authorizes an endpoint; this repository does not assume that an always-on Splash lifecycle manager exists.

## Concurrent sessions

Each `claude-on` process owns one route, one temporary credential helper, and one Claude session. Normal `claude`,
OpenRouter, and multiple local-engine sessions can therefore coexist as processes. Agent-on does not allocate unified
memory or arbitrate concurrent inference between oMLX, Splash, and EXO. That admission and lifecycle boundary belongs
to cluster operations and the serving layer. A reachable endpoint is not evidence that cross-engine concurrent GPU
work is safe.

## Claude sessions

The default session store is isolated under `~/.local/state/agent-on/claude-config`. To resume a session created by
ordinary Claude Code, select the native store before the route:

```sh
claude-on --session-store native <route> --resume <session-uuid>
claude-on --session-store native <route> --continue
```

Native mode uses `~/.claude` in place. Session data is not synchronized by Git, and one session must not be run
concurrently by normal Claude Code and Agent-on.
