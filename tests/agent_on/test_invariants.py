from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import MOCK_ROUTES, REPO, Sandbox  # noqa: E402

import unittest  # noqa: E402

from agent_on.invariants import REGISTRY, build_context, evaluate, skipped_ids  # noqa: E402
from agent_on.schemas.knowledge import validate_file, validate_record  # noqa: E402
from agent_on.schemas.errors import SchemaError  # noqa: E402
from agent_on.schemas.observed import empty_route, empty_source  # noqa: E402
from agent_on.state import update_observed  # noqa: E402

EXPECTED_IDS = {"route.served", "route.unique", "source.limits.propagated", "limits.declared_vs_observed", "copy.single",
                "credential.not_in_child_env", "harness.env.clean", "gate.no_silent_skip", "gate.mock.ephemeral",
                "test.names.derived", "knowledge.typed", "schema.complete", "cost.not_copied", "qualification.current"}
BASE = "http://127.0.0.1:1"
TS = "2026-09-07T00:00:00Z"


def one(paths, inv_id, route=None):
    res = [r for r in evaluate(build_context(paths), ids=[inv_id], route=route)]
    return res if route is None and REGISTRY[inv_id].per_route else res[0]


class RegistryTest(unittest.TestCase):
    def test_the_fourteen_predicates_are_registered_with_statement_and_fix(self):
        self.assertEqual(set(REGISTRY), EXPECTED_IDS)
        for inv in REGISTRY.values():
            self.assertTrue(inv.statement and inv.fix, inv.id)

    def test_a_skip_is_reported_as_skip_and_listed(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            res = evaluate(build_context(sb.paths))
            self.assertTrue(all(r.result in ("pass", "fail", "skip") for r in res))
            served = [r for r in res if r.id == "route.served"]
            self.assertTrue(served and all(r.result == "skip" for r in served))     # never synced → skip, not pass
            self.assertIn("route.served:mock/alpha", skipped_ids(res))
            self.assertEqual([r.result for r in res if r.id == "credential.not_in_child_env"], ["pass"])

    def test_broken_routes_toml_fails_every_route_predicate_by_name(self):
        with Sandbox('version = 1\n[sources.mock]\nbase_url = "http://x"\n[routes."mock/m"]\naliases=["z"]\n[routes."mock/n"]\naliases=["z"]\n') as sb:
            res = {r.id: r for r in evaluate(build_context(sb.paths), ids=["route.unique", "route.served"])}
            self.assertEqual(res["route.unique"].result, "fail")            # F4
            self.assertIn("routes.unique", res["route.unique"].reason)
            self.assertEqual(res["route.served"].result, "fail")


class F1ServedTest(unittest.TestCase):
    def test_planted_dead_wire_model_fails_and_live_passes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            def plant(doc):   # exactly what `sync` (Task 8) writes: the source's catalog and each route's served flag
                doc["sources"]["mock"] = {**empty_source(), "reachable": True, "checked": TS, "catalog": ["alpha"], "catalog_count": 1}
                doc["routes"]["mock/alpha"] = {**empty_route(), "served": True, "checked": TS}
                doc["routes"]["mock/gone"] = {**empty_route(), "served": False, "checked": TS}
            update_observed(sb.paths, plant)
            res = {r.subject: r for r in one(sb.paths, "route.served")}
            self.assertEqual(res["mock/alpha"].result, "pass")
            self.assertEqual(res["mock/gone"].result, "fail")
            self.assertIn("not in mock catalog", res["mock/gone"].reason)
            self.assertIn("sync", res["mock/gone"].fix)
            self.assertEqual(res["paid/vendor/model-x"].result, "skip")          # its source was never probed


class F2F12LimitsTest(unittest.TestCase):
    def test_globs_are_rejected_at_load_and_a_limitless_source_fails_its_discovered_routes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE).replace('[routes."mock/gone"]', '[routes."mock/Qwen*"]')) as sb:
            r = one(sb.paths, "source.limits.propagated")
            self.assertEqual(r[0].result, "fail")
            self.assertIn("no_globs", r[0].reason)
        text = 'version = 1\n[sources.mock]\nbase_url = "http://x"\ndiscover = true\n'
        with Sandbox(text) as sb:
            sb.paths.state.mkdir()
            sb.paths.discovered_toml.write_text('version = 1\n[routes."mock/found"]\n', encoding="utf-8")
            r = {x.subject: x for x in one(sb.paths, "source.limits.propagated")}
            self.assertEqual(r["mock/found"].result, "fail")
            self.assertIn("declares none", r["mock/found"].reason)
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            r = {x.subject: x for x in one(sb.paths, "source.limits.propagated")}
            self.assertEqual(r["mock/alpha"].result, "pass")                     # inherited
            self.assertIn("inherit", r["mock/alpha"].reason)
            self.assertEqual(r["paid/vendor/model-x"].result, "pass")            # its own

    def test_declared_above_observed_fails_and_verified_is_the_stronger_bound(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            def plant(doc):   # declared 8192 (inherited from the source) against an advertised 4096
                doc["routes"]["mock/alpha"] = empty_route()
                doc["routes"]["mock/alpha"]["limits"]["input"].update({"advertised": 4096, "checked": TS})
            update_observed(sb.paths, plant)
            r = {x.subject: x for x in one(sb.paths, "limits.declared_vs_observed")}
            self.assertEqual(r["mock/alpha"].result, "fail")
            self.assertIn("8192 > advertised 4096", r["mock/alpha"].reason)
            self.assertEqual(r["paid/vendor/model-x"].result, "skip")            # nothing observed for it → skip
            update_observed(sb.paths, lambda doc: doc["routes"]["mock/alpha"]["limits"]["input"].__setitem__("verified", 16384))
            r = {x.subject: x for x in one(sb.paths, "limits.declared_vs_observed")}
            self.assertEqual(r["mock/alpha"].result, "pass")
            self.assertIn("verified", r["mock/alpha"].reason)


class F7F8CopyTest(unittest.TestCase):
    def test_shim_elsewhere_fails_and_shim_here_passes(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            self.assertEqual(one(sb.paths, "copy.single").result, "skip")            # no shim yet
            shim = sb.paths.shim
            shim.parent.mkdir(parents=True)
            shim.symlink_to(sb.root / "elsewhere" / "agent-on")
            r = one(sb.paths, "copy.single")
            self.assertEqual(r.result, "fail")
            self.assertIn("elsewhere", r.reason)
            shim.unlink()
            (sb.paths.checkout / "bin").mkdir()
            (sb.paths.checkout / "bin" / "agent-on").write_text("#!/bin/sh\n")
            shim.symlink_to(sb.paths.checkout / "bin" / "agent-on")
            self.assertEqual(one(sb.paths, "copy.single").result, "pass")


class HarnessEnvTest(unittest.TestCase):
    def write(self, sb, settings):
        p = sb.paths.home / ".claude" / "settings.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(settings), encoding="utf-8")

    def test_denylist_tier_name_and_literal_model(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "skip")
            self.write(sb, {"model": "fable", "env": {"EDITOR": "vim"}})
            r = one(sb.paths, "harness.env.clean")
            self.assertEqual(r.result, "pass")
            self.assertIn("tier name", r.reason)                                   # rev 6: this machine sets model: fable
            self.write(sb, {"model": "claude-opus-5"})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"env": {"ANTHROPIC_BASE_URL": "http://x"}})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"env": {"HTTPS_PROXY": "http://x"}})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"env": {"https_proxy": "http://x"}})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"env": {"anthropic_base_url": "http://x"}})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")
            self.write(sb, {"apiKeyHelper": "cat x"})
            self.assertEqual(one(sb.paths, "harness.env.clean").result, "fail")


