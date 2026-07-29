"""Analyze a Logic bounce: tempo, key, chords, structure, dynamics."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import librosa
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

import paths


def banner(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def finite_or_none(x: float) -> float | None:
    """float(x), or None if it is inf or nan.

    json.dump writes bare Infinity/NaN tokens for those, which Python reads back
    happily but which are not JSON. Consumers disagree about what to do with
    them: JavaScript's JSON.parse raises, while jq silently converts -Infinity to
    -1.8e308 — a plausible-looking number that is not the measurement. null is
    the honest record of "not measurable", matching tempo_bpm's treatment of a
    track with no detectable pulse.
    """
    return float(x) if np.isfinite(x) else None


def stereo_metrics(y_stereo: np.ndarray) -> tuple[float | None, float | None]:
    """(L/R correlation, side-to-mid dB) for an (n_samples, n_channels) array.

    Higher correlation = more mono; more negative dB = narrower. Three inputs have
    no meaningful width to report, and each returns None for the affected value
    rather than a stand-in number, on the same reasoning as tempo_bpm: a 0.0 or a
    -inf reads downstream as a measurement.

      - a mono file has no second channel. Indexing one used to raise IndexError,
        killing a run that every other section would have handled fine.
      - a dual-mono file has an exactly-zero side signal, so the dB ratio is -inf.
      - a file with a silent or constant channel gives corrcoef = nan, since
        corrcoef divides by each channel's standard deviation.

    A hard-panned file is NOT one of these: mid and side carry equal energy there,
    so 0.0 dB is a real measurement rather than a fallback.
    """
    if y_stereo.shape[1] < 2:
        return None, None

    L, R = y_stereo[:, 0].astype(np.float32), y_stereo[:, 1].astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        lr_corr = finite_or_none(np.corrcoef(L, R)[0, 1])
    mid = 0.5 * (L + R)
    side = 0.5 * (L - R)
    mid_rms = float(np.sqrt(np.mean(mid**2)))
    side_rms = float(np.sqrt(np.mean(side**2)))
    with np.errstate(divide="ignore"):
        side_to_mid_db = finite_or_none(20 * np.log10(side_rms / max(mid_rms, 1e-9)))
    return lr_corr, side_to_mid_db


# ------------------------- Half-time detection -------------------------
# Warn when beat_track locked onto 2× the real pulse — the common failure mode
# on half-time R&B, hip-hop, and ballads where the hi-hat is louder than the kick.
#
# A peak near tempo/2 is NOT on its own evidence of that. The autocorrelation of
# any periodic pulse train has peaks at 2× and 3× the beat period, so that peak
# is present by construction even when beat_track is exactly right — on synthetic
# click tracks at 70-200 BPM it fired on 21 of 24 correct detections. Two further
# conditions are what carry the actual signal:
#   1. the detected tempo is too fast to plausibly be the notated pulse, and
#   2. the half-tempo peak is genuinely STRONGER than the peak at the tempo.
# Both matter: (2) alone still misfires because the BPM grid here is 60*sr/(hop*lag),
# which is ~14 BPM coarse near 136 but ~3.6 BPM near 68, so the tempo-side peak can
# fall between bins and read low purely from quantisation.
IMPLAUSIBLY_FAST_BPM = 150.0
TEMPO_PEAK_TOLERANCE = 0.05  # how near tempo/2 a peak must sit to count as "the half"


def ac_strength(band_bpms: np.ndarray, band_ac: np.ndarray, target_bpm: float) -> float:
    """Autocorrelation strength at the tempogram bin nearest to target_bpm."""
    return float(band_ac[int(np.argmin(np.abs(band_bpms - target_bpm)))])


def tempogram_peaks(
    y: np.ndarray,
    sr: float,
    hop: int,
    *,
    bpm_range: tuple[float, float] = (40.0, 220.0),
    n_top: int = 5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Global tempogram restricted to a plausible BPM band.

    Returns (band_bpms, band_ac, top_bpms), where top_bpms is ordered by
    descending autocorrelation strength. The band arrays are what ac_strength
    indexes into, so the three travel together.
    """
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempogram = librosa.feature.tempogram(onset_envelope=oenv, sr=sr, hop_length=hop)
    ac_global = np.mean(tempogram, axis=1)
    bpms = librosa.tempo_frequencies(len(ac_global), hop_length=hop, sr=sr)
    mask = (bpms >= bpm_range[0]) & (bpms <= bpm_range[1])
    band_bpms, band_ac = bpms[mask], ac_global[mask]
    top_bpms = band_bpms[np.argsort(band_ac)[::-1][:n_top]]
    return band_bpms, band_ac, top_bpms


class HalfTimeCheck(NamedTuple):
    """Outcome of the half-time test. Strengths are None when no half peak was found."""

    suspected: bool
    half_bpm: float | None = None
    half_strength: float | None = None
    tempo_strength: float | None = None


def suspect_half_time(
    tempo: float,
    top_bpms: np.ndarray,
    band_bpms: np.ndarray,
    band_ac: np.ndarray,
    *,
    min_bpm: float = IMPLAUSIBLY_FAST_BPM,
    tolerance: float = TEMPO_PEAK_TOLERANCE,
) -> HalfTimeCheck:
    """Decide whether `tempo` looks like 2× the real pulse.

    Only the first peak within `tolerance` of tempo/2 is considered — top_bpms is
    ordered by descending autocorrelation, so that is the strongest candidate for
    "the half", and a weaker peak that also happens to sit near tempo/2 should not
    get a second bite.
    """
    if tempo < min_bpm:
        return HalfTimeCheck(False)

    half_tempo = tempo / 2.0
    for tb in top_bpms:
        if abs(tb - half_tempo) / max(half_tempo, 1e-6) < tolerance:
            half_strength = ac_strength(band_bpms, band_ac, tb)
            tempo_strength = ac_strength(band_bpms, band_ac, tempo)
            return HalfTimeCheck(
                half_strength > tempo_strength, float(tb), half_strength, tempo_strength
            )
    return HalfTimeCheck(False)


