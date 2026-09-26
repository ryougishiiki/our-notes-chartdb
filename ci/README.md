# Activate CI (one click, one paste — no token, no file name typing)

GitHub refuses to create `.github/workflows/*` from a token without the
`workflow` scope. This repository was published with a `repo`-only token, so the
workflow template lives at `ci/chartdb.yml`.

**All build logic is in `ci/run.sh`**, so the workflow itself is only ~25 lines
and can be created from the browser (an interactive session is allowed to create
workflow files).

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
pip install -r requirements.txt
npm ci
node tools/oracle/build.mjs          # pinned external parser
python -m chartdb build --all        # -> dist/
python tools/ci_gate.py dist         # hard gates; writes dist/gate.json
gh release create chartdb-v<N>       # only inside Actions, only if changed
```

No secrets are required: the game CDN, the Addressables catalog and the public
Master mirror are all unauthenticated. `GH_TOKEN` is the automatic
`${{ github.token }}` with `contents: write`.