class GateRecordTest(unittest.TestCase):
    def gate_run(self, **over):
        base = {"at": "2026-09-07T00:00:00Z", "commit": "x", "result": "pass", "tests": 1, "verifiers": {"declared": [], "ran": []},
                "invariants": {"route.served:mock/alpha": "skip"}, "skipped": ["route.served:mock/alpha"], "skipped_reasons": [], "mock_port": 51873}
        return {**base, **over}

    def test_silent_skip_and_unrun_verifier_fail(self):  # F6
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "gate.no_silent_skip").result, "skip")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run()))
            self.assertEqual(one(sb.paths, "gate.no_silent_skip").result, "pass")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(skipped=[])))
            self.assertEqual(one(sb.paths, "gate.no_silent_skip").result, "fail")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(verifiers={"declared": ["fidelity"], "ran": []})))
            r = one(sb.paths, "gate.no_silent_skip")
            self.assertEqual(r.result, "fail")
            self.assertIn("fidelity", r.reason)

    def test_mock_on_a_configured_port_fails(self):  # F9
        with Sandbox(MOCK_ROUTES.format(base="http://127.0.0.1:8000")) as sb:
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(mock_port=8000)))
            self.assertEqual(one(sb.paths, "gate.mock.ephemeral").result, "fail")
            update_observed(sb.paths, lambda d: d.__setitem__("last_gate_run", self.gate_run(mock_port=51873)))
            self.assertEqual(one(sb.paths, "gate.mock.ephemeral").result, "pass")


