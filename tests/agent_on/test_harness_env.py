from __future__ import annotations

import json
import os
import shlex
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import harness  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402
from agent_on.state import read_observed, read_session_runs  # noqa: E402

BASE = "http://127.0.0.1:1"


def table(sb):
    return load_routes(sb.paths)


class ChildEnvTest(unittest.TestCase):
    def test_keyed_source_scrubs_every_secret_and_sets_no_key_variable(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            t = table(sb)
            parent = {"PATH": "/usr/bin", "HOME": "/h", "MOCK_PAID_KEY": "sk-paid", "ANTHROPIC_API_KEY": "sk-ant", "ANTHROPIC_MODEL": "x",
                      "OPENROUTER_API_KEY": "sk-or", "HTTPS_PROXY": "keep-me", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
                      "CLAUDE_CODE_SESSION_ID": "parent-session", "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_MESSAGING_TOKEN": "t", "CLAUDE_EFFORT": "high", "CLAUDE_PID": "1"}
            env = harness.child_env(parent, t, t.routes["paid/vendor/model-x"], context=100000, config_dir=Path("/cfg"))
            for k in ("MOCK_PAID_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL", "OPENROUTER_API_KEY",
                      "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_EFFORT", "CLAUDE_PID"):
                self.assertNotIn(k, env, k)
            self.assertEqual(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "4096")                # the operator's output cap passes (D12)
            self.assertNotIn("sk-paid", json.dumps(env))
            self.assertEqual(env["PATH"], "/usr/bin")
            self.assertEqual(env["HTTPS_PROXY"], "keep-me")                        # not a routing variable: kept
            self.assertEqual(env["ANTHROPIC_BASE_URL"], BASE)
            for tier in harness.TIERS:
                self.assertEqual(env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"], "vendor/model-x")
            self.assertEqual(env["CLAUDE_CODE_SUBAGENT_MODEL"], "vendor/model-x")
            self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "100000")
            self.assertEqual(env["CLAUDE_CODE_ATTRIBUTION_HEADER"], "0")
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/cfg")
            self.assertNotIn(harness.DISCOVERY_ENV, env)

    def test_keyless_source_gets_the_placeholder_token_and_discover_is_opt_in(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            t = table(sb)
            env = harness.child_env({}, t, t.routes["mock/alpha"], context=None, config_dir=Path("/cfg"), discover=True)
            self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], harness.PLACEHOLDER_TOKEN)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("CLAUDE_CODE_MAX_CONTEXT_TOKENS", env)
            self.assertEqual(env[harness.DISCOVERY_ENV], "1")

    def test_tier_overrides_must_stay_on_the_same_source(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            t = table(sb)
            env = harness.child_env({}, t, t.routes["mock/alpha"], context=None, config_dir=Path("/c"), haiku=t.routes["mock/gone"])
            self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gone")
            self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "alpha")
            self.assertEqual(env["CLAUDE_CODE_SUBAGENT_MODEL"], "alpha")
            with self.assertRaises(ValueError):
                harness.child_env({}, t, t.routes["mock/alpha"], context=None, config_dir=Path("/c"), sonnet=t.routes["paid/vendor/model-x"])


