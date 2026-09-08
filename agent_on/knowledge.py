"""L5 — knowledge/ (§10): git-tracked, append-only JSONL in the checkout, one file per kind, every record typed and
carrying id + ts. This module is the only writer path: `learn`, `qualify`, the gate and the launch all append here."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .ids import ulid
from .paths import Paths
from .schemas.errors import SchemaError
from .schemas.knowledge import KINDS, validate_record
from .state import locked
from .util import utc_now


def _path(paths: Paths, kind: str) -> Path:
    if kind not in KINDS:
        raise SchemaError("knowledge.record", f"unknown kind {kind!r}; kinds: {sorted(KINDS)}")
    return paths.knowledge_dir / f"{kind}.jsonl"


def read(paths: Paths, kind: str) -> list[dict]:
    """Every record of one kind in file order (append order is time order). A missing file is empty."""
    p = _path(paths, kind)
    if not p.exists():
        return []
    out: list[dict] = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            validate_record(kind, rec)
        except (ValueError, SchemaError) as e:
            raise SchemaError("knowledge.record", f"{p.name}:{n}: {e}") from None
        out.append(rec)
    return out


def append(paths: Paths, kind: str, rec: dict, *, now: str | None = None) -> dict:
    """Validate, then append one line under the knowledge lock. id and ts are minted when absent (§9); a caller that
    brings its own id (the seeds) keeps it. `supersedes` must name an existing id of the same kind. Nothing is
    written when validation fails."""
    p = _path(paths, kind)
    rec = dict(rec)
    rec.setdefault("id", f"{kind}-{ulid()}")
    rec.setdefault("ts", now or utc_now())
    validate_record(kind, rec)
    with locked(paths.knowledge_lock):
        existing = read(paths, kind)
        if any(r["id"] == rec["id"] for r in existing):
            raise SchemaError("knowledge.record", f"{kind}: id {rec['id']} already exists")
        if "supersedes" in rec and not any(r["id"] == rec["supersedes"] for r in existing):
            raise SchemaError("knowledge.record", f"{kind}: supersedes {rec['supersedes']} not found")
        p.parent.mkdir(exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return rec


def active(records: list[dict]) -> list[dict]:
    """Records not superseded by a later one."""
    dead = {r["supersedes"] for r in records if "supersedes" in r}
    return [r for r in records if r["id"] not in dead]


def latest(records: list[dict], *, route: str | None, n: int = 3) -> list[dict]:
    sel = [r for r in records if route is None or r.get("route") == route]
    return sel[-n:] if n else []


def applicable_traps(traps: list[dict], *, route: str | None, source: str | None, action: str) -> list[dict]:
    keys = {"*", action, source, route} - {None}
    return [t for t in traps if keys.intersection(t["applies_to"])]


def knowledge_view(paths: Paths, *, route: str | None, source: str | None, action: str, n: int = 3) -> dict:
    """What status and the launch show for one route: the last n observations and the traps for the action in hand.

    D6: inform, don't gate. A malformed line in either file must not take down every launch or plain `status` — it
    is surfaced as `error` (naming file:line, from `read`'s SchemaError) with empty observations/traps, rather than
    raised. `status --check`'s `knowledge.typed` invariant still fails on the same file; that is the gate."""
    if not paths.knowledge_dir.is_dir():
        return {"observations": [], "traps": [], "missing": True}
    try:
        observations = latest(read(paths, "observations"), route=route, n=n)
        traps = applicable_traps(active(read(paths, "traps")), route=route, source=source, action=action)
    except SchemaError as e:
        return {"observations": [], "traps": [], "error": str(e)}
    return {"observations": observations, "traps": traps}
