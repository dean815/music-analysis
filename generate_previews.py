"""Render audio + MIDI previews of pre-intro harmonic ideas.

Produces 16-bar previews at 135 BPM (= 28.44s each) — exactly the duration
of project bars 1-16, so the WAV can be dropped at project 0:00 and will
end precisely when the existing keyboard part enters at m17.

Outputs:
  previews/approach1_modal_brightening.wav  + .mid
  previews/approach2_fsharp_aeolian.wav     + .mid
  previews/approach3_a_pedal.wav            + .mid
  previews/approach4_two_phrases.wav        + .mid
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import soundfile as sf
from music21 import stream, note as m21note, chord as m21chord, meter, tempo, key as m21key, duration

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, needs_out=False, needs_previews=True)
_args = _parser.parse_args()
OUT = paths.ensure_dir(_args.previews)

SR = 44100
BPM = 135.0
BAR_S = 4 * 60.0 / BPM  # = 1.778s per bar

PITCH_TO_OFFSET = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
                    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
                    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def pitch_to_midi(name: str, octave: int) -> int:
    """Convert pitch like 'F#' + octave 4 to MIDI number (60 = C4)."""
    return PITCH_TO_OFFSET[name] + (octave + 1) * 12


def midi_to_hz(midi: int | float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


# ---------- Chord vocabulary -----------
# Each chord is defined as a list of (pitch-name, octave) pairs.
# I'm hand-voicing each chord to keep the lead-tone in a reasonable register
# and to avoid muddy low-end clashes. Voicings sit roughly D3-A5 (= MIDI 50-81).
CHORDS = {
    # Dm-related (Aeolian/Dorian, no #4)
    "Dm9":         [("D", 3), ("A", 3), ("F", 4), ("C", 5), ("E", 5)],
    "Dm11":        [("D", 3), ("A", 3), ("F", 4), ("C", 5), ("G", 5)],
    "Fmaj7":       [("F", 3), ("C", 4), ("E", 4), ("A", 4)],
    "Bbmaj7":      [("Bb", 2), ("F", 3), ("A", 3), ("D", 4)],
    "G7sus4":      [("G", 2), ("D", 3), ("F", 3), ("C", 4)],
    "Am7":         [("A", 2), ("E", 3), ("G", 3), ("C", 4)],
    "Cadd9":       [("C", 3), ("G", 3), ("E", 4), ("D", 5)],
    "C_E":         [("E", 3), ("G", 3), ("C", 4)],   # C/E
    "Gmaj7":       [("G", 2), ("D", 3), ("F#", 3), ("B", 3)],
    "Gmaj9":       [("G", 2), ("D", 3), ("F#", 3), ("A", 3), ("B", 4)],

    # D Mixolydian arrival voicings (no G#, yes F#)
    "Dadd9_mix":   [("D", 3), ("A", 3), ("F#", 4), ("E", 5)],

    # D Lydian arrival voicings (yes G#, yes #11 = G# = #4 of D)
    "Dadd9":       [("D", 3), ("A", 3), ("F#", 4), ("E", 5)],
    "Dmaj7":       [("D", 3), ("A", 3), ("F#", 4), ("C#", 5)],
    "Dmaj7_sharp11": [("D", 3), ("F#", 3), ("A", 3), ("C#", 4), ("G#", 4)],
    "Aadd9":       [("A", 2), ("E", 3), ("C#", 4), ("B", 4)],
    "Aadd9_E":     [("E", 3), ("A", 3), ("C#", 4), ("B", 4)],  # Aadd9/E
    "Eadd9":       [("E", 3), ("B", 3), ("G#", 4), ("F#", 4)],
    "Esus2":       [("E", 3), ("B", 3), ("F#", 4)],
    "EaddF":       [("E", 3), ("B", 3), ("F#", 4), ("G#", 4)],
    "Asus2":       [("A", 2), ("E", 3), ("B", 3)],
    "Asus4":       [("A", 2), ("E", 3), ("D", 4)],
    "A7sus4":      [("A", 2), ("E", 3), ("D", 4), ("G", 4)],
    "A6_9":        [("A", 2), ("E", 3), ("C#", 4), ("F#", 4), ("B", 4)],
    "Amaj9":       [("A", 2), ("E", 3), ("G#", 3), ("C#", 4), ("B", 4)],
    "Bm7":         [("B", 2), ("F#", 3), ("A", 3), ("D", 4)],
    "Bm9":         [("B", 2), ("F#", 3), ("A", 3), ("C#", 4), ("D", 4)],
    "Bm7_A":       [("A", 2), ("B", 2), ("F#", 3), ("D", 4)],  # Bm7/A pedal
    "F_m7_A":      [("A", 2), ("F#", 3), ("C#", 4), ("E", 4)],  # F#m7/A pedal
    "Dmaj7_A":     [("A", 2), ("D", 3), ("F#", 3), ("C#", 4)],
    "E_A":         [("A", 2), ("E", 3), ("G#", 3), ("B", 3)],
    "F_m9_A":      [("A", 2), ("F#", 3), ("C#", 4), ("E", 4), ("G#", 4)],
    "F_m9":        [("F#", 2), ("C#", 3), ("E", 3), ("A", 3), ("G#", 4)],
    "F_m11":       [("F#", 2), ("C#", 3), ("E", 3), ("A", 3), ("B", 3), ("G#", 4)],
    "F_m7":        [("F#", 2), ("C#", 3), ("E", 3), ("A", 3)],
    "C_m7":        [("C#", 3), ("G#", 3), ("B", 3), ("E", 4)],
    "A_Cs":        [("C#", 3), ("E", 3), ("A", 3)],  # A/C#
    "G_B":         [("B", 2), ("D", 3), ("G", 3)],  # G/B
}


# ---------- Pad synthesizer ----------

def synth_voice(midi_pitch: float, duration_s: float, amplitude: float = 0.18) -> np.ndarray:
    """Synthesize a single sustained voice — choir-pad-like.

    - Fundamental + 2nd + 3rd harmonics with formant-ish weighting
    - Two slightly-detuned voices for a chorus shimmer
    - Slow attack (250ms), slow release (600ms)
    """
    n = int(SR * duration_s)
    t = np.arange(n) / SR
    freq = midi_to_hz(midi_pitch)

    # Voice A
    a = (np.sin(2 * np.pi * freq * t) * 0.55
         + np.sin(2 * np.pi * 2 * freq * t) * 0.20
         + np.sin(2 * np.pi * 3 * freq * t) * 0.08)

    # Voice B — detuned by ~5 cents (300% slower vibrato cycle for shimmer)
    b_freq = freq * (1 + 0.003 * np.sin(2 * np.pi * 4.5 * t))
    phase_b = 2 * np.pi * np.cumsum(b_freq) / SR
    b = (np.sin(phase_b) * 0.40
         + np.sin(2 * phase_b) * 0.12)

    wave = a + b

    # Envelope
    env = np.ones(n)
    atk = int(0.25 * SR)
    rel = int(0.60 * SR)
    if atk + rel > n:
        atk = max(1, int(n * 0.3))
        rel = max(1, int(n * 0.5))
    env[:atk] = np.linspace(0, 1, atk) ** 1.4
    env[-rel:] = np.linspace(1, 0, rel) ** 1.4
    return wave * env * amplitude


def synth_chord(chord_pitches: list[tuple[str, int]], duration_s: float,
                  amp_scale: float = 1.0) -> np.ndarray:
    """Sum voices for a single chord."""
    voices = [synth_voice(pitch_to_midi(n, o), duration_s, amplitude=0.18) for n, o in chord_pitches]
    max_len = max(len(v) for v in voices)
    out = np.zeros(max_len)
    for v in voices:
        out[:len(v)] += v
    return out * amp_scale


def render_progression(progression: list[tuple[str, float]],
                        amp_curve: list[float] | None = None) -> np.ndarray:
    """Render a list of (chord_name, bar_count) pairs.

    Every chord starts exactly on its bar line and the result is exactly
    sum(bar_count) bars long, so a 16-bar progression really is 28.44s and
    still lines up with project bars 1-16.

    Crossfades between chords for smoothness: each chord rings on for 120ms
    past its bar line, blending into the next chord's opening. That tail is an
    *overlap*, not a splice — it must not consume timeline, or the shortfall
    accumulates and drags every later chord off the grid.

    amp_curve: per-chord amplitude scale (for build dynamics). Defaults to 1.0 each.
    """
    if amp_curve is None:
        amp_curve = [1.0] * len(progression)
    crossfade_s = 0.12
    crossfade_samples = int(SR * crossfade_s)

    # Bar-line offsets, each measured from the start of the progression so that
    # per-chord rounding can't accumulate into drift.
    starts: list[int] = []
    elapsed_bars = 0.0
    for _, bars in progression:
        starts.append(int(round(elapsed_bars * BAR_S * SR)))
        elapsed_bars += bars
    total_len = int(round(elapsed_bars * BAR_S * SR))

    out = np.zeros(total_len)
    fade_in = np.linspace(0, 1, crossfade_samples)
    last = len(progression) - 1
    for i, ((name, _), amp) in enumerate(zip(progression, amp_curve)):
        start = starts[i]
        end = starts[i + 1] if i < last else total_len
        # Every chord but the last renders a tail that overlaps its successor.
        tail = crossfade_samples if i < last else 0
        chord = synth_chord(CHORDS[name], (end - start + tail) / SR, amp_scale=amp)
        if i > 0:
            chord[:crossfade_samples] *= fade_in       # fade in across the bar line
        if tail:
            chord[-tail:] *= fade_in[::-1]             # fade out across the tail
        seg = out[start:start + len(chord)]
        seg += chord[:len(seg)]

    # Soft-clip to prevent peaks > 1.0
    peak = np.max(np.abs(out), initial=0.0)
    if peak > 0.9:
        out *= 0.9 / peak
    return out


# ---------- MIDI writer using music21 ----------

def chord_to_pitch_strings(chord_name: str) -> list[str]:
    """Return music21 pitch strings like 'D3' from chord-name lookup."""
    return [f"{n}{o}" for n, o in CHORDS[chord_name]]


def write_midi(progression: list[tuple[str, float]], path: Path, title: str):
    s = stream.Score(id=title)
    p = stream.Part()
    p.append(tempo.MetronomeMark(number=BPM))
    p.append(meter.TimeSignature("4/4"))
    p.append(m21key.KeySignature(3))  # A major / D Lydian
    for chord_name, bars in progression:
        pitches = chord_to_pitch_strings(chord_name)
        c = m21chord.Chord(pitches)
        c.duration = duration.Duration(bars * 4)  # bars × 4 quarter notes
        p.append(c)
    s.append(p)
    s.write("midi", fp=str(path))


# ---------- The 4 approaches ----------

APPROACHES = {
    "approach1_modal_brightening": {
        "title": "Modal brightening on D",
        # 16 bars, 1 bar per chord
        "progression": [
            # D Aeolian (m1-4)
            ("Dm9", 1), ("Bbmaj7", 1), ("Fmaj7", 1), ("Dm11", 1),
            # D Dorian (m5-8) — gain B natural
            ("Dm9", 1), ("G7sus4", 1), ("Dm11", 1), ("Am7", 1),
            # D Mixolydian (m9-12) — gain F#, gain major-3rd flavor
            ("Dadd9_mix", 1), ("C_E", 1), ("Gmaj7", 1), ("Dadd9_mix", 1),
            # D Lydian (m13-16) — gain G# (#4)
            ("Dadd9", 1), ("F_m9", 1), ("Aadd9_E", 1), ("Eadd9", 1),
        ],
        # Gradual build: start at 0.6, grow to 1.0 by the Lydian phase
        "amp_curve": [0.55,0.55,0.55,0.55, 0.65,0.65,0.65,0.65,
                       0.80,0.80,0.80,0.85, 0.95,0.95,1.00,1.00],
    },
    "approach2_fsharp_aeolian": {
        "title": "F# Aeolian → D Lydian arrival",
        # 16 bars, 1 bar per chord
        "progression": [
            # F# Aeolian drone (m1-4)
            ("F_m9", 1), ("F_m9", 1), ("F_m9", 1), ("F_m9", 1),
            # Harmonic motion (m5-8)
            ("F_m11", 1), ("C_m7", 1), ("Bm9", 1), ("F_m9", 1),
            # Rising bass (m9-12)
            ("F_m9", 1), ("A_Cs", 1), ("Bm7", 1), ("Dmaj7", 1),
            # Lydian unveiling (m13-16)
            ("Dadd9", 1), ("F_m7", 1), ("Aadd9", 1), ("Eadd9", 1),
        ],
        "amp_curve": [0.50,0.50,0.50,0.50, 0.60,0.65,0.70,0.65,
                       0.75,0.80,0.85,0.95, 1.00,0.95,1.00,1.00],
    },
    "approach3_a_pedal": {
        "title": "A pedal point with harmonic decoration",
        "progression": [
            # A drone, sparse (m1-4)
            ("Asus2", 1), ("Aadd9", 1), ("Asus2", 1), ("A6_9", 1),
            # Colors above A (m5-8)
            ("Aadd9", 1), ("Bm7_A", 1), ("F_m7_A", 1), ("Dmaj7_A", 1),
            # More density (m9-12)
            ("Aadd9", 1), ("E_A", 1), ("F_m9_A", 1), ("Aadd9", 1),
            # Building tension (m13-16) — sus → release
            ("Asus4", 1), ("A7sus4", 1), ("Asus4", 1), ("Eadd9", 1),
        ],
        "amp_curve": [0.50,0.55,0.55,0.60, 0.65,0.70,0.75,0.80,
                       0.85,0.85,0.90,0.90, 0.95,1.00,0.95,1.00],
    },
    "approach4_two_phrases": {
        "title": "Two phrases — minor mood then Lydian breakthrough",
        "progression": [
            # Phrase A — F# minor mood (m1-8)
            ("F_m9", 1), ("Dadd9", 1), ("A_Cs", 1), ("Bm7", 1),
            ("F_m9", 1), ("Esus2", 1), ("Dmaj7", 1), ("Aadd9", 1),
            # Phrase B — start tilting Lydian (m9-16)
            ("Aadd9", 1), ("Dmaj7_sharp11", 1), ("F_m9", 1), ("Bm7", 1),
            ("Aadd9", 1), ("Esus2", 1), ("Dmaj7_sharp11", 1), ("Eadd9", 1),
        ],
        "amp_curve": [0.65,0.70,0.70,0.70, 0.75,0.70,0.75,0.80,
                       0.85,0.95,0.85,0.85, 0.95,0.90,1.00,1.00],
    },
}


def main():
    for slug, spec in APPROACHES.items():
        print(f"\n=== {spec['title']} ===")
        audio = render_progression(spec["progression"], spec["amp_curve"])
        wav_path = OUT / f"{slug}.wav"
        sf.write(str(wav_path), audio, SR, subtype="PCM_24")
        # MIDI too
        mid_path = OUT / f"{slug}.mid"
        write_midi(spec["progression"], mid_path, spec["title"])
        print(f"  audio: {wav_path}  ({len(audio)/SR:.2f}s)")
        print(f"  midi : {mid_path}")
        # List chord progression briefly
        for ch, b in spec["progression"]:
            print(f"    {ch:<18} ({b} bar)")


if __name__ == "__main__":
    main()
