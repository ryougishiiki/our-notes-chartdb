"""SsRoot -> ChartDocument v1.

Rules:
  * confirmed semantics are normalised under a stable name;
  * everything whose meaning is only *guessed* stays verbatim under ``raw``;
  * the original SS fields are always preserved so a future schema can be
    derived without re-downloading anything.
"""

from __future__ import annotations

from .ss import SsNote, SsRoot, bpm_events, sig_events
from .timing import TickConverter

CHART_SCHEMA_VERSION = "chartdoc/1"

#: Per-field confidence.  Only CONFIRMED fields are promoted to first-class
#: names; CANDIDATE/UNKNOWN fields keep their raw value alongside.
FIELD_CONFIDENCE: dict[str, str] = {
    "tick": "CONFIRMED",
    "timeMs": "CONFIRMED",
    "bar": "CONFIRMED",
    "position": "CONFIRMED",
    "positionAuto": "CONFIRMED",
    "size": "CONFIRMED",
    "critical": "CONFIRMED",
    "visible": "CONFIRMED",
    "direction": "CONFIRMED",
    "type": "CONFIRMED",
    "node": "CONFIRMED",
    "bpm": "CONFIRMED",
    "signature": "CONFIRMED",
    "ease": "CANDIDATE",
    "alpha": "CANDIDATE",
    "skill": "CANDIDATE",
    "fever": "CANDIDATE",
    "call": "CANDIDATE",
    "dirRaw": "CONFIRMED",
}

NOTE_KEYS_RAW = ("type", "t", "pos", "size", "crit", "dir", "ease", "visible", "alpha", "node")


def _normalize_note(note: SsNote, converter: TickConverter, depth: int = 0) -> dict:
    if depth > 32:
        raise ValueError("SS node nesting is too deep")
    entry = {
        "type": note.type_effective,
        "container": note.container,
        "position": note.pos,
        "positionAuto": note.pos_auto,
        "size": note.size,
        "critical": note.crit,
        "visible": note.visible,
        "direction": note.dir_effective,
        "ease": [note.ease_l, note.ease_r],
        "alpha": note.alpha_effective,
        "raw": note.to_raw_dict(),
    }
    if note.t is None:
        # container note (long/guide): geometry lives in node[]
        entry["tick"] = None
        entry["timeMs"] = None
        entry["bar"] = None
    else:
        bar = converter.tick_to_bar_position(note.t)
        entry["tick"] = note.t
        entry["timeMs"] = converter.tick_to_time_ms(note.t)
        entry["bar"] = {"bar": bar.bar, "progress": bar.progress}
    if note.node:
        entry["node"] = [_normalize_note(child, converter, depth + 1) for child in note.node]
    return entry


def build_chart_document(ss: SsRoot, chart_ref, source: dict, judge: dict | None) -> dict:
    converter = TickConverter(bpm_events(ss), sig_events(ss))
    notes = [_normalize_note(note, converter) for note in ss.notes]

    calculated = judge.get("judgedCount") if judge else None
    master_full_combo = chart_ref.full_combo_count
    match = (
        None if calculated is None or master_full_combo is None else calculated == master_full_combo
    )
    validation = {
        "rawNoteCount": ss.raw_note_count,
        "renderedNoteCount": judge.get("totalNotes") if judge else None,
        "authoredJudgedCount": judge.get("authoredJudgedCount") if judge else None,
        "generatedComboCount": judge.get("generatedComboCount") if judge else None,
        "generatedComboSkipCount": judge.get("generatedComboSkipCount") if judge else None,
        "calculatedComboCount": calculated,
        "masterFullComboCount": master_full_combo,
        "comboCountMatch": match,
        "comboCountDelta": (
            None if calculated is None or master_full_combo is None else calculated - master_full_combo
        ),
        "lineCount": judge.get("lineCount") if judge else None,
        "durationMs": judge.get("durationMs") if judge else None,
        "oracle": judge.get("oracle") if judge else None,
    }

    return {
        "schema": CHART_SCHEMA_VERSION,
        "identity": {
            "musicId": chart_ref.music_id,
            "difficulty": chart_ref.difficulty,
            "difficultyIndex": chart_ref.difficulty_index,
            "scoreId": chart_ref.score_id,
        },
        "source": source,
        "timing": {
            "bpm": ss.bpm,
            "signature": ss.sig,
            "tickConverter": {
                "implementation": "cassiopeia-tick-converter-port",
                "ppq": 480,
                "confidence": "CONFIRMED",
            },
        },
        "notes": notes,
        "metadata": {
            "fieldConfidence": FIELD_CONFIDENCE,
            "title": chart_ref.title,
            "playLevel": chart_ref.play_level,
            "masterSource": chart_ref.master_source,
            "validation": validation,
        },
    }
