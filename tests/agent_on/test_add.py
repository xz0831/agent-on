from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.add import HOLD_ENV, route_from_catalog, run_add  # noqa: E402
from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.paths import Paths  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.routes import Source, load_routes  # noqa: E402
from agent_on.sources import normalize_catalog  # noqa: E402

CATALOG = [omlx_entry("alpha"), omlx_entry("beta", 131072), openrouter_entry("vendor/model-y", 200000, 8000, "0.000001", "0.000002", None)]

ADD_SCRIPT = """
import sys, time; sys.path.insert(0, {repo!r})
from pathlib import Path
from agent_on.paths import Paths
from agent_on.add import run_add
from agent_on.schemas.errors import SchemaError
p = Paths(checkout=Path({co!r}), state=Path({st!r}), home=Path({home!r}))
t0 = time.monotonic()
try:
    r = run_add(p, {name!r}, timeout=3)
except SchemaError as e:
    print(f"schema:{{e.rule}}", file=sys.stderr)
    raise SystemExit(3)
print(f"took:{{time.monotonic() - t0:.3f}}")
raise SystemExit(0 if r["written"] else 1)
"""


class AddTest(unittest.TestCase):
    def test_add_appends_a_block_preserving_the_file_and_fills_from_the_catalog(self):
        with MockSource(catalog=CATALOG) as m, Sandbox("# keep this comment\n" + MOCK_ROUTES.format(base=m.base_url)) as sb:
            before = sb.paths.routes_toml.read_text(encoding="utf-8")
            r = run_add(sb.paths, "mock/beta", alias="b", timeout=3)
            self.assertTrue(r["written"])
            self.assertEqual([i["id"] for i in r["invariants"]], ["route.served", "route.unique"])
            self.assertEqual([i["result"] for i in r["invariants"]], ["pass", "pass"])
            after = sb.paths.routes_toml.read_text(encoding="utf-8")
            self.assertTrue(after.startswith(before.rstrip("\n")))             # nothing above the new block changed
            table = load_routes(sb.paths)
            self.assertIs(table.resolve("b"), table.routes["mock/beta"])
            self.assertIsNone(table.routes["mock/beta"].limits)                 # keyless source: inherits, no price
            self.assertEqual(table.effective_limits(table.routes["mock/beta"]).input, 8192)
            r = run_add(sb.paths, "paid/vendor/model-y", timeout=3)
            y = load_routes(sb.paths).routes["paid/vendor/model-y"]
            self.assertEqual((y.limits.input, y.limits.output, y.limits.confidence), (200000, 8000, "provider"))
            self.assertEqual((y.price.input, y.price.output, y.price.cache_read, y.price.cache_write), (1.0, 2.0, None, None))
            self.assertTrue(y.reasoning.supported)
            self.assertEqual((y.reasoning.confidence, y.reasoning.efforts), ("provider", ()))
            self.assertIn("paid.pricing", y.price.source)
            self.assertEqual(list(sb.paths.checkout.glob("routes.toml.tmp.*")), [])

    def test_an_unparseable_catalog_price_is_an_absent_price_not_a_crash(self):
        entry = normalize_catalog({"data": [openrouter_entry("vendor/model-z", prompt="n/a")]})["vendor/model-z"]
        source = Source("paid", "http://127.0.0.1:9", "MOCK_PAID_KEY", "/v1/models", False, None,
                        billing="metered")
        route = route_from_catalog("paid/vendor/model-z", source, entry, (), "2026-09-08")
        self.assertIsNone(route.price)
        self.assertIsNotNone(route.limits)      # the rest of the entry is still read

    def test_unserved_model_is_refused_and_unreachable_source_proceeds_with_a_skip(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            r = run_add(sb.paths, "mock/nope", timeout=3)
            self.assertFalse(r["written"])
            self.assertEqual(r["invariants"][0]["result"], "fail")
            self.assertNotIn("mock/nope", sb.paths.routes_toml.read_text())
        with Sandbox(MOCK_ROUTES.format(base="http://127.0.0.1:9")) as sb:
            r = run_add(sb.paths, "mock/blind", timeout=1)
            self.assertTrue(r["written"])
            self.assertEqual(r["invariants"][0]["result"], "skip")

    def test_duplicates_and_bad_names_are_schema_errors_and_write_nothing(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            before = sb.paths.routes_toml.read_text()
            with self.assertRaises(SchemaError) as cm:
                run_add(sb.paths, "mock/beta", alias="a", timeout=3)            # alias "a" already on mock/alpha
            self.assertEqual(cm.exception.rule, "routes.unique")
            with self.assertRaises(SchemaError):
                run_add(sb.paths, "nosuch/model", timeout=3)
            with self.assertRaises(SchemaError):
                run_add(sb.paths, "mock/alpha", timeout=3)                      # already packaged
            self.assertEqual(sb.paths.routes_toml.read_text(), before)

    def test_two_adds_under_different_state_roots_both_survive(self):
        # rev-6 P2: the writer lock is keyed by the checkout, so a scratch AGENT_ON_STATE run serialises with the default one.
        # Process A holds the lock ~600 ms after its re-read; B starts 150 ms later and must wait, then re-read A's result.
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            other_state = sb.root / "scratch-state"
            script = lambda st, name: ADD_SCRIPT.format(repo=str(REPO), co=str(sb.paths.checkout), st=str(st), home=str(sb.paths.home), name=name)
            a = subprocess.Popen([sys.executable, "-c", script(sb.paths.state, "mock/beta")], env={**os.environ, HOLD_ENV: "600"},
                                 stdout=subprocess.PIPE, text=True)
            time.sleep(0.15)
            b = subprocess.Popen([sys.executable, "-c", script(other_state, "paid/vendor/model-y")], env={**os.environ, HOLD_ENV: "0"},
                                 stdout=subprocess.PIPE, text=True)
            a_out, _ = a.communicate(timeout=60)
            b_out, _ = b.communicate(timeout=60)
            self.assertEqual((a.returncode, b.returncode), (0, 0))
            # Non-vacuous: B really blocked on A's lock. A holds it 600 ms after its re-read and B starts 150 ms
            # in, so B cannot finish in under ~0.45 s unless the two never contended for the same lock at all.
            b_took = float(b_out.split("took:")[1].strip())
            self.assertGreaterEqual(b_took, 0.3, f"B did not wait for A's hold (a={a_out!r} b={b_out!r})")
            table = load_routes(sb.paths)
            self.assertIn("mock/beta", table.routes)
            self.assertIn("paid/vendor/model-y", table.routes)

    def test_two_adds_of_the_same_route_refuse_the_loser_under_routes_unique(self):
        # Same race as above, but both processes target "mock/beta": the loser's pre-lock read predates the
        # winner's write, so it must be refused in-lock under routes.unique rather than corrupting the merge.
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            other_state = sb.root / "scratch-state"
            script = lambda st, name: ADD_SCRIPT.format(repo=str(REPO), co=str(sb.paths.checkout), st=str(st), home=str(sb.paths.home), name=name)
            a = subprocess.Popen([sys.executable, "-c", script(sb.paths.state, "mock/beta")], env={**os.environ, HOLD_ENV: "600"},
                                  stderr=subprocess.PIPE, text=True)
            time.sleep(0.15)
            b = subprocess.Popen([sys.executable, "-c", script(other_state, "mock/beta")], env={**os.environ, HOLD_ENV: "0"},
                                  stderr=subprocess.PIPE, text=True)
            _, a_err = a.communicate(timeout=60)
            _, b_err = b.communicate(timeout=60)
            codes = {a.returncode, b.returncode}
            self.assertEqual(codes, {0, 3})
            loser_err = a_err if a.returncode == 3 else b_err
            self.assertIn("schema:routes.unique", loser_err)
            table = load_routes(sb.paths)
            self.assertIn("mock/beta", table.routes)
            text = sb.paths.routes_toml.read_text(encoding="utf-8")
            self.assertEqual(text.count('[routes."mock/beta"]'), 1)


if __name__ == "__main__":
    unittest.main()
