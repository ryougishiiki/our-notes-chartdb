"""Resource-format crypto for the current Our Notes generation.

Two independent layers:
  * AssetBundle header: first `headerBytes` of every bundle are AES-CTR-ish
    encrypted; the nonce is derived from the exact bundle filename.
  * Master tables: Rijndael-CBC-256 + gzip, shipped inside the asset-pack APK.

Both follow haneoka-gakuen/haneoka (MPL-2.0) implementations that were verified
against real Our Notes bundles.  They are treated as *current generation*
implementations, not eternal protocols: callers must fail closed when the
decrypted bundle does not start with ``UnityFS``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass

from Crypto.Cipher import AES

from .config import BundleCrypto

UNITY_SIGNATURE = b"UnityFS\0"


@dataclass(frozen=True)
class DecryptResult:
    changed: bool
    signature: bytes


def decrypt_bundle_header(buffer: bytearray, filename: str, crypto: BundleCrypto) -> DecryptResult:
    """Decrypt (in place) the protected prefix of one AssetBundle.

    The source file is addressed by filename: the same bytes downloaded under a
    different name will not decrypt.  ``filename`` must be a plain basename.
    """
    if "/" in filename or "\\" in filename:
        raise ValueError("bundle decryption requires a plain filename")
    if bytes(buffer[: len(UNITY_SIGNATURE)]) == UNITY_SIGNATURE:
        return DecryptResult(False, bytes(buffer[:8]))
    if crypto.scheme != "haneoka-aes-ctr-header-v1":
        raise ValueError(f"unsupported bundle crypto scheme: {crypto.scheme}")

    nonce = hashlib.sha256(crypto.nonce_seed + filename.encode("utf-8")).digest()[:8]
    cipher = AES.new(crypto.key, AES.MODE_ECB)
    limit = min(len(buffer), crypto.header_bytes)
    for offset in range(0, limit, 16):
        mask = cipher.encrypt(nonce + (offset // 16).to_bytes(8, "big"))
        count = min(16, limit - offset)
        buffer[offset : offset + count] = bytes(
            left ^ right for left, right in zip(buffer[offset : offset + count], mask)
        )
    signature = bytes(buffer[: len(UNITY_SIGNATURE)])
    return DecryptResult(True, signature)


def decrypt_master_table(raw: bytes, master_crypto: dict[str, str]) -> dict:
    """Decrypt one ``assets/Master/Master*.bin`` blob from the asset-pack APK."""
    try:
        from py3rijndael import Pkcs7Padding, RijndaelCbc
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("py3rijndael is required to decrypt Master tables") from error

    salt = bytes.fromhex(master_crypto["salt"])
    key = bytes.fromhex(master_crypto["key"])
    iv = bytes.fromhex(master_crypto["iv"])
    if raw[:64] != salt + iv:
        raise ValueError("master crypto constants do not match this table")
    cipher = RijndaelCbc(key, iv, Pkcs7Padding(32), block_size=32)
    decoded = gzip.decompress(cipher.decrypt(raw[64:]))
    value = json.loads(decoded.decode("utf-8"))
    if not isinstance(value.get("_allData"), list):
        raise ValueError("decrypted master table has no _allData list")
    return value