class ConfigDirTest(unittest.TestCase):
    def test_shared_items_are_symlinked_and_the_project_is_trusted(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            native = sb.paths.home / ".claude"
            native.mkdir()
            (native / "settings.json").write_text("{}")
            cfg = harness.prepare_config_dir(sb.paths, "/work/dir")
            self.assertEqual(cfg, sb.paths.claude_config_dir)
            self.assertEqual(stat.S_IMODE(sb.paths.state.stat().st_mode), 0o700)
            for item in harness.SHARED_ITEMS:
                self.assertTrue((cfg / item).is_symlink(), item)
                self.assertEqual(os.readlink(cfg / item), str(native / item))
            doc = json.loads((cfg / ".claude.json").read_text())
            self.assertTrue(doc["hasCompletedOnboarding"])
            self.assertTrue(doc["projects"]["/work/dir"]["hasTrustDialogAccepted"])
            # a second call with another cwd keeps the first project and existing keys
            doc["someKey"] = 1
            (cfg / ".claude.json").write_text(json.dumps(doc))
            harness.prepare_config_dir(sb.paths, "/other")
            doc = json.loads((cfg / ".claude.json").read_text())
            self.assertEqual(doc["someKey"], 1)
            self.assertEqual(set(doc["projects"]), {"/work/dir", "/other"})

    def test_a_real_file_in_the_way_is_moved_aside_never_deleted(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            cfg = sb.paths.claude_config_dir
            cfg.mkdir(parents=True)
            (cfg / "settings.json").write_text('{"was": "isolated"}')
            harness.prepare_config_dir(sb.paths, "/w")
            self.assertTrue((cfg / "settings.json").is_symlink())
            self.assertEqual((cfg / "settings.json.isolated.bak").read_text(), '{"was": "isolated"}')


class RunDirTest(unittest.TestCase):
    def test_write_run_dir_holds_the_key_privately_and_sweep_removes_dead_launches(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            d, helper = harness.write_run_dir(sb.paths, "01LAUNCHA", key="sk-secret", launch={"route": "paid/vendor/model-x"})
            self.assertEqual(d, sb.paths.run_dir / "01LAUNCHA")
            self.assertEqual(oct((d / "key").stat().st_mode & 0o777), "0o600")
            self.assertEqual((d / "key").read_text(), "sk-secret")
            self.assertEqual(json.loads(helper.read_text())["apiKeyHelper"], f"cat {shlex.quote(str(d / 'key'))}")
            self.assertEqual(int((d / "pid").read_text()), os.getpid())
            self.assertEqual(json.loads((d / "launch.json").read_text())["route"], "paid/vendor/model-x")
            d2, helper2 = harness.write_run_dir(sb.paths, "01LAUNCHB", key=None, launch={})
            self.assertIsNone(helper2)
            self.assertFalse((d2 / "key").exists())
            dead = sb.paths.run_dir / "01DEAD"
            dead.mkdir()
            (dead / "pid").write_text("999999")
            (dead / "key").write_text("stale")
            old = time.time() - 60
            os.utime(dead, (old, old))
            removed = harness.sweep_run_dirs(sb.paths)
            self.assertEqual(removed, ["01DEAD"])
            self.assertFalse(dead.exists())
            self.assertTrue(d.exists() and d2.exists())                             # live launcher pid → kept


class SessionArgsTest(unittest.TestCase):
    def test_modes(self):
        args, sid, mode = harness.session_args(["-p", "hi"])
        self.assertEqual((args[0], mode), ("--session-id", "fresh"))
        self.assertEqual(args[1], sid)
        self.assertEqual(args[2:], ["-p", "hi"])
        self.assertEqual(harness.session_args(["--session-id", "abc"]), (["--session-id", "abc"], "abc", "user-session-id"))
        self.assertEqual(harness.session_args(["--session-id=abc"]), (["--session-id=abc"], "abc", "user-session-id"))
        self.assertEqual(harness.session_args(["--resume", "r1", "-p", "x"]), (["--resume", "r1", "-p", "x"], "r1", "resume"))
        self.assertEqual(harness.session_args(["-r"]), (["-r"], None, "resume"))
        self.assertEqual(harness.session_args(["--continue"]), (["--continue"], None, "continue"))
        self.assertEqual(harness.session_args(["--no-session-persistence", "-p", "x"]), (["--no-session-persistence", "-p", "x"], None, "no-persistence"))


class CostLineTest(unittest.TestCase):
    def test_renders_measured_values_and_never_invents(self):
        self.assertEqual(harness.cost_line("mock/alpha", None), "mock/alpha  ctx ? · ? tok/s · $? · cache ? · concurrency ? · thinking ?")
        obs = {"cost_model": {"context": 131072, "harness_baseline_tokens": {"value": 48312}, "tok_s": 63.2,
                              "usd_per_mtok": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, "caching": True, "concurrency": 1,
                              "thinking": {"observed": True, "tokens_on_probe": 2600}}}
        self.assertEqual(harness.cost_line("mock/x", obs), "mock/x  ctx 131072 (48312 baseline = 37%) · 63 tok/s · $0 · cache ✓ · serial · thinking on (~2.6K tok/probe)")
        obs = {"cost_model": {"context": 200000, "harness_baseline_tokens": None, "tok_s": None, "usd_per_mtok": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": None},
                              "caching": False, "concurrency": 4, "thinking": {"observed": False, "tokens_on_probe": None}}}
        self.assertEqual(harness.cost_line("paid/x", obs), "paid/x  ctx 200000 · ? tok/s · $1.0/5.0 per Mtok · cache ✗ · 4× concurrent · thinking off")
        obs = {"cost_model": {"usd_per_mtok": {"input": 1.0, "output": None, "cache_read": None, "cache_write": None}}}
        self.assertEqual(harness.cost_line("mock/half", obs), "mock/half  ctx ? · ? tok/s · $? · cache ? · concurrency ? · thinking ?")
        obs = {"cost_model": {"usd_per_mtok": {"input": 0, "output": None, "cache_read": None, "cache_write": None}}}
        self.assertEqual(harness.cost_line("mock/half2", obs), "mock/half2  ctx ? · ? tok/s · $? · cache ? · concurrency ? · thinking ?")


class TranscriptTest(unittest.TestCase):
    def write(self, path, lines):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(l) + "\n" for l in lines))

    def test_read_dedups_by_message_id_and_takes_verified_fields_only(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.paths.transcript_path("s1", "/w")
            u1 = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5000, "service_tier": "x"}
            u2 = {"input_tokens": 20, "output_tokens": 30, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 0}
            self.write(p, [
                {"type": "user", "timestamp": "2026-09-08T00:00:00Z", "sessionId": "s1", "version": "2.1.263", "effort": "high", "permissionMode": None, "message": {"role": "user"}},
                {"type": "assistant", "timestamp": "2026-09-08T00:00:01Z", "sessionId": "s1", "version": "2.1.263", "message": {"id": "m1", "model": "alpha", "usage": u1, "total_cost_usd": 9}},
                {"type": "assistant", "timestamp": "2026-09-08T00:00:01Z", "message": {"id": "m1", "model": "alpha", "usage": u1}},      # same API response, second block
                {"type": "assistant", "timestamp": "2026-09-08T00:00:05Z", "message": {"id": "m2", "model": "alpha", "usage": u2}},
                "not json",
            ])
            t = harness.read_transcript(p)
            self.assertEqual(len(t["turns"]), 2)
            self.assertEqual(t["turns"][0]["usage"], {k: u1[k] for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")})
            self.assertEqual(t["first_request"]["input_tokens_total"], 5100)
            self.assertEqual((t["version"], t["effort"], t["permission_mode"], t["session_id"]), ("2.1.263", "high", None, "s1"))
            self.assertNotIn("total_cost_usd", json.dumps(t))

    def test_record_session_fresh_then_resumed_on_a_free_route_keeps_the_paid_cost(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.paths.transcript_path("s2", "/w")
            paid = {"input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": None}
            usage = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
            self.write(p, [{"type": "assistant", "timestamp": "2026-09-08T01:00:01Z", "sessionId": "s2", "version": "2.1.263",
                            "message": {"id": "a", "model": "vendor/model-x", "usage": usage}}])
            launch1 = {"launch_id": "L1", "route": "paid/vendor/model-x", "source": "paid", "wire_model": "vendor/model-x", "started": "2026-09-08T01:00:00Z",
                       "session_id": "s2", "price": paid, "priced_models": {"vendor/model-x": paid}}
            rec = harness.record_session(sb.paths, launch1, ended="2026-09-08T01:00:10Z", transcript=p, mode="fresh")
            self.assertEqual(rec["this_run"]["cost_usd"], 1.0)
            self.assertEqual(rec["session_total"]["cost_usd"], 1.0)
            self.assertEqual(rec["scope_note"], "fresh session; this_run == session_total")
            self.assertEqual(rec["duration_ms"], 10000)
            self.assertEqual(read_observed(sb.paths)["routes"]["paid/vendor/model-x"]["last_session"]["id"], "s2")
            # resumed later on the free mock route: the paid turn keeps its price
            with open(p, "a") as f:
                f.write(json.dumps({"type": "assistant", "timestamp": "2026-09-08T02:00:01Z", "message": {"id": "b", "model": "alpha", "usage": usage}}) + "\n")
            launch2 = {"launch_id": "L2", "route": "mock/alpha", "source": "mock", "wire_model": "alpha", "started": "2026-09-08T02:00:00Z",
                       "session_id": "s2", "price": harness.FREE, "priced_models": {"alpha": harness.FREE}}
            rec = harness.record_session(sb.paths, launch2, ended="2026-09-08T02:00:10Z", transcript=p, mode="resume")
            self.assertEqual(rec["this_run"]["cost_usd"], 0.0)
            self.assertEqual(rec["this_run"]["turns"], 1)
            self.assertEqual(rec["session_total"]["turns"], 2)
            self.assertEqual(rec["session_total"]["cost_usd"], 1.0)                 # rev-6 P2: paid + 0, never 0
            self.assertIn("2 run(s)", rec["scope_note"])
            self.assertEqual(len(read_session_runs(sb.paths, "s2")), 2)

    def test_a_transcript_with_no_assistant_turn_records_null_first_request(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            p = sb.paths.transcript_path("s3", "/w")
            self.write(p, [{"type": "user", "timestamp": "2026-09-08T03:00:00Z", "sessionId": "s3", "version": "2.1.263"}])
            launch = {"launch_id": "L3", "route": "mock/alpha", "source": "mock", "wire_model": "alpha", "started": "2026-09-08T03:00:00Z",
                      "session_id": "s3", "price": harness.FREE, "priced_models": {"alpha": harness.FREE}}
            rec = harness.record_session(sb.paths, launch, ended="2026-09-08T03:00:01Z", transcript=p, mode="fresh")
            self.assertIsNone(rec["first_request"])
            self.assertEqual(rec["this_run"]["turns"], 0)
            self.assertEqual(rec["session_total"]["cost_usd"], 0.0)
            self.assertIsNone(read_observed(sb.paths)["routes"]["mock/alpha"]["last_session"]["first_request"])

    def test_skipped_records(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            launch = {"launch_id": "L", "route": "mock/alpha", "source": "mock", "wire_model": "alpha", "started": "2026-09-08T01:00:00Z", "session_id": None, "price": harness.FREE, "priced_models": {}}
            rec = harness.record_session(sb.paths, launch, ended="2026-09-08T01:00:01Z", transcript=None, mode="no-persistence")
            self.assertEqual(rec, {"skipped": "no-session-persistence"})
            rec = harness.record_session(sb.paths, launch, ended="2026-09-08T01:00:01Z", transcript=sb.paths.transcript_path("zz", "/w"), mode="fresh")
            self.assertIn("no transcript", rec["skipped"])
            self.assertEqual(read_observed(sb.paths)["routes"]["mock/alpha"]["last_session"]["skipped"], rec["skipped"])


if __name__ == "__main__":
    unittest.main()