class TreeLintTest(unittest.TestCase):
    def test_undeclared_route_literal_in_the_tree_fails(self):  # F5
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            (sb.paths.checkout / "agent_on").mkdir()
            (sb.paths.checkout / "agent_on" / "x.py").write_text('NAME = "mock/alpha"\n', encoding="utf-8")
            self.assertEqual(one(sb.paths, "test.names.derived").result, "pass")
            (sb.paths.checkout / "agent_on" / "x.py").write_text('NAME = "mock/does-not-exist"\n', encoding="utf-8")
            r = one(sb.paths, "test.names.derived")
            self.assertEqual(r.result, "fail")
            self.assertIn("does-not-exist", r.reason)

    def test_the_real_tree_has_no_undeclared_route_literals(self):
        from agent_on.paths import default_paths
        self.assertEqual(one(default_paths(), "test.names.derived").result, "pass")

    def test_schema_rules_registry_is_complete_and_alive(self):  # F14
        from agent_on.paths import default_paths
        r = one(default_paths(), "schema.complete")
        self.assertEqual(r.result, "pass", r.reason)
        with Sandbox(MOCK_ROUTES.format(base=BASE), tree=None) as sb:
            (sb.paths.checkout / "agent_on").mkdir()
            (sb.paths.checkout / "agent_on" / "y.py").write_text('raise SchemaError("not.a.rule", "x")\n', encoding="utf-8")
            r = one(sb.paths, "schema.complete")
            self.assertEqual(r.result, "fail")
            self.assertIn("not.a.rule", r.reason)


class KnowledgeTest(unittest.TestCase):
    def test_records_are_typed(self):  # F13
        validate_record("traps", {"id": "traps-01J", "ts": "2026-09-07T00:00:00Z", "trap": "t", "mechanism": "m", "avoid": "a",
                                  "evidence": "e", "found_by": "f", "applies_to": ["sync"]})
        with self.assertRaises(SchemaError):
            validate_record("traps", {"id": "traps-01J", "ts": "x", "trap": "t"})
        with self.assertRaises(SchemaError):
            validate_record("observations", {"id": "observations-1", "ts": "x", "route": "r", "kind": "vibes", "values": {}, "evidence": "e"})
        with self.assertRaises(SchemaError):
            validate_record("decisions", {"id": "wrong-1", "ts": "x", "decision": "d", "rationale": "r", "by": "b"})
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "knowledge.typed").result, "skip")
            k = sb.paths.checkout / "knowledge"
            k.mkdir()
            (k / "decisions.jsonl").write_text('{"id": "decisions-1", "ts": "2026-09-07T00:00:00Z", "decision": "d", "rationale": "r", "by": "b"}\nnot json\n', encoding="utf-8")
            r = one(sb.paths, "knowledge.typed")
            self.assertEqual(r.result, "fail")
            self.assertIn("decisions.jsonl:2", r.reason)
            self.assertEqual(len(validate_file(k / "decisions.jsonl")), 1)

        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            k = sb.paths.checkout / "knowledge"
            k.mkdir()
            (k / "decisions.jsonl").write_text(
                '{"id": "decisions-1", "ts": "2026-09-07T00:00:00Z", "decision": "d", "rationale": "r", "by": "b"}\n'
                '{"id": "decisions-1", "ts": "2026-09-07T00:00:00Z", "decision": "d", "rationale": "r", "by": "b"}\n',
                encoding="utf-8")
            r = one(sb.paths, "knowledge.typed")
            self.assertEqual(r.result, "fail")
            self.assertIn("duplicate id", r.reason)


