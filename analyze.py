"""Analyze a Logic bounce: tempo, key, chords, structure, dynamics."""
from __future__ import annotations

import argparse
import json
import sys
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


def banner(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ------------------------- 1. Load + basic stats ------------------------
banner("FILE")
info = sf.info(str(AUDIO))
print(f"path        : {AUDIO}")
print(f"sample rate : {info.samplerate} Hz")
print(f"channels    : {info.channels}")
print(f"frames      : {info.frames}")
print(f"duration    : {info.duration:.2f} s ({info.duration/60:.2f} min)")
print(f"subtype     : {info.subtype} ({info.subtype_info})")

# Load as mono for analysis at native SR; keep stereo only for L/R balance check.
y_stereo, sr = sf.read(str(AUDIO), always_2d=True)
y = y_stereo.mean(axis=1).astype(np.float32)
duration = len(y) / sr

# Stereo width: corr between L and R. Higher = more mono.
L, R = y_stereo[:, 0].astype(np.float32), y_stereo[:, 1].astype(np.float32)
lr_corr = float(np.corrcoef(L, R)[0, 1])
mid = 0.5 * (L + R)
side = 0.5 * (L - R)
mid_rms = float(np.sqrt(np.mean(mid**2)))
side_rms = float(np.sqrt(np.mean(side**2)))
side_to_mid_db = 20 * np.log10(side_rms / max(mid_rms, 1e-9))
print(f"L/R corr    : {lr_corr:+.3f}   (1=mono, 0=independent, -1=antiphase)")
print(f"S/M ratio   : {side_to_mid_db:+.2f} dB   (more negative = narrower stereo)")

# Loudness curve (RMS over time, in dBFS).
hop = 2048
rms = librosa.feature.rms(y=y, frame_length=4096, hop_length=hop)[0]
rms_db = 20 * np.log10(np.maximum(rms, 1e-6))
times_rms = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
print(f"peak dBFS   : {20*np.log10(np.max(np.abs(y))):.2f}")
print(f"avg RMS dBFS: {20*np.log10(np.sqrt(np.mean(y**2))):.2f}")
print(f"crest factor: {20*np.log10(np.max(np.abs(y))/np.sqrt(np.mean(y**2))):.2f} dB")

# ------------------------- 2. Tempo + beats ----------------------------
banner("TEMPO + BEATS")
tempo_arr, beats = librosa.beat.beat_track(y=y, sr=sr, units="frames")
tempo = float(np.atleast_1d(tempo_arr)[0])
beat_times = librosa.frames_to_time(beats, sr=sr)

# beat_track runs on librosa's default 512-sample hop, but the chroma and MFCC
# features below are computed at hop=2048. Beat frame indices are therefore on a
# 4x finer grid than those arrays and cannot be used as column indices directly —
# doing so pushes every index past the end of the array, and librosa.util.sync
# silently clamps them all into a single slice. Re-grid via seconds instead.
beat_frames_feat = librosa.time_to_frames(beat_times, sr=sr, hop_length=hop)
beat_frames_feat = np.unique(np.clip(beat_frames_feat, 0, None))
# Times matching the re-gridded indices. Columns of anything sync'd against
# beat_frames_feat line up with these, not with beat_times, since np.unique may
# merge two beats that land in the same 46 ms feature frame.
beat_times_feat = librosa.frames_to_time(beat_frames_feat, sr=sr, hop_length=hop)

# librosa.util.sync treats its index array as INTERIOR boundaries: it prepends 0
# and appends n_frames, so it returns len(idx)+1 columns, not len(idx). Column j
# therefore spans [seg_bounds[j], seg_bounds[j+1]) in seconds — labelling column j
# with beat_times_feat[j] would name its END, shifting every chord one beat late
# and leaving the audio before the first beat unlabelled entirely.
seg_bounds = np.concatenate(([0.0], beat_times_feat, [duration]))

print(f"tempo (BPM) : {tempo:.2f}")
print(f"# beats     : {len(beat_times)}")
if len(beat_times) > 1:
    ibi = np.diff(beat_times)
    print(f"beat IBI    : mean {ibi.mean()*1000:.1f} ms, std {ibi.std()*1000:.1f} ms")

# Tempogram peak as cross-check (sometimes beat_track halves/doubles).
oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
tempogram = librosa.feature.tempogram(onset_envelope=oenv, sr=sr, hop_length=hop)
ac_global = np.mean(tempogram, axis=1)
bpms = librosa.tempo_frequencies(len(ac_global), hop_length=hop, sr=sr)
mask = (bpms >= 40) & (bpms <= 220)
top_bpms = bpms[mask][np.argsort(ac_global[mask])[::-1][:5]]
print(f"top tempogram BPMs: {[round(float(b), 2) for b in top_bpms]}")

# Warn when beat_track tempo is ~2× a strong tempogram peak — a common
# failure mode on half-time R&B, hip-hop, and ballads where the hi-hat
# is louder than the kick.
half_tempo = tempo / 2.0
half_time_suspected = False
for tb in top_bpms:
    if abs(tb - half_tempo) / max(half_tempo, 1e-6) < 0.05:  # within 5%
        half_time_suspected = True
        print(
            f"\nWARNING: beat_track ({tempo:.1f} BPM) ≈ 2× tempogram peak "
            f"({tb:.1f} BPM).\n"
            f"  Song may have a half-time feel; {tb:.2f} BPM may be the true pulse.\n"
            f"  If so: python3 analyze_v3.py --audio <file> --bpm {tb:.2f}"
        )
        break

# ------------------------- 3. Key / mode -------------------------------
banner("KEY / MODE")

# Chromagram — CQT-based, more robust for harmonic content than STFT chroma.
chroma_cqt = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, bins_per_octave=36)
chroma_mean = chroma_cqt.mean(axis=1)
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
print("mean chroma:")
for p, v in sorted(zip(PITCHES, chroma_mean), key=lambda x: -x[1]):
    bar = "█" * int(v * 50)
    print(f"  {p:>2}  {v:.3f}  {bar}")

