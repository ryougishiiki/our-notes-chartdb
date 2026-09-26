"""chartdb CLI.

    python -m chartdb build --server intl --music 100001 --difficulty easy --difficulty expert
    python -m chartdb build --server intl --all --master-source apk --apk UnityDataAssetPack.apk
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .addressables import parse_catalog
from .config import resolve_server
from .db import DatabaseBuilder
from .discover import discover
from .hashing import canonical_json, sha256_bytes
from .master import ApkMasterSource, HaneokaMirrorMasterSource
from .normalize import CHART_SCHEMA_VERSION, build_chart_document
from .ss import SsError, parse_ss
from .state import diff, key_of, load_state, save_state
from .unity import iter_text_assets, load_environment
from .validate import chart_gates, global_gates, summarize
from .http import cached_bytes


def _oracle_path(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    default = Path(__file__).resolve().parents[2] / "tools" / "oracle" / "oracle.cjs"
    return default if default.is_file() else None


def _run_oracle(oracle: Path, payload: bytes) -> dict:
    handle = tempfile.NamedTemporaryFile(suffix=".bytes", delete=False)
    try:
        handle.write(payload)
        handle.close()
        completed = subprocess.run(
            ["node", str(oracle), handle.name], capture_output=True, text=True, check=True
        )
        return json.loads(completed.stdout)
    finally:
        Path(handle.name).unlink(missing_ok=True)


def _select(refs, args):
    if args.all or (not args.music and not args.difficulty):
        return refs
    music = {int(value) for value in args.music or []}
    difficulties = {value for value in args.difficulty or []}
    return [
        ref
        for ref in refs
        if (not music or ref.music_id in music) and (not difficulties or ref.difficulty in difficulties)
    ]


def cmd_build(args) -> int:
    config = resolve_server(args.server)
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Addressables catalog -------------------------------------------------
    catalog_bytes = cached_bytes(
        config.catalog_bin_url, work / "catalog" / f"catalog_{config.catalog_version}.bin"
    )
    catalog_hash = sha256_bytes(catalog_bytes)
    reader = parse_catalog(catalog_bytes, config.remote_root, config.remote_root)
    discovery = discover(reader)
    print(
        f"[catalog] version={config.catalog_version} sha256={catalog_hash[:16]} "
        f"chartBundles={discovery.chart_bundle_count} unreferenced={discovery.unreferenced_count}",
        file=sys.stderr,
    )

    # 2. Master mapping -------------------------------------------------------
    if args.master_source == "apk":
        if not args.apk:
            raise SystemExit("--apk is required with --master-source apk")
        master = ApkMasterSource(Path(args.apk), config)
    else:
        master = HaneokaMirrorMasterSource(config)
    snapshot = master.snapshot(music_ids={int(value) for value in args.music} or None)
    refs = list(snapshot.refs)
    print(
        f"[master] source={snapshot.source} authority={snapshot.authority} "
        f"revision={snapshot.revision[:16]} charts={len(refs)}",
        file=sys.stderr,
    )

    selected = _select(refs, args)
    print(f"[select] {len(selected)} chart(s)", file=sys.stderr)

    # 3. Convert --------------------------------------------------------------
    builder = DatabaseBuilder(CHART_SCHEMA_VERSION)
    oracle = _oracle_path(args.oracle)
    oracle_available = bool(oracle) and not args.no_oracle
    if args.no_oracle:
        print("[oracle] disabled", file=sys.stderr)
    elif not oracle_available:
        print("[oracle] tools/oracle/oracle.cjs NOT built; fullComboCount gate will be UNKNOWN", file=sys.stderr)

    failures: list[dict] = []
    combo_stats: dict[str, int] = {}
    state_charts: dict[str, str] = {}
    converted = 0
    for ref in selected:
        key = key_of(ref.music_id, ref.difficulty)
        bundle = discovery.charts.get(ref.chart_file)
        if bundle is None:
            failures.append({"chart": key, "reason": "master references a chart with no MusicScore bundle"})
            continue
        try:
            raw = cached_bytes(bundle.remote_url, work / "bundles" / bundle.download_filename)
            environment = load_environment(raw, bundle.download_filename, config)
            assets = list(iter_text_assets(environment))
            asset = next(
                (a for a in assets if a.container_path.endswith(f"{ref.chart_file}.bytes")), None
            )
            if asset is None and len(assets) == 1:
                asset = assets[0]
            if asset is None:
                raise ValueError(
                    f"no TextAsset for {ref.chart_file} in bundle (found {[a.container_path for a in assets]})"
                )
            ss = parse_ss(asset.payload)
        except (SsError, ValueError, OSError) as error:
            failures.append({"chart": key, "reason": f"{type(error).__name__}: {error}"})
            continue

        judge = None
        if oracle_available:
            try:
                judge = _run_oracle(oracle, asset.payload)
            except Exception as error:  # oracle must never silently degrade a release
                failures.append({"chart": key, "reason": f"oracle failed: {error}"})
                continue

        source = {
            "server": config.id,
            "masterSource": ref.master_source,
            "catalogVersion": config.catalog_version,
            "catalogHash": catalog_hash,
            "chartFile": ref.chart_file,
            "assetPath": asset.container_path,
            "ssVersion": ss.version,
            "sourceSha256": sha256_bytes(asset.payload),
            "textAssetClassId": 49,
            "bundle": {
                "primaryKey": bundle.primary_key,
                "remoteUrl": bundle.remote_url,
                "sha256": sha256_bytes(raw),
                "size": len(raw),
                "unityVersion": config.unity_version,
            },
        }
        document = build_chart_document(ss, ref, source, judge)
        gates = chart_gates(document, asset.payload, args.oracle_policy)
        failed = [g for g in gates if g.status == "fail"]
        document["metadata"]["gates"] = [g.__dict__ for g in gates]
        if failed:
            failures.append({"chart": key, "reason": "gates: " + ", ".join(g.name for g in failed)})
            continue

        builder.add(document, source["sourceSha256"])
        state_charts[key] = source["sourceSha256"]
        converted += 1
        combo_state = "unknown"
        if judge is not None and ref.full_combo_count is not None:
            combo_state = "exact" if judge["judgedCount"] == ref.full_combo_count else "mismatch"
        combo_stats[combo_state] = combo_stats.get(combo_state, 0) + 1
        print(
            f"  ok {key} scoreId={ref.score_id} file={ref.chart_file} rawNotes={ss.raw_note_count} "
            f"judged={judge['judgedCount'] if judge else None} fullCombo={ref.full_combo_count} combo={combo_state}",
            file=sys.stderr,
        )

    # 4. Global gates ---------------------------------------------------------
    selected_refs = [ref for ref in selected if discovery.charts.get(ref.chart_file)]
    gates = global_gates(selected_refs)
    global_failed = [g for g in gates if g.status == "fail"]

    # 5. Write DB -------------------------------------------------------------
    previous = load_state(work / "state.json")
    incremental = diff(previous.get("charts", {}), state_charts)
    catalog_chart_files = set(discovery.charts)
    master_chart_files = {ref.chart_file for ref in refs}
    catalog_named_without_master = sorted(catalog_chart_files - master_chart_files)
    coverage = {
        "catalogMusicScoreBundles": discovery.chart_bundle_count + discovery.unreferenced_count,
        "catalogNamedCharts": discovery.chart_bundle_count,
        "catalogNonChartUnreferenced": discovery.unreferenced_count,
        "masterReferenced": len(refs),
        "masterResolved": len(selected_refs),
        "masterReferencedWithoutCatalog": sum(
            1 for ref in refs if ref.chart_file not in catalog_chart_files
        ),
        "catalogNamedWithoutMaster": len(catalog_named_without_master),
        "catalogNamedWithoutMasterList": catalog_named_without_master,
        "catalogAligned": len(catalog_named_without_master) == 0,
    }

    validation_meta = {
        # "complete" is only ever about THIS Master snapshot: every chart the
        # Master references has been resolved and passed its gates.  Catalog
        # alignment is a separate axis (see coverage.catalogAligned).
        "completeForMasterSnapshot": not failures and not global_failed,
        "failedCharts": failures,
        "converted": converted,
        "selected": len(selected),
        "globalGates": [g.__dict__ for g in gates],
        "comboCountExact": combo_stats.get("exact", 0),
        "comboCountMismatch": combo_stats.get("mismatch", 0),
        "comboCountUnknown": combo_stats.get("unknown", 0),
        "comboCountPolicy": args.oracle_policy,
    }
    source_meta = {
        "server": config.id,
        "catalogVersion": config.catalog_version,
        "catalogHash": catalog_hash,
        "remoteRoot": config.remote_root,
        "masterSource": snapshot.source,
        "masterAuthority": snapshot.authority,
        "masterRevision": snapshot.revision,
        "masterTables": snapshot.tables,
        "officialMasterSource": "TODO",
        "gameVersion": config.catalog_version,
    }
    version = args.database_version or f"{config.id}-{catalog_hash[:12]}"
    manifest = builder.write(out, source_meta, validation_meta, incremental, version)
    manifest["coverage"] = coverage
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    full_selection = len(selected) == len(refs)
    if args.no_state_update:
        pass
    elif not full_selection:
        print("[state] partial build: incremental state left untouched", file=sys.stderr)
    else:
        save_state(work / "state.json", state_charts, catalog_hash)

    print(json.dumps({
        "converted": converted,
        "failed": len(failures),
        "globalGates": summarize(gates),
        "incremental": {k: v for k, v in incremental.items() if k.endswith("Count")},
        "manifest": str(out / "manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0 if validation_meta["completeForMasterSnapshot"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chartdb")
    parser.add_argument("--version", action="version", version=f"chartdb {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="produce a Chart DB pack + manifest")
    build.add_argument("--server", default=None)
    build.add_argument("--music", action="append", default=[])
    build.add_argument("--difficulty", action="append", default=[])
    build.add_argument("--all", action="store_true")
    build.add_argument("--master-source", choices=["mirror", "apk"], default="mirror")
    build.add_argument("--apk", default=None)
    build.add_argument("--oracle", default=None)
    build.add_argument("--no-oracle", action="store_true")
    build.add_argument("--oracle-policy", choices=["report", "strict"], default="report")
    build.add_argument("--no-state-update", action="store_true")
    build.add_argument("--workdir", default=".chartdb-cache")
    build.add_argument("--out", default="dist")
    build.add_argument("--database-version", default=None)
    build.set_defaults(func=cmd_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
