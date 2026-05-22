"""Centralized path configuration for analysis scripts.

Reads from environment variables, with CLI flags as overrides:

    $ export MUSIC_AUDIO=~/Music/Logic/Bounces/your_track.wav
    $ export MUSIC_XML=~/Music/Logic/your_track.xml
    $ python3 analyze.py                       # uses env vars
    $ python3 analyze.py --audio other.wav     # CLI overrides env

Output directories default to ./out and ./previews under the project root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _env_path(var: str, default: str | None = None) -> Path | None:
    """Look up an env var as a path. Returns None if unset and no default."""
    raw = os.environ.get(var, default)
    return Path(raw).expanduser() if raw else None


# Defaults — populated from environment.
AUDIO: Path | None = _env_path("MUSIC_AUDIO")
XML: Path | None = _env_path("MUSIC_XML")
GUITARS_XML: Path | None = _env_path("MUSIC_GUITARS_XML")
OUT: Path = _env_path("MUSIC_OUT", "./out")  # type: ignore[assignment]
PREVIEWS: Path = _env_path("MUSIC_PREVIEWS", "./previews")  # type: ignore[assignment]


def add_args(
    parser: argparse.ArgumentParser,
    *,
    audio: bool = False,
    xml: bool = False,
    guitars: bool = False,
    needs_out: bool = True,
    needs_previews: bool = False,
) -> None:
    """Attach standard --audio / --xml / --guitars-xml / --out / --previews flags.

    Pass only the flags the script actually needs. Each is optional at the
    argparse level (so --help works without env vars set), but `require()`
    below errors helpfully if a required value is still None at use time.
    """
    if audio:
        parser.add_argument(
            "--audio", type=Path, default=AUDIO,
            help="Path to bounce WAV (default: $MUSIC_AUDIO)",
        )
    if xml:
        parser.add_argument(
            "--xml", type=Path, default=XML,
            help="Path to MusicXML (default: $MUSIC_XML)",
        )
    if guitars:
        parser.add_argument(
            "--guitars-xml", dest="guitars_xml", type=Path, default=GUITARS_XML,
            help="Path to guitar-parts MusicXML (default: $MUSIC_GUITARS_XML)",
        )
    if needs_out:
        parser.add_argument(
            "--out", type=Path, default=OUT,
            help="Output directory (default: ./out)",
        )
    if needs_previews:
        parser.add_argument(
            "--previews", type=Path, default=PREVIEWS,
            help="Previews directory (default: ./previews)",
        )


def require(value: Path | None, var_name: str, *, must_exist: bool = True) -> Path:
    """Validate a path argument. Exits with a helpful message if missing/invalid."""
    if value is None:
        sys.exit(
            f"error: no path supplied for {var_name}.\n"
            f"  set the env var {var_name} or pass --{var_name.lower().replace('music_', '').replace('_', '-')}"
        )
    if must_exist and not value.exists():
        sys.exit(f"error: path does not exist: {value}")
    return value


def ensure_dir(path: Path) -> Path:
    """Create a directory if it doesn't exist, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_summary(out_dir: Path) -> dict:
    """Load the summary.json that analyze.py writes into its --out directory.

    Downstream scripts (analyze_v3.py, melody.py, etc.) call this to pick up
    tempo, section boundaries, and key candidates rather than recomputing
    them or — worse — hardcoding them.

    Exits with a helpful message if the file isn't there, since "run
    analyze.py first" is the canonical workflow.
    """
    p = Path(out_dir) / "summary.json"
    if not p.exists():
        sys.exit(
            f"error: no summary.json in {out_dir}.\n"
            f"  run `python3 analyze.py --audio <file> --out {out_dir}` first."
        )
    with open(p) as f:
        return json.load(f)
