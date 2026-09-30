"""Render release notes from a validated Chart DB manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _chart_list(label: str, values: list[str]) -> list[str]:
    if not values:
        return [f"{label}: none"]
    shown = values[:40]
    suffix = f" (and {len(values) - len(shown)} more)" if len(values) > len(shown) else ""
    return [f"{label}:", *(f"- `{key}`" for key in shown), *([f"- ...{suffix}"] if suffix else [])]


def render(manifest: dict) -> str:
    source = manifest.get("source", {})
    incremental = manifest.get("incremental", {})
    new = incremental.get("newCharts") or []
    changed = incremental.get("changedCharts") or []
    removed = incremental.get("removedCharts") or []
    unchanged = incremental.get("unchangedCharts", 0)
    pack = manifest.get("pack", {})

    lines = [
        f"Chart DB `{manifest.get('databaseVersion')}` (protocolVersion {manifest.get('protocolVersion')}, chartSchemaVersion {manifest.get('chartSchemaVersion')}).",
        "",
        f"Catalog version floor: `{source.get('catalogVersionConfiguredFloor')}`",
        f"Catalog version resolved: `{source.get('catalogVersionResolved')}` (source: `{source.get('catalogVersionSource')}`)",
        f"Catalog official hash: `{source.get('catalogOfficialHash')}`",
        f"Catalog SHA-256: `{source.get('catalogSha256')}`",
        f"Master revision: `{source.get('masterRevision')}`",
        "",
        "Charts:",
        f"+ new: {len(new)}",
        f"~ changed: {len(changed)}",
        f"- removed: {len(removed)}",
        f"= unchanged: {unchanged}",
        "",
        f"Total charts: {manifest.get('chartCount')}",
        f"Pack SHA-256: `{pack.get('sha256')}`",
        "",
    ]
    lines.extend(_chart_list("New charts", new))
    lines.append("")
    lines.extend(_chart_list("Changed charts", changed))
    lines.append("")
    lines.extend(_chart_list("Removed charts", removed))
    lines.extend(
        [
            "",
            "Source-derived normalized chart data only: no APK, game bundles, audio, images, video, or keys.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python tools/release_notes.py MANIFEST OUTPUT", file=sys.stderr)
        return 2
    manifest = json.loads(Path(sys.argv[1]).read_text("utf-8"))
    Path(sys.argv[2]).write_text(render(manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
