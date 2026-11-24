"""Modal-diatonic prior for chord detection.

Given a chord label like "G#maj7" and the current mode/key (e.g., "C# Dorian"),
return a penalty in [0, 1] where 0 = fully diatonic (no penalty), 1 = fully out-of-key.

This penalty gets subtracted from each chord template's cosine-similarity score
during Viterbi decoding, biasing the chord track toward harmonically plausible chords.

Status: not implemented. `modal_penalty()` raises NotImplementedError and
nothing in the pipeline calls it yet. The open question is the penalty policy:

  STRICT    Reject any chord with any out-of-key tone (no borrowed chords).
            Cleaner output, but misses real modal mixture (e.g. a Gmaj7
            turnaround in D Lydian).

  LENIENT   Penalize only when several chord tones are out of key. Keeps real
            borrowed chords but lets through more noise.

  GRADUATED Penalty proportional to the share of non-diatonic tones, with a
            lower penalty for common borrowings (parallel major/minor). The
            most musically nuanced option and the hardest to tune.
"""
from __future__ import annotations

from modes import PITCHES

# Mode templates: scale degrees (0-11) from the tonic.
MODE_DEGREES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],   # natural minor / aeolian
    "lydian":     [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "phrygian":   [0, 1, 3, 5, 7, 8, 10],
}


def chord_pitch_classes(chord_label: str) -> set[int]:
    """Return the set of pitch classes (0-11) for a chord label like 'C#m7' or 'F#sus2'."""
    # Parse root (1 or 2 chars).
    if len(chord_label) >= 2 and chord_label[1] == "#":
        root_name, quality = chord_label[:2], chord_label[2:]
    else:
        root_name, quality = chord_label[:1], chord_label[1:]
    root = PITCHES.index(root_name)
    intervals = {
        "":     [0, 4, 7],
        "m":    [0, 3, 7],
        "sus2": [0, 2, 7],
        "sus4": [0, 5, 7],
        "maj7": [0, 4, 7, 11],
        "7":    [0, 4, 7, 10],
        "m7":   [0, 3, 7, 10],
        "add9": [0, 2, 4, 7],
    }.get(quality, [0, 4, 7])
    return {(root + i) % 12 for i in intervals}


def mode_pitch_classes(tonic: str, mode: str) -> set[int]:
    """Return the set of pitch classes for `tonic mode` (e.g., 'C#', 'dorian')."""
    tonic_pc = PITCHES.index(tonic)
    return {(tonic_pc + d) % 12 for d in MODE_DEGREES[mode]}


def modal_penalty(chord_label: str, tonic: str, mode: str) -> float:
    """Return a penalty in [0, 1] for using `chord_label` in the given key/mode.

    0.0 = chord is fully diatonic (no penalty)
    1.0 = chord is maximally out of key (full penalty)

    Not implemented yet; see the module docstring. Open design questions:

    1. How should a chord be scored by how many of its notes are out of key?
       - All-or-nothing? (any out-of-key note → penalty = 1.0)
       - Linear? (1 out-of-key note out of 4 → penalty = 0.25)
       - Square/exponential? (penalize multi-note violations more steeply)

    2. Should common borrowed chords get a discount?
       Common borrowings in modal music:
       - bVII in major (Mixolydian borrowing)
       - IV in minor (Dorian borrowing)
       - bII / Neapolitan (Phrygian flavor)
       - bVI in major (parallel minor borrowing)
       This needs a list of discounted (root, quality) borrowings and a factor
       (e.g. multiply the penalty by 0.3).

    3. Should the penalty depend on which scale degree the chord's ROOT is on?
       (A non-diatonic chord rooted on the tonic is usually a Picardy / parallel
       mode shift — different feel than a non-diatonic chord rooted on a random
       non-scale tone.)

    Any policy starts from the same set:
        out_of_key = chord_pitch_classes(chord_label) - mode_pitch_classes(tonic, mode)
    """
    raise NotImplementedError("modal_penalty: penalty policy not chosen yet")


# Expected behaviour for a few cases, for checking an implementation:
if __name__ == "__main__":
    test_cases = [
        # (chord, tonic, mode, expected penalty)
        ("Dmaj7",  "D",  "lydian",  "0 — fully in key"),
        ("Emaj7",  "D",  "lydian",  "0 — the Lydian II, fully in key"),
        ("Gmaj7",  "D",  "lydian",  "non-zero — G natural is out of D Lydian (Mixolydian borrowing)"),
        ("C#maj7", "C#", "dorian",  "non-zero — has F natural and C natural, neither in C# Dorian"),
        ("F#sus2", "C#", "dorian",  "0 — F#-G#-C# all in C# Dorian"),
        ("C#sus4", "C#", "dorian",  "0 — C#-F#-G# all in C# Dorian"),
        ("F#",     "C#", "dorian",  "0 — F# major (the Dorian IV), fully in key"),
        ("F#m",    "C#", "minor",   "0 — F#m (the Aeolian iv), fully in key"),
    ]
    for chord, tonic, mode, expected in test_cases:
        try:
            p = modal_penalty(chord, tonic, mode)
            print(f"  {chord:<8} in {tonic} {mode:<10}  penalty = {p:.3f}   ({expected})")
        except NotImplementedError as e:
            print(f"  not yet implemented: {e}")
            break
