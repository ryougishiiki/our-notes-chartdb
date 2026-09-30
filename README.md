# chartdb — Our Notes chart database producer

Builds a **versioned, downloadable chart database** for *BanG Dream! Our Notes*
from the official CDN, so that a client only needs:

```
musicId + difficulty  ->  ChartDocument
```

The Android side never has to understand Addressables, UnityFS, AES,
AssetBundles, TextAssets or the game's resource paths.

## Pipeline

```
official Addressables catalog  (catalog_<version>.bin)
        |
        +-- MusicScore bundle discovery        src/chartdb/discover.py
        |
Master (musicId -> scoreId -> chartFile)        src/chartdb/master.py
        |
        +-- bundle download (cached by primary key)
        +-- header decryption (AES-CTR, 16 KiB)  src/chartdb/crypto.py
        +-- Unity parse (UnityPy)                src/chartdb/unity.py
        +-- m_Container -> TextAsset -> SS JSON
        +-- SS parse                             src/chartdb/ss.py
        +-- normalize                            src/chartdb/normalize.py
        +-- validation gates                     src/chartdb/validate.py
        +-- pack + manifest                      src/chartdb/db.py
```

## Output

`dist/`

| file | contents |
| --- | --- |
| `manifest.json` | protocol/schema versions, source revision, counts, pack hash, validation report |
| `chartdb-<version>.tar.zst` | `index.json` + `charts/<musicId>/<difficulty>.json` |

`index.json` supports the runtime query directly:

```json
{"musicId":100001,"difficulty":"expert","difficultyIndex":3,"scoreId":10000103,
 "chartFile":"0001/0001_03","sourceSha256":"...","normalizedSha256":"...",
 "path":"charts/100001/expert.json"}
```

## Run

```sh
pip install -r requirements.txt
npm install --no-save esbuild
node tools/oracle/build.mjs          # builds the correctness oracle (pinned parser)

PYTHONPATH=src python -m chartdb build --server intl --music 100001 \
    --difficulty easy --difficulty expert --out dist
PYTHONPATH=src python -m chartdb build --server intl --all --out dist
```

## ChartDocument v1 (`chartdoc/1`)

```
identity  { musicId, difficulty, difficultyIndex, scoreId }
source    { server, catalogVersion, catalogHash, masterSource, chartFile,
            assetPath, ssVersion, sourceSha256, bundle{...} }
timing    { bpm[], signature[], tickConverter }
notes[]   { type, container, tick, timeMs, bar, position, positionAuto,
            size, critical, visible, direction, ease, alpha, node[], raw }
metadata  { title, playLevel, fieldConfidence, validation, gates }
```

**Confirmed / preserved split.** Every field carries a confidence label in
`metadata.fieldConfidence`:

| label | meaning | examples |
| --- | --- | --- |
| `CONFIRMED` | 1:1 with the raw SS JSON, or verified by the audited parser + real data | `tick`, `position`, `size`, `critical`, `visible`, `type`, `direction`, `node`, `timeMs`, `bpm`, `signature` |
| `CANDIDATE` | value is preserved verbatim, semantics not fully pinned | `ease`, `alpha`, `skill`, `fever`, `call` |

`raw` always keeps the original SS note object verbatim, so nothing is lost and
a future schema can be derived without re-downloading.

`notes[]` is in **source order** (`SsScore.Notes` order, i.e. authored order).
Container notes (`long`/`guide`) have `container: true`, `tick: null` and carry
their geometry in `node[]`.

## Master source

`musicId`/`scoreId` come from *Master data*, never from bundle filenames. CI
defaults to the public official Master version service and CDN. It validates the
gRPC response and `MasterManifest.json`, then fetches and verifies only
`MasterLiveMusic.bin` and `MasterLiveMusicScore.bin` before decrypting them.
An official Master failure stops the build; CI does not silently use a mirror.

| `--master-source` | implementation | authority |
| --- | --- | --- |
| `official` (default) | official version service, manifest, and Master CDN files | `official` |
| `mirror` | Haneoka's public song index and detail rows | `derived`; explicit diagnostic use only |
| `apk` | Master tables decrypted from a supplied asset-pack APK | official game data supplied by the operator |

An official build makes a one-request Haneoka comparison for song/chart counts
and ID differences. It cannot affect whether the build succeeds. Set
`--master-source mirror` explicitly to perform a derived build and look for the
`MASTER_AUTHORITY=derived` log marker.

The manifest records official master version, resourceVersion, manifest hash,
catalog floor/resolved version/hash, table hashes, and mirror comparison status.
`masterRevision` remains our content hash of the rows consumed, while
`masterVersion` and `masterResourceVersion` are the official service values.

Whatever the source, every master-referenced `chartFile` must resolve to a
`live_assets_live_musicscore_<...>.bundle` in the official catalog; a master
reference without a bundle is a hard failure. MusicScore bundles that no Master
row references (`dev`/`preview`/tests) are reported as `unreferenced` and are
never published.

