# Lead Sheet GUI — design handoff

For wireframing in Claude Design. Written cold-start: assumes no knowledge of the repo.

---

## 1. What this is

A local web tool that renders a **lead sheet** (a one-page chord chart musicians read from) out of the output of an audio-analysis pipeline.

The critical thing to understand: **it is a correction tool, not a viewer.** The analysis guesses at song structure using crude heuristics, and on real music the guesses are visibly wrong. The intro detector is literally "first bar whose chord differs from the most common chord, minus one" — on the demo track that yields a **1-bar intro**. Loop detection returns a **3-bar loop** where a musician would immediately say it's 2 bars.

So the product is not "here is your chart." It is **"here is what the machine thinks; tell it where it's wrong and watch the chart redraw."** Making a musician's disagreement with the machine fast and legible *is* the product. Any wireframe that treats this as a document viewer with settings has missed it.

## 2. Audience

Two, simultaneously:

1. **A musician** correcting a chart for their own song, who wants to print it or copy it into a DAW session.
2. **A hiring manager** who opens it for ninety seconds. This is a portfolio piece. It has to communicate what it does without a tour.

## 3. Current state

Built and working, vanilla HTML/CSS/JS + a small Python server. Roughly:

```
┌────────────────────────────────────────────────────────────────────────┐
│ LEAD SHEET   Correct what the analysis got wrong…      TRACK [demo ▾]  │
├────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────┐  ┌──────────────────────────────────────────────┐ │
│ │ CORRECTIONS      │  │                                              │ │
│ │                  │  │          D LYDIAN SOARING GUITAR             │ │
│ │ ┌──────────────┐ │  │   Key: C# Minor  ♩=136  4/4  73 bars  2:08   │ │
│ │ │ Half-time    │ │  │  ══════════════════════════════════════════  │ │
│ │ │ suspected —  │ │  │                                              │ │
│ │ │ 68 BPM may   │ │  │  INTRO                                       │ │
│ │ │ be the true  │ │  │  ┌────────┐                                  │ │
│ │ │ pulse [Use]  │ │  │  │¹ Dmaj7 │                                  │ │
│ │ └──────────────┘ │  │  └────────┘                                  │ │
│ │                  │  │                                              │ │
│ │ Intro ends at    │  │  MAIN BODY  3-bar loop, repeats ~19×         │ │
│ │ bar      ☑ AUTO  │  │     ┌──────────┬────────┬────────┐           │ │
│ │ ──○─────────  1  │  │  ‖: │¹Dmaj7/Em7│²Dmaj7  │³Emaj7  │ :‖        │ │
│ │                  │  │     └──────────┴────────┴────────┘           │ │
│ │ Outro starts at  │  │                                              │ │
│ │ bar      ☑ AUTO  │  │  OUTRO                                       │ │
│ │ ─────────○─  60  │  │  ┌────────┬────────┬────────┬────────┐       │ │
│ │                  │  │  │⁶⁰C#maj7│⁶¹C#maj7│⁶²C#/G#m│⁶³G#m/C#│       │ │
│ │ Loop length      │  │  ├────────┼────────┼────────┼────────┤       │ │
│ │          ☑ AUTO  │  │  │  … 14 bars total, 4 per row …    │       │ │
│ │ ──○─────────  3  │  │  └────────┴────────┴────────┴────────┘       │ │
│ │                  │  │  (to fade)                                   │ │
│ │ Tempo    ☑ AUTO  │  │  ──────────────────────────────────────────  │ │
│ │ [136.00]  BPM    │  │  HARMONIC DEPARTURES                         │ │
│ │ Cosmetic — hits  │  │  Bars whose root sits outside the loop's     │ │
│ │ the header only. │  │  vocabulary.                                 │ │
│ │                  │  │  bar 15  0:24  F#m7   bar 32  0:54  C#m7     │ │
│ │ Title  [_______] │  │  bar 33  0:56  C#m7   bar 35  1:00  C#m7     │ │
│ │ Artist [_______] │  │  … 11 total                                  │ │
│ │ Bars/line [4 ▾]  │  │  ──────────────────────────────────────────  │ │
│ │ ☑ Collapse       │  │  python3 real_book.py --out out/demo  [Copy] │ │
│ │   repeats        │  │                                              │ │
│ │ ☐ Show ASCII     │  └──────────────────────────────────────────────┘ │
│ └──────────────────┘                                                   │
└────────────────────────────────────────────────────────────────────────┘
```

**One caveat on that diagram:** the half-time chip is *conditional*, and on the bundled demo track it does **not** appear — a tempo heuristic that used to fire here was corrected, and 136 BPM no longer trips it. It is drawn above because it's an existing component worth designing around (see problem F), but if you open the tool expecting it, you won't see it. Everything else in the diagram is what the demo track actually renders.

