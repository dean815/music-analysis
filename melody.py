"""Extract dominant melody pitch (pyin) and analyze G vs G# in the D-plateau.

Goal: determine whether the lead line is genuinely Lydian (uses G#) or
falls into D major / D Mixolydian (uses G natural) over the Dadd9 pad.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import librosa
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, audio=True)
_args = _parser.parse_args()
AUDIO = paths.require(_args.audio, "MUSIC_AUDIO")
OUT = paths.ensure_dir(_args.out)

y_stereo, sr = sf.read(str(AUDIO), always_2d=True)
y = y_stereo.mean(axis=1).astype(np.float32)
duration = len(y) / sr
hop = 512  # finer resolution for melody than for harmony

# pyin is monophonic — gives one pitch + voicing probability per frame.
# Range: a guitar lead "soaring" would live mostly E3..C6.
print("Running pyin (this may take 30-60s)...")
f0, voiced_flag, voiced_prob = librosa.pyin(
    y,
    fmin=float(librosa.note_to_hz("E3")),
    fmax=float(librosa.note_to_hz("C7")),
    sr=sr,
    frame_length=4096,
    hop_length=hop,
)
times = librosa.times_like(f0, sr=sr, hop_length=hop)
print(f"frames: {len(f0)}, voiced %: {100*np.mean(~np.isnan(f0)):.1f}")

# Convert pitches to MIDI numbers and pitch classes.
midi = librosa.hz_to_midi(f0)
pc = np.where(np.isnan(midi), -1, np.round(midi).astype(int) % 12)
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Define section boundaries from earlier analysis.
sections = [
    ("Intro", 0.65, 4.46),
    ("D-plateau (Lydian?)", 4.46, 31.11),
    ("C#m plateau", 31.11, 61.77),
    ("F# plateau", 61.77, duration),
]

print("\n" + "=" * 64)
print("MELODY PITCH-CLASS DISTRIBUTION PER SECTION (lead/melody only)")
print("=" * 64)
for name, t0, t1 in sections:
    f_idx = (times >= t0) & (times < t1)
    pcs = pc[f_idx]
    pcs = pcs[pcs >= 0]
    if len(pcs) == 0:
        continue
    counts = np.bincount(pcs, minlength=12)
    total = counts.sum()
    print(f"\n{name}  ({t0:.2f}-{t1:.2f}s)  voiced frames: {total}")
    order = np.argsort(-counts)
    for i, p_idx in enumerate(order[:12]):
        if counts[p_idx] == 0:
            continue
        pct = 100 * counts[p_idx] / total
        bar = "█" * int(pct * 0.5)
        print(f"  {PITCHES[p_idx]:>2}  {counts[p_idx]:5d}  {pct:5.1f}%  {bar}")

# Specific test: G vs G# in the D-plateau.
print("\n" + "=" * 64)
print("THE LYDIAN TEST: G vs G# in the D-plateau (4.46–31.11s)")
print("=" * 64)
t0, t1 = 4.46, 31.11
f_idx = (times >= t0) & (times < t1)
pcs = pc[f_idx]
pcs = pcs[pcs >= 0]
g_count = int(np.sum(pcs == 7))   # G
gs_count = int(np.sum(pcs == 8))  # G#
total = len(pcs)
print(f"voiced frames in section: {total}")
print(f"G  natural (4):  {g_count:5d}  ({100*g_count/max(total,1):.2f}%)")
print(f"G# (#4 Lydian):  {gs_count:5d}  ({100*gs_count/max(total,1):.2f}%)")
ratio = gs_count / max(g_count, 1)
print(f"G#/G ratio    :  {ratio:.2f}")
if gs_count > g_count * 1.5:
    verdict = "STRONG D LYDIAN — melody clearly favors #4"
elif gs_count > g_count:
    verdict = "MILD D LYDIAN — melody uses #4 more than 4"
elif g_count > gs_count * 1.5:
    verdict = "D MAJOR / MIXOLYDIAN — melody favors natural 4"
else:
    verdict = "AMBIGUOUS — melody uses both, slight major lean"
print(f"VERDICT       :  {verdict}")

# Plot the melody contour over time, color-coded by section, with horizontal lines for D-Lydian scale.
fig, ax = plt.subplots(figsize=(15, 6))
ax.scatter(times[~np.isnan(midi)], midi[~np.isnan(midi)], s=2, c="#3a6ea5", alpha=0.6)

# Reference grid: D Lydian scale (D, E, F#, G#, A, B, C#) in octaves 4-6.
d_lydian_pcs = [2, 4, 6, 8, 9, 11, 1]  # D, E, F#, G#, A, B, C#
for octave in (4, 5, 6):
    for pc_ in d_lydian_pcs:
        midi_n = pc_ + 12 * (octave + 1)
        ax.axhline(midi_n, color="lightgreen", lw=0.4, alpha=0.5)
# G natural (would be the "wrong" note for D Lydian):
for octave in (4, 5, 6):
    midi_g = 7 + 12 * (octave + 1)
    ax.axhline(midi_g, color="salmon", lw=0.5, alpha=0.7, ls=":")

# Section boundaries.
for name, t0, t1 in sections:
    ax.axvline(t0, color="black", lw=0.5, alpha=0.4)
    ax.text(t0 + 0.3, 84, name, fontsize=8, color="black", alpha=0.7)

ax.set_xlim(0, duration)
ax.set_ylim(50, 90)
ax.set_xlabel("time (s)")
ax.set_ylabel("MIDI pitch")
ax.set_title("Monophonic melody contour (pyin)\n"
             "Green lines = D Lydian scale degrees, red dotted = G natural (NOT in D Lydian)")
ax.grid(True, lw=0.3, alpha=0.3)
plt.tight_layout()
fig.savefig(OUT / "melody.png", dpi=120)
plt.close(fig)
print(f"\nsaved {OUT / 'melody.png'}")
print("DONE")
