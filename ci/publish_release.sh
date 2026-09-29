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

LATEST="$(git ls-remote --tags origin 'chartdb-v*' \
  | sed -nE 's#.*refs/tags/chartdb-v([0-9]+)$#\1#p' \
  | sort -n | tail -1)"
TAG="chartdb-v$(( ${LATEST:-0} + 1 ))"

echo "== publish $TAG =="
gh release create "$TAG" \
  --title "$TAG" \
  --notes-file "$DIST/release-notes.md" \
  "$DIST/manifest.json" "$DIST/$PACK"