Visual language today: cream paper (`#faf6ec`), near-black ink, a rust accent (`#8a5a2b`), serif for chords and headings (Iowan Old Style / Palatino), monospace for metadata and bar numbers. The reference is a **Real Book page** — the standard fake-book format jazz musicians read from. Bar cells with real bar lines, repeat signs (`‖:` `:‖`) as their own marks flanking a repeated section.

There is a print stylesheet: printing drops the top bar, corrections panel, ASCII pane and CLI line, leaving just the chart. Musicians print these.

## 4. The data the screen renders

One POST returns the whole chart. Real response for the demo track, abridged:

```jsonc
{
  "title": "D Lydian Soaring Guitar",   // derived from the audio filename unless overridden
  "artist": "",
  "key": "C# Minor",
  "bpm": 135.99,
  "detected_bpm": 135.99,               // differs from bpm when the user overrides
  "duration_timecode": "2:08",
  "total_bars": 73,
  "intro_end": 1,                       // ← the machine's guess, often wrong
  "body_start": 2,
  "body_end": 59,
  "outro_start": 60,                    // nullable — some songs have no outro
  "bars_per_line": 4,
  "half_time_suggestion": null,         // nullable — "the tempo may be double the real pulse".
                                        // null on this track; non-null only above ~150 BPM.

  "sections": [                         // ordered, ready to draw, 1–3 of them
    { "kind": "intro", "label": "Intro", "detail": "", "repeat": false, "note": "",
      "bars": [ {"number": 1, "display": "Dmaj7"} ] },

    { "kind": "loop",  "label": "Main body", "detail": "3-bar loop, repeats ~19×",
      "repeat": true, "note": "",
      "bars": [ {"number": 1, "display": "Dmaj7 / Emaj7"},
                {"number": 2, "display": "Dmaj7"},
                {"number": 3, "display": "Emaj7"} ] },

    { "kind": "outro", "label": "Outro", "detail": "", "repeat": false, "note": "to fade",
      "bars": [ /* 14 cells, absolute bar numbers 60–73 */ ] }
  ],

  "loop": { "length": 3, "chords": ["Dmaj7 / Emaj7","Dmaj7","Emaj7"], "repeats": 19 },

  "departures": [                       // 11 of these on this track
    { "bar": 15, "chord": "F#m7", "time": 24.71, "timecode": "0:24" },
    { "bar": 32, "chord": "C#m7", "time": 54.71, "timecode": "0:54" }
    // …
  ],

  "cli_command": "python3 real_book.py --out out/demo --loop-len 2"
}
```

Notes that matter for layout:

- **`display` can hold two chords**: `"Dmaj7 / Emaj7"` means two chords in one bar (Real Book slash notation). It can also be `"%"`, meaning "repeat the previous bar" — an empty bar.
- **`section.kind` is one of `intro` / `loop` / `body` / `outro`.** `loop` and `body` are alternatives: `loop` when repeats are collapsed, `body` when every bar is drawn.
- **Inside a `loop` section, `number` is the position in the loop (1,2,3), not an absolute bar number.** Everywhere else it's the absolute bar.
- **Chord labels run 2–7 characters**: `C`, `Am`, `Dmaj7`, `F#sus2`, `C#m7`, `G#maj7`, and two-chord cells like `F#sus2 / Gadd9` which is 14 characters.
- Sections can be **empty** (`bars: []`) if the user drags intro-end past outro-start. Currently shows an inline note.

Scale: this track is 73 bars. With repeat-collapsing off, that's **73 cells on one page**. Longer songs will be worse — assume up to ~300 bars.

## 5. Interaction model

- Every control change POSTs the **full override set** and redraws from the response. The server holds no state.
- **Server rebuild takes ~1.5 ms.** Redraw is effectively instant; you can design for continuous feedback while dragging a slider, with no spinners or optimistic rendering.
- Each structural control is an **auto / mine pair**. Auto = the machine's heuristic runs and the control *displays* what it decided. Unchecking hands the axis to the user, seeded with the machine's value so taking over never moves the chart by itself. This distinction is the core of the product and currently gets a checkbox labelled "AUTO" — which is the weakest part of the design.
- **Nothing is saved.** Corrections vanish on reload. The durability story is the copyable `real_book.py` command at the bottom, which reproduces the corrected chart from a terminal.
- **Tempo is cosmetic** — it only changes a number in the header. It's exposed for correctness of the printed page, but it is *not* an interesting axis and shouldn't anchor the layout.

## 6. States that need designing

