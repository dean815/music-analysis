"""FastAPI server for the interactive lead sheet.

No analysis runs here. `lead_sheet.build()` reads two text files and transforms
them, so every control change can round-trip through the server and come back as
a whole fresh chart. The server holds no session state: a request carries the
complete override set, and nothing is written to disk — corrections are
reproduced through the printed `real_book.py` command, not persisted.

Unlike the analysis scripts, argument parsing happens under `__main__` rather
than at import. `app` is imported directly by uvicorn and by the tests, and a
module-level `parse_args()` would consume their argv.

Usage:
    python3 gui/app.py                              # serves ./out on :8000
    python3 gui/app.py --out-root examples --port 9000
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import paths  # noqa: E402

EXAMPLES_ROOT = REPO_ROOT / "examples"
ANALYZE_HINT = "python3 analyze.py --audio <file> --out out/<name>"

app = FastAPI(title="Lead Sheet")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Defaults for `uvicorn gui.app:app` and for tests; __main__ overrides them.
app.state.out_root = Path(paths.OUT)
app.state.allow_example_fallback = True


# ── Track discovery ───────────────────────────────────────────────────────────


def list_tracks(root: Path) -> list[dict]:
    """Analysed track dirs directly under `root`, sorted by name.

    "Analysed" means summary.json exists — that is the file analyze.py writes
    first and everything downstream reads. A dir with a summary but no chord
    chart is still listed, with has_chart False, so the UI can name the
    analyze_v3.py command instead of hiding the track.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    tracks = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name.startswith("."):
            continue
        if not (d / "summary.json").exists():
            continue
        tracks.append({
            "name": d.name,
            "has_chart": (d / "chord_chart_v3.txt").exists(),
        })
    return tracks


def resolve_out_root(configured: Path, allow_fallback: bool) -> tuple[Path, bool]:
    """Pick the directory to serve, falling back to the bundled example.

    A fresh clone has no out/ yet. Opening on an empty picker would show the
    shell of a correction tool and nothing to correct, so the bundled example
    stands in — but only when the root was defaulted, never when the operator
    named one explicitly, and the response always says which happened.
    """
    configured = Path(configured)
    if list_tracks(configured):
        return configured, False
    if allow_fallback and list_tracks(EXAMPLES_ROOT):
        return EXAMPLES_ROOT, True
    return configured, False


def _active_root() -> tuple[Path, bool]:
    return resolve_out_root(app.state.out_root, app.state.allow_example_fallback)


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static" / "index.html").read_text()


@app.get("/api/tracks")
def api_tracks() -> dict:
    root, is_fallback = _active_root()
    return {
        "out_root": str(root),
        "is_example_fallback": is_fallback,
        "tracks": list_tracks(root),
        "analyze_hint": ANALYZE_HINT,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out-root", type=Path, default=None,
        help="Directory holding analysed track dirs (default: $MUSIC_OUT or ./out). "
             "When defaulted and empty, the bundled examples/ is served instead.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    args = parser.parse_args()

    app.state.out_root = args.out_root if args.out_root else Path(paths.OUT)
    app.state.allow_example_fallback = args.out_root is None

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
