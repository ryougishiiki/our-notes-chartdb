"""Consumer smoke test: manifest -> index -> lookup(musicId, difficulty)."""
import io, json, tarfile, zstandard
from pathlib import Path

dist = Path("dist-all")
manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
assert manifest["protocolVersion"] == 1
pack = dist / manifest["pack"]["file"]
stream = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(pack.read_bytes()))
index = None
chart = None
with tarfile.open(fileobj=stream, mode="r|") as tar:
    for member in tar:
        if member.name == "index.json":
            index = json.loads(tar.extractfile(member).read())
        elif member.name == "charts/100001/expert.json":
            chart = json.loads(tar.extractfile(member).read())
target = next(c for c in index["charts"] if c["musicId"] == 100001 and c["difficulty"] == "expert")
print("lookup(100001, expert) ->")
print("  index entry   :", json.dumps({k: target[k] for k in ("scoreId","chartFile","sourceSha256","normalizedSha256")}, ensure_ascii=False))
print("  assetPath     :", chart["source"]["assetPath"])
print("  ssVersion     :", chart["source"]["ssVersion"])
print("  notes         :", len(chart["notes"]), "| container:", sum(1 for n in chart["notes"] if n["container"]))
print("  validation    :", json.dumps(chart["metadata"]["validation"], ensure_ascii=False))
print("OK: consumer lookup works")
