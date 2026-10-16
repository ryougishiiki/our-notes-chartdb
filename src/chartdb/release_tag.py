"""Derive a stable GitHub Release tag from the official game resource version."""

from __future__ import annotations

from .master_protocol import is_safe_resource_version


def format_game_version(resource_version: object) -> str:
    """Format an official resource version for a readable release tag.

    The service currently reports versions such as
    ``1.0.1.600.7c4e9a2b``. When a dotted token has a non-numeric revision
    suffix, render its final separator as a hyphen: ``1.0.1.600-7c4e9a2b``.
    Existing hyphenated values and plain numeric versions are preserved.
    """
    if not is_safe_resource_version(resource_version):
        raise ValueError("Master resourceVersion is missing or unsafe for a release tag")
    assert isinstance(resource_version, str)
    if ".." in resource_version or resource_version.endswith("."):
        raise ValueError("Master resourceVersion cannot be represented as a Git tag")

    parts = resource_version.split(".")
    if len(parts) >= 4 and all(part.isdecimal() for part in parts[:-1]) and not parts[-1].isdecimal():
        return f"{'.'.join(parts[:-1])}-{parts[-1]}"
    return resource_version


def tag_for_manifest(manifest: object) -> str:
    """Return a ChartDB release tag, requiring official Master provenance."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("masterAuthority") != "official":
        raise ValueError("release tag requires official Master provenance")
    version = format_game_version(source.get("masterResourceVersion"))
    tag = f"chartdb-v{version}"
    if ".." in tag or tag.endswith(".") or tag.lower().endswith(".lock"):
        raise ValueError("Master resourceVersion cannot be represented as a Git tag")
    return tag
