"""Symbolic analysis of the MusicXML export — keyboard + bass only, no guitar lead.

Goal: replace the audio-based chord estimates with exact notes from the score,
then cross-check our D Lydian / turnaround / C# Dorian reading.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from music21 import converter, harmony, key, note, pitch, roman, stream, chord as m21chord

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, xml=True, needs_out=False)
_args = _parser.parse_args()
XML = paths.require(_args.xml, "MUSIC_XML")


def banner(t):
    print(f"\n{'=' * 64}\n{t}\n{'=' * 64}")


# ---------------- Load ----------------
banner("FILE METADATA")
score = converter.parse(str(XML))
print(f"title       : {score.metadata.title if score.metadata else '(none)'}")
print(f"parts       : {len(score.parts)}")
for i, p in enumerate(score.parts):
    print(f"  part {i}: {p.partName!r}")
    print(f"    measures: {len(p.getElementsByClass('Measure'))}")

# Time / key signatures.
ts_list = list(score.recurse().getElementsByClass("TimeSignature"))
ks_list = list(score.recurse().getElementsByClass("KeySignature"))
print(f"time sigs   : {[str(t) for t in ts_list[:5]]}{' ...' if len(ts_list)>5 else ''}")
print(f"key sigs    : {[str(k) for k in ks_list[:5]]}{' ...' if len(ks_list)>5 else ''}")

# Tempo markings.
tempos = list(score.recurse().getElementsByClass("MetronomeMark"))
print(f"tempo marks : {tempos}")

# Total length in quarter notes.
total_ql = score.highestTime
print(f"length      : {total_ql} quarter-notes  =  {total_ql/4:.1f} bars at 4/4")
print(f"at 135 BPM, that's {total_ql * 60 / 135:.2f} seconds of music")

# ---------------- First-note-onset per measure to find empty leading bars ----
banner("WHEN DOES SOUND ACTUALLY START?")
part0 = score.parts[0]
first_sounding_measure = None
for m in part0.getElementsByClass("Measure"):
    # 'notes' excludes rests; if anything is here, measure has content.
    if any(True for _ in m.recurse().notes):
        first_sounding_measure = m.number
        break
print(f"first measure with any note: {first_sounding_measure}")
if first_sounding_measure:
    onset_sec_at_135 = (first_sounding_measure - 1) * 4 * (60 / 135)
    print(f"that's measure {first_sounding_measure} → ~{onset_sec_at_135:.2f}s at 135 BPM")

# ---------------- Chordify: collapse both staves into one chord-per-beat stream
banner("CHORDIFY (vertical sonority per onset)")
chordified = score.chordify()
chord_events = list(chordified.recurse().getElementsByClass("Chord"))
print(f"chord events: {len(chord_events)}")

# Walk through and pretty-print each chord with: measure, beat, pitches, label.
print("\nFirst 40 chord events:")
print(f"  {'meas':>4}  {'beat':>5}  {'duration':>8}  {'pitches':<25}  {'label':<14}")
for c in chord_events[:40]:
    m = c.measureNumber
    b = c.beat
    d = c.quarterLength
    pitches = " ".join(p.nameWithOctave for p in c.pitches)
    # Try a chord-symbol label using music21's heuristic.
    try:
        cs = harmony.chordSymbolFigureFromChord(c)
    except Exception:
        cs = "?"
    print(f"  {m:>4}  {b:>5.2f}  {d:>8.2f}  {pitches:<25}  {cs:<14}")

# ---------------- Per-measure unique pitch classes -----------------
banner("PER-MEASURE PITCH-CLASS CONTENT (unique pitches, ignoring octave)")
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def pcs_in_measure(m):
    pcs = set()
    for n in m.recurse().notes:
        if isinstance(n, note.Note):
            pcs.add(n.pitch.pitchClass)
        elif isinstance(n, m21chord.Chord):
            for p in n.pitches:
                pcs.add(p.pitchClass)
    return pcs


measures = part0.getElementsByClass("Measure")
print(f"  {'meas':>4}  {'seconds':>9}  pitch classes")
for m in measures:
    pcs = pcs_in_measure(m)
    if not pcs:
        continue
    pc_names = " ".join(PITCHES[i] for i in sorted(pcs))
    sec_start = (m.number - 1) * 4 * (60 / 135)
    print(f"  {m.number:>4}  {sec_start:>9.2f}  {pc_names}")

# ---------------- Roman-numeral analysis per measure in D Lydian -----------
banner("ROMAN NUMERAL ANALYSIS (interpreted relative to D Lydian)")

# music21 doesn't directly know "Lydian" as a key — we build a Lydian-aware
# label by using D major as the reference and noting the #4.
D = key.Key("D", "major")  # 2-sharp reference; Lydian adds G#

# Group chords by measure: pick the most-prevalent harmony in each measure.
from collections import defaultdict
chords_per_measure = defaultdict(list)
for c in chord_events:
    chords_per_measure[c.measureNumber].append(c)

def dominant_chord_in_measure(measure_chord_list):
    """Pick the chord that occupies the most time in the measure."""
    by_duration = sorted(measure_chord_list,
                          key=lambda c: c.quarterLength, reverse=True)
    return by_duration[0] if by_duration else None


print(f"  {'meas':>4}  {'sec':>6}  {'pitches':<25}  {'label':<14}  {'roman':<14}")
for m_num in sorted(chords_per_measure.keys()):
    c = dominant_chord_in_measure(chords_per_measure[m_num])
    if c is None or not c.pitches:
        continue
    pcs_str = " ".join(p.name for p in c.pitches[:6])
    try:
        cs = harmony.chordSymbolFigureFromChord(c)
    except Exception:
        cs = "?"
    try:
        rn = roman.romanNumeralFromChord(c, D).figure
    except Exception:
        rn = "?"
    sec_start = (m_num - 1) * 4 * (60 / 135)
    print(f"  {m_num:>4}  {sec_start:>6.2f}  {pcs_str:<25}  {cs:<14}  {rn:<14}")

# ---------------- Tonal-center segmentation -----------------
banner("WHEN DOES THE TONAL CENTER SHIFT?")

# Heuristic: a 4-measure rolling window of chord roots; if the most-common root
# changes, we mark a section boundary. Crude but useful.
roots_per_measure = {}
for m_num, chords in chords_per_measure.items():
    c = dominant_chord_in_measure(chords)
    if c is not None and c.pitches:
        try:
            roots_per_measure[m_num] = c.root().name
        except Exception:
            pass

window = 4
sorted_measures = sorted(roots_per_measure.keys())
current_center = None
for i in range(len(sorted_measures) - window + 1):
    window_meas = sorted_measures[i : i + window]
    window_roots = [roots_per_measure[m] for m in window_meas]
    most_common = Counter(window_roots).most_common(1)[0][0]
    if most_common != current_center:
        sec = (window_meas[0] - 1) * 4 * (60 / 135)
        print(f"  measure {window_meas[0]:>3}  (~{sec:>5.2f}s)  → root center: {most_common}")
        current_center = most_common

# ---------------- D Lydian II verification (E major appearances) ---------
banner("LYDIAN II (E major) APPEARANCES")
e_major_measures = []
for m_num, chords in chords_per_measure.items():
    for c in chords:
        try:
            if c.root().name == "E" and c.quality in ("major", "dominant"):
                e_major_measures.append((m_num, c.quarterLength, c.pitches))
                break
        except Exception:
            pass

print(f"E-rooted major chords found in {len(e_major_measures)} measures:")
for m_num, ql, pitches in e_major_measures[:20]:
    sec = (m_num - 1) * 4 * (60 / 135)
    pcs_str = " ".join(p.name for p in pitches)
    print(f"  measure {m_num:>3}  (~{sec:>5.2f}s)  duration {ql:.2f}  pitches: {pcs_str}")

# ---------------- G-natural counter (the "out of D Lydian" diagnostic) ---
banner("G NATURAL vs G# OCCURRENCES (the Lydian #4 test)")
g_nat_count = 0
g_sharp_count = 0
g_nat_measures = set()
g_sharp_measures = set()
for n in score.recurse().notes:
    if isinstance(n, note.Note):
        ps = [n.pitch]
    elif isinstance(n, m21chord.Chord):
        ps = n.pitches
    else:
        continue
    for p in ps:
        if p.step == "G":
            if p.alter == 1:  # G#
                g_sharp_count += 1
                g_sharp_measures.add(n.measureNumber)
            elif p.alter == 0:  # G natural
                g_nat_count += 1
                g_nat_measures.add(n.measureNumber)

print(f"G  natural notes  : {g_nat_count}  (in {len(g_nat_measures)} measures)")
print(f"G# notes          : {g_sharp_count}  (in {len(g_sharp_measures)} measures)")
print(f"G# / G ratio      : {g_sharp_count / max(g_nat_count, 1):.2f}")
print(f"G  natural measures: {sorted(g_nat_measures)[:30]}")

# ---------------- A vs A# (Dorian vs Aeolian diagnostic in C# section) ---
banner("A natural vs A# OCCURRENCES (Dorian vs Aeolian diagnostic)")
a_nat_count = a_sharp_count = 0
a_nat_measures = set()
a_sharp_measures = set()
for n in score.recurse().notes:
    if isinstance(n, note.Note):
        ps = [n.pitch]
    elif isinstance(n, m21chord.Chord):
        ps = n.pitches
    else:
        continue
    for p in ps:
        if p.step == "A":
            if p.alter == 1:  # A#
                a_sharp_count += 1
                a_sharp_measures.add(n.measureNumber)
            elif p.alter == 0:
                a_nat_count += 1
                a_nat_measures.add(n.measureNumber)

print(f"A  natural notes  : {a_nat_count}  (in {len(a_nat_measures)} measures)")
print(f"A# notes          : {a_sharp_count}  (in {len(a_sharp_measures)} measures)")
print(f"A# measures        : {sorted(a_sharp_measures)[:30]}")
print(f"A  natural measures: {sorted(a_nat_measures)[:30]}")

print("\nDONE")
