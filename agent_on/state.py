"""§7.1 storage rules. One advisory lock per state file; every writer re-reads under the lock; temp+fsync+rename;
one-line O_APPEND for ledgers. The routes.toml lock is keyed by the checkout (rev 6), never by the state root."""
from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .paths import Paths, ensure_state
from .schemas.observed import empty_observed, migrate_observed, validate_observed


@contextmanager
def locked(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def sweep_tmp(directory: Path, stem: str) -> int:
    """Delete `<stem>.tmp.*` left by a crashed writer. Returns how many."""
    n = 0
    for p in directory.glob(f"{stem}.tmp.*"):
        try:
            p.unlink()
            n += 1
        except FileNotFoundError:
            pass
    return n


def atomic_write(path: Path, text: str) -> None:
    """Write `<path>.tmp.<pid>`, fsync, rename over `path`. The caller holds the lock that serialises writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_observed(paths: Paths) -> dict:
    if not paths.observed_json.exists():
        return empty_observed()
    try:
        doc = json.loads(paths.observed_json.read_text(encoding="utf-8"))
    except ValueError as e:   # a corrupt observed.json must name itself: the CLI turns this into an operator hint
        raise ValueError(f"{paths.observed_json}: {e}") from e
    doc = migrate_observed(doc)
    validate_observed(doc)
    return doc


def update_observed(paths: Paths, mutate: Callable[[dict], None]) -> dict:
    """Read-modify-write under the observed lock. `mutate` edits the freshly re-read document in place; the result
    is validated before it is written, so a bad mutation leaves the file untouched."""
    ensure_state(paths)
    with locked(paths.observed_lock):
        sweep_tmp(paths.state, paths.observed_json.name)
        doc = read_observed(paths)
        mutate(doc)
        validate_observed(doc)
        atomic_write(paths.observed_json, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        return doc


def write_discovered(paths: Paths, text: str) -> None:
    """routes.discovered.toml is state and `sync` also writes observed.json: same lock (§7.1)."""
    ensure_state(paths)
    with locked(paths.observed_lock):
        sweep_tmp(paths.state, paths.discovered_toml.name)
        atomic_write(paths.discovered_toml, text)


@contextmanager
def checkout_locked(paths: Paths):
    """The routes.toml writer lock, `<checkout>/.routes.lock` — keyed by the resource it protects, so a default run
    and a AGENT_ON_STATE scratch run editing the same checkout contend for the same lock (§7.1, rev 6)."""
    with locked(paths.routes_lock):
        yield


def read_env_file(paths: Paths) -> dict[str, str]:
    """`KEY=value` lines in $STATE/env. Refused unless mode is 0600 — a secret readable by group/other is a defect."""
    p = paths.env_file
    if not p.exists():
        return {}
    mode = stat.S_IMODE(p.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"{p} is mode {oct(mode)}; it must be 0600 (chmod 600 {p})")
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def resolve_secret(paths: Paths, name: str, env: dict | None = None) -> str | None:
    """The environment wins over $STATE/env (§9), decided once in the parent (D2)."""
    env = os.environ if env is None else env
    if env.get(name):
        return env[name]
    return read_env_file(paths).get(name) or None


def append_session_run(paths: Paths, session_id: str, record: dict) -> Path:
    """One complete line, O_APPEND (§7.1). The per-session run ledger of §11."""
    ensure_state(paths)
    p = paths.sessions_dir / f"{session_id}.jsonl"
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return p


def read_session_runs(paths: Paths, session_id: str) -> list[dict]:
    p = paths.sessions_dir / f"{session_id}.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
