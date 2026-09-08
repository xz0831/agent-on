from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.paths import Paths  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.state import (  # noqa: E402
    append_session_run, atomic_write, checkout_locked, read_env_file, read_observed, read_session_runs,
    resolve_secret, sweep_tmp, update_observed, write_discovered,
)

ROUTES = 'version = 1\n[sources.mock]\nbase_url = "http://127.0.0.1:1"\n'

INCREMENT = """
import sys; sys.path.insert(0, {repo!r})
from pathlib import Path
from agent_on.paths import Paths
from agent_on.state import update_observed
p = Paths(checkout=Path({co!r}), state=Path({st!r}), home=Path({co!r}))
def bump(doc):
    doc["spend"].setdefault("counter", {{"n": 0}})["n"] += 1
for _ in range(50):
    update_observed(p, bump)
"""


class ObservedTest(unittest.TestCase):
    def test_missing_file_reads_as_the_empty_document(self):
        with Sandbox(ROUTES) as sb:
            self.assertEqual(read_observed(sb.paths)["routes"], {})

    def test_update_is_read_modify_write_and_validated(self):
        with Sandbox(ROUTES) as sb:
            update_observed(sb.paths, lambda d: d["spend"].__setitem__("x", {"n": 1}))
            update_observed(sb.paths, lambda d: d["spend"]["x"].__setitem__("n", d["spend"]["x"]["n"] + 1))
            self.assertEqual(read_observed(sb.paths)["spend"]["x"]["n"], 2)
            with self.assertRaises(SchemaError):
                update_observed(sb.paths, lambda d: d.__setitem__("routes", {"r": {"served": True}}))
            self.assertEqual(read_observed(sb.paths)["spend"]["x"]["n"], 2)   # the rejected write left the file alone
            self.assertEqual(list(sb.paths.state.glob("observed.json.tmp.*")), [])

    def test_two_processes_updating_concurrently_lose_nothing(self):
        with Sandbox(ROUTES) as sb:
            script = INCREMENT.format(repo=str(REPO), co=str(sb.paths.checkout), st=str(sb.paths.state))
            procs = [subprocess.Popen([sys.executable, "-c", script]) for _ in range(2)]
            self.assertEqual([p.wait() for p in procs], [0, 0])
            self.assertEqual(read_observed(sb.paths)["spend"]["counter"]["n"], 100)

    def test_stale_tmp_files_are_swept_and_ignored(self):
        with Sandbox(ROUTES) as sb:
            update_observed(sb.paths, lambda d: None)
            stale = sb.paths.state / "observed.json.tmp.99999"
            stale.write_text("{garbage", encoding="utf-8")
            self.assertEqual(read_observed(sb.paths)["version"], 1)
            update_observed(sb.paths, lambda d: None)
            self.assertFalse(stale.exists())
            self.assertEqual(sweep_tmp(sb.paths.state, "observed.json"), 0)

    def test_write_discovered_is_atomic_under_the_same_lock(self):
        with Sandbox(ROUTES) as sb:
            write_discovered(sb.paths, "version = 1\n")
            self.assertEqual(sb.paths.discovered_toml.read_text(), "version = 1\n")
            self.assertEqual(list(sb.paths.state.glob("routes.discovered.toml.tmp.*")), [])


class CheckoutLockTest(unittest.TestCase):
    def test_lock_file_lives_in_the_checkout_and_is_shared_across_state_roots(self):
        with Sandbox(ROUTES) as sb:
            other = Paths(checkout=sb.paths.checkout, state=sb.root / "other-state", home=sb.paths.home)
            with checkout_locked(sb.paths):
                self.assertTrue(sb.paths.routes_lock.exists())
                probe = subprocess.run([sys.executable, "-c", f"""
import fcntl, os, sys
fd = os.open({str(other.routes_lock)!r}, os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print("acquired")
except BlockingIOError:
    print("blocked")
"""], capture_output=True, text=True)
            self.assertEqual(probe.stdout.strip(), "blocked", "a run with another AGENT_ON_STATE must contend for the same lock")

    def test_atomic_write_replaces_in_place(self):
        with Sandbox(ROUTES) as sb:
            atomic_write(sb.paths.routes_toml, "version = 1\n")
            self.assertEqual(sb.paths.routes_toml.read_text(), "version = 1\n")
            self.assertEqual(list(sb.paths.checkout.glob("routes.toml.tmp.*")), [])


class SecretsTest(unittest.TestCase):
    def test_env_wins_over_the_env_file_and_the_file_must_be_private(self):
        with Sandbox(ROUTES) as sb:
            self.assertIsNone(resolve_secret(sb.paths, "K", env={}))
            sb.paths.state.mkdir()
            sb.paths.env_file.write_text("# comment\nK=from-file\nOTHER = spaced \n", encoding="utf-8")
            os.chmod(sb.paths.env_file, 0o600)
            self.assertEqual(read_env_file(sb.paths), {"K": "from-file", "OTHER": "spaced"})
            self.assertEqual(resolve_secret(sb.paths, "K", env={}), "from-file")
            self.assertEqual(resolve_secret(sb.paths, "K", env={"K": "from-env"}), "from-env")
            os.chmod(sb.paths.env_file, 0o644)
            with self.assertRaises(PermissionError):
                read_env_file(sb.paths)


class SessionLedgerTest(unittest.TestCase):
    def test_append_and_read_back_one_line_per_run(self):
        with Sandbox(ROUTES) as sb:
            p = append_session_run(sb.paths, "sess-1", {"launch_id": "L1", "cost_usd": 1.5})
            append_session_run(sb.paths, "sess-1", {"launch_id": "L2", "cost_usd": "unknown"})
            self.assertEqual(p, sb.paths.sessions_dir / "sess-1.jsonl")
            self.assertEqual([r["launch_id"] for r in read_session_runs(sb.paths, "sess-1")], ["L1", "L2"])
            self.assertEqual(read_session_runs(sb.paths, "nope"), [])
            self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
            self.assertEqual(len(p.read_text().splitlines()), 2)
            json.loads(p.read_text().splitlines()[1])


if __name__ == "__main__":
    unittest.main()
