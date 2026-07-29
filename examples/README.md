# Bundled example

`demo/` is a real analysis run over one of my own recordings — a D Lydian guitar
piece, 128 seconds, 73 bars. It is here so a fresh clone has something to open in
the GUI without needing audio on disk.

Only the two files the lead sheet actually consumes are tracked:

| File | Written by | Read by |
|---|---|---|
| `summary.json` | `analyze.py` | key, tempo, duration, half-time suspicion |
| `chord_chart_v3.txt` | `analyze_v3.py` | half-bar chord track |

The `file` field in `summary.json` has been rewritten from the absolute path of
my local bounce to a bare title. Nothing else is modified — the numbers are what
the analysis produced.

This directory is *not* where the tools write. Analysis output goes to `out/`,
which is gitignored. `examples/` is tracked, read-only demo data; the GUI falls
back to it when `out/` holds nothing analysed yet.

To regenerate from your own audio:

    python3 analyze.py    --audio your-track.wav --out out/your-track
    python3 analyze_v3.py --audio your-track.wav --out out/your-track
    python3 gui/app.py    --out-root out
