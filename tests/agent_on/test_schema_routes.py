from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.schemas.errors import RULES, SchemaError  # noqa: E402
from agent_on.schemas.routes import (  # noqa: E402
    Route, discovered_text, load_routes, merge_tables, parse_routes_text, route_block,
)

BASE = "http://127.0.0.1:1"


def routes(text: str):
    return parse_routes_text(text, packaged=True)


class ParseTest(unittest.TestCase):
    def test_fixture_parses_and_wire_model_defaults_to_the_name_tail(self):
        srcs, rts, stale = routes(MOCK_ROUTES.format(base=BASE))
        self.assertEqual(set(srcs), {"mock", "paid"})
        self.assertEqual(rts["mock/alpha"].wire_model, "alpha")
        self.assertEqual(rts["paid/vendor/model-x"].wire_model, "vendor/model-x")
        self.assertEqual(rts["mock/alpha"].aliases, ("a",))
        self.assertTrue(rts["mock/alpha"].packaged)
        self.assertEqual(stale, ())
        self.assertEqual(srcs["mock"].catalog_url(), f"{BASE}/v1/models")
        self.assertEqual(srcs["paid"].catalog_url(), f"{BASE}/api/v1/models")
        self.assertEqual(srcs["mock"].port(), 1)

    def assertRule(self, rule: str, text: str):
        with self.assertRaises(SchemaError) as cm:
            routes(text)
        self.assertEqual(cm.exception.rule, rule, str(cm.exception))

    def test_every_rule_is_stated_once_and_raised_with_its_id(self):
        head = 'version = 1\n[sources.mock]\nbase_url = "http://127.0.0.1:1"\n'
        self.assertRule("routes.version", 'version = 2\n[sources.mock]\nbase_url = "http://x"\n')
        self.assertRule("routes.version", "this is not toml [[[")
        self.assertRule("routes.source.shape", 'version = 1\n[sources.mock]\nbase_url = "ftp://x"\n')
        self.assertRule("routes.source.shape", head + "discover = 1\n")
        self.assertRule("routes.route.name", head + '[routes."nosource"]\n')
        self.assertRule("routes.route.name", head + '[routes."other/m"]\n')
        self.assertRule("routes.route.shape", head + '[routes."mock/m"]\nthinking = true\n')
        self.assertRule("routes.route.wire_model", head + '[routes."mock/m"]\nwire_model = ""\n')
        self.assertRule("routes.limits.shape", head + '[routes."mock/m".limits]\ninput = 10\n')
        self.assertRule("routes.limits.shape", head + '[routes."mock/m".limits]\ninput = 10\nconfidence = "verified"\nsource = "x"\n')
        self.assertRule("routes.limits.no_globs", head + '[routes."mock/Qwen*"]\n')
        self.assertRule("routes.reasoning.shape", head + '[routes."mock/m".reasoning]\nefforts = "low"\nsource = "x"\n')
        self.assertRule("routes.reasoning.shape", head + '[routes."mock/m".reasoning]\nsupported = true\n')
        self.assertRule("routes.price.shape", head + '[routes."mock/m".price]\ninput_usd_per_mtok = 1\nsource = "x"\n')
        self.assertRule("routes.alias.shape", head + '[routes."mock/m"]\naliases = ["a/b"]\n')
        self.assertRule("routes.unique", head + '[routes."mock/m"]\naliases = ["z"]\n[routes."mock/n"]\naliases = ["z"]\n')
        self.assertRule("routes.unique", head + '[routes."mock/m"]\nwire_model = "same"\n[routes."mock/n"]\nwire_model = "same"\n')
        for rule in ("routes.version", "routes.source.shape", "routes.route.name", "routes.route.shape", "routes.route.wire_model",
                     "routes.limits.shape", "routes.limits.no_globs", "routes.reasoning.shape", "routes.price.shape",
                     "routes.alias.shape", "routes.unique"):
            self.assertIn(rule, RULES)

    def test_reasoning_accepts_the_spec_shape_and_supported_alone(self):
        head = 'version = 1\n[sources.mock]\nbase_url = "http://127.0.0.1:1"\n'
        _, rts, _ = routes(head + '[routes."mock/m".reasoning]\nefforts = ["low", "high"]\nprovider_efforts = ["xhigh", "high"]\nconfidence = "provider"\nsource = "x"\n')
        r = rts["mock/m"].reasoning
        self.assertEqual((r.supported, r.efforts, r.provider_efforts, r.confidence), (True, ("low", "high"), ("xhigh", "high"), "provider"))
        _, rts, _ = routes(head + '[routes."mock/m".reasoning]\nsupported = true\nsource = "x"\n')
        r = rts["mock/m"].reasoning
        self.assertEqual((r.supported, r.efforts, r.confidence), (True, (), None))

    def test_unregistered_rule_cannot_be_raised(self):
        with self.assertRaises(KeyError):
            SchemaError("not.a.rule", "x")

    def test_discovered_file_may_not_declare_sources_and_drops_stale_sources(self):
        srcs, _, _ = routes(MOCK_ROUTES.format(base=BASE))
        with self.assertRaises(SchemaError) as cm:
            parse_routes_text('version = 1\n[sources.x]\nbase_url = "http://x"\n', packaged=False, sources=srcs)
        self.assertEqual(cm.exception.rule, "routes.source.shape")
        _, rts, stale = parse_routes_text('version = 1\n[routes."mock/new"]\n[routes."vanished/m"]\n', packaged=False, sources=srcs)
        self.assertEqual(set(rts), {"mock/new"})
        self.assertFalse(rts["mock/new"].packaged)
        self.assertEqual(stale, ("vanished/m",))


