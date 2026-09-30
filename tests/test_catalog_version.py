from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from chartdb import catalog_version
from chartdb.cache import catalog_cache_path
from chartdb.http import HttpError, probe_exists


FIXTURE = Path(__file__).parent / "fixtures" / "catalog_version_probe_contract.json"


def test_shared_probe_contract_cases():
    contract = json.loads(FIXTURE.read_text("utf-8"))
    assert catalog_version.MAX_CONSECUTIVE_MISSES == contract["maxConsecutiveMisses"]
    assert catalog_version.MAX_BUILD_ADVANCE == contract["maxBuildAdvance"]
    assert catalog_version.MAX_LINE_ADVANCE == contract["maxLineAdvance"]
    assert catalog_version.MAX_PROBE_REQUESTS == contract["maxProbeRequests"]
    for case in contract["cases"]:
        hits = set(case["existing"])
        result = catalog_version.resolve_catalog_version(case["floor"], hits.__contains__)
        assert result.resolved == case["expected"], case["name"]
        assert result.source == "probe", case["name"]


def test_nonstandard_version_is_returned_without_network_probes():
    called = []
    result = catalog_version.resolve_catalog_version("1.0.0-beta", called.append)
    assert result.resolved == "1.0.0-beta"
    assert result.source == "config"
    assert result.probes == 0
    assert called == []


@pytest.mark.parametrize("status", [400, 403, 404])
def test_probe_http_missing_statuses_are_misses(status):
    error = urllib.error.HTTPError("https://cdn.invalid/catalog_1.0.0.101.hash", status, "missing", {}, None)
    with patch("chartdb.http.urllib.request.urlopen", side_effect=error):
        assert not probe_exists("https://cdn.invalid/catalog_1.0.0.101.hash")


def test_probe_server_errors_retry_then_fail_instead_of_becoming_a_miss():
    error = urllib.error.HTTPError("https://cdn.invalid/catalog_1.0.0.101.hash", 503, "unavailable", {}, None)
    with patch("chartdb.http.urllib.request.urlopen", side_effect=error) as request, patch(
        "chartdb.http.time.sleep"
    ):
        with pytest.raises(HttpError, match="failed to probe"):
            probe_exists("https://cdn.invalid/catalog_1.0.0.101.hash", retries=3)
    assert request.call_count == 3


def test_probe_request_budget_fails_closed(monkeypatch):
    monkeypatch.setattr(catalog_version, "MAX_PROBE_REQUESTS", 4)
    checked = []
    with pytest.raises(catalog_version.CatalogProbeLimitError):
        catalog_version.resolve_catalog_version("1.0.0.100", lambda version: checked.append(version) or True)
    assert len(checked) == 4


def test_line_search_limit_fails_closed(monkeypatch):
    monkeypatch.setattr(catalog_version, "MAX_BUILD_ADVANCE", 0)
    monkeypatch.setattr(catalog_version, "MAX_LINE_ADVANCE", 1)
    with pytest.raises(catalog_version.CatalogProbeLimitError, match="higher lines"):
        catalog_version.resolve_catalog_version("1.0.0.100", lambda _version: True)


def test_catalog_cache_namespace_includes_resolved_version(tmp_path):
    old_cache = catalog_cache_path(tmp_path, "1.0.0.100")
    new_cache = catalog_cache_path(tmp_path, "1.0.0.101")
    assert old_cache == tmp_path / "catalog" / "1.0.0.100" / "catalog.bin"
    assert new_cache == tmp_path / "catalog" / "1.0.0.101" / "catalog.bin"
    assert old_cache != new_cache
