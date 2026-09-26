import sys, json, collections
from pathlib import Path
sys.path.insert(0, "src")
from chartdb.config import resolve_server
from chartdb.addressables import parse_catalog
from chartdb.discover import discover
from chartdb.master import HaneokaMirrorMasterSource
from chartdb.unity import load_environment, iter_text_assets
from chartdb import cli

config = resolve_server("intl"); work = Path(".cache")
cat = (work / "catalog" / f"catalog_{config.catalog_version}.bin").read_bytes()
discovery = discover(parse_catalog(cat, config.remote_root, config.remote_root))
refs = {f"{r.music_id}/{r.difficulty}": r for r in HaneokaMirrorMasterSource(config).charts()}
oracle = Path("tools/oracle/oracle.cjs")

def payload(ref):
    b = discovery.charts[ref.chart_file]
    env = load_environment((work/"bundles"/b.download_filename).read_bytes(), b.download_filename, config)
    a = list(iter_text_assets(env))
    return a[0].payload

targets = ["100001/easy", "100005/hard", "100043/hard", "100082/hard", "100017/hard"]
rows = []
for key in targets:
    ref = refs[key]
    r = cli._run_oracle(oracle, payload(ref))
    rows.append((key, ref.full_combo_count, r["rawNoteCount"], r["authoredJudgedCount"], r["generatedComboCount"], r["generatedComboSkipCount"], r["judgedCount"], r["judgedCount"]-ref.full_combo_count))
print(f"{'chart':16}{'fullCombo':>10}{'raw':>6}{'authJudge':>11}{'combo':>8}{'comboSkip':>11}{'judged':>8}{'delta':>7}")
for r in rows: print(f"{r[0]:16}{r[1]:>10}{r[2]:>6}{r[3]:>11}{r[4]:>8}{r[5]:>11}{r[6]:>8}{r[7]:>7}")

# full distribution: authored judged vs generated combo
import statistics
deltas_auth, deltas_combo = [], []
for key, ref in refs.items():
    b = discovery.charts.get(ref.chart_file)
    if not b or not (work/"bundles"/b.download_filename).is_file(): continue
    if ref.full_combo_count is None: continue
    r = cli._run_oracle(oracle, payload(ref))
    deltas_auth.append(r["authoredJudgedCount"] - ref.full_combo_count)
print("\nauthoredJudged - fullComboCount: min", min(deltas_auth), "max", max(deltas_auth), "mean", round(statistics.mean(deltas_auth),2))
print("authored==fullCombo for", sum(1 for d in deltas_auth if d==0), "of", len(deltas_auth))
