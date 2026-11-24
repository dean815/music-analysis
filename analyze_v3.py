"""Fine-grained chord track with Viterbi smoothing and per-section modal analysis.

Reads tempo, section boundaries, and detected key/mode from the
summary.json that analyze.py writes (so run analyze.py first). Override
with CLI flags if you disagree with auto-detection.

Per-section work:
  * Half-bar chord histogram (every 2 beats)
  * Modal character test: if the detected mode has a sibling test
    defined in modes.py, count signature vs. sibling pitches.
  * Out-of-key chord roots flagged against the detected mode's
    diatonic set.

The third plot panel adapts to the detected mode: signature-vs-sibling
strength over time when a modal test applies; tonic-vs-dominant chord-
root strength otherwise.
"""
from __future__ import annotations

import argparse
from collections import Counter

import librosa
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

import modes
import paths
from analysis_common import banner, bass_chroma, chord_templates, viterbi_sticky

# Chords are estimated every PERIOD_BEATS beats (a half bar in 4/4).
PERIOD_BEATS = 2
# Viterbi bonus for staying on the same chord; small, so the track stays responsive.
SELF_BONUS = 0.06


def pick_tempo(cli_bpm: float | None, summary: dict) -> float:
    if cli_bpm is not None:
        return float(cli_bpm)
    bpm = summary.get("tempo_bpm")
    if bpm is None:
        raise SystemExit("error: no tempo_bpm in summary.json; pass --bpm")
    return float(bpm)


def pick_mode(cli_key: str | None, cli_mode: str | None, summary: dict) -> tuple[str, str]:
    if cli_key and cli_mode:
        return cli_key, cli_mode.lower()
    cands = summary.get("key_candidates") or []
    if not cands:
        raise SystemExit("error: no key_candidates in summary.json; pass --key/--mode")
    top = cands[0]
    return cli_key or top["root"], (cli_mode or top["mode"]).lower()


def parse_sections_arg(raw: str | None, total_duration: float, summary: dict) -> list[tuple[str, float, float]]:
    if raw:
        pairs = []
        for chunk in raw.split(";"):
            a, b = chunk.split(",")
            pairs.append((float(a), float(b)))
    else:
        bounds = summary.get("section_boundaries_sec") or [0.0, total_duration]
        pairs = list(zip(bounds[:-1], bounds[1:]))
    return [(f"Section {i+1}", t0, t1) for i, (t0, t1) in enumerate(pairs)]


def score_phase(phase_offset, oenv, duration, beat_period_sec, sr, hop):
    """Higher = onset peaks land closer to beat ticks."""
    ticks = np.arange(phase_offset, duration, beat_period_sec)
    score = 0.0
    for t in ticks:
        idx = int(round(t * sr / hop))
        if 0 <= idx < len(oenv):
            window = oenv[max(0, idx - 2): idx + 3]
            score += float(window.max()) if len(window) else 0.0
    return score


def pool(matrix, beat_frames_, group_size):
    cols = []
    for i in range(0, len(beat_frames_) - group_size + 1, group_size):
        f0 = beat_frames_[i]
        f1 = beat_frames_[i + group_size] if i + group_size < len(beat_frames_) else matrix.shape[1]
        f0 = max(0, min(f0, matrix.shape[1] - 1))
        f1 = max(f0 + 1, min(f1, matrix.shape[1]))
        cols.append(np.median(matrix[:, f0:f1], axis=1))
    return np.stack(cols, axis=1)


def label_for(t: float, sections) -> str:
    for name, t0, t1 in sections:
        if t0 <= t < t1:
            return name
    return "(outside)"


def chord_root(chord_label: str) -> str:
    if len(chord_label) >= 2 and chord_label[1] == "#":
        return chord_label[:2]
    return chord_label[:1]


