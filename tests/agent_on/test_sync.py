from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402
from agent_on.state import read_observed  # noqa: E402
from agent_on.sync import run_sync  # noqa: E402

CATALOG = [omlx_entry("alpha", 262144), omlx_entry("beta", 131072), openrouter_entry("vendor/model-x", 200000, 8000)]
SPEND = {"usage": 1.5, "limit": 10, "limit_reset": "daily", "limit_remaining": 8.5, "usage_daily": 0.5}


class SyncTest(unittest.TestCase):
    def test_sync_measures_served_limits_discovery_orphans_and_spend(self):
        with MockSource(catalog=CATALOG, spend=SPEND, expect_key="k-1") as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            settings = sb.paths.home / ".omlx" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"sampling": {"max_context_window": 131072, "max_tokens": 32768}}), encoding="utf-8")
            before = sb.paths.routes_toml.read_bytes()
            report = run_sync(sb.paths, timeout=3, env={"MOCK_PAID_KEY": "k-1"})
            self.assertEqual(sb.paths.routes_toml.read_bytes(), before, "sync never touches routes.toml")
            self.assertEqual(report["orphaned"], ["mock/gone"])                      # F1: declared but not served
            # alpha is packaged → shadowed, not discovered; the OpenRouter-shaped entry is also in `mock`'s catalog (one mock, two sources)
            self.assertEqual(report["discovered"], ["mock/beta", "mock/vendor/model-x"])
            self.assertEqual(report["shadowed"], [])
            obs = read_observed(sb.paths)
            self.assertTrue(obs["sources"]["mock"]["reachable"])
            self.assertEqual(obs["sources"]["mock"]["catalog"], ["alpha", "beta", "vendor/model-x"])
            self.assertEqual(obs["sources"]["mock"]["identity"], "owned_by=omlx")
            # R1: `mock` is loopback but not an oMLX source, so ~/.omlx/settings.json is not its configuration
            self.assertIsNone(obs["sources"]["mock"]["configured_limits"])
            self.assertEqual(set(obs["sources"]["paid"]["catalog"]), {"vendor/model-x"})   # non-discover: declared entries only
            self.assertEqual(obs["sources"]["paid"]["catalog_count"], 3)
            r = obs["routes"]["mock/alpha"]
            self.assertTrue(r["served"])
            self.assertEqual(r["limits"]["input"], {"configured": None, "advertised": 262144, "verified": None, "checked": r["checked"]})
            self.assertIsNone(r["limits"]["output"]["configured"])
            self.assertEqual((r["cost_model"]["context"], r["cost_model"]["context_basis"]), (8192, "declared"))   # source limit 8192 wins
            self.assertEqual(r["cost_model"]["usd_per_mtok"], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
            self.assertEqual(r["cost_model"]["caching"], "unknown")                   # never inferred from a price
            self.assertFalse(obs["routes"]["mock/gone"]["served"])
            x = obs["routes"]["paid/vendor/model-x"]
            self.assertEqual((x["cost_model"]["context"], x["cost_model"]["context_basis"]), (100000, "declared"))
            self.assertEqual(x["limits"]["input"]["advertised"], 200000)
            self.assertEqual(x["cost_model"]["usd_per_mtok"]["input"], 1.0)
            self.assertEqual(obs["routes"]["mock/beta"]["cost_model"]["context"], 8192)   # discovered → inherited source limit
            self.assertEqual(obs["spend"]["paid"]["usd_used"], 1.5)
            self.assertIsNone(obs["spend"]["paid"]["error"])
            self.assertEqual([i["id"] for i in report["invariants"]], ["route.unique"])
            self.assertEqual(report["invariants"][0]["result"], "pass")
            table = load_routes(sb.paths)
            self.assertIn("mock/beta", table.routes)
            self.assertEqual(table.effective_limits(table.routes["mock/beta"]).input, 8192)
            self.assertEqual(list(sb.paths.state.glob("*.tmp.*")), [])

    def test_declared_over_advertised_is_visible_and_second_sync_shadows_a_promoted_route(self):
        with MockSource(catalog=CATALOG) as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            self.assertIn("mock/beta", sb.paths.discovered_toml.read_text())
            # promote beta to packaged by hand (what `add` does), then sync again: it must drop out of the discovered file
            sb.paths.routes_toml.write_text(sb.paths.routes_toml.read_text() + '\n[routes."mock/beta"]\n', encoding="utf-8")
            report = run_sync(sb.paths, timeout=3, env={})
            self.assertNotIn("mock/beta", sb.paths.discovered_toml.read_text())
            self.assertEqual(report["discovered"], ["mock/vendor/model-x"])
            self.assertTrue(read_observed(sb.paths)["routes"]["mock/beta"]["served"])

    def test_configured_limits_reach_observed_only_for_an_omlx_source(self):
        # The same fixture with its loopback source named `omlxmock`: now ~/.omlx/settings.json IS its configuration,
        # and the tier reaches both the source record and every route it serves (§7 `sources.omlx*`).
        routes = MOCK_ROUTES.replace("mock", "omlxmock")   # an oMLX-named source the checkout does not declare
        with MockSource(catalog=CATALOG) as m, Sandbox(routes.format(base=m.base_url)) as sb:
            settings = sb.paths.home / ".omlx" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"sampling": {"max_context_window": 131072, "max_tokens": 32768}}), encoding="utf-8")
            run_sync(sb.paths, timeout=3, env={})
            obs = read_observed(sb.paths)
            self.assertEqual(obs["sources"]["omlxmock"]["configured_limits"]["input"], 131072)
            self.assertEqual(obs["sources"]["omlxmock"]["configured_limits"]["source"], "~/.omlx/settings.json")
            self.assertEqual(obs["routes"]["omlxmock/alpha"]["limits"]["input"]["configured"], 131072)
            self.assertEqual(obs["routes"]["omlxmock/alpha"]["limits"]["output"]["configured"], 32768)

    def test_unreachable_source_records_the_error_and_leaves_served_unmeasured(self):
        with Sandbox(MOCK_ROUTES.format(base="http://127.0.0.1:9")) as sb:
            report = run_sync(sb.paths, timeout=1, env={})
            obs = read_observed(sb.paths)
            self.assertFalse(obs["sources"]["mock"]["reachable"])
            self.assertIn(":9", obs["sources"]["mock"]["error"])
            self.assertIsNone(obs["routes"]["mock/alpha"]["served"])
            self.assertIsNone(obs["routes"]["mock/alpha"]["limits"]["input"]["advertised"])
            self.assertEqual(report["orphaned"], [])
            self.assertEqual(report["discovered"], [])
            self.assertIn("MOCK_PAID_KEY", obs["spend"]["paid"]["error"])            # no key anywhere → said where it looked
            self.assertTrue(sb.paths.discovered_toml.exists())

    def test_forwarded_remote_catalog_keeps_local_limits_out_of_observed(self):
        routes = '''version = 1
[sources."omlxmock@remote"]
base_url = "{base}"
catalog = "/v1/models"
discover = true
[sources."omlxmock@remote".limits]
input = 8192
output = 1024
confidence = "owned-policy"
source = "remote operator cap"
[routes."omlxmock@remote/alpha"]
'''
        with MockSource(catalog=CATALOG) as mock, Sandbox(routes.format(base=mock.base_url)) as sb:
            settings = sb.paths.home / ".omlx" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"sampling": {"max_context_window": 524288, "max_tokens": 65536}}))
            report = run_sync(sb.paths, timeout=3, env={})
            observed = read_observed(sb.paths)
            self.assertTrue(report["sources"]["omlxmock@remote"]["reachable"])
            self.assertIsNone(observed["sources"]["omlxmock@remote"]["configured_limits"])
            for name in ("omlxmock@remote/alpha", "omlxmock@remote/beta"):
                route = observed["routes"][name]
                self.assertTrue(route["served"])
                self.assertIsNone(route["limits"]["input"]["configured"])
                self.assertIsNone(route["limits"]["output"]["configured"])
                self.assertEqual(route["cost_model"]["context"], 8192)
                self.assertEqual(route["cost_model"]["context_basis"], "declared")

    def test_a_source_that_goes_unreachable_loses_its_stale_catalog_and_identity(self):
        m = MockSource(catalog=CATALOG).start()
        with Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            run_sync(sb.paths, timeout=3, env={})
            self.assertEqual(read_observed(sb.paths)["sources"]["mock"]["identity"], "owned_by=omlx")
            m.stop()
            run_sync(sb.paths, timeout=1, env={})
            src = read_observed(sb.paths)["sources"]["mock"]
            self.assertFalse(src["reachable"])
            self.assertIsNone(src["catalog"])                                   # a stale list under a fresh `checked` is R1
            self.assertIsNone(src["identity"])
            self.assertIsNone(src["catalog_count"])
            self.assertIsNone(read_observed(sb.paths)["routes"]["mock/alpha"]["served"])

    def test_spend_key_comes_from_the_env_file_when_the_environment_has_none(self):
        with MockSource(catalog=CATALOG, spend=SPEND, expect_key="k-file") as m, Sandbox(MOCK_ROUTES.format(base=m.base_url)) as sb:
            sb.paths.state.mkdir()
            sb.paths.env_file.write_text("MOCK_PAID_KEY=k-file\n", encoding="utf-8")
            os.chmod(sb.paths.env_file, 0o600)
            run_sync(sb.paths, timeout=3, env={})
            self.assertEqual(read_observed(sb.paths)["spend"]["paid"]["usd_limit"], 10)


if __name__ == "__main__":
    unittest.main()
