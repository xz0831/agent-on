"""bin/agent-on must never let the caller's cwd shadow the checkout's own agent_on package.

`python -m agent_on` prepends the current working directory to sys.path ahead of PYTHONPATH,
so running the shim from inside a directory that itself holds an agent_on/ package (e.g. a
different checkout of this repo) would silently import that package instead of the shim's own.
The fix execs the interpreter with -P (Python >= 3.11), which disables that cwd-prepend while
still honouring PYTHONPATH.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

SHIM = REPO / "bin" / "agent-on"


class ShimCwdShadowTest(unittest.TestCase):
    def _run(self, cwd: Path, home: Path, state: Path):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "AGENT_ON_STATE": str(state),
        }
        return subprocess.run(
            [str(SHIM), "--help"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=env,
        )

    def test_decoy_package_in_cwd_is_not_shadowed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            decoy_dir = tmp / "decoy"
            pkg = decoy_dir / "agent_on"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("")
            (pkg / "__main__.py").write_text('print("DECOY"); raise SystemExit(7)\n')

            home = tmp / "home"
            home.mkdir()
            state = tmp / "state"

            result = self._run(decoy_dir, home, state)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("DECOY", result.stdout + result.stderr)
            self.assertIn("usage: agent-on", result.stdout)

    def test_run_from_repo_is_sane(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            home.mkdir()
            state = tmp / "state"

            result = self._run(REPO, home, state)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage: agent-on", result.stdout)


if __name__ == "__main__":
    unittest.main()
