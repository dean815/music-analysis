"""V3: tempo locked at 135 BPM, finer chord resolution, Dorian vs Aeolian test.

Builds on user feedback:
- Tempo is 135 BPM as recorded; half-time feel from ~30s.
- 0:02-0:09 + 0:16-0:23 are clear D Lydian (D -> E vamps).
- The intervening sections are turnarounds with out-of-key chords.
- The C# section (0:30+) is C# Dorian, not C# Aeolian.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
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
TEMPO_BPM = 135.0  # user-confirmed
HALF_TIME_AT = 30.0  # user-stated transition


def banner(t):
    print(f"\n{'=' * 64}\n{t}\n{'=' * 64}")


# ---------------- Load ----------------
y_stereo, sr = sf.read(str(AUDIO), always_2d=True)
y = y_stereo.mean(axis=1).astype(np.float32)
duration = len(y) / sr
hop = 1024  # finer than v2 to resolve sub-bar chord changes
print(f"loaded {duration:.2f}s @ {sr} Hz")
print(f"using user-confirmed tempo: {TEMPO_BPM} BPM ({60/TEMPO_BPM*1000:.1f}ms per beat)")

# ---------------- Build a synthetic beat grid at 135 BPM ----------------
# Force a metronomic grid rather than trusting beat_track. Phase-align by
# scanning offsets and picking the one whose ticks align with onset peaks.
beat_period_sec = 60.0 / TEMPO_BPM
oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
oenv_times = librosa.times_like(oenv, sr=sr, hop_length=hop)


def score_phase(phase_offset):
    """Higher = onset peaks land closer to beat ticks."""
    ticks = np.arange(phase_offset, duration, beat_period_sec)
    score = 0.0
    for t in ticks:
        idx = int(round(t * sr / hop))
        if 0 <= idx < len(oenv):
            window = oenv[max(0, idx - 2): idx + 3]
            score += float(window.max()) if len(window) else 0.0
    return score


phases = np.linspace(0, beat_period_sec, 32, endpoint=False)
phase_scores = [score_phase(p) for p in phases]
best_phase = phases[int(np.argmax(phase_scores))]
beat_times = np.arange(best_phase, duration, beat_period_sec)
print(f"phase-aligned beat 1 at t={best_phase:.3f}s")
print(f"total beats in song: {len(beat_times)}")

# Frame indices at the chroma resolution.
beat_frames = (beat_times * sr / hop).astype(int)

# ---------------- Chroma ----------------
chroma_full = librosa.feature.chroma_cqt(
    y=y, sr=sr, hop_length=hop, bins_per_octave=36, n_octaves=7
)
chroma_smooth = median_filter(chroma_full, size=(1, 7))
print(f"chroma shape: {chroma_smooth.shape}")

# Bass-emphasized chroma (low octaves only) — useful for chord-root detection.
C_low = np.abs(librosa.cqt(y=y, sr=sr, hop_length=hop,
                            fmin=librosa.note_to_hz("C2"),
                            n_bins=36, bins_per_octave=12))
C_low_chroma = np.zeros((12, C_low.shape[1]))
for i in range(C_low.shape[0]):
    C_low_chroma[i % 12] += C_low[i]
C_low_chroma = librosa.util.normalize(C_low_chroma, axis=0)

# ---------------- Per-2-beat (half-bar) chord pooling for fine resolution ----
# In the D Lydian sections, the user describes a "D -> E" vamp. At 135 BPM,
# if the vamp is 2 bars of D + 2 bars of E (8 beats each), or 1 bar D + 1 bar E,
# we want resolution finer than a full bar. Pool every 2 beats.
PERIOD_BEATS = 2
bar_starts_idx = np.arange(0, len(beat_times) - PERIOD_BEATS + 1, PERIOD_BEATS)
half_bar_times = beat_times[bar_starts_idx]
print(f"\nhalf-bar grid (every {PERIOD_BEATS} beats): {len(half_bar_times)} positions")


def pool(matrix, beat_frames_, group_size):
    cols = []
    for i in range(0, len(beat_frames_) - group_size + 1, group_size):
        f0 = beat_frames_[i]
        f1 = beat_frames_[i + group_size] if i + group_size < len(beat_frames_) else matrix.shape[1]
        f0 = max(0, min(f0, matrix.shape[1] - 1))
        f1 = max(f0 + 1, min(f1, matrix.shape[1]))
        cols.append(np.median(matrix[:, f0:f1], axis=1))
    return np.stack(cols, axis=1)


chroma_hb = pool(chroma_smooth, beat_frames, PERIOD_BEATS)
chroma_hb_bass = pool(C_low_chroma, beat_frames, PERIOD_BEATS)


# ---------------- Chord templates ----------------
def chord_templates():
    base = {
        "":     [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
        "m":    [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
        "sus2": [1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0],
        "sus4": [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0],
        "maj7": [0.9, 0, 0, 0, 0.9, 0, 0, 0.9, 0, 0, 0, 0.7],
        "7":    [0.9, 0, 0, 0, 0.9, 0, 0, 0.9, 0, 0, 0.7, 0],
        "m7":   [0.9, 0, 0, 0.9, 0, 0, 0, 0.9, 0, 0, 0.7, 0],
        "add9": [0.9, 0, 0.7, 0, 0.9, 0, 0, 0.9, 0, 0, 0, 0],
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

# Combine harmonic chroma with bass-weighted chroma (root detection).
combined = 0.7 * chroma_hb + 0.3 * chroma_hb_bass
combined_n = combined / (np.linalg.norm(combined, axis=0, keepdims=True) + 1e-9)
emit = tpl_mat @ combined_n  # (n_chords, n_periods)

# Light Viterbi (small self-bonus so changes happen).
n_chords, n_periods = emit.shape
SELF_BONUS = 0.06
dp = np.full((n_chords, n_periods), -np.inf)
back = np.zeros((n_chords, n_periods), dtype=np.int32)
dp[:, 0] = emit[:, 0]
for t in range(1, n_periods):
    prev = dp[:, t - 1]
    max_prev = float(prev.max())
    argmax_prev = int(prev.argmax())
    for c in range(n_chords):
        stay = prev[c] + SELF_BONUS
        switch = max_prev
        if stay >= switch:
            dp[c, t] = emit[c, t] + stay
            back[c, t] = c
        else:
            dp[c, t] = emit[c, t] + switch
            back[c, t] = argmax_prev

path = np.zeros(n_periods, dtype=np.int32)
path[-1] = int(dp[:, -1].argmax())
for t in range(n_periods - 2, -1, -1):
    path[t] = back[path[t + 1], t + 1]
period_chords = [tpl_names[i] for i in path]

# Top-3 alternates for context.
top3_idx = np.argsort(-emit, axis=0)[:3, :]
top3 = [[tpl_names[top3_idx[r, t]] for r in range(3)] for t in range(n_periods)]
top3_scores = [[float(emit[top3_idx[r, t], t]) for r in range(3)] for t in range(n_periods)]

# ---------------- Print fine-grained progression with section labels --------
banner("FINE-GRAINED CHORD MAP (every 2 beats ≈ 0.89s)")

def label_for(t):
    if t < 2.0: return "intro       "
    if 2.0 <= t < 9.0: return "A1 (D-Lyd)  "
    if 9.0 <= t < 16.0: return "TURN1       "
    if 16.0 <= t < 23.0: return "A2 (D-Lyd)  "
    if 23.0 <= t < 30.0: return "TURN2       "
    if 30.0 <= t < 62.0: return "B (C#Dorian)"
    return "C (F# pad)  "


for i, (chord, t_start) in enumerate(zip(period_chords, half_bar_times)):
    t_end = half_bar_times[i + 1] if i + 1 < len(half_bar_times) else duration
    alts = top3[i]
    s = top3_scores[i]
    label = label_for(t_start)
    print(f"  {label}  {t_start:6.2f}s  {chord:<8}   "
          f"(top3: {alts[0]}/{alts[1]}/{alts[2]}, scores {s[0]:.2f}/{s[1]:.2f}/{s[2]:.2f})")

# ---------------- Chord histograms per section -------------
banner("CHORD HISTOGRAM PER USER-DEFINED SECTION")
sections = [
    ("A1 (D Lydian)",       2.0,  9.0),
    ("Turnaround 1",        9.0, 16.0),
    ("A2 (D Lydian)",      16.0, 23.0),
    ("Turnaround 2",       23.0, 30.0),
    ("B (C# Dorian)",      30.0, 62.0),
    ("C (F# pad)",         62.0, duration),
]

section_chord_summaries = {}
for name, t0, t1 in sections:
    chords_here = [period_chords[i] for i, t in enumerate(half_bar_times) if t0 <= t < t1]
    cnt = Counter(chords_here)
    section_chord_summaries[name] = cnt
    print(f"\n{name}  ({t0:.1f}-{t1:.1f}s):")
    for ch, n in cnt.most_common():
        bar = "█" * n
        print(f"  {ch:<10}  {n:3d}  {bar}")

# ---------------- DORIAN vs AEOLIAN test on the C# section ------------------
banner("DORIAN vs AEOLIAN TEST on B section (30-62s)")

t0, t1 = 30.0, 62.0
f0 = int(t0 * sr / hop)
f1 = int(t1 * sr / hop)
section_chroma = chroma_smooth[:, f0:f1].mean(axis=1)
section_chroma_norm = section_chroma / section_chroma.sum()

a_idx, asharp_idx = 9, 10  # A=9, A#=10
print("Section mean chroma (C# section):")
for i, p in enumerate(PITCHES):
    bar = "█" * int(section_chroma_norm[i] * 200)
    flag = ""
    if i == a_idx: flag = "  ← A natural (b6 of C# Aeolian)"
    if i == asharp_idx: flag = "  ← A# (6 of C# Dorian)"
    print(f"  {p:>2}  {section_chroma_norm[i]:.4f}  {bar}{flag}")

a_strength = section_chroma_norm[a_idx]
asharp_strength = section_chroma_norm[asharp_idx]
ratio_dorian = asharp_strength / max(a_strength, 1e-6)
print(f"\nA  natural strength: {a_strength:.4f}")
print(f"A# strength        : {asharp_strength:.4f}")
print(f"A#/A ratio         : {ratio_dorian:.2f}")

# Also: compute templates for C# Dorian vs C# Aeolian and correlate.
def mode_template(scale_deg, tonic_emph=6.5, fifth_emph=4.5, third_emph=4.0,
                   sixth_emph=3.5, other=3.0):
    p = np.full(12, 1.0)
    p[scale_deg[0]] = tonic_emph
    if len(scale_deg) >= 5: p[scale_deg[4]] = fifth_emph
    if len(scale_deg) >= 3: p[scale_deg[2]] = third_emph
    if len(scale_deg) >= 6: p[scale_deg[5]] = sixth_emph  # 6th is the discriminator
    for d in scale_deg:
        p[d] = max(p[d], other)
    return p


C_AEOLIAN_DEG = [0, 2, 3, 5, 7, 8, 10]   # 1 2 b3 4 5 b6 b7  → with C# tonic uses A
C_DORIAN_DEG  = [0, 2, 3, 5, 7, 9, 10]   # 1 2 b3 4 5  6 b7  → with C# tonic uses A#

# Build profiles and rotate to C# (root index 1).
aeo_profile = np.roll(mode_template(C_AEOLIAN_DEG, sixth_emph=3.5), 1)
dor_profile = np.roll(mode_template(C_DORIAN_DEG, sixth_emph=3.5), 1)


def cosine(a, b):
    a = a - a.mean(); b = b - b.mean()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


cos_aeo = cosine(section_chroma, aeo_profile)
cos_dor = cosine(section_chroma, dor_profile)
print(f"\nProfile correlation:")
print(f"  C# Aeolian  : {cos_aeo:+.4f}")
print(f"  C# Dorian   : {cos_dor:+.4f}")
print(f"  -> {'DORIAN' if cos_dor > cos_aeo else 'AEOLIAN'} wins by {abs(cos_dor - cos_aeo):.4f}")

# Also test on melody pyin pitches (already did pyin — re-do quickly).
print("\nMelody-only test (pyin, voiced frames in 30-62s):")
print("  Re-running pyin on the C# section…")
y_section = y[int(t0*sr):int(t1*sr)]
f0_arr, _, _ = librosa.pyin(
    y_section,
    fmin=float(librosa.note_to_hz("E3")),
    fmax=float(librosa.note_to_hz("C7")),
    sr=sr, frame_length=4096, hop_length=512,
)
midi_arr = librosa.hz_to_midi(f0_arr)
pcs = []
for m in midi_arr:
    if not np.isnan(m):
        pcs.append(int(round(m)) % 12)
pcs = np.array(pcs)
n_a = int(np.sum(pcs == 9))
n_asharp = int(np.sum(pcs == 10))
total_pcs = len(pcs)
print(f"  voiced frames: {total_pcs}")
print(f"  A natural in melody : {n_a}  ({100*n_a/max(total_pcs,1):.2f}%)")
print(f"  A#       in melody  : {n_asharp}  ({100*n_asharp/max(total_pcs,1):.2f}%)")

# ---------------- D Lydian II chord verification (D->E vamp) ----------------
banner("D LYDIAN II VERIFICATION on A1 (2-9s)")
a1_chords = section_chord_summaries["A1 (D Lydian)"]
print("Chords detected in A1:", dict(a1_chords))
# Look for any E-rooted major chord variants.
e_chord_count = sum(n for ch, n in a1_chords.items() if ch.startswith("E") and "m" not in ch)
d_chord_count = sum(n for ch, n in a1_chords.items() if ch.startswith("D") and "D#" not in ch and "m" not in ch)
total = sum(a1_chords.values())
print(f"D-rooted (major/sus/add9/maj7) periods: {d_chord_count}/{total}")
print(f"E-rooted (major/sus/add9/maj7) periods: {e_chord_count}/{total}")
if e_chord_count > 0 and d_chord_count > 0:
    print("✓ Confirms D → E vamp (Lydian I → II)")

# ---------------- Identify out-of-key turnaround chords ---------------------
banner("TURNAROUND OUT-OF-KEY CHORDS")

# D Lydian diatonic chord roots: D E F# G# A B C#
DLYD_ROOTS = {"D", "E", "F#", "G#", "A", "B", "C#"}


def chord_root(chord_label):
    if len(chord_label) >= 2 and chord_label[1] == "#":
        return chord_label[:2]
    return chord_label[:1]


for sect in ("Turnaround 1", "Turnaround 2"):
    cnt = section_chord_summaries[sect]
    print(f"\n{sect}:")
    out_of_key = []
    in_key = []
    for ch, n in cnt.items():
        root = chord_root(ch)
        if root in DLYD_ROOTS:
            in_key.append((ch, n))
        else:
            out_of_key.append((ch, n))
    print("  in-key:    ", in_key)
    print("  OUT-OF-KEY:", out_of_key)

# ---------------- Plot --------------------
banner("PLOT")
fig, axs = plt.subplots(3, 1, figsize=(16, 9))

# 1. Chromagram with section bands.
img = librosa.display.specshow(chroma_smooth, x_axis="time", y_axis="chroma",
                                sr=sr, hop_length=hop, ax=axs[0], cmap="magma")
band_colors = {"A1 (D Lydian)": "#3a8c3a", "Turnaround 1": "#aa6622",
                "A2 (D Lydian)": "#3a8c3a", "Turnaround 2": "#aa6622",
                "B (C# Dorian)": "#3a3a8c", "C (F# pad)": "#8c3a8c"}
for name, t0_, t1_ in sections:
    axs[0].axvspan(t0_, t1_, alpha=0.15, color=band_colors.get(name, "gray"))
    axs[0].text(t0_ + 0.5, 11.5, name, fontsize=8, color="white",
                bbox=dict(facecolor=band_colors.get(name, "gray"), alpha=0.7, pad=1))
axs[0].set_title(f"Chromagram with user-defined sections | tempo locked at {TEMPO_BPM} BPM")
fig.colorbar(img, ax=axs[0])

# 2. Chord track at half-bar resolution.
chord_seen = {}
ys = []
for c in period_chords:
    if c not in chord_seen:
        chord_seen[c] = len(chord_seen)
    ys.append(chord_seen[c])
axs[1].step(half_bar_times, ys, where="post", lw=1.4, color="#3a6ea5")
axs[1].set_yticks(list(chord_seen.values()))
axs[1].set_yticklabels(list(chord_seen.keys()), fontsize=7)
for name, t0_, t1_ in sections:
    axs[1].axvspan(t0_, t1_, alpha=0.1, color=band_colors.get(name, "gray"))
axs[1].set_xlim(0, duration)
axs[1].set_title("Half-bar (every 2 beats) chord track — light Viterbi smoothing")
axs[1].set_xlabel("time (s)")

# 3. A vs A# strength over time (rolling mean) for Dorian/Aeolian discrim.
window_frames = int(2.0 * sr / hop)  # 2-second smoothing
def smooth(x, w):
    if w < 2: return x
    pad = w // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones(w) / w
    return np.convolve(xp, kernel, mode="valid")[: len(x)]


t_chroma = librosa.times_like(chroma_smooth, sr=sr, hop_length=hop)
a_track = smooth(chroma_smooth[a_idx], window_frames)
asharp_track = smooth(chroma_smooth[asharp_idx], window_frames)
axs[2].plot(t_chroma, a_track, label="A natural (Aeolian b6)", color="crimson", lw=1.2)
axs[2].plot(t_chroma, asharp_track, label="A# (Dorian 6)", color="seagreen", lw=1.2)
for name, t0_, t1_ in sections:
    axs[2].axvspan(t0_, t1_, alpha=0.08, color=band_colors.get(name, "gray"))
axs[2].axvspan(30, 62, alpha=0.05, color="blue")
axs[2].set_xlim(0, duration)
axs[2].set_title("A vs A# strength over time — discriminates Dorian (A#) from Aeolian (A)")
axs[2].set_xlabel("time (s)")
axs[2].legend()
axs[2].grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(OUT / "overview_v3.png", dpi=120)
plt.close(fig)
print(f"saved {OUT / 'overview_v3.png'}")

# ---------------- Save a clean chord chart -----------------
with open(OUT / "chord_chart_v3.txt", "w") as f:
    f.write(f"# Chord chart at {TEMPO_BPM} BPM, half-bar resolution\n")
    f.write(f"# Beat 1 phase-aligned at t={best_phase:.3f}s\n\n")
    for sect_name, t0_, t1_ in sections:
        f.write(f"\n[{sect_name}]  ({t0_:.1f}-{t1_:.1f}s)\n")
        for i, (c, t) in enumerate(zip(period_chords, half_bar_times)):
            if t0_ <= t < t1_:
                f.write(f"  {t:6.2f}s  |  {c}\n")
print(f"saved {OUT / 'chord_chart_v3.txt'}")

print("\nDONE")
