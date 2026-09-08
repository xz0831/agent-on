from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.schemas.observed import empty_route  # noqa: E402
from agent_on.state import read_observed, update_observed  # noqa: E402
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
            self.assertNotIn("credential.not_in_child_env", obs["last_check"]["skipped"])
            self.assertIn("copy.single", obs["last_check"]["skipped"])
            text = render_text(doc)
            self.assertIn("fail route.served[mock/gone]", text)
            self.assertIn("pass credential.not_in_child_env", text)
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

    def test_text_view_shows_the_last_qualifications_outcome(self):  # F3
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            fp = {"effective_route_sha": "sha", "wire_model": "alpha", "source_identity": None, "claude_code": None}

            def plant_failing(doc):
                doc["routes"]["mock/alpha"] = empty_route()
                doc["routes"]["mock/alpha"]["last_qualification"] = {
                    "pass": False, "at": "2026-09-08T00:00:00Z",
                    "gates": {"text_sse": True, "forced_structured_tool": False},
                    "thinking_block_seen": False, "completed": True, "fingerprint": fp}

            def plant_passing(doc):
                doc["routes"]["paid/vendor/model-x"] = empty_route()
                doc["routes"]["paid/vendor/model-x"]["last_qualification"] = {
                    "pass": True, "at": "2026-09-08T01:00:00Z", "gates": {"text_sse": True},
                    "thinking_block_seen": True, "completed": True, "fingerprint": fp}

            def plant_never(doc):
                doc["routes"]["mock/gone"] = empty_route()

            update_observed(sb.paths, plant_failing)
            update_observed(sb.paths, plant_passing)
            update_observed(sb.paths, plant_never)
            text = render_text(build_status(sb.paths))
            self.assertIn("qualified ✗ 2026-09-08T00:00:00Z (forced_structured_tool)", text)
            self.assertIn("qualified ✓ 2026-09-08T01:00:00Z", text)
            self.assertIn("qualified: never", text)

    def test_broken_routes_toml_is_reported_not_raised(self):
        with Sandbox("version = 7\n") as sb:
            doc = build_status(sb.paths)
            self.assertIn("routes.version", doc["routes_error"])
            self.assertEqual(doc["routes"], {})
            self.assertIn("ERROR", render_text(doc))

    def test_status_shows_the_last_observations_and_the_traps_for_the_route(self):
        from agent_on import knowledge
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            for i in range(4):
                knowledge.append(sb.paths, "observations", {"route": "mock/alpha", "kind": "cost", "values": {"i": i}, "evidence": "e"})
            knowledge.append(sb.paths, "traps", {"trap": "mind the gap", "mechanism": "m", "avoid": "step over", "evidence": "e", "found_by": "f", "applies_to": ["mock"]})
            knowledge.append(sb.paths, "traps", {"trap": "launch only", "mechanism": "m", "avoid": "a", "evidence": "e", "found_by": "f", "applies_to": ["launch"]})
            doc = build_status(sb.paths, route="a")
            k = doc["routes"]["mock/alpha"]["knowledge"]
            self.assertEqual([o["values"]["i"] for o in k["observations"]], [1, 2, 3])
            self.assertEqual([t["trap"] for t in k["traps"]], ["mind the gap"])
            text = render_text(doc)
            self.assertIn("trap: mind the gap — avoid: step over", text)
            self.assertIn('observation', text)
            self.assertNotIn("launch only", text)

    def test_a_corrupt_knowledge_line_does_not_gate_status(self):  # D6: inform, don't gate
        from agent_on import knowledge
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            knowledge.append(sb.paths, "traps", {"trap": "mind the gap", "mechanism": "m", "avoid": "step over", "evidence": "e", "found_by": "f", "applies_to": ["mock"]})
            with open(sb.paths.knowledge_dir / "traps.jsonl", "a", encoding="utf-8") as f:
                f.write("not json\n")
            doc = build_status(sb.paths, route="a")
            k = doc["routes"]["mock/alpha"]["knowledge"]
            self.assertEqual(k["traps"], [])
            self.assertIn("traps.jsonl:2", k["error"])
            text = render_text(doc)
            self.assertIn("knowledge: unreadable", text)
            self.assertIn("traps.jsonl:2", text)


if __name__ == "__main__":
    unittest.main()
