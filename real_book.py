"""Generate a Real Book style lead sheet from analysis outputs.

Reads summary.json (for key/tempo) and chord_chart_v3.txt (for half-bar
chord data), groups into 4/4 bars by INDEX (not time — avoids floating-
point boundary drift), and renders an ASCII lead sheet with 4 bars per
line, a detected repeating loop, and section markers.

The analysis and rendering live in lead_sheet.py so other consumers can
build the same chart without going through this CLI. This file is the
command-line front end: parse flags, build, render, save.

Usage:
    python3 real_book.py --out ./out/my-song
    python3 real_book.py --out ./out/my-song --title "Song Title" --artist "Artist Name"
    python3 real_book.py --out ./out/my-song --bpm 80.75 --bars-per-line 4
"""
from __future__ import annotations

import argparse

import lead_sheet
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
_parser.add_argument("--intro-end", type=int, default=None,
    help="Override the detected last bar of the intro.")
_parser.add_argument("--outro-start", type=int, default=None,
    help="Override the detected first bar of the outro.")
_parser.add_argument("--loop-len", type=int, default=None,
    help="Force the main-body loop to this many bars instead of detecting it.")
_args = _parser.parse_args()

OUT = paths.ensure_dir(_args.out)

try:
    sheet = lead_sheet.build(
        OUT,
        bpm=_args.bpm,
        title=_args.title,
        artist=_args.artist,
        intro_end=_args.intro_end,
        outro_start=_args.outro_start,
        loop_len=_args.loop_len,
        simplify=not _args.no_simplify,
    )
except (FileNotFoundError, ValueError) as exc:
    raise SystemExit(f"error: {exc}")

output = lead_sheet.render_ascii(sheet, bars_per_line=_args.bars_per_line)
print(output)

out_path = OUT / "real_book.txt"
out_path.write_text(output + "\n")
print(f"\nsaved {out_path}")
