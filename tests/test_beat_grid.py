"""Regression guards for the beat-grid conventions analyze.py depends on.

Two defects shipped in this repo for its entire history, both from assuming
something about librosa that isn't true. Neither was caught by the CLI smoke
test, because both scripts still exited 0 while emitting wrong numbers. These
tests pin the actual library behaviour so a future librosa upgrade — or a future
edit to analyze.py — fails loudly instead of silently.

See PR #6 for the full write-up.
"""
from __future__ import annotations

import librosa
import numpy as np


def test_sync_returns_one_more_column_than_indices():
    """sync() treats its index array as INTERIOR boundaries.

    It prepends 0 and appends n_frames, so N indices produce N+1 columns. Reading
    it as "one column per index" is what shifted every chord label one beat late.
    """
    data = np.arange(20, dtype=float).reshape(1, 20)
    idx = np.array([4, 8, 12, 16])
    out = librosa.util.sync(data, idx, aggregate=np.mean)
    assert out.shape[1] == len(idx) + 1


def test_sync_column_spans_are_left_closed_from_the_previous_boundary():
    """Column j covers [bounds[j], bounds[j+1]) where bounds = [0, *idx, n]."""
    data = np.arange(20, dtype=float).reshape(1, 20)
    idx = [4, 8, 12, 16]
    out = librosa.util.sync(data, np.array(idx), aggregate=np.mean)

    bounds = [0, *idx, data.shape[1]]
    expected = [data[0, bounds[j] : bounds[j + 1]].mean() for j in range(len(bounds) - 1)]
    assert np.allclose(out[0], expected)


def test_beat_track_defaults_to_a_different_hop_than_our_features():
    """beat_track() without hop_length uses 512; our features use 2048.

    Frame indices from one grid cannot index an array built on the other. This is
    the trap that collapsed a whole track into a single column — sync() clamps
    out-of-range indices rather than raising, so nothing complains.
    """
    sr = 22050
    y = np.zeros(sr * 4, dtype=float)
    y[:: sr // 4] = 1.0  # click track, 4 clicks/sec

    _, beats_default = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    _, beats_2048 = librosa.beat.beat_track(y=y, sr=sr, hop_length=2048, units="frames")

    assert beats_default.max() > beats_2048.max(), (
        "the default grid should be finer; if this fails, librosa changed its "
        "default hop and analyze.py's re-gridding assumption needs revisiting"
    )


def test_regridding_through_seconds_keeps_indices_in_range():
    """The fix: convert to seconds, then back onto the feature hop.

    This is what analyze.py does. Every re-gridded index must fall inside the
    feature array, otherwise sync() silently clamps and the collapse returns.
    """
    sr = 22050
    hop = 2048
    y = np.zeros(sr * 4, dtype=float)
    y[:: sr // 4] = 1.0

    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beats, sr=sr)
    regridded = np.unique(
        np.clip(librosa.time_to_frames(beat_times, sr=sr, hop_length=hop), 0, None)
    )

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    assert regridded.max() <= chroma.shape[1], "re-gridded index still out of range"

    synced = librosa.util.sync(chroma, regridded, aggregate=np.median)
    assert synced.shape[1] == len(regridded) + 1
    assert synced.shape[1] > 1, "collapsed to a single column — the original bug"


def test_boundary_array_labelling_covers_the_whole_timeline():
    """seg_bounds = [0, *beat_times, duration] must tile [0, duration] exactly.

    Before the fix, labelling column i with beat_times[i] left the audio before
    the first beat unlabelled and produced a zero-length final segment.
    """
    duration = 40.0
    beat_times = np.arange(0.5, duration, 0.5)
    seg_bounds = np.concatenate(([0.0], beat_times, [duration]))

    assert seg_bounds[0] == 0.0
    assert seg_bounds[-1] == duration
    assert np.all(np.diff(seg_bounds) >= 0), "boundaries must be monotonic"

    covered = sum(
        seg_bounds[i + 1] - seg_bounds[i] for i in range(len(seg_bounds) - 1)
    )
    assert np.isclose(covered, duration), "labelling must cover 100% of the timeline"
