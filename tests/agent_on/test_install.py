from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.install import run_install  # noqa: E402
from agent_on.paths import describe_copy  # noqa: E402

BASE = "http://127.0.0.1:1"


class InstallTest(unittest.TestCase):
    def test_install_links_both_shims_creates_the_state_root_and_copy_single_passes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            self.assertFalse(sb.paths.state.exists())
            doc = run_install(sb.paths)
            self.assertTrue(doc["written"], doc)
            for name in ("agent-on", "claude-on"):
                link = sb.paths.home / ".local" / "bin" / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), str((REPO / "bin" / name).resolve()))
                self.assertEqual(doc["links"][name]["state"], "linked")
            self.assertTrue(sb.paths.state.is_dir())
            self.assertTrue(doc["python"]["ok"])
            self.assertEqual([i["result"] for i in doc["invariants"] if i["id"] == "copy.single"], ["pass"])
            self.assertIn("~/.local/bin", describe_copy(sb.paths)["shim"].replace(str(sb.paths.home), "~"))
            again = run_install(sb.paths)
            self.assertEqual({v["state"] for v in again["links"].values()}, {"unchanged"})

    def test_a_stale_symlink_is_replaced_and_a_regular_file_is_refused(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            bd = sb.paths.home / ".local" / "bin"
            bd.mkdir(parents=True)
            (bd / "agent-on").symlink_to("/nonexistent/agent-on")
            (bd / "claude-on").write_text("#!/bin/sh\n", encoding="utf-8")
            doc = run_install(sb.paths)
            self.assertFalse(doc["written"])
            self.assertEqual(doc["links"]["agent-on"]["state"], "replaced")
            self.assertEqual(os.readlink(bd / "agent-on"), str((REPO / "bin" / "agent-on").resolve()))
            self.assertEqual(doc["links"]["claude-on"]["state"], "refused")
            self.assertIn("not a symlink", doc["links"]["claude-on"]["reason"])
            self.assertEqual((bd / "claude-on").read_text(encoding="utf-8"), "#!/bin/sh\n")            # untouched

    def test_dry_run_touches_nothing_and_a_custom_bin_dir_is_honoured(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            bd = sb.root / "elsewhere" / "bin"
            doc = run_install(sb.paths, bin_dir=bd, dry_run=True)
            self.assertEqual({v["state"] for v in doc["links"].values()}, {"dry-run"})
            self.assertFalse(bd.exists())
            self.assertFalse(sb.paths.state.exists())
            doc = run_install(sb.paths, bin_dir=bd)
            self.assertTrue((bd / "claude-on").is_symlink())
            self.assertFalse(doc["on_path"])
            self.assertTrue(any("PATH" in w for w in doc["warnings"]))

    def test_old_python_links_nothing(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=REPO) as sb:
            with mock.patch("agent_on.install.sys.version_info", (3, 10, 0)):
                doc = run_install(sb.paths)
            self.assertFalse(doc["python"]["ok"])
            self.assertFalse(doc["written"])
            self.assertFalse((sb.paths.home / ".local" / "bin").exists())


if __name__ == "__main__":
    unittest.main()
