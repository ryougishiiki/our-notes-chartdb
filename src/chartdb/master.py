"""Authoritative song/difficulty/chart mapping.

``musicId`` and ``scoreId`` MUST come from Master data, never from bundle
filenames.  Two providers exist:

* ``ApkMasterSource`` - the official path: decrypt ``MasterLiveMusic`` /
  ``MasterLiveMusicScore`` out of the asset-pack APK.  ``authority=official``.
* ``HaneokaMirrorMasterSource`` - a public *derived* mirror of the same tables.
  ``authority=derived``.  Used until an official endpoint is available.

Both return a :class:`MasterSnapshot` whose ``revision`` is a content hash of
the Master rows we actually consumed - it is **our own source revision**, not a
game-published version string.

The difficulty list is data (see ``config/servers.json`` semantics): adding a
difficulty is a config change, not a code change.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import ServerConfig
from .crypto import decrypt_master_table
from .hashing import canonical_json, sha256_bytes
from .http import fetch_json

MASTER_PREFIX = "assets/Master/"
ASSET_PACK_NAMES = {"split_UnityDataAssetPack.apk", "UnityDataAssetPack.apk"}

DEFAULT_DIFFICULTIES: tuple[dict, ...] = (
    {"index": 0, "name": "easy", "field": "_easyID"},
    {"index": 1, "name": "normal", "field": "_normalID"},
    {"index": 2, "name": "hard", "field": "_hardID"},
    {"index": 3, "name": "expert", "field": "_expertID"},
    {"index": 4, "name": "special", "field": "_specialID"},
)


@dataclass(frozen=True)
class ChartRef:
    music_id: int
    difficulty_index: int
    difficulty: str
    score_id: int
    chart_file: str
    title: str
    full_combo_count: int | None
    play_level: int | None
    master_source: str


@dataclass(frozen=True)
class MasterSnapshot:
    source: str
    authority: str  # "official" | "derived"
    revision: str  # content hash of the consumed Master rows
    tables: dict[str, str]  # table name -> sha256 of its rows
    refs: tuple[ChartRef, ...]

    @property
    def master_live_music_sha256(self) -> str:
        return self.tables.get("MasterLiveMusic", "")

    @property
    def master_live_music_score_sha256(self) -> str:
        return self.tables.get("MasterLiveMusicScore", "")


class MasterSource(Protocol):
    source: str
    authority: str

    def snapshot(self, music_ids: set[int] | None = None) -> MasterSnapshot:
        ...


def _table_sha256(rows: object) -> str:
    return sha256_bytes(canonical_json(rows))


def make_snapshot(
    *, source: str, authority: str, music_rows: list[dict], score_rows: list[dict], refs: list[ChartRef]
) -> MasterSnapshot:
    tables = {
        "MasterLiveMusic": _table_sha256(music_rows),
        "MasterLiveMusicScore": _table_sha256(score_rows),
    }
    revision = sha256_bytes(canonical_json(tables))
    return MasterSnapshot(
        source=source,
        authority=authority,
        revision=revision,
        tables=tables,
        refs=tuple(refs),
    )


def build_chart_refs(
    music_rows: list[dict],
    score_rows: list[dict],
    *,
    master_source: str,
    difficulties: tuple[dict, ...] = DEFAULT_DIFFICULTIES,
    titles: dict[int, str] | None = None,
) -> list[ChartRef]:
    scores = {int(row.get("_id") or 0): row for row in score_rows}
    refs: list[ChartRef] = []
    for row in music_rows:
        music_id = int(row.get("_id") or 0)
        if not music_id:
            continue
        for entry in difficulties:
            score_id = int(row.get(entry["field"]) or 0)
            if not score_id:
                continue
            score = scores.get(score_id)
            if not score:
                continue
            chart_file = str(score.get("_musicScoreTextFileName") or "").strip()
            if not chart_file:
                continue
            full_combo = score.get("_fullComboCount")
            play_level = score.get("_musicScoreLevel")
            refs.append(
                ChartRef(
                    music_id=music_id,
                    difficulty_index=int(entry["index"]),
                    difficulty=str(entry["name"]),
                    score_id=score_id,
                    chart_file=chart_file,
                    title=(titles or {}).get(music_id, ""),
                    full_combo_count=int(full_combo) if isinstance(full_combo, (int, float)) else None,
                    play_level=int(play_level) if isinstance(play_level, (int, float)) else None,
                    master_source=master_source,
                )
            )
    refs.sort(key=lambda ref: (ref.music_id, ref.difficulty_index))
    return refs


class ApkMasterSource:
    """Official Master tables, decrypted from the asset-pack APK."""

    source = "official-apk"
    authority = "official"

    def __init__(self, package: Path, config: ServerConfig):
        self.package = Path(package)
        self.config = config

    def _tables(self) -> dict[str, dict]:
        tables: dict[str, bytes] = {}
        with zipfile.ZipFile(self.package) as outer:
            members = outer.namelist()
            if any(name.startswith(MASTER_PREFIX) for name in members):
                source_zip = outer
                close = False
            else:
                nested = [n for n in members if Path(n).name in ASSET_PACK_NAMES]
                if len(nested) != 1:
                    raise ValueError(
                        "package must contain exactly one UnityDataAssetPack split; "
                        f"found {len(nested)}"
                    )
                import tempfile

                tmp = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
                tmp.write(outer.read(nested[0]))
                tmp.close()
                source_zip = zipfile.ZipFile(tmp.name)
                close = True
            try:
                bins = [
                    name
                    for name in source_zip.namelist()
                    if name.startswith(MASTER_PREFIX)
                    and Path(name).name.startswith("Master")
                    and name.endswith(".bin")
                ]
                if not bins:
                    raise ValueError("package contains no encrypted Master tables")
                for name in sorted(bins):
                    tables[Path(name).stem] = source_zip.read(name)
            finally:
                if close:
                    source_zip.close()
        return {name: decrypt_master_table(raw, self.config.master_crypto) for name, raw in tables.items()}

    def snapshot(self, music_ids: set[int] | None = None) -> MasterSnapshot:
        tables = self._tables()
        for required in ("MasterLiveMusic", "MasterLiveMusicScore"):
            if required not in tables:
                raise ValueError(f"asset pack is missing {required}")
        music_rows = tables["MasterLiveMusic"]["_allData"]
        score_rows = tables["MasterLiveMusicScore"]["_allData"]
        refs = build_chart_refs(music_rows, score_rows, master_source=self.source)
        if music_ids is not None:
            refs = [ref for ref in refs if ref.music_id in music_ids]
        return make_snapshot(
            source=self.source,
            authority=self.authority,
            music_rows=music_rows,
            score_rows=score_rows,
            refs=refs,
        )


class HaneokaMirrorMasterSource:
    """Public *derived* mirror of the same Master tables (authority=derived)."""

    source = "haneoka-public-mirror"
    authority = "derived"

    def __init__(self, config: ServerConfig):
        self.config = config
        self.base = config.master_mirror["baseUrl"].rstrip("/")
        self.prefix = config.master_mirror["apiPrefix"]

    def _songs(self) -> dict[str, dict]:
        document = fetch_json(f"{self.base}{self.prefix}/songs")
        if not isinstance(document, dict):
            raise ValueError("mirror songs endpoint did not return an object")
        return document

    def _detail_raw(self, key: str) -> dict | None:
        try:
            document = fetch_json(f"{self.base}{self.prefix}/songs/{key}")
        except Exception:
            return None
        raw = document.get("raw") if isinstance(document, dict) else None
        return raw if isinstance(raw, dict) else None

    def snapshot(self, music_ids: set[int] | None = None) -> MasterSnapshot:
        from concurrent.futures import ThreadPoolExecutor

        songs = self._songs()
        selected: list[tuple[str, dict]] = []
        for key, song in songs.items():
            if not isinstance(song, dict):
                continue
            music_id = int(song.get("musicId") or key)
            if music_ids is not None and music_id not in music_ids:
                continue
            selected.append((key, song))

        # The list endpoint omits the MasterLiveMusic row, so the score ids need
        # one detail request per song.  Fetch concurrently.
        needs_detail = [key for key, song in selected if not isinstance(song.get("raw"), dict)]
        details: dict[str, dict | None] = {}
        if needs_detail:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for key, raw in zip(needs_detail, pool.map(self._detail_raw, needs_detail)):
                    details[key] = raw

        # Rebuild the MasterLiveMusic / MasterLiveMusicScore rows we consumed so
        # the snapshot revision is a content hash of the real input.
        music_rows: list[dict] = []
        score_by_id: dict[int, dict] = {}
        titles: dict[int, str] = {}
        for key, song in selected:
            music_id = int(song.get("musicId") or key)
            raw = song.get("raw")
            if not isinstance(raw, dict):
                raw = details.get(key)
            if not isinstance(raw, dict):
                continue
            music_rows.append(raw)
            title = song.get("musicTitle")
            if isinstance(title, list) and title:
                titles[music_id] = str(title[0])
            for entry in song.get("difficulty") or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("difficultyName") or "")
                field = next((d["field"] for d in DEFAULT_DIFFICULTIES if d["name"] == name), None)
                if field is None:
                    continue
                score_id = int(raw.get(field) or 0)
                chart_file = (
                    str(entry.get("file") or "").split("/Live/MusicScore/")[-1].removesuffix(".bytes")
                )
                if not score_id or not chart_file:
                    continue
                score_by_id[score_id] = {
                    "_id": score_id,
                    "_musicScoreTextFileName": chart_file,
                    "_fullComboCount": entry.get("noteCount"),
                    "_musicScoreLevel": entry.get("playLevel"),
                }
        music_rows.sort(key=lambda row: int(row.get("_id") or 0))
        score_rows = [score_by_id[key] for key in sorted(score_by_id)]
        refs = build_chart_refs(
            music_rows, score_rows, master_source=self.source, titles=titles
        )
        return make_snapshot(
            source=self.source,
            authority=self.authority,
            music_rows=music_rows,
            score_rows=score_rows,
            refs=refs,
        )
