from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

from agent_on import cli  # noqa: E402


class CliTest(unittest.TestCase):
    def test_help_lists_the_four_plan_a_commands(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            cli.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        for verb in ("status", "sync", "add", "gate"):
            self.assertIn(verb, out.getvalue())

    def test_json_is_accepted_before_or_after_the_verb(self):
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["status", "--json"]).json)
        self.assertTrue(parser.parse_args(["--json", "status"]).json)
        self.assertFalse(parser.parse_args(["status"]).json)
        self.assertTrue(parser.parse_args(["add", "mock/x", "--json", "--alias", "a"]).json)
        self.assertFalse(parser.parse_args(["gate"]).json)

    def test_unknown_command_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cli.main(["frobnicate"])
        self.assertEqual(cm.exception.code, 2)

    def test_shim_runs_the_package_and_checks_the_interpreter(self):
        shim = REPO / "bin" / "agent-on"
        self.assertTrue(shim.exists() and shim.stat().st_mode & 0o111, "bin/agent-on must be executable")
        self.assertLessEqual(len(shim.read_text().splitlines()), 20, "the shim is ≤ 20 lines (D4)")
        proc = subprocess.run([str(shim), "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("status", proc.stdout)
        bad = subprocess.run([str(shim), "--help"], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "AGENT_ON_PYTHON": "/bin/false"})
        self.assertEqual(bad.returncode, 3)
        self.assertIn("3.11", bad.stderr)


if __name__ == "__main__":
    unittest.main()
