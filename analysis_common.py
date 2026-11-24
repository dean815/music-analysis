"""Helpers shared by the analysis scripts.

Before this module existed, each script carried its own copy of these.
The copies had drifted in small ways (banner width, chord-template
weights), so the differences are kept as parameters: every script prints
and computes exactly what it did before.
"""
from __future__ import annotations

import functools

import numpy as np

from modes import PITCHES

__all__ = [
    "PITCHES",
    "KK_MAJOR",
    "KK_MINOR",
    "banner",
    "banner_with_width",
    "chord_templates",
    "bass_chroma",
    "viterbi_sticky",
]

# Krumhansl-Kessler key profiles, indexed by semitones above the tonic.
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def banner(title: str, width: int = 64) -> None:
    """Print a section heading framed by rules of `width` '=' characters."""
    print(f"\n{'=' * width}\n{title}\n{'=' * width}")


def banner_with_width(width: int):
    """A banner() fixed at `width`, for scripts whose headings are not 64 wide."""
    return functools.partial(banner, width=width)


# Chord qualities as 12-bin pitch-class templates rooted on C.
_BINARY_TEMPLATES = {
    "":      [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],   # major triad
    "m":     [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],   # minor triad
    "sus2":  [1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0],
    "sus4":  [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0],
    "maj7":  [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1],
    "7":     [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0],
    "m7":    [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0],
    "add9":  [1, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0],
}
# Same qualities, but four-note chords weight the added tone below the triad
# so a plain triad is not out-scored by its seventh/add9 neighbour.
_WEIGHTED_TEMPLATES = {
    **{q: _BINARY_TEMPLATES[q] for q in ("", "m", "sus2", "sus4")},
    "maj7":  [0.9, 0, 0, 0, 0.9, 0, 0, 0.9, 0, 0, 0, 0.7],
    "7":     [0.9, 0, 0, 0, 0.9, 0, 0, 0.9, 0, 0, 0.7, 0],
    "m7":    [0.9, 0, 0, 0.9, 0, 0, 0, 0.9, 0, 0, 0.7, 0],
    "add9":  [0.9, 0, 0.7, 0, 0.9, 0, 0, 0.9, 0, 0, 0, 0],
}


def chord_templates(*, weighted: bool) -> list[tuple[str, np.ndarray]]:
    """Unit-norm chord templates for every quality on all 12 roots.

    `weighted=False` gives equal-weight chord tones (analyze.py);
    `weighted=True` de-emphasises the added tone of four-note chords
    (analyze_v2.py, analyze_v3.py).
    """
    base = _WEIGHTED_TEMPLATES if weighted else _BINARY_TEMPLATES
    out = []
    for quality, tpl in base.items():
        v = np.array(tpl, dtype=float)
        v /= np.linalg.norm(v)
        for root in range(12):
            out.append((f"{PITCHES[root]}{quality}", np.roll(v, root)))
    return out


def bass_chroma(y: np.ndarray, sr: int, hop: int) -> np.ndarray:
    """Chroma from the three octaves C2..B4 only, normalised per frame."""
    import librosa

    c_low = np.abs(librosa.cqt(y=y, sr=sr, hop_length=hop,
                               fmin=librosa.note_to_hz("C2"),
                               n_bins=36, bins_per_octave=12))
    chroma = np.zeros((12, c_low.shape[1]))
    for i in range(c_low.shape[0]):
        chroma[i % 12] += c_low[i]
    return librosa.util.normalize(chroma, axis=0)


def viterbi_sticky(emit: np.ndarray, self_bonus: float) -> np.ndarray:
    """Most likely chord index per column of `emit` (n_chords, n_steps).

    Staying on the same chord earns `self_bonus`; every change costs the
    same, so the prior only discourages flicker, not particular moves.
    """
    n_chords, n_steps = emit.shape
    dp = np.full((n_chords, n_steps), -np.inf)
    back = np.zeros((n_chords, n_steps), dtype=np.int32)
    dp[:, 0] = emit[:, 0]
    for t in range(1, n_steps):
        prev = dp[:, t - 1]
        max_prev = float(prev.max())
        argmax_prev = int(prev.argmax())
        for c in range(n_chords):
            stay = prev[c] + self_bonus
            if stay >= max_prev:
                dp[c, t] = emit[c, t] + stay
                back[c, t] = c
            else:
                dp[c, t] = emit[c, t] + max_prev
                back[c, t] = argmax_prev

    path = np.zeros(n_steps, dtype=np.int32)
    path[-1] = int(dp[:, -1].argmax())
    for t in range(n_steps - 2, -1, -1):
        path[t] = back[path[t + 1], t + 1]
    return path
