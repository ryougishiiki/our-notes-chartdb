# Authored events and judgement timeline

These are additive `chartdoc/1` fields shipped inside every chart, in the same
verified pack/index generation as its notes. No consumer APK rebuild is needed
when songs are added or their authored events change.

## Fields

```text
timing.events:
  schema: chart-events/1
  sourceSha256: original decoded SS digest
  clock: authored-music-time-ms
  skills: [{index, tick, timeMs}]
  fever: [{index, sourceIndex, startTick, endTick, startTimeMs, endTimeMs}]
  raw: {skill: [...], fever: [[startTick,endTick],...], call: [...]}
judgements:
  schema: chart-judgements/1
  sourceSha256: same digest
  normalizer: pinned Cassiopeia plugin revision
  groups: [[timeMs, totalJudgedCount, nonGeneratedJudgedCount], ...]
  totalCount: canonical judged count
scoreTiming:
  schema: onsm-score-timing/1
  identity: same complete chart identity
  sourceSha256: same digest
  normalizer: same pinned revision
  skills: sorted skill times in ms
  groups: same triples, filtered to any [skillTime, skillTime+5000) window
```

`judgements.groups` covers the **entire song**, including outside skill windows.
Simultaneous notes share a time group but retain their total count. Generated
combo judgements count toward the total but not `nonGeneratedJudgedCount`;
skip/nonjudged events and canonical merged duplicates are excluded. It is not
a list of physical DOWN events and not a measured record of actual judgements.

The normalizer is the existing pinned Cassiopeia plugin
`46ac13fd263ead3e2dbc16825a1ab253d6690ea4`; the build oracle now exports its
timeline and complete count groups in addition to its existing count summary.
Python independently converts raw skill/fever endpoints using the audited
TickConverter port and requires exact agreement with the canonical normalizer.
Raw tick values and original source order remain available. Fever's normalized
index is ordered by start tick, and `sourceIndex` points to its original pair.

Fever endpoints are **authored boundaries/candidate release ranges**. They do
not assert that a player activated Gekisou, that a buff is currently active, or
that the exact endpoint note is inclusive in every gameplay rule. All authored
sections are retained, not just a single guessed activation. The complete
judgement groups let a future consumer find an exact boundary chord, first group
at/after the start, or last group at/before the end without guessing from skill
windows. This change does not implement early/late Gekisou input scheduling.

The judgement stream is the reconstructed **canonical model**, not a native
trace. Existing `metadata.validation.{masterFullComboCount,calculatedComboCount,
comboCountMatch,comboCountDelta}` remains authoritative for its measured
agreement with Master. The existing report-only mismatch policy is unchanged;
a published contract being internally consistent does not prove that every
native auto-combo judgement is reproduced. Consumers must retain that caveat
when using static PERFECT/JUST counts for score timing.

## Validation and update lifecycle

- Per-chart gates check schemas, exact source/identity correspondence, raw-event
  projection, converter agreement, ordered finite groups, full count equality and
  exact skill-window filtering. Stale count-only oracle binaries fail explicitly.
- Release gates require these contracts for **every chart**. `--no-oracle` remains
  available for diagnostic exports, which cannot pass the publication gate.
- The manifest advertises `contracts`, `eventContractCharts` and completeness.
- Incremental state v2 stores **normalized output hashes**. State v1 is read for
  migration; its old source hashes trigger one migration release. Changing
  exported fields can publish even if original SS/catalog/game version is unchanged.
- Identical repeated exports have identical index/pack hashes and no release.
- New tags retain the official resource version and append `-db-<indexSHA12>`.
  This permits corrections without replacing historical tags or requiring a
  game version change. The tag targets the producer commit used by the build.
- Pushes to producer code/dependencies/workflow on main trigger the same tested
  build/release pipeline as scheduled checks and dispatch events.
- OnSSM checks index **and pack** hashes and atomically installs immutable DB
  generations; a metadata-only change to the same `databaseVersion` is accepted.
  A Live already holding an old chart keeps its snapshot until the next session.

## Verification

```powershell
$env:PYTHONPATH='src'
node tools/oracle/build.mjs
python -m pytest tests -q
python -m chartdb build --server intl --all --master-source official --out dist --workdir .chartdb-cache
python tools/ci_gate.py dist
```

CI also runs the pinned-oracle integration test **after** bundling the oracle.
Tests cover converter drift, invalid endpoints/groups, generated counts, window
filtering, source mismatches, output-only changes, legacy-state migration and
same-game-version release tags. Runtime game timing is a separate user task.
