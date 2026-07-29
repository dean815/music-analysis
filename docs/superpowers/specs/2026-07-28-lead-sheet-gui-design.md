# Lead Sheet GUI — Design

**Date:** 2026-07-28
**Status:** Design approved; extraction shipped. GUI implementation not started — handed off to a separate session.
**Depends on:** PR #6 (correctness fixes) and the `refactor/extract-lead-sheet` branch.

## Context

`music-analysis` is a CLI toolkit: audio and MusicXML in, tempo/key/chord/form analysis out, plus a Real Book style ASCII lead sheet. This spec covers putting an interactive GUI over the lead-sheet half of it.

The session that produced this spec also found and fixed two long-standing correctness defects in `analyze.py` (see PR #6). That matters here for one reason: it established that the analysis gets tempo and structure *nearly* right and needs a human to correct it. The GUI is where that correction happens. It is not a viewer.

## Decisions on record

| Decision | Answer |
|---|---|
| Audience | Portfolio showcase — a hiring manager should grasp it fast |
| Delivery | Local clone-and-run first; hosting is a later increment, not a rewrite |
| Core interaction | Correct and re-render: override what the machine got wrong, redraw instantly |
| Correction axes | Intro end, outro start, loop length, bars-per-line, title/artist |
| Tempo | Displayed and overridable, but **cosmetic** — see below |
| Stack | FastAPI + vanilla HTML/CSS/JS, no build step |
| Scope for v1 | Operates on an already-analysed `out/<track>/`. Running the analysis from the UI is out. |

### Why tempo is cosmetic

`bpm` reaches only two places: the header string, and a fallback for bar timestamps that rarely fires because `bar_times` comes from the chart file. Bar mapping is index-based *by design*, to avoid float drift. A tempo control changes one number in a header — worth exposing for correctness of the printed chart, but it is not the interesting axis.

### Why the structural axes are

The heuristics are crude and visibly wrong on real input:

- **Intro end** — "first bar in 1..20 whose chord differs from the dominant chord, minus one." On the demo track this yields a **1-bar intro**.
- **Outro start** — scans the last 20% for a sustained non-dominant chord.
- **Loop length** — scores `count × variety` over lengths 2–8. On the demo track it returns a **3-bar loop** (`Dmaj7 / Emaj7 │ Dmaj7 │ Emaj7`); forcing `--loop-len 2` yields `Dmaj7 │ Emaj7`, musically the more plausible reading.

A musician improves on these at a glance. That is the demo.

## Current state — the seam already exists

`lead_sheet.py` shipped on `refactor/extract-lead-sheet`. The GUI does **not** need to refactor anything; it consumes this API.

```python
import lead_sheet

sheet = lead_sheet.build(
    out_dir,                 # Path to an analysed out/<track>/
    bpm=None,                # override; None = detected
    title="", artist="",
    intro_end=None,          # override; None = heuristic
    outro_start=None,        # override; None = heuristic
    loop_len=None,           # override; None = detect
    simplify=True,           # False = render every bar, skip loop detection
)                            # -> LeadSheet

text = lead_sheet.render_ascii(sheet, bars_per_line=4)
```

`LeadSheet` fields: `title`, `artist`, `key_root`, `key_mode`, `bpm`, `detected_bpm`, `duration`, `out_dir`, `total_bars`, `bars: dict[int, str]`, `bar_times: dict[int, float]`, `intro_end`, `body_start`, `body_end`, `outro_start`, `loop: tuple[int, list[str]] | None`, `departures: list[tuple[int, str, float]]`, `half_time_suggestion`, and a `loop_repeats` property.

Properties the GUI can rely on:

- **`build()` is pure and fast.** Everything expensive happens in `analyze.py` / `analyze_v3.py`. `build()` only reads two files and transforms data, so a full rebuild per keystroke is fine.
- **Overrides are clamped, not validated.** Out-of-range values are silently pulled into `[1, total_bars]`. A slider can be dragged anywhere without the caller knowing the bar count.
- **Errors are exceptions, not exits.** `build()` raises `FileNotFoundError` / `ValueError`. It never calls `sys.exit`, so it is safe inside a server process.
- **`bars` is the render model.** `dict[bar_number, display_string]`, 1-indexed, with `"%"` for empty bars. `"C / G"` denotes two chords in one bar (Real Book slash notation).

## Architecture

```
out/<track>/{summary.json, chord_chart_v3.txt}
        |
        v
lead_sheet.build(overrides)  ->  LeadSheet
        |                              |
        v                              v
render_ascii()                   JSON (gui/app.py)
   (CLI today)                         |
                                       v
                              HTML bar grid (gui/static/)
```

| unit | responsibility |
|---|---|
| `gui/app.py` | FastAPI. `GET /` serves the page. `GET /api/tracks` lists analysed `out/*` dirs. `POST /api/sheet` takes `{out_dir, overrides}` and returns a serialised `LeadSheet`. |
| `gui/static/index.html` | Page shell: track picker, control panel, chart area. |
| `gui/static/app.js` | Reads controls, POSTs, renders the bar grid. No framework. |
| `gui/static/style.css` | The visual craft. This is the portfolio surface. |

### Data flow

Control change → `POST /api/sheet` with the full override set → server calls `build()` → JSON → client redraws the grid. Stateless; the server holds no session. Sub-100ms, so no optimistic rendering or debouncing beyond the obvious.

### Rendering the chart

The ASCII output is the reference, not the target. HTML should do what the box-drawing characters approximate: bars as real cells, repeat signs as styled glyphs, section headers as headings, departures as an annotated list linking back to bar numbers. Print stylesheet is worth having — a lead sheet is a thing musicians print.

### Error handling

- No `out/` dirs at all → empty state naming the `analyze.py` command to run.
- Chosen dir missing `chord_chart_v3.txt` → the `analyze_v3.py` command, rendered in the page. Never a stack trace.
- `build()` raising → 422 with the exception message; client shows it inline and keeps the last good chart on screen.

### Testing

`lead_sheet.py` is already covered (39 tests). New tests needed:

- `POST /api/sheet` round-trip against `tests/fixtures/synthetic` — the same fixture the unit tests use, so no audio is required in CI.
- Override plumbing: a request with `loop_len: 2` returns a 2-bar loop.
- Error mapping: nonexistent dir → 422, not 500.

Frontend tests are out of scope; keep logic in the server so there is little to test client-side.

## Out of scope for v1

- Running `analyze.py` / `analyze_v3.py` from the UI. Requires job management and progress streaming for a minute-long task.
- **Key correction.** The most valuable missing axis — the demo track modulates A → B → G major twice, and a single global key label makes `analyze_v3` flag the tonic `Dmaj7` as OUT-OF-KEY. Fixing it means extracting the in-key/out-of-key labelling from `analyze_v3.py`, a second refactor of comparable size. `analyze_v2.py` — currently orphaned, nothing reads its outputs — is described as doing "per-section key detection", so it may be a partial answer already in the repo. **Do not delete `analyze_v2.py` without reading it first.**
- Hosting. The seam supports it; the increment is a container plus a static build.
- Multi-track comparison, export to MusicXML/MIDI, audio playback.

## Open questions — resolved 2026-07-28

1. **Web dependencies.** Resolved: `requirements-gui.txt`. `fastapi` and
   `uvicorn` stay out of `requirements.txt`, CI installs all three files, and
   the GUI tests `importorskip("fastapi")` so a lean install reports skips
   rather than collection errors. The `--html` static-export alternative was
   rejected: it removes the live controls, which are the product.
2. **Which track ships as the demo.** Resolved: the D Lydian bounce, as
   `examples/demo/`. Only `summary.json` and `chord_chart_v3.txt` are tracked;
   the `file` field is scrubbed from an absolute path to a bare title, since
   `build()` derives the chart title from it. It lives in `examples/` rather
   than `out/` so `analyze.py --out out/demo` cannot overwrite tracked data.
3. **Does the GUI write anything?** Resolved: no. The server is read-only. The
   page renders the `real_book.py` invocation that reproduces the current
   chart, which gives durability through the CLI seam that already exists
   without inventing a precedence contract between a state file and explicit
   flags.

## Notes for the implementing session

- Start from `refactor/extract-lead-sheet` (or `main` once it merges). `lead_sheet.py` is done; do not re-extract it.
- The golden-output check that guarded the refactor lives in the session scratchpad, not the repo. If you change `render_ascii`, regenerate goldens for `out/kitchen` and `out/demo` across all five flag combinations first.
- Two background tasks were running at handoff: a fix for false-positive half-time detection (`analyze.py:104`) and a verify-then-fix for crossfade drift in `generate_previews.py:163`. Neither touches `lead_sheet.py`.
- `out/kitchen` derives its title from the source filename and therefore names a commercial track. It is gitignored. Keep it out of anything committed or screenshotted.
