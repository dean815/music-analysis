"""Tests for lead_sheet.py.

The fixture under tests/fixtures/synthetic is hand-built, not captured from a
recording: 20 bars at 120 BPM whose structure is known exactly, so assertions can
be specific rather than "doesn't crash". Layout is

    bar  1      C            intro
    bars 2-17   Am F C G x4  main body, four clean repetitions
    bar  18     D#m7         harmonic departure, still inside the body
    bars 19-21  Em           outro

which gives one dominant chord (C, five occurrences), an unambiguous four-bar
loop, and exactly one harmonic departure.

The departure sits outside the loop deliberately. Substituting a chord *inside*
the repeated figure drops that pattern to three occurrences, which ties it with
the three-bar F|C|G on `count * variety` — and since the search keeps a result
only when `score > best_score`, a tie resolves to the shorter loop. Fine
behaviour, but it makes for a fixture that tests the tie-break rather than the
structure it looks like it tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lead_sheet  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic"


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_bar_display_single_chord_is_not_slashed():
    assert lead_sheet.bar_display([(0.0, "Cmaj7"), (1.0, "Cmaj7")]) == "Cmaj7"


def test_bar_display_two_chords_uses_slash_notation():
    assert lead_sheet.bar_display([(0.0, "C"), (1.0, "G")]) == "C / G"


def test_bar_display_three_items_takes_majority_as_beat_one():
    # Edge rounding can emit three half-bars; majority lands on beat 1.
    assert lead_sheet.bar_display([(0.0, "C"), (1.0, "C"), (1.5, "G")]) == "C / G"


def test_bar_display_empty_is_repeat_marker():
    assert lead_sheet.bar_display([]) == "%"


@pytest.mark.parametrize(
    "label,root",
    [("C", "C"), ("Am", "A"), ("C#m7", "C#"), ("F#add9", "F#"), ("Gmaj7", "G")],
)
def test_chord_root_keeps_sharps(label, root):
    assert lead_sheet.chord_root(label) == root


def test_map_bars_groups_two_half_bars_per_bar_by_index():
    half = [(0.0, "C"), (1.0, "C"), (2.0, "G"), (3.0, "G")]
    total, bars, times = lead_sheet.map_bars(half)
    assert total == 2
    assert bars == {1: "C", 2: "G"}
    assert times == {1: 0.0, 2: 2.0}


def test_map_bars_handles_odd_trailing_half_bar():
    half = [(0.0, "C"), (1.0, "C"), (2.0, "G")]
    total, bars, _ = lead_sheet.map_bars(half)
    assert total == 2
    assert bars[2] == "G"


def test_find_dominant_loop_prefers_variety_over_raw_count():
    # "C" alone repeats more often, but the 2-bar C|G alternation has variety,
    # and score is count * variety.
    bars = {i: ("C" if i % 2 else "G") for i in range(1, 17)}
    found = lead_sheet.find_dominant_loop(bars, 1, 16)
    assert found is not None
    n, chords = found
    assert n == 2
    assert set(chords) == {"C", "G"}


def test_find_dominant_loop_returns_none_without_repetition():
    bars = {i: c for i, c in enumerate("ABCDEFGH", start=1)}
    assert lead_sheet.find_dominant_loop(bars, 1, 8) is None


# ── build() against the fixture ───────────────────────────────────────────────


def test_build_detects_known_structure():
    s = lead_sheet.build(FIXTURE)
    assert s.total_bars == 21
    assert s.intro_end == 1
    assert s.body_start == 2
    assert s.outro_start == 19
    assert s.body_end == 18
    assert s.loop == (4, ["Am", "F", "C", "G"])


def test_build_finds_the_single_departure():
    s = lead_sheet.build(FIXTURE)
    assert [(bn, ch) for bn, ch, _ in s.departures] == [(18, "D#m7")]


def test_loop_tie_breaks_toward_the_shorter_pattern():
    # count * variety ties between a 4-bar and a 3-bar reading are resolved by
    # `score > best_score` being strict, so the first (shorter) length wins.
    bars = {i: c for i, c in enumerate(["Am", "F", "C", "G"] * 3, start=1)}
    bars[9] = "D#m7"  # breaks one repetition of the 4-bar figure
    found = lead_sheet.find_dominant_loop(bars, 1, 12)
    assert found is not None and found[0] == 3


def test_build_reads_metadata_from_summary():
    s = lead_sheet.build(FIXTURE)
    assert (s.key_root, s.key_mode) == ("C", "Major")
    assert s.bpm == 120.0
    assert s.duration == 42.0
    assert s.title == "synthetic"
    assert s.half_time_suggestion is None


def test_explicit_title_and_artist_win():
    s = lead_sheet.build(FIXTURE, title="Given", artist="Someone")
    assert s.title == "Given"
    assert s.artist == "Someone"


def test_bpm_override_replaces_detected_tempo():
    s = lead_sheet.build(FIXTURE, bpm=60.0)
    assert s.bpm == 60.0
    assert s.detected_bpm == 120.0


def test_simplify_false_skips_loop_detection():
    s = lead_sheet.build(FIXTURE, simplify=False)
    assert s.loop is None
    assert s.departures == []


# ── Overrides ─────────────────────────────────────────────────────────────────


def test_loop_len_override_forces_that_length():
    s = lead_sheet.build(FIXTURE, loop_len=2)
    assert s.loop is not None and s.loop[0] == 2


def test_intro_end_override_moves_the_body():
    s = lead_sheet.build(FIXTURE, intro_end=4)
    assert s.intro_end == 4
    assert s.body_start == 5


def test_outro_start_override_moves_the_body_end():
    s = lead_sheet.build(FIXTURE, outro_start=15)
    assert s.outro_start == 15
    assert s.body_end == 14


@pytest.mark.parametrize("bad", [-5, 0, 9999])
def test_structural_overrides_are_clamped_not_fatal(bad):
    # An interactive caller moves a control without knowing the bar count.
    s = lead_sheet.build(FIXTURE, intro_end=bad, outro_start=bad, loop_len=bad)
    assert 1 <= s.intro_end <= s.total_bars
    assert s.outro_start is None or 1 <= s.outro_start <= s.total_bars


def test_missing_directory_raises_rather_than_exiting(tmp_path):
    # A GUI process must not be killed by sys.exit() from deep in the stack.
    with pytest.raises(FileNotFoundError):
        lead_sheet.build(tmp_path)


def test_missing_chart_raises_rather_than_exiting(tmp_path):
    (tmp_path / "summary.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        lead_sheet.build(tmp_path)


# ── Rendering ─────────────────────────────────────────────────────────────────


def test_render_includes_sections_and_repeat_signs():
    out = lead_sheet.render_ascii(lead_sheet.build(FIXTURE))
    assert "INTRO" in out
    assert "MAIN BODY" in out
    assert "OUTRO" in out
    assert "‖:" in out and ":‖" in out
    assert "4-bar loop" in out


def test_render_reports_the_departure():
    out = lead_sheet.render_ascii(lead_sheet.build(FIXTURE))
    assert "Harmonic departures" in out
    assert "D#m7" in out


def test_bars_per_line_changes_layout_not_content():
    # simplify=False renders the body verbatim (17 bars), which actually wraps.
    # With loop detection on, every section fits one line at both widths and the
    # comparison is vacuous.
    sheet = lead_sheet.build(FIXTURE, simplify=False)
    four = lead_sheet.render_ascii(sheet, bars_per_line=4)
    eight = lead_sheet.render_ascii(sheet, bars_per_line=8)
    assert four != eight
    assert four.count("\n") > eight.count("\n")
    for chord in ("Am", "F", "C", "G", "D#m7", "Em"):
        assert chord in four and chord in eight


@pytest.mark.parametrize("bpl", [0, -3])
def test_bars_per_line_is_clamped(bpl):
    lead_sheet.render_ascii(lead_sheet.build(FIXTURE), bars_per_line=bpl)


def test_render_is_deterministic():
    a = lead_sheet.render_ascii(lead_sheet.build(FIXTURE))
    b = lead_sheet.render_ascii(lead_sheet.build(FIXTURE))
    assert a == b
