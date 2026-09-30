"""Small HTTP helper with retries and an on-disk cache."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = (
    "haneoka-chartdb/0.1 (+https://github.com/; source-derived chart database)"
)
ACCEPT = "application/json, application/octet-stream, */*"


class HttpError(RuntimeError):
    pass


def fetch_bytes(url: str, timeout: float = 60.0, retries: int = 5) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            last = error
            # 4xx other than rate limiting will not succeed on retry.
            if error.code not in (403, 408, 425, 429) and error.code < 500:
                raise HttpError(f"failed to fetch {url}: HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
        time.sleep(min(8.0, 1.5 * (attempt + 1)) + random.uniform(0, 0.5))
    raise HttpError(f"failed to fetch {url}: {last}")


def probe_exists(url: str, timeout: float = 60.0, retries: int = 5) -> bool:
    """Check an object without treating transient or unexpected errors as misses."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Cache-Control": "no-cache"}
            )
            with urllib.request.urlopen(request, timeout=timeout):
                return True
        except urllib.error.HTTPError as error:
            if error.code in (400, 403, 404):
                return False
            last = error
            if error.code not in (408, 425, 429) and error.code < 500:
                raise HttpError(f"failed to probe {url}: HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
        if attempt + 1 < retries:
            time.sleep(min(8.0, 1.5 * (attempt + 1)) + random.uniform(0, 0.5))
    raise HttpError(f"failed to probe after {retries} attempts: {url}: {last}") from last


def fetch_json(url: str, timeout: float = 60.0) -> object:
    return json.loads(fetch_bytes(url, timeout=timeout).decode("utf-8"))


def cached_bytes(url: str, cache_file: Path, expect_sha256: str | None = None) -> bytes:
    from .hashing import sha256_bytes

    if cache_file.is_file():
        data = cache_file.read_bytes()
        if expect_sha256 is None or sha256_bytes(data) == expect_sha256:
            return data
    data = fetch_bytes(url)
    if expect_sha256 is not None and sha256_bytes(data) != expect_sha256:
        raise HttpError(f"hash mismatch for {url}")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_name(cache_file.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(cache_file)
    return data
