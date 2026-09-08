"""Helpers shared by every layer: RFC 3339 time, canonical JSON, short hashes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def utc_now() -> str:
    """RFC 3339 UTC to the second — the form of every `checked` / `at` / `ts` field (§7)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
