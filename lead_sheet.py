"""Lead sheet construction from analysis artifacts.

Reads `summary.json` (key/tempo) and `chord_chart_v3.txt` (half-bar chord data)
from an analysis output directory and produces a `LeadSheet` — structured data
describing bars, sections, the detected loop, and harmonic departures.

Rendering is separate from construction on purpose. `build()` returns data;
`render_ascii()` turns it into the Real Book style chart the CLI prints. Any
other consumer (a GUI, a JSON API) renders the same `LeadSheet` its own way
without reimplementing the analysis.

Every structural decision `build()` makes by heuristic can be overridden by the
caller. Passing `intro_end`, `outro_start`, or `loop_len` replaces the guess with
a human's judgement; omitting them keeps the heuristic. This is what lets an
interactive consumer correct the chart without re-running audio analysis, since
everything here is pure data transformation over the two artifact files.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import paths

BAR_W = 14
_HEADER_RULE = "=" * 52


@dataclass
class LeadSheet:
    """Everything needed to render a lead sheet, with no analysis left to do."""

    # Metadata
    title: str
    artist: str
    key_root: str
    key_mode: str
    bpm: float
    detected_bpm: float
    duration: float
    out_dir: Path

    # Bar data
    total_bars: int
    bars: dict[int, str]
    bar_times: dict[int, float]

    # Structure
    intro_end: int
    body_start: int
    body_end: int
    outro_start: int | None

    # Detected loop: (length_in_bars, chord_strings)
    loop: tuple[int, list[str]] | None = None
    departures: list[tuple[int, str, float]] = field(default_factory=list)

    # Set when the tempo looks like it may be double the true pulse. Only ever a
    # suggestion — see the note in build().
    half_time_suggestion: float | None = None

    @property
    def loop_repeats(self) -> int:
        if not self.loop:
            return 0
        return (self.body_end - self.body_start + 1) // self.loop[0]


# ── Parsing ───────────────────────────────────────────────────────────────────

_CHART_RE = re.compile(r"\s*([\d.]+)s\s*\|\s*(\S+)")


def parse_chart(chart_file: Path) -> list[tuple[float, str]]:
    """Read `chord_chart_v3.txt` into (time, chord) pairs, one per half-bar."""
    if not chart_file.exists():
        raise FileNotFoundError(
            f"{chart_file} not found.\n"
            f"  run: python3 analyze_v3.py --audio <file> --out {chart_file.parent}"
        )
    out: list[tuple[float, str]] = []
    with open(chart_file) as f:
        for line in f:
            m = _CHART_RE.match(line)
            if m:
                out.append((float(m.group(1)), m.group(2)))
    if not out:
        raise ValueError(f"no chord entries found in {chart_file}")
    return out


def bar_display(items: list[tuple[float, str]]) -> str:
    """Reduce a bar's half-bars to a display string.

    Same chord on both halves → one chord.
    Different chords → "A / B" (Real Book slash notation).
    Three items due to edge rounding → majority chord as beat 1, minority beat 3.
    """
    chords = [c for _, c in items]
    if not chords:
        return "%"
    counts = Counter(chords)
    if len(counts) == 1:
        return chords[0]
    by_freq = counts.most_common()
    beat1 = by_freq[0][0]
    beat3 = next((c for c in chords if c != beat1), by_freq[1][0])
    return f"{beat1} / {beat3}"


def map_bars(
    half_bar_chords: list[tuple[float, str]],
) -> tuple[int, dict[int, str], dict[int, float]]:
    """Group half-bars into 4/4 bars by INDEX, not time.

    analyze_v3 emits exactly two half-bars per bar, so positional indexing is
    exact. Time-based mapping can mis-assign a half-bar that lands right on a bar
    boundary due to rounding in the analysis output.
    """
    total_bars = (len(half_bar_chords) + 1) // 2
    grouped: dict[int, list[tuple[float, str]]] = {}
    for idx, (t, chord) in enumerate(half_bar_chords):
        grouped.setdefault(idx // 2 + 1, []).append((t, chord))

    bar_times = {bn: items[0][0] for bn, items in grouped.items()}
    bars = {bn: bar_display(items) for bn, items in grouped.items()}
    for bn in range(1, total_bars + 1):
        bars.setdefault(bn, "%")
    return total_bars, bars, bar_times


# ── Structure detection ───────────────────────────────────────────────────────


def detect_intro_end(bars: dict[int, str], total_bars: int, dominant: str) -> int:
    """First bar whose chord departs from the dominant chord, minus one."""
    intro_end = 1
    for bn in range(1, min(total_bars, 20)):
        chord = bars.get(bn, "%")
        if chord != dominant and chord != "%":
            intro_end = bn - 1
            break
    return max(intro_end, 1)


def detect_outro_start(
    bars: dict[int, str], total_bars: int, dominant: str
) -> int | None:
    """Last sustained harmonic shift in the final 20% of the chart."""
    for bn in range(int(total_bars * 0.80), total_bars):
        chord = bars.get(bn, "%")
        if chord != dominant and bars.get(bn + 1, "%") == chord and chord != "%":
            return bn
    return None


def find_dominant_loop(
    bars: dict[int, str],
    start: int,
    end: int,
    min_len: int = 2,
    max_len: int = 8,
) -> tuple[int, list[str]] | None:
    """Find the most-repeated n-bar chord sequence in [start, end].

    Scored by repeat count times chord variety, so a genuinely alternating
    progression beats a run of one chord repeated n times.
    """
    seq = [bars.get(bn, "%") for bn in range(start, end + 1)]
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
        score = count * len(set(top_pat))
        if score > best_score and count >= 2:
            best_score = score
            best = (n, list(top_pat))
    return best


def chord_root(label: str) -> str:
    """Root of a chord label, keeping an accidental ("C#m7" → "C#")."""
    return label[:2] if len(label) >= 2 and label[1] == "#" else label[:1]


# ── Construction ──────────────────────────────────────────────────────────────


def build(
    out_dir: Path | str,
    *,
    bpm: float | None = None,
    title: str = "",
    artist: str = "",
    intro_end: int | None = None,
    outro_start: int | None = None,
    loop_len: int | None = None,
    simplify: bool = True,
) -> LeadSheet:
    """Build a LeadSheet from an analysis output directory.

    All structural arguments are optional overrides. Omitted means "use the
    heuristic"; supplied means "the caller decided". Overrides are clamped to the
    chart's actual extent rather than raising, so an interactive caller can move a
    control freely without needing to know the bar count in advance.
    """
    out_dir = Path(out_dir)
    # paths.load_summary() calls sys.exit() when the file is missing, which is
    # right for a CLI and fatal for a long-running consumer. Check first so this
    # module always signals by exception; real_book.py turns it back into an exit.
    if not (out_dir / "summary.json").exists():
        raise FileNotFoundError(
            f"no summary.json in {out_dir}.\n"
            f"  run: python3 analyze.py --audio <file> --out {out_dir}"
        )
    summary = paths.load_summary(out_dir)

    detected_bpm = float(summary.get("tempo_bpm", 120))
    top_bpms = summary.get("tempogram_top_bpms", [])
    half_time = summary.get("half_time_suspected", False)

    # Half-time detection is a heuristic and it gets this wrong: a genuine 135 BPM
    # piece with strong energy on the half-note shows a tempogram peak near 68,
    # trips the check, and would end up stamped at half its real tempo. Silently
    # halving a correct reading is worse than leaving an ambiguous one alone, so
    # the candidate is only ever suggested — applying it requires an explicit bpm.
    true_bpm = bpm if bpm else detected_bpm
    half_time_suggestion = None
    if half_time and top_bpms and not bpm:
        half = detected_bpm / 2.0
        for tb in top_bpms:
            if abs(tb - half) / max(half, 1e-6) < 0.06:
                half_time_suggestion = tb
                break

    cands = summary.get("key_candidates") or []
    total_bars, bars, bar_times = map_bars(parse_chart(out_dir / "chord_chart_v3.txt"))
    dominant = Counter(bars.values()).most_common(1)[0][0]

    resolved_outro = (
        detect_outro_start(bars, total_bars, dominant)
        if outro_start is None
        else max(1, min(int(outro_start), total_bars))
    )
    resolved_intro = (
        detect_intro_end(bars, total_bars, dominant)
        if intro_end is None
        else max(1, min(int(intro_end), total_bars))
    )

    body_start = resolved_intro + 1
    body_end = (resolved_outro - 1) if resolved_outro else total_bars

    loop = None
    departures: list[tuple[int, str, float]] = []
    if simplify and body_start <= body_end:
        if loop_len is not None:
            n = max(1, min(int(loop_len), max(1, body_end - body_start + 1)))
            loop = find_dominant_loop(bars, body_start, body_end, min_len=n, max_len=n)
        else:
            loop = find_dominant_loop(bars, body_start, body_end)

    if loop:
        bar_period = 4.0 * (60.0 / true_bpm)
        loop_roots = {chord_root(c) for c in loop[1]}
        for bn in range(body_start, body_end + 1):
            actual = bars.get(bn, "%")
            if actual == "%" or "/" in actual:
                continue
            if chord_root(actual) not in loop_roots:
                departures.append(
                    (bn, actual, bar_times.get(bn, (bn - 1) * bar_period))
                )

    return LeadSheet(
        title=title or Path(summary.get("file", "Untitled")).stem,
        artist=artist,
        key_root=cands[0]["root"] if cands else "?",
        key_mode=(cands[0]["mode"] if cands else "?").capitalize(),
        bpm=true_bpm,
        detected_bpm=detected_bpm,
        duration=float(summary.get("duration_sec", 0)),
        out_dir=out_dir,
        total_bars=total_bars,
        bars=bars,
        bar_times=bar_times,
        intro_end=resolved_intro,
        body_start=body_start,
        body_end=body_end,
        outro_start=resolved_outro,
        loop=loop,
        departures=departures,
        half_time_suggestion=half_time_suggestion,
    )


# ── ASCII rendering ───────────────────────────────────────────────────────────


def _render_bar(s: str) -> str:
    return f" {s:<{BAR_W - 1}}"


def _render_line(
    src: dict[int, str],
    bar_nums: list[int],
    open_rep: bool = False,
    close_rep: bool = False,
) -> str:
    left = "‖:" if open_rep else "│"
    right = ":‖" if close_rep else "│"
    cells = "│".join(_render_bar(src.get(bn, "%")) for bn in bar_nums)
    return f"{left}{cells}{right}"


def render_ascii(sheet: LeadSheet, bars_per_line: int = 4) -> str:
    """Render a LeadSheet as a Real Book style ASCII chart."""
    bpl = max(1, int(bars_per_line))
    lines: list[str] = [
        "",
        f"  {_HEADER_RULE}",
        f"  {sheet.title.upper()}" if sheet.title else "",
        f"  ({sheet.artist})" if sheet.artist else "",
        f"  Key: {sheet.key_root} {sheet.key_mode}   ♩= {sheet.bpm:.0f}   4/4",
    ]
    if sheet.half_time_suggestion is not None:
        lines.append(
            f"  [half-time feel suspected: {sheet.half_time_suggestion:.0f} BPM may be"
            f" the true pulse.  Chart is at the detected {sheet.detected_bpm:.0f}.]"
        )
        lines.append(
            f"  [to redraw at that pulse: real_book.py --out {sheet.out_dir}"
            f" --bpm {sheet.half_time_suggestion:.2f}]"
        )
    lines += [f"  {_HEADER_RULE}", ""]

    if sheet.intro_end >= 1:
        lines.append(f"  ┌─ INTRO {'─' * 43}┐")
        intro_bars = list(range(1, sheet.intro_end + 1))
        for i in range(0, len(intro_bars), bpl):
            lines.append("  " + _render_line(sheet.bars, intro_bars[i : i + bpl]))
        lines.append("")

    if sheet.loop:
        loop_len, loop_chords = sheet.loop
        lines.append(
            f"  ┌─ MAIN BODY  ({loop_len}-bar loop, repeats ~"
            f"{sheet.loop_repeats}×) {'─' * 12}┐"
        )
        override = {i + 1: c for i, c in enumerate(loop_chords)}
        for i in range(0, loop_len, bpl):
            chunk = list(range(i + 1, min(i + bpl, loop_len) + 1))
            lines.append(
                "  "
                + _render_line(
                    override,
                    chunk,
                    open_rep=(i == 0),
                    close_rep=(i + bpl >= loop_len),
                )
            )
        if sheet.departures:
            lines.append("")
            lines.append("  Harmonic departures (root outside loop vocabulary):")
            for bn, actual, t in sheet.departures[:12]:
                m, s = divmod(int(t), 60)
                lines.append(f"    bar {bn:3d} ({m}:{s:02d})  {actual}")
            if len(sheet.departures) > 12:
                lines.append(f"    … and {len(sheet.departures) - 12} more")
    else:
        lines.append(f"  ┌─ MAIN BODY {'─' * 39}┐")
        body_bars = list(range(sheet.body_start, sheet.body_end + 1))
        for i in range(0, len(body_bars), bpl):
            lines.append("  " + _render_line(sheet.bars, body_bars[i : i + bpl]))

    lines.append("")

    if sheet.outro_start is not None:
        lines.append(f"  ┌─ OUTRO {'─' * 43}┐")
        outro_bars = list(range(sheet.outro_start, sheet.total_bars + 1))
        for i in range(0, len(outro_bars), bpl):
            lines.append("  " + _render_line(sheet.bars, outro_bars[i : i + bpl]))
        lines.append("  (to fade)")
        lines.append("")

    return "\n".join(l for l in lines if l is not None)
