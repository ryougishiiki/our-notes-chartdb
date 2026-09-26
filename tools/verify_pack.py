import io, json, tarfile, zstandard
from pathlib import Path
pack = next(Path("dist").glob("*.tar.zst"))
data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(pack.read_bytes()))
with tarfile.open(fileobj=data, mode="r|") as tar:
    names = []
    index = None
    chart = None
    for member in tar:
        names.append(member.name)
        if member.name == "index.json":
            index = json.loads(tar.extractfile(member).read())
        if member.name == "charts/100001/expert.json" and chart is None:
            chart = json.loads(tar.extractfile(member).read())
print("pack entries:", names)
print("index.chartCount:", index["chartCount"])
print("index.charts[0]:", json.dumps(index["charts"][0], ensure_ascii=False))
n = chart["notes"][0]
print("expert notes:", len(chart["notes"]), "first note (raw stripped):")
print(json.dumps({k: v for k, v in n.items() if k != "raw"}, ensure_ascii=False, indent=1))
print("first note raw:", json.dumps(n["raw"], ensure_ascii=False))
long = next(x for x in chart["notes"] if x.get("node"))
print("first container note:", json.dumps({k: v for k, v in long.items() if k != "raw"}, ensure_ascii=False)[:400])
print("metadata.validation:", json.dumps(chart["metadata"]["validation"], ensure_ascii=False))
print("fieldConfidence:", json.dumps(chart["metadata"]["fieldConfidence"], ensure_ascii=False))