## Validation gates

Hard gates (`fail` blocks the release):

* payload is valid JSON; `score` / `events` / `notes` structure valid
* every leaf note has an integer `tick >= 0`; `pos` present or `"auto"`
* every BPM event `> 0`
* `sourceSha256` reproducible from the extracted TextAsset
* master mapping unique: `(musicId,difficulty)`, `scoreId`, `chartFile`

### Combo count (report-only by default)

Each chart records:

```
masterFullComboCount   # MasterLiveMusicScore._fullComboCount
calculatedComboCount   # pinned cassiopeia parser, judged notes
comboCountDelta        # calculatedComboCount - masterFullComboCount
```

* the oracle is `cassiopeia-plugin-our-notes` at a **pinned commit**, re-parsing
  the same SS JSON;
* real data: **219/336 charts match exactly, 117/336 differ** (delta −17…+48);
* the authored notes are identical between the two implementations — only the
  *generated* `Combo` notes (reconstructed every `30000/bpm` ms inside slides)
  differ, so the mismatch is a limitation of the combo-note model, **not** of the
  extracted/parsed chart data;
* therefore **no release depends on `calculatedComboCount == masterFullComboCount`**;
* `--oracle-policy report` (default) records and summarises it;
  `--oracle-policy strict` promotes a mismatch to a blocking failure.

## `complete` vs `coverage`

Two independent axes, never conflated into one boolean:

| field | meaning |
| --- | --- |
| `validation.completeForMasterSnapshot` | every chart the **Master** references resolved and passed its gates |
| `coverage.catalogAligned` | every chart-named MusicScore bundle in the **catalog** is referenced by the Master snapshot |
| `coverage.catalogNamedWithoutMaster` | count of chart-named bundles with no Master row (currently `0047/0047_00..03`) |

A chart-named bundle with no Master reference is **never** guessed into a
`musicId`; it stays unreferenced and is remapped automatically once the Master
snapshot catches up.

## CI

`.github/workflows/chartdb.yml` runs on `repository_dispatch` for
`our-notes-chart-update`, `workflow_dispatch`, and nightly `schedule` at
03:17 UTC. A dispatch logs `sourceEventId` and runs the existing full upstream
build, freshness checks, validation, and release gate. Chart data in the
payload is ignored. Test dispatches may set `dryRun: true` to run the build
without uploading release files, creating a Release, or deploying Pages. All
build and site generation live in [`ci/run.sh`](ci/run.sh), so validated data
and reports can also be reproduced locally with `bash ci/run.sh`.

```
build (all charts) -> hard gates -> report + release gate
                    ├─ chart changes -> database Release
                    └─ successful main build -> GitHub Pages deploy
```

* incremental: `.chartdb-cache/state.json` holds `(musicId,difficulty) -> sourceSha256`;
  a release is only published when there are new/changed/removed charts.
* freshness: the official Master `resourceVersion` anchors catalog resolution;
  bounded local probing continues from that anchor. A version is published only
  when both its official `.hash` and `.bin` files exist.
* Master: the manifest SHA-256, declared file size, and file SHA-256 are checked
  before decrypting. Master version-only changes appear in diagnostics and the
  Pages report even when no chart Release is needed.
* bundles: cached payloads are reused only while their catalog identity matches;
  a new or changed identity triggers a download.
* atomicity: the release is created only after the whole build + all gates pass.
* Pages: every successful build on `main` deploys the generated statistics
  site, regardless of whether the incremental gate found changes. The Pages job
  depends on the build job, not the conditional Release job.
* tag: `chartdb-v<N>`; the real source revision is in `manifest.json`.
* release notes: catalog version/hash, Master revision, new/changed/removed and
  unchanged counts, chart keys, total charts, and pack SHA-256.

CI installs pinned Python dependencies with up to three attempts, runs the unit
tests, then builds and validates the database. A clean diff skips Release
creation but still produces and deploys the current statistics site.

## Statistics site

[`site/index.template.html`](site/index.template.html) is rendered by
[`tools/build_site.py`](tools/build_site.py) from the same validated `dist/pack`
used for the database Release. The build writes a self-contained
`dist/site/index.html` and `dist/site/chartdb_spectra_stats.csv`; the HTML
embeds the data, so the hosted page does not need a server-side API.

To enable hosting once, open **Settings → Pages → Build and deployment → Source**
and select **GitHub Actions**. After that, each successful `main` build deploys
the site, including nightly runs with no database diff. Database Releases
remain limited to runs with new, changed, or removed charts.

## Legal / scope

Publishes **source-derived normalized chart data only**. No APK, no game
bundles, no audio, no images, no video, no AES keys. CI downloads are temporary
and cached, never committed. This repository ends at
`musicId + difficulty -> ChartDocument`; it deliberately contains no LSPosed,
runtime reading, input or scheduling logic.
