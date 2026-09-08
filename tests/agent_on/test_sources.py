from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402,F401

import unittest  # noqa: E402

from agent_on.mock_source import MockSource, omlx_entry, openrouter_entry  # noqa: E402
from agent_on.schemas.routes import Source  # noqa: E402
from agent_on.sources import (  # noqa: E402
    fetch_openrouter_spend, is_loopback, normalize_catalog, omlx_settings_path, probe_all, probe_source, read_configured_limits,
)


def src(name, base, catalog="/v1/models", auth_env=None, discover=False):
    return Source(name, base, auth_env, catalog, discover, None)


class NormalizeTest(unittest.TestCase):
    def test_both_catalog_shapes_normalise_to_one(self):
        cat = normalize_catalog({"object": "list", "data": [omlx_entry("local-a", 262144), openrouter_entry("v/m", 1048576, 131072)]})
        self.assertEqual(cat["local-a"], {"max_input": 262144, "max_output": None, "owned_by": "omlx", "pricing": None, "supported_parameters": None})
        self.assertEqual(cat["v/m"]["max_input"], 1048576)
        self.assertEqual(cat["v/m"]["max_output"], 131072)
        self.assertEqual(cat["v/m"]["pricing"]["prompt"], "0.000000966")
        self.assertIn("reasoning_effort", cat["v/m"]["supported_parameters"])

    def test_garbage_is_ignored_not_fatal(self):
        self.assertEqual(normalize_catalog({"data": [{"no": "id"}, "x", {"id": 3}]}), {})
        self.assertEqual(normalize_catalog([]), {})


class ProbeTest(unittest.TestCase):
    def test_reachable_source_yields_catalog_and_identity(self):
        with MockSource(catalog=[omlx_entry("a"), omlx_entry("b")]) as m:
            p = probe_source(src("mock", m.base_url), timeout=3)
            self.assertTrue(p.reachable)
            self.assertEqual(sorted(p.catalog), ["a", "b"])
            self.assertEqual(p.catalog_count, 2)
            self.assertEqual(p.identity, "owned_by=omlx")
            self.assertIsNone(p.error)
            self.assertTrue(p.checked.endswith("Z"))

    def test_unreachable_source_is_recorded_not_raised(self):
        p = probe_source(src("dead", "http://127.0.0.1:9"), timeout=1)   # port 9: discard, closed on macOS/Linux
        self.assertFalse(p.reachable)
        self.assertIn(":9", p.error)
        self.assertEqual(p.catalog, {})

    def test_http_error_and_missing_catalog_are_named(self):
        with MockSource() as m:
            p = probe_source(src("mock", m.base_url, catalog="/nope"), timeout=3)
            self.assertFalse(p.reachable)
            self.assertIn("HTTP 404", p.error)
        p = probe_source(Source("x", "http://127.0.0.1:1", None, None, False, None), timeout=1)
        self.assertEqual(p.error, "source declares no catalog")

    def test_probe_all_runs_every_source_and_times_out_the_stuck_one(self):
        with MockSource(catalog=[omlx_entry("a")]) as m:
            res = probe_all({"ok": src("ok", m.base_url), "dead": src("dead", "http://127.0.0.1:9")}, timeout=1)
            self.assertTrue(res["ok"].reachable)
            self.assertFalse(res["dead"].reachable)
            # a black-holed address (RFC 5737 TEST-NET) must come back within the bound, whether the network
            # answers with ICMP or with silence — never hang sync
            import time
            t0 = time.monotonic()
            res = probe_all({"hole": src("hole", "http://192.0.2.1:8000")}, timeout=1)
            self.assertFalse(res["hole"].reachable)
            self.assertIsNotNone(res["hole"].error)
            self.assertLess(time.monotonic() - t0, 5.0)

    def test_probe_all_bounds_total_time_with_several_stalled_sources(self):
        # three simultaneously black-holed sources must still come back inside the ONE shared deadline
        # window, not N * (timeout + 2) — that is what a sequential per-thread join would produce (~9s here).
        import time
        holes = {
            "hole1": src("hole1", "http://192.0.2.1:8000"),
            "hole2": src("hole2", "http://192.0.2.2:8000"),
            "hole3": src("hole3", "http://192.0.2.3:8000"),
        }
        t0 = time.monotonic()
        res = probe_all(holes, timeout=1)
        elapsed = time.monotonic() - t0
        for name in holes:
            self.assertFalse(res[name].reachable)
            self.assertIsNotNone(res[name].error)
        self.assertLess(elapsed, 5.0)

    def test_loopback_detection_and_settings_path(self):
        self.assertTrue(is_loopback("http://127.0.0.1:8000"))
        self.assertTrue(is_loopback("http://localhost:8000"))
        self.assertFalse(is_loopback("http://mortys-mac-studio:8000"))
        home = Path("/h")
        self.assertEqual(omlx_settings_path(src("omlx", "http://127.0.0.1:8000"), home), home / ".omlx" / "settings.json")
        self.assertIsNone(omlx_settings_path(src("omlx@morty", "http://mortys-mac-studio:8000"), home))
        self.assertIsNone(omlx_settings_path(src("exo", "http://127.0.0.1:52415"), home))   # loopback, but not oMLX
        self.assertEqual(omlx_settings_path(src("omlx-tp2", "http://127.0.0.1:8003"), home), home / ".omlx" / "settings.json")


class ConfiguredLimitsTest(unittest.TestCase):
    def test_reads_sampling_caps_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            p = home / ".omlx" / "settings.json"
            p.parent.mkdir()
            p.write_text(json.dumps({"sampling": {"max_context_window": 131072, "max_tokens": 32768}}), encoding="utf-8")
            got = read_configured_limits(p, home)
            self.assertEqual((got["input"], got["output"]), (131072, 32768))
            self.assertEqual(got["source"], "~/.omlx/settings.json")
            self.assertTrue(got["read_at"].endswith("Z"))
            p.write_text("{broken", encoding="utf-8")
            self.assertIsNone(read_configured_limits(p, home))
            self.assertIsNone(read_configured_limits(home / "missing.json", home))


class SpendTest(unittest.TestCase):
    def test_key_endpoint_maps_to_the_five_spend_fields(self):
        data = {"usage": 77.848, "limit": 100, "limit_reset": "daily", "limit_remaining": 99.96, "usage_daily": 0.04, "label": "<key label, never recorded>"}
        with MockSource(spend=data, expect_key="k-1") as m:
            s = fetch_openrouter_spend(m.base_url, "k-1", timeout=3)
            self.assertEqual((s["usd_used"], s["usd_limit"], s["limit_reset"], s["usd_remaining"], s["usd_used_daily"]), (77.848, 100, "daily", 99.96, 0.04))
            self.assertIsNone(s["error"])
            self.assertNotIn("label", s)                     # the (masked) key label is never recorded
            bad = fetch_openrouter_spend(m.base_url, "wrong", timeout=3)
            self.assertIsNone(bad["usd_used"])
            self.assertIn("401", bad["error"])
            self.assertTrue(any(path.endswith("/v1/auth/key") for path, _ in m.requests))


if __name__ == "__main__":
    unittest.main()
