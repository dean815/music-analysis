# music-analysis

This project provides a tool that takes audio input and analyzes the musical
content — tempo, key/mode, chord progression, structural form, and melodic
content. MusicXML files can also be provided for more intentional analysis
using exact note information rather than estimates from audio features.
Beyond analysis, the tool offers suggestions for musical ideas that could
be used to complete or extend a piece, and generates MIDI and audio
renderings of those ideas so they can be auditioned directly or imported
into a DAW.

Built around `librosa` + `pyin` for audio features and `music21` for
symbolic harmonic analysis.

## Setup

```bash
# Recommended: a virtualenv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

# Configure paths to your audio + MusicXML files
cp .env.example .env
$EDITOR .env             # fill in MUSIC_AUDIO, MUSIC_XML, etc.
set -a; source .env; set +a
```

You can also override env vars per-script with CLI flags — every script supports
`--audio`, `--xml`, `--guitars-xml`, `--out`, or `--previews` as appropriate. Run
any script with `--help` to see its specific flags.

## Try it without your own audio

Every audio script needs a `--audio` bounce, which normally means your own mix.
To try the pipeline without one, generate a public-domain demo bounce first —
the ground bass of Pachelbel's *Canon in D* (c. 1680), rendered by the repo's
own synth, so nothing needs downloading:

```bash
python3 demo_bounce.py                                   # -> out/demo_bounce.wav
python3 analyze.py    --audio out/demo_bounce.wav --out out/demo
python3 analyze_v3.py --audio out/demo_bounce.wav --out out/demo
python3 real_book.py  --out out/demo
```

That should report ~136 BPM, pick **D major** as the top key candidate, and
render a lead sheet whose main loop is the ground bass — a quick end-to-end
check that your install works and that the analysis is behaving.

## What each script does

| Script | Inputs | Purpose |
|---|---|---|
| `demo_bounce.py` | `--out` | Renders a public-domain demo bounce (Pachelbel's *Canon in D* ground bass) so the audio scripts are runnable without private audio. Start here if you just want to see the pipeline work |
| `analyze.py` | `--audio` | First-pass audio analysis: tempo, key (Krumhansl), chromagram, structural segmentation |
| `analyze_v2.py` | `--audio` | Refined audio: bar-level chord smoothing, per-section key detection |
| `analyze_v3.py` | `--audio` | Fine-grained chord track with Viterbi smoothing, Dorian-vs-Aeolian diagnostic |
| `melody.py` | `--audio` | Monophonic pitch extraction via pyin; tests Lydian #4 vs natural 4 |
| `xml_analyze.py` | `--xml` | Symbolic analysis: exact notes from MusicXML, Roman numerals, key signature events |
| `xml_aligned.py` | `--xml` | Bar-by-bar chord chart with measure-to-time alignment |
| `xml_guitars.py` | `--guitars-xml` | Pitch histograms per section for guitar/lead parts |
| `generate_previews.py` | `--previews` (out) | Synthesizes audio + MIDI of hypothetical chord progressions |
| `splice_transitions.py` | `--audio`, `--previews` | Crossfades synth previews into the start of your bounce for transition auditioning |
| `real_book.py` | `--out` | Renders a Real Book-style ASCII lead sheet from `analyze_v3.py`'s chord chart, with loop detection and section labels. Override the detected structure with `--intro-end`, `--outro-start`, `--loop-len`, or the tempo with `--bpm` |
| `lead_sheet.py` | — | Shared module behind `real_book.py`: turns the chord chart into structured lead-sheet data (bars, sections, loop, departures), separately from rendering it. Import this rather than shelling out if you want the chart as data |
| `paths.py` | — | Shared config helper (env vars + argparse) used by all scripts |
| `modes.py` | — | Shared modal-theory module: resolves a mode name into its diatonic pitch classes and tests a melody against its closest sibling mode. Used by `analyze_v3.py` and `melody.py` |
| `modal_prior.py` | — | **Work-in-progress.** Scaffold for a modal-diatonic prior to bias chord detection toward harmonically plausible chords. The function body is intentionally unimplemented; see the docstring for the policy choices to fill in. |

## Output locations

By default each script writes to:
- `./out/` for analysis artifacts (PNG plots, JSON summaries, TSV chord charts)
- `./previews/` for generated audio + MIDI

Both are gitignored. Override with `--out` / `--previews` or `MUSIC_OUT` / `MUSIC_PREVIEWS` env vars.

## Notes on the pipeline

- **Audio analysis is approximate; MusicXML analysis is exact.** Whenever both inputs are available, prefer the symbolic results. The audio pipeline is most useful for cases where no score exists or for cross-checking the score against what was actually performed.
- **The audio scripts share assumptions:** 44.1 kHz sample rate, stereo input that gets summed to mono, hop sizes tuned for chord-time-scale analysis (~46 ms at hop=2048). If your audio is in a different format, you may need to adapt.
- **`paths.py` centralizes path config.** If you want to add a new script, follow the pattern in any existing script: `import argparse; import paths; ...; paths.add_args(parser, ...); ...; paths.require(args.x, "MUSIC_X")`.

## Privacy

This repository is intended to be runnable on any audio/MusicXML inputs, not tied to
a specific piece. The default values for all paths come from environment variables
in your local `.env` (which is gitignored). No personal paths are committed to git
history — verify with `git log -p | grep '/Users/' ` after any changes.

## License

MIT License — see [LICENSE](LICENSE).
