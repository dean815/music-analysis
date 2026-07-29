"""Regression guards for the half-time suspicion heuristic in analyze.py.

The heuristic warns that beat_track may have locked onto 2x the real pulse. It
used to fire on a tempogram peak near tempo/2 alone, which is not evidence of
anything: the autocorrelation of any periodic pulse train has peaks at 2x and 3x
the beat period, so that peak is there by construction even when the detection is
correct. It fired on 21 of 24 correct synthetic detections. See PR #6 and the
correction commit that follows #7 for the measurements.

Two conditions now have to hold together — the detected tempo must be >= 150 BPM,
and the half-tempo peak must be stronger than the peak at the tempo. The two tests
below pin each condition to the case where it is the one doing the work:

  - below the gate, condition 1 suppresses the warning
  - above the gate, condition 1 passes and only condition 2 suppresses it

Every case asserts that a half-tempo peak IS present in the reported top-5, so the
old heuristic would have fired on all of them. Without that assertion these tests
would pass just as happily against a heuristic that never fires at all.

analyze.py runs argparse at import and so cannot be imported. These tests drive it
as a subprocess and read summary.json, which is slower but exercises the shipped
code path rather than a reimplementation of it. Each case is ~2.5s.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np
import pytest
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYZE = REPO_ROOT / "analyze.py"

SR = 44100
CLIP_SECONDS = 20.0
GATE_BPM = 150.0  # IMPLAUSIBLY_FAST_BPM in analyze.py
TOLERANCE = 0.05  # the "within 5% of tempo/2" window in analyze.py


def _write_click_track(bpm: float, path: Path) -> None:
    """A bare quarter-note click train — a pulse beat_track reads correctly.

    Written as stereo because analyze.py indexes both channels for its L/R
    correlation and would raise on a single-channel file.
    """
    times = np.arange(0.0, CLIP_SECONDS, 60.0 / bpm)
    y = librosa.clicks(times=times, sr=SR, length=int(CLIP_SECONDS * SR))
    sf.write(path, np.stack([y, y], axis=1), SR)


def _run_analyze(bpm: float, tmp_dir: Path) -> dict:
    wav = tmp_dir / f"click_{bpm}.wav"
    out = tmp_dir / f"out_{bpm}"
    _write_click_track(bpm, wav)
    subprocess.run(
        [sys.executable, str(ANALYZE), "--audio", str(wav), "--out", str(out)],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return json.loads((out / "summary.json").read_text())


def _half_tempo_peaks(summary: dict) -> list[float]:
    """Top-5 tempogram peaks sitting within 5% of half the detected tempo."""
    half = summary["tempo_bpm"] / 2.0
    return [b for b in summary["tempogram_top_bpms"] if abs(b - half) / half < TOLERANCE]


# ── Above the gate: condition 2 is the only thing suppressing the warning ─────


@pytest.mark.parametrize("bpm", [160, 165, 190])
def test_fast_tracks_are_not_flagged_half_time(bpm, tmp_path):
    """A genuinely fast pulse, read correctly, must not be called half-time.

    This is the band the 150 BPM gate deliberately lets through, so the strength
    comparison is unassisted here. Drum & bass, footwork and punk live in it.
    """
    summary = _run_analyze(bpm, tmp_path)

    assert summary["tempo_bpm"] >= GATE_BPM, (
        f"detected {summary['tempo_bpm']:.2f} BPM, below the {GATE_BPM} gate — this "
        "case no longer exercises the strength comparison and needs a new tempo"
    )
    assert _half_tempo_peaks(summary), (
        "no tempogram peak near tempo/2, so the old heuristic would not have fired "
        "here either and this case proves nothing"
    )
    assert summary["half_time_suspected"] is False, (
        f"{bpm} BPM click track flagged as half-time; detected "
        f"{summary['tempo_bpm']:.2f}, top peaks {summary['tempogram_top_bpms']}"
    )


# ── Below the gate: condition 1 suppresses it ────────────────────────────────


@pytest.mark.parametrize("bpm", [135, 145])
def test_mid_tempo_tracks_are_not_flagged_half_time(bpm, tmp_path):
    """The original false positive: correct detection, half peak present, no warning.

    135 BPM is the motivating case — a bounce with MusicXML ground truth of 135
    that beat_track read as 136 and the old heuristic flagged, suggesting 68.
    """
    summary = _run_analyze(bpm, tmp_path)

    assert summary["tempo_bpm"] < GATE_BPM, (
        f"detected {summary['tempo_bpm']:.2f} BPM, at or above the {GATE_BPM} gate — "
        "this case no longer exercises the gate and needs a new tempo"
    )
    assert _half_tempo_peaks(summary), (
        "no tempogram peak near tempo/2, so the old heuristic would not have fired "
        "here either and this case proves nothing"
    )
    assert summary["half_time_suspected"] is False, (
        f"{bpm} BPM click track flagged as half-time; detected "
        f"{summary['tempo_bpm']:.2f}, top peaks {summary['tempogram_top_bpms']}"
    )
