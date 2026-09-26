"""Unity AssetBundle access.

Parsing is delegated to UnityPy 1.25.x, the implementation demonstrated on real
Our Notes ``Unity 6000.3.12f1`` MusicScore bundles.  We only add header
decryption, fail-closed format checking, and the ``m_Container`` -> TextAsset
projection.  Nothing here assumes a fixed Unity version.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import Iterator

import UnityPy

from .config import ServerConfig
from .crypto import UNITY_SIGNATURE, decrypt_bundle_header


@dataclass(frozen=True)
class TextAssetEntry:
    container_path: str
    name: str
    payload: bytes
    path_id: int
    cab: str


def _text_payload(data: object) -> bytes:
    value = None
    for attribute in ("m_Script", "script", "text"):
        candidate = getattr(data, attribute, None)
        if candidate not in (None, b"", ""):
            value = candidate
            break
    if value is None:
        raise ValueError("TextAsset has no readable script payload")
    if isinstance(value, str):
        raw = value.encode("utf-8", "surrogateescape")
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    else:
        raise TypeError(f"unexpected TextAsset payload type: {type(value)!r}")
    # Historical/compat resources may be gzip-wrapped. Do not assume otherwise.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def load_environment(raw: bytes, filename: str, config: ServerConfig):
    """Decrypt (if needed) then parse one bundle. Fails closed on format drift."""
    buffer = bytearray(raw)
    result = decrypt_bundle_header(buffer, filename, config.bundle_crypto)
    if result.signature != UNITY_SIGNATURE:
        raise ValueError(
            "resource format change: decrypted bundle header is not UnityFS "
            f"(got {result.signature!r}) for {filename}"
        )
    environment = UnityPy.load(bytes(buffer))
    if not list(getattr(environment, "objects", []) or []):
        raise ValueError(f"bundle has no readable Unity objects: {filename}")
    return environment


def _resolve_container_value(value):
    """UnityPy exposes container values as ObjectReader *or* PPtr by version."""
    deref = getattr(value, "deref", None)
    if callable(deref):
        try:
            return deref()
        except Exception:
            return None
    return value


def _assets_file_name(reader) -> str:
    for attribute in ("assetsfile", "assets_file"):
        assets_file = getattr(reader, attribute, None)
        if assets_file is not None:
            name = getattr(assets_file, "name", None)
            if name:
                return str(name)
    return ""


def iter_text_assets(environment) -> Iterator[TextAssetEntry]:
    """Yield TextAssets reachable through ``AssetBundle.m_Container``.

    The container key is the authoritative Unity resource path; it is preserved
    verbatim and never derived from the download filename.
    """
    seen: set[int] = set()
    for container_path, value in environment.container.items():
        if getattr(getattr(value, "type", None), "name", None) != "TextAsset":
            continue
        reader = _resolve_container_value(value)
        if reader is None:
            continue
        path_id = int(getattr(reader, "path_id", 0) or 0)
        if path_id in seen:
            continue
        seen.add(path_id)
        try:
            data = reader.read()
        except Exception:
            continue
        name = getattr(data, "m_Name", None) or getattr(data, "name", None) or ""
        yield TextAssetEntry(
            container_path=str(container_path),
            name=str(name),
            payload=_text_payload(data),
            path_id=path_id,
            cab=_assets_file_name(reader),
        )
