# Repository agent guidance

## Cross-version compatibility policy

> Do not infer chart-semantic incompatibility from game version changes alone.
>
> Reuse previously validated chart semantics, compilation rules, and compatible runtime recipes whenever the relevant contracts remain unchanged.
>
> A generated target inventory describes the recipes bundled in a particular build; it is not a permanent project-wide version support policy.
>
> Never require a full manual chart revalidation solely because the game version changed.

## Applying the policy

- Determine chart changes from official Catalog/Master identity and per-chart source/normalized content hashes, not from the game version string alone.
- Preserve content-hash validation, source provenance, incremental builds, immutable snapshots, and historical database records.
- The manifest's chart inventory describes one source-data snapshot; it is not an OnSSM runtime recipe inventory or a game-version support list.
- Rebuild or publish only when the existing data-diff and validation rules identify changed inputs or outputs; unchanged charts keep their validated results.
- This repository produces normalized chart data. Do not infer changes to GestureCompiler judgement semantics from a game-version change or chart-resource version alone.
- Prefer automated fixture and regression comparisons; never demand full manual chart revalidation solely because the game version changed.
