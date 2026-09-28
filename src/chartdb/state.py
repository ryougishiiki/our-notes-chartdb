"""Incremental state: one hash per (musicId, difficulty)."""

from __future__ import annotations

import json
from pathlib import Path

STATE_SCHEMA = "chartdb-state/1"


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {"schema": STATE_SCHEMA, "charts": {}}
    value = json.loads(path.read_text("utf-8"))
    if value.get("schema") != STATE_SCHEMA or not isinstance(value.get("charts"), dict):
        raise ValueError(f"invalid state file: {path}")
    return value


def save_state(path: Path, charts: dict[str, str], source_revision: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema": STATE_SCHEMA, "sourceRevision": source_revision, "charts": charts},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def key_of(music_id: int, difficulty: str) -> str:
    return f"{music_id}/{difficulty}"


def diff(old: dict[str, str], new: dict[str, str]) -> dict:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(key for key in set(old) & set(new) if old[key] != new[key])
    unchanged = len(set(old) & set(new)) - len(changed)
    return {
        "newCharts": added,
        "changedCharts": changed,
        "removedCharts": removed,
        "unchangedCharts": unchanged,
        "newCount": len(added),
        "changedCount": len(changed),
        "removedCount": len(removed),
    }


def has_changes(incremental: dict) -> bool:
    """Whether the formal chart set or any of its source payloads changed."""
    return any(
        bool(incremental.get(key))
        for key in ("newCharts", "changedCharts", "removedCharts")
    )
