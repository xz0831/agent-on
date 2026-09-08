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

from agent_on import cli, knowledge  # noqa: E402

BASE = "http://127.0.0.1:1"
DECISION = json.dumps({"decision": "d", "rationale": "r", "by": "test"})


def run(sb, argv, stdin: str | None = None) -> tuple[int, dict]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sb.paths.home), "AGENT_ON_STATE": str(sb.paths.state), "AGENT_ON_CHECKOUT": str(sb.paths.checkout)}
    out = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin or "")):
        code = cli.main(["--json", *argv])
    return code, json.loads(out.getvalue())


class LearnTest(unittest.TestCase):
    def test_learn_appends_a_validated_record_from_the_flag(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions", "--json-record", DECISION])
            self.assertEqual(code, 0, doc)
            self.assertTrue(doc["written"])
            self.assertTrue(doc["record"]["id"].startswith("decisions-"))
            self.assertEqual(doc["path"], str(sb.paths.knowledge_dir / "decisions.jsonl"))
            self.assertEqual([i["result"] for i in doc["invariants"]], ["pass"])
            self.assertEqual(knowledge.read(sb.paths, "decisions")[0]["id"], doc["record"]["id"])

    def test_learn_reads_stdin_when_the_flag_is_absent(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions"], stdin=DECISION)
            self.assertEqual(code, 0, doc)
            self.assertTrue(doc["written"])

    def test_a_bad_record_is_a_schema_error_exit_3_and_nothing_is_written(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions", "--json-record", '{"decision": "d"}'])
            self.assertEqual(code, 3)
            self.assertEqual(doc["rule"], "knowledge.record")
            self.assertFalse((sb.paths.knowledge_dir / "decisions.jsonl").exists())
            code, doc = run(sb, ["learn", "vibes", "--json-record", DECISION])
            self.assertEqual(code, 3)
            code, doc = run(sb, ["learn", "decisions", "--json-record", "not json"])
            self.assertEqual(code, 2)
            self.assertIn("error", doc)

    def test_empty_stdin_is_usage(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "decisions"], stdin="")
            self.assertEqual(code, 2)

    def test_learn_task_is_routed_to_the_task_parser(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            code, doc = run(sb, ["learn", "task"])
            self.assertEqual(code, 2)                                                   # Task 6 replaces the stub


if __name__ == "__main__":
    unittest.main()
