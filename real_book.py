"""Generate a Real Book style lead sheet from analysis outputs.

Reads summary.json (for key/tempo) and chord_chart_v3.txt (for half-bar
chord data), groups into 4/4 bars by INDEX (not time — avoids floating-
point boundary drift), and renders an ASCII lead sheet with 4 bars per
line, a detected repeating loop, and section markers.

Usage:
    python3 real_book.py --out ./out/my-song
    python3 real_book.py --out ./out/my-song --title "Song Title" --artist "Artist Name"
    python3 real_book.py --out ./out/my-song --bpm 80.75 --bars-per-line 4
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, needs_out=True)
_parser.add_argument("--bpm", type=float, default=None,
    help="Override tempo. Default: from summary.json (corrects for half-time).")
_parser.add_argument("--title",  default="")
_parser.add_argument("--artist", default="")
_parser.add_argument("--bars-per-line", type=int, default=4)
_parser.add_argument("--no-simplify", action="store_true",
    help="Print every bar; skip loop detection.")
_args = _parser.parse_args()
OUT = paths.ensure_dir(_args.out)

summary = paths.load_summary(OUT)

# ── Metadata ──────────────────────────────────────────────────────────────────
bpm       = float(summary.get("tempo_bpm", 120))
top_bpms  = summary.get("tempogram_top_bpms", [])
half_time = summary.get("half_time_suspected", False)

# Half-time detection is a heuristic and it gets this wrong: a genuine 135 BPM
# piece with strong energy on the half-note will show a tempogram peak near 68,
# trip the check, and end up stamped at half its real tempo. Silently halving a
# correct reading is worse than leaving an ambiguous one alone, so the suspected
# half-time value is only ever *suggested* here — applying it requires --bpm.
true_bpm = _args.bpm if _args.bpm else bpm

half_time_suggestion = None
if half_time and top_bpms and not _args.bpm:
    half = bpm / 2.0
    for tb in top_bpms:
        if abs(tb - half) / max(half, 1e-6) < 0.06:
            half_time_suggestion = tb
            break

cands     = summary.get("key_candidates") or []
key_root  = cands[0]["root"] if cands else "?"
key_mode  = (cands[0]["mode"] if cands else "?").capitalize()
duration  = float(summary.get("duration_sec", 0))
title     = _args.title  or Path(summary.get("file", "Untitled")).stem
artist    = _args.artist or ""

beat_period = 60.0 / true_bpm
bar_period  = 4.0 * beat_period


# ── Parse chord_chart_v3.txt ──────────────────────────────────────────────────
chart_file = OUT / "chord_chart_v3.txt"
if not chart_file.exists():
    raise SystemExit(
        f"error: {chart_file} not found.\n"
        f"  run: python3 analyze_v3.py --audio <file> --out {OUT}"
    )

half_bar_chords: list[tuple[float, str]] = []
with open(chart_file) as f:
    for line in f:
        m = re.match(r"\s*([\d.]+)s\s*\|\s*(\S+)", line)
        if m:
            half_bar_chords.append((float(m.group(1)), m.group(2)))

if not half_bar_chords:
    raise SystemExit("error: no chord entries found in chord_chart_v3.txt")

# ── Bar mapping: 2 consecutive half-bars → 1 bar (index-based, no float drift)
# analyze_v3 generates exactly 2 half-bars per bar; indexing by position is
# exact. Time-based mapping can mis-assign half-bars that land right on a
# bar boundary due to rounding in the analysis output.
total_bars = (len(half_bar_chords) + 1) // 2

bars: dict[int, list[tuple[float, str]]] = {}  # bar_num (1-indexed) → [(time, chord)]
for idx, (t, chord) in enumerate(half_bar_chords):
    bn = idx // 2 + 1
    bars.setdefault(bn, []).append((t, chord))

# Bar start times (approximate — first half-bar in the bar).
bar_times: dict[int, float] = {bn: items[0][0] for bn, items in bars.items()}


def bar_display(items: list[tuple[float, str]]) -> str:
    """Reduce a bar's half-bars to a display string.

    Same chord on both halves → one chord.
    Different chords → "A / B" (Real Book slash notation).
    Three items due to edge rounding → take the majority chord as beat 1,
    the minority as beat 3.
    """
    chords = [c for _, c in items]
    if not chords:
        return "%"
    counts = Counter(chords)
    if len(counts) == 1:
        return chords[0]
    # Majority → beat 1 slot; first different → beat 3 slot.
    by_freq = counts.most_common()
    beat1 = by_freq[0][0]
    beat3 = next((c for c in chords if c != beat1), by_freq[1][0])
    return f"{beat1} / {beat3}"


bar_strings: dict[int, str] = {bn: bar_display(items) for bn, items in bars.items()}
for bn in range(1, total_bars + 1):
    bar_strings.setdefault(bn, "%")


# ── Outro detection: look for a sustained harmonic shift near the end ──────────
# Strategy: find the last bar where the chord is clearly different from the
# dominant chord of the song, sustained for ≥2 consecutive bars, in the
# final 20% of the song.
dominant_chord = Counter(bar_strings.values()).most_common(1)[0][0]
last_20pct_start = int(total_bars * 0.80)
outro_bar: int | None = None

for bn in range(last_20pct_start, total_bars):
    chord = bar_strings.get(bn, "%")
    next_chord = bar_strings.get(bn + 1, "%")
    if chord != dominant_chord and next_chord == chord and chord != "%":
        outro_bar = bn
        break


# ── Section labels ──────────────────────────────────────────────────────────
# Sections: INTRO (bars 1–N where harmony is sparse/intro-like),
# MAIN BODY (the repeating loop), OUTRO (if detected).
# Heuristic: INTRO = first bars until the first chord change from the
# dominant chord has settled (first sustained IV or ii appearance).
intro_end_bar = 1
for bn in range(1, min(total_bars, 20)):
    chord = bar_strings.get(bn, "%")
    if chord != dominant_chord and chord != "%":
        intro_end_bar = bn - 1
        break

intro_end_bar = max(intro_end_bar, 1)
body_start = intro_end_bar + 1
body_end = (outro_bar - 1) if outro_bar else total_bars


# ── Loop detection in the main body ──────────────────────────────────────────
def find_dominant_loop(
    bar_strs: dict[int, str], start: int, end: int,
    min_len: int = 2, max_len: int = 8,
) -> tuple[int, list[str]] | None:
    """Find the most-repeated n-bar chord sequence in [start, end]."""
    seq = [bar_strs.get(bn, "%") for bn in range(start, end + 1)]
    best: tuple[int, list[str]] | None = None
    best_score = 0
    for n in range(min_len, max_len + 1):
        patterns: dict[tuple[str, ...], int] = {}
        for i in range(len(seq) - n + 1):
            pat = tuple(seq[i : i + n])
            patterns[pat] = patterns.get(pat, 0) + 1
        if not patterns:
            continue
        top_pat, count = max(patterns.items(), key=lambda kv: kv[1])
        # Prefer loops with chord variety (not just "Dmaj7 × n").
        variety = len(set(top_pat))
        score = count * variety
        if score > best_score and count >= 2:
            best_score = score
            best = (n, list(top_pat))
    return best


# ── Render ────────────────────────────────────────────────────────────────────
BAR_W = 14
BPL   = _args.bars_per_line


def render_bar(s: str) -> str:
    return f" {s:<{BAR_W - 1}}"


def render_line(
    bar_nums: list[int],
    open_rep: bool = False,
    close_rep: bool = False,
    override: dict[int, str] | None = None,
) -> str:
    src = override or bar_strings
    left  = "‖:" if open_rep  else "│"
    right = ":‖" if close_rep else "│"
    cells = "│".join(render_bar(src.get(bn, "%")) for bn in bar_nums)
    return f"{left}{cells}{right}"


lines: list[str] = []

# Header.
lines += [
    "",
    f"  {'=' * 52}",
    f"  {title.upper()}" if title else "",
    f"  ({artist})"      if artist else "",
    f"  Key: {key_root} {key_mode}   ♩= {true_bpm:.0f}   4/4",
]
if half_time_suggestion is not None:
    lines.append(
        f"  [half-time feel suspected: {half_time_suggestion:.0f} BPM may be the true"
        f" pulse.  Chart is at the detected {bpm:.0f}.]"
    )
    lines.append(
        f"  [to redraw at that pulse: real_book.py --out {OUT}"
        f" --bpm {half_time_suggestion:.2f}]"
    )
lines += [f"  {'=' * 52}", ""]

# ── INTRO ──────────────────────────────────────────────────────────────────────
if intro_end_bar >= 1:
    lines.append(f"  ┌─ INTRO {'─' * 43}┐")
    intro_bars = list(range(1, intro_end_bar + 1))
    for i in range(0, len(intro_bars), BPL):
        chunk = intro_bars[i : i + BPL]
        lines.append("  " + render_line(chunk))
    lines.append("")

# ── MAIN BODY ─────────────────────────────────────────────────────────────────
loop_info = None if _args.no_simplify else find_dominant_loop(
    bar_strings, body_start, body_end
)

if loop_info and not _args.no_simplify:
    loop_len, loop_chords = loop_info
    variety = len(set(loop_chords))
    lines.append(
        f"  ┌─ MAIN BODY  ({loop_len}-bar loop, repeats ~"
        f"{(body_end - body_start + 1) // loop_len}×) {'─' * 12}┐"
    )

    # Render the loop pattern with repeat signs.
    loop_override = {i + 1: c for i, c in enumerate(loop_chords)}
    for i in range(0, loop_len, BPL):
        chunk = list(range(i + 1, min(i + BPL, loop_len) + 1))
        lines.append(
            "  " + render_line(
                chunk,
                open_rep=(i == 0),
                close_rep=(i + BPL >= loop_len),
                override=loop_override,
            )
        )

    # Harmonic departures: bars whose chord ROOT is not in the loop's root set.
    # Positional shifts (G landing on bar 2 vs bar 3) are normal loop variation
    # and are intentionally ignored here.
    def chord_root(label: str) -> str:
        return label[:2] if len(label) >= 2 and label[1] == "#" else label[:1]

    loop_roots = {chord_root(c) for c in loop_chords}

    departures = []
    for bn in range(body_start, body_end + 1):
        actual = bar_strings.get(bn, "%")
        t      = bar_times.get(bn, (bn - 1) * bar_period)
        if actual in ("%",) or "/" in actual:
            continue
        if chord_root(actual) not in loop_roots:
            departures.append((bn, actual, t))

    if departures:
        lines.append("")
        lines.append("  Harmonic departures (root outside loop vocabulary):")
        for bn, actual, t in departures[:12]:
            m, s = divmod(int(t), 60)
            lines.append(f"    bar {bn:3d} ({m}:{s:02d})  {actual}")
        if len(departures) > 12:
            lines.append(f"    … and {len(departures) - 12} more")

else:
    # Full verbatim render.
    lines.append(f"  ┌─ MAIN BODY {'─' * 39}┐")
    body_bars = list(range(body_start, body_end + 1))
    for i in range(0, len(body_bars), BPL):
        chunk = body_bars[i : i + BPL]
        lines.append("  " + render_line(chunk))

lines.append("")

# ── OUTRO ─────────────────────────────────────────────────────────────────────
if outro_bar is not None:
    lines.append(f"  ┌─ OUTRO {'─' * 43}┐")
    outro_bars = list(range(outro_bar, total_bars + 1))
    for i in range(0, len(outro_bars), BPL):
        chunk = outro_bars[i : i + BPL]
        lines.append("  " + render_line(chunk))
    lines.append("  (to fade)")
    lines.append("")

# ── Print + save ───────────────────────────────────────────────────────────────
output = "\n".join(l for l in lines if l is not None)
print(output)
out_path = OUT / "real_book.txt"
out_path.write_text(output + "\n")
print(f"\nsaved {out_path}")
