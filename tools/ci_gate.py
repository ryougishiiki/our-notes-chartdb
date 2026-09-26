"""CI gate: decide release readiness from a produced manifest."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


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

    print("---- chartdb report ----")
    print("databaseVersion:", manifest.get("databaseVersion"))
    print("chartSchemaVersion:", manifest.get("chartSchemaVersion"))
    print("chartCount:", manifest.get("chartCount"))
    print("source:", json.dumps(manifest.get("source", {}), ensure_ascii=False))
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

    if not complete or failed:
        print(f"GATE FAIL: {len(failed)} chart(s) failed; refusing to publish")
        for entry in failed[:20]:
            print("  -", entry)
        return 1

    changed = any(
        incremental.get(key)
        for key in ("newCharts", "changedCharts", "removedCharts")
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