def smooth(x, w):
    if w < 2: return x
    pad = w // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones(w) / w
    return np.convolve(xp, kernel, mode="valid")[: len(x)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    paths.add_args(parser, audio=True)
    parser.add_argument(
        "--bpm", type=float, default=None,
        help="Override detected tempo. Default: read tempo_bpm from summary.json.",
    )
    parser.add_argument(
        "--key", default=None,
        help="Override detected tonic (e.g. 'D'). Default: read from summary.json.",
    )
    parser.add_argument(
        "--mode", default=None,
        help="Override detected mode (e.g. 'lydian'). Default: read from summary.json.",
    )
    parser.add_argument(
        "--sections", default=None,
        help=(
            "Override section boundaries as semicolon-separated 'start,end' pairs "
            "in seconds, e.g. '0,8;8,24;24,30'. Default: read from summary.json."
        ),
    )
    args = parser.parse_args()
    AUDIO = paths.require(args.audio, "MUSIC_AUDIO")
    OUT = paths.ensure_dir(args.out)

    # ---------------- Context from analyze.py + CLI overrides ----------------
    summary = paths.load_summary(OUT)

    # ---------------- Load ----------------
    y_stereo, sr = sf.read(str(AUDIO), always_2d=True)
    y = y_stereo.mean(axis=1).astype(np.float32)
    duration = len(y) / sr
    hop = 1024
    print(f"loaded {duration:.2f}s @ {sr} Hz")

    tempo_bpm = pick_tempo(args.bpm, summary)
    tonic, mode_name = pick_mode(args.key, args.mode, summary)
    sections = parse_sections_arg(args.sections, duration, summary)
    mode_pcs = modes.diatonic_pcs(tonic, mode_name)
    diatonic_roots = {modes.PITCHES[p] for p in mode_pcs}
    print(f"tempo: {tempo_bpm:.2f} BPM   key: {tonic} {mode_name}")
    print(f"diatonic pitches: {[modes.PITCHES[p] for p in mode_pcs]}")
    print(f"sections: {len(sections)}")
    for name, t0, t1 in sections:
        print(f"  {name}  {t0:6.2f} → {t1:6.2f}s")

    # ---------------- Phase-aligned beat grid at the chosen tempo ----------------
    beat_period_sec = 60.0 / tempo_bpm
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)

    phases = np.linspace(0, beat_period_sec, 32, endpoint=False)
    phase_scores = [score_phase(p, oenv, duration, beat_period_sec, sr, hop) for p in phases]
    best_phase = phases[int(np.argmax(phase_scores))]
    beat_times = np.arange(best_phase, duration, beat_period_sec)
    beat_frames = (beat_times * sr / hop).astype(int)
    print(f"phase-aligned beat 1 at t={best_phase:.3f}s   total beats: {len(beat_times)}")

    # ---------------- Chroma ----------------
    chroma_full = librosa.feature.chroma_cqt(
        y=y, sr=sr, hop_length=hop, bins_per_octave=36, n_octaves=7
    )
    chroma_smooth = median_filter(chroma_full, size=(1, 7))

    C_low_chroma = bass_chroma(y, sr, hop)

    # ---------------- Half-bar (every 2 beats) chord pooling ----------------
    bar_starts_idx = np.arange(0, len(beat_times) - PERIOD_BEATS + 1, PERIOD_BEATS)
    half_bar_times = beat_times[bar_starts_idx]

    chroma_hb = pool(chroma_smooth, beat_frames, PERIOD_BEATS)
    chroma_hb_bass = pool(C_low_chroma, beat_frames, PERIOD_BEATS)

    # ---------------- Chord templates + Viterbi ----------------
    tpls = chord_templates(weighted=True)
    tpl_names = [n for n, _ in tpls]
    tpl_mat = np.stack([t for _, t in tpls])

    combined = 0.7 * chroma_hb + 0.3 * chroma_hb_bass
    combined_n = combined / (np.linalg.norm(combined, axis=0, keepdims=True) + 1e-9)
    emit = tpl_mat @ combined_n  # (n_chords, n_periods)

    n_periods = emit.shape[1]
    path = viterbi_sticky(emit, SELF_BONUS)
    period_chords = [tpl_names[i] for i in path]

    top3_idx = np.argsort(-emit, axis=0)[:3, :]
    top3 = [[tpl_names[top3_idx[r, t]] for r in range(3)] for t in range(n_periods)]
    top3_scores = [[float(emit[top3_idx[r, t], t]) for r in range(3)] for t in range(n_periods)]

    # ---------------- Print fine-grained progression with section labels ----
    banner(f"FINE-GRAINED CHORD MAP (every {PERIOD_BEATS} beats ≈ {PERIOD_BEATS * beat_period_sec:.2f}s)")
    max_label_width = max((len(s[0]) for s in sections), default=10)
    for i, (chord, t_start) in enumerate(zip(period_chords, half_bar_times)):
        alts = top3[i]
        s = top3_scores[i]
        label = label_for(t_start, sections).ljust(max_label_width)
        print(f"  {label}  {t_start:6.2f}s  {chord:<8}   "
              f"(top3: {alts[0]}/{alts[1]}/{alts[2]}, scores {s[0]:.2f}/{s[1]:.2f}/{s[2]:.2f})")

    # ---------------- Chord histograms per section --------------
    banner("CHORD HISTOGRAM PER SECTION")
    section_chord_summaries = {}
    for name, t0, t1 in sections:
        chords_here = [period_chords[i] for i, t in enumerate(half_bar_times) if t0 <= t < t1]
        cnt = Counter(chords_here)
        section_chord_summaries[name] = cnt
        print(f"\n{name}  ({t0:.1f}-{t1:.1f}s):")
        for ch, n in cnt.most_common():
            bar = "█" * n
            print(f"  {ch:<10}  {n:3d}  {bar}")

    # ---------------- Modal character test per section -------------------
    test_result = modes.modal_character_test(tonic, mode_name)
    if test_result is None:
        banner(f"NO MODAL CHARACTER TEST for {tonic} {mode_name}")
        print(f"  {mode_name} is a reference mode (major or minor); skipping.")
        sig_pc = sib_pc = None
    else:
        sig_pc, sib_pc, test = test_result
        banner(
            f"MODAL CHARACTER TEST per section: "
            f"{tonic} {mode_name} ({modes.PITCHES[sig_pc]} {test.signature_degree}) "
            f"vs {tonic} {test.sibling_mode} ({modes.PITCHES[sib_pc]} {test.sibling_degree})"
        )
        for name, t0, t1 in sections:
            f0i = int(t0 * sr / hop)
            f1i = int(t1 * sr / hop)
            if f1i <= f0i:
                continue
            sect_chroma = chroma_smooth[:, f0i:f1i].mean(axis=1)
            sect_norm = sect_chroma / sect_chroma.sum()
            sig_strength = float(sect_norm[sig_pc])
            sib_strength = float(sect_norm[sib_pc])
            ratio = sig_strength / max(sib_strength, 1e-6)
            verdict = modes.interpret_modal_test(
                int(sig_strength * 1000), int(sib_strength * 1000)
            )
            print(f"\n{name}  ({t0:.1f}-{t1:.1f}s):")
            print(f"  {modes.PITCHES[sig_pc]} ({test.signature_degree}, signature): {sig_strength:.4f}")
            print(f"  {modes.PITCHES[sib_pc]} ({test.sibling_degree}, sibling)  : {sib_strength:.4f}")
            print(f"  ratio sig/sib: {ratio:.2f}   verdict: {verdict}")

    # ---------------- Identify out-of-key chord roots per section ---------------
    banner(f"OUT-OF-KEY CHORD ROOTS (diatonic to {tonic} {mode_name}: {sorted(diatonic_roots)})")

    for name, _t0, _t1 in sections:
        cnt = section_chord_summaries[name]
        in_key, out_of_key = [], []
        for ch, n in cnt.items():
            (in_key if chord_root(ch) in diatonic_roots else out_of_key).append((ch, n))
        print(f"\n{name}:")
        print(f"  in-key    : {in_key}")
        print(f"  OUT-OF-KEY: {out_of_key}")

    # ---------------- Plot --------------------
    banner("PLOT")
    fig, axs = plt.subplots(3, 1, figsize=(16, 9))

    # Build a deterministic color cycle for sections.
    palette = ["#3a8c3a", "#aa6622", "#3a3a8c", "#8c3a8c", "#7a7a3a", "#2a8c8c", "#8c3a3a", "#4a4a4a"]
    band_colors = {name: palette[i % len(palette)] for i, (name, _, _) in enumerate(sections)}

    # 1. Chromagram with section bands.
    img = librosa.display.specshow(chroma_smooth, x_axis="time", y_axis="chroma",
                                    sr=sr, hop_length=hop, ax=axs[0], cmap="magma")
    for name, t0_, t1_ in sections:
        axs[0].axvspan(t0_, t1_, alpha=0.15, color=band_colors[name])
        axs[0].text(t0_ + 0.5, 11.5, name, fontsize=8, color="white",
                    bbox=dict(facecolor=band_colors[name], alpha=0.7, pad=1))
    axs[0].set_title(f"Chromagram with sections | {tonic} {mode_name} | {tempo_bpm:.1f} BPM")
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
        axs[1].axvspan(t0_, t1_, alpha=0.1, color=band_colors[name])
    axs[1].set_xlim(0, duration)
    axs[1].set_title(f"Half-bar (every {PERIOD_BEATS} beats) chord track — light Viterbi smoothing")
    axs[1].set_xlabel("time (s)")

    # 3. Modal character or tonic-vs-dominant strength over time.
    window_frames = int(2.0 * sr / hop)

    t_chroma = librosa.times_like(chroma_smooth, sr=sr, hop_length=hop)

    if test_result is not None:
        sig_pc_, sib_pc_, test_ = test_result
        sig_track = smooth(chroma_smooth[sig_pc_], window_frames)
        sib_track = smooth(chroma_smooth[sib_pc_], window_frames)
        axs[2].plot(t_chroma, sig_track,
                    label=f"{modes.PITCHES[sig_pc_]} (signature, {mode_name} {test_.signature_degree})",
                    color="seagreen", lw=1.2)
        axs[2].plot(t_chroma, sib_track,
                    label=f"{modes.PITCHES[sib_pc_]} (sibling, {test_.sibling_mode} {test_.sibling_degree})",
                    color="crimson", lw=1.2)
        axs[2].set_title(f"Modal signature vs sibling strength — discriminates {mode_name} from {test_.sibling_mode}")
    else:
        # Reference mode: show tonic vs dominant root strength as the diagnostic.
        tonic_pc = modes.pitch_class_of(tonic)
        dom_pc = (tonic_pc + 7) % 12
        tonic_track = smooth(chroma_smooth[tonic_pc], window_frames)
        dom_track = smooth(chroma_smooth[dom_pc], window_frames)
        axs[2].plot(t_chroma, tonic_track,
                    label=f"{modes.PITCHES[tonic_pc]} (tonic)",
                    color="seagreen", lw=1.2)
        axs[2].plot(t_chroma, dom_track,
                    label=f"{modes.PITCHES[dom_pc]} (dominant)",
                    color="crimson", lw=1.2)
        axs[2].set_title(f"Tonic vs dominant strength over time (reference-mode diagnostic)")

    for name, t0_, t1_ in sections:
        axs[2].axvspan(t0_, t1_, alpha=0.08, color=band_colors[name])
    axs[2].set_xlim(0, duration)
    axs[2].set_xlabel("time (s)")
    axs[2].legend()
    axs[2].grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(OUT / "overview_v3.png", dpi=120)
    plt.close(fig)
    print(f"saved {OUT / 'overview_v3.png'}")

    # ---------------- Save a clean chord chart -----------------
    with open(OUT / "chord_chart_v3.txt", "w") as f:
        f.write(f"# Chord chart at {tempo_bpm:.2f} BPM, half-bar resolution\n")
        f.write(f"# Key: {tonic} {mode_name}\n")
        f.write(f"# Beat 1 phase-aligned at t={best_phase:.3f}s\n\n")
        for sect_name, t0_, t1_ in sections:
            f.write(f"\n[{sect_name}]  ({t0_:.1f}-{t1_:.1f}s)\n")
            for c, t in zip(period_chords, half_bar_times):
                if t0_ <= t < t1_:
                    f.write(f"  {t:6.2f}s  |  {c}\n")
    print(f"saved {OUT / 'chord_chart_v3.txt'}")

    print("\nDONE")


if __name__ == "__main__":
    main()
