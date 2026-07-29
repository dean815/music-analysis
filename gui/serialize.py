"""Turn a LeadSheet into the JSON the page draws, plus the command that repeats it.

render_ascii() makes four layout decisions: which sections exist, which bars
belong to each, that the loop is drawn as loop positions rather than absolute
bars, and where the repeat signs go. A browser client re-deriving those from the
raw LeadSheet fields would be a second implementation of the same rules, free to
disagree with the CLI. So they are made once, here, and app.js walks the result.

Corrections are not persisted anywhere. `cli_command()` is the durability story:
whatever the musician dialled in comes back as a real_book.py invocation that
reproduces it from the shell.
"""
from __future__ import annotations

import shlex

import lead_sheet
from lead_sheet import LeadSheet


def timecode(seconds: float) -> str:
    """Seconds as m:ss, the form the ASCII departure list uses."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _cells(sheet: LeadSheet, numbers) -> list[dict]:
    return [{"number": n, "display": sheet.bars.get(n, "%")} for n in numbers]


def sections(sheet: LeadSheet) -> list[dict]:
    """The chart as an ordered list of drawable sections.

    `number` is an absolute bar number everywhere except inside a detected loop,
    where it is the position within the loop — the loop is printed once under a
    repeat sign, so absolute numbering there would be a lie about which pass of
    the figure you are looking at.
    """
    out: list[dict] = []

    if sheet.intro_end >= 1:
        out.append({
            "kind": "intro",
            "label": "Intro",
            "detail": "",
            "repeat": False,
            "note": "",
            "bars": _cells(sheet, range(1, sheet.intro_end + 1)),
        })

    if sheet.loop:
        length, chords = sheet.loop
        out.append({
            "kind": "loop",
            "label": "Main body",
            "detail": f"{length}-bar loop, repeats ~{sheet.loop_repeats}×",
            "repeat": True,
            "note": "",
            "bars": [{"number": i + 1, "display": c} for i, c in enumerate(chords)],
        })
    else:
        out.append({
            "kind": "body",
            "label": "Main body",
            "detail": "",
            "repeat": False,
            "note": "",
            "bars": _cells(sheet, range(sheet.body_start, sheet.body_end + 1)),
        })

    if sheet.outro_start is not None:
        out.append({
            "kind": "outro",
            "label": "Outro",
            "detail": "",
            "repeat": False,
            "note": "to fade",
            "bars": _cells(sheet, range(sheet.outro_start, sheet.total_bars + 1)),
        })

    return out


def cli_command(out_dir_arg: str, overrides: dict) -> str:
    """The real_book.py invocation that reproduces this chart from a shell.

    Only flags that depart from the defaults are emitted, so the command stays
    readable and reads as a list of the musician's disagreements with the
    machine rather than a dump of every setting.
    """
    parts = ["python3", "real_book.py", "--out", out_dir_arg]

    if overrides.get("title"):
        parts += ["--title", str(overrides["title"])]
    if overrides.get("artist"):
        parts += ["--artist", str(overrides["artist"])]
    if overrides.get("bpm") is not None:
        parts += ["--bpm", f"{float(overrides['bpm']):g}"]
    if overrides.get("intro_end") is not None:
        parts += ["--intro-end", str(int(overrides["intro_end"]))]
    if overrides.get("outro_start") is not None:
        parts += ["--outro-start", str(int(overrides["outro_start"]))]
    if overrides.get("loop_len") is not None:
        parts += ["--loop-len", str(int(overrides["loop_len"]))]
    if int(overrides.get("bars_per_line", 4) or 4) != 4:
        parts += ["--bars-per-line", str(int(overrides["bars_per_line"]))]
    if not overrides.get("simplify", True):
        parts.append("--no-simplify")

    return " ".join(shlex.quote(p) for p in parts)


def sheet_to_dict(
    sheet: LeadSheet,
    *,
    bars_per_line: int,
    out_dir_arg: str,
    overrides: dict,
) -> dict:
    """The whole POST /api/sheet response body."""
    return {
        "title": sheet.title,
        "artist": sheet.artist,
        "key": f"{sheet.key_root} {sheet.key_mode}",
        "key_root": sheet.key_root,
        "key_mode": sheet.key_mode,
        "bpm": sheet.bpm,
        "detected_bpm": sheet.detected_bpm,
        "duration": sheet.duration,
        "duration_timecode": timecode(sheet.duration),
        "total_bars": sheet.total_bars,
        "intro_end": sheet.intro_end,
        "body_start": sheet.body_start,
        "body_end": sheet.body_end,
        "outro_start": sheet.outro_start,
        "bars_per_line": bars_per_line,
        "sections": sections(sheet),
        "loop": None if not sheet.loop else {
            "length": sheet.loop[0],
            "chords": sheet.loop[1],
            "repeats": sheet.loop_repeats,
        },
        "departures": [
            {"bar": bn, "chord": chord, "time": t, "timecode": timecode(t)}
            for bn, chord, t in sheet.departures
        ],
        "half_time_suggestion": sheet.half_time_suggestion,
        "ascii": lead_sheet.render_ascii(sheet, bars_per_line=bars_per_line),
        "cli_command": cli_command(out_dir_arg, overrides),
    }
