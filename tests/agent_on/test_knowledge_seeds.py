from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

import unittest  # noqa: E402

from agent_on import knowledge  # noqa: E402
from agent_on.paths import Paths  # noqa: E402
from agent_on.schemas.knowledge import APPLIES_TO_VERBS, KINDS, validate_file  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402

REQUIRED = {"decisions": ["decisions-D1", "decisions-D2", "decisions-D3", "decisions-D3-2026-08-20", "decisions-D3-2026-09-06", "decisions-D6",
                          "decisions-D13", "decisions-Q8-attribution-deferred", "decisions-Q10-delete-a-route", "decisions-delegate-cheaper-models", "decisions-fix-on-contact"],
            "observations": ["observations-2026-08-23-tokenizer-delta", "observations-2026-08-23-huihui-quality", "observations-2026-09-06-omlx-serialises",
                             "observations-2026-09-08-omlx-concurrency-per-model", "observations-2026-09-06-baseline-48312", "observations-2026-09-08-baseline-54380",
                             "observations-2026-09-07-thinking-two-arm", "observations-2026-09-08-direct-cache", "observations-2026-09-08-limits-huihui-260671"],
            "traps": ["traps-single-quoted-battery", "traps-installed-copy-selector", "traps-promotion-deadlock", "traps-budget-formula-in-code",
                      "traps-port-4000-collision", "traps-fabricated-cost-field", "traps-discovery-filter", "traps-child-env-credential",
                      "traps-exo-thunderbolt-hijack", "traps-settings-last-wins", "traps-synthetic-error-turns"]}


class SeedsTest(unittest.TestCase):
    """Read-only over the real checkout's knowledge/: the seeds are data the repo ships, and this pins their shape."""

    def setUp(self):
        self.paths = Paths(checkout=REPO, state=REPO / "does-not-exist", home=REPO / "does-not-exist")

    def test_every_kind_has_a_file_and_every_file_validates(self):
        for kind in KINDS:
            p = self.paths.knowledge_dir / f"{kind}.jsonl"
            self.assertTrue(p.exists(), p)
            self.assertEqual(validate_file(p), [], kind)

    def test_required_seed_ids_are_present_and_the_d3_chain_ends_at_d3(self):
        for kind, ids in REQUIRED.items():
            have = {r["id"] for r in knowledge.read(self.paths, kind)}
            self.assertTrue(set(ids) <= have, sorted(set(ids) - have))
        d = {r["id"]: r for r in knowledge.read(self.paths, "decisions")}
        self.assertEqual(d["decisions-D3-2026-09-06"]["supersedes"], "decisions-D3-2026-08-20")
        self.assertEqual(d["decisions-D3"]["supersedes"], "decisions-D3-2026-09-06")
        self.assertIn("decisions-D3", {r["id"] for r in knowledge.active(list(d.values()))})
        self.assertNotIn("decisions-D3-2026-09-06", {r["id"] for r in knowledge.active(list(d.values()))})

    def test_trap_targets_are_verbs_sources_routes_or_star(self):
        table = load_routes(self.paths)
        allowed = set(APPLIES_TO_VERBS) | {"*"} | set(table.sources) | set(table.routes)
        for t in knowledge.read(self.paths, "traps"):
            for a in t["applies_to"]:
                self.assertIn(a, allowed, f"{t['id']}: {a}")

    def test_observation_routes_name_a_source_of_this_system(self):
        table = load_routes(self.paths)
        for o in knowledge.read(self.paths, "observations"):
            self.assertIn(o["route"].split("/", 1)[0], set(table.sources) | {"harness"}, o["id"])


if __name__ == "__main__":
    unittest.main()
