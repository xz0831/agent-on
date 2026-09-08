"""L0 reads (§5): catalog GETs, the local oMLX settings file, OpenRouter's key endpoint. Nothing here writes."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .schemas.routes import Source
from .util import utc_now

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


@dataclass
class Probe:
    reachable: bool
    checked: str
    error: str | None = None
    catalog: dict[str, dict] = field(default_factory=dict)
    catalog_count: int = 0
    identity: str | None = None


def is_loopback(url: str) -> bool:
    return (urlsplit(url).hostname or "") in LOOPBACK_HOSTS


def http_get_json(url: str, timeout: float, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_catalog(payload) -> dict[str, dict]:
    """One shape for both catalogs seen so far: oMLX (`max_model_len`, `owned_by`) and OpenRouter
    (`context_length`, `top_provider`, `pricing`, `supported_parameters`). Entries without a string id are skipped."""
    items = payload.get("data", []) if isinstance(payload, dict) else []
    out: dict[str, dict] = {}
    for m in items:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            continue
        top = m.get("top_provider") or {}
        max_in = m.get("max_model_len")
        if max_in is None:
            max_in = top.get("context_length") or m.get("context_length")
        out[m["id"]] = {"max_input": max_in, "max_output": top.get("max_completion_tokens"), "owned_by": m.get("owned_by"),
                        "pricing": m.get("pricing"), "supported_parameters": m.get("supported_parameters")}
    return out


def probe_source(source: Source, timeout: float = 5.0, headers: dict | None = None) -> Probe:
    url = source.catalog_url()
    checked = utc_now()
    if url is None:
        return Probe(False, checked, error="source declares no catalog")
    try:
        payload = http_get_json(url, timeout, headers)
    except urllib.error.HTTPError as e:
        e.close()
        return Probe(False, checked, error=f"HTTP {e.code} from {url}")
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return Probe(False, checked, error=f"{type(reason).__name__}: {reason} ({source.host()}:{source.port()})")
    catalog = normalize_catalog(payload)
    owners = sorted({v["owned_by"] for v in catalog.values() if v.get("owned_by")})
    return Probe(True, checked, catalog=catalog, catalog_count=len(catalog),
                 identity=f"owned_by={','.join(owners)}" if owners else None)


def probe_all(sources: dict[str, Source], timeout: float = 5.0) -> dict[str, Probe]:
    """Every source concurrently on daemon threads, so any number of stalled resolvers or black-holed hosts
    cannot pin `sync` past one shared window: all probes race against a single deadline set once, at
    timeout + 2 s from the start of this call — not timeout + 2 s per source. A probe that has not returned
    by then is recorded unreachable ('timeout') and its thread dies with the process instead of blocking exit."""
    results: dict[str, Probe] = {}

    def run(name: str, src: Source) -> None:
        results[name] = probe_source(src, timeout)

    threads = [threading.Thread(target=run, args=(n, s), daemon=True, name=f"probe-{n}") for n, s in sources.items()]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout + 2
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    for n in sources:
        results.setdefault(n, Probe(False, utc_now(), error=f"timeout: no answer within {timeout + 2:.0f}s"))
    return results


def omlx_settings_path(source: Source, home: Path) -> Path | None:
    """Only a loopback *oMLX* source's settings file is ours to read: a tailnet host's file is its own, and a
    non-oMLX loopback server (exo, vLLM, …) is not configured by ~/.omlx/settings.json at all. Spec §7 names the
    tier `sources.omlx*`, so the source name's part before any `@` must start with `omlx`."""
    if not is_loopback(source.base_url) or not source.name.partition("@")[0].startswith("omlx"):
        return None
    return home / ".omlx" / "settings.json"


def read_configured_limits(path: Path, home: Path) -> dict | None:
    """What the settings file *says* (`sampling.max_context_window` / `sampling.max_tokens`) — not what the server applied."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    s = doc.get("sampling") or {}
    shown = str(path)
    if shown.startswith(str(home)):
        shown = "~" + shown[len(str(home)):]
    return {"input": s.get("max_context_window"), "output": s.get("max_tokens"), "source": shown, "read_at": utc_now()}


def fetch_openrouter_spend(base_url: str, key: str, timeout: float = 5.0) -> dict:
    """OpenRouter `GET <base>/v1/auth/key` (measured 2026-09-07): data.usage is lifetime USD, data.limit +
    limit_reset the cap and its period, limit_remaining and usage_daily what is left and spent today.
    Errors are recorded, not raised — spend is informational (D6). The key label is never recorded."""
    checked = utc_now()
    url = base_url.rstrip("/") + "/v1/auth/key"
    empty = {"usd_used": None, "usd_limit": None, "limit_reset": None, "usd_remaining": None, "usd_used_daily": None,
             "source": f"openrouter GET {url}", "checked": checked, "error": None}
    try:
        d = http_get_json(url, timeout, {"Authorization": f"Bearer {key}"}).get("data", {})
    except urllib.error.HTTPError as e:
        e.close()
        return {**empty, "error": f"HTTP {e.code}"}
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, ValueError) as e:
        return {**empty, "error": f"{type(e).__name__}: {getattr(e, 'reason', e)}"}
    return {**empty, "usd_used": d.get("usage"), "usd_limit": d.get("limit"), "limit_reset": d.get("limit_reset"),
            "usd_remaining": d.get("limit_remaining"), "usd_used_daily": d.get("usage_daily")}
