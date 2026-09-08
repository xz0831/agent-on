"""L4 — the commands. Plan A ships status, sync, add, gate. Every command accepts --json and prints copy.* (§9)."""
from __future__ import annotations

import argparse
import json
import sys

from .paths import default_paths, describe_copy
from .schemas.errors import SchemaError

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_SCHEMA = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    # `--json` is accepted before or after the verb. The per-verb copy defaults to SUPPRESS so that, when absent,
    # it does not overwrite a `--json` given before the verb (argparse lets subparser defaults clobber parent values).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    p = argparse.ArgumentParser(prog="agent-on", description="run the Claude Code harness on any model from any source")
    p.add_argument("--json", action="store_true", help="machine-readable output (every command; before or after the verb)")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("status", parents=[common], help="L1 beside L2; --check evaluates every invariant and writes last_check")
    s.add_argument("route", nargs="?", help="a route name or alias; default: every route")
    s.add_argument("--check", action="store_true")
    y = sub.add_parser("sync", parents=[common], help="probe every source; refresh catalogs, served flags, limits, spend; rewrite routes.discovered.toml")
    y.add_argument("--timeout", type=float, default=5.0, help="seconds per source (default 5)")
    a = sub.add_parser("add", parents=[common], help="declare a packaged route in routes.toml (limits, reasoning, price filled from the catalog)")
    a.add_argument("name", metavar="<source>/<model>")
    a.add_argument("--alias")
    a.add_argument("--timeout", type=float, default=5.0)
    sub.add_parser("gate", parents=[common], help="unit tests + mock-source smoke + every invariant; writes last_gate_run")
    return p


def copy_line(c: dict) -> str:
    return (f"copy: {c['checkout']} @ {c['commit'] or '?'}{' (dirty)' if c['dirty'] else ''}"
            f" · state {c['state']} · {c['python']}" + (f" · shim {c['shim']}" if c["shim"] else " · no shim"))


def invariant_lines(results: list[dict]) -> list[str]:
    return [f"  {r['result']:4} {r['id']}" + (f"[{r['subject']}]" if r.get("subject") else "") + f": {r['reason']}"
            + (f" — fix: {r['fix']}" if r.get("fix") else "") for r in results]


def render_sync(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    for n, s in doc["sources"].items():
        lines.append(f"source {n}: " + ("reachable, catalog " + str(s["catalog_count"]) if s["reachable"] else f"unreachable ({s['error']})"))
    lines.append(f"discovered {len(doc['discovered'])} route(s); shadowed {len(doc['shadowed'])}; orphaned packaged: {doc['orphans'] or 'none'}")
    for n, sp in doc["spend"].items():
        lines.append(f"spend {n}: " + (f"error {sp['error']}" if sp.get("error") else f"used ${sp['usd_used']} · limit ${sp['usd_limit']}/{sp['limit_reset']} · remaining ${sp['usd_remaining']} · today ${sp['usd_used_daily']}"))
    return "\n".join(lines + invariant_lines(doc["invariants"]))


def render_add(doc: dict) -> str:
    lines = [copy_line(doc["copy"]), f"{'added' if doc['written'] else 'NOT added'}: {doc['route']}"]
    if doc["written"]:
        lines.append(doc["block"].rstrip())
    return "\n".join(lines + invariant_lines(doc["invariants"]))


def render_gate(doc: dict) -> str:
    t = doc["tests"]
    lines = [copy_line(doc["copy"]),
             "tests: " + (f"skipped ({t['skipped']})" if t["skipped"] else f"ran {t['ran']} — {'ok' if t['ok'] else 'FAILED: ' + ' | '.join(t['tail'])}"),
             f"smoke (F1 on the mock source): {'ok' if doc['smoke']['ok'] else 'FAILED ' + str(doc['smoke']['results'])}"]
    lines += invariant_lines(doc["invariants"])
    g = doc["last_gate_run"]
    lines.append(f"result: {g['result']} · skipped {g['skipped']} · mock port {g['mock_port']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = default_paths()
    try:
        if args.command == "status":
            from .status import build_status, render_text
            doc = build_status(paths, route=args.route, check=args.check)
            code = EXIT_FAIL if args.check and any(i["result"] == "fail" for i in doc["invariants"]) else EXIT_OK
            text = render_text(doc)
        elif args.command == "sync":
            from .sync import run_sync
            doc = run_sync(paths, timeout=args.timeout)
            code = EXIT_FAIL if any(i["result"] == "fail" for i in doc["invariants"]) else EXIT_OK
            text = render_sync(doc)
        elif args.command == "add":
            from .add import run_add
            doc = run_add(paths, args.name, alias=args.alias, timeout=args.timeout)
            code = EXIT_OK if doc["written"] else EXIT_FAIL
            text = render_add(doc)
        else:
            from .gate import run_gate
            doc = run_gate(paths)
            code = EXIT_OK if doc["result"] == "pass" else EXIT_FAIL
            text = render_gate(doc)
    except SchemaError as e:
        doc = {"command": args.command, "copy": describe_copy(paths), "error": str(e), "rule": e.rule}
        code, text = EXIT_SCHEMA, f"{copy_line(doc['copy'])}\nschema: {e}"
    except KeyError as e:  # RouteTable.resolve(): unknown route or alias
        doc = {"command": args.command, "copy": describe_copy(paths), "error": str(e.args[0])}
        code, text = EXIT_USAGE, f"{copy_line(doc['copy'])}\nerror: {e.args[0]}"
    print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) if args.json else text)
    return code


if __name__ == "__main__":
    sys.exit(main())
