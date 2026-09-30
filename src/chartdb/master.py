"""Authoritative song/difficulty/chart mapping.

``musicId`` and ``scoreId`` MUST come from Master data, never from bundle
filenames.  Two providers exist:

* ``OfficialMasterSource`` - discover the official version, validate its
  manifest, and decrypt only ``MasterLiveMusic`` / ``MasterLiveMusicScore`` from
  the CDN. ``authority=official``.
* ``ApkMasterSource`` - an explicit local path that decrypts those tables from
  an operator-supplied asset-pack APK. ``authority=official``.
* ``HaneokaMirrorMasterSource`` - a public *derived* mirror of the same tables.
  ``authority=derived``. Used for comparison and explicit manual diagnostics.

Both return a :class:`MasterSnapshot` whose ``revision`` is a content hash of
the Master rows we actually consumed - it is **our own source revision**, not a
game-published version string.

The difficulty list is data (see ``config/servers.json`` semantics): adding a
difficulty is a config change, not a code change.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .config import ServerConfig
from .crypto import decrypt_master_table
from .hashing import canonical_json, sha256_bytes
from .http import fetch_bytes, fetch_json
from .master_protocol import MasterVersion, discover_master_version

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
    version: str = ""
    resource_version: str = ""
    manifest_sha256: str = ""
    music_ids: tuple[int, ...] = ()

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
    *,
    source: str,
    authority: str,
    music_rows: list[dict],
    score_rows: list[dict],
    refs: list[ChartRef],
    version: str = "",
    resource_version: str = "",
    manifest_sha256: str = "",
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
        version=version,
        resource_version=resource_version,
        manifest_sha256=manifest_sha256,
        music_ids=tuple(
            sorted(
                {
                    int(row.get("_id") or 0)
                    for row in music_rows
                    if isinstance(row, dict) and int(row.get("_id") or 0) > 0
                }
            )
        ),
    )


_MANIFEST_VERSION = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_MANIFEST_FILE = re.compile(r"^Master[A-Za-z0-9_]+\.bin$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_MAX_MANIFEST_FILES = 4096
_MAX_MASTER_TABLE_BYTES = 1024 * 1024 * 1024


def validate_master_manifest(value: object, expected_version: str) -> dict:
    """Validate a complete MasterManifest contract before selecting files.

    Schema and path rules follow haneoka-gakuen/haneoka's
    ``scripts/extract/master.py`` (MPL-2.0); no remote data is trusted before
    all entries have passed validation.
    """
    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    version = value.get("version")
    if (
        not isinstance(version, str)
        or version != expected_version
        or not _MANIFEST_VERSION.fullmatch(version)
        or any(segment in {".", ".."} for segment in version.split("/"))
    ):
        raise ValueError("manifest version is missing, unsafe, or does not match the official version")
    files = value.get("files")
    if not isinstance(files, list) or not files or len(files) > _MAX_MANIFEST_FILES:
        raise ValueError("manifest files must be a non-empty bounded list")
    seen: set[str] = set()
    validated: list[dict] = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest files[{index}] must be an object")
        name, digest, size = entry.get("name"), entry.get("hash"), entry.get("size")
        if not isinstance(name, str) or not _MANIFEST_FILE.fullmatch(name):
            raise ValueError(f"manifest files[{index}] has an unsafe filename")
        if name in seen:
            raise ValueError(f"manifest contains duplicate filename {name}")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"manifest has an invalid SHA-256 for {name}")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= _MAX_MASTER_TABLE_BYTES:
            raise ValueError(f"manifest has an invalid size for {name}")
        seen.add(name)
        validated.append({"name": name, "hash": digest.lower(), "size": size})
    result = dict(value)
    result["files"] = validated
    return result


def _validate_master_remote_root(root: str) -> str:
    parsed = urlsplit(root)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Master remote root has an invalid port") from error
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or "\\" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise ValueError("Master remote root must be a plain HTTPS URL")
    return root.rstrip("/")


class OfficialMasterSource:
    """Official version service and Master CDN source.

    The implementation follows the public protocol and integrity contract in
    haneoka-gakuen/haneoka ``scripts/ingest/master.py`` and
    ``scripts/extract/master.py`` (MPL-2.0). Only the required two table files
    are fetched, verified, and decrypted in memory.
    """

    source = "official-master-cdn"
    authority = "official"
    required_tables = ("MasterLiveMusic", "MasterLiveMusicScore")

    def __init__(self, config: ServerConfig):
        self.config = config

    def discover_version(self) -> MasterVersion:
        endpoint = str(self.config.master.get("versionEndpoint") or "")
        if not endpoint:
            raise ValueError("official Master version endpoint is not configured")
        return discover_master_version(endpoint)

    def snapshot(
        self,
        music_ids: set[int] | None = None,
        *,
        version_info: MasterVersion | None = None,
    ) -> MasterSnapshot:
        version_info = version_info or self.discover_version()
        root = _validate_master_remote_root(str(self.config.master.get("remoteRoot") or ""))
        manifest_url = f"{root}/{version_info.version}/MasterManifest.json"
        try:
            raw_manifest = fetch_bytes(manifest_url)
            document = json.loads(raw_manifest.decode("utf-8"))
            manifest = validate_master_manifest(document, version_info.version)
        except Exception as error:
            raise RuntimeError(f"OFFICIAL_MASTER_MANIFEST_INVALID: {error}") from error
        manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
        entries = {item["name"]: item for item in manifest["files"]}
        tables: dict[str, dict] = {}
        for table_name in self.required_tables:
            filename = f"{table_name}.bin"
            entry = entries.get(filename)
            if entry is None:
                raise RuntimeError(f"OFFICIAL_MASTER_MANIFEST_INVALID: required {filename} is missing")
            raw = fetch_bytes(f"{root}/{version_info.version}/{filename}")
            if len(raw) != entry["size"]:
                raise RuntimeError(
                    f"OFFICIAL_MASTER_TABLE_INTEGRITY_FAILED: {filename} size mismatch "
                    f"(expected {entry['size']}, got {len(raw)})"
                )
            digest = hashlib.sha256(raw).hexdigest()
            if digest != entry["hash"]:
                raise RuntimeError(f"OFFICIAL_MASTER_TABLE_INTEGRITY_FAILED: {filename} SHA-256 mismatch")
            table = decrypt_master_table(raw, self.config.master_crypto)
            if not isinstance(table, dict) or not isinstance(table.get("_allData"), list):
                raise RuntimeError(f"OFFICIAL_MASTER_TABLE_INVALID: {filename} has no _allData list")
            tables[table_name] = table

        music_rows = tables["MasterLiveMusic"]["_allData"]
        score_rows = tables["MasterLiveMusicScore"]["_allData"]
        if not music_rows or not score_rows:
            raise RuntimeError("OFFICIAL_MASTER_TABLE_INVALID: required song or score table is empty")
        refs = build_chart_refs(music_rows, score_rows, master_source=self.source)
        if music_ids is not None:
            refs = [ref for ref in refs if ref.music_id in music_ids]
        return make_snapshot(
            source=self.source,
            authority=self.authority,
            music_rows=music_rows,
            score_rows=score_rows,
            refs=refs,
            version=version_info.version,
            resource_version=version_info.resource_version,
            manifest_sha256=manifest_sha256,
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
        if not document:
            raise ValueError("mirror songs endpoint returned no songs")
        return document

    def _detail_raw(self, key: str) -> dict:
        document = fetch_json(f"{self.base}{self.prefix}/songs/{key}")
        raw = document.get("raw") if isinstance(document, dict) else None
        if not isinstance(raw, dict):
            raise ValueError(f"mirror detail endpoint returned no raw Master row for song {key}")
        return raw

    def compare(
        self,
        *,
        official_music_ids: set[int],
        official_chart_files: set[str],
    ) -> dict:
        """Compare only the mirror song index; no detail-row fan-out is needed."""
        songs = self._songs()
        mirror_music_ids: set[int] = set()
        mirror_chart_files: set[str] = set()
        mirror_chart_count = 0
        for key, song in songs.items():
            if not isinstance(song, dict):
                continue
            try:
                music_id = int(song.get("musicId") or key)
            except (TypeError, ValueError):
                continue
            mirror_music_ids.add(music_id)
            for entry in song.get("difficulty") or []:
                if not isinstance(entry, dict):
                    continue
                mirror_chart_count += 1
                value = str(entry.get("file") or "").split("/Live/MusicScore/")[-1]
                if value.endswith(".bytes"):
                    mirror_chart_files.add(value[:-6])
        official_only = sorted(official_music_ids - mirror_music_ids)
        mirror_only = sorted(mirror_music_ids - official_music_ids)
        official_chart_only = sorted(official_chart_files - mirror_chart_files)
        mirror_chart_only = sorted(mirror_chart_files - official_chart_files)
        if official_only or len(official_music_ids) > len(mirror_music_ids):
            status = "MIRROR_LAG_CONFIRMED"
        elif not mirror_only and not official_chart_only and not mirror_chart_only:
            status = "MIRROR_CURRENT"
        else:
            status = "MIRROR_DIVERGED"
        return {
            "officialSongCount": len(official_music_ids),
            "mirrorSongCount": len(mirror_music_ids),
            "officialChartCount": len(official_chart_files),
            "mirrorChartCount": mirror_chart_count,
            "officialOnlyMusicIds": official_only,
            "mirrorOnlyMusicIds": mirror_only,
            "officialOnlyChartFiles": official_chart_only,
            "mirrorOnlyChartFiles": mirror_chart_only,
            "status": status,
        }

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

        # Always refresh every detail row. The list endpoint is a discovery
        # index, not a durable Master snapshot or cache.
        needs_detail = [key for key, _song in selected]
        details: dict[str, dict] = {}
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
            raw = details.get(key)
            if not isinstance(raw, dict):
                raise ValueError(f"mirror detail snapshot is missing raw Master row for song {key}")
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
