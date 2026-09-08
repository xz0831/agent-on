"""L4 — the commands. Plan A ships status, sync, add, gate. Every command accepts --json and prints copy.* (§9)."""
from __future__ import annotations

import argparse
import json
import os
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
    l = sub.add_parser("launch", parents=[common], help="bind Claude Code to a route and run it; `claude-on <route>` is this verb (everything after the route goes to Claude Code)")
    l.add_argument("--harness", default="claude", choices=["claude"])
    l.add_argument("--discover", action="store_true", help="set CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1 (D8: off by default)")
    l.add_argument("--sonnet", metavar="ROUTE", help="bind the SONNET slot to another route on the same source")
    l.add_argument("--haiku", metavar="ROUTE", help="bind the HAIKU slot to another route on the same source")
    l.add_argument("--dry-run", action="store_true", help="print the environment keys, argv and cost line; spawn nothing")
    l.add_argument("route", help="a route name or alias")
    l.add_argument("claude_args", nargs=argparse.REMAINDER, help="passed to Claude Code unchanged")
    q = sub.add_parser("qualify", parents=[common], help="six fidelity gates + throughput/concurrency/caching/thinking probes; --baseline and --limits (paid sources need --allow-paid)")
    q.add_argument("route")
    q.add_argument("--baseline", action="store_true")
    q.add_argument("--limits", action="store_true")
    q.add_argument("--allow-paid", action="store_true")
    q.add_argument("--timeout", type=float, default=90.0)
    n = sub.add_parser("learn", parents=[common], help="validate and append one record to knowledge/<kind>.jsonl (id and ts minted when absent); `learn task …` is the task ledger")
    n.add_argument("kind", help="observations | decisions | traps | qualifications | gate-runs | tasks — or `task` for the ledger verbs")
    n.add_argument("--json-record", metavar="JSON", help="the record; when absent, one JSON object is read from stdin")
    # No `rest = REMAINDER` here (deliberately, see main()): a REMAINDER positional placed after `kind` in the
    # same parser greedily swallows any later recognized optional too — including --json-record — because
    # argparse's REMAINDER pattern matches both positional and optional tokens once its turn comes. `learn
    # decisions --json-record X` would parse json_record as None and rest as ["--json-record", "X"]. Routing
    # `learn task …` untouched to Task 6's parser is instead done via parse_known_args()'s leftover list.
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
    lines.append(f"discovered {len(doc['discovered'])} route(s); shadowed {len(doc['shadowed'])}; orphaned packaged: {doc['orphaned'] or 'none'}")
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
    if doc.get("knowledge"):
        lines.append(f"knowledge: gate-runs {doc['knowledge']['gate_run']}")
    return "\n".join(lines)


def render_launch(doc: dict) -> str:
    lines = [copy_line(doc["copy"]), doc["cost_line"]]
    lines += [f"warning: {w}" for w in doc["warnings"]]
    lines += [f"trap: {t['trap']} — avoid: {t['avoid']}" for t in doc.get("traps", [])]
    if doc.get("dry_run"):
        lines.append("dry run — argv: " + " ".join(doc["argv"]))
        lines.append("env: " + ", ".join(doc["env_keys"]))
        return "\n".join(lines + invariant_lines(doc["invariants"]))
    ls = doc.get("last_session") or {}
    lines.append(f"exit {doc['exit_code']} · session {doc['session']['id'] or '?'} ({doc['session']['mode']})")
    if "skipped" in ls:
        lines.append(f"read-back skipped: {ls['skipped']}")
    elif ls:
        lines.append(f"this run: {ls['this_run']['turns']} turns, ${ls['this_run']['cost_usd']} · session: {ls['session_total']['turns']} turns, ${ls['session_total']['cost_usd']}")
    return "\n".join(lines)


