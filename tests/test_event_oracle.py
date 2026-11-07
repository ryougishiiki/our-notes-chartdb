"""Exercise the actual pinned normalizer after oracle.cjs has been bundled."""
import json
from pathlib import Path
import subprocess

import pytest

from chartdb.events import build_events, build_derived
from chartdb.ss import parse_ss, bpm_events, sig_events
from chartdb.timing import TickConverter


def test_pinned_oracle_emits_complete_skill_fever_and_judgement_contract(tmp_path):
    oracle = Path(__file__).resolve().parents[1] / "tools/oracle/oracle.cjs"
    if not oracle.is_file():
        pytest.skip("run again after node tools/oracle/build.mjs")
    raw = {"meta": {"version": 100}, "score": {"events": {"bpm": [{"t": 0, "bpm": 120}],
           "sig": [{"t": 0, "sig": [4, 4]}], "skill": [960], "fever": [[1920, 3840]]},
           "notes": [{"t": 960, "pos": 0, "size": 4}, {"t": 960, "pos": 12, "size": 4},
                     {"type": "long", "node": [{"t": 1920, "pos": 0, "size": 4}, {"t": 3840, "pos": 12, "size": 4}]}]}}
    payload = json.dumps(raw)
    path = tmp_path / "score.bytes"
    path.write_text(payload, encoding="utf8")
    data = json.loads(subprocess.check_output(["node", str(oracle), str(path)], text=True))
    ss = parse_ss(payload)
    events = build_events(ss, TickConverter(bpm_events(ss), sig_events(ss)), "f" * 64)
    judges, scoring = build_derived(events, data, {"musicId": 1}, "f" * 64)
    assert data["timeline"]["fever"] == [{"index": 0, "startTick": 1920, "endTick": 3840, "startTimeMs": 2000, "endTimeMs": 4000}]
    assert judges["groups"][0] == [1000, 2, 2]
    assert any(group[2] < group[1] for group in judges["groups"])
    assert scoring["skills"] == [1000]
