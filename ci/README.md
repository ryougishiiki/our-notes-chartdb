# CI (active)

`.github/workflows/chartdb.yml` is live: nightly `schedule` (03:17 UTC) plus
`workflow_dispatch`.

**All build logic is in `ci/run.sh`**, so the workflow is a ~25 line wrapper.
Reproduce the whole pipeline locally with:

```sh
bash ci/run.sh          # build + gates only; publishing requires GitHub Actions
```

`ci/chartdb.yml` is kept as the template in case the workflow file ever has to
be recreated from the browser.

## Steps

1. Open <https://github.com/ryougishiiki/our-notes-chartdb/actions>
2. Click the small link **"set up a workflow yourself"** (top right).
   The editor opens with the path `.github/workflows/main.yml` already filled in.
3. Select everything in the editor (Ctrl+A) and delete it.
4. Paste the contents of [`ci/chartdb.yml`](chartdb.yml).
5. Click **Commit changes…** → **Commit changes**.

Then open the **Actions** tab, choose **chartdb** → **Run workflow**.

Direct alternative (path pre-filled, then paste + commit):
<https://github.com/ryougishiiki/our-notes-chartdb/new/main?filename=.github%2Fworkflows%2Fchartdb.yml>

## What runs

`ci/run.sh` (all logic, reproducible locally):

```
pip install -r requirements-ci.txt   # build + pinned test dependencies; retried up to 3 times
python -m pytest tests -q
npm ci
node tools/oracle/build.mjs          # pinned external parser
python -m chartdb build --all        # -> dist/
python tools/ci_gate.py dist         # hard gates; writes dist/gate.json
gh release create chartdb-v<N>       # only inside Actions, only if changed
```

Every build checks the official catalog `.hash` URL before looking at the cached
catalog binary. It also fetches the latest Master song list and song details.
Catalog/Master freshness metadata is a hard release gate. No secrets are
required: the game CDN, the Addressables catalog and the public Master mirror
are unauthenticated. `GH_TOKEN` is the automatic `${{ github.token }}` with
`contents: write`.
