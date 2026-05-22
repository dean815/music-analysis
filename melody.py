"""Extract dominant melody pitch (pyin) and analyze modal character per section.

Reads tempo, section boundaries, and detected key/mode from the
summary.json that analyze.py writes. Override with CLI flags if you
disagree with auto-detection.

For modes with a defined sibling test (Lydian, Mixolydian, Dorian,
Phrygian, Locrian), the script runs a "modal character test" per
section: it counts how often the melody hits the mode's signature
scale degree vs. the sibling-mode note, and prints a verdict.

For reference modes (major / minor), only the pitch-class histogram
is reported — no modal test is meaningful.
"""
from __future__ import annotations

import argparse

import librosa
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

import modes
import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, audio=True)
_parser.add_argument(
    "--key", default=None,
    help="Override detected tonic (e.g. 'D'). Default: read from summary.json.",
)
_parser.add_argument(
    "--mode", default=None,
    help="Override detected mode (e.g. 'lydian'). Default: read from summary.json.",
)
_parser.add_argument(
    "--sections", default=None,
    help=(
        "Override section boundaries as semicolon-separated 'start,end' pairs "
        "in seconds, e.g. '0,8;8,24;24,30'. Default: read from summary.json."
    ),
)
_args = _parser.parse_args()

AUDIO = paths.require(_args.audio, "MUSIC_AUDIO")
OUT = paths.ensure_dir(_args.out)


# ---------------- Load context from analyze.py's output ----------------
summary = paths.load_summary(OUT)


def parse_sections_arg(raw: str | None, total_duration: float, summary: dict) -> list[tuple[str, float, float]]:
    """Resolve section boundaries from CLI override or summary.json.

    Returns a list of (label, start_sec, end_sec). Labels are generic
    ("Section 1", "Section 2", …) — this script intentionally doesn't
    invent harmonic names for sections it can't verify.
    """
    if raw:
        pairs = []
        for chunk in raw.split(";"):
            a, b = chunk.split(",")
            pairs.append((float(a), float(b)))
    else:
        bounds = summary.get("section_boundaries_sec") or [0.0, total_duration]
        pairs = list(zip(bounds[:-1], bounds[1:]))
    return [(f"Section {i+1}", t0, t1) for i, (t0, t1) in enumerate(pairs)]


def pick_mode(cli_key: str | None, cli_mode: str | None, summary: dict) -> tuple[str, str]:
    """Resolve which key+mode to analyze against.

    CLI flags win; otherwise take the top-scoring candidate from analyze.py.
    """
    if cli_key and cli_mode:
        return cli_key, cli_mode.lower()
    cands = summary.get("key_candidates") or []
    if not cands:
        raise SystemExit("error: no key_candidates in summary.json; pass --key/--mode")
    top = cands[0]
    return cli_key or top["root"], (cli_mode or top["mode"]).lower()


# ---------------- Audio + melody extraction ----------------
y_stereo, sr = sf.read(str(AUDIO), always_2d=True)
y = y_stereo.mean(axis=1).astype(np.float32)
duration = len(y) / sr
hop = 512  # finer resolution for melody than for harmony

sections = parse_sections_arg(_args.sections, duration, summary)
tonic, mode_name = pick_mode(_args.key, _args.mode, summary)
mode_pcs = modes.diatonic_pcs(tonic, mode_name)
print(f"analyzing melody against {tonic} {mode_name}")
print(f"diatonic pitch classes: {[modes.PITCHES[p] for p in mode_pcs]}")
print(f"sections ({len(sections)}):")
for name, t0, t1 in sections:
    print(f"  {name}  {t0:6.2f} → {t1:6.2f}s  ({t1-t0:5.2f}s)")

print("\nRunning pyin (this may take 30-60s)...")
f0, _voiced_flag, _voiced_prob = librosa.pyin(
    y,
    fmin=float(librosa.note_to_hz("E3")),
    fmax=float(librosa.note_to_hz("C7")),
    sr=sr,
    frame_length=4096,
    hop_length=hop,
)
times = librosa.times_like(f0, sr=sr, hop_length=hop)
midi = librosa.hz_to_midi(f0)
pc = np.where(np.isnan(midi), -1, np.round(midi).astype(int) % 12)
voiced_pct = 100 * np.mean(~np.isnan(f0))
print(f"frames: {len(f0)}, voiced: {voiced_pct:.1f}%")


