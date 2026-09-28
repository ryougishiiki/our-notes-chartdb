"""Core unit tests (run: PYTHONPATH=src python -m pytest tests -q)."""

from __future__ import annotations

import json

from chartdb.addressables import remote_url
from chartdb.discover import CHART_KEY, MUSIC_SCORE_MARKER
from chartdb.ss import SsError, parse_ss
from chartdb.state import diff, has_changes
from chartdb.timing import TickConverter, BpmEvent, SigEvent


def test_tick_converter_matches_native_sample():
    # Verified against a real chart: tick 9600 at 190 BPM -> 6315 ms.
    converter = TickConverter([BpmEvent(0, 190.0)], [SigEvent(0, (4, 4))])
    assert converter.tick_to_time_ms(9600) == 6315
    assert converter.tick_to_time_ms(0) == 0


def test_tick_converter_handles_bpm_changes():
    converter = TickConverter([BpmEvent(0, 120.0), BpmEvent(480, 240.0)], [])
    # 480 ticks at 120bpm = 500ms, then 480 ticks at 240bpm = 250ms
    assert converter.tick_to_time_ms(480) == 500
    assert converter.tick_to_time_ms(960) == 750


def test_chart_key_pattern():
    key = "live_assets_live_musicscore_0001_0001_03_be02901aec561cfa69f6a0d700190757.bundle"
    match = CHART_KEY.match(key)
    assert match and f"{match.group(1)}/{match.group(2)}_{match.group(3)}" == "0001/0001_03"
    assert MUSIC_SCORE_MARKER in key
    assert CHART_KEY.match("live_assets_live_musicscore_dev_trace_guide_music_x.bundle") is None


def test_remote_url_reanchors_dummy_net():
    # Captured verbatim from the live Our Notes catalog for bundle 0001_00.
    parts = ["live_assets_x.bundle", "asset/Android", "dummy.net", "https:/"]
    url = remote_url(parts, "https://cdn.example/prod/asset/Android")
    assert url == "https://cdn.example/prod/asset/Android/live_assets_x.bundle"


def test_remote_url_is_total():
    # A stray RuntimePath token without an opening brace must not raise.
    assert remote_url(["RuntimePath}"], "https://cdn.example") == "RuntimePath%7D"


def test_ss_parse_leaf_and_container():
    document = {
        "meta": {"version": 100},
        "score": {
            "events": {"bpm": [{"t": 0, "bpm": 190}], "sig": [{"t": 0, "sig": [4, 4]}]},
            "notes": [
                {"t": 960, "pos": 12, "size": 8, "crit": True},
                {"type": "flick", "t": 1920, "pos": 0, "size": 10, "dir": "left"},
                {"type": "long", "node": [{"t": 2880, "pos": 3, "size": 6}, {"t": 3840, "pos": 9, "size": 6}]},
            ],
        },
    }
    root = parse_ss(json.dumps(document))
    assert root.version == 100
    assert root.raw_note_count == 3
    tap, flick, long_note = root.notes
    assert tap.type_effective == "tap" and tap.crit and tap.t == 960
    assert flick.dir_effective == "left"
    assert long_note.container and long_note.t is None and len(long_note.node) == 2
    assert long_note.node[0].raw == {"t": 2880, "pos": 3, "size": 6}


def test_ss_rejects_unplaceable_leaf():
    bad = {"score": {"notes": [{"pos": 1, "size": 4}]}}
    try:
        parse_ss(json.dumps(bad))
    except SsError:
        return
    raise AssertionError("a leaf note without a tick must be rejected")


def test_release_gate_skips_when_chart_diff_is_empty():
    change = diff({"100001/expert": "same"}, {"100001/expert": "same"})
    assert not has_changes(change)


def test_release_gate_publishes_for_new_changed_or_removed_charts():
    assert has_changes(diff({}, {"100001/expert": "new"}))
    assert has_changes(diff({"100001/expert": "old"}, {"100001/expert": "changed"}))
    assert has_changes(diff({"100001/expert": "removed"}, {}))