class MergeAndTableTest(unittest.TestCase):
    def test_packaged_wins_by_source_and_wire_model(self):
        srcs, packaged, _ = routes(MOCK_ROUTES.format(base=BASE))
        disc = {"mock/alpha": Route("mock/alpha", "mock", "alpha", (), None, None, None, False),
                "mock/beta": Route("mock/beta", "mock", "beta", (), None, None, None, False)}
        merged, shadowed = merge_tables(packaged, disc)
        self.assertEqual(shadowed, ("mock/alpha",))
        self.assertTrue(merged["mock/alpha"].packaged)
        self.assertIn("mock/beta", merged)
        with self.assertRaises(SchemaError):  # a discovered alias may not reuse a packaged alias
            merge_tables(packaged, {"mock/z": Route("mock/z", "mock", "z", ("a",), None, None, None, False)})

    def test_load_routes_merges_the_state_file_and_inherits_source_limits(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir()
            sb.paths.discovered_toml.write_text('version = 1\n[routes."mock/beta"]\n', encoding="utf-8")
            table = load_routes(sb.paths)
            self.assertEqual(set(table.routes), {"mock/alpha", "mock/gone", "paid/vendor/model-x", "mock/beta"})
            beta = table.routes["mock/beta"]
            self.assertIsNone(beta.limits)
            self.assertEqual(table.effective_limits(beta).input, 8192)        # inherited (§6, rev 6)
            self.assertEqual(table.effective_limits(table.routes["paid/vendor/model-x"]).input, 100000)
            self.assertIs(table.resolve("a"), table.routes["mock/alpha"])
            self.assertIs(table.resolve("mock/beta"), beta)
            with self.assertRaises(KeyError):
                table.resolve("nope")

    def test_effective_sha_tracks_the_source_entry_and_inherited_limits(self):
        # rev-5 P2: the fingerprint must change when the *source* changes, not only the route entry
        text = MOCK_ROUTES.format(base=BASE)
        with Sandbox(text) as sb:
            before = load_routes(sb.paths)
            sha_alpha = before.effective_sha(before.routes["mock/alpha"])
            sha_x = before.effective_sha(before.routes["paid/vendor/model-x"])
            sb.paths.routes_toml.write_text(text.replace("input = 8192", "input = 4096"), encoding="utf-8")
            after = load_routes(sb.paths)
            self.assertNotEqual(sha_alpha, after.effective_sha(after.routes["mock/alpha"]))   # inherited limit changed
            self.assertEqual(sha_x, after.effective_sha(after.routes["paid/vendor/model-x"]))  # unrelated route unchanged
            sb.paths.routes_toml.write_text(text.replace(f'base_url = "{BASE}"\nauth_env', 'base_url = "http://127.0.0.1:2"\nauth_env'), encoding="utf-8")
            moved = load_routes(sb.paths)
            self.assertNotEqual(sha_x, moved.effective_sha(moved.routes["paid/vendor/model-x"]))  # source URL changed


class EmitTest(unittest.TestCase):
    def test_route_block_round_trips_through_the_parser(self):
        srcs, rts, _ = routes(MOCK_ROUTES.format(base=BASE))
        r = rts["paid/vendor/model-x"]
        text = 'version = 1\n[sources.paid]\nbase_url = "http://127.0.0.1:1"\nauth_env = "K"\n\n' + route_block(r)
        _, again, _ = routes(text)
        self.assertEqual(again["paid/vendor/model-x"], r)

    def test_discovered_text_is_machine_state_with_no_sources(self):
        text = discovered_text([Route("mock/beta", "mock", "beta", (), None, None, None, False)], "2026-09-07T00:00:00Z")
        self.assertIn("never edit, never commit", text)
        self.assertNotIn("[sources", text)
        srcs, _, _ = routes(MOCK_ROUTES.format(base=BASE))
        _, rts, _ = parse_routes_text(text, packaged=False, sources=srcs)
        self.assertEqual(list(rts), ["mock/beta"])


class SeedTest(unittest.TestCase):
    """The checkout's routes.toml is data; these assertions are the only place its content is checked in code."""

    def test_seed_loads_and_carries_the_five_sources_and_no_oauth_routes(self):
        text = (REPO / "routes.toml").read_text(encoding="utf-8")
        srcs, rts, _ = routes(text)
        self.assertEqual(set(srcs), {"openrouter", "omlx", "omlx@morty", "omlx-tp2", "exo"})
        import re
        self.assertEqual(len(rts), len(re.findall(r'^\[routes\."[^"]+"\]$', text, re.M)))   # every declared block parses; the count lives in the file (D5)
        self.assertGreaterEqual(len(rts), 6)
        self.assertEqual(sum(r.source == "openrouter" for r in rts.values()), 4)
        self.assertEqual(sum(r.source == "omlx" for r in rts.values()), 2)
        self.assertFalse(any("chatgpt" in n or "xai" in n or "gpt-" in n for n in rts))  # D3
        for r in rts.values():
            if r.source == "openrouter":
                self.assertIsNotNone(r.price, r.name)
                self.assertEqual(r.limits.confidence, "provider", r.name)
        for s in srcs.values():
            if s.discover:
                self.assertIsNotNone(s.limits, f"{s.name}: a discoverable source must declare limits or its routes are uncapped")
        self.assertEqual(srcs["omlx"].limits.confidence, "configured")
        self.assertEqual(srcs["openrouter"].auth_env, "OPENROUTER_API_KEY")


if __name__ == "__main__":
    unittest.main()