# ------------------------- Key / mode profiles -------------------------
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    paths.add_args(parser, audio=True)
    args = parser.parse_args()
    AUDIO = paths.require(args.audio, "MUSIC_AUDIO")
    OUT = paths.ensure_dir(args.out)

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

    # Stereo width. Either value is None when the file has no measurable width —
    # mono, dual-mono, or a silent channel. See stereo_metrics.
    lr_corr, side_to_mid_db = stereo_metrics(y_stereo)

    lr_text = f"{lr_corr:+.3f}" if lr_corr is not None else "   n/a"
    smd_text = f"{side_to_mid_db:+.2f} dB" if side_to_mid_db is not None else "   n/a"
    print(f"L/R corr    : {lr_text}   (1=mono, 0=independent, -1=antiphase)")
    print(f"S/M ratio   : {smd_text}   (more negative = narrower stereo)")

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

    # librosa hands back an empty beat array (and tempo 0.0) when it finds no pulse
    # at all. Everything beat-synchronous below then degenerates rather than merely
    # shrinking: sync() on an empty index array returns ZERO columns, not the one
    # whole-track column its interior-boundary rule would suggest, so the chord and
    # structure passes get an empty feature matrix instead of a coarse one.
    has_beats = len(beats) > 0

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

    if not has_beats:
        print(
            "\nWARNING: no beats detected — the beat-synchronous passes are skipped.\n"
            "  beat_track builds its onset envelope with aggregate=np.median across mel\n"
            "  bins, so material with no transients or a sparse spectrum (pads, drones,\n"
            "  pure tones) can read as beatless even when it is audibly rhythmic.\n"
            "  Key, chroma, loudness, and spectral results below are unaffected.\n"
            "  summary.json records tempo_bpm = null rather than 0.0, so downstream\n"
            "  scripts ask for a tempo instead of analysing against a 0 BPM grid:\n"
            "    python3 analyze_v3.py --audio <file> --bpm <tempo>"
        )

    # Tempogram peak as cross-check (sometimes beat_track halves/doubles).
    band_bpms, band_ac, top_bpms = tempogram_peaks(y, sr, hop)
    print(f"top tempogram BPMs: {[round(float(b), 2) for b in top_bpms]}")

    half_time = suspect_half_time(tempo, top_bpms, band_bpms, band_ac)
    if half_time.suspected:
        print(
            f"\nWARNING: beat_track ({tempo:.1f} BPM) ≈ 2× tempogram peak "
            f"({half_time.half_bpm:.1f} BPM), and that peak is the stronger of the two "
            f"({half_time.half_strength:.3f} vs {half_time.tempo_strength:.3f}).\n"
            f"  Song may have a half-time feel; {half_time.half_bpm:.2f} BPM may be the "
            f"true pulse.\n"
            f"  If so: python3 analyze_v3.py --audio <file> --bpm {half_time.half_bpm:.2f}"
        )

    # ------------------------- 3. Key / mode -------------------------------
    banner("KEY / MODE")

    # Chromagram — CQT-based, more robust for harmonic content than STFT chroma.
    chroma_cqt = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, bins_per_octave=36)
    chroma_mean = chroma_cqt.mean(axis=1)
    print("mean chroma:")
    for p, v in sorted(zip(PITCHES, chroma_mean), key=lambda x: -x[1]):
        bar = "█" * int(v * 50)
        print(f"  {p:>2}  {v:.3f}  {bar}")

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

    templates = chord_templates()
    tpl_names = [n for n, _ in templates]
    tpl_mat = np.stack([t for _, t in templates])  # (N_templates, 12)

    segments: list[tuple[str, float, float]] = []
    top_chords: list[tuple[str, float]] = []

    if not has_beats:
        print("skipped — chord detection pools chroma over the beat grid, which is empty.")
    else:
        # Beat-synchronous chroma (median pooled), gives stable per-beat estimates.
        chroma_sync = librosa.util.sync(chroma_cqt, beat_frames_feat, aggregate=np.median)
        chroma_sync_n = chroma_sync / (np.linalg.norm(chroma_sync, axis=0, keepdims=True) + 1e-9)
        scores = tpl_mat @ chroma_sync_n  # (N_templates, N_beats)
        best_idx = scores.argmax(axis=0)
        beat_chords = [tpl_names[i] for i in best_idx]

        # Collapse repeats into chord segments (merge consecutive identical chords).
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

    if not has_beats:
        print("skipped — segmentation pools MFCCs over the beat grid, which is empty.")
        boundary_times = [0.0, float(duration)]
    else:
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop)
        mfcc_sync = librosa.util.sync(mfcc, beat_frames_feat, aggregate=np.mean)
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
        # null when the file has no measurable stereo width — see the L/R block above.
        "lr_correlation": lr_corr,
        "side_to_mid_db": side_to_mid_db,
        # null, not 0.0, when the tracker found no pulse — analyze_v3.pick_tempo
        # treats a missing tempo as "pass --bpm", which is the right prompt. A 0.0
        # would be accepted as a real tempo and silently poison everything downstream.
        "tempo_bpm": tempo if has_beats else None,
        "beats_detected": int(len(beats)),
        "tempogram_top_bpms": [float(b) for b in top_bpms],
        "half_time_suspected": half_time.suspected,
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


if __name__ == "__main__":
    main()