def render_qualify(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    if doc["refused"]:
        return "\n".join(lines + [f"refused: {doc['refused']}"])
    lines += [f"  {'pass' if ok else 'FAIL'} {g}" for g, ok in doc["gates"].items()]
    p = doc["probes"]
    lines.append(f"tok/s {p['throughput']['tok_s'] and round(p['throughput']['tok_s'])} · concurrency {p['concurrency']['concurrency']} (pair/serial {p['concurrency']['ratio']})"
                 f" · caching {p['caching']['caching']} (cache_read {p['caching']['cache_read_second']})")
    if doc["baseline"] is not None:
        lines.append(f"harness baseline: {doc['baseline']} input tokens")
    if p.get("limits"):
        lines.append(f"verified input limit: {p['limits']['verified']} ({len(p['limits']['probes'])} probes)")
    lines.append("fingerprint: " + json.dumps(doc["fingerprint"], sort_keys=True))
    return "\n".join(lines + invariant_lines(doc["invariants"]))


def render_learn(doc: dict) -> str:
    lines = [copy_line(doc["copy"])]
    lines.append(f"learned {doc['record']['id']} → {doc['path']}" if doc["written"] else "NOT learned")
    return "\n".join(lines + invariant_lines(doc["invariants"]))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # parse_known_args, not parse_args: `learn task …` must reach Task 6's task parser with its own arguments
    # untouched (see build_parser()'s note on why `rest` isn't a REMAINDER positional). Every other command keeps
    # parse_args's strict behavior — any leftover token still raises the usual "unrecognized arguments" usage
    # error (this replicates what parse_args does internally: parse_known_args, then error() on leftovers).
    args, extra = parser.parse_known_args(argv)
    rest = extra if args.command == "learn" and getattr(args, "kind", None) == "task" else []
    if extra and not rest:
        parser.error("unrecognized arguments: %s" % " ".join(extra))
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
        elif args.command == "launch":
            from .harness import run_launch
            doc = run_launch(paths, args.route, args.claude_args, harness=args.harness, discover=args.discover, sonnet=args.sonnet,
                             haiku=args.haiku, dry_run=args.dry_run, claude_bin=os.environ.get("AGENT_ON_CLAUDE_BIN"))
            if args.dry_run:
                code = 0
            else:
                # subprocess.Popen.wait() returns a negative code (-N) for a child killed by signal N on POSIX;
                # the shell shows that raw value as 256 - N (e.g. 241 for SIGTERM). Map it to the usual 128 + N
                # (143) at this boundary only — the JSON envelope's exit_code keeps the raw value (§9).
                raw = int(doc["exit_code"])
                code = 128 - raw if raw < 0 else raw
            text = render_launch(doc)
        elif args.command == "qualify":
            from .qualify import run_qualify
            doc = run_qualify(paths, args.route, baseline=args.baseline, limits=args.limits, allow_paid=args.allow_paid, timeout=args.timeout,
                              claude_bin=os.environ.get("AGENT_ON_CLAUDE_BIN"))
            code = EXIT_OK if doc["written"] and all(doc["gates"].values()) else EXIT_FAIL
            text = render_qualify(doc)
        elif args.command == "learn":
            if args.kind == "task":
                from .tasks import run_task_verb                     # Task 6; until then a usage error
                doc, code = run_task_verb(paths, rest)
                text = doc.get("text") or json.dumps(doc, indent=1, sort_keys=True)
            else:
                from .knowledge import append
                from .invariants import build_context, evaluate
                raw = args.json_record if args.json_record is not None else sys.stdin.read()
                if not raw.strip():
                    doc = {"command": "learn", "copy": describe_copy(paths), "error": "learn: no record given (use --json-record or stdin)", "hint": "pass one JSON object"}
                    print(json.dumps(doc, indent=1, sort_keys=True) if args.json else f"{copy_line(doc['copy'])}\nerror: {doc['error']}")
                    return EXIT_USAGE
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    doc = {"command": "learn", "copy": describe_copy(paths), "error": f"record is not JSON: {e}", "hint": "pass one JSON object"}
                    print(json.dumps(doc, indent=1, sort_keys=True) if args.json else f"{copy_line(doc['copy'])}\nerror: {doc['error']}")
                    return EXIT_USAGE
                written = append(paths, args.kind, rec)
                doc = {"command": "learn", "copy": describe_copy(paths), "kind": args.kind, "written": True, "record": written,
                       "path": str(paths.knowledge_dir / f"{args.kind}.jsonl"),
                       "invariants": [r.as_dict() for r in evaluate(build_context(paths), ids=["knowledge.typed"])]}
                code, text = EXIT_OK, render_learn(doc)
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
    except (OSError, ValueError) as e:
        # An operator's broken state file or permissions is a reportable condition, not a traceback: `--json`
        # callers must still get the envelope (copy.*, error, hint), and the hint must say what to do.
        if isinstance(e, json.JSONDecodeError) or "observed.json" in str(e):
            hint = "observed.json is unreadable: move it aside and run `agent-on sync` to rebuild it"
        elif isinstance(e, PermissionError) and "env" in str(e):
            hint = "$STATE/env must be mode 0600"
        else:
            hint = None
        doc = {"command": args.command, "copy": describe_copy(paths), "error": f"{type(e).__name__}: {e}", "hint": hint}
        code = EXIT_FAIL
        text = f"{copy_line(doc['copy'])}\nerror: {doc['error']}" + (f"\nhint: {hint}" if hint else "")
    if args.json and args.command == "launch" and not getattr(args, "dry_run", False):
        print("\n" + json.dumps(doc, sort_keys=True, ensure_ascii=False))          # one line after the child's own stdout: take the last line
    else:
        print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) if args.json else text)
    return code


if __name__ == "__main__":
    sys.exit(main())
