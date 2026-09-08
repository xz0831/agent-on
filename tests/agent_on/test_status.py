from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.state import read_observed  # noqa: E402
from agent_on.status import build_status, render_text  # noqa: E402
from agent_on.sync import run_sync  # noqa: E402

BASE = "http://127.0.0.1:1"


class StatusTest(unittest.TestCase):
    def test_declared_beside_observed_before_any_sync(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            doc = build_status(sb.paths)
            self.assertEqual(doc["command"], "status")
            self.assertEqual(set(doc["routes"]), {"mock/alpha", "mock/gone", "paid/vendor/model-x"})
            alpha = doc["routes"]["mock/alpha"]
            self.assertEqual(alpha["declared"]["limits"]["input"], 8192)
            self.assertEqual(alpha["declared"]["limits_from"], "source")
            self.assertEqual(doc["routes"]["paid/vendor/model-x"]["declared"]["limits_from"], "route")
            self.assertEqual(doc["routes"]["paid/vendor/model-x"]["declared"]["price"]["input"], 1.0)
            self.assertIsNone(alpha["observed"])                                  # never measured → null, not a guess
            self.assertEqual(len(alpha["declared"]["effective_route_sha"]), 16)
            self.assertIsNone(doc["invariants"])
            self.assertIsNone(doc["last_check"])
            self.assertEqual(doc["orphaned"], [])
            self.assertIn("copy:", render_text(doc).splitlines()[0])
            json.dumps(doc)                                                       # --json must serialise as-is

    def test_route_filter_accepts_aliases_and_rejects_unknown(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(list(build_status(sb.paths, route="a")["routes"]), ["mock/alpha"])
            with self.assertRaises(KeyError):
                build_status(sb.paths, route="nope")

    def test_check_writes_last_check_never_last_gate_run(self):  # Q4
        with MockSource(catalog=[omlx_entry("alpha"), openrouter_entry("vendor/model-x")]) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            doc = build_status(sb.paths, check=True)
            self.assertIsNotNone(doc["invariants"])
            ids = {i["id"] for i in doc["invariants"]}
            self.assertIn("route.served", ids)
            self.assertEqual(doc["last_check"]["result"], "fail")                 # mock/gone is orphaned (F1)
            self.assertEqual(doc["orphaned"], ["mock/gone"])
            obs = read_observed(sb.paths)
            self.assertEqual(obs["last_check"]["result"], "fail")
            self.assertIsNone(obs["last_gate_run"])
            self.assertIn("credential.not_in_child_env", obs["last_check"]["skipped"])
            text = render_text(doc)
            self.assertIn("fail route.served[mock/gone]", text)
            self.assertIn("skip credential.not_in_child_env", text)
            self.assertIn("ORPHANED", text)

    def test_check_on_one_route_is_shown_but_never_persisted(self):
        with MockSource(catalog=[omlx_entry("alpha"), openrouter_entry("vendor/model-x")]) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            doc = build_status(sb.paths, route="mock/alpha", check=True)
            subjects = {i["subject"] for i in doc["invariants"] if i["subject"]}
            self.assertEqual(subjects, {"mock/alpha"})
            self.assertIsNone(doc["last_check"])                                # a partial check must not stand as the last check (Q4)
            self.assertIsNone(read_observed(sb.paths)["last_check"])
            build_status(sb.paths, check=True)
            self.assertEqual(read_observed(sb.paths)["last_check"]["result"], "fail")   # the full check sees mock/gone

    def test_broken_routes_toml_is_reported_not_raised(self):
        with Sandbox("version = 7\n") as sb:
            doc = build_status(sb.paths)
            self.assertIn("routes.version", doc["routes_error"])
            self.assertEqual(doc["routes"], {})
            self.assertIn("ERROR", render_text(doc))


if __name__ == "__main__":
    unittest.main()
