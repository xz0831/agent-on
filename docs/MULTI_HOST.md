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

`routes.toml` names shared sources, models, limits, and aliases. If a source is reached at a different address on a
host, create `~/.local/state/agent-on/routes.local.toml`:

```toml
version = 1

[sources."omlx@morty"]
base_url = "http://127.0.0.1:1238"
```

Only `base_url` may be overridden, and only for a source already declared in the tracked route table. This keeps
machine topology out of the shared policy while retaining a single Git history.

## Claude sessions

The default session store is isolated under `~/.local/state/agent-on/claude-config`. To resume a session created by
ordinary Claude Code, select the native store before the route:

```sh
claude-on --session-store native <route> --resume <session-uuid>
claude-on --session-store native <route> --continue
```

Native mode uses `~/.claude` in place. Session data is not synchronized by Git, and one session must not be run
concurrently by normal Claude Code and Agent-on.
