from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from agent_on import cli  # noqa: E402
from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

FAKE = str(REPO / "tests" / "agent_on" / "fakeclaude.py")
FAKE_CODEX = str(REPO / "tests" / "agent_on" / "fakecodex.py")
CATALOG = [omlx_entry("alpha"), openrouter_entry("vendor/model-x")]


def first_route(paths) -> str:
    table = load_routes(paths)
    return sorted(n for n, r in table.routes.items() if r.packaged)[0]   # derived, never a literal; packaged so a scratch state root knows it


def sandboxed_env(sb, **extra) -> dict:
    """A fully controlled environment for a launch through the CLI: HOME and AGENT_ON_CHECKOUT point at the sandbox
    (final-fix item 3), never the real ~/.claude or the real routes.toml. Used both to `mock.patch.dict(os.environ,
    ..., clear=True)` an in-process `cli.main` call and, verbatim, as a subprocess `env=`."""
    return {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "AGENT_ON_STATE": str(sb.paths.state),
            "AGENT_ON_CHECKOUT": str(sb.paths.checkout), **extra}


class LaunchCliTest(unittest.TestCase):
    def test_parser_splits_launch_options_from_claude_args(self):
        p = cli.build_parser()
        a = p.parse_args(["launch", "--dry-run", "--haiku", "h", "some/route", "-p", "hi", "--model", "x"])
        self.assertEqual((a.command, a.route, a.dry_run, a.haiku, a.harness), ("launch", "some/route", True, "h", "claude"))
        self.assertEqual(a.claude_args, ["-p", "hi", "--model", "x"])
        q = p.parse_args(["qualify", "some/route", "--limits", "--allow-paid"])
        self.assertEqual((q.command, q.route, q.limits, q.allow_paid, q.baseline), ("qualify", "some/route", True, True, False))

    def test_dry_run_prints_the_plan_and_spawns_nothing(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            route = first_route(sb.paths)
            env = sandboxed_env(sb, FAKE_CLAUDE_OUT=str(sb.root / "out"))
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
                code = cli.main(["--json", "launch", "--dry-run", route, "-p", "hi"])
            self.assertEqual(code, 0)
            doc = json.loads(out.getvalue())
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["route"], route)
            self.assertEqual(doc["base_url"], m.base_url)                            # the sandbox's mock, never the real machine
            self.assertNotIn(":8000", doc["base_url"])
            self.assertIn("ANTHROPIC_BASE_URL", doc["env_keys"])
            self.assertFalse((sb.root / "out").exists())
            # isolation proof: harness.env.clean's "skip" reason names the sandbox home, not the runner's real ~/.claude
            clean = next(i for i in doc["invariants"] if i["id"] == "harness.env.clean")
            self.assertEqual(clean, {"id": "harness.env.clean", "result": "skip",
                                     "reason": f"no shared settings at {sb.paths.home / '.claude' / 'settings.json'}",
                                     "subject": None, "fix": None})

    def test_codex_harness_dry_run_through_the_cli(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            env = sandboxed_env(sb, AGENT_ON_CODEX_BIN=FAKE_CODEX)
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
                code = cli.main(["--json", "launch", "--harness", "codex", "--dry-run", "a", "exec", "hi"])
            self.assertEqual(code, 0)
            doc = json.loads(out.getvalue())
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["argv"][1:3], ["--profile", "agent-on"])

    def test_shim_delegates_to_launch(self):
        shim = REPO / "bin" / "claude-on"
        self.assertTrue(shim.stat().st_mode & 0o111)
        self.assertLessEqual(len(shim.read_text().splitlines()), 20)
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            route = first_route(sb.paths)
            proc = subprocess.run([str(shim), "--json", "--dry-run", route, "-p", "hi"], capture_output=True, text=True,
                                  env=sandboxed_env(sb))                             # a curated env, never the runner's own os.environ
            self.assertEqual(proc.returncode, 0, proc.stderr)
            doc = json.loads(proc.stdout)
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["base_url"], m.base_url)

    def test_real_launch_through_the_cli_returns_the_child_exit_code(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            route = first_route(sb.paths)
            env = sandboxed_env(sb, FAKE_CLAUDE_OUT=str(sb.root / "out"), FAKE_CLAUDE_EXIT="4", AGENT_ON_CLAUDE_BIN=FAKE)
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
                code = cli.main(["--json", "launch", route, "-p", "hi"])
            self.assertEqual(code, 4)
            doc = json.loads(out.getvalue().strip().splitlines()[-1])                 # the envelope is the last line; the child's stdout precedes it
            self.assertEqual(doc["exit_code"], 4)
            self.assertIn("last_session", doc)
            self.assertTrue((sb.root / "out" / "env.json").exists())
            # the fake claude never saw the runner's real home
            child_env = json.loads((sb.root / "out" / "env.json").read_text())
            self.assertEqual(child_env.get("CLAUDE_CONFIG_DIR"), str(sb.paths.claude_config_dir))

    def test_a_child_killed_by_a_signal_maps_to_128_plus_n(self):
        # F-fix 4: harness.spawn() returns subprocess.Popen.wait()'s raw code, negative for a signal death on
        # POSIX (SIGTERM = -15); the shell would show that as 241. The CLI boundary maps it to 128 + N (143).
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            route = first_route(sb.paths)
            env = sandboxed_env(sb, FAKE_CLAUDE_OUT=str(sb.root / "out"), FAKE_CLAUDE_SIGNAL="TERM", AGENT_ON_CLAUDE_BIN=FAKE)
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
                code = cli.main(["--json", "launch", route, "-p", "hi"])
            self.assertEqual(code, 143)
            doc = json.loads(out.getvalue().strip().splitlines()[-1])
            self.assertEqual(doc["exit_code"], -15)                                   # the envelope keeps the raw value


if __name__ == "__main__":
    unittest.main()