# Krumhansl-Kessler key profiles for major and minor; add Lydian/Mixolydian custom.
KK_MAJOR = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
KK_MINOR = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
# Lydian: like major but with #4 emphasized. Take major and swap weights of 4 and #4.
LYDIAN = KK_MAJOR.copy()
LYDIAN[5], LYDIAN[6] = KK_MAJOR[6] * 1.05, KK_MAJOR[5] * 0.6  # boost #4, weaken nat 4
MIXO = KK_MAJOR.copy()
MIXO[10], MIXO[11] = KK_MAJOR[11] * 1.05, KK_MAJOR[10] * 0.6  # boost b7, weaken nat 7
DORIAN = KK_MINOR.copy()
DORIAN[9], DORIAN[8] = KK_MINOR[8] * 1.05, KK_MINOR[9] * 0.6  # raised 6 in dorian


def correlate_profile(chroma_vec: np.ndarray, profile: np.ndarray) -> tuple[int, float]:
    best_root, best_score = 0, -np.inf
    cv = chroma_vec - chroma_vec.mean()
    pv = profile - profile.mean()
    pv_norm = np.linalg.norm(pv)
    cv_norm = np.linalg.norm(cv)
    for root in range(12):
        rolled = np.roll(profile, root)
        pv2 = rolled - rolled.mean()
        score = float(np.dot(cv, pv2) / (cv_norm * np.linalg.norm(pv2) + 1e-9))
        if score > best_score:
            best_score, best_root = score, root
    return best_root, best_score


candidates = []
for name, prof in [("major", KK_MAJOR), ("minor", KK_MINOR),
                    ("lydian", LYDIAN), ("mixolydian", MIXO), ("dorian", DORIAN)]:
    root, score = correlate_profile(chroma_mean, prof)
    candidates.append((score, PITCHES[root], name))

candidates.sort(reverse=True)
print("\ntop key/mode candidates (cosine similarity to profile):")
for score, root, mode in candidates[:8]:
    print(f"  {root:>2} {mode:<11} {score:+.3f}")

# ------------------------- 4. Chord estimation -------------------------
banner("CHORD ESTIMATION (template matching)")

