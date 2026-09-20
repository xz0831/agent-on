from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

from agent_on.paths import CHECKOUT, Paths, default_paths, describe_copy, ensure_state  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_default_state_root_follows_xdg_then_home(self):
        p = default_paths(env={"HOME": "/h"})
        self.assertEqual(p.state, Path("/h/.local/state/agent-on"))
        p = default_paths(env={"HOME": "/h", "XDG_STATE_HOME": "/x"})
        self.assertEqual(p.state, Path("/x/agent-on"))
        p = default_paths(env={"HOME": "/h", "XDG_STATE_HOME": "/x", "AGENT_ON_STATE": "/s"})
        self.assertEqual(p.state, Path("/s"))
        self.assertEqual(p.checkout, CHECKOUT)
        self.assertEqual(p.code_tree, CHECKOUT)

    def test_agent_on_checkout_overrides_checkout_and_tree_for_a_sandboxed_cli_subprocess(self):
        # final-fix item 3: a CLI-launch test needs a subprocess to resolve routes.toml from a sandbox, not the
        # real installation; AGENT_ON_CHECKOUT is read only here, and only when set.
        p = default_paths(env={"HOME": "/h"})
        self.assertEqual((p.checkout, p.code_tree), (CHECKOUT, CHECKOUT))
        p = default_paths(env={"HOME": "/h", "AGENT_ON_CHECKOUT": "/sandbox/co"})
        self.assertEqual((p.checkout, p.code_tree), (Path("/sandbox/co"), Path("/sandbox/co")))

    def test_routes_lock_is_keyed_by_the_checkout_not_the_state_root(self):
        # rev-6 P2: two runs with different AGENT_ON_STATE must take the same lock for the same routes.toml
        a = Paths(checkout=Path("/co"), state=Path("/s1"), home=Path("/h"))
        b = Paths(checkout=Path("/co"), state=Path("/s2"), home=Path("/h"))
        self.assertEqual(a.routes_lock, b.routes_lock)
        self.assertEqual(a.routes_lock, Path("/co/.routes.lock"))
        self.assertNotEqual(a.observed_lock, b.observed_lock)
        self.assertEqual(a.observed_lock, Path("/s1/locks/observed.lock"))

    def test_derived_paths(self):
        p = Paths(checkout=Path("/co"), state=Path("/s"), home=Path("/h"))
        self.assertEqual(p.routes_toml, Path("/co/routes.toml"))
        self.assertEqual(p.discovered_toml, Path("/s/routes.discovered.toml"))
        self.assertEqual(p.local_routes_toml, Path("/s/routes.local.toml"))
        self.assertEqual(p.observed_json, Path("/s/observed.json"))
        self.assertEqual(p.sessions_dir, Path("/s/sessions"))
        self.assertEqual(p.env_file, Path("/s/env"))
        self.assertEqual(p.shim, Path("/h/.local/bin/agent-on"))

    def test_ensure_state_creates_private_dirs(self):
        import tempfile, stat
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(checkout=Path(tmp), state=Path(tmp) / "st", home=Path(tmp))
            ensure_state(p)
            for d in (p.state, p.observed_lock.parent, p.sessions_dir):
                self.assertTrue(d.is_dir())
                self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)

    def test_describe_copy_reports_real_git_facts(self):
        p = default_paths()
        c = describe_copy(p)
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(c["commit"], head)
        self.assertIn(c["dirty"], (True, False))
        self.assertTrue(c["python"].startswith(sys.executable))
        self.assertEqual(set(c), {"checkout", "commit", "dirty", "shim", "python", "state"})

    def test_describe_copy_without_git_is_honest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            c = describe_copy(Paths(checkout=Path(tmp), state=Path(tmp) / "s", home=Path(tmp)))
            self.assertIsNone(c["commit"])
            self.assertIsNone(c["dirty"])
            self.assertIsNone(c["shim"])

    def test_describe_copy_falls_back_when_the_path_git_cannot_run(self):
        def run(argv, **kwargs):
            if argv[0] == "/broken/git":
                return subprocess.CompletedProcess(argv, 69, "", "license required")
            if argv[1:] == ["--version"]:
                return subprocess.CompletedProcess(argv, 0, "git version 2.55.0\n", "")
            if "rev-parse" in argv:
                return subprocess.CompletedProcess(argv, 0, "abc1234\n", "")
            if "status" in argv:
                return subprocess.CompletedProcess(argv, 0, "", "")
            raise AssertionError(argv)

        p = Paths(checkout=Path("/co"), state=Path("/s"), home=Path("/h"))
        with mock.patch("agent_on.paths.shutil.which", return_value="/broken/git"), \
             mock.patch("agent_on.paths.subprocess.run", side_effect=run):
            c = describe_copy(p)
        self.assertEqual(c["commit"], "abc1234")
        self.assertFalse(c["dirty"])

    def test_launch_paths_and_project_slug(self):
        from agent_on.paths import project_slug
        p = Paths(checkout=Path("/co"), state=Path("/s"), home=Path("/h"))
        self.assertEqual(p.run_dir, Path("/s/run"))
        self.assertEqual(p.claude_config_dir, Path("/s/claude-config"))
        self.assertEqual(project_slug("/Users/rick/.openclaw"), "-Users-rick--openclaw")
        self.assertEqual(project_slug("/Users/rick/Projects/agent-on"), "-Users-rick-Projects-agent-on")
        self.assertEqual(p.transcript_path("abc-123", "/Users/rick/x y"), Path("/s/claude-config/projects/-Users-rick-x-y/abc-123.jsonl"))
        self.assertEqual(p.native_transcript_path("abc-123", "/Users/rick/x y"), Path("/h/.claude/projects/-Users-rick-x-y/abc-123.jsonl"))

    def test_ensure_state_creates_the_run_dir(self):
        import tempfile, stat
        with tempfile.TemporaryDirectory() as tmp:
            p = Paths(checkout=Path(tmp), state=Path(tmp) / "st", home=Path(tmp))
            ensure_state(p)
            self.assertTrue(p.run_dir.is_dir())
            self.assertEqual(stat.S_IMODE(p.run_dir.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
