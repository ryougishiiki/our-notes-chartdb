# Activate the CI workflow (no token needed)

GitHub refuses to create/update `.github/workflows/*` from a token without the
`workflow` scope. This repository was published with a `repo`-only token, so the
workflow file currently lives here at `ci/chartdb.yml`.

You do **not** need a new token or any command line. GitHub's web editor is an
interactive session and is allowed to create workflow files.

## Recommended: move the file in the browser (3 clicks)

1. Open
   <https://github.com/ryougishiiki/our-notes-chartdb/edit/main/ci/chartdb.yml>
2. Click the **file name box** at the top (it shows `ci/chartdb.yml`) and change
   it to exactly:

   ```
   .github/workflows/chartdb.yml
   ```

3. Click **Commit changes…** → **Commit changes**.

That creates the workflow at its active path. (If GitHub keeps `ci/chartdb.yml`
behind, that is harmless; you can delete it with the 🗑 icon on the file page.)

## Then run it once

Open <https://github.com/ryougishiiki/our-notes-chartdb/actions> and click
**chartdb → Run workflow → Run workflow**.

The workflow will build the whole chart DB, run every gate, and publish a
release tagged `chartdb-v<N>`. After that it also runs nightly at 03:17 UTC.

## Alternative: grant the scope and push

```sh
gh auth refresh -s workflow      # browser confirmation, one-time
mkdir -p .github/workflows
git mv ci/chartdb.yml .github/workflows/chartdb.yml
git commit -m "ci: activate chartdb workflow"
git push
```

## What the workflow does

```
checkout -> python 3.13 + node 20 -> pip install -r requirements.txt + npm ci
         -> node tools/oracle/build.mjs        (pins the external parser)
         -> restore incremental state          (.chartdb-cache)
         -> python -m chartdb build --all --out dist
         -> python tools/ci_gate.py dist       (hard gates; blocks on failure)
         -> upload artifact
         -> tag chartdb-v<N> + publish release (manifest.json + *.tar.zst)
         -> save incremental state
```

No secrets are required: the game CDN, the Addressables catalog and the public
Master mirror are all unauthenticated.
