"""Timing: SS tick -> music time.

This is a faithful Python port of the audited ``TickConverter`` in
haneoka-gakuen/cassiopeia ``src/core/timing.ts`` (MPL-2.0), which itself mirrors
the native ``SsTickConverter``.  The single-precision steps are intentional: the
native code multiplies ``bpm * 480`` in ``float`` before the double division,
and stores BPM-change times rounded to even milliseconds.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

PPQ = 480
MAX_SUPPORTED_BPM = 10_000.0


def fround(value: float) -> float:
    """IEEE-754 binary32 rounding, matching JS ``Math.fround``."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def round_to_even(value: float) -> int:
    floor = int(value // 1)
    fraction = value - floor
    if fraction < 0.5:
        return floor
    if fraction > 0.5:
        return floor + 1
    return floor if floor % 2 == 0 else floor + 1


def ticks_per_measure(numerator: float, denominator: float) -> float:
    return (numerator * 1920) / denominator


@dataclass(frozen=True)
class BpmEvent:
    t: int
    bpm: float


@dataclass(frozen=True)
class SigEvent:
    t: int
    sig: tuple[int, int]


@dataclass(frozen=True)
class _BpmSegment:
    start_tick: int
    start_time_ms: int
    event_time_ms: int
    bpm: float


@dataclass(frozen=True)
class _SigSegment:
    start_tick: int
    start_bar: int
    event_time_ms: int
    ticks_per_measure: float
    quarter_beats_per_measure: float


@dataclass(frozen=True)
class BarPosition:
    bar: int
    progress: float


def _tick_duration_ms(delta_tick: float, bpm: float) -> float:
    return (delta_tick * 60_000) / fround(bpm * PPQ)


class TickConverter:
    def __init__(self, bpms: Sequence[BpmEvent], signatures: Sequence[SigEvent] = ()):
        bpm_points = sorted(bpms, key=lambda p: p.t) if bpms else [BpmEvent(0, 120.0)]
        if bpm_points[0].t > 0:
            bpm_points = [BpmEvent(0, 120.0), *bpm_points]
        self.bpm_segments: list[_BpmSegment] = []
        accumulated = 0.0
        previous: _BpmSegment | None = None
        for point in bpm_points:
            if not (0 < point.bpm <= MAX_SUPPORTED_BPM):
                raise ValueError(f"invalid BPM event at tick {point.t}: {point.bpm}")
            if previous is not None:
                accumulated += _tick_duration_ms(point.t - previous.start_tick, previous.bpm)
            start_time_ms = round_to_even(accumulated)
            previous = _BpmSegment(point.t, start_time_ms, start_time_ms, fround(point.bpm))
            self.bpm_segments.append(previous)

        sig_points = sorted(signatures, key=lambda p: p.t) if signatures else [SigEvent(0, (4, 4))]
        if sig_points[0].t > 0:
            sig_points = [SigEvent(0, (4, 4)), *sig_points]
        self.sig_segments: list[_SigSegment] = []
        previous_sig: _SigSegment | None = None
        for point in sig_points:
            numerator, denominator = point.sig
            if numerator <= 0 or denominator <= 0:
                raise ValueError(f"invalid signature event at tick {point.t}: {point.sig}")
            measure = ticks_per_measure(numerator, denominator)
            start_bar = (
                previous_sig.start_bar
                + int((point.t - previous_sig.start_tick) // previous_sig.ticks_per_measure)
                if previous_sig is not None
                else 0
            )
            previous_sig = _SigSegment(
                point.t,
                start_bar,
                self.tick_to_time_ms(point.t),
                measure,
                fround(fround(numerator * 4) / denominator),
            )
            self.sig_segments.append(previous_sig)

    def tick_to_time_ms(self, tick: float) -> int:
        segment = self.bpm_segments[0]
        for candidate in self.bpm_segments:
            if candidate.start_tick > tick:
                break
            segment = candidate
        return int((segment.start_time_ms + _tick_duration_ms(tick - segment.start_tick, segment.bpm)) // 1)

    def tick_to_bar_position(self, tick: float) -> BarPosition:
        segment = self.sig_segments[0]
        for candidate in self.sig_segments:
            if candidate.start_tick > tick:
                break
            segment = candidate
        delta = tick - segment.start_tick
        bar_delta = int(delta // segment.ticks_per_measure)
        return BarPosition(
            bar=segment.start_bar + bar_delta,
            progress=fround((delta - bar_delta * segment.ticks_per_measure) / segment.ticks_per_measure),
        )

    def beat(self, tick: float) -> float:
        return tick / PPQ
