from __future__ import annotations

import json

import pytest

from chartdb import cache
from chartdb.config import resolve_server
from chartdb.discover import BundleRef, Discovery
from chartdb.hashing import sha256_bytes
from chartdb.http import HttpError


def _seed_catalog(path, data: bytes, official_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.with_name(path.name + ".meta.json").write_text(
        json.dumps(
            {
                "officialCatalogHash": official_hash,
                "catalogSha256": sha256_bytes(data),
            }
        ),
        encoding="utf-8",
    )


def test_cached_catalog_with_same_official_hash_is_reused(tmp_path, monkeypatch):
    config = resolve_server("intl")
    catalog_path = tmp_path / "catalog.bin"
    data = b"cached catalog"
    _seed_catalog(catalog_path, data, "official-1")
    parsed = Discovery(charts={}, unreferenced=[])
    calls = []

    def fetch(url):
        calls.append(url)
        if url == config.catalog_hash_url:
            return b"official-1\n"
        raise AssertionError("catalog binary should be reused")

    monkeypatch.setattr(cache, "fetch_bytes", fetch)
    monkeypatch.setattr(cache, "_parse_catalog", lambda _data, _config: parsed)

    result = cache.load_fresh_catalog(config, catalog_path)

    assert calls == [config.catalog_hash_url]
    assert result.data == data
    assert result.discovery is parsed
    assert result.cached_official_catalog_hash == "official-1"
    assert result.catalog_sha256 == sha256_bytes(data)
    assert result.action == "REUSED"


def test_cached_catalog_with_changed_official_hash_is_downloaded(tmp_path, monkeypatch):
    config = resolve_server("intl")
    catalog_path = tmp_path / "catalog.bin"
    _seed_catalog(catalog_path, b"old catalog", "official-1")
    new_data = b"new catalog"
    calls = []

    def fetch(url):
        calls.append(url)
        return b"official-2" if url == config.catalog_hash_url else new_data

    monkeypatch.setattr(cache, "fetch_bytes", fetch)
    monkeypatch.setattr(
        cache,
        "_parse_catalog",
        lambda data, _config: Discovery(charts={"parsed": data}, unreferenced=[]),
    )

    result = cache.load_fresh_catalog(config, catalog_path)

    assert calls == [config.catalog_hash_url, config.catalog_bin_url]
    assert result.data == new_data
    assert result.official_catalog_hash == "official-2"
    assert result.cached_official_catalog_hash == "official-1"
    assert result.catalog_sha256 == sha256_bytes(new_data)
    assert result.action == "REFRESHED"
    assert catalog_path.read_bytes() == new_data
    metadata = json.loads(catalog_path.with_name(catalog_path.name + ".meta.json").read_text())
    assert metadata == {
        "officialCatalogHash": "official-2",
        "catalogSha256": sha256_bytes(new_data),
    }


def test_missing_catalog_cache_downloads_after_hash_check(tmp_path, monkeypatch):
    config = resolve_server("intl")
    catalog_path = tmp_path / "catalog.bin"
    new_data = b"first catalog"
    calls = []

    def fetch(url):
        calls.append(url)
        return b"official-first" if url == config.catalog_hash_url else new_data

    monkeypatch.setattr(cache, "fetch_bytes", fetch)
    monkeypatch.setattr(cache, "_parse_catalog", lambda _data, _config: Discovery({}, []))

    result = cache.load_fresh_catalog(config, catalog_path)

    assert calls == [config.catalog_hash_url, config.catalog_bin_url]
    assert result.action == "REFRESHED"
    assert result.cached_official_catalog_hash is None
    assert catalog_path.read_bytes() == new_data


def test_unavailable_official_hash_fails_without_using_cache(tmp_path, monkeypatch):
    config = resolve_server("intl")
    catalog_path = tmp_path / "catalog.bin"
    _seed_catalog(catalog_path, b"stale catalog", "official-old")
    calls = []

    def fetch(url):
        calls.append(url)
        raise HttpError("offline")

    monkeypatch.setattr(cache, "fetch_bytes", fetch)

    with pytest.raises(HttpError):
        cache.load_fresh_catalog(config, catalog_path)

    assert calls == [config.catalog_hash_url]
    assert catalog_path.read_bytes() == b"stale catalog"


def test_invalid_download_does_not_replace_cached_catalog(tmp_path, monkeypatch):
    config = resolve_server("intl")
    catalog_path = tmp_path / "catalog.bin"
    _seed_catalog(catalog_path, b"old catalog", "official-1")

    monkeypatch.setattr(
        cache,
        "fetch_bytes",
        lambda url: b"official-2" if url == config.catalog_hash_url else b"invalid new catalog",
    )

    def reject(_data, _config):
        raise ValueError("not a valid catalog")

    monkeypatch.setattr(cache, "_parse_catalog", reject)

    with pytest.raises(ValueError, match="not a valid catalog"):
        cache.load_fresh_catalog(config, catalog_path)

    assert catalog_path.read_bytes() == b"old catalog"


def test_bundle_cache_reuses_only_matching_catalog_identity(tmp_path, monkeypatch):
    bundle = BundleRef(
        primary_key="live_assets_live_musicscore_0001_0001_03_abcd.bundle",
        remote_url="https://cdn.example/chart.bundle",
        bundle_name="chart.bundle",
        bundle_size=10,
        bundle_hash="hash-1",
        chart_file="0001/0001_03",
    )
    cache_path = tmp_path / "bundles" / bundle.primary_key
    downloads = []

    def fetch(url):
        downloads.append(url)
        return f"payload-{len(downloads)}".encode()

    monkeypatch.setattr(cache, "fetch_bytes", fetch)

    first = cache.cached_bundle_bytes(bundle, cache_path)
    reused = cache.cached_bundle_bytes(bundle, cache_path)
    changed = cache.cached_bundle_bytes(
        BundleRef(**{**bundle.__dict__, "bundle_hash": "hash-2"}), cache_path
    )

    assert first == b"payload-1"
    assert reused == first
    assert changed == b"payload-2"
    assert downloads == [bundle.remote_url, bundle.remote_url]