class CostAndQualificationTest(unittest.TestCase):
    def test_claude_cost_figure_in_observed_fails(self):  # F11
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            self.assertEqual(one(sb.paths, "cost.not_copied").result, "pass")
            sb.paths.state.mkdir(parents=True, exist_ok=True)
            bad = {"version": 1, "copy": None, "sources": {}, "routes": {}, "last_check": None, "last_gate_run": None, "spend": {"x": {"total_cost_usd": 0.24}}}
            sb.paths.observed_json.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(SchemaError):
                update_observed(sb.paths, lambda d: None)                          # the schema refuses it at the door

    def test_qualification_goes_stale_when_the_effective_config_changes(self):  # F10
        text = MOCK_ROUTES.format(base=BASE)
        with Sandbox(text) as sb:
            r = {x.subject: x for x in one(sb.paths, "qualification.current")}
            self.assertEqual(r["mock/alpha"].result, "skip")
            ctx = build_context(sb.paths)
            sha = ctx.routes.effective_sha(ctx.routes.routes["mock/alpha"])
            def plant(doc):
                doc["routes"]["mock/alpha"] = empty_route()
                doc["routes"]["mock/alpha"]["last_qualification"] = {"pass": True, "at": "2026-09-07T00:00:00Z", "gates": {}, "thinking_block_seen": False, "completed": True,
                    "fingerprint": {"effective_route_sha": sha, "wire_model": "alpha", "source_identity": None, "claude_code": None}}
            update_observed(sb.paths, plant)
            self.assertEqual({x.subject: x.result for x in one(sb.paths, "qualification.current")}["mock/alpha"], "pass")
            sb.paths.routes_toml.write_text(text.replace("input = 8192", "input = 4096"), encoding="utf-8")   # inherited limit changed
            r = {x.subject: x for x in one(sb.paths, "qualification.current")}
            self.assertEqual(r["mock/alpha"].result, "fail")
            self.assertIn("effective_route_sha", r["mock/alpha"].reason)

    def test_corrupt_observed_json_reaches_the_error_branch_instead_of_crashing(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            sb.paths.state.mkdir(parents=True, exist_ok=True)
            sb.paths.observed_json.write_text("not json at all", encoding="utf-8")
            ctx = build_context(sb.paths)
            self.assertIn("_error", ctx.observed)
            r = one(sb.paths, "cost.not_copied")
            self.assertEqual(r.result, "fail")
            self.assertIn(ctx.observed["_error"], r.reason)
            self.assertEqual(one(sb.paths, "route.unique").result, "pass")           # routes still load


class CredentialTest(unittest.TestCase):
    def test_no_source_credential_reaches_any_route_child_env(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            r = one(sb.paths, "credential.not_in_child_env")
            self.assertEqual(r.result, "pass")
            self.assertIn("MOCK_PAID_KEY", r.reason)


class ClaudeCodeVersionTest(unittest.TestCase):
    # F-fix 5: claude_code_version() used shutil.which("claude") unconditionally, so a baseline measured with
    # AGENT_ON_CLAUDE_BIN was tagged with whatever real `claude` happened to be on PATH. It takes the binary the
    # launch will use.
    FAKE = str(Path(__file__).resolve().parent / "fakeclaude.py")

    def test_an_explicit_binary_is_used_instead_of_path(self):
        from agent_on.invariants import claude_code_version
        self.assertEqual(claude_code_version(self.FAKE), "0.0.0")

    def test_build_context_threads_the_binary_through(self):
        with Sandbox(MOCK_ROUTES.format(base=BASE)) as sb:
            ctx = build_context(sb.paths, with_claude_code=True, claude_bin=self.FAKE)
            self.assertEqual(ctx.claude_code, "0.0.0")


if __name__ == "__main__":
    unittest.main()
