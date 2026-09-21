from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402


class DocsTest(unittest.TestCase):
    def test_readme_and_skill_name_codex_on_and_the_wire_flag(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for needle in ("./bin/codex-on 'omlx@rick/Qwen3.8-27B-Uncensored-8bit'", "--wire responses", "## Harnesses", "CODEX_HOME"):
            self.assertIn(needle, readme)
        skill = (REPO / ".claude" / "skills" / "agent-on" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("codex-on", skill)
        self.assertIn("--wire responses", skill)

    def test_spec_says_the_harness_is_implied_by_the_wire(self):
        spec = (REPO / "docs" / "superpowers" / "specs" / "2026-09-07-agent-on-design.md").read_text(encoding="utf-8")
        self.assertIn("`--baseline` measures the harness implied by the wire", spec)


if __name__ == "__main__":
    unittest.main()
