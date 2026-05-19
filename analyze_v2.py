"""V2: bar-level chord smoothing, per-section key detection, better structure."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import librosa
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, audio=True)
_args = _parser.parse_args()
AUDIO = paths.require(_args.audio, "MUSIC_AUDIO")
OUT = paths.ensure_dir(_args.out)
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def banner(t: str) -> None:
    print(f"\n{'=' * 64}\n{t}\n{'=' * 64}")


# ---------------- Load ----------------
y_stereo, sr = sf.read(str(AUDIO), always_2d=True)
y = y_stereo.mean(axis=1).astype(np.float32)
duration = len(y) / sr
hop = 2048
print(f"loaded {duration:.2f}s @ {sr} Hz, {y_stereo.shape[1]} ch")

# ---------------- Tempo: bias toward half-tempo (slow ballad) ----------------
banner("TEMPO (corrected)")
oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
# Try with start_bpm=70 to bias toward slow tempo.
tempo_slow_arr, beats_slow = librosa.beat.beat_track(
    onset_envelope=oenv, sr=sr, hop_length=hop, start_bpm=70.0, units="frames"
)
tempo_slow = float(np.atleast_1d(tempo_slow_arr)[0])
beat_times_slow = librosa.frames_to_time(beats_slow, sr=sr, hop_length=hop)

# Also default for comparison.
tempo_def_arr, beats_def = librosa.beat.beat_track(
    onset_envelope=oenv, sr=sr, hop_length=hop, units="frames"
)
tempo_def = float(np.atleast_1d(tempo_def_arr)[0])

print(f"default beat_track : {tempo_def:.2f} BPM ({len(beats_def)} beats)")
print(f"start_bpm=70       : {tempo_slow:.2f} BPM ({len(beats_slow)} beats)")
# Pick whichever feels more musical: if start_bpm=70 is ~half of default, prefer it.
if abs(tempo_def - 2 * tempo_slow) < 4:
    tempo = tempo_slow
    beats = beats_slow
    beat_times = beat_times_slow
    print(f"-> picking SLOW tempo {tempo:.2f} (default was octave-doubled)")
else:
    tempo = tempo_def
    beats = beats_def
    beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop)
    print(f"-> picking DEFAULT tempo {tempo:.2f}")

print(f"beat IBI mean: {np.diff(beat_times).mean()*1000:.1f} ms")
print(f"first 8 beats: {[round(t, 2) for t in beat_times[:8]]}")

# ---------------- Build chroma at high resolution ----------------
banner("CHROMA")
chroma_cqt = librosa.feature.chroma_cqt(
    y=y, sr=sr, hop_length=hop, bins_per_octave=36, n_octaves=7
)
# Slight median filter along time to suppress transient spikes.
chroma_smooth = median_filter(chroma_cqt, size=(1, 9))
print(f"chroma shape: {chroma_smooth.shape}  (12 pitches x {chroma_smooth.shape[1]} frames)")

# Bass-emphasized chroma: weight low octaves more (helps key detection).
# CQT chroma already pools all octaves. Build a separate low-band chroma:
C_low = np.abs(librosa.cqt(y=y, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C2"),
                            n_bins=36, bins_per_octave=12))  # 3 octaves: C2..B4
C_low_chroma = np.zeros((12, C_low.shape[1]))
for i in range(C_low.shape[0]):
    C_low_chroma[i % 12] += C_low[i]
C_low_chroma = librosa.util.normalize(C_low_chroma, axis=0)
print(f"bass chroma shape: {C_low_chroma.shape}")

# ---------------- Bar-level pooling ----------------
# Assume 4/4 time. Pool every 4 beats. Will be wrong if 3/4 or 6/8, but the audio
# clearly has steady pulse and "soaring" usually = 4/4 in this genre.
beats_per_bar = 4
n_bars = len(beats) // beats_per_bar
bar_starts = beats[: n_bars * beats_per_bar : beats_per_bar]
bar_start_times = librosa.frames_to_time(bar_starts, sr=sr, hop_length=hop)
print(f"\nassumed 4/4 → {n_bars} full bars, bar duration ~{60.0 / tempo * 4:.2f}s")

# Pool chroma per bar (median).
def pool_per_bar(chroma_mat, bar_starts_frames, beats_per_bar):
    out = []
    for i in range(len(bar_starts_frames)):
        f0 = bar_starts_frames[i]
        f1 = bar_starts_frames[i + 1] if i + 1 < len(bar_starts_frames) else chroma_mat.shape[1]
        # Convert from beat-frame index to chroma-frame index:
        out.append(np.median(chroma_mat[:, f0:f1], axis=1))
    return np.stack(out, axis=1)


chroma_bar = pool_per_bar(chroma_smooth, bar_starts, beats_per_bar)
chroma_bar_bass = pool_per_bar(C_low_chroma, bar_starts, beats_per_bar)
print(f"chroma_bar shape: {chroma_bar.shape}  (one column per bar)")

# ---------------- Per-bar chord estimation w/ Viterbi smoothing ----------------
banner("BAR-LEVEL CHORDS")


def chord_templates():
    base = {
        "":      [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
        "m":     [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
        "sus2":  [1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0],
        "sus4":  [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0],
        "maj7":  [0.9, 0, 0, 0, 0.9, 0, 0, 0.9, 0, 0, 0, 0.7],
        "7":     [0.9, 0, 0, 0, 0.9, 0, 0, 0.9, 0, 0, 0.7, 0],
        "m7":    [0.9, 0, 0, 0.9, 0, 0, 0, 0.9, 0, 0, 0.7, 0],
        "add9":  [0.9, 0, 0.7, 0, 0.9, 0, 0, 0.9, 0, 0, 0, 0],
    }
    out = []
    for q, t in base.items():
        v = np.array(t, float)
        v /= np.linalg.norm(v)
        for r in range(12):
            out.append((f"{PITCHES[r]}{q}", np.roll(v, r)))
    return out


tpls = chord_templates()
tpl_names = [n for n, _ in tpls]
tpl_mat = np.stack([t for _, t in tpls])

chroma_bar_n = chroma_bar / (np.linalg.norm(chroma_bar, axis=0, keepdims=True) + 1e-9)
emit = tpl_mat @ chroma_bar_n  # (n_chords, n_bars), cosine sim in [-1,1]

# Viterbi: cheap "self-transition strongly preferred" prior, no chord-tonic prior.
n_chords, n_bars = emit.shape
dp = np.full((n_chords, n_bars), -np.inf)
back = np.zeros((n_chords, n_bars), dtype=np.int32)
dp[:, 0] = emit[:, 0]
self_bonus = 0.25  # add to staying on the same chord
for t in range(1, n_bars):
    prev = dp[:, t - 1]
    # transition cost: 0 for self, -self_bonus for any change
    best_prev_for_each = np.zeros(n_chords)
    best_prev_idx = np.zeros(n_chords, dtype=np.int32)
    # For each candidate chord at time t, the best prev is either staying (prev[same]+self_bonus)
    # or switching from argmax(prev) - self_bonus (we treat all switches equally).
    max_prev = float(prev.max())
    argmax_prev = int(prev.argmax())
    for c in range(n_chords):
        stay = prev[c] + self_bonus
        switch = max_prev  # cost-free switch from best
        if stay >= switch:
            best_prev_for_each[c] = stay
            best_prev_idx[c] = c
        else:
            best_prev_for_each[c] = switch
            best_prev_idx[c] = argmax_prev
    dp[:, t] = emit[:, t] + best_prev_for_each
    back[:, t] = best_prev_idx

# Backtrace.
path = np.zeros(n_bars, dtype=np.int32)
path[-1] = int(dp[:, -1].argmax())
for t in range(n_bars - 2, -1, -1):
    path[t] = back[path[t + 1], t + 1]
bar_chords = [tpl_names[i] for i in path]

# Build segments by merging consecutive identical chord labels — fixed merge logic.
segments = []
for i, c in enumerate(bar_chords):
    t0 = float(bar_start_times[i])
    t1 = float(bar_start_times[i + 1]) if i + 1 < len(bar_start_times) else duration
    if segments and segments[-1][0] == c:
        segments[-1] = (c, segments[-1][1], t1)
    else:
        segments.append((c, t0, t1))

print(f"{n_bars} bars → {len(segments)} chord segments after Viterbi+merge\n")
print("bar-by-bar chord progression:")
for i, c in enumerate(bar_chords):
    t0 = float(bar_start_times[i])
    print(f"  bar {i+1:>3}  {t0:6.2f}s  {c}")

# ---------------- Structural segmentation v2 ----------------
banner("STRUCTURE (chroma+timbre fused)")
mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop)
mfcc_bar = pool_per_bar(mfcc, bar_starts, beats_per_bar)

# Stack chroma + MFCC and z-score each.
def zscore_rows(M):
    mu = M.mean(axis=1, keepdims=True)
    sd = M.std(axis=1, keepdims=True) + 1e-9
    return (M - mu) / sd


feat = np.vstack([zscore_rows(chroma_bar), zscore_rows(mfcc_bar)])
# Pick k by kneedle-ish heuristic: try 4..8, pick the one where boundary spread is most uniform.
best_k, best_score, best_boundaries = 4, np.inf, None
for k in range(4, 9):
    try:
        b = librosa.segment.agglomerative(feat, k=k)
        bt = [float(bar_start_times[i]) for i in b if i < len(bar_start_times)]
        if not bt or bt[0] > 0.3:
            bt = [0.0] + bt
        if bt[-1] < duration - 0.3:
            bt = bt + [float(duration)]
        spans = np.diff(bt)
        # Lower coefficient of variation = more uniform spans.
        cv = spans.std() / max(spans.mean(), 1e-9)
        if cv < best_score:
            best_score, best_k, best_boundaries = cv, k, bt
    except Exception:  # noqa: BLE001
        continue

if best_boundaries is None:
    best_boundaries = [0.0, float(duration)]
print(f"chose k={best_k} (cv={best_score:.3f})")
print("section boundaries (s):")
for i in range(len(best_boundaries) - 1):
    a, b = best_boundaries[i], best_boundaries[i + 1]
    print(f"  S{i+1}: {a:6.2f} → {b:6.2f}   ({b-a:5.2f}s)")

# ---------------- Per-section key/mode ----------------
banner("PER-SECTION KEY/MODE")

KK_MAJOR = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
KK_MINOR = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])

# Build mode profiles directly from scale degrees + emphasis on tonic & 5th.
def mode_profile(scale_deg, tonic_emph=6.5, fifth_emph=4.5, third_emph=4.0, other=3.0):
    """scale_deg: list of 7 ints in [0..11], degree 0 is tonic."""
    p = np.full(12, 1.0)  # off-scale
    p[scale_deg[0]] = tonic_emph  # tonic
    if len(scale_deg) >= 5:
        p[scale_deg[4]] = fifth_emph  # 5th
    if len(scale_deg) >= 3:
        p[scale_deg[2]] = third_emph  # 3rd
    for d in scale_deg:
        p[d] = max(p[d], other)
    return p


# Major/minor we keep KK; modes we build from scale degrees.
LYDIAN_DEG    = [0, 2, 4, 6, 7, 9, 11]   # 1 2 3 #4 5 6 7
MIXO_DEG      = [0, 2, 4, 5, 7, 9, 10]   # 1 2 3 4 5 6 b7
DORIAN_DEG    = [0, 2, 3, 5, 7, 9, 10]   # 1 2 b3 4 5 6 b7
PHRYGIAN_DEG  = [0, 1, 3, 5, 7, 8, 10]
AEOLIAN_DEG   = [0, 2, 3, 5, 7, 8, 10]   # natural minor
LOCRIAN_DEG   = [0, 1, 3, 5, 6, 8, 10]


def correlate(chroma_vec, profile):
    cv = chroma_vec - chroma_vec.mean()
    cv_n = np.linalg.norm(cv)
    best_root, best = 0, -np.inf
    for root in range(12):
        rolled = np.roll(profile, root)
        pv = rolled - rolled.mean()
        pv_n = np.linalg.norm(pv)
        s = float(np.dot(cv, pv) / (cv_n * pv_n + 1e-9))
        if s > best:
            best, best_root = s, root
    return best_root, best


MODES = {
    "major":      KK_MAJOR,
    "minor":      KK_MINOR,
    "lydian":     mode_profile(LYDIAN_DEG, tonic_emph=6.5, fifth_emph=4.5,
                                 third_emph=4.0, other=3.0) + np.array([0]*6 + [1.5] + [0]*5),  # extra #4 boost
    "mixolydian": mode_profile(MIXO_DEG),
    "dorian":     mode_profile(DORIAN_DEG),
    "aeolian":    mode_profile(AEOLIAN_DEG),
}

section_keys = []
for i in range(len(best_boundaries) - 1):
    a, b = best_boundaries[i], best_boundaries[i + 1]
    # Frame range in chroma (chroma is at sr/hop frames per second).
    f0 = int(a * sr / hop)
    f1 = int(b * sr / hop)
    if f1 - f0 < 8:
        continue
    cm = chroma_smooth[:, f0:f1].mean(axis=1)
    # Use bass chroma too — average over same frames.
    cb = C_low_chroma[:, f0:f1].mean(axis=1)
    cm = 0.6 * (cm / (cm.sum() + 1e-9)) + 0.4 * (cb / (cb.sum() + 1e-9))

    cands = []
    for name, prof in MODES.items():
        root, score = correlate(cm, prof)
        cands.append((score, PITCHES[root], name))
    cands.sort(reverse=True)
    section_keys.append((a, b, cands[:5], cm))
    print(f"\nS{i+1} {a:5.2f}–{b:5.2f}s  ({b-a:.2f}s):")
    print(f"  pitch order: {' '.join(p for p, _ in sorted(zip(PITCHES, cm), key=lambda x: -x[1]))}")
    for score, root, mode in cands[:5]:
        print(f"    {root:>2} {mode:<11} {score:+.3f}")

# ---------------- Plots ----------------
banner("PLOTS")
fig, axs = plt.subplots(3, 1, figsize=(15, 9))

# Chromagram with section boundaries.
img = librosa.display.specshow(
    chroma_smooth, x_axis="time", y_axis="chroma", sr=sr, hop_length=hop, ax=axs[0], cmap="magma"
)
for bt in best_boundaries:
    axs[0].axvline(bt, color="cyan", lw=0.8)
axs[0].set_title(f"Chromagram with section boundaries (k={best_k})")
fig.colorbar(img, ax=axs[0])

# Bar-level chord track.
chord_y = []
chord_seen = {}
for i, c in enumerate(bar_chords):
    if c not in chord_seen:
        chord_seen[c] = len(chord_seen)
    chord_y.append(chord_seen[c])
axs[1].step(bar_start_times, chord_y, where="post", lw=1.4, color="#3a6ea5")
axs[1].set_yticks(list(chord_seen.values()))
axs[1].set_yticklabels(list(chord_seen.keys()), fontsize=7)
axs[1].set_xlim(0, duration)
axs[1].set_title("Bar-level chord track (Viterbi-smoothed)")
axs[1].set_xlabel("time (s)")
for bt in best_boundaries:
    axs[1].axvline(bt, color="crimson", lw=0.5, alpha=0.5)

# Per-section mean chroma bars (small multiples).
n_sec = len(section_keys)
x = np.arange(12)
width = 0.8 / max(n_sec, 1)
for i, (a, b, cands, cm) in enumerate(section_keys):
    label = f"S{i+1} ({cands[0][1]} {cands[0][2]})"
    axs[2].bar(x + i * width - 0.4 + width / 2, cm, width=width, label=label)
axs[2].set_xticks(x)
axs[2].set_xticklabels(PITCHES)
axs[2].set_title("Per-section pitch-class strength (with top key/mode)")
axs[2].legend(fontsize=7, ncol=4)

plt.tight_layout()
fig.savefig(OUT / "overview_v2.png", dpi=120)
plt.close(fig)
print(f"saved {OUT / 'overview_v2.png'}")

# ---------------- Save ----------------
out_data = {
    "tempo_bpm": tempo,
    "n_bars": n_bars,
    "section_boundaries_sec": [float(b) for b in best_boundaries],
    "bar_chords": bar_chords,
    "section_keys": [
        {
            "start": float(a), "end": float(b),
            "candidates": [
                {"root": r, "mode": m, "score": float(s)} for s, r, m in cands
            ],
        }
        for a, b, cands, _ in section_keys
    ],
    "chord_segments": [
        {"start": float(t0), "end": float(t1), "chord": c} for c, t0, t1 in segments
    ],
}
with open(OUT / "summary_v2.json", "w") as f:
    json.dump(out_data, f, indent=2)
print(f"saved {OUT / 'summary_v2.json'}")

with open(OUT / "chords_v2.tsv", "w") as f:
    f.write("start_sec\tend_sec\tchord\n")
    for c, t0, t1 in segments:
        f.write(f"{t0:.3f}\t{t1:.3f}\t{c}\n")
print(f"saved {OUT / 'chords_v2.tsv'}  ({len(segments)} merged segments)")

print("\nDONE")
