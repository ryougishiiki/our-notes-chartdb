#!/usr/bin/env python3
"""Print the game-version-based GitHub Release tag for a validated manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartdb.release_tag import tag_for_manifest  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/release_tag.py MANIFEST", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        print(tag_for_manifest(manifest))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"release tag: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
