from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from agent_on import cli  # noqa: E402
from agent_on.paths import default_paths  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

FAKE = str(REPO / "tests" / "agent_on" / "fakeclaude.py")


def first_route() -> str:
    table = load_routes(default_paths())
    return sorted(n for n, r in table.routes.items() if r.packaged)[0]   # derived, never a literal; packaged so a scratch state root knows it


class LaunchCliTest(unittest.TestCase):
    def test_parser_splits_launch_options_from_claude_args(self):
        p = cli.build_parser()
        a = p.parse_args(["launch", "--dry-run", "--haiku", "h", "some/route", "-p", "hi", "--model", "x"])
        self.assertEqual((a.command, a.route, a.dry_run, a.haiku, a.harness), ("launch", "some/route", True, "h", "claude"))
        self.assertEqual(a.claude_args, ["-p", "hi", "--model", "x"])
        q = p.parse_args(["qualify", "some/route", "--limits", "--allow-paid"])
        self.assertEqual((q.command, q.route, q.limits, q.allow_paid, q.baseline), ("qualify", "some/route", True, True, False))

    def test_dry_run_prints_the_plan_and_spawns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AGENT_ON_STATE": tmp, "FAKE_CLAUDE_OUT": tmp + "/out"}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--json", "launch", "--dry-run", first_route(), "-p", "hi"])
            self.assertEqual(code, 0)
            doc = json.loads(out.getvalue())
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["route"], first_route())
            self.assertIn("ANTHROPIC_BASE_URL", doc["env_keys"])
            self.assertFalse(Path(tmp, "out").exists())

    def test_shim_delegates_to_launch(self):
        shim = REPO / "bin" / "claude-on"
        self.assertTrue(shim.stat().st_mode & 0o111)
        self.assertLessEqual(len(shim.read_text().splitlines()), 20)
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([str(shim), "--json", "--dry-run", first_route(), "-p", "hi"], capture_output=True, text=True,
                                  env={**os.environ, "AGENT_ON_STATE": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["dry_run"])

    def test_real_launch_through_the_cli_returns_the_child_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AGENT_ON_STATE": tmp, "FAKE_CLAUDE_OUT": tmp + "/out", "FAKE_CLAUDE_EXIT": "4", "AGENT_ON_CLAUDE_BIN": FAKE}):
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--json", "launch", first_route(), "-p", "hi"])
            self.assertEqual(code, 4)
            doc = json.loads(out.getvalue().strip().splitlines()[-1])                 # the envelope is the last line; the child's stdout precedes it
            self.assertEqual(doc["exit_code"], 4)
            self.assertIn("last_session", doc)
            self.assertTrue(Path(tmp, "out", "env.json").exists())


if __name__ == "__main__":
    unittest.main()
