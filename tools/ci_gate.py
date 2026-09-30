"""CI gate: decide release readiness from a produced manifest."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from chartdb.state import has_changes


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    manifest_path = dist / "manifest.json"
    if not manifest_path.is_file():
        print("GATE FAIL: manifest.json is missing")
        return 1
    manifest = json.loads(manifest_path.read_text("utf-8"))
    validation = manifest.get("validation", {})
    failed = validation.get("failedCharts") or []
    complete = bool(validation.get("completeForMasterSnapshot"))
    incremental = manifest.get("incremental", {})
    source = manifest.get("source", {})

    print("---- chartdb report ----")
    print("databaseVersion:", manifest.get("databaseVersion"))
    print("chartSchemaVersion:", manifest.get("chartSchemaVersion"))
    print("chartCount:", manifest.get("chartCount"))
    print("source:", json.dumps(source, ensure_ascii=False))
    freshness_complete = bool(
        source.get("catalogVersionConfiguredFloor")
        and source.get("catalogVersionResolved")
        and source.get("catalogVersion") == source.get("catalogVersionResolved")
        and source.get("catalogVersionSource") in {"probe", "config"}
        and source.get("catalogOfficialHash")
        and source.get("officialCatalogHash") == source.get("catalogOfficialHash")
        and source.get("catalogSha256")
        and source.get("catalogAction") in {"REUSED", "REFRESHED"}
        and source.get("masterRevision")
    )
    if freshness_complete:
        print(
            "latest upstream checked: catalogAction={} masterSource={} masterRevision={}".format(
                source["catalogAction"],
                source.get("masterSource"),
                source.get("masterRevision"),
            )
        )
    else:
        print("GATE FAIL: catalog or Master freshness metadata is incomplete")
    print("catalogAligned:", (manifest.get("coverage") or {}).get("catalogAligned"))
    print("coverage:", json.dumps(manifest.get("coverage", {}), ensure_ascii=False))
    print("incremental:", json.dumps({k: v for k, v in incremental.items() if k.endswith("Count")}))
    print("pack:", json.dumps(manifest.get("pack", {}), ensure_ascii=False))
    print("failedCharts:", len(failed))
    print(
        "comboCount: exact={} mismatch={} unknown={} (policy={})".format(
            validation.get("comboCountExact"),
            validation.get("comboCountMismatch"),
            validation.get("comboCountUnknown"),
            validation.get("comboCountPolicy"),
        )
    )

    if not freshness_complete or not complete or failed:
        print(f"GATE FAIL: {len(failed)} chart(s) failed; refusing to publish")
        for entry in failed[:20]:
            print("  -", entry)
        return 1

    changed = has_changes(incremental)
    (dist / "gate.json").write_text(
        json.dumps(
            {
                "releaseReady": True,
                "hasChanges": changed,
                "databaseVersion": manifest.get("databaseVersion"),
                "packFile": (manifest.get("pack") or {}).get("file"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as handle:
            handle.write(f"HAS_CHANGES={'1' if changed else '0'}\n")
            handle.write(f"DB_VERSION={manifest.get('databaseVersion')}\n")
    print("HAS_CHANGES:", "1" if changed else "0")
    print("GATE PASS" if changed else "GATE PASS (no changes -> no release)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
