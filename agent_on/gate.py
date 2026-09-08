"""`agent-on gate` (§8): unit tests, the mock-source smoke that reproduces F1, every invariant; then
`last_gate_run` to L2 with every skip listed and the mock's port, plus its knowledge/gate-runs.jsonl twin (§10)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .invariants import build_context, evaluate, skipped_ids
from .mock_source import MockSource, omlx_entry
from .paths import Paths, describe_copy
from .state import update_observed
from .sync import run_sync
from .util import utc_now

VERIFIERS: list[str] = []          # verifier processes join in Plan B; declared here so gate.no_silent_skip holds them to account
INNER_ENV = "AGENT_ON_GATE_INNER"

SMOKE_ROUTES = """version = 1
[sources.mock]
base_url = "{base}"
catalog = "/v1/models"
discover = true
[sources.mock.limits]
input = 4096
output = 1024
confidence = "owned-policy"
source = "gate smoke"
[routes."mock/alive"]
[routes."mock/dead"]
"""


def run_unit_tests(checkout: Path) -> dict:
    if os.environ.get(INNER_ENV):
        return {"ran": None, "ok": None, "tail": [], "skipped": "inner gate (tests already running)"}
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(checkout / "tests" / "agent_on"), "-p", "test_*.py"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(checkout), env={**os.environ, INNER_ENV: "1"}, timeout=900)
    m = re.search(r"Ran (\d+) tests?", proc.stderr)
    return {"ran": int(m.group(1)) if m else 0, "ok": proc.returncode == 0,
            "tail": proc.stderr.strip().splitlines()[-3:], "skipped": None}


def run_smoke(mock: MockSource) -> dict:
    """F1 on every gate run: a planted dead wire_model must fail route.served; a live one and a discovered one must pass."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "co").mkdir()
        (root / "home").mkdir()
        (root / "co" / "routes.toml").write_text(SMOKE_ROUTES.format(base=mock.base_url), encoding="utf-8")
        paths = Paths(checkout=root / "co", state=root / "state", home=root / "home")
        run_sync(paths, timeout=5, env={})
        results = {f"{r.id}:{r.subject}": r.result for r in evaluate(build_context(paths), ids=["route.served"])}
    expected = {"route.served:mock/alive": "pass", "route.served:mock/dead": "fail", "route.served:mock/extra": "pass"}
    return {"ok": all(results.get(k) == v for k, v in expected.items()), "results": results, "expected": expected}


def run_gate(paths: Paths) -> dict:
    with MockSource(catalog=[omlx_entry("alive"), omlx_entry("extra")]) as mock:
        tests = run_unit_tests(paths.checkout)
        smoke = run_smoke(mock)
        mock_port = mock.port
    ctx = build_context(paths, with_claude_code=True)
    results = evaluate(ctx)
    failed = tests["ok"] is False or not smoke["ok"] or any(r.result == "fail" for r in results)
    record = {"at": utc_now(), "commit": describe_copy(paths)["commit"], "result": "fail" if failed else "pass",
              "tests": tests["ran"], "tests_ok": tests["ok"], "smoke_ok": smoke["ok"],
              "verifiers": {"declared": list(VERIFIERS), "ran": []},
              "invariants": {f"{r.id}:{r.subject}" if r.subject else r.id: r.result for r in results},
              "skipped": skipped_ids(results) + ([f"tests:{tests['skipped']}"] if tests["skipped"] else []),
              "skipped_reasons": [f"{r.id}{'[' + r.subject + ']' if r.subject else ''}: {r.reason}" for r in results if r.result == "skip"],
              "mock_port": mock_port}
    update_observed(paths, lambda d: d.__setitem__("last_gate_run", record))
    kn = None
    if paths.knowledge_dir.is_dir():                                               # the durable twin of last_gate_run (§10, Q4)
        from .knowledge import append
        rec = append(paths, "gate-runs", {"commit": record["commit"], "result": record["result"], "tests": record["tests"],
                                          "verifiers": record["verifiers"], "invariants": record["invariants"],
                                          "skipped_reasons": record["skipped_reasons"], "mock_port": record["mock_port"]}, now=record["at"])
        kn = {"gate_run": rec["id"]}
    return {"command": "gate", "copy": describe_copy(paths), "tests": tests, "smoke": smoke,
            "invariants": [r.as_dict() for r in results], "last_gate_run": record, "result": record["result"], "knowledge": kn}
