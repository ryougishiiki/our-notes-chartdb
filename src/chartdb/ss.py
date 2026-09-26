"""Raw SS chart model.

Only structure and the fields that are literally present in the JSON are
modelled here.  Absent fields are preserved as ``None`` plus an ``effective``
value derived from the audited parser in
cassiopeia-plugin-our-notes ``src/core/parser.ts`` (which is what the game-side
``SsRootDeserializer`` produces).  Nothing is invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

NOTE_TYPES = ("tap", "flick", "trace", "long", "guide", "node")
FLICK_DIRECTIONS = ("up", "left", "right", "down")
EASES = ("linear", "in", "out")
FADES = ("none", "in", "out")
DEFAULT_SIZE = 6.0


class SsError(ValueError):
    """Raised when a chart payload is not a valid SS document."""


def _object(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise SsError(f"{path} must be an object")
    return value


def _number(value: Any, path: str, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        raise SsError(f"{path} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    if default is not None:
        return default
    raise SsError(f"{path} must be a number")


def _enum(value: Any, allowed: tuple[str, ...], path: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise SsError(f"{path} has invalid value {value!r}; expected one of {allowed}")
    return value


@dataclass
class SsNote:
    type_raw: str | None
    type_effective: str
    container: bool
    t: int | None
    pos_raw: float | str | None
    pos: float | None
    pos_auto: bool
    size_raw: float | None
    size: float | None
    crit_raw: bool | None
    crit: bool
    dir_raw: str | None
    dir_effective: str
    ease_raw: Any
    ease_l: str
    ease_r: str
    visible_raw: bool | None
    visible: bool
    alpha_raw: str | None
    alpha_effective: str
    node: list["SsNote"] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_raw_dict(self) -> dict:
        """Original JSON fields, verbatim, preserving unknown keys."""
        return dict(self.raw)


def parse_note(value: Any, path: str) -> SsNote:
    item = _object(value, path)
    type_raw = item.get("type")
    type_effective = _enum(type_raw, NOTE_TYPES, f"{path}.type", "tap")

    # long/guide notes are containers: their own t/pos/size are absent and the
    # geometry lives in node[].  Leaf notes must be placeable.
    node_raw = item.get("node")
    container = isinstance(node_raw, list) and len(node_raw) > 0
    if node_raw is not None and not isinstance(node_raw, list):
        raise SsError(f"{path}.node must be an array")

    t_raw = item.get("t")
    t: int | None = None
    if t_raw is None:
        if not container:
            raise SsError(f"{path}.t is required on a leaf note")
    else:
        number = _number(t_raw, f"{path}.t")
        if number is None or number != int(number):
            raise SsError(f"{path}.t must be an integer tick")
        if number < 0:
            raise SsError(f"{path}.t must not be negative")
        t = int(number)

    pos_raw = item.get("pos")
    if pos_raw is None:
        if not container:
            raise SsError(f"{path}.pos is required on a leaf note")
        pos_auto, pos = False, None
    elif pos_raw == "auto":
        pos_auto, pos = True, None
    else:
        pos_auto, pos = False, _number(pos_raw, f"{path}.pos")

    size_raw = item.get("size")
    size: float | None = None
    if container and size_raw is None:
        size = None
    else:
        size = _number(size_raw, f"{path}.size", DEFAULT_SIZE)
        assert size is not None

    crit_raw = item.get("crit")
    if crit_raw is not None and not isinstance(crit_raw, bool):
        raise SsError(f"{path}.crit must be a boolean")
    crit = crit_raw is True

    dir_raw = item.get("dir")
    dir_effective = _enum(dir_raw, FLICK_DIRECTIONS, f"{path}.dir", "up")

    ease_raw = item.get("ease")
    if isinstance(ease_raw, list):
        if len(ease_raw) != 2:
            raise SsError(f"{path}.ease must be a string or two strings")
        ease_l = _enum(ease_raw[0], EASES, f"{path}.ease[0]", "linear")
        ease_r = _enum(ease_raw[1], EASES, f"{path}.ease[1]", "linear")
    else:
        ease_l = ease_r = _enum(ease_raw, EASES, f"{path}.ease", "linear")

    visible_raw = item.get("visible")
    if visible_raw is not None and not isinstance(visible_raw, bool):
        raise SsError(f"{path}.visible must be a boolean")
    visible = visible_raw is not False

    alpha_raw = item.get("alpha")
    alpha_effective = _enum(alpha_raw, FADES, f"{path}.alpha", "none")

    node_raw = item.get("node")
    node: list[SsNote] = []
    if node_raw is not None:
        if not isinstance(node_raw, list):
            raise SsError(f"{path}.node must be an array")
        for index, entry in enumerate(node_raw):
            node.append(parse_note(entry, f"{path}.node[{index}]"))

    return SsNote(
        type_raw=type_raw,
        type_effective=type_effective,
        container=container,
        t=t,
        pos_raw=pos_raw,
        pos=pos,
        pos_auto=pos_auto,
        size_raw=size_raw,
        size=size,
        crit_raw=crit_raw,
        crit=crit,
        dir_raw=dir_raw,
        dir_effective=dir_effective,
        ease_raw=ease_raw,
        ease_l=ease_l,
        ease_r=ease_r,
        visible_raw=visible_raw,
        visible=visible,
        alpha_raw=alpha_raw,
        alpha_effective=alpha_effective,
        node=node,
        raw=item,
    )


@dataclass
class SsRoot:
    version: Any
    bpm: list[dict]
    sig: list[dict]
    skill: list[float]
    fever: list[list[float]]
    call: list[dict]
    notes: list[SsNote]
    meta_raw: dict
    score_raw: dict

    @property
    def raw_note_count(self) -> int:
        return len(self.notes)


def parse_ss(payload: bytes | str) -> SsRoot:
    if isinstance(payload, (bytes, bytearray)):
        text = bytes(payload).decode("utf-8-sig")
    else:
        text = payload.lstrip("\ufeff")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise SsError(f"chart payload is not valid JSON: {error}") from error
    root = _object(value, "root")
    score = _object(root.get("score"), "root.score")
    meta = root.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    events = score.get("events")
    events = events if isinstance(events, dict) else {}

    for key in ("bpm", "sig", "skill", "fever", "call"):
        if key in events and not isinstance(events[key], list):
            raise SsError(f"score.events.{key} must be an array")

    notes_raw = score.get("notes")
    if not isinstance(notes_raw, list):
        raise SsError("score.notes must be an array")
    notes = [parse_note(entry, f"score.notes[{index}]") for index, entry in enumerate(notes_raw)]

    return SsRoot(
        version=meta.get("version"),
        bpm=list(events.get("bpm", [])),
        sig=list(events.get("sig", [])),
        skill=[float(v) for v in events.get("skill", [])],
        fever=[list(map(float, entry)) for entry in events.get("fever", [])],
        call=list(events.get("call", [])),
        notes=notes,
        meta_raw=meta,
        score_raw=score,
    )


def bpm_events(root: SsRoot):
    from .timing import BpmEvent

    out = []
    for index, raw in enumerate(root.bpm):
        if not isinstance(raw, dict):
            raise SsError(f"score.events.bpm[{index}] must be an object")
        out.append(BpmEvent(int(raw.get("t", 0)), float(raw.get("bpm", 0))))
    return out


def sig_events(root: SsRoot):
    from .timing import SigEvent

    out = []
    for index, raw in enumerate(root.sig):
        if not isinstance(raw, dict):
            raise SsError(f"score.events.sig[{index}] must be an object")
        sig = raw.get("sig")
        if not isinstance(sig, list) or len(sig) < 2:
            raise SsError(f"score.events.sig[{index}].sig must have two values")
        out.append(SigEvent(int(raw.get("t", 0)), (int(sig[0]), int(sig[1]))))
    return out
