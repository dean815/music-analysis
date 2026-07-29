"""Regression guards for the half-time suspicion heuristic in analyze.py.

The heuristic warns that beat_track may have locked onto 2x the real pulse. It
used to fire on a tempogram peak near tempo/2 alone, which is not evidence of
anything: the autocorrelation of any periodic pulse train has peaks at 2x and 3x
the beat period, so that peak is there by construction even when the detection is
correct. It fired on 21 of 24 correct synthetic detections. See PR #6.

Two conditions now have to hold together — the detected tempo must be >= 150 BPM,
and the half-tempo peak must be stronger than the peak at the tempo. The tests are
in three layers, cheapest first:

  1. the rule itself, against hand-built tempogram bands. Pins each condition in
     isolation, including the true-positive direction.
  2. the rule against real librosa output for click tracks either side of the gate.
  3. one end-to-end run, guarding that main() writes the verdict it computed.

Layer 1 is what the earlier subprocess-only version of this file could not do.
A genuine half-time positive cannot be synthesised as audio — adding half-rate
accents to a click train leaves beat_track's reading and the tempogram peaks
unchanged — and the real fixture is a commercial recording that cannot go in the
repo. Feeding the decision function the band a half-time track produces tests that
direction directly.
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
sys.path.insert(0, str(REPO_ROOT))

import analyze  # noqa: E402

SR = 44100
CLIP_SECONDS = 20.0
HOP = 2048  # the feature hop analyze.py runs its tempogram on
GATE = analyze.IMPLAUSIBLY_FAST_BPM
TOL = analyze.TEMPO_PEAK_TOLERANCE


# ── Layer 1: the rule, against hand-built tempogram bands ────────────────────


def _band(peaks: dict[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """A tempogram band holding {bpm: strength}, zero everywhere else."""
    band_bpms = np.arange(40.0, 220.5, 0.5)
    band_ac = np.zeros_like(band_bpms)
    for bpm, strength in peaks.items():
        band_ac[int(np.argmin(np.abs(band_bpms - bpm)))] = strength
    return band_bpms, band_ac


def _decide(tempo: float, peaks: dict[float, float], top: list[float]):
    band_bpms, band_ac = _band(peaks)
    return analyze.suspect_half_time(tempo, np.array(top), band_bpms, band_ac)


def test_fires_when_fast_and_half_peak_is_stronger():
    """The true positive. This is the shape a real half-time track produces."""
    result = _decide(161.5, {80.75: 0.90, 161.5: 0.50}, [80.75, 161.5])
    assert result.suspected is True
    assert result.half_bpm == pytest.approx(80.75)
    assert result.half_strength == pytest.approx(0.90)
    assert result.tempo_strength == pytest.approx(0.50)


def test_gate_suppresses_the_same_evidence_below_150_bpm():
    """Identical evidence, slower tempo: condition 1 alone must veto it.

    This is the original false positive — a 136 BPM read with a strong 68 BPM
    peak, which the old heuristic flagged and suggested 68 for.
    """
    assert _decide(136.0, {68.0: 0.90, 136.0: 0.50}, [68.0, 136.0]).suspected is False


def test_strength_test_suppresses_a_fast_track_with_a_weaker_half_peak():
    """Above the gate, condition 2 is the only thing left to say no."""
    result = _decide(161.5, {80.75: 0.40, 161.5: 0.90}, [161.5, 80.75])
    assert result.suspected is False
    assert result.half_bpm == pytest.approx(80.75), "the half peak was still found"


def test_no_peak_near_half_reports_nothing_found():
    result = _decide(161.5, {161.5: 0.90, 55.0: 0.30}, [161.5, 55.0])
    assert result.suspected is False
    assert result.half_bpm is None


@pytest.mark.parametrize(
    "tempo, expected", [(GATE, True), (GATE - 0.1, False)]
)
def test_gate_is_inclusive_at_exactly_150_bpm(tempo, expected):
    peaks = {tempo / 2: 0.90, tempo: 0.50}
    assert _decide(tempo, peaks, [tempo / 2, tempo]).suspected is expected


def test_only_the_strongest_peak_near_half_gets_considered():
    """Two peaks sit within tolerance of half; the first in top_bpms decides.

    Here the first is weaker than the tempo, so no warning — even though the
    second would have fired. Documented behaviour, pinned so a refactor that
    starts scanning the whole list has to do so deliberately.
    """
    result = _decide(161.5, {79.0: 0.40, 81.0: 0.95, 161.5: 0.50}, [79.0, 81.0, 161.5])
    assert result.suspected is False
    assert result.half_bpm == pytest.approx(79.0)


# ── Layer 2: the rule against real librosa output ────────────────────────────


def _click_track(bpm: float) -> np.ndarray:
    """A bare quarter-note click train — a pulse beat_track reads correctly.

    float32 mono, matching what analyze.py hands its own tempogram after
    averaging channels.
    """
    times = np.arange(0.0, CLIP_SECONDS, 60.0 / bpm)
    return librosa.clicks(times=times, sr=SR, length=int(CLIP_SECONDS * SR)).astype(np.float32)


def _analyse_clicks(bpm: float):
    y = _click_track(bpm)
    tempo_arr, _ = librosa.beat.beat_track(y=y, sr=SR, units="frames")
    tempo = float(np.atleast_1d(tempo_arr)[0])
    band_bpms, band_ac, top_bpms = analyze.tempogram_peaks(y, SR, HOP)
    return tempo, top_bpms, analyze.suspect_half_time(tempo, top_bpms, band_bpms, band_ac)


def _half_peaks(tempo: float, top_bpms: np.ndarray) -> list[float]:
    half = tempo / 2.0
    return [float(b) for b in top_bpms if abs(b - half) / half < TOL]


@pytest.mark.parametrize("bpm", [160, 165, 190])
def test_fast_click_tracks_are_not_flagged(bpm):
    """Genuinely fast material, read correctly, must not be called half-time.

    This is the band the gate deliberately lets through, so the strength
    comparison is unassisted. Drum & bass, footwork and punk live here.
    """
    tempo, top_bpms, result = _analyse_clicks(bpm)

    assert tempo >= GATE, (
        f"detected {tempo:.2f} BPM, below the {GATE} gate — this case no longer "
        "exercises the strength comparison and needs a new tempo"
    )
    assert _half_peaks(tempo, top_bpms), (
        "no tempogram peak near tempo/2, so the old heuristic would not have fired "
        "here either and this case proves nothing"
    )
    assert result.suspected is False, (
        f"{bpm} BPM click flagged as half-time; detected {tempo:.2f}, "
        f"half={result.half_strength}, tempo={result.tempo_strength}"
    )


@pytest.mark.parametrize("bpm", [135, 145])
def test_mid_tempo_click_tracks_are_not_flagged(bpm):
    """Correct detection, half peak present, no warning — the original bug."""
    tempo, top_bpms, result = _analyse_clicks(bpm)

    assert tempo < GATE, (
        f"detected {tempo:.2f} BPM, at or above the {GATE} gate — this case no "
        "longer exercises the gate and needs a new tempo"
    )
    assert _half_peaks(tempo, top_bpms), (
        "no tempogram peak near tempo/2, so the old heuristic would not have fired "
        "here either and this case proves nothing"
    )
    assert result.suspected is False


# ── Layer 3: end-to-end, guarding the wiring ─────────────────────────────────


def test_summary_json_records_the_verdict_the_rule_returned(tmp_path):
    """main() must write the decision it computed, not a stale or separate one.

    The two layers above would both pass if main() ignored suspect_half_time and
    wrote a constant. Stereo because analyze.py indexes both channels for its L/R
    correlation and raises on a single-channel file.
    """
    y = _click_track(160)
    wav = tmp_path / "clicks.wav"
    sf.write(wav, np.stack([y, y], axis=1), SR)

    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "analyze.py"), "--audio", str(wav), "--out", str(out)],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
    )
    summary = json.loads((out / "summary.json").read_text())

    _, _, expected = _analyse_clicks(160)
    assert summary["half_time_suspected"] == expected.suspected
    assert summary["tempogram_top_bpms"], "top BPMs should still be reported"