# ---------------- Per-section pitch-class histogram ----------------
print("\n" + "=" * 64)
print("MELODY PITCH-CLASS DISTRIBUTION PER SECTION (lead/melody only)")
print("=" * 64)
for name, t0, t1 in sections:
    f_idx = (times >= t0) & (times < t1)
    pcs = pc[f_idx]
    pcs = pcs[pcs >= 0]
    if len(pcs) == 0:
        print(f"\n{name}  ({t0:.2f}-{t1:.2f}s)  [no voiced frames]")
        continue
    counts = np.bincount(pcs, minlength=12)
    total = int(counts.sum())
    print(f"\n{name}  ({t0:.2f}-{t1:.2f}s)  voiced frames: {total}")
    in_mode_total = sum(int(counts[p]) for p in mode_pcs)
    in_mode_pct = 100 * in_mode_total / total
    print(f"  in-mode total: {in_mode_total}  ({in_mode_pct:.1f}%)")
    order = np.argsort(-counts)
    for p_idx in order[:12]:
        if counts[p_idx] == 0:
            continue
        pct = 100 * counts[p_idx] / total
        bar = "█" * int(pct * 0.5)
        flag = "  (in mode)" if p_idx in mode_pcs else "  (out)"
        print(f"  {modes.PITCHES[p_idx]:>2}  {counts[p_idx]:5d}  {pct:5.1f}%  {bar}{flag}")


# ---------------- Modal character test (if applicable) ----------------
test_result = modes.modal_character_test(tonic, mode_name)
if test_result is None:
    print("\n" + "=" * 64)
    print(f"NO MODAL CHARACTER TEST for {tonic} {mode_name}")
    print("=" * 64)
    print(
        f"  {mode_name} is a reference mode (major or minor); there's no\n"
        f"  sibling mode to test against. Skipping modal character test."
    )
else:
    sig_pc, sib_pc, test = test_result
    print("\n" + "=" * 64)
    print(f"MODAL CHARACTER TEST: {tonic} {mode_name} vs {tonic} {test.sibling_mode}")
    print(f"  signature note: {modes.PITCHES[sig_pc]} ({test.signature_degree})")
    print(f"  sibling note  : {modes.PITCHES[sib_pc]} ({test.sibling_degree})")
    print("=" * 64)
    for name, t0, t1 in sections:
        f_idx = (times >= t0) & (times < t1)
        pcs = pc[f_idx]
        pcs = pcs[pcs >= 0]
        if len(pcs) == 0:
            continue
        sig_count = int(np.sum(pcs == sig_pc))
        sib_count = int(np.sum(pcs == sib_pc))
        ratio = sig_count / max(sib_count, 1)
        verdict = modes.interpret_modal_test(sig_count, sib_count)
        print(
            f"\n{name}  ({t0:.2f}-{t1:.2f}s):\n"
            f"  {modes.PITCHES[sig_pc]} (signature, {test.signature_degree}): {sig_count:5d}\n"
            f"  {modes.PITCHES[sib_pc]} (sibling,   {test.sibling_degree}): {sib_count:5d}\n"
            f"  ratio sig/sibling: {ratio:.2f}\n"
            f"  verdict: {verdict}"
        )


# ---------------- Plot ----------------
fig, ax = plt.subplots(figsize=(15, 6))
ax.scatter(times[~np.isnan(midi)], midi[~np.isnan(midi)], s=2, c="#3a6ea5", alpha=0.6)

# Reference grid: diatonic pitch classes of the detected mode, octaves 4-6.
for octave in (4, 5, 6):
    for pc_ in mode_pcs:
        midi_n = pc_ + 12 * (octave + 1)
        ax.axhline(midi_n, color="lightgreen", lw=0.4, alpha=0.5)

# If there's a modal character test, also draw the sibling note for contrast.
if test_result is not None:
    _, sib_pc, _ = test_result
    for octave in (4, 5, 6):
        midi_sib = sib_pc + 12 * (octave + 1)
        ax.axhline(midi_sib, color="salmon", lw=0.5, alpha=0.7, ls=":")

for name, t0, _t1 in sections:
    ax.axvline(t0, color="black", lw=0.5, alpha=0.4)
    ax.text(t0 + 0.3, 84, name, fontsize=8, color="black", alpha=0.7)

ax.set_xlim(0, duration)
ax.set_ylim(50, 90)
ax.set_xlabel("time (s)")
ax.set_ylabel("MIDI pitch")
title_legend = f"Green lines = {tonic} {mode_name} scale degrees"
if test_result is not None:
    _, sib_pc, test = test_result
    title_legend += (
        f", red dotted = {modes.PITCHES[sib_pc]} natural "
        f"({test.sibling_mode} {test.sibling_degree}, NOT in {mode_name})"
    )
ax.set_title(f"Monophonic melody contour (pyin)\n{title_legend}")
ax.grid(True, lw=0.3, alpha=0.3)
plt.tight_layout()
fig.savefig(OUT / "melody.png", dpi=120)
plt.close(fig)
print(f"\nsaved {OUT / 'melody.png'}")
print("DONE")
