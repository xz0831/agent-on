"""Shared fixtures for the agent-on tests."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_on.paths import Paths  # noqa: E402

# Two sources on one mock server: `mock` is oMLX-shaped and discoverable, `paid` is OpenRouter-shaped and keyed.
MOCK_ROUTES = """version = 1

[sources.mock]
base_url = "{base}"
catalog = "/v1/models"
discover = true
billing = "free"

[sources.mock.limits]
input = 8192
output = 2048
confidence = "owned-policy"
source = "test fixture"

[sources.paid]
base_url = "{base}"
auth_env = "MOCK_PAID_KEY"
catalog = "{base}/api/v1/models"
backend = "openrouter"
billing = "metered"

[routes."mock/alpha"]
aliases = ["a"]

[routes."mock/gone"]

[routes."paid/vendor/model-x"]
wire_model = "vendor/model-x"
aliases = ["x"]

[routes."paid/vendor/model-x".limits]
input = 100000
output = 4000
confidence = "provider"
source = "fixture"

[routes."paid/vendor/model-x".price]
input_usd_per_mtok = 1.0
output_usd_per_mtok = 2.0
cache_read_usd_per_mtok = 0.1
source = "fixture"
"""


class Sandbox:
    """A throwaway checkout (routes.toml only) + state root + home. `tree` defaults to the real code tree so
    the tree lints (schema.complete, test.names.derived) scan real code; pass tree=None to lint the sandbox."""

    def __init__(self, routes_text: str, *, tree: Path | None = REPO):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "co").mkdir()
        (root / "home").mkdir()
        (root / "co" / "routes.toml").write_text(routes_text, encoding="utf-8")
        self.root = root
        self.paths = Paths(checkout=root / "co", state=root / "state", home=root / "home",
                           tree=tree if tree is not None else root / "co")

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
