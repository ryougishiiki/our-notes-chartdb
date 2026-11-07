from __future__ import annotations

import pytest

from chartdb.release_tag import format_game_version, tag_for_manifest


def _manifest(resource_version: str, *, authority: str = "official") -> dict:
    return {
        "source": {
            "masterAuthority": authority,
            "masterResourceVersion": resource_version,
        }
    }


def test_release_tag_uses_game_version_and_revision_suffix():
    assert tag_for_manifest(_manifest("1.0.3.abcd1234")) == "chartdb-v1.0.3-abcd1234"
    assert tag_for_manifest(_manifest("1.0.1.600.7c4e9a2b")) == "chartdb-v1.0.1.600-7c4e9a2b"


def test_existing_hyphenated_and_numeric_versions_are_preserved():
    assert format_game_version("1.0.3-xxxx") == "1.0.3-xxxx"
    assert format_game_version("1.0.0.201") == "1.0.0.201"


def test_release_tag_requires_official_master_version():
    with pytest.raises(ValueError, match="official Master"):
        tag_for_manifest(_manifest("1.0.3.abcd1234", authority="derived"))


def test_corrected_export_gets_unique_tag_without_game_version_change():
    manifest = _manifest("1.1.0.301.3d7eee12")
    manifest["index"] = {"sha256": "a" * 64}
    assert tag_for_manifest(manifest) == "chartdb-v1.1.0.301-3d7eee12-db-aaaaaaaaaaaa"
    manifest["index"]["sha256"] = "b" * 64
    assert tag_for_manifest(manifest).endswith("-db-bbbbbbbbbbbb")
    manifest["index"]["sha256"] = "bad"
    with pytest.raises(ValueError, match="digest"):
        tag_for_manifest(manifest)


@pytest.mark.parametrize("resource_version", ["", "../1.0.3", "1.0..3", "1.0.3."])
def test_unsafe_versions_are_rejected(resource_version: str):
    with pytest.raises(ValueError):
        tag_for_manifest(_manifest(resource_version))
