from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.harness_codex import read_rollout, write_profile  # noqa: E402
from agent_on.state import read_observed, read_session_runs  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fakecodex.py")
BASE = "http://127.0.0.1:1"


class CodexLaunchTest(unittest.TestCase):
    def launch(self, sb, name, args, env=None, **kw):
        out = sb.root / "fake-out"
        (sb.paths.home / ".codex").mkdir(parents=True, exist_ok=True)
        (sb.paths.home / ".codex" / "config.toml").write_text('model = "user-default"\n', encoding="utf-8")
        (sb.paths.home / ".codex" / "skills").mkdir(exist_ok=True)
        base_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "FAKE_CODEX_OUT": str(out), **(env or {})}
        doc = harness.run_launch(sb.paths, name, args, harness="codex", env=base_env, codex_bin=FAKE, cwd=str(sb.paths.checkout),
                                 probe_timeout=0.5, announce=False, **kw)
        return doc, out

    def test_keyed_launch_puts_the_key_in_the_profile_and_nowhere_else(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "x", ["exec", "Reply OK"], env={"MOCK_PAID_KEY": "sk-from-env", "OPENAI_API_KEY": "sk-inherited"})
            self.assertEqual(doc["exit_code"], 0)
            env = json.loads((out / "env.json").read_text())
            self.assertNotIn("MOCK_PAID_KEY", env)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("sk-from-env", json.dumps(env))
            self.assertTrue(env["CODEX_HOME"].endswith("/codex-home"))
            profile = json.loads((out / "profile.json").read_text())
            self.assertEqual(profile["model_provider"], "agent-on")
            self.assertEqual(profile["model"], "vendor/model-x")
            p = profile["model_providers"]["agent-on"]
            self.assertEqual((p["wire_api"], p["base_url"]), ("responses", BASE + "/v1"))
            self.assertEqual(p["http_headers"]["Authorization"], "Bearer sk-from-env")
            self.assertEqual(profile["model_context_window"], 100000)
            argv = json.loads((out / "argv.json").read_text())
            self.assertEqual(argv[:2], ["--profile", "agent-on"])
            self.assertEqual(argv[2:], ["exec", "Reply OK"])
            self.assertFalse(list(sb.paths.run_dir.glob("*")))                                          # the home never outlives the child
            ls = doc["last_session"]
            self.assertEqual((ls["harness"], ls["harness_version"]), ("codex", "0.0.0"))
            self.assertEqual(ls["this_run"]["turns"], 1)
            self.assertEqual(ls["this_run"]["usage"], {"input_tokens": 1000, "output_tokens": 20, "cache_read_input_tokens": 6000, "cache_creation_input_tokens": 0})
            self.assertEqual(ls["first_request"]["input_tokens_total"], 7000)
            self.assertEqual(len(read_session_runs(sb.paths, ls["id"])), 1)
            self.assertEqual(read_observed(sb.paths)["routes"]["paid/vendor/model-x"]["last_session"]["harness"], "codex")

    def test_keyless_launch_has_no_header_and_shares_the_user_items(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, out = self.launch(sb, "a", ["exec", "hi"])
            profile = json.loads((out / "profile.json").read_text())
            self.assertNotIn("http_headers", profile["model_providers"]["agent-on"])
            env = json.loads((out / "env.json").read_text())
            home = Path(env["CODEX_HOME"])
            # the fake ran while the home existed; it recorded what the links pointed at
            links = json.loads((out / "home_links.json").read_text())
            self.assertEqual(links["config.toml"], str(sb.paths.home / ".codex" / "config.toml"))
            self.assertEqual(links["skills"], str(sb.paths.home / ".codex" / "skills"))
            self.assertNotIn("plugins", links)                                                          # absent in the user's home: no dangling link

    def test_dry_run_and_user_profile_are_reported(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, _ = self.launch(sb, "a", ["--profile", "mine", "exec", "hi"], dry_run=True)
            self.assertTrue(doc["dry_run"])
            self.assertEqual(doc["argv"][1:3], ["--profile", "agent-on"])
            self.assertNotIn("mine", doc["argv"])
            self.assertTrue(any("user --profile mine replaced" in w for w in doc["warnings"]))
            self.assertIn("CODEX_HOME", doc["env_keys"])
            self.assertFalse(sb.paths.run_dir.exists() and list(sb.paths.run_dir.glob("*")))

    def test_task_handoff_appends_the_prompt_last_and_marks_launched(self):
        from agent_on import tasks
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "Ship it", str(wt))
            tasks.handoff(sb.paths, t["id"], to_route="a", objective="Do the thing")
            doc, out = self.launch(sb, "a", ["exec"], task=t["id"])
            argv = json.loads((out / "argv.json").read_text())
            self.assertTrue(argv[-1].startswith("You are worker session 1 for agent-on task"))
            self.assertEqual((out / "cwd.txt").read_text().strip(), str(wt.resolve()))
            self.assertEqual(tasks.load(sb.paths, t["id"])["handoffs"][0]["status"], "launched")


class RolloutTest(unittest.TestCase):
    def test_read_rollout_maps_usage_and_reads_meta(self):
        lines = [{"timestamp": "2026-09-09T00:00:00.000Z", "type": "session_meta", "payload": {"id": "sid-1", "cli_version": "0.153.4", "model_provider": "agent-on", "cwd": "/w"}},
                 {"timestamp": "2026-09-09T00:00:01.000Z", "type": "turn_context", "payload": {"model": "m1", "effort": "low", "sandbox_policy": {"mode": "read-only"}}},
                 {"timestamp": "2026-09-09T00:00:02.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 3, "output_tokens": 10, "reasoning_output_tokens": 4}, "total_token_usage": {}}}},
                 {"timestamp": "2026-09-09T00:00:03.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 200, "cached_input_tokens": 150, "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0}, "total_token_usage": {}}}},
                 {"timestamp": "2026-09-09T00:00:04.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": None}}]
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.root / "rollout-x.jsonl"
            p.write_text("\n".join(json.dumps(l) for l in lines) + "\nnot json\n", encoding="utf-8")
            r = read_rollout(p)
            self.assertEqual((r["session_id"], r["version"], r["model"], r["effort"], r["permission_mode"]), ("sid-1", "0.153.4", "m1", "low", "read-only"))
            self.assertEqual([t["usage"] for t in r["turns"]],
                             [{"input_tokens": 60, "output_tokens": 10, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 3},
                              {"input_tokens": 50, "output_tokens": 5, "cache_read_input_tokens": 150, "cache_creation_input_tokens": 0}])
            self.assertEqual(r["first_request"]["input_tokens_total"], 100)
            self.assertTrue(all(t["model"] == "m1" for t in r["turns"]))

    def test_profile_toml_escapes_and_omits_what_is_unknown(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            home = sb.root / "ch"; home.mkdir()
            p = write_profile(home, model='we"ird', base_url="http://h:1/v1", key='k\\"y', context=None)
            import tomllib
            d = tomllib.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(d["model"], 'we"ird')
            self.assertEqual(d["model_providers"]["agent-on"]["http_headers"]["Authorization"], 'Bearer k\\"y')
            self.assertEqual(d["model_providers"]["agent-on"]["base_url"], "http://h:1/v1")
            self.assertNotIn("model_context_window", d)
            self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
