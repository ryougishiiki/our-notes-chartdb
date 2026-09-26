# CI workflow (not yet active)

GitHub refuses to create/update `.github/workflows/*` from a token without the
`workflow` scope. This repository was published with a token that only had
`repo`, so the workflow lives here instead of in its active location.

To enable automated updates:

```sh
# 1. grant the workflow scope to your token
gh auth refresh -s workflow      # or create a PAT with repo + workflow

# 2. activate the workflow
mkdir -p .github/workflows
git mv ci/chartdb.yml .github/workflows/chartdb.yml
git commit -m "ci: activate chartdb workflow"
git push
```

After that the workflow runs nightly (`schedule`) and on demand
(`workflow_dispatch`) and publishes `chartdb-v<N>` releases.
