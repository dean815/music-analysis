"""Analyze the guitars-only MusicXML — focuses on melodic content and the
   key questions: G/G# and A/A# distribution across sections."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from music21 import converter, note, chord as m21chord, harmony, roman, key as m21key

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, guitars=True, needs_out=False)
_args = _parser.parse_args()
XML = paths.require(_args.guitars_xml, "MUSIC_GUITARS_XML")
BPM = 135.0
BOUNCE_START_BAR = 17
BOUNCE_OFFSET_SEC = (BOUNCE_START_BAR - 1) * 4 * (60 / BPM)


def bar_to_bounce(m): return ((m - 1) * 4) * (60 / BPM) - BOUNCE_OFFSET_SEC
def bar_to_project(m): return ((m - 1) * 4) * (60 / BPM)


def banner(t): print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


score = converter.parse(str(XML))
print(f"parts: {len(score.parts)}")
for i, p in enumerate(score.parts):
    n_meas = len(p.getElementsByClass('Measure'))
    instr = p.partName or (p.getInstrument().instrumentName if p.getInstrument() else "(unnamed)")
    first = last = None
    for m in p.getElementsByClass('Measure'):
        if any(True for _ in m.recurse().notes):
            if first is None: first = m.number
            last = m.number
    print(f"  part {i} ({instr!r}): {n_meas} measures, sounds m{first}-{last}")

banner("PITCH-CLASS HISTOGRAM PER GUITAR PART, PER SECTION")
SECTIONS = [
    ("intro/silence", 1, 16),
    ("kbd-only D Lyd intro", 17, 32),
    ("dual-guitar bridge",   33, 48),
    ("C# vamp (lush)",       49, 72),
    ("C# ending (sparse)",   73, 88),
]
PITCH_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

def pitch_label(p):
    s = p.step
    a = int(p.alter) if p.alter else 0
    return {0:s, 1:s+"#", -1:s+"b", 2:s+"##"}.get(a, s)


def pcs_for_part(part, m_low, m_high):
    out = []
    for m in part.getElementsByClass("Measure"):
        if not (m_low <= m.number <= m_high):
            continue
        for n in m.recurse().notes:
            ps = [n.pitch] if isinstance(n, note.Note) else (
                 n.pitches if isinstance(n, m21chord.Chord) else [])
            for p in ps:
                out.append(p.pitchClass)
    return out


for p_idx, part in enumerate(score.parts):
    print(f"\n--- Guitar part {p_idx + 1} ---")
    for sect_name, m0, m1 in SECTIONS:
        pcs = pcs_for_part(part, m0, m1)
        if not pcs:
            continue
        cnt = Counter(pcs)
        total = sum(cnt.values())
        print(f"\n  {sect_name}  (m{m0}-{m1}, bounce {bar_to_bounce(m0):.1f}-{bar_to_bounce(m1+1):.1f}s):")
        ordered = sorted(cnt.items(), key=lambda kv: -kv[1])
        for pc, n in ordered:
            pct = 100*n/total
            bar = "█"*int(pct*0.6)
            flag = ""
            if pc == 7: flag = "  ← G natural (out of A maj / D Lyd)"
            if pc == 8: flag = "  ← G# (Lydian #4 of D)"
            if pc == 9: flag = "  ← A natural (Aeolian b6 of C#)"
            if pc == 10: flag = "  ← A# (Dorian 6 of C#)"
            print(f"    {PITCH_NAMES[pc]:>2}  {n:>4}  {pct:>5.1f}%  {bar}{flag}")

banner("THE TWO BIG TESTS — across both guitar parts combined")

# Combine all notes from both parts.
all_notes_by_measure = defaultdict(list)
for part in score.parts:
    for m in part.getElementsByClass("Measure"):
        for n in m.recurse().notes:
            ps = [n.pitch] if isinstance(n, note.Note) else (
                 n.pitches if isinstance(n, m21chord.Chord) else [])
            for p in ps:
                all_notes_by_measure[m.number].append((p.step, int(p.alter) if p.alter else 0))

def count(m_low, m_high, step, alter):
    total = 0
    measures = set()
    for m_num in range(m_low, m_high+1):
        for s, a in all_notes_by_measure.get(m_num, []):
            if s == step and a == alter:
                total += 1
                measures.add(m_num)
    return total, sorted(measures)


for sect_name, m0, m1 in SECTIONS:
    if m0 < 17: continue  # skip silence
    print(f"\n{sect_name}  (m{m0}-{m1}):")
    for label, (step, alter) in [
        ("G  natural", ("G", 0)),
        ("G# (Lyd #4)", ("G", 1)),
        ("A  natural", ("A", 0)),
        ("A#", ("A", 1)),
    ]:
        c, ms = count(m0, m1, step, alter)
        ms_str = ", ".join(f"m{m}" for m in ms[:10])
        if len(ms) > 10: ms_str += f", … (+{len(ms)-10} more)"
        print(f"  {label:<12}  count {c:>4}  in {len(ms)} measures   [{ms_str}]")

banner("MELODIC PROFILE OF C# SECTION (m49-72) — what's the lead actually playing?")
# Most-common pitches with octave info, to see what register the guitar is in
pitch_oct_count = Counter()
for part in score.parts:
    for m in part.getElementsByClass("Measure"):
        if not (49 <= m.number <= 72): continue
        for n in m.recurse().notes:
            ps = [n.pitch] if isinstance(n, note.Note) else (
                 n.pitches if isinstance(n, m21chord.Chord) else [])
            for p in ps:
                pitch_oct_count[p.nameWithOctave] += 1
top = pitch_oct_count.most_common(20)
print("Top 20 pitches (name+octave) in m49-72 across both guitar parts:")
for nm, c in top:
    print(f"  {nm:<6}  {c:>4}")

banner("STARTING NOTES OF EACH PHRASE — m33, m41 (cell starts of bridge)")
for p_idx, part in enumerate(score.parts):
    for tgt in [33, 41]:
        m = next((mm for mm in part.getElementsByClass("Measure") if mm.number == tgt), None)
        if m is None: continue
        notes_seq = []
        for n in m.recurse().notes:
            ps = [n.pitch] if isinstance(n, note.Note) else (n.pitches if isinstance(n, m21chord.Chord) else [])
            for p in ps:
                notes_seq.append(p.nameWithOctave)
            if len(notes_seq) >= 12: break
        print(f"  part {p_idx+1} m{tgt}: {' '.join(notes_seq[:12])}")
