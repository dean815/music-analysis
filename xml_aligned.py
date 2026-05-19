"""Aligned chord chart: maps every measure to project time AND bounce time.

Bounce now starts at bar 17 of the project = 28.44s at 135 BPM.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from collections import defaultdict
from music21 import converter, harmony, key as m21key, roman, note, chord as m21chord

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, xml=True, needs_out=False)
_args = _parser.parse_args()
XML = paths.require(_args.xml, "MUSIC_XML")
BPM = 135.0
BOUNCE_START_BAR = 17
BOUNCE_OFFSET_SEC = (BOUNCE_START_BAR - 1) * 4 * (60 / BPM)  # = 28.44s


def proj_time(measure_num: int, beat: float = 1.0) -> float:
    return ((measure_num - 1) * 4 + (beat - 1)) * (60 / BPM)


def bounce_time(measure_num: int, beat: float = 1.0) -> float:
    return proj_time(measure_num, beat) - BOUNCE_OFFSET_SEC


def banner(t):
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


score = converter.parse(str(XML))
print(f"Score: 88 bars / 156.44s. Bounce: starts m{BOUNCE_START_BAR} / {BOUNCE_OFFSET_SEC:.2f}s offset.")

D_KEY = m21key.Key("D", "major")  # reference for Roman numerals (Lydian-aware manually)
CS_KEY = m21key.Key("C#", "minor")  # for C# Dorian section

chordified = score.chordify()
chord_events = list(chordified.recurse().getElementsByClass("Chord"))

# Group by measure and pick longest-duration chord per measure.
by_measure = defaultdict(list)
for c in chord_events:
    by_measure[c.measureNumber].append(c)


def dominant(chs):
    return max(chs, key=lambda c: c.quarterLength) if chs else None


banner("FULL ALIGNED CHORD CHART (per-measure dominant chord)")
print(f"{'meas':>4}  {'proj':>7}  {'bounce':>7}  {'chord-symbol':<14}  {'pitches':<22}  {'RN/D':<10}  {'RN/C#m':<10}")
print("-" * 86)
for m_num in sorted(by_measure.keys()):
    c = dominant(by_measure[m_num])
    if c is None or not c.pitches:
        continue
    p_t = proj_time(m_num)
    b_t = bounce_time(m_num)
    b_t_str = f"{b_t:+.2f}" if b_t < 0 else f"{b_t:.2f}"
    pitches = " ".join(p.name for p in c.pitches[:6])
    try:
        cs = harmony.chordSymbolFigureFromChord(c)
    except Exception:
        cs = "?"
    try:
        rn_d = roman.romanNumeralFromChord(c, D_KEY).figure
    except Exception:
        rn_d = "?"
    try:
        rn_cs = roman.romanNumeralFromChord(c, CS_KEY).figure
    except Exception:
        rn_cs = "?"
    print(f"{m_num:>4}  {p_t:>7.2f}  {b_t_str:>7}  {cs:<14}  {pitches:<22}  {rn_d:<10}  {rn_cs:<10}")

banner("NEW CONTENT — measures 17 through 31 (not in previous bounce)")
for m_num in range(17, 32):
    if m_num not in by_measure:
        continue
    chs = by_measure[m_num]
    print(f"  m{m_num:>2}  (project {proj_time(m_num):.2f}s = bounce {bounce_time(m_num):+.2f}s):")
    for c in chs[:8]:  # first 8 events in the measure
        try:
            cs = harmony.chordSymbolFigureFromChord(c)
        except Exception:
            cs = "?"
        pitches = " ".join(p.nameWithOctave for p in c.pitches)
        print(f"    beat {c.beat:>4.2f}  dur {c.quarterLength:.2f}  {pitches:<28}  {cs}")

banner("G-NATURAL OCCURRENCES — confirming the borrowed-chord moments")
g_nat_events = []
for n in score.recurse().notes:
    pcs = [n.pitch] if isinstance(n, note.Note) else (n.pitches if isinstance(n, m21chord.Chord) else [])
    for p in pcs:
        if p.step == "G" and p.alter == 0:
            g_nat_events.append((n.measureNumber, p.nameWithOctave, n.offset))

print(f"Total G-natural events: {len(g_nat_events)}")
seen_measures = set()
for m_num, name, off in g_nat_events:
    if m_num not in seen_measures:
        seen_measures.add(m_num)
        print(f"  m{m_num:>3}  project {proj_time(m_num):6.2f}s  bounce {bounce_time(m_num):+6.2f}s  {name}")

banner("A vs A# OCCURRENCES — Dorian commitment")
a_nat = []
a_sharp = []
for n in score.recurse().notes:
    pcs = [n.pitch] if isinstance(n, note.Note) else (n.pitches if isinstance(n, m21chord.Chord) else [])
    for p in pcs:
        if p.step == "A":
            if p.alter == 0:
                a_nat.append(n.measureNumber)
            elif p.alter == 1:
                a_sharp.append(n.measureNumber)
print(f"A natural: {len(a_nat)} events in measures {sorted(set(a_nat))}")
print(f"A#:        {len(a_sharp)} events in measures {sorted(set(a_sharp))}")
print(f"  → A# measures in bounce time: ", end="")
for m in sorted(set(a_sharp)):
    print(f"{bounce_time(m):.1f}s ", end="")
print()
