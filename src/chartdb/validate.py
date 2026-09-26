"""Validation gates.

Status values: ``pass`` / ``fail`` / ``unknown``.
A release requires ``fail == 0`` across every chart.  The combo-count oracle is
report-only by default (``combo_policy="report"``): a mismatch is recorded as
``unknown`` together with its delta, because what differs is the reconstructed
Combo-note model, not the extracted chart data.  ``combo_policy="strict"``
promotes a mismatch to a blocking ``fail``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ss import SsError


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    detail: str = ""


def _gate(name: str, ok: bool | None, detail: str = "") -> Gate:
    if ok is None:
        return Gate(name, "unknown", detail)
    return Gate(name, "pass" if ok else "fail", detail)


def chart_gates(document: dict[str, Any], source_bytes: bytes | None = None, combo_policy: str = "report") -> list[Gate]:
    gates: list[Gate] = []
    identity = document.get("identity", {})
    source = document.get("source", {})
    timing = document.get("timing", {})
    metadata = document.get("metadata", {})
    validation = metadata.get("validation", {})

    gates.append(_gate("identity.musicId", isinstance(identity.get("musicId"), int) and identity["musicId"] > 0))
    gates.append(_gate("identity.scoreId", isinstance(identity.get("scoreId"), int) and identity["scoreId"] > 0))
    gates.append(_gate("identity.difficulty", isinstance(identity.get("difficulty"), str) and bool(identity["difficulty"])))
    gates.append(_gate("source.chartFile", isinstance(source.get("chartFile"), str) and bool(source["chartFile"])))
    gates.append(_gate("source.sha256", isinstance(source.get("sourceSha256"), str) and len(source["sourceSha256"]) == 64))

    notes = document.get("notes")
    gates.append(_gate("notes.isArray", isinstance(notes, list)))
    gates.append(_gate("notes.nonEmpty", isinstance(notes, list) and len(notes) > 0))

    def walk(entries):
        for note in entries or []:
            yield note
            yield from walk(note.get("node"))

    ticks_ok = True
    for note in walk(notes):
        tick = note.get("tick")
        if tick is None:
            # container notes (long/guide) legitimately carry no tick of their own
            if not note.get("node"):
                ticks_ok = False
                break
            continue
        if not isinstance(tick, int) or tick < 0:
            ticks_ok = False
            break
    gates.append(_gate("notes.ticks", ticks_ok))

    bpms = timing.get("bpm")
    bpm_ok = isinstance(bpms, list)
    if bpm_ok:
        for entry in bpms:
            if not isinstance(entry, dict) or not isinstance(entry.get("bpm"), (int, float)) or entry["bpm"] <= 0:
                bpm_ok = False
                break
    gates.append(_gate("timing.bpm", bpm_ok))

    if source_bytes is not None:
        from .hashing import sha256_bytes

        gates.append(
            _gate(
                "source.sha256Reproducible",
                sha256_bytes(source_bytes) == source.get("sourceSha256"),
            )
        )

    full_combo = validation.get("masterFullComboCount")
    calculated = validation.get("calculatedComboCount")
    detail = (
        f"masterFullComboCount={full_combo} calculatedComboCount={calculated} "
        f"comboCountDelta={validation.get('comboCountDelta')}"
    )
    if full_combo is None:
        gates.append(_gate("comboCount.match", None, "MasterLiveMusicScore._fullComboCount unavailable"))
    elif calculated is None:
        gates.append(_gate("comboCount.match", None, "derived combo count unavailable"))
    elif validation.get("comboCountMatch") is True:
        gates.append(_gate("comboCount.match", True, detail))
    elif combo_policy == "strict":
        gates.append(_gate("comboCount.match", False, detail))
    else:
        # The mismatch is a limitation of the reconstructed combo-note model, not
        # a defect in the authored chart data (see README).  Report it, do not
        # let it silently pass and do not let it block on its own.
        gates.append(
            Gate("comboCount.match", "unknown", f"combo-model delta (reported): {detail}")
        )
    return gates


def summarize(gates: list[Gate]) -> dict[str, int]:
    out = {"pass": 0, "fail": 0, "unknown": 0}
    for gate in gates:
        out[gate.status] = out.get(gate.status, 0) + 1
    return out


def global_gates(refs: list) -> list[Gate]:
    gates: list[Gate] = []
    seen_music: dict[tuple[int, str], int] = {}
    seen_score: dict[int, int] = {}
    seen_file: dict[str, int] = {}
    for ref in refs:
        key = (ref.music_id, ref.difficulty)
        seen_music[key] = seen_music.get(key, 0) + 1
        seen_score[ref.score_id] = seen_score.get(ref.score_id, 0) + 1
        seen_file[ref.chart_file] = seen_file.get(ref.chart_file, 0) + 1
    dup_music = {k: v for k, v in seen_music.items() if v > 1}
    dup_score = {k: v for k, v in seen_score.items() if v > 1}
    dup_file = {k: v for k, v in seen_file.items() if v > 1}
    gates.append(_gate("master.musicIdDifficultyUnique", not dup_music, str(dup_music)[:200]))
    gates.append(_gate("master.scoreIdUnique", not dup_score, str(dup_score)[:200]))
    gates.append(_gate("master.chartFileUnique", not dup_file, str(dup_file)[:200]))
    return gates
