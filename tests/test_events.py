from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from chartdb.events import build_events, validate_contracts
from chartdb.normalize import build_chart_document
from chartdb.ss import parse_ss, bpm_events, sig_events
from chartdb.timing import TickConverter
from chartdb.hashing import canonical_json, sha256_bytes
from chartdb.db import DatabaseBuilder
from chartdb.state import diff, has_changes, load_state, save_state, STATE_SCHEMA


def fixture():
    raw = {"score": {"events": {"bpm": [{"t": 0, "bpm": 120}, {"t": 1920, "bpm": 240}],
            "sig": [{"t": 0, "sig": [4, 4]}], "skill": [960], "fever": [[1440, 2880]],
            "call": [{"t": 0, "timing": [1, 0]}]}, "notes": [{"t": 960, "pos": 0, "size": 4}]}}
    payload = json.dumps(raw).encode()
    ss = parse_ss(payload)
    event = build_events(ss, TickConverter(bpm_events(ss), sig_events(ss)), sha256_bytes(payload))
    canonical_fever = [{k: v for k, v in f.items() if k != "sourceIndex"} for f in event["fever"]]
    judge = {"judgedCount": 6, "authoredJudgedCount": 5, "generatedComboCount": 1, "generatedComboSkipCount": 0,
             "timeline": {"skills": event["skills"], "fever": canonical_fever},
             "judgementGroups": [[500, 1, 1], [1000, 2, 2], [1250, 1, 0], [1500, 1, 1], [6500, 1, 1]]}
    ref = SimpleNamespace(music_id=100116, score_id=10011603, difficulty="expert", difficulty_index=3,
                          full_combo_count=6, title="", play_level=25, master_source="official-master-cdn")
    source = {"sourceSha256": sha256_bytes(payload), "chartFile": "0116/0116_03"}
    return ss, ref, source, judge


def document():
    return build_chart_document(*fixture())


def test_full_timeline_and_window_subset_are_separate_contracts():
    doc = document()
    assert validate_contracts(doc)
    assert len(doc["judgements"]["groups"]) == 5
    assert doc["judgements"]["totalCount"] == 6
    assert doc["scoreTiming"]["skills"] == [1000]
    assert doc["scoreTiming"]["groups"] == [[1000, 2, 2], [1250, 1, 0], [1500, 1, 1]]
    assert doc["scoreTiming"]["identity"] == doc["identity"]


def test_fever_preserves_both_ticks_and_bpm_aware_times():
    events = document()["timing"]["events"]
    assert events["clock"] == "authored-music-time-ms"
    assert events["raw"]["fever"] == [[1440.0, 2880.0]]
    fever = events["fever"][0]
    assert (fever["startTick"], fever["endTick"]) == (1440, 2880)
    assert (fever["startTimeMs"], fever["endTimeMs"]) == (1500, 2500)
    assert events["raw"]["call"] == [{"t": 0, "timing": [1, 0]}]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_event_values_fail_export(value):
    ss, ref, source, judge = fixture()
    ss.skill = [value]
    with pytest.raises(ValueError):
        build_chart_document(ss, ref, source, judge)


@pytest.mark.parametrize("pair", [[2, 1], [1], [1, 1], [1, 2, 3]])
def test_invalid_fever_pair_fails(pair):
    ss, ref, source, judge = fixture()
    ss.fever = [pair]
    with pytest.raises(ValueError):
        build_chart_document(ss, ref, source, judge)


def test_independent_event_converter_drift_is_rejected():
    ss, ref, source, judge = fixture()
    judge["timeline"]["skills"][0]["timeMs"] += 1
    with pytest.raises(ValueError, match="ports"):
        build_chart_document(ss, ref, source, judge)


@pytest.mark.parametrize("groups", [[[1000, 0, 0]], [[1000, 1, 2]], [[1000, 1, 1], [1000, 1, 1]],
                                  [[1000, 1, 1], [500, 1, 1]], [[float("nan"), 6, 6]]])
def test_bad_judgement_groups_are_rejected(groups):
    ss, ref, source, judge = fixture()
    judge["judgementGroups"] = groups
    with pytest.raises(ValueError):
        build_chart_document(ss, ref, source, judge)


@pytest.mark.parametrize("field", ["timing", "judgements", "scoreTiming"])
def test_inconsistent_document_contract_fails(field):
    doc = document()
    target = doc["timing"]["events"] if field == "timing" else doc[field]
    target["sourceSha256"] = "a" * 64
    assert not validate_contracts(doc)


def test_old_oracle_is_not_silently_accepted():
    ss, ref, source, judge = fixture()
    del judge["judgementGroups"]
    with pytest.raises(ValueError, match="rebuild"):
        build_chart_document(ss, ref, source, judge)


def test_metadata_only_change_triggers_output_diff_and_stable_rebuild_does_not():
    doc = document()
    before = copy.deepcopy(doc)
    del before["scoreTiming"]
    hashes = []
    for item in [before, doc, copy.deepcopy(doc)]:
        builder = DatabaseBuilder("chartdoc/1")
        hashes.append(builder.add(item, item["source"]["sourceSha256"])["normalizedSha256"])
    assert has_changes(diff({"100116/expert": hashes[0]}, {"100116/expert": hashes[1]}))
    assert not has_changes(diff({"100116/expert": hashes[1]}, {"100116/expert": hashes[2]}))


def test_legacy_state_migrates_once_without_losing_inventory(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema": "chartdb-state/1", "charts": {"100116/expert": "source-hash"}}))
    old = load_state(path)
    assert has_changes(diff(old["charts"], {"100116/expert": "normalized-hash"}))
    save_state(path, {"100116/expert": "normalized-hash"}, "revision")
    current = load_state(path)
    assert current["schema"] == STATE_SCHEMA
    assert not has_changes(diff(current["charts"], {"100116/expert": "normalized-hash"}))
