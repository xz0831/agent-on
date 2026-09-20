from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.harness_codex import read_rollout, write_profile, session_lock  # noqa: E402
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
            self.assertFalse(list(sb.paths.run_dir.glob("*")))                                          # credentials do not outlive the child
            self.assertTrue(Path(doc["transcript"]).is_file())
            self.assertFalse((Path(doc["codex_home"]) / "agent-on.config.toml").exists())
            ls = doc["last_session"]
            self.assertEqual((ls["harness"], ls["harness_version"]), ("codex", "0.0.0"))
            self.assertEqual(ls["this_run"]["turns"], 1)
            self.assertEqual(ls["this_run"]["usage"], {"input_tokens": 1000, "output_tokens": 20, "cache_read_input_tokens": 6000, "cache_creation_input_tokens": 0})
            self.assertEqual(ls["first_request"]["input_tokens_total"], 7000)
            self.assertEqual(len(read_session_runs(sb.paths, ls["id"])), 1)
            self.assertEqual(read_observed(sb.paths)["routes"]["paid/vendor/model-x"]["last_session"]["harness"], "codex")

    def test_codex_doc_carries_a_session_dict_so_render_launch_does_not_crash(self):
        # regression: run_launch_codex used to omit doc["session"], so cli.render_launch (which reads
        # doc["session"]["id"]/["mode"]) raised KeyError -> codex-on always exited 2 with "error: session".
        from agent_on.cli import render_launch
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc, _ = self.launch(sb, "x", ["exec", "Reply OK"], env={"MOCK_PAID_KEY": "sk-from-env"})
            self.assertEqual(doc["exit_code"], 0)
            self.assertEqual(doc["session"], {"id": doc["last_session"]["id"], "mode": "fresh"})
            self.assertTrue(doc["session"]["id"])                                                       # a real session id, not None/empty
            rendered = render_launch(doc)                                                               # must not raise KeyError
            self.assertIn(f"session {doc['session']['id']} (fresh)", rendered)

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

    def test_spawn_failure_still_cleans_up_the_per_launch_key_dir(self):
        # final-fix minor: a launch that fails to spawn (nonexistent binary) must still remove the per-launch
        # CODEX_HOME under run_dir in `finally` — the key must never outlive the child, success or not.
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            (sb.paths.home / ".codex").mkdir(parents=True, exist_ok=True)
            base_env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home)}
            with self.assertRaises(OSError):
                harness.run_launch(sb.paths, "x", ["exec", "hi"], harness="codex", env=base_env,
                                   codex_bin="/nonexistent/codex", cwd=str(sb.paths.checkout), probe_timeout=0.5, announce=False)
            self.assertEqual(list(sb.paths.run_dir.glob("*")), [])

    def test_resume_reuses_durable_home_and_session_without_double_counting(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            first, _ = self.launch(sb, "a", ["exec", "hi"])
            sid = first["session"]["id"]
            second, _ = self.launch(sb, "a", ["exec", "resume", sid, "continue"])
            self.assertEqual(second["session"], {"id": sid, "mode": "resume"})
            self.assertEqual(second["codex_home"], first["codex_home"])
            self.assertEqual(second["last_session"]["this_run"]["turns"], 1)
            self.assertEqual(second["last_session"]["session_total"]["turns"], 2)
            self.assertEqual(len(read_session_runs(sb.paths, sid)), 2)
            self.assertTrue(Path(first["transcript"]).exists())
            self.assertFalse(list(sb.paths.run_dir.glob("*")))

    def test_resume_missing_or_ambiguous_selection_never_spawns_a_fresh_session(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            for args in (["resume"], ["exec", "resume", "--last"], ["resume", "a-name"],
                         ["-s", "workspace-write", "exec", "resume", "11111111-1111-1111-1111-111111111111"]):
                with self.assertRaises(ValueError):
                    self.launch(sb, "a", list(args))
            self.assertFalse((sb.root / "fake-out").exists())

    def test_concurrent_resume_is_rejected_without_touching_active_profile(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            first, _ = self.launch(sb, "a", ["exec", "hi"])
            ch = Path(first["codex_home"])
            sentinel = ch / "active-profile"
            sentinel.write_text("owned by existing child")
            link = ch / "agent-on.config.toml"
            link.symlink_to(sentinel)
            with session_lock(ch):
                with self.assertRaisesRegex(ValueError, "already active"):
                    self.launch(sb, "a", ["resume", first["session"]["id"]])
            self.assertTrue(link.is_symlink())
            self.assertEqual(sentinel.read_text(), "owned by existing child")

    def test_crash_sweep_removes_credentials_but_keeps_transcript(self):
        from agent_on.harness import sweep_run_dirs
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            first, _ = self.launch(sb, "a", ["exec", "hi"])
            run = sb.paths.run_dir / "dead-launch"
            run.mkdir()
            (run / "pid").write_text("99999999")
            (run / "secret").write_text("do not retain")
            self.assertEqual(sweep_run_dirs(sb.paths, min_age_s=0), ["dead-launch"])
            self.assertTrue(Path(first["transcript"]).is_file())


class RolloutTest(unittest.TestCase):
    def test_read_rollout_derives_turn_deltas_from_cumulative_total_and_drops_a_zero_delta_reemit(self):
        # final-fix item 1: a turn is the delta between consecutive `total_token_usage` totals, not a straight
        # sum of `last_token_usage` — the third event below re-emits the second turn's total with no new model
        # call (a zero delta) and must add no turn. final-fix item 2: `sandbox_policy` carries `type`, not
        # `mode`, on real 0.153.4 rollouts; a later turn_context's `mode` (when present) still wins.
        lines = [{"timestamp": "2026-09-09T00:00:00.000Z", "type": "session_meta", "payload": {"id": "sid-1", "cli_version": "0.153.4", "model_provider": "agent-on", "cwd": "/w"}},
                 {"timestamp": "2026-09-09T00:00:01.000Z", "type": "turn_context", "payload": {"model": "m1", "effort": "low", "sandbox_policy": {"type": "read-only"}}},
                 {"timestamp": "2026-09-09T00:00:02.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                     "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 3, "output_tokens": 10, "reasoning_output_tokens": 4},
                     "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 3, "output_tokens": 10, "reasoning_output_tokens": 4}}}},
                 {"timestamp": "2026-09-09T00:00:02.500Z", "type": "turn_context", "payload": {"model": "m1", "sandbox_policy": {"mode": "x", "type": "ignored"}}},
                 {"timestamp": "2026-09-09T00:00:03.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                     "last_token_usage": {"input_tokens": 200, "cached_input_tokens": 150, "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0},
                     "total_token_usage": {"input_tokens": 300, "cached_input_tokens": 190, "cache_write_input_tokens": 3, "output_tokens": 15, "reasoning_output_tokens": 4}}}},
                 {"timestamp": "2026-09-09T00:00:03.500Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                     "last_token_usage": {"input_tokens": 0, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0},
                     "total_token_usage": {"input_tokens": 300, "cached_input_tokens": 190, "cache_write_input_tokens": 3, "output_tokens": 15, "reasoning_output_tokens": 4}}}},
                 {"timestamp": "2026-09-09T00:00:04.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": None}}]
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.root / "rollout-x.jsonl"
            p.write_text("\n".join(json.dumps(l) for l in lines) + "\nnot json\n", encoding="utf-8")
            r = read_rollout(p)
            self.assertEqual((r["session_id"], r["version"], r["model"], r["effort"], r["permission_mode"]), ("sid-1", "0.153.4", "m1", "low", "x"))
            self.assertEqual(len(r["turns"]), 2)                                      # the zero-delta re-emit adds no turn
            self.assertEqual([t["usage"] for t in r["turns"]],
                             [{"input_tokens": 60, "output_tokens": 10, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 3},
                              {"input_tokens": 50, "output_tokens": 5, "cache_read_input_tokens": 150, "cache_creation_input_tokens": 0}])
            summed = {k: sum(t["usage"][k] for t in r["turns"]) for k in r["turns"][0]["usage"]}
            # the invariant: summed per-turn usage equals the final total_token_usage (input_tokens + cache_read
            # = 300, cache_creation = 3, output = 15) — nothing is double-counted by the re-emit.
            self.assertEqual(summed["input_tokens"] + summed["cache_read_input_tokens"], 300)
            self.assertEqual(summed["cache_creation_input_tokens"], 3)
            self.assertEqual(summed["output_tokens"], 15)
            self.assertEqual(r["first_request"]["input_tokens_total"], 100)
            self.assertTrue(all(t["model"] == "m1" for t in r["turns"]))

    def test_read_rollout_falls_back_to_last_token_usage_when_no_event_carries_a_total(self):
        # older Codex rollouts with no info.total_token_usage at all: nothing regresses.
        lines = [{"timestamp": "2026-09-09T00:00:00.000Z", "type": "session_meta", "payload": {"id": "sid-2", "cli_version": "0.140.0"}},
                 {"timestamp": "2026-09-09T00:00:01.000Z", "type": "turn_context", "payload": {"model": "m1"}},
                 {"timestamp": "2026-09-09T00:00:02.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "cache_write_input_tokens": 3, "output_tokens": 10}}}},
                 {"timestamp": "2026-09-09T00:00:03.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 200, "cached_input_tokens": 150, "cache_write_input_tokens": 0, "output_tokens": 5}}}}]
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.root / "rollout-y.jsonl"
            p.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
            r = read_rollout(p)
            self.assertEqual(len(r["turns"]), 2)
            self.assertEqual(r["first_request"]["input_tokens_total"], 100)

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
