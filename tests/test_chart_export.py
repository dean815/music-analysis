"""Tests for chart_export.py's seconds-to-bars helpers.

The engines are not run here (PyTorch is not a test dependency); the inputs are
what they return — beat and downbeat times in seconds, and BTC's Harte-labelled
segments — built by hand so every bar boundary is known.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chart_export import analysis_result, bar_edges, chord_at, harte_to_symbol, meter_numerator  # noqa: E402


def grid(bars: int, per_bar: int = 4, beat: float = 0.5, start: float = 0.0):
    beats = start + beat * np.arange(bars * per_bar)
    return beats, beats[::per_bar]


def test_harte_labels_render_as_chart_symbols():
    assert harte_to_symbol("D:maj") == "D"
    assert harte_to_symbol("D") == "D"
    assert harte_to_symbol("F#:min7") == "F#m7"
    assert harte_to_symbol("B:hdim7") == "Bm7b5"
    assert harte_to_symbol("C:maj/E") == "C/E"
    assert harte_to_symbol("N") == "N.C."
    assert harte_to_symbol("X") == "N.C."


def test_a_scale_degree_bass_is_dropped():
    # The app reads a bass only if it parses as a pitch class; `/3` would not.
    assert harte_to_symbol("C:maj/3") == "C"
    assert harte_to_symbol("A:min/b7") == "Am"


def test_one_bar_per_downbeat_and_the_last_bar_gets_the_median_length():
    beats, downs = grid(3)
    assert bar_edges(beats, downs) == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]


def test_a_downbeat_under_half_a_bar_after_the_last_is_a_glitch():
    beats, downs = grid(3)
    glitched = np.sort(np.append(downs, 2.5))
    assert bar_edges(beats, glitched) == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]


def test_meter_is_the_common_beat_count_between_downbeats():
    assert meter_numerator(*grid(4, per_bar=3)) == 3
    assert meter_numerator(*grid(4, per_bar=4)) == 4


def test_chord_at_uses_the_segment_sounding_and_holds_the_last_past_the_end():
    segments = [(0.0, 1.0, "D:maj"), (1.0, 2.0, "E:maj")]
    assert chord_at(segments, 0.5) == "D"
    assert chord_at(segments, 1.0) == "E"
    assert chord_at(segments, 9.0) == "E"
    assert chord_at([], 0.0) == "N.C."


def test_a_change_on_beat_three_splits_the_bar():
    beats, downs = grid(2)
    segments = [(0.0, 3.0, "D:maj"), (3.0, 4.0, "E:maj")]
    result = analysis_result("Vamp", beats, downs, segments, slots=2)
    assert result == {
        "version": 1,
        "title": "Vamp",
        "tempoBpm": 120.0,
        "meter": {"numerator": 4, "denominator": 4},
        "bars": [["D", "D"], ["D", "E"]],
    }