The happy path is only part of it:

1. **Nothing analysed yet** — no tracks at all. Needs to name the shell command that produces one.
2. **Track half-analysed** — has metadata but no chord data. Server returns an error naming the missing command; the page shows it and keeps the previous chart on screen.
3. **Error while correcting** — a rebuild fails; the last good chart stays visible with the message above it. (Deliberate: blanking the page would remove the context needed to see which control broke.)
4. **Bundled-example fallback** — when the user's output directory is empty, a bundled demo track loads instead, with a banner saying so.
5. **No loop detected** — `loop` is null, the whole body renders bar-by-bar, no repeat signs.
6. **No outro detected** — `outro_start` is null, section absent.
7. **Empty section** — contradictory overrides.
8. **Print.**
9. **Narrow viewport.**

## 7. Open design problems — the actual brief

Ranked by how much they'd improve the thing.

### A. Departures reference bars you cannot see ★ the sharpest one

The departures list calls out 11 bars — 15, 32, 33, 35, 36, 37, 44, 45, 52, 53, 58 — that sit harmonically outside the loop. **Every one of those bars is inside the 58-bar body that the loop view collapses into 3 cells.** So the chart says "bars 2–59 are this 3-bar figure ×19," then a list underneath says "except at bar 15, and 32, and 33…" pointing at bars that aren't drawn anywhere.

Musically, these are the most interesting moments in the song — the places the tune leaves its own harmony. Right now they're a footnote of orphan numbers. How should a collapsed loop and its exceptions be shown *together*? Some directions: a timeline strip under the loop marking where departures fall; departures as annotations hanging off a repeat bracket; an expand-in-place for the region around a departure; treating them as "endings" the way a Real Book writes 1st/2nd endings.

### B. "The machine said X, I say Y" needs to be visible

A checked box labelled AUTO carries the entire concept. There is no persistent sense of *what the machine originally thought* once you've overridden it, no way to see how many axes you've changed, and no one-click "revert to the machine's reading." Given that the whole product is a human disagreeing with a heuristic, this deserves a real pattern. Consider showing both values, a modified-count, per-axis reset, and a diff-like summary.

### C. Density at length

73 bars is fine. 300 is not. Consider how the chart behaves as songs get long: does the corrections panel stay pinned, does the chart get its own scroll region, is there a minimap or section nav, does bars-per-line adapt to width instead of being a manual 2/4/8 choice?

### D. The bars-per-line control is a layout knob in a semantic panel

It sits among corrections but it isn't a correction — it doesn't change what the machine got wrong, only how the page wraps. Same for "show ASCII." Worth separating "what the song is" from "how to draw it."

### E. Two audiences, one screen

A hiring manager needs to grasp in ninety seconds that this is a correction tool. A musician wants their chart with minimal chrome. Right now the strapline does all that work. There may be a better first-run treatment — perhaps showing an axis mid-correction so the value is legible on arrival.

### F. Machine uncertainty as a category

The tool has exactly one component that admits doubt: a chip reading "Half-time feel suspected — 68 BPM may be the true pulse [Use 68]", which offers a correction rather than applying it. It's a good pattern and it's bespoke — it exists for one heuristic only.

It also **doesn't fire on the demo track** (the heuristic that produced it there was a false positive and has since been fixed), which makes the point sharper: the one place the tool shows uncertainty is invisible most of the time, while *every other* number on the page — intro end, outro start, loop length, the key — is equally a guess and is presented as fact. Is there a consistent visual language for "this is inferred, and here's how sure we are," rather than one chip for one case?

## 8. Hard constraints

- **Vanilla HTML/CSS/JS.** No framework, no build step, no CDN, no external fonts or assets. Anything designed has to be buildable in plain markup and stylesheets.
- **Must print well.** A print stylesheet already exists and is a real requirement, not a nice-to-have.
- Server is **read-only**; nothing the design implies can write files.
- The chart's structural content is **decided server-side** — section order, which bars are in which section, where repeat signs go. The client draws what it's given. Redesigns of *layout* are free; redesigns that need different structural grouping mean changing server code (possible, just not free).
- Runs locally, single user, no auth, no accounts.

## 9. Out of scope

Deliberately excluded: running the audio analysis from the UI, audio playback, multi-track comparison, export to MusicXML/MIDI, hosting/multi-user, and **key correction** (the most-wanted missing axis — the demo track modulates and a single global key label mislabels the tonic chord as out-of-key; it needs pipeline work before it can be designed).

## 10. Useful reference

Search "Real Book page" for the visual reference — the format's conventions around bar lines, repeat signs, section labels, endings and coda marks are all fair game, and leaning further into them would likely improve this.
