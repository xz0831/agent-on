from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on import knowledge  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.knowledge import validate_file  # noqa: E402

BASE = "http://127.0.0.1:1"
TRAP = {"trap": "t", "mechanism": "m", "avoid": "a", "evidence": "e", "found_by": "f", "applies_to": ["launch", "mock"]}


class AppendReadTest(unittest.TestCase):
    def test_append_mints_id_and_ts_creates_the_dir_and_reads_back_in_order(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            self.assertFalse(sb.paths.knowledge_dir.exists())
            a = knowledge.append(sb.paths, "traps", dict(TRAP))
            b = knowledge.append(sb.paths, "traps", dict(TRAP, trap="u"), now="2026-09-08T00:00:00Z")
            self.assertTrue(a["id"].startswith("traps-") and len(a["id"]) == len("traps-") + 26)
            self.assertRegex(a["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertEqual(b["ts"], "2026-09-08T00:00:00Z")
            self.assertEqual([r["trap"] for r in knowledge.read(sb.paths, "traps")], ["t", "u"])
            self.assertEqual(knowledge.read(sb.paths, "decisions"), [])
            lines = (sb.paths.knowledge_dir / "traps.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0]), a)                                   # one line per record, sorted keys
            self.assertTrue(sb.paths.knowledge_lock.exists())

    def test_an_invalid_record_writes_nothing(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "traps", {"trap": "t"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "vibes", {"x": 1})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=[]))
            self.assertFalse((sb.paths.knowledge_dir / "traps.jsonl").exists())

    def test_supersedes_must_name_an_existing_id_of_the_same_kind(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            d1 = knowledge.append(sb.paths, "decisions", {"decision": "a", "rationale": "r", "by": "rick"})
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "decisions", {"decision": "b", "rationale": "r", "by": "rick", "supersedes": "decisions-nope"})
            t = knowledge.append(sb.paths, "traps", dict(TRAP))
            with self.assertRaises(SchemaError):
                knowledge.append(sb.paths, "decisions", {"decision": "b", "rationale": "r", "by": "rick", "supersedes": t["id"]})
            d2 = knowledge.append(sb.paths, "decisions", {"decision": "b", "rationale": "r", "by": "rick", "supersedes": d1["id"]})
            self.assertEqual([r["id"] for r in knowledge.active(knowledge.read(sb.paths, "decisions"))], [d2["id"]])

    def test_a_malformed_line_is_a_schema_error_naming_file_and_line(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            knowledge.append(sb.paths, "traps", dict(TRAP))
            with open(sb.paths.knowledge_dir / "traps.jsonl", "a", encoding="utf-8") as f:
                f.write("not json\n")
            with self.assertRaises(SchemaError) as cm:
                knowledge.read(sb.paths, "traps")
            self.assertIn("traps.jsonl:2", str(cm.exception))
            errors = validate_file(sb.paths.knowledge_dir / "traps.jsonl")
            self.assertEqual(len(errors), 1)

    def test_validate_file_reports_duplicate_ids_and_dangling_supersedes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            sb.paths.knowledge_dir.mkdir()
            p = sb.paths.knowledge_dir / "decisions.jsonl"
            p.write_text('{"id": "decisions-1", "ts": "2026-09-08T00:00:00Z", "decision": "a", "rationale": "r", "by": "b"}\n'
                         '{"id": "decisions-1", "ts": "2026-09-08T00:00:00Z", "decision": "a", "rationale": "r", "by": "b"}\n'
                         '{"id": "decisions-2", "ts": "2026-09-08T00:00:00Z", "decision": "a", "rationale": "r", "by": "b", "supersedes": "decisions-9"}\n',
                         encoding="utf-8")
            errors = validate_file(p)
            self.assertTrue(any("duplicate id decisions-1" in e for e in errors), errors)
            self.assertTrue(any("supersedes decisions-9 not found" in e for e in errors), errors)


class SelectionTest(unittest.TestCase):
    def test_latest_and_applicable_traps(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            for i in range(5):
                knowledge.append(sb.paths, "observations", {"route": "mock/alpha" if i % 2 == 0 else "mock/beta", "kind": "cost",
                                                            "values": {"i": i}, "evidence": "e"})
            obs = knowledge.read(sb.paths, "observations")
            self.assertEqual([o["values"]["i"] for o in knowledge.latest(obs, route="mock/alpha", n=2)], [2, 4])
            self.assertEqual([o["values"]["i"] for o in knowledge.latest(obs, route=None, n=2)], [3, 4])
            t_launch = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["launch"]))
            t_src = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["mock"]))
            t_route = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["mock/beta"]))
            t_star = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["*"]))
            t_old = knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["*"]))
            knowledge.append(sb.paths, "traps", dict(TRAP, applies_to=["sync"], supersedes=t_old["id"]))
            traps = knowledge.active(knowledge.read(sb.paths, "traps"))
            got = knowledge.applicable_traps(traps, route="mock/alpha", source="mock", action="launch")
            self.assertEqual({t["id"] for t in got}, {t_launch["id"], t_src["id"], t_star["id"]})
            got = knowledge.applicable_traps(traps, route="mock/beta", source="mock", action="status")
            self.assertEqual({t["id"] for t in got}, {t_src["id"], t_route["id"], t_star["id"]})
            self.assertNotIn(t_old["id"], {t["id"] for t in traps})

    def test_knowledge_view_reports_missing_when_there_is_no_directory(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            v = knowledge.knowledge_view(sb.paths, route="mock/alpha", source="mock", action="status")
            self.assertEqual(v, {"observations": [], "traps": [], "missing": True})

    def test_knowledge_view_reports_a_corrupt_line_instead_of_raising(self):  # D6: inform, don't gate
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            knowledge.append(sb.paths, "traps", dict(TRAP))
            with open(sb.paths.knowledge_dir / "traps.jsonl", "a", encoding="utf-8") as f:
                f.write("not json\n")
            v = knowledge.knowledge_view(sb.paths, route="mock/alpha", source="mock", action="status")
            self.assertEqual(v["observations"], [])
            self.assertEqual(v["traps"], [])
            self.assertIn("traps.jsonl:2", v["error"])
            self.assertNotIn("missing", v)


if __name__ == "__main__":
    unittest.main()
