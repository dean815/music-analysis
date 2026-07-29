"""The bundled example is committed data, so it gets committed-data tests.

Two things can rot here and neither shows up as a normal test failure: the
privacy scrub can be undone by someone re-copying from a local out/ dir, and the
chart can drift out of sync with what lead_sheet expects. Both are asserted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lead_sheet  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "demo"


def test_example_files_are_present():
    assert (EXAMPLE / "summary.json").exists()
    assert (EXAMPLE / "chord_chart_v3.txt").exists()


def test_example_contains_no_personal_paths():
    # The README promises `git log -p | grep '/Users/'` stays clean.
    for name in ("summary.json", "chord_chart_v3.txt"):
        text = (EXAMPLE / name).read_text()
        assert "/Users/" not in text
        assert "deanhicks" not in text


def test_example_title_is_the_scrubbed_name():
    summary = json.loads((EXAMPLE / "summary.json").read_text())
    assert summary["file"] == "D Lydian Soaring Guitar.wav"


def test_example_builds_into_the_documented_structure():
    # These are the numbers the spec quotes as evidence the heuristics need a
    # human: a 1-bar intro, and a 3-bar loop where 2 bars is the better reading.
    sheet = lead_sheet.build(EXAMPLE)
    assert sheet.title == "D Lydian Soaring Guitar"
    assert sheet.total_bars == 73
    assert sheet.intro_end == 1
    assert sheet.outro_start == 60
    assert sheet.loop == (3, ["Dmaj7 / Emaj7", "Dmaj7", "Emaj7"])


def test_example_two_bar_loop_override_is_the_musical_reading():
    sheet = lead_sheet.build(EXAMPLE, loop_len=2)
    assert sheet.loop == (2, ["Dmaj7", "Emaj7"])
