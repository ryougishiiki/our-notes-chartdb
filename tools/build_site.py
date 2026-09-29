"""Build a self-contained static chart statistics site from a validated build."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path, PurePosixPath


def count_leaf_notes(notes: list[dict]) -> int:
    """Count judged leaf notes; containers only contribute their children."""
    count = 0
    for note in notes:
        if note.get("container") is True:
            count += count_leaf_notes(note.get("node", []))
        else:
            count += 1
    return count


def last_note_time_ms(notes: list[dict]) -> float:
    """Find the greatest leaf-note time, including nested containers."""
    max_time = 0.0
    for note in notes:
        if note.get("container") is True:
            max_time = max(max_time, last_note_time_ms(note.get("node", [])))
        else:
            value = note.get("timeMs", 0) or 0
            if not isinstance(value, (int, float)):
                raise ValueError(f"leaf note timeMs is not numeric: {value!r}")
            max_time = max(max_time, value)
    return max_time


def chart_document_path(pack_dir: Path, archive_path: str) -> Path:
    relative = PurePosixPath(archive_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe chart path in index: {archive_path!r}")
    target = pack_dir.joinpath(*relative.parts)
    if not target.is_file():
        raise FileNotFoundError(f"chart listed in index is missing: {archive_path}")
    return target


def read_records(pack_dir: Path, manifest: dict) -> list[dict]:
    index_path = pack_dir / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"validated pack directory is missing {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index.get("charts")
    expected_count = manifest.get("chartCount")
    if not isinstance(entries, list) or len(entries) != expected_count:
        raise ValueError(
            f"index chart count mismatch: manifest={expected_count}, "
            f"index={len(entries) if isinstance(entries, list) else 'invalid'}"
        )

    records = []
    for entry in entries:
        path = chart_document_path(pack_dir, entry["path"])
        data = json.loads(path.read_text(encoding="utf-8"))
        notes = data.get("notes", [])
        if not notes:
            continue

        identity = data.get("identity", {})
        if identity.get("musicId") != entry.get("musicId"):
            raise ValueError(f"musicId mismatch in {entry['path']}")
        if identity.get("difficulty") != entry.get("difficulty"):
            raise ValueError(f"difficulty mismatch in {entry['path']}")

        note_count = count_leaf_notes(notes)
        duration_ms = last_note_time_ms(notes)
        duration_s = duration_ms / 1000 if duration_ms > 0 else 0
        density = note_count / duration_s if duration_s > 0 else 0
        metadata = data.get("metadata", {})
        records.append(
            {
                "file": path.relative_to(pack_dir / "charts").as_posix(),
                "music_id": identity.get("musicId"),
                "difficulty": identity.get("difficulty"),
                "play_level": metadata.get("playLevel"),
                "title": metadata.get("title") or "",
                "note_count": note_count,
                "duration_s": round(duration_s, 2),
                "density": round(density, 2),
            }
        )

    if len(records) != expected_count:
        raise ValueError(
            f"only {len(records)} non-empty charts found; expected {expected_count}"
        )
    return records


def average(values: list[float], digits: int = 2) -> float:
    return round(statistics.mean(values), digits) if values else 0


def build_summary(records: list[dict], manifest: dict) -> dict:
    if not records:
        raise ValueError("the validated pack contains no charts")

    by_difficulty = {}
    for difficulty in ("easy", "normal", "hard", "expert"):
        group = [r for r in records if r["difficulty"] == difficulty]
        by_difficulty[difficulty] = {
            "count": len(group),
            "avg_note_count": average([r["note_count"] for r in group], 1),
            "median_note_count": statistics.median(
                [r["note_count"] for r in group]
            )
            if group
            else 0,
            "avg_duration_s": average([r["duration_s"] for r in group]),
            "avg_density": average([r["density"] for r in group]),
            "median_density": statistics.median([r["density"] for r in group])
            if group
            else 0,
        }

    source = manifest.get("source", {})
    pack = manifest.get("pack", {})
    return {
        "chart_count": len(records),
        "song_count": len({r["music_id"] for r in records}),
        "difficulty_count": len({r["difficulty"] for r in records}),
        "avg_note_count": average([r["note_count"] for r in records], 1),
        "avg_duration_s": average([r["duration_s"] for r in records]),
        "avg_density": average([r["density"] for r in records]),
        "median_density": statistics.median([r["density"] for r in records]),
        "by_difficulty": by_difficulty,
        "shortest": min(records, key=lambda r: r["duration_s"]),
        "most_notes": max(records, key=lambda r: r["note_count"]),
        "highest_density": max(records, key=lambda r: r["density"]),
        "longest": max(records, key=lambda r: r["duration_s"]),
        "database_version": manifest.get("databaseVersion", "unknown"),
        "generated_at": manifest.get("generatedAt", "unknown"),
        "pack_sha256": pack.get("sha256", ""),
        "catalog_version": source.get("catalogVersion", "unknown"),
        "server": source.get("server", "unknown"),
    }


def write_csv(records: list[dict], path: Path) -> None:
    fields = [
        "file",
        "music_id",
        "title",
        "difficulty",
        "play_level",
        "note_count",
        "duration_s",
        "density",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument(
        "--template", type=Path, default=Path("site/index.template.html")
    )
    parser.add_argument("--output", type=Path, default=Path("dist/site"))
    args = parser.parse_args()

    manifest = json.loads((args.dist / "manifest.json").read_text(encoding="utf-8"))
    records = read_records(args.dist / "pack", manifest)
    summary = build_summary(records, manifest)
    payload = {"summary": summary, "records": records}
    json_payload = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
    )

    template = args.template.read_text(encoding="utf-8")
    marker = "__CHARTDB_DATA__"
    if template.count(marker) != 1:
        raise ValueError(f"template must contain exactly one {marker} marker")

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "index.html").write_text(
        template.replace(marker, json_payload), encoding="utf-8"
    )
    write_csv(records, args.output / "chartdb_spectra_stats.csv")

    print(
        f"site built: {len(records)} charts, "
        f"{summary['song_count']} songs, version {summary['database_version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
