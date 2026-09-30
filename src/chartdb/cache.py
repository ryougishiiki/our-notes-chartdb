"""Upstream-aware caches for the catalog and downloadable chart bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .addressables import parse_catalog
from .config import ServerConfig
from .discover import Discovery, BundleRef, discover
from .hashing import sha256_bytes
from .http import HttpError, fetch_bytes


@dataclass(frozen=True)
class FreshCatalog:
    data: bytes
    discovery: Discovery
    official_catalog_hash: str
    cached_official_catalog_hash: str | None
    catalog_sha256: str
    action: str


def catalog_cache_path(workdir: Path, version: str) -> Path:
    """Keep each versioned catalog and its hash metadata in a separate namespace."""
    return workdir / "catalog" / version / "catalog.bin"


def load_fresh_catalog(config: ServerConfig, cache_file: Path) -> FreshCatalog:
    """Check the official hash on every call and reuse only a matching cache."""
    remote_hash = _fetch_official_catalog_hash(config.catalog_hash_url)
    metadata_file = cache_file.with_name(cache_file.name + ".meta.json")
    metadata = _read_metadata(metadata_file)
    cached_hash = metadata.get("officialCatalogHash") if metadata else None
    cached_sha256 = metadata.get("catalogSha256") if metadata else None

    if (
        isinstance(cached_hash, str)
        and cached_hash == remote_hash
        and isinstance(cached_sha256, str)
        and cache_file.is_file()
    ):
        data = cache_file.read_bytes()
        digest = sha256_bytes(data)
        if digest == cached_sha256:
            try:
                result = _parse_catalog(data, config)
            except Exception:
                # A damaged cache must not turn a successful remote hash check
                # into a stale or permanently unusable catalog.
                pass
            else:
                return FreshCatalog(
                    data=data,
                    discovery=result,
                    official_catalog_hash=remote_hash,
                    cached_official_catalog_hash=cached_hash,
                    catalog_sha256=digest,
                    action="REUSED",
                )

    data = fetch_bytes(config.catalog_bin_url)
    parsed = _parse_catalog(data, config)
    digest = sha256_bytes(data)

    # Replace the data before its metadata. If interrupted between writes, the
    # next run sees a mismatch and downloads again instead of trusting stale data.
    _atomic_write(cache_file, data)
    _atomic_write(
        metadata_file,
        json.dumps(
            {"officialCatalogHash": remote_hash, "catalogSha256": digest},
            sort_keys=True,
            indent=2,
        ).encode("utf-8"),
    )
    return FreshCatalog(
        data=data,
        discovery=parsed,
        official_catalog_hash=remote_hash,
        cached_official_catalog_hash=cached_hash if isinstance(cached_hash, str) else None,
        catalog_sha256=digest,
        action="REFRESHED",
    )


def cached_bundle_bytes(bundle: BundleRef, cache_file: Path) -> bytes:
    """Reuse a bundle only when its persisted catalog identity still matches."""
    metadata_file = cache_file.with_name(cache_file.name + ".meta.json")
    identity = {
        "primaryKey": bundle.primary_key,
        "bundleName": bundle.bundle_name,
        "bundleSize": bundle.bundle_size,
        "bundleHash": bundle.bundle_hash,
        "remoteUrl": bundle.remote_url,
    }
    metadata = _read_metadata(metadata_file)
    if cache_file.is_file() and metadata and metadata.get("identity") == identity:
        data = cache_file.read_bytes()
        if sha256_bytes(data) == metadata.get("downloadSha256"):
            return data

    data = fetch_bytes(bundle.remote_url)
    _atomic_write(cache_file, data)
    _atomic_write(
        metadata_file,
        json.dumps(
            {"identity": identity, "downloadSha256": sha256_bytes(data)},
            sort_keys=True,
            indent=2,
        ).encode("utf-8"),
    )
    return data


def _fetch_official_catalog_hash(url: str) -> str:
    raw = fetch_bytes(url)
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise HttpError(f"official catalog hash at {url} is not ASCII") from error
    if not value:
        raise HttpError(f"official catalog hash at {url} is empty")
    return value


def _read_metadata(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_catalog(data: bytes, config: ServerConfig) -> Discovery:
    return discover(parse_catalog(data, config.remote_root, config.remote_root))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
