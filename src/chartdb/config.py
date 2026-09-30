from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "servers.json"


@dataclass(frozen=True)
class BundleCrypto:
    scheme: str
    key: bytes
    nonce_seed: bytes
    header_bytes: int


@dataclass(frozen=True)
class ServerConfig:
    id: str
    package_name: str
    platform: str
    unity_version: str
    remote_root: str
    catalog_version: str
    bundle_crypto: BundleCrypto
    master_crypto: dict[str, str]
    master_mirror: dict[str, str]
    master: dict[str, Any]

    @property
    def catalog_bin_url(self) -> str:
        return f"{self.remote_root}/catalog_{self.catalog_version}.bin"

    @property
    def catalog_hash_url(self) -> str:
        return f"{self.remote_root}/catalog_{self.catalog_version}.hash"


def load_config(path: Path | None = None) -> dict[str, ServerConfig]:
    document = json.loads((path or DEFAULT_CONFIG).read_text("utf-8"))
    servers: dict[str, ServerConfig] = {}
    for key, raw in document["servers"].items():
        crypto = raw["bundleCrypto"]
        servers[key] = ServerConfig(
            id=raw["id"],
            package_name=raw["packageName"],
            platform=raw["platform"],
            unity_version=raw["unityVersion"],
            remote_root=raw["remoteRoot"].rstrip("/"),
            catalog_version=raw["catalog"]["version"],
            bundle_crypto=BundleCrypto(
                scheme=crypto["scheme"],
                key=bytes.fromhex(crypto["key"]),
                nonce_seed=bytes.fromhex(crypto["nonceSeed"]),
                header_bytes=int(crypto["headerBytes"]),
            ),
            master_crypto=dict(raw.get("masterCrypto", {})),
            master_mirror=dict(raw.get("master", {}).get("mirror", raw.get("masterMirror", {}))),
            master=dict(raw.get("master", {})),
        )
    return servers


def resolve_server(name: str | None, path: Path | None = None) -> ServerConfig:
    document = json.loads((path or DEFAULT_CONFIG).read_text("utf-8"))
    chosen = name or document["default"]
    servers = load_config(path)
    if chosen not in servers:
        raise KeyError(f"unknown server: {chosen}")
    return servers[chosen]
