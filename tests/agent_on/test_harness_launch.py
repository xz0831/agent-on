from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.state import read_observed, read_session_runs  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fakeclaude.py")
BASE = "http://127.0.0.1:1"      # every source unreachable: route.served skips, the launch proceeds (D6)


class LaunchTest(unittest.TestCase):
    def launch(self, sb, name, args, env=None, **kw):
        out = sb.root / "fake-out"
        base_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "FAKE_CLAUDE_OUT": str(out), **(env or {})}
        doc = harness.run_launch(sb.paths, name, args, env=base_env, claude_bin=FAKE, cwd=str(sb.paths.checkout), probe_timeout=0.5, announce=False, **kw)
        return doc, out

    def test_keyed_launch_hands_the_key_to_the_helper_and_never_to_the_environment(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "x", ["-p", "hi"], env={"MOCK_PAID_KEY": "sk-from-env", "ANTHROPIC_API_KEY": "sk-inherited"})
            self.assertEqual(doc["exit_code"], 0)
            env = json.loads((out / "env.json").read_text())
            self.assertNotIn("MOCK_PAID_KEY", env)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
            self.assertNotIn("sk-from-env", json.dumps(env))
            self.assertEqual((out / "helper_key.txt").read_text(), "sk-from-env")      # the helper got it
            argv = json.loads((out / "argv.json").read_text())
            self.assertEqual(argv[0], "--settings")
            self.assertTrue(argv[1].endswith("/settings.json"))
            self.assertEqual(argv[2], "--session-id")
            self.assertEqual(argv[3], doc["session"]["id"])
            self.assertEqual(argv[4:], ["-p", "hi"])
            self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "vendor/model-x")
            self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "100000")               # declared limit: nothing measured yet
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(sb.paths.claude_config_dir))
            self.assertEqual(list(sb.paths.run_dir.iterdir()), [])                      # run dir removed after exit
            rec = doc["last_session"]
            self.assertEqual(rec["id"], doc["session"]["id"])
            self.assertEqual(rec["this_run"]["turns"], 2)                                # 4 lines, 2 message ids
            # the first message carries cache_creation tokens and the paid fixture publishes no cache-write price:
            # an absent price is not 0 (§11), so the run is "unknown" and says why
            self.assertEqual(rec["this_run"]["cost_usd"], "unknown")
            self.assertTrue(any("cache_write" in r for r in rec["this_run"]["unknown_reasons"]))
            self.assertEqual(rec["session_total"]["cost_usd"], "unknown")
            self.assertEqual(rec["first_request"]["input_tokens_total"], 21000)
            self.assertEqual(rec["claude_code"], "0.0.0-fake")
            self.assertEqual(rec["effort"], "high")
            self.assertNotIn("total_cost_usd", json.dumps(read_observed(sb.paths)))
            self.assertEqual(len(read_session_runs(sb.paths, rec["id"])), 1)
            self.assertEqual([i["id"] for i in doc["invariants"]], ["route.served", "credential.not_in_child_env", "harness.env.clean"])   # §9: the three, first (registry order)
            self.assertEqual([i["result"] for i in doc["invariants"]], ["skip", "pass", "skip"])                                       # no shared settings in the sandbox home; credential.not_in_child_env is real as of Task 6
            self.assertTrue(doc["cost_line"].startswith("paid/vendor/model-x  ctx ?"))

    def test_key_from_the_env_file_when_the_environment_has_none(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir(parents=True, exist_ok=True)
            sb.paths.env_file.write_text("MOCK_PAID_KEY=sk-from-file\n")
            os.chmod(sb.paths.env_file, 0o600)
            doc, out = self.launch(sb, "paid/vendor/model-x", ["-p", "hi"])
            self.assertEqual((out / "helper_key.txt").read_text(), "sk-from-file")
            self.assertFalse(any("MOCK_PAID_KEY" in w for w in doc["warnings"]))          # the D6 "unreachable" warning may be present

    def test_keyless_launch_uses_the_placeholder_and_no_settings_file(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["-p", "hi"])
            env = json.loads((out / "env.json").read_text())
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "agent-on")
            self.assertNotIn("--settings", json.loads((out / "argv.json").read_text()))
            self.assertFalse((out / "helper_key.txt").exists())
            self.assertEqual(doc["last_session"]["this_run"]["cost_usd"], 0.0)

    def test_session_modes_exit_code_and_dry_run(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["--no-session-persistence", "-p", "hi"])
            self.assertEqual(doc["last_session"], {"skipped": "no-session-persistence"})
            doc, out = self.launch(sb, "a", ["--session-id", "11111111-1111-1111-1111-111111111111"])
            self.assertEqual(doc["session"], {"id": "11111111-1111-1111-1111-111111111111", "mode": "user-session-id"})
            self.assertEqual(doc["last_session"]["this_run"]["turns"], 2)
            time.sleep(1.1)   # run windows are second-precision (floor start, ceil end): a relaunch of the same session within
            #                   the same second would overlap the previous window, and the fold would honestly say "unknown"
            doc, out = self.launch(sb, "a", ["--resume", "11111111-1111-1111-1111-111111111111"])
            self.assertEqual(doc["session"]["mode"], "resume")
            self.assertEqual(doc["last_session"]["this_run"]["turns"], 2)
            self.assertEqual(doc["last_session"]["session_total"]["turns"], 4)
            self.assertEqual(doc["last_session"]["session_total"]["cost_usd"], 0.0)
            self.assertIn("2 run(s)", doc["last_session"]["scope_note"])
            time.sleep(1.1)
            doc, out = self.launch(sb, "a", ["--continue"])
            self.assertEqual(doc["session"]["mode"], "continue")
            self.assertEqual(doc["last_session"]["session_total"]["turns"], 6)          # the newest transcript was continued
            doc, out = self.launch(sb, "a", ["-p", "x"], env={"FAKE_CLAUDE_EXIT": "3"})
            self.assertEqual(doc["exit_code"], 3)
            (out / "env.json").unlink()                                                  # left by the launches above
            doc, out = self.launch(sb, "a", ["-p", "x"], dry_run=True)
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["argv"][0], FAKE)
            self.assertIn("--session-id", doc["argv"])
            self.assertFalse((out / "env.json").exists())                                # nothing was spawned
            self.assertIn("ANTHROPIC_BASE_URL", doc["env_keys"])

    def test_a_routing_key_in_the_shared_settings_is_warned_about_not_gated(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            (sb.paths.home / ".claude").mkdir()
            (sb.paths.home / ".claude" / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_API_KEY": "sk-shared"}}))
            doc, out = self.launch(sb, "a", ["-p", "x"])
            self.assertEqual(doc["exit_code"], 0)                                          # D6: informed, never gated
            self.assertEqual({i["id"]: i["result"] for i in doc["invariants"]}["harness.env.clean"], "fail")
            self.assertTrue(any("harness.env.clean" in w for w in doc["warnings"]))

    def test_tier_override_and_a_missing_key_are_reported(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["-p", "x"], haiku="mock/gone")
            self.assertEqual(json.loads((out / "env.json").read_text())["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gone")
            with self.assertRaises(ValueError):
                self.launch(sb, "a", ["-p", "x"], sonnet="x")
            doc, out = self.launch(sb, "x", ["-p", "x"])                                   # keyed source, no key anywhere
            self.assertTrue(any("MOCK_PAID_KEY" in w for w in doc["warnings"]))
            self.assertEqual(doc["exit_code"], 0)                                          # D6: informed, not gated
            self.assertFalse((out / "helper_key.txt").exists())


if __name__ == "__main__":
    unittest.main()
