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

## Master source (important)

`musicId`/`scoreId` come from *Master data*, never from bundle filenames. Two
implementations exist:

| `--master-source` | implementation | status |
| --- | --- | --- |
| `apk` | `MasterLiveMusic` + `MasterLiveMusicScore` decrypted from the asset-pack APK (`assets/Master/Master*.bin`, Rijndael-CBC + gzip) | **official authority**; requires the APK |
| `mirror` (default) | `https://haneoka.org/api/v1/servers/<server>/songs[/<id>]`, which exposes the same MasterLiveMusic row (`_easyID`…) and the resolved chart file | publicly reachable **derived** mirror |

The official path needs `split_UnityDataAssetPack.apk`, which is discovered via a
private game-service version endpoint; it is not on the public CDN. Point CI at
an APK (`--apk`) to use the authoritative source.

Provenance is recorded explicitly in `manifest.json`:

```json
"masterSource": "haneoka-public-mirror",
"masterAuthority": "derived",
"masterRevision": "<sha256 over the consumed Master rows>",
"masterTables": {
  "MasterLiveMusic": "<sha256>",
  "MasterLiveMusicScore": "<sha256>"
},
"officialMasterSource": "TODO"
```

`masterRevision` is **our own content hash of the rows we actually consumed**,
not a game-published version string.  When an official Master endpoint becomes
available (`officialMasterSource`), it replaces the mirror as a higher-priority
provider without touching the downstream `chartdoc/1` protocol.

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

`.github/workflows/chartdb.yml` is active: `workflow_dispatch` + nightly
`schedule` at 03:17 UTC. All build logic lives in [`ci/run.sh`](ci/run.sh), so
the workflow is a thin wrapper and the whole pipeline is reproducible locally
with `bash ci/run.sh` (it stops before publishing outside Actions).

```
build (all charts) -> hard gates -> release gate -> artifact -> release
```

* incremental: `.chartdb-cache/state.json` holds `(musicId,difficulty) -> sourceSha256`;
  a release is only published when there are new/changed/removed charts.
* atomicity: the release is created only after the whole build + all gates pass.
* tag: `chartdb-v<N>`; the real source revision is in `manifest.json`.

## Legal / scope

Publishes **source-derived normalized chart data only**. No APK, no game
bundles, no audio, no images, no video, no AES keys. CI downloads are temporary
and cached, never committed. This repository ends at
`musicId + difficulty -> ChartDocument`; it deliberately contains no LSPosed,
runtime reading, input or scheduling logic.
