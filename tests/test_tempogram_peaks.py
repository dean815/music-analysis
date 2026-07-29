"""Guards for tempogram peak selection in analyze.py.

`top_bpms` used to be the n strongest *bins*, which is not the same as the n
strongest tempi. The BPM axis is 60*sr/(hop*lag), so bin spacing is set by the
hop, and the shoulders of one tall peak can outrank every other peak in the band.
Ranking bare bins then reports the same tempo several times and pushes real
candidates out of a five-slot list.

That was not hypothetical even at the hop analyze.py uses — a 135 BPM click track
returned 44.55 and 46.14 as two of its five findings, 3.6% apart and the same
peak. At hop=256 it collapsed to 2 distinct tempi out of 5.

It matters beyond the printout: suspect_half_time scans this list for a peak near
tempo/2 and can only find one if it is in the list.
"""
from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import analyze  # noqa: E402

SR = 44100
CLIP_SECONDS = 8.0
TOL = analyze.TEMPO_PEAK_TOLERANCE


# ── local_maxima ─────────────────────────────────────────────────────────────


def test_interior_peak_is_found():
    assert list(analyze.local_maxima(np.array([0.0, 1.0, 5.0, 1.0, 0.0]))) == [2]


def test_shoulders_of_a_peak_are_not_peaks():
    """The actual bug: a tall peak's neighbours outrank other real peaks."""
    values = np.array([0.1, 8.0, 9.0, 8.5, 0.1, 2.0, 0.1])
    found = analyze.local_maxima(values)
    assert list(found) == [2, 5], "only the apex and the small separate peak"
    # ranked by height, the top two are the apex and the small peak — not the shoulders
    top2 = found[np.argsort(values[found])[::-1][:2]]
    assert sorted(top2) == [2, 5]


def test_plateau_contributes_exactly_one_index():
    assert len(analyze.local_maxima(np.array([0.0, 3.0, 3.0, 3.0, 0.0]))) == 1


def test_peaks_on_the_band_edges_count():
    """A peak at the edge is still the best evidence in the band."""
    assert 0 in analyze.local_maxima(np.array([9.0, 1.0, 2.0]))
    assert 2 in analyze.local_maxima(np.array([2.0, 1.0, 9.0]))


@pytest.mark.parametrize(
    "values",
    [
        np.arange(10.0),           # monotonic up
        np.arange(10.0)[::-1],     # monotonic down
        np.zeros(10),              # flat
        np.array([1.0]),           # single bin
        np.array([]),              # empty
    ],
)
def test_never_loses_the_global_maximum(values):
    found = analyze.local_maxima(values)
    if len(values) == 0:
        assert len(found) == 0
        return
    assert len(found) >= 1
    assert values[found].max() == values.max()


# ── tempogram_peaks ──────────────────────────────────────────────────────────


def _clicks(bpm: float) -> np.ndarray:
    times = np.arange(0.0, CLIP_SECONDS, 60.0 / bpm)
    return librosa.clicks(times=times, sr=SR, length=int(CLIP_SECONDS * SR)).astype(np.float32)


def _count_distinct(bpms, tol: float = TOL) -> int:
    kept: list[float] = []
    for b in sorted((float(b) for b in bpms), reverse=True):
        if not any(abs(b - k) / k < tol for k in kept):
            kept.append(b)
    return len(kept)


@pytest.mark.parametrize("hop", [2048, 512, 256])
def test_reported_peaks_are_distinct_tempi(hop):
    """One peak must not occupy several slots, at any hop.

    hop=256 is the case that used to collapse to 2 distinct tempi out of 5. It is
    not the hop analyze.py runs at — the point is that the selection should not
    depend on the bin spacing happening to be coarse.
    """
    _, _, top_bpms = analyze.tempogram_peaks(_clicks(135), SR, hop)
    assert _count_distinct(top_bpms) == len(top_bpms), (
        f"hop={hop} reported {[round(float(b), 2) for b in top_bpms]}, which is "
        f"only {_count_distinct(top_bpms)} distinct tempi"
    )


@pytest.mark.parametrize("hop", [2048, 256])
def test_every_reported_bpm_is_a_real_peak(hop):
    band_bpms, band_ac, top_bpms = analyze.tempogram_peaks(_clicks(135), SR, hop)
    peak_bpms = set(band_bpms[analyze.local_maxima(band_ac)])
    assert set(top_bpms) <= peak_bpms


def test_peaks_come_back_strongest_first():
    band_bpms, band_ac, top_bpms = analyze.tempogram_peaks(_clicks(135), SR, 2048)
    strengths = [analyze.ac_strength(band_bpms, band_ac, b) for b in top_bpms]
    assert strengths == sorted(strengths, reverse=True)


def test_returns_at_most_n_top():
    _, _, top_bpms = analyze.tempogram_peaks(_clicks(135), SR, 2048, n_top=3)
    assert len(top_bpms) <= 3


def test_half_peak_survives_selection():
    """The list feeds suspect_half_time, so the half must still be findable.

    A 155 BPM click over 60s is the one synthetic input to hand whose half-tempo
    peak is genuinely the stronger of the two, so it is the case that would break
    loudest if peak selection dropped the half.
    """
    times = np.arange(0.0, 60.0, 60.0 / 155)
    y = librosa.clicks(times=times, sr=SR, length=int(60.0 * SR)).astype(np.float32)
    tempo_arr, _ = librosa.beat.beat_track(y=y, sr=SR, units="frames")
    tempo = float(np.atleast_1d(tempo_arr)[0])

    band_bpms, band_ac, top_bpms = analyze.tempogram_peaks(y, SR, 2048)
    result = analyze.suspect_half_time(tempo, top_bpms, band_bpms, band_ac)

    assert tempo >= analyze.IMPLAUSIBLY_FAST_BPM, "case must clear the gate to be meaningful"
    assert result.half_bpm is not None, "the half-tempo peak fell out of the list"
    assert result.half_bpm == pytest.approx(tempo / 2, rel=TOL)
