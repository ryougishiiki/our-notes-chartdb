#!/usr/bin/env bash
# Publish the validated database pack when the incremental gate reports changes.
set -euo pipefail

DIST="${1:-dist}"

python - "$DIST" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

dist = Path(sys.argv[1])
gate = json.loads((dist / "gate.json").read_text(encoding="utf-8"))
manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))

if not gate.get("releaseReady") or not gate.get("hasChanges"):
    raise SystemExit("release gate does not authorize a database release")
if gate.get("databaseVersion") != manifest.get("databaseVersion"):
    raise SystemExit("gate and manifest database versions do not match")

pack_info = manifest.get("pack") or {}
pack_name = pack_info.get("file")
if not pack_name or Path(pack_name).name != pack_name:
    raise SystemExit("manifest contains an invalid pack filename")
pack_path = dist / pack_name
if not pack_path.is_file():
    raise SystemExit(f"database pack is missing: {pack_path}")
actual_sha256 = hashlib.sha256(pack_path.read_bytes()).hexdigest()
if actual_sha256 != pack_info.get("sha256"):
    raise SystemExit("database pack SHA-256 does not match manifest")
if not (dist / "release-notes.md").is_file():
    raise SystemExit("release notes are missing")
PY

PACK="$(python -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8"))["pack"]["file"])' "$DIST/manifest.json")"

TAG="$(python tools/release_tag.py "$DIST/manifest.json")"
TAG_MATCHES="$(git ls-remote --tags origin "refs/tags/$TAG")"
if [[ -n "$TAG_MATCHES" ]]; then
  gh release download "$TAG" --pattern manifest.json --output "$DIST/existing-manifest.json" --clobber
  python - "$DIST" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
expected = json.loads((root / "manifest.json").read_text("utf-8"))
existing = json.loads((root / "existing-manifest.json").read_text("utf-8"))
for key in ("pack", "index"):
    if expected[key]["sha256"] != existing[key]["sha256"]:
        raise SystemExit("existing tag contains different immutable database data")
if expected.get("contracts") != existing.get("contracts"):
    raise SystemExit("existing tag contract mismatch")
PY
  echo "verified identical export already published: $TAG"
  exit 0
fi

echo "== publish $TAG =="
gh release create "$TAG" \
  --target "$(git rev-parse HEAD)" \
  --title "$TAG" \
  --notes-file "$DIST/release-notes.md" \
  "$DIST/manifest.json" "$DIST/$PACK"
