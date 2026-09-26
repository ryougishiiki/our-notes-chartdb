"""Diagnose oracle (judged) vs MasterLiveMusicScore._fullComboCount deltas."""
import sys, collections
from pathlib import Path
sys.path.insert(0, "src")
from chartdb.config import resolve_server
from chartdb.addressables import parse_catalog
from chartdb.discover import discover
from chartdb.master import HaneokaMirrorMasterSource
from chartdb.unity import load_environment, iter_text_assets
from chartdb import cli

config = resolve_server("intl")
work = Path(".cache")
catalog_bytes = (work / "catalog" / f"catalog_{config.catalog_version}.bin").read_bytes()
discovery = discover(parse_catalog(catalog_bytes, config.remote_root, config.remote_root))
master = HaneokaMirrorMasterSource(config)
refs = master.charts()
oracle = Path("tools/oracle/oracle.cjs")

deltas = collections.Counter()
worst = []
matched = 0
n = 0
for ref in refs:
    bundle = discovery.charts.get(ref.chart_file)
    if bundle is None:
        continue
    path = work / "bundles" / bundle.download_filename
    if not path.is_file():
        continue
    env = load_environment(path.read_bytes(), bundle.download_filename, config)
    assets = list(iter_text_assets(env))
    asset = next((a for a in assets if a.container_path.endswith(f"{ref.chart_file}.bytes")), None)
    if asset is None and len(assets) == 1:
        asset = assets[0]
    if asset is None:
        continue
    judged = int(cli._run_oracle(oracle, asset.payload)["judgedCount"])
    if ref.full_combo_count is None:
        continue
    n += 1
    d = judged - ref.full_combo_count
    deltas[d] += 1
    if d == 0:
        matched += 1
    else:
        worst.append((abs(d), d, ref.music_id, ref.difficulty, judged, ref.full_combo_count))
print(f"charts compared: {n}  matched: {matched}  mismatched: {n-matched} ({100*(n-matched)/max(n,1):.1f}%)")
print("delta histogram (judged - fullComboCount):", dict(sorted(deltas.items())))
worst.sort(reverse=True)
print("worst 10:", worst[:10])
