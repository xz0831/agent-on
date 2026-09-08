"""Where everything lives (D9, D13). One checkout, one state root; `AGENT_ON_STATE` overrides the root."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
CHECKOUT = PACKAGE_DIR.parent


@dataclass(frozen=True)
class Paths:
    checkout: Path          # holds routes.toml (and knowledge/ from Plan C)
    state: Path             # D13: machine-written state, outside git
    home: Path              # ~ — for the shim and the shared ~/.claude/settings.json lint
    tree: Path | None = None  # the code tree the lints scan; defaults to `checkout` (they coincide in production)

    @property
    def code_tree(self) -> Path:
        return self.tree or self.checkout

    @property
    def routes_toml(self) -> Path:
        return self.checkout / "routes.toml"

    @property
    def routes_lock(self) -> Path:
        # rev-6 P2: keyed by the resource it protects, never by the state root, so every AGENT_ON_STATE shares it
        return self.checkout / ".routes.lock"

    @property
    def discovered_toml(self) -> Path:
        return self.state / "routes.discovered.toml"

    @property
    def observed_json(self) -> Path:
        return self.state / "observed.json"

    @property
    def observed_lock(self) -> Path:
        return self.state / "locks" / "observed.lock"

    @property
    def sessions_dir(self) -> Path:
        return self.state / "sessions"

    @property
    def env_file(self) -> Path:
        return self.state / "env"

    @property
    def shim(self) -> Path:
        return self.home / ".local" / "bin" / "agent-on"


def default_paths(env: dict | None = None) -> Paths:
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    if env.get("AGENT_ON_STATE"):
        state = Path(env["AGENT_ON_STATE"])
    else:
        state = Path(env.get("XDG_STATE_HOME") or (home / ".local" / "state")) / "agent-on"
    return Paths(checkout=CHECKOUT, state=state, home=home, tree=CHECKOUT)


def ensure_state(paths: Paths) -> None:
    for d in (paths.state, paths.observed_lock.parent, paths.sessions_dir):
        existed = d.exists()
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not existed:
            os.chmod(d, 0o700)   # only a directory *we* created is ours to re-mode; an operator's own mode stands


def describe_copy(paths: Paths) -> dict:
    """§7 `copy.*`: which checkout, which commit, dirty or not, where the shim points, which Python, which state root."""
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", str(paths.checkout), *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = git("rev-parse", "--short", "HEAD")
    porcelain = git("status", "--porcelain")
    shim: str | None = None
    if paths.shim.is_symlink():
        shim = f"{paths.shim} -> {os.readlink(paths.shim)}"
    elif paths.shim.exists():
        shim = f"{paths.shim} (not a symlink)"
    v = sys.version_info
    return {"checkout": str(paths.checkout), "commit": commit,
            "dirty": None if porcelain is None else bool(porcelain),
            "shim": shim, "python": f"{sys.executable} {v.major}.{v.minor}.{v.micro}", "state": str(paths.state)}
