"""Chart DB pack + manifest writer.

Nothing about AES / AssetBundles / Unity ever enters the release: the pack only
holds ChatDocument JSON plus an index and a manifest.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from .hashing import canonical_json, sha256_bytes

PROTOCOL_VERSION = 1
PACK_FORMAT = "tar.zst"


class DatabaseBuilder:
    def __init__(self, chart_schema: str):
        self.chart_schema = chart_schema
        self._entries: list[dict] = []

    def add(self, document: dict, source_sha256: str) -> dict:
        identity = document["identity"]
        normalized = canonical_json(document)
        entry = {
            "musicId": identity["musicId"],
            "difficulty": identity["difficulty"],
            "difficultyIndex": identity["difficultyIndex"],
            "scoreId": identity["scoreId"],
            "chartFile": document["source"]["chartFile"],
            "sourceSha256": source_sha256,
            "normalizedSha256": sha256_bytes(normalized),
            "path": f"charts/{identity['musicId']}/{identity['difficulty']}.json",
            "document": document,
        }
        self._entries.append(entry)
        return entry

    @property
    def count(self) -> int:
        return len(self._entries)

    def index_document(self) -> dict:
        entries = [
            {key: value for key, value in entry.items() if key != "document"}
            for entry in self._entries
        ]
        entries.sort(key=lambda item: (item["musicId"], item["difficultyIndex"]))
        return {
            "schema": "chartindex/1",
            "protocolVersion": PROTOCOL_VERSION,
            "chartSchemaVersion": self.chart_schema,
            "chartCount": len(entries),
            "charts": entries,
        }

    def write(self, out_dir: Path, source_meta: dict, validation_meta: dict, incremental: dict, database_version: str) -> dict:
        out_dir.mkdir(parents=True, exist_ok=True)
        staging = out_dir / "pack"
        import shutil

        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        index = self.index_document()
        index_bytes = canonical_json(index)
        (staging / "index.json").write_bytes(index_bytes)
        for entry in self._entries:
            target = staging / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(canonical_json(entry["document"]))

        pack_name = f"chartdb-{database_version}.{PACK_FORMAT}"
        pack_bytes = _pack_directory(staging, pack_name)
        pack_path = out_dir / pack_name
        pack_path.write_bytes(pack_bytes)

        manifest = {
            "protocolVersion": PROTOCOL_VERSION,
            "databaseVersion": database_version,
            "chartSchemaVersion": self.chart_schema,
            "generatorVersion": _generator_version(),
            "source": source_meta,
            "chartCount": len(self._entries),
            "index": {
                "file": "index.json",
                "size": len(index_bytes),
                "sha256": sha256_bytes(index_bytes),
            },
            "pack": {
                "file": pack_name,
                "format": PACK_FORMAT,
                "size": len(pack_bytes),
                "sha256": sha256_bytes(pack_bytes),
            },
            "validation": validation_meta,
            "incremental": incremental,
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest


def _generator_version() -> str:
    from . import __version__

    return f"chartdb/{__version__}"


def _pack_directory(directory: Path, name: str) -> bytes:
    # Fail closed: never silently emit a different container than the manifest
    # claims.  A missing dependency must break the build, not change the format.
    try:
        import zstandard
    except ImportError as error:  # pragma: no cover
        raise RuntimeError(
            "zstandard is required to emit the tar.zst pack; refusing to fall back"
        ) from error
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                _add_reproducible(archive, path, str(path.relative_to(directory)))
    return zstandard.ZstdCompressor(level=19).compress(buffer.getvalue())


def _add_reproducible(archive: tarfile.TarFile, path: Path, arcname: str) -> None:
    """Add one file with normalised metadata so the pack is byte-reproducible.

    ``tarfile.add`` records the file's mtime/uid/gid, which makes an otherwise
    identical pack differ between runs.  Reproducibility is a release
    requirement (sha256 is the client's integrity anchor).
    """
    info = archive.gettarinfo(str(path), arcname=arcname)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o644
    with path.open("rb") as handle:
        archive.addfile(info, handle)
