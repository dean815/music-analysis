"""Guards for audio that librosa's beat tracker finds no pulse in.

analyze.py is a beat-synchronous analyser — chords and structure are both pooled
over the beat grid — but nothing in it checked that the grid was non-empty. On
sustained pad, drone, or ambient material the grid comes back empty and the
script died deep inside librosa with

    ValueError: cannot reshape array of size 0 into shape (0,newaxis)

which names neither the cause nor the offending input. Worse, the crash site was
a recurrence matrix assigned to a variable nothing ever read.

These tests pin the library behaviours that combine to produce that failure, plus
the end-to-end contract that analyze.py now degrades with a warning instead of
dying, and marks the summary so analyze_v3.py refuses the bogus tempo rather than
silently analysing at 0 BPM.
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

REPO = Path(__file__).resolve().parents[1]
SR = 22050


def sustained_pad(duration_s: float = 8.0, freqs=(146.83, 220.0, 293.66)) -> np.ndarray:
    """A sine chord with a slow attack and release — harmonic, but no transients."""
    n = int(SR * duration_s)
    t = np.arange(n) / SR
    y = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    env = np.ones(n)
    atk, rel = int(0.25 * SR), int(0.6 * SR)
    env[:atk] = np.linspace(0, 1, atk) ** 1.4
    env[-rel:] = np.linspace(1, 0, rel) ** 1.4
    return y * env * 0.5


def test_sustained_pad_yields_no_beats():
    """The precondition for the whole failure mode: an empty beat grid is reachable.

    This is not a contrived input — it is what any pad, drone, or ambient track
    looks like to the onset envelope.
    """
    _, beats = librosa.beat.beat_track(y=sustained_pad(), sr=SR, units="frames")
    assert len(beats) == 0


def test_median_aggregation_is_why_pure_tones_read_as_beatless():
    """beat_track builds its onset envelope with aggregate=np.median across mel bins.

    onset_strength on its own defaults to np.mean. Summed sinusoids occupy only a
    handful of the mel bins, so the median bin is empty and the envelope is
    *identically zero* while the mean envelope is clearly non-zero. This is the
    non-obvious part: audio can be plainly rhythmic to a listener and still be
    beatless to beat_track purely because its spectrum is sparse.
    """
    y = sustained_pad()
    env_mean = librosa.onset.onset_strength(y=y, sr=SR, hop_length=512, aggregate=np.mean)
    env_median = librosa.onset.onset_strength(y=y, sr=SR, hop_length=512, aggregate=np.median)

    assert env_mean.max() > 0.0
    assert env_median.max() == 0.0


def test_sync_of_an_empty_index_array_yields_zero_columns():
    """No beats -> no columns, so every beat-synchronous array is empty, not short.

    Note this differs from the interior-boundary rule pinned in test_beat_grid.py:
    N indices normally give N+1 columns, but zero indices give zero columns rather
    than the one column spanning the whole track that the +1 rule would suggest.
    """
    data = np.random.default_rng(0).random((13, 50))
    assert librosa.util.sync(data, np.array([], dtype=int)).shape == (13, 0)


def test_recurrence_matrix_rejects_a_zero_column_array():
    """The exact crash: a (n_features, 0) array reaches recurrence_matrix."""
    with pytest.raises(ValueError):
        librosa.segment.recurrence_matrix(
            np.zeros((13, 0)), mode="affinity", sym=True, width=3
        )


def test_analyze_degrades_instead_of_crashing_on_beatless_audio(tmp_path):
    """End-to-end: analyze.py exits 0, warns, and marks the summary as beatless.

    tempo_bpm must be null rather than 0.0 — analyze_v3.pick_tempo already treats a
    missing tempo as "pass --bpm", so writing null routes the user to the existing
    escape hatch instead of letting a 0 BPM grid propagate downstream.
    """
    audio = tmp_path / "pad.wav"
    mono = sustained_pad()
    sf.write(str(audio), np.stack([mono, mono], axis=1), SR, subtype="PCM_16")

    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "analyze.py", "--audio", str(audio), "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )

    assert proc.returncode == 0, f"analyze.py crashed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    assert "no beats" in proc.stdout.lower()

    summary = json.loads((out / "summary.json").read_text())
    assert summary["tempo_bpm"] is None
    assert summary["beats_detected"] == 0
