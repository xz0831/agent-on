from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

OLD = ["config", "scripts/check.zsh", "scripts/install.zsh", "scripts/task-ledger.py", "scripts/verify_tool_call_fidelity.py",
       "bin/claude-litellm", "docs/ARCHITECTURE.md", "docs/MODEL-RUNBOOK.md", "docs/PROVIDERS.md", "docs/MIGRATION.md",
       "tests/test_task_ledger.py", "tests/test_output_clamp.py"]


def tracked() -> list[str]:
    return subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split()


class OldPathGoneTest(unittest.TestCase):
    def test_nothing_of_the_old_path_is_tracked(self):
        files = tracked()
        for p in OLD:
            self.assertFalse(any(f == p or f.startswith(p + "/") for f in files), p)
        self.assertEqual([f for f in files if f.startswith("scripts/")], ["scripts/routes-doc.py"])
        self.assertEqual([f for f in files if f.startswith("tests/") and "/" not in f[len("tests/"):]], [])

    def test_no_litellm_under_the_surviving_trees(self):
        # This test file itself names the deleted path (to check it is gone) and so is excluded from its own scan.
        hits = subprocess.run(["git", "-C", str(REPO), "grep", "-il", "litellm", "--", "agent_on", "bin", "routes.toml", "tests", "scripts", ".github",
                               ":(exclude)tests/agent_on/test_docs_plan_d.py"],
                              capture_output=True, text=True)
        self.assertEqual(hits.stdout.strip(), "", hits.stdout)

    def test_readme_names_the_old_path_only_in_the_upgrade_note(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        head, _, tail = text.partition("## Upgrading from claude-litellm")
        self.assertNotIn("litellm", head.lower())
        self.assertIn("rm -rf ~/.local/share/claude-litellm", tail)


if __name__ == "__main__":
    unittest.main()
