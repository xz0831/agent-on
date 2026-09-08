from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import cli, knowledge, tasks  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402

BASE = "http://127.0.0.1:1"


class LedgerTest(unittest.TestCase):
    def test_create_handoff_launched_complete_lifecycle_is_a_fold_over_events(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "Gateway review", "Review the migration", str(wt))
            self.assertRegex(t["id"], tasks.TASK_ID.pattern)
            self.assertEqual(t["status"], "active")
            h = tasks.handoff(sb.paths, t["id"], to_route="a", objective="Run the focused tests", from_route=None, summary="Migration done", commit="abc", tests="31 ok")
            self.assertEqual((h["index"], h["to_route"], h["status"]), (1, "mock/alpha", "pending"))     # alias resolved to the route name
            self.assertEqual(tasks.launched(sb.paths, t["id"], launch_id="01LAUNCH", route="mock/alpha")["status"], "launched")
            done = tasks.complete(sb.paths, t["id"], summary="Reviewed", commit="def", tests="32 ok", close=True)
            self.assertEqual(done["status"], "completed")
            self.assertEqual(done["closed_summary"], "Reviewed")
            self.assertEqual(done["handoffs"][0]["result_commit"], "def")
            events = knowledge.read(sb.paths, "tasks")
            self.assertEqual([e["event"] for e in events], ["created", "handoff", "launched", "completed"])
            self.assertTrue(all(e["id"].startswith("tasks-") for e in events))
            with self.assertRaises(ValueError):
                tasks.handoff(sb.paths, t["id"], to_route="a", objective="again")                       # closed task
            with self.assertRaises(ValueError):
                tasks.complete(sb.paths, t["id"], summary="twice")                                       # handoff already completed

    def test_handoff_route_must_exist_and_worktree_must_be_a_directory_and_text_is_bounded(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            with self.assertRaises(ValueError):
                tasks.create(sb.paths, "x", "goal", str(sb.root / "missing"))
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "goal", str(wt))
            with self.assertRaises(KeyError):
                tasks.handoff(sb.paths, t["id"], to_route="nope/nothing", objective="o")
            with self.assertRaises(ValueError):
                tasks.create(sb.paths, "x", "g" * (tasks.MAX_TEXT + 1), str(wt))
            self.assertEqual(knowledge.read(sb.paths, "tasks")[-1]["event"], "created")                 # nothing written by the failures

    def test_prompt_renders_the_bounded_handoff(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            t = tasks.create(sb.paths, "x", "Ship it", str(wt))
            tasks.handoff(sb.paths, t["id"], to_route="a", objective="Do the thing", summary="Context here", commit="abc")
            task = tasks.load(sb.paths, t["id"])
            p = tasks.render_prompt(task, tasks.select_handoff(task, "latest"))
            for needle in ("worker session 1 for agent-on task", "Ship it", str(wt), "To route: mock/alpha", "Do the thing", "Context here", "Commit/base: abc",
                           "Do not assume the previous model transcript"):
                self.assertIn(needle, p)
            with self.assertRaises(ValueError):
                tasks.select_handoff(task, "7")

    def test_task_event_schema_is_enforced_by_learn(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "tasks", {"task_id": "bad id", "event": "created", "name": "n", "goal": "g", "worktree": "w"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "tasks", {"task_id": "20260908T000000Z-x-abcdef", "event": "created", "name": "n"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "tasks", {"task_id": "20260908T000000Z-x-abcdef", "event": "vanished"})


class CliTest(unittest.TestCase):
    def run_cli(self, sb, argv):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "AGENT_ON_STATE": str(sb.paths.state), "AGENT_ON_CHECKOUT": str(sb.paths.checkout)}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
            code = cli.main(["--json", "learn", "task", *argv])
        return code, json.loads(out.getvalue())

    def test_learn_task_verbs_through_the_cli(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            wt = sb.root / "wt"; wt.mkdir()
            code, doc = self.run_cli(sb, ["create", "Gateway review", "--goal", "Review", "--worktree", str(wt)])
            self.assertEqual(code, 0, doc)
            tid = doc["task"]["id"]
            code, doc = self.run_cli(sb, ["handoff", tid, "--to", "a", "--objective", "Run tests", "--summary", "s"])
            self.assertEqual(code, 0, doc)
            code, doc = self.run_cli(sb, ["prompt", tid])
            self.assertIn("Run tests", doc["prompt"])
            self.assertEqual(doc["route"], "mock/alpha")
            self.assertEqual(doc["worktree"], str(wt))
            code, doc = self.run_cli(sb, ["complete", tid, "--summary", "done", "--close"])
            self.assertEqual(doc["task"]["status"], "completed")
            code, doc = self.run_cli(sb, ["list"])
            self.assertEqual([t["id"] for t in doc["tasks"]], [tid])
            code, doc = self.run_cli(sb, ["show", tid])
            self.assertEqual(doc["task"]["handoffs"][0]["status"], "completed")
            code, doc = self.run_cli(sb, ["show", "20260908T000000Z-nope-abcdef"])
            self.assertEqual(code, 1)
            code, doc = self.run_cli(sb, ["bogus"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
