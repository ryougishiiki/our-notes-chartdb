# Third-party notices

## Haneoka source references

The official Master version-service and manifest contracts and the bounded
catalog probing strategy in this repository are adapted from
[haneoka-gakuen/haneoka](https://github.com/haneoka-gakuen/haneoka):

- `scripts/ingest/master.py` (`decode_master_version` and
  `discover_master_version`)
- `scripts/extract/master.py` (`validate_master_manifest` and Master table
  integrity/decryption flow)
- `scripts/ingest/apks.py` (`_resolve_catalog_version`)

Those references are licensed under the Mozilla Public License 2.0 (MPL-2.0).
The corresponding adapted Source Code Form in this repository is identified in
the file headers of `src/chartdb/master_protocol.py`, `src/chartdb/master.py`,
and `src/chartdb/catalog_version.py`. The MPL-2.0 text is retained at
[`LICENSES/MPL-2.0.txt`](LICENSES/MPL-2.0.txt). This notice does not make a
project-wide license claim for files that are not Haneoka-derived.

Haneoka is used only for comparison and an explicitly selected derived mirror
build. Official Master and catalog data remain the production authority; neither
repository is a runtime dependency.
