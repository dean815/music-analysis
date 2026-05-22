"""Shared modal music-theory definitions.

Used by any analysis script that needs to:
  * Resolve a mode name into its diatonic pitch-class set.
  * Identify the "signature" scale degree(s) that distinguish a mode from
    its closest sibling, so a melody analysis can test which mode the
    line actually inhabits.

All scale-degree offsets are in semitones above the mode's tonic.

Nothing here is song-specific — the only musical knowledge encoded is
canonical mode theory.
"""
from __future__ import annotations

from dataclasses import dataclass

PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# Diatonic pitch classes of each mode, expressed as semitones above the tonic.
# "major" is the alias for ionian; "minor" is the alias for aeolian.
MODE_INTERVALS: dict[str, tuple[int, ...]] = {
    "major":      (0, 2, 4, 5, 7, 9, 11),
    "ionian":     (0, 2, 4, 5, 7, 9, 11),
    "dorian":     (0, 2, 3, 5, 7, 9, 10),
    "phrygian":   (0, 1, 3, 5, 7, 8, 10),
    "lydian":     (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "aeolian":    (0, 2, 3, 5, 7, 8, 10),
    "minor":      (0, 2, 3, 5, 7, 8, 10),
    "locrian":    (0, 1, 3, 5, 6, 8, 10),
}


@dataclass(frozen=True)
class ModalCharacterTest:
    """Describes how to test 'is this melody really in mode X?'

    For each non-reference mode (i.e. anything other than major/minor),
    one scale degree is the *signature* note — the one that defines the
    mode against its closest sibling. If the melody favors the signature
    note over the sibling note, the modal reading is confirmed.

    Example: D Lydian's signature is #4 (G#) vs. the sibling D major's
    natural 4 (G). G#-heavy → Lydian; G-heavy → fell into D major.

    `signature_semitones` and `sibling_semitones` are offsets above the
    mode's tonic in semitones.
    """
    mode: str
    signature_semitones: int
    signature_degree: str   # e.g. "#4"
    sibling_semitones: int
    sibling_degree: str     # e.g. "4"
    sibling_mode: str       # e.g. "major"


# Sibling pairings follow the conventional reading: a mode is tested
# against the closest reference mode it could collapse into.
# Lydian/Mixolydian are tested against Major (one chromatic alteration
# away). Dorian/Phrygian are tested against Aeolian. Locrian is tested
# against Phrygian (closest minor-leaning mode).
MODAL_TESTS: dict[str, ModalCharacterTest] = {
    "lydian": ModalCharacterTest(
        mode="lydian",
        signature_semitones=6, signature_degree="#4",
        sibling_semitones=5,   sibling_degree="4",
        sibling_mode="major",
    ),
    "mixolydian": ModalCharacterTest(
        mode="mixolydian",
        signature_semitones=10, signature_degree="b7",
        sibling_semitones=11,   sibling_degree="7",
        sibling_mode="major",
    ),
    "dorian": ModalCharacterTest(
        mode="dorian",
        signature_semitones=9, signature_degree="6",
        sibling_semitones=8,   sibling_degree="b6",
        sibling_mode="aeolian",
    ),
    "phrygian": ModalCharacterTest(
        mode="phrygian",
        signature_semitones=1, signature_degree="b2",
        sibling_semitones=2,   sibling_degree="2",
        sibling_mode="aeolian",
    ),
    "locrian": ModalCharacterTest(
        mode="locrian",
        signature_semitones=6, signature_degree="b5",
        sibling_semitones=7,   sibling_degree="5",
        sibling_mode="phrygian",
    ),
}


def pitch_class_of(root: str) -> int:
    """Convert a note name like 'C#' or 'Db' to a pitch class (0-11)."""
    norm = root.strip()
    if norm in PITCHES:
        return PITCHES.index(norm)
    # Handle flats by converting to sharps.
    flat_to_sharp = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    if norm in flat_to_sharp:
        return PITCHES.index(flat_to_sharp[norm])
    raise ValueError(f"unrecognized note name: {root!r}")


def diatonic_pcs(root: str, mode: str) -> list[int]:
    """Return the diatonic pitch classes of `root mode` as a sorted list of ints."""
    mode_key = mode.lower()
    if mode_key not in MODE_INTERVALS:
        raise ValueError(
            f"unknown mode {mode!r}; known: {sorted(MODE_INTERVALS)}"
        )
    tonic_pc = pitch_class_of(root)
    return sorted(((tonic_pc + i) % 12) for i in MODE_INTERVALS[mode_key])


def modal_character_test(root: str, mode: str) -> tuple[int, int, ModalCharacterTest] | None:
    """For modes with a sibling test, return (signature_pc, sibling_pc, test).

    Returns None for reference modes (major/ionian, minor/aeolian) — those
    have no sibling to test against.
    """
    mode_key = mode.lower()
    if mode_key in ("major", "ionian", "minor", "aeolian"):
        return None
    if mode_key not in MODAL_TESTS:
        return None
    tonic_pc = pitch_class_of(root)
    test = MODAL_TESTS[mode_key]
    sig_pc = (tonic_pc + test.signature_semitones) % 12
    sib_pc = (tonic_pc + test.sibling_semitones) % 12
    return sig_pc, sib_pc, test


def interpret_modal_test(signature_count: int, sibling_count: int) -> str:
    """Human-readable verdict for a modal character test result."""
    if signature_count == 0 and sibling_count == 0:
        return "INSUFFICIENT DATA — neither note appears in this section"
    if signature_count > sibling_count * 1.5:
        return "STRONG — melody clearly favors the modal signature note"
    if signature_count > sibling_count:
        return "MILD — melody uses signature more than sibling"
    if sibling_count > signature_count * 1.5:
        return "SIBLING DOMINATES — melody favors the reference-mode note instead"
    return "AMBIGUOUS — melody uses both, no clear modal commitment"
