from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from py3rijndael import Pkcs7Padding, RijndaelCbc

from chartdb.master import OfficialMasterSource, validate_master_manifest
from chartdb.master_protocol import MasterVersion


CONTRACT = Path(__file__).parent / "fixtures" / "official_master_manifest_contract.json"
VERSION = "74639bc3f98486a22b1232f232213def"
RESOURCE_VERSION = "1.0.0.201"
ROOT = "https://master.example.test/master"
CRYPTO = {
    "scheme": "haneoka-rijndael-cbc-v2",
    "salt": "b50b23a5fd628c3dc386f7488f81d6b0450b8c89671574f55a3ad815f10b8e30",
    "key": "0532791c510a08eb7ede6b46c6ba71ea9aa2a3cfb678a595f89d67c8a5e493b6",
    "iv": "9b94c91e242a562e97fcd505b75a5129b2b80632a269034cf942ec7293d489a1",
}


def _encrypted_table(rows: list[dict]) -> bytes:
    salt, key, iv = (bytes.fromhex(CRYPTO[name]) for name in ("salt", "key", "iv"))
    cipher = RijndaelCbc(key, iv, Pkcs7Padding(32), block_size=32)
    payload = gzip.compress(json.dumps({"_allData": rows}, separators=(",", ":")).encode())
    return salt + iv + cipher.encrypt(payload)


def _source_inputs():
    tables = {
        "MasterLiveMusic.bin": [{"_id": 100107, "_easyID": 10010700, "_normalID": 10010701, "_hardID": 10010702, "_expertID": 10010703}],
        "MasterLiveMusicScore.bin": [
            {"_id": 10010700, "_musicScoreTextFileName": "0107/0107_00", "_fullComboCount": 320, "_musicScoreLevel": 6},
            {"_id": 10010701, "_musicScoreTextFileName": "0107/0107_01", "_fullComboCount": 499, "_musicScoreLevel": 12},
            {"_id": 10010702, "_musicScoreTextFileName": "0107/0107_02", "_fullComboCount": 646, "_musicScoreLevel": 18},
            {"_id": 10010703, "_musicScoreTextFileName": "0107/0107_03", "_fullComboCount": 960, "_musicScoreLevel": 25},
        ],
    }
    binaries = {name: _encrypted_table(rows) for name, rows in tables.items()}
    manifest = {
        "version": VERSION,
        "files": [
            {"name": name, "size": len(data), "hash": hashlib.sha256(data).hexdigest()}
            for name, data in binaries.items()
        ],
    }
    manifest_raw = json.dumps(manifest, separators=(",", ":")).encode()
    response_map = {
        f"{ROOT}/{VERSION}/MasterManifest.json": manifest_raw,
        **{f"{ROOT}/{VERSION}/{name}": data for name, data in binaries.items()},
    }
    return manifest, manifest_raw, binaries, response_map


def _config():
    return SimpleNamespace(
        master={"versionEndpoint": "https://versions.example.test/service/Version", "remoteRoot": ROOT},
        master_crypto=CRYPTO,
    )


def test_shared_manifest_contract_validates_and_rejects_invalid_cases():
    contract = json.loads(CONTRACT.read_text("utf-8"))
    assert validate_master_manifest(contract["valid"], contract["expectedVersion"]) == contract["valid"]
    for case in contract["invalid"]:
        with pytest.raises(ValueError):
            validate_master_manifest(case["value"], contract["expectedVersion"])


def test_official_source_loads_verified_tables_and_chart_refs():
    _manifest, manifest_raw, _binaries, response_map = _source_inputs()
    with patch("chartdb.master.fetch_bytes", side_effect=lambda url, **_kwargs: response_map[url]):
        snapshot = OfficialMasterSource(_config()).snapshot(
            version_info=MasterVersion(VERSION, RESOURCE_VERSION)
        )
    assert snapshot.authority == "official"
    assert snapshot.version == VERSION
    assert snapshot.resource_version == RESOURCE_VERSION
    assert snapshot.manifest_sha256 == hashlib.sha256(manifest_raw).hexdigest()
    assert snapshot.music_ids == (100107,)
    assert {ref.chart_file for ref in snapshot.refs} == {
        "0107/0107_00", "0107/0107_01", "0107/0107_02", "0107/0107_03"
    }


@pytest.mark.parametrize("mismatch", ["hash", "size"])
def test_master_integrity_mismatch_fails_closed(mismatch):
    manifest, _raw, _binaries, response_map = _source_inputs()
    if mismatch == "hash":
        manifest["files"][0]["hash"] = "0" * 64
    else:
        manifest["files"][0]["size"] += 1
    response_map[f"{ROOT}/{VERSION}/MasterManifest.json"] = json.dumps(manifest).encode()
    with patch("chartdb.master.fetch_bytes", side_effect=lambda url, **_kwargs: response_map[url]):
        with pytest.raises(RuntimeError, match="OFFICIAL_MASTER_TABLE_INTEGRITY_FAILED"):
            OfficialMasterSource(_config()).snapshot(version_info=MasterVersion(VERSION, RESOURCE_VERSION))


def test_manifest_missing_required_score_table_fails_closed():
    manifest, _raw, _binaries, response_map = _source_inputs()
    manifest["files"] = [entry for entry in manifest["files"] if entry["name"] != "MasterLiveMusicScore.bin"]
    response_map[f"{ROOT}/{VERSION}/MasterManifest.json"] = json.dumps(manifest).encode()
    with patch("chartdb.master.fetch_bytes", side_effect=lambda url, **_kwargs: response_map[url]):
        with pytest.raises(RuntimeError, match="OFFICIAL_MASTER_MANIFEST_INVALID"):
            OfficialMasterSource(_config()).snapshot(version_info=MasterVersion(VERSION, RESOURCE_VERSION))


def test_partial_table_response_fails_without_returning_a_snapshot():
    _manifest, _raw, _binaries, response_map = _source_inputs()
    response_map.pop(f"{ROOT}/{VERSION}/MasterLiveMusicScore.bin")
    with patch("chartdb.master.fetch_bytes", side_effect=lambda url, **_kwargs: response_map[url]):
        with pytest.raises(KeyError):
            OfficialMasterSource(_config()).snapshot(version_info=MasterVersion(VERSION, RESOURCE_VERSION))
