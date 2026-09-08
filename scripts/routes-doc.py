#!/usr/bin/env python3
"""Write (or --check) docs/ROUTES.md from routes.toml. Standard library only; run from anywhere."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_on.docs import render_routes_doc  # noqa: E402
from agent_on.paths import default_paths  # noqa: E402
from agent_on.schemas.routes import load_routes  # noqa: E402


def main(argv: list[str]) -> int:
    paths = default_paths()
    page = paths.checkout / "docs" / "ROUTES.md"
    text = render_routes_doc(load_routes(paths))
    if "--check" in argv:
        current = page.read_text(encoding="utf-8") if page.exists() else None
        if current == text:
            print(f"{page}: current")
            return 0
        print(f"{page}: stale — run scripts/routes-doc.py", file=sys.stderr)
        return 1
    page.parent.mkdir(exist_ok=True)
    page.write_text(text, encoding="utf-8")
    print(f"wrote {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
