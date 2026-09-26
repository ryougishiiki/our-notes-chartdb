"""MusicScore bundle discovery from the Addressables catalog.

The catalog key is the only discovery input.  Bundle *filenames* are content
addresses and are never used to infer musicId; they only identify the bundle
for download and for header decryption (the nonce depends on the filename).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MUSIC_SCORE_MARKER = "live_assets_live_musicscore_"
# live_assets_live_musicscore_<folder>_<file>_<difficulty>_<md5>.bundle
CHART_KEY = re.compile(
    r"^live_assets_live_musicscore_(\d{4})_(\d{4})_(\d{2})_([0-9a-f]{32})\.bundle$"
)


@dataclass(frozen=True)
class BundleRef:
    primary_key: str
    remote_url: str
    bundle_name: str
    bundle_size: int
    bundle_hash: str
    chart_file: str | None

    @property
    def download_filename(self) -> str:
        """Filename the CDN serves; the decryption nonce is derived from this."""
        return self.primary_key


@dataclass
class Discovery:
    charts: dict[str, BundleRef]
    unreferenced: list[BundleRef]

    @property
    def chart_bundle_count(self) -> int:
        return len(self.charts)

    @property
    def unreferenced_count(self) -> int:
        return len(self.unreferenced)


def discover(catalog) -> Discovery:
    charts: dict[str, BundleRef] = {}
    unreferenced: list[BundleRef] = []
    for location in catalog.downloadable():
        key = str(location.get("primaryKey") or "")
        if MUSIC_SCORE_MARKER not in key:
            continue
        data = location["data"]
        match = CHART_KEY.match(key)
        ref = BundleRef(
            primary_key=key,
            remote_url=str(location["remoteUrl"]),
            bundle_name=str(data.get("bundleName") or ""),
            bundle_size=int(data.get("bundleSize") or 0),
            bundle_hash=str(data.get("hash") or ""),
            chart_file=f"{match.group(1)}/{match.group(2)}_{match.group(3)}" if match else None,
        )
        if ref.chart_file is None:
            unreferenced.append(ref)
            continue
        if ref.chart_file in charts:
            existing = charts[ref.chart_file]
            if existing.primary_key != ref.primary_key:
                raise ValueError(
                    f"ambiguous MusicScore bundles for {ref.chart_file}: "
                    f"{existing.primary_key} vs {ref.primary_key}"
                )
            continue
        charts[ref.chart_file] = ref
    unreferenced.sort(key=lambda item: item.primary_key)
    return Discovery(charts=charts, unreferenced=unreferenced)
