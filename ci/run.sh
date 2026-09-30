#!/usr/bin/env bash
# chartdb build, validation and site-generation entrypoint.
# Release publication and Pages deployment are separate workflow jobs.
set -euo pipefail

SERVER="${SERVER:-intl}"
WORK=".chartdb-cache"
OUT="dist"

echo "sourceEventId=${CHARTDB_SOURCE_EVENT_ID:-none}"

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

echo "== generate static statistics site =="
python tools/build_site.py --dist "$OUT" --template site/index.template.html --output "$OUT/site"
python tools/release_notes.py "$OUT/manifest.json" "$OUT/release-notes.md"

if [ "${GITHUB_ACTIONS:-}" != "true" ]; then
  echo "not running inside GitHub Actions -> build, gate and site generated locally"
  exit 0
fi

echo "build, validation, gate and site generation completed"
