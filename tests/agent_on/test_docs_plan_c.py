from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402


class DocsTest(unittest.TestCase):
    def test_skill_exists_names_the_verbs_and_the_files_and_no_literal_values(self):
        p = REPO / ".claude" / "skills" / "agent-on" / "SKILL.md"
        self.assertTrue(p.exists())
        text = p.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: agent-on\n"))
        for needle in ("agent-on status --json", "agent-on learn", "knowledge/observations.jsonl", "knowledge/traps.jsonl", "knowledge/decisions.jsonl",
                       "learn task", "claude-on", "--task", "Q1", "Q10"):
            self.assertIn(needle, text)
        self.assertNotIn("131072", text)                                            # values live in routes.toml / observed.json, never in the skill (D5)

    def test_readme_has_the_plan_c_section_and_architecture_lost_the_orca_paragraph(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("### Knowledge (Plan C)", readme)
        self.assertIn("agent-on learn", readme)
        arch = (REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertNotIn("consumed by Orca", arch)

    def test_spec_learn_row_names_the_real_flag(self):
        spec = (REPO / "docs" / "superpowers" / "specs" / "2026-09-07-agent-on-design.md").read_text(encoding="utf-8")
        self.assertIn("`agent-on learn <kind> --json-record", spec)


if __name__ == "__main__":
    unittest.main()
