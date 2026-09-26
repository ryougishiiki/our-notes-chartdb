#!/usr/bin/env bash
# chartdb CI entrypoint.  Everything the workflow does lives here so the whole
# pipeline can be reproduced locally with:  bash ci/run.sh
set -euo pipefail

SERVER="${SERVER:-intl}"
WORK=".chartdb-cache"
OUT="dist"

echo "== install =="
python -m pip install --quiet -r requirements.txt
npm ci --no-audit --no-fund

echo "== build correctness oracle (pinned external parser) =="
node tools/oracle/build.mjs

echo "== build chart DB =="
export PYTHONPATH=src
python -m chartdb build --server "$SERVER" --all --out "$OUT" --workdir "$WORK"

echo "== release gate =="
python tools/ci_gate.py "$OUT"

if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
  echo "not running inside GitHub Actions -> build + gate only, not publishing"
  exit 0
fi

HAS_CHANGES=$(python -c "import json;print('1' if json.load(open('$OUT/gate.json'))['hasChanges'] else '0')")
DB_VERSION=$(python -c "import json;print(json.load(open('$OUT/gate.json'))['databaseVersion'])")
PACK=$(python -c "import json;print(json.load(open('$OUT/gate.json'))['packFile'])")

if [ "$HAS_CHANGES" != "1" ]; then
  echo "no new/changed/removed charts -> not publishing a release"
  exit 0
fi

LATEST=$(git ls-remote --tags origin 'chartdb-v*' \
  | sed -E 's#.*refs/tags/chartdb-v([0-9]+)$#\1#' \
  | sort -n | tail -1)
TAG="chartdb-v$(( ${LATEST:-0} + 1 ))"

echo "== publish $TAG =="
gh release create "$TAG" \
  --title "$TAG" \
  --notes "Chart DB \`$DB_VERSION\` (protocolVersion 1, chartSchemaVersion chartdoc/1).

Source-derived normalized chart data only: no APK, no game bundles, no audio,
no images, no video, no keys.  Source revision, pack size and sha256 are in
\`manifest.json\`." \
  "$OUT/manifest.json" "$OUT/$PACK"