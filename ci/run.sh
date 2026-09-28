#!/usr/bin/env bash
# chartdb CI entrypoint.  Everything the workflow does lives here so the whole
# pipeline can be reproduced locally with:  bash ci/run.sh
set -euo pipefail

SERVER="${SERVER:-intl}"
WORK=".chartdb-cache"
OUT="dist"

echo "== install Python dependencies (up to 3 attempts) =="
install_python_dependencies() {
  local attempt
  for attempt in 1 2 3; do
    echo "pip install requirements-ci.txt attempt ${attempt}/3"
    if python -m pip install --disable-pip-version-check --retries 2 -r requirements-ci.txt; then
      return 0
    fi
    if [ "$attempt" -lt 3 ]; then
      echo "pip install failed; retrying after a short delay"
      sleep "$((attempt * 5))"
    fi
  done
  echo "pip install failed after 3 attempts"
  return 1
}
install_python_dependencies

export PYTHONPATH=src
echo "== unit tests =="
python -m pytest tests -q

echo "== install Node dependencies =="
npm ci --no-audit --no-fund

echo "== build correctness oracle (pinned external parser) =="
node tools/oracle/build.mjs

echo "== build chart DB =="
python -m chartdb build --server "$SERVER" --all --out "$OUT" --workdir "$WORK"

echo "== release gate =="
python tools/ci_gate.py "$OUT"

if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
  echo "not running inside GitHub Actions -> build + gate only, not publishing"
  exit 0
fi

HAS_CHANGES=$(python -c "import json;print('1' if json.load(open('$OUT/gate.json'))['hasChanges'] else '0')")
PACK=$(python -c "import json;print(json.load(open('$OUT/gate.json'))['packFile'])")

if [ "$HAS_CHANGES" != "1" ]; then
  echo "latest upstream checked; no Chart DB changes detected"
  echo "no new/changed/removed charts -> not publishing a release"
  exit 0
fi

LATEST=$(git ls-remote --tags origin 'chartdb-v*' \
  | sed -E 's#.*refs/tags/chartdb-v([0-9]+)$#\1#' \
  | sort -n | tail -1)
TAG="chartdb-v$(( ${LATEST:-0} + 1 ))"
python tools/release_notes.py "$OUT/manifest.json" "$OUT/release-notes.md"

echo "== publish $TAG =="
gh release create "$TAG" \
  --title "$TAG" \
  --notes-file "$OUT/release-notes.md" \
  "$OUT/manifest.json" "$OUT/$PACK"
