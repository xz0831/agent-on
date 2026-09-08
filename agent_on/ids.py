"""Launch ids (§7.1): ULIDs from the standard library — 48-bit millisecond time + 80 random bits, 26 Crockford
base32 characters, lexically sortable by time. The launcher mints one per launch before spawning."""
from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms: int | None = None, rand: bytes | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    rb = os.urandom(10) if rand is None else rand
    if ms < 0 or ms >= (1 << 48) or len(rb) != 10:
        raise ValueError("ulid: time must fit 48 bits and rand must be 10 bytes")
    value = (ms << 80) | int.from_bytes(rb, "big")
    out = []
    for _ in range(26):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))
