"""Generate a public-domain demo bounce, so the pipeline runs without private audio.

Every audio script here needs a `--audio` bounce, which normally means your own
unreleased mix. That makes the repo awkward to try out. This renders a synthetic
stand-in instead, using only public-domain source material:

    Pachelbel, Canon in D (c. 1680) — ground bass
        D  A  Bm  F#m  G  D  G  A

The progression is Pachelbel's; the voicings and the pad timbre are this repo's
own (reused from generate_previews.py), so nothing here is a transcription of
any copyrighted edition or recording.

Written at 135 BPM in 4/4 — the same grid generate_previews.py renders against,
so the output also works as the `--audio` side of splice_transitions.py.

    $ python3 demo_bounce.py
    $ python3 analyze.py           --audio out/demo_bounce.wav
    $ python3 splice_transitions.py --audio out/demo_bounce.wav

Deliberately stereo, because the analysis scripts sum stereo to mono and that
path should be exercised by the demo rather than only by real bounces.
"""
from __future__ import annotations
import argparse

import numpy as np
import soundfile as sf

import paths
from generate_previews import (BAR_S, BPM, CHORDS, SR, midi_to_hz,
                               pitch_to_midi, render_progression)

# Pachelbel's ground bass, one bar per chord, voiced from the shared vocabulary
# in generate_previews.CHORDS.
GROUND_BASS = ["Dadd9", "Aadd9", "Bm7", "F_m7", "Gmaj7", "Dadd9", "Gmaj7", "Aadd9"]

HAAS_S = 0.012      # inter-channel delay for a simple stereo spread
ARP_PER_BAR = 8     # eighth notes at 4/4


def build_progression(cycles: int) -> list[tuple[str, float]]:
    """Repeat the 8-bar ground bass, one bar per chord."""
    return [(name, 1) for _ in range(cycles) for name in GROUND_BASS]


def synth_pluck(midi_pitch: float, duration_s: float, rng: np.random.Generator,
                amplitude: float = 0.12) -> np.ndarray:
    """A short plucked tone — fast attack, exponential decay, broadband onset.

    Two things here exist to keep the demo analyzable, and both are easy to lose:

    1. The pad in generate_previews has a 250ms attack, far too soft for an onset
       envelope. Pad-only audio yields *zero* beats and the analysis scripts then
       fail on an empty beat grid. This voice supplies the transients.

    2. The noise burst is not decoration. librosa's beat_track computes its onset
       envelope with aggregate=np.median across mel bins. Pure summed sinusoids
       occupy only a handful of bins, so the median bin is empty and the envelope
       is identically zero — beats again. A broadband attack (which real plucked
       strings have) puts energy in every bin so the median responds.
    """
    n = int(SR * duration_s)
    t = np.arange(n) / SR
    freq = midi_to_hz(midi_pitch)
    wave = (np.sin(2 * np.pi * freq * t) * 0.60
            + np.sin(2 * np.pi * 2 * freq * t) * 0.25
            + np.sin(2 * np.pi * 3 * freq * t) * 0.12)
    # Broadband pick attack, decaying much faster than the tone itself.
    wave = wave + rng.standard_normal(n) * np.exp(-t * 120.0) * 0.55
    env = np.exp(-t * 9.0)
    atk = max(1, int(0.002 * SR))  # 2ms ramp so the transient isn't a click
    env[:atk] *= np.linspace(0, 1, atk)
    return wave * env * amplitude


def render_arpeggio(progression: list[tuple[str, float]],
                    rng: np.random.Generator) -> np.ndarray:
    """Arpeggiate each chord in eighth notes, an octave above the pad.

    Canon in D is conventionally played over a running quaver figure, so this is
    faithful to the source as well as being what makes beat tracking work.
    """
    total_len = int(round(sum(b for _, b in progression) * BAR_S * SR))
    out = np.zeros(total_len)
    step_s = BAR_S / ARP_PER_BAR
    elapsed_bars = 0.0
    for name, bars in progression:
        pitches = [pitch_to_midi(n, o) + 12 for n, o in CHORDS[name]]
        for k in range(int(round(bars * ARP_PER_BAR))):
            start = int(round((elapsed_bars + k / ARP_PER_BAR) * BAR_S * SR))
            # Metrical accent. Without it every eighth is identical, there is no
            # audible pulse, and beat_track drifts to librosa's 120 BPM prior
            # instead of finding the real tempo.
            if k % ARP_PER_BAR == 0:
                accent = 1.60      # downbeat
            elif k % 2 == 0:
                accent = 1.15      # on the quarter-note beat
            else:
                accent = 0.65      # off-beat eighth
            # Ring slightly past the step so notes overlap rather than gate off.
            note = synth_pluck(pitches[k % len(pitches)], step_s * 1.8, rng,
                               amplitude=0.12 * accent)
            seg = out[start:start + len(note)]
            seg += note[:len(seg)]
        elapsed_bars += bars
    return out


def to_stereo(mono: np.ndarray, sr: int = SR) -> np.ndarray:
    """Widen mono to stereo with a short Haas delay on the right channel."""
    delay = int(HAAS_S * sr)
    right = np.concatenate([np.zeros(delay), mono[:-delay]])
    return np.stack([mono, right], axis=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    paths.add_args(parser)
    parser.add_argument("--cycles", type=int, default=4,
                        help="repetitions of the 8-bar ground bass (default: 4 = 32 bars)")
    parser.add_argument("--name", default="demo_bounce.wav",
                        help="output filename (default: demo_bounce.wav)")
    args = parser.parse_args()

    if args.cycles < 1:
        parser.error("--cycles must be at least 1")

    out_dir = paths.ensure_dir(args.out)
    progression = build_progression(args.cycles)

    # Gentle swell across the whole take, so level-matching downstream has
    # something to work with rather than a flat pad.
    amp_curve = list(np.linspace(0.65, 1.0, len(progression)))

    pad = render_progression(progression, amp_curve)
    # Seeded so the fixture is byte-reproducible across runs.
    arp = render_arpeggio(progression, np.random.default_rng(0))
    mono = pad * 0.70 + arp * 0.85
    peak = np.max(np.abs(mono), initial=0.0)
    if peak > 0.85:
        mono *= 0.85 / peak
    audio = to_stereo(mono)

    out_path = out_dir / args.name
    sf.write(str(out_path), audio, SR, subtype="PCM_24")

    bars = len(progression)
    print(f"wrote {out_path}")
    print(f"  Pachelbel, Canon in D ground bass — public domain")
    print(f"  {args.cycles} x 8 bars = {bars} bars @ {BPM:g} BPM = {bars * BAR_S:.2f}s")
    print(f"  {audio.shape[0]} frames x {audio.shape[1]} ch @ {SR} Hz, peak {np.max(np.abs(audio)):.3f}")
    print()
    print("  try it with:")
    print(f"    python3 analyze.py            --audio {out_path}")
    print(f"    python3 splice_transitions.py --audio {out_path}")


if __name__ == "__main__":
    main()
