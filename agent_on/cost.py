"""§11 cost attribution, as pure functions. Cost is attributed per run at the price of that run; a price that is
absent is not 0; a turn no run covers cannot be priced. The launch (Plan B) feeds transcript turns and run
records in; the tests in tests/agent_on/test_cost.py are the contract."""
from __future__ import annotations

from .schemas.observed import USAGE_FIELDS
from .util import parse_utc

PRICE_FOR = {"input_tokens": "input", "output_tokens": "output",
             "cache_read_input_tokens": "cache_read", "cache_creation_input_tokens": "cache_write"}


def zero_usage() -> dict:
    return {k: 0 for k in USAGE_FIELDS}


def sum_usage(usages) -> dict:
    total = zero_usage()
    for usage in usages:
        for k in USAGE_FIELDS:
            total[k] += int(usage.get(k) or 0)
    return total


def price_usage(usage: dict, price: dict | None) -> tuple[float | None, list[str]]:
    """USD for one usage record at one price table (USD per Mtok for input, output, cache_read, cache_write).
    (None, reasons) when any non-zero field has no price."""
    if price is None:
        return None, ["no price table"]
    usd = 0.0
    reasons: list[str] = []
    for field, key in PRICE_FOR.items():
        n = int(usage.get(field) or 0)
        if n == 0:
            continue
        p = price.get(key)
        if p is None:
            reasons.append(f"{field}={n} but no {key} price")
            continue
        usd += n * float(p) / 1_000_000
    return (None, reasons) if reasons else (round(usd, 6), [])


def turns_in(turns, started: str, ended: str | None):
    s = parse_utc(started)
    e = parse_utc(ended) if ended else None
    for t in turns:
        ts = parse_utc(t["timestamp"])
        if ts >= s and (e is None or ts <= e):
            yield t


def attribute_run(turns: list[dict], run: dict) -> dict:
    """One launch's share of a transcript, as the ledger line `$STATE/sessions/<session-id>.jsonl` receives.
    Turns inside [started, ended] whose model is the run's wire_model are priced at `run["price"]` (the snapshot
    taken at spawn); a turn on another model is priced only if `run["priced_models"]` has it; anything else makes
    the run 'unknown' and is named in unknown_reasons."""
    mine = list(turns_in(turns, run["started"], run.get("ended")))
    usd = 0.0
    reasons: list[str] = []
    for t in mine:
        model = t["model"]
        price = run["price"] if model == run["wire_model"] else (run.get("priced_models") or {}).get(model)
        if price is None and model != run["wire_model"]:
            reasons.append(f"turn at {t['timestamp']} used {model!r}, which has no price on source {run['source']!r}")
            continue
        part, why = price_usage(t["usage"], price)
        if part is None:
            reasons.extend(why)
            continue
        usd += part
    return {"launch_id": run["launch_id"], "route": run["route"], "source": run["source"], "wire_model": run["wire_model"],
            "started": run["started"], "ended": run.get("ended"), "price": run["price"],
            "turns": len(mine), "usage": sum_usage(t["usage"] for t in mine),
            "cost_usd": "unknown" if reasons else round(usd, 6),
            "models_seen": sorted({t["model"] for t in mine}), "unknown_reasons": sorted(set(reasons))}


def fold_session(turns: list[dict], runs: list[dict]) -> dict:
    """session_total (§11): turns and usage from the whole transcript; cost_usd is the sum of the ledger lines only
    when every turn is covered by exactly one line and no line is unknown — else 'unknown' with the counts."""
    total = {"turns": len(turns), "usage": sum_usage(t["usage"] for t in turns)}
    covered = 0
    reasons: list[str] = []
    for t in turns:
        hits = [r for r in runs if any(True for _ in turns_in([t], r["started"], r.get("ended")))]
        if len(hits) == 1:
            covered += 1
        elif len(hits) > 1:
            reasons.append(f"turn at {t['timestamp']} is covered by {len(hits)} runs ({[r['launch_id'] for r in hits]})")
    uncovered = len(turns) - covered
    if uncovered:
        reasons.append(f"{uncovered} turn(s) not covered by any run ledger line — their price cannot be restored")
    for r in runs:
        if r.get("cost_usd") == "unknown":
            reasons.append(f"run {r['launch_id']} is unknown: " + "; ".join(r.get("unknown_reasons", [])))
    total["covered_turns"] = covered
    total["uncovered_turns"] = uncovered
    total["cost_usd"] = "unknown" if reasons else round(sum(float(r["cost_usd"]) for r in runs), 6)
    total["unknown_reasons"] = reasons
    return total
