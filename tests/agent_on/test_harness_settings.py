"""extract_user_settings (F1): the pure function that pulls --settings out of the user's argv and merges it, so
run_launch can fold it under the launcher's apiKeyHelper instead of letting Claude Code's last---settings-wins
silently displace the credential helper."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402


class ExtractUserSettingsTest(unittest.TestCase):
    def test_no_settings_flag_is_a_no_op(self):
        self.assertEqual(harness.extract_user_settings(["-p", "x"]), (["-p", "x"], None))

    def test_inline_json_is_parsed_and_stripped(self):
        args, settings = harness.extract_user_settings(["-p", "x", "--settings", '{"a": 1}'])
        self.assertEqual(args, ["-p", "x"])
        self.assertEqual(settings, {"a": 1})

    def test_equals_form_and_a_file_path_are_both_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text('{"b": 2}', encoding="utf-8")
            args, settings = harness.extract_user_settings(["-p", "x", "--settings", '{"a": 1, "b": 1}', f"--settings={p}"])
            self.assertEqual(args, ["-p", "x"])
            self.assertEqual(settings, {"a": 1, "b": 2})   # later occurrence wins, shallow merge

    def test_malformed_inline_json_raises(self):
        with self.assertRaises(ValueError):
            harness.extract_user_settings(["--settings", "{"])

    def test_missing_file_raises(self):
        with self.assertRaises(ValueError):
            harness.extract_user_settings(["--settings", "/nonexistent/path/settings.json"])

    def test_non_object_document_raises(self):
        with self.assertRaises(ValueError):
            harness.extract_user_settings(["--settings", "[]"])

    def test_route_model_is_explicit_and_identical_user_value_is_deduplicated(self):
        self.assertEqual(harness.pin_model_args(["-p", "x"], "wire/model"),
                         ["--model", "wire/model", "-p", "x"])
        self.assertEqual(harness.pin_model_args(["--model=wire/model", "-p", "x"], "wire/model"),
                         ["--model", "wire/model", "-p", "x"])

    def test_conflicting_or_incomplete_user_model_is_refused(self):
        with self.assertRaisesRegex(ValueError, "conflicts with route model"):
            harness.pin_model_args(["--model", "other"], "wire/model")
        with self.assertRaisesRegex(ValueError, "requires a value"):
            harness.pin_model_args(["--model"], "wire/model")

    def test_model_like_prompt_data_after_separator_is_not_rewritten(self):
        self.assertEqual(harness.pin_model_args(["-p", "x", "--", "--model", "prompt-data"], "wire/model"),
                         ["--model", "wire/model", "-p", "x", "--", "--model", "prompt-data"])

    def test_settings_routing_conflicts_are_narrow(self):
        self.assertEqual(harness.settings_route_conflicts({"permissions": {"allow": ["Read"]}, "model": "literal"}), [])
        self.assertEqual(harness.settings_route_conflicts({"env": {"ANTHROPIC_BASE_URL": "http://other"},
                                                            "apiKeyHelper": "echo wrong"}),
                         ["env.ANTHROPIC_BASE_URL", "apiKeyHelper"])


if __name__ == "__main__":
    unittest.main()
