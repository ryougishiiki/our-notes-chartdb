import sys
from pathlib import Path
sys.path.insert(0, "src")
from chartdb.config import resolve_server
from chartdb.addressables import parse_catalog
from chartdb.discover import discover
from chartdb.master import HaneokaMirrorMasterSource
c = resolve_server("intl"); w = Path(".cache")
cat = (w/"catalog"/f"catalog_{c.catalog_version}.bin").read_bytes()
d = discover(parse_catalog(cat, c.remote_root, c.remote_root))
refs = HaneokaMirrorMasterSource(c).charts()
ref_files = {r.chart_file for r in refs}
missing = sorted(set(d.charts) - ref_files)
print("chart-named bundles:", len(d.charts))
print("master-referenced chart files:", len(ref_files))
print("chart-named bundles with NO master reference:", len(missing), missing)
print("non-chart MusicScore bundles:", len(d.unreferenced))
for u in d.unreferenced[:6]: print("   ", u.primary_key)