# Build major / minor / sus4 / 7th templates and slide across 12 roots.
def chord_templates() -> list[tuple[str, np.ndarray]]:
    base = {
        "":      [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],   # major triad
        "m":     [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],   # minor triad
        "sus2":  [1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0],
        "sus4":  [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0],
        "maj7":  [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1],
        "7":     [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0],
        "m7":    [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0],
        "add9":  [1, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0],
    }
    out = []
    for quality, tpl in base.items():
        v = np.array(tpl, dtype=float)
        v /= np.linalg.norm(v)
        for root in range(12):
            out.append((f"{PITCHES[root]}{quality}", np.roll(v, root)))
    return out


templates = chord_templates()
tpl_names = [n for n, _ in templates]
tpl_mat = np.stack([t for _, t in templates])  # (N_templates, 12)

# Beat-synchronous chroma (median pooled), gives stable per-beat estimates.
chroma_sync = librosa.util.sync(chroma_cqt, beat_frames_feat, aggregate=np.median)
chroma_sync_n = chroma_sync / (np.linalg.norm(chroma_sync, axis=0, keepdims=True) + 1e-9)
scores = tpl_mat @ chroma_sync_n  # (N_templates, N_beats)
best_idx = scores.argmax(axis=0)
beat_chords = [tpl_names[i] for i in best_idx]

# Collapse repeats into chord segments (merge consecutive identical chords).
segments = []
for i, c in enumerate(beat_chords):
    t0, t_end = float(seg_bounds[i]), float(seg_bounds[i + 1])
    if segments and segments[-1][0] == c:
        segments[-1] = (c, segments[-1][1], t_end)
    else:
        segments.append((c, t0, t_end))

# Print first 60 segments.
print("first chord segments (chord, start, end, duration):")
for c, t0, t1 in segments[:60]:
    print(f"  {c:<8}  {t0:6.2f} → {t1:6.2f}   ({t1-t0:5.2f}s)")
print(f"... {len(segments)} total chord segments")

# Chord histogram (by total time).
from collections import defaultdict
chord_time = defaultdict(float)
for c, t0, t1 in segments:
    chord_time[c] += (t1 - t0)
top_chords = sorted(chord_time.items(), key=lambda kv: -kv[1])[:12]
print("\ntop chords by total time:")
for c, t in top_chords:
    pct = 100 * t / duration
    print(f"  {c:<8}  {t:6.2f}s  ({pct:5.1f}%)")

# ------------------------- 5. Structural segmentation -----------------
banner("STRUCTURE (self-similarity segmentation)")

mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop)
mfcc_sync = librosa.util.sync(mfcc, beat_frames_feat, aggregate=np.mean)
# Normalize and build recurrence matrix; then agglomerative segmentation.
R = librosa.segment.recurrence_matrix(
    mfcc_sync, mode="affinity", sym=True, width=3
)
try:
    boundaries_beats = librosa.segment.agglomerative(mfcc_sync, k=6)
    boundary_beat_idx = boundaries_beats
    # agglomerative() returns column indices into mfcc_sync, so a boundary at
    # column i starts at seg_bounds[i] — same interior-boundary convention.
    boundary_times = [
        float(seg_bounds[i]) for i in boundary_beat_idx if i < len(seg_bounds)
    ]
    if not boundary_times or boundary_times[0] > 0.5:
        boundary_times = [0.0] + boundary_times
    if boundary_times[-1] < duration - 0.5:
        boundary_times.append(float(duration))
    print("section boundaries (s):")
    for i in range(len(boundary_times) - 1):
        a, b = boundary_times[i], boundary_times[i + 1]
        print(f"  section {i+1}: {a:6.2f} → {b:6.2f}   ({b-a:5.2f}s)")
except Exception as e:  # noqa: BLE001
    print(f"agglomerative segmentation failed: {e}")
    boundary_times = [0.0, float(duration)]

