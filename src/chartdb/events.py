"""Versioned authored-event and canonical judgement contracts, independent of APKs.

Fever endpoints are authored boundaries, not evidence of actual player activation.
The complete judgement timeline is retained for future boundary timing consumers.
"""
from __future__ import annotations

import math
from pathlib import Path
import json

EVENT_SCHEMA = "chart-events/1"
JUDGEMENT_SCHEMA = "chart-judgements/1"
SCORE_SCHEMA = "onsm-score-timing/1"
CONTRACTS = {"events": EVENT_SCHEMA, "judgements": JUDGEMENT_SCHEMA, "scoreTiming": SCORE_SCHEMA}


def normalizer_revision() -> str:
    lock = json.loads((Path(__file__).resolve().parents[2] / "tools/oracle/vendor.json").read_text("utf-8"))
    return next(repo["commit"] for repo in lock["repositories"] if repo["name"] == "cassiopeia-plugin-our-notes")


def _tick(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("event tick must be finite and non-negative")
    return value


def build_events(ss, converter, source_sha256: str) -> dict:
    skills = [{"index": i, "tick": _tick(t), "timeMs": converter.tick_to_time_ms(t)} for i, t in enumerate(ss.skill)]
    fever = []
    ordered = sorted(enumerate(ss.fever), key=lambda pair: pair[1][0] if pair[1] else -1)
    for i, (source_index, pair) in enumerate(ordered):
        if len(pair) != 2:
            raise ValueError("fever event must have exactly two endpoints")
        start, end = map(_tick, pair)
        if end <= start:
            raise ValueError("fever endpoints must be increasing")
        fever.append({"index": i, "sourceIndex": source_index, "startTick": start, "endTick": end,
                      "startTimeMs": converter.tick_to_time_ms(start), "endTimeMs": converter.tick_to_time_ms(end)})
    return {"schema": EVENT_SCHEMA, "sourceSha256": source_sha256, "clock": "authored-music-time-ms",
            "skills": skills, "fever": fever, "raw": {"skill": ss.skill, "fever": ss.fever, "call": ss.call}}


def build_derived(events: dict, judge: dict, identity: dict, source_sha256: str) -> tuple[dict, dict]:
    if not isinstance(judge.get("timeline"), dict) or not isinstance(judge.get("judgementGroups"), list):
        raise ValueError("oracle lacks timeline contract; rebuild the pinned oracle")
    # Use both independent ports to catch accidental event conversion drift.
    timeline = judge["timeline"]
    if timeline.get("skills") != events["skills"]:
        raise ValueError("skill timing differs between TickConverter ports")
    expected_fever = [{k: v for k, v in f.items() if k != "sourceIndex"} for f in events["fever"]]
    if timeline.get("fever") != expected_fever:
        raise ValueError("fever timing differs between TickConverter ports")
    groups = judge["judgementGroups"]
    previous = -1
    for group in groups:
        if not isinstance(group, list) or len(group) != 3:
            raise ValueError("invalid judgement group")
        time, total, active = group
        if (not isinstance(time, int) or isinstance(time, bool) or time <= previous or time < 0
                or not isinstance(total, int) or isinstance(total, bool) or not 1 <= total <= 64
                or not isinstance(active, int) or isinstance(active, bool) or not 0 <= active <= total):
            raise ValueError("invalid judgement group values/order")
        previous = time
    if len(groups) > 25000 or sum(g[1] for g in groups) != judge.get("judgedCount"):
        raise ValueError("judgement timeline count differs from canonical combo count")
    starts = sorted(s["timeMs"] for s in events["skills"])
    if len(starts) > 64 or len(set(starts)) != len(starts):
        raise ValueError("ambiguous or excessive skill events")
    revision = normalizer_revision()
    judgements = {"schema": JUDGEMENT_SCHEMA, "sourceSha256": source_sha256, "normalizer": revision,
                  "groups": groups, "totalCount": judge["judgedCount"]}
    scoring = {"schema": SCORE_SCHEMA, "identity": identity, "sourceSha256": source_sha256,
               "normalizer": revision, "skills": starts,
               "groups": [g for g in groups if any(start <= g[0] < start + 5000 for start in starts)]}
    return judgements, scoring


def validate_contracts(document: dict) -> bool:
    """Check a published document independently of the extraction call site."""
    try:
        events = document["timing"]["events"]
        judgement = document["judgements"]
        score = document["scoreTiming"]
        source = document["source"]["sourceSha256"]
        if (events["schema"] != EVENT_SCHEMA or judgement["schema"] != JUDGEMENT_SCHEMA
                or score["schema"] != SCORE_SCHEMA or score["identity"] != document["identity"]
                or any(item["sourceSha256"] != source for item in (events, judgement, score))):
            return False
        from .timing import TickConverter
        from .ss import bpm_events, sig_events, parse_ss
        # Reuse the production conversion, with the preserved authored event fields.
        raw = events["raw"]
        ss = parse_ss(json.dumps({"score": {"events": {"bpm": document["timing"]["bpm"],
                "sig": document["timing"]["signature"], **raw}, "notes": []}}))
        expected = build_events(ss, TickConverter(bpm_events(ss), sig_events(ss)), source)
        if events != expected:
            return False
        timeline = {"skills": events["skills"], "fever": [{k: v for k, v in f.items() if k != "sourceIndex"} for f in events["fever"]]}
        derived, scoring = build_derived(events, {"timeline": timeline, "judgementGroups": judgement["groups"],
                "judgedCount": document["metadata"]["validation"]["calculatedComboCount"]}, document["identity"], source)
        return judgement == derived and score == scoring
    except (KeyError, TypeError, ValueError, StopIteration, OverflowError):
        return False
