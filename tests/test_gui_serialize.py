"""Tests for the LeadSheet -> JSON layer.

This module owns the layout decisions render_ascii also makes (section order,
bar membership, repeat signs). Testing it here rather than through HTTP keeps
the assertions about shape, and means these run without fastapi installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lead_sheet  # noqa: E402
from gui import serialize  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic"


@pytest.fixture
def sheet():
    return lead_sheet.build(FIXTURE)


# ── timecode ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "seconds,expected",
    [(0.0, "0:00"), (5.4, "0:05"), (65.0, "1:05"), (125.9, "2:05"), (600.0, "10:00")],
)
def test_timecode_formats_as_minutes_and_padded_seconds(seconds, expected):
    assert serialize.timecode(seconds) == expected


# ── sections ──────────────────────────────────────────────────────────────────


def test_sections_follow_the_ascii_order(sheet):
    assert [s["kind"] for s in serialize.sections(sheet)] == ["intro", "loop", "outro"]


def test_intro_section_holds_the_intro_bars(sheet):
    intro = serialize.sections(sheet)[0]
    assert [b["number"] for b in intro["bars"]] == [1]
    assert intro["bars"][0]["display"] == "C"
    assert intro["repeat"] is False


def test_loop_section_is_marked_repeating_and_holds_loop_positions(sheet):
    loop = serialize.sections(sheet)[1]
    assert loop["repeat"] is True
    assert loop["detail"] == "4-bar loop, repeats ~4×"
    # Numbers are positions inside the loop, not absolute bars — the same thing
    # render_ascii does when it renders the loop instead of the body.
    assert [b["number"] for b in loop["bars"]] == [1, 2, 3, 4]
    assert [b["display"] for b in loop["bars"]] == ["Am", "F", "C", "G"]


def test_outro_section_carries_the_fade_note(sheet):
    outro = serialize.sections(sheet)[-1]
    assert [b["number"] for b in outro["bars"]] == [19, 20, 21]
    assert outro["note"] == "to fade"


def test_without_a_loop_the_body_renders_verbatim_with_absolute_bars():
    plain = lead_sheet.build(FIXTURE, simplify=False)
    body = next(s for s in serialize.sections(plain) if s["kind"] == "body")
    assert body["repeat"] is False
    assert [b["number"] for b in body["bars"]] == list(range(2, 19))


def test_body_is_empty_not_broken_when_overrides_invert_it():
    # intro_end past outro_start leaves body_start > body_end. A musician can
    # drag two sliders into that state, so it has to serialise, not raise.
    inverted = lead_sheet.build(FIXTURE, intro_end=18, outro_start=5, simplify=False)
    body = next(s for s in serialize.sections(inverted) if s["kind"] == "body")
    assert body["bars"] == []


# ── cli_command ───────────────────────────────────────────────────────────────


def test_cli_command_omits_flags_left_on_auto():
    cmd = serialize.cli_command("out/demo", {"simplify": True, "bars_per_line": 4})
    assert cmd == "python3 real_book.py --out out/demo"


def test_cli_command_includes_structural_overrides():
    cmd = serialize.cli_command("out/demo", {
        "intro_end": 8, "outro_start": 60, "loop_len": 2,
        "simplify": True, "bars_per_line": 4,
    })
    assert "--intro-end 8" in cmd
    assert "--outro-start 60" in cmd
    assert "--loop-len 2" in cmd


def test_cli_command_quotes_titles_with_spaces():
    cmd = serialize.cli_command("out/demo", {"title": "D Lydian Soaring Guitar"})
    assert "--title 'D Lydian Soaring Guitar'" in cmd


def test_cli_command_renders_bpm_without_a_trailing_zero_tail():
    assert "--bpm 68" in serialize.cli_command("out/demo", {"bpm": 68.0})
    assert "--bpm 80.75" in serialize.cli_command("out/demo", {"bpm": 80.75})


def test_cli_command_carries_non_default_layout_flags():
    cmd = serialize.cli_command("out/demo", {"simplify": False, "bars_per_line": 8})
    assert "--no-simplify" in cmd
    assert "--bars-per-line 8" in cmd


# ── sheet_to_dict ─────────────────────────────────────────────────────────────


def test_sheet_to_dict_carries_the_metadata_the_header_needs(sheet):
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["title"] == "synthetic"
    assert d["key"] == "C Major"
    assert d["bpm"] == 120.0
    assert d["total_bars"] == 21
    assert d["bars_per_line"] == 4


def test_sheet_to_dict_reports_the_loop_as_an_object(sheet):
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["loop"] == {"length": 4, "chords": ["Am", "F", "C", "G"], "repeats": 4}


def test_sheet_to_dict_timecodes_the_departures(sheet):
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["departures"] == [
        {"bar": 18, "chord": "D#m7", "time": 34.0, "timecode": "0:34"},
    ]


def test_sheet_to_dict_includes_the_ascii_rendering(sheet):
    # The CLI and the browser render the same LeadSheet. Shipping the ASCII too
    # lets the page prove it rather than assert it.
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["ascii"] == lead_sheet.render_ascii(sheet, bars_per_line=4)