# ------------------------- 6. Spectral character ----------------------
banner("SPECTRAL CHARACTER")
spec_centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
spec_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, hop_length=hop, roll_percent=0.85)[0]
spec_bw = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=hop)[0]
zcr = librosa.feature.zero_crossing_rate(y, hop_length=hop)[0]
print(f"spectral centroid : mean {spec_centroid.mean():7.1f} Hz   median {np.median(spec_centroid):7.1f} Hz")
print(f"spectral rolloff  : mean {spec_rolloff.mean():7.1f} Hz")
print(f"spectral bandwidth: mean {spec_bw.mean():7.1f} Hz")
print(f"zero-crossing rate: mean {zcr.mean():.4f}")

# ------------------------- 7. Plots -----------------------------------
banner("PLOTS")
fig, axs = plt.subplots(4, 1, figsize=(14, 11), sharex=False)

axs[0].plot(times_rms, rms_db, lw=0.8, color="#444")
axs[0].set_title("Loudness (RMS dBFS)")
axs[0].set_ylabel("dBFS")
axs[0].set_xlabel("time (s)")
axs[0].set_xlim(0, duration)
for bt in boundary_times:
    axs[0].axvline(bt, color="crimson", lw=0.6, alpha=0.5)

img = librosa.display.specshow(
    chroma_cqt, x_axis="time", y_axis="chroma", sr=sr, hop_length=hop, ax=axs[1], cmap="magma"
)
axs[1].set_title("Chromagram (CQT)")
fig.colorbar(img, ax=axs[1])

axs[2].bar(PITCHES, chroma_mean, color="#3a6ea5")
axs[2].set_title(f"Mean chroma (top key candidate: {candidates[0][1]} {candidates[0][2]})")
axs[2].set_ylabel("strength")

axs[3].plot(times_rms, spec_centroid[: len(times_rms)], lw=0.8, label="centroid", color="#3a6ea5")
axs[3].plot(times_rms, spec_rolloff[: len(times_rms)], lw=0.8, label="rolloff 85%", color="#a53a3a")
axs[3].set_title("Spectral centroid + rolloff (Hz)")
axs[3].set_ylabel("Hz")
axs[3].set_xlabel("time (s)")
axs[3].set_xlim(0, duration)
axs[3].legend(loc="upper right")

plt.tight_layout()
plot_path = OUT / "overview.png"
fig.savefig(plot_path, dpi=120)
plt.close(fig)
print(f"saved {plot_path}")

# ------------------------- 8. JSON summary ----------------------------
summary = {
    "file": str(AUDIO),
    "duration_sec": float(duration),
    "sample_rate": int(sr),
    "channels": int(info.channels),
    "peak_dbfs": float(20 * np.log10(np.max(np.abs(y)))),
    "rms_dbfs": float(20 * np.log10(np.sqrt(np.mean(y**2)))),
    "lr_correlation": lr_corr,
    "side_to_mid_db": float(side_to_mid_db),
    "tempo_bpm": tempo,
    "tempogram_top_bpms": [float(b) for b in top_bpms],
    "half_time_suspected": half_time_suspected,
    "mean_chroma": {p: float(v) for p, v in zip(PITCHES, chroma_mean)},
    "key_candidates": [
        {"root": r, "mode": m, "score": float(s)} for s, r, m in candidates[:8]
    ],
    "top_chords_by_time": [{"chord": c, "seconds": float(t)} for c, t in top_chords],
    "section_boundaries_sec": [float(b) for b in boundary_times],
    "spectral": {
        "centroid_mean_hz": float(spec_centroid.mean()),
        "rolloff_mean_hz": float(spec_rolloff.mean()),
        "bandwidth_mean_hz": float(spec_bw.mean()),
        "zcr_mean": float(zcr.mean()),
    },
}
with open(OUT / "summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"saved {OUT / 'summary.json'}")

# Also save full chord segment list as TSV.
with open(OUT / "chords.tsv", "w") as f:
    f.write("start_sec\tend_sec\tchord\n")
    for c, t0, t1 in segments:
        f.write(f"{t0:.3f}\t{t1:.3f}\t{c}\n")
print(f"saved {OUT / 'chords.tsv'}  ({len(segments)} segments)")

print("\nDONE")
