# Lead Sheet GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put an interactive correction tool over `lead_sheet.build()` so a musician can disagree with the structural heuristics and watch the chart redraw.

**Architecture:** A stateless FastAPI server wraps the existing `lead_sheet` module. Every control change POSTs the *complete* override set; the server rebuilds the sheet from scratch (cheap — two file reads and a transform) and returns it as JSON. Section layout, repeat-sign placement and the reproducing CLI command are all computed server-side in `gui/serialize.py`, so `app.js` stays a dumb renderer and there is almost nothing to test client-side.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, pydantic v2, pytest + httpx (`TestClient`). Frontend is vanilla HTML/CSS/JS — no build step, no framework, no CDN.

## Global Constraints

These apply to every task. Copied from the spec and the handoff brief.

- **Do not modify `lead_sheet.py`.** The GUI is a consumer. If a task appears to need a change to `build()` or `render_ascii()`, stop and escalate rather than editing.
- **If `render_ascii` is ever changed, the golden-output protocol runs FIRST:** capture output for `out/kitchen` and `out/demo` across all five flag combinations (default, `--title`/`--artist`, `--bpm`, `--bars-per-line`, `--no-simplify`), then diff after. No task in this plan is expected to trigger this.
- **Do not delete or gut `analyze_v2.py`.** It is orphaned but holds the per-section key detection the deferred key-correction axis needs.
- **`out/kitchen` is a commercial recording.** Never commit it, never screenshot it, never use it as demo content. Browser verification steps in this plan use `examples/demo` only.
- **No personal absolute paths in anything committed** — the README promises `git log -p | grep '/Users/'` stays clean. This includes this plan document and the bundled example's `summary.json`.
- **Runtime web deps live in `requirements-gui.txt`**, never in `requirements.txt`. The analysis install stays lean.
- **Corrections are ephemeral.** The server writes nothing to disk. Durability is provided by the copy-able `real_book.py` command only.
- **Python version floor: 3.12** (CI pins 3.12; local venv is 3.13).
- **Commit style:** conventional commits, body explains the wrong output the change prevents — not just what changed. Match `git log`.
- All commands below assume the repo root as CWD. The project virtualenv is `.venv/` at the repo root; use `.venv/bin/python` if a bare `python3` lacks the deps.

---

## File Structure

| File | Responsibility |
|---|---|
| `examples/demo/summary.json` | Bundled example — analysis metadata, source filename scrubbed to a bare title |
| `examples/demo/chord_chart_v3.txt` | Bundled example — half-bar chord track |
| `examples/README.md` | Provenance of the bundled example and how to regenerate it |
| `requirements-gui.txt` | `fastapi`, `uvicorn` — optional install, GUI only |
| `requirements-dev.txt` | add `httpx` (FastAPI `TestClient` transport) |
| `gui/__init__.py` | Marks `gui` a package so `from gui import serialize` resolves identically under `python3 gui/app.py` and `uvicorn gui.app:app` |
| `gui/serialize.py` | `LeadSheet` → render-ready JSON. Owns section layout, repeat-sign placement, timecodes, and the reproducing CLI command. No FastAPI import — testable standalone |
| `gui/app.py` | FastAPI routes, track discovery, out-root resolution, path-traversal guard, exception → 422 mapping |
| `gui/static/index.html` | Page shell: track picker, control panel, chart area |
| `gui/static/app.js` | Reads controls, POSTs, walks `sections`, draws cells |
| `gui/static/style.css` | The visual craft + print stylesheet. This is the portfolio surface |
| `tests/test_example_track.py` | The bundled example is privacy-clean and actually builds |
| `tests/test_gui_serialize.py` | Serializer unit tests — no FastAPI needed |
| `tests/test_gui_api.py` | HTTP round-trip, override plumbing, error mapping. `importorskip("fastapi")` |
| `.github/workflows/ci.yml` | Install `requirements-gui.txt`; import-check `gui.app`; `--help` on `gui/app.py` |
| `README.md` | GUI section, script-table rows, `examples/` note |

---

### Task 1: Bundled example track

Ships Dean's D Lydian bounce as tracked data so a fresh clone has something to show. Only two text files (~6 KB); the 600 KB of PNGs stay out. `out/` remains fully gitignored — the example lives in `examples/`, outside the regenerable-artifacts tree, so `analyze.py --out out/demo` can never clobber it.

**Files:**
- Create: `examples/demo/summary.json`
- Create: `examples/demo/chord_chart_v3.txt`
- Create: `examples/README.md`
- Test: `tests/test_example_track.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `examples/demo/` — the fixture path Task 2's fallback logic and Task 8's manual verification both depend on. Track name is exactly `demo`; rendered title is exactly `D Lydian Soaring Guitar`.

- [ ] **Step 1: Copy the two artifacts out of the analysed directory**

The analysed output lives in the main checkout's gitignored `out/demo`. From the worktree that is `../../../out/demo`; from the main checkout it is `out/demo`. Adjust the source prefix to wherever you are, but the destination is fixed.

```bash
mkdir -p examples/demo
cp ../../../out/demo/summary.json examples/demo/summary.json
cp ../../../out/demo/chord_chart_v3.txt examples/demo/chord_chart_v3.txt
```

- [ ] **Step 2: Scrub the source path out of `summary.json`**

`analyze.py` records the absolute path of the bounce it read. `lead_sheet.build()` derives the chart title from `Path(summary["file"]).stem`, so this field is both the privacy leak and the demo's title. Rewrite it to a bare filename that reads well when upper-cased into a chart header.

```bash
python3 - <<'PY'
import json
from pathlib import Path

p = Path("examples/demo/summary.json")
data = json.loads(p.read_text())
data["file"] = "D Lydian Soaring Guitar.wav"
p.write_text(json.dumps(data, indent=2) + "\n")
print("file ->", data["file"])
PY
```

Expected output: `file -> D Lydian Soaring Guitar.wav`

- [ ] **Step 3: Verify no personal path survives in either file**

```bash
grep -rn "/Users/\|deanhicks\|Bounces" examples/ ; echo "exit=$?"
```

Expected: no matching lines, `exit=1`.

- [ ] **Step 4: Write `examples/README.md`**

```markdown
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
```

- [ ] **Step 5: Write the failing test**

Create `tests/test_example_track.py`:

```python
"""The bundled example is committed data, so it gets committed-data tests.

Two things can rot here and neither shows up as a normal test failure: the
privacy scrub can be undone by someone re-copying from a local out/ dir, and the
chart can drift out of sync with what lead_sheet expects. Both are asserted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lead_sheet  # noqa: E402

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "demo"


def test_example_files_are_present():
    assert (EXAMPLE / "summary.json").exists()
    assert (EXAMPLE / "chord_chart_v3.txt").exists()


def test_example_contains_no_personal_paths():
    # The README promises `git log -p | grep '/Users/'` stays clean.
    for name in ("summary.json", "chord_chart_v3.txt"):
        text = (EXAMPLE / name).read_text()
        assert "/Users/" not in text
        assert "deanhicks" not in text


def test_example_title_is_the_scrubbed_name():
    summary = json.loads((EXAMPLE / "summary.json").read_text())
    assert summary["file"] == "D Lydian Soaring Guitar.wav"


def test_example_builds_into_the_documented_structure():
    # These are the numbers the spec quotes as evidence the heuristics need a
    # human: a 1-bar intro, and a 3-bar loop where 2 bars is the better reading.
    sheet = lead_sheet.build(EXAMPLE)
    assert sheet.title == "D Lydian Soaring Guitar"
    assert sheet.total_bars == 73
    assert sheet.intro_end == 1
    assert sheet.outro_start == 60
    assert sheet.loop == (3, ["Dmaj7 / Emaj7", "Dmaj7", "Emaj7"])


def test_example_two_bar_loop_override_is_the_musical_reading():
    sheet = lead_sheet.build(EXAMPLE, loop_len=2)
    assert sheet.loop == (2, ["Dmaj7", "Emaj7"])
```

- [ ] **Step 6: Run the test**

```bash
.venv/bin/python -m pytest tests/test_example_track.py -q
```

Expected: 5 passed. (The data was copied in Step 1, so these pass immediately — they are a regression guard on committed data, not a red-green cycle.)

- [ ] **Step 7: Confirm git will actually track the example**

`out/` is gitignored; `examples/` must not be caught by any pattern.

```bash
git check-ignore -v examples/demo/summary.json ; echo "exit=$?"
```

Expected: no output, `exit=1` (not ignored).

- [ ] **Step 8: Commit**

```bash
git add examples/ tests/test_example_track.py
git commit -m "$(cat <<'EOF'
feat: bundle a real analysed track as example data

A fresh clone has no out/ directory, so the GUI would have opened on an
empty picker with nothing to demonstrate — a visitor would see the shell of
a correction tool and none of the corrections. examples/demo is a real
analysis run (73 bars, D Lydian) carrying the two files lead_sheet reads.

It lives in examples/ rather than out/ deliberately. out/ is gitignored as
regenerable, and `analyze.py --out out/demo` would silently overwrite a
tracked file if the example were kept there.

analyze.py records the absolute path of the bounce it read, and lead_sheet
derives the chart title from it, so the committed summary.json would have
printed a personal /Users path into every rendered header. The field is
rewritten to a bare title; a test asserts no /Users path comes back.
EOF
)"
```

---

### Task 2: Dependencies, server skeleton, track discovery

Stands up the app with `GET /` and `GET /api/tracks`, plus the out-root resolution that makes clone-and-run land on the bundled example.

**Files:**
- Create: `requirements-gui.txt`
- Modify: `requirements-dev.txt`
- Create: `gui/__init__.py`
- Create: `gui/app.py`
- Create: `gui/static/index.html` (placeholder shell, filled in Task 5)
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_gui_api.py`

**Interfaces:**
- Consumes: `examples/demo/` from Task 1.
- Produces:
  - `gui.app.app` — the `FastAPI` instance. Tests set `app.state.out_root: Path` and `app.state.allow_example_fallback: bool`.
  - `gui.app.list_tracks(root: Path) -> list[dict]` — `[{"name": str, "has_chart": bool}]`, sorted by name.
  - `gui.app.resolve_out_root(configured: Path, allow_fallback: bool) -> tuple[Path, bool]` — returns `(root, is_fallback)`.
  - `GET /api/tracks` → `{"out_root": str, "is_example_fallback": bool, "tracks": [...], "analyze_hint": str}`.

- [ ] **Step 1: Write `requirements-gui.txt`**

```
# Optional — only needed for the lead sheet GUI (gui/app.py).
# The analysis scripts do not import these; keep requirements.txt lean.
fastapi>=0.115
uvicorn>=0.30
```

- [ ] **Step 2: Add the test transport to `requirements-dev.txt`**

Replace the whole file with:

```
# Development-only dependencies (not needed to run the analysis scripts).
pytest>=8.0

# Transport behind fastapi's TestClient. Only the GUI tests use it, and they
# skip themselves when fastapi is absent.
httpx>=0.27
```

- [ ] **Step 3: Install into the venv**

```bash
.venv/bin/python -m pip install -r requirements-gui.txt -r requirements-dev.txt
```

Expected: fastapi, uvicorn, httpx (and their deps) installed; no errors.

- [ ] **Step 4: Write `gui/__init__.py`**

```python
"""Web front end for the lead sheet.

A package rather than a bare directory so `from gui import serialize` resolves
the same way whether the server was started as `python3 gui/app.py` or as
`uvicorn gui.app:app`. Deliberately imports nothing — importing this must not
require fastapi.
"""
```

- [ ] **Step 5: Write the failing test**

Create `tests/test_gui_api.py`:

```python
"""HTTP-level tests for the lead sheet GUI.

The GUI's dependencies are optional (requirements-gui.txt), so these skip
rather than error for someone who installed only the analysis requirements.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi", reason="GUI deps are optional: requirements-gui.txt")

from fastapi.testclient import TestClient  # noqa: E402

from gui.app import app  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
EXAMPLES = REPO / "examples"


@pytest.fixture
def client(tmp_path):
    """A client whose out-root is the synthetic fixture dir, fallback disabled.

    tests/fixtures holds exactly one analysed dir (`synthetic`), which makes it
    a usable out-root without copying files around.
    """
    app.state.out_root = FIXTURES
    app.state.allow_example_fallback = False
    with TestClient(app) as c:
        yield c


def test_index_serves_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_tracks_lists_analysed_dirs(client):
    res = client.get("/api/tracks")
    assert res.status_code == 200
    body = res.json()
    names = [t["name"] for t in body["tracks"]]
    assert "synthetic" in names
    assert body["is_example_fallback"] is False


def test_tracks_reports_chart_presence(client):
    entry = next(t for t in client.get("/api/tracks").json()["tracks"]
                 if t["name"] == "synthetic")
    assert entry["has_chart"] is True


def test_tracks_skips_dirs_without_a_summary(tmp_path):
    (tmp_path / "not-analysed").mkdir()
    app.state.out_root = tmp_path
    app.state.allow_example_fallback = False
    with TestClient(app) as c:
        assert c.get("/api/tracks").json()["tracks"] == []


def test_tracks_falls_back_to_the_bundled_example(tmp_path):
    # A fresh clone has no out/ at all. Showing an empty picker there teaches a
    # visitor nothing, so the bundled example stands in — and says so.
    app.state.out_root = tmp_path / "nonexistent-out"
    app.state.allow_example_fallback = True
    with TestClient(app) as c:
        body = c.get("/api/tracks").json()
    assert body["is_example_fallback"] is True
    assert [t["name"] for t in body["tracks"]] == ["demo"]


def test_explicit_out_root_does_not_silently_become_the_example(tmp_path):
    # --out-root is an instruction, not a hint. An empty one stays empty.
    app.state.out_root = tmp_path
    app.state.allow_example_fallback = False
    with TestClient(app) as c:
        body = c.get("/api/tracks").json()
    assert body["is_example_fallback"] is False
    assert body["tracks"] == []
```

- [ ] **Step 6: Run it to confirm it fails**

```bash
.venv/bin/python -m pytest tests/test_gui_api.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'gui.app'`.

- [ ] **Step 7: Write `gui/app.py`**

```python
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
```

- [ ] **Step 8: Write the placeholder `gui/static/index.html`**

Task 5 replaces this. It exists now so `GET /` and the `StaticFiles` mount have something to serve.

```html
<!doctype html>
<meta charset="utf-8">
<title>Lead Sheet</title>
<h1>Lead Sheet</h1>
```

- [ ] **Step 9: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_gui_api.py -q
```

Expected: 6 passed.

- [ ] **Step 10: Verify `--help` works and the server boots**

```bash
.venv/bin/python gui/app.py --help
```

Expected: usage text listing `--out-root`, `--host`, `--port`.

- [ ] **Step 11: Update CI**

In `.github/workflows/ci.yml`, change the install step to add the GUI requirements:

```yaml
      - name: Install dependencies
        run: |
          python -m pip install -r requirements.txt
          python -m pip install -r requirements-gui.txt
          python -m pip install -r requirements-dev.txt
```

Change the import-check step to cover the server module:

```yaml
      - name: Import-check shared modules
        run: |
          python -c "import paths, modes, lead_sheet"
          python -c "import gui.app"
```

And add `gui/app.py` to the smoke-test loop — replace that step's script with:

```yaml
      - name: Smoke-test each script (--help)
        run: |
          set -e
          for f in analyze.py analyze_v2.py analyze_v3.py melody.py \
                   xml_analyze.py xml_aligned.py xml_guitars.py \
                   generate_previews.py splice_transitions.py real_book.py \
                   modal_prior.py gui/app.py; do
            echo "=== $f ==="
            python3 "$f" --help
          done
```

- [ ] **Step 12: Run the full suite**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: 45 passed (39 existing + 5 from Task 1 + 6 here... report the actual count; the pre-existing 39 must all still pass).

- [ ] **Step 13: Commit**

```bash
git add requirements-gui.txt requirements-dev.txt gui/ .github/workflows/ci.yml tests/test_gui_api.py
git commit -m "$(cat <<'EOF'
feat: add the lead sheet server with track discovery

First half of the GUI: GET / and GET /api/tracks.

fastapi and uvicorn go in requirements-gui.txt rather than requirements.txt
so that `pip install -r requirements.txt` for someone who only wants the
analysis scripts does not pull a web framework and an ASGI server they never
import. CI installs all three files, and the GUI tests importorskip fastapi
so a lean install reports skips instead of collection errors.

Track discovery keys on summary.json rather than on the chord chart, so a
directory that has been through analyze.py but not analyze_v3.py is listed
with has_chart false. Filtering it out instead would have made a
half-analysed track invisible with no indication of which command was
missing.

Argument parsing sits under __main__ rather than at module level as the
other scripts do: uvicorn and TestClient both import this module, and a
module-level parse_args() would consume their argv and exit.
EOF
)"
```

---

### Task 3: The serializer

Turns a `LeadSheet` into exactly what the browser draws. Section order, which bars belong to which section, and where repeat signs go are decided here — the same decisions `render_ascii` makes — so `app.js` never re-derives them and cannot drift.

**Files:**
- Create: `gui/serialize.py`
- Test: `tests/test_gui_serialize.py`

**Interfaces:**
- Consumes: `lead_sheet.LeadSheet`.
- Produces:
  - `gui.serialize.timecode(seconds: float) -> str` — `"2:05"`.
  - `gui.serialize.sections(sheet: LeadSheet) -> list[dict]` — each `{"kind": str, "label": str, "detail": str, "repeat": bool, "note": str, "bars": [{"number": int, "display": str}]}`; `kind` ∈ `{"intro", "loop", "body", "outro"}`.
  - `gui.serialize.cli_command(out_dir_arg: str, overrides: dict) -> str`.
  - `gui.serialize.sheet_to_dict(sheet, *, bars_per_line: int, out_dir_arg: str, overrides: dict) -> dict` — the full `POST /api/sheet` response body.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gui_serialize.py`:

```python
"""Tests for the LeadSheet -> JSON layer.

This module owns the layout decisions render_ascii also makes (section order,
bar membership, repeat signs). Testing it here rather than through HTTP keeps
the assertions about shape, and means these run without fastapi installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lead_sheet  # noqa: E402
from gui import serialize  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic"


@pytest.fixture
def sheet():
    return lead_sheet.build(FIXTURE)


# ── timecode ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "seconds,expected",
    [(0.0, "0:00"), (5.4, "0:05"), (65.0, "1:05"), (125.9, "2:05"), (600.0, "10:00")],
)
def test_timecode_formats_as_minutes_and_padded_seconds(seconds, expected):
    assert serialize.timecode(seconds) == expected


# ── sections ──────────────────────────────────────────────────────────────────


def test_sections_follow_the_ascii_order(sheet):
    assert [s["kind"] for s in serialize.sections(sheet)] == ["intro", "loop", "outro"]


def test_intro_section_holds_the_intro_bars(sheet):
    intro = serialize.sections(sheet)[0]
    assert [b["number"] for b in intro["bars"]] == [1]
    assert intro["bars"][0]["display"] == "C"
    assert intro["repeat"] is False


def test_loop_section_is_marked_repeating_and_holds_loop_positions(sheet):
    loop = serialize.sections(sheet)[1]
    assert loop["repeat"] is True
    assert loop["detail"] == "4-bar loop, repeats ~4×"
    # Numbers are positions inside the loop, not absolute bars — the same thing
    # render_ascii does when it renders the loop instead of the body.
    assert [b["number"] for b in loop["bars"]] == [1, 2, 3, 4]
    assert [b["display"] for b in loop["bars"]] == ["Am", "F", "C", "G"]


def test_outro_section_carries_the_fade_note(sheet):
    outro = serialize.sections(sheet)[-1]
    assert [b["number"] for b in outro["bars"]] == [19, 20, 21]
    assert outro["note"] == "to fade"


def test_without_a_loop_the_body_renders_verbatim_with_absolute_bars():
    plain = lead_sheet.build(FIXTURE, simplify=False)
    body = next(s for s in serialize.sections(plain) if s["kind"] == "body")
    assert body["repeat"] is False
    assert [b["number"] for b in body["bars"]] == list(range(2, 19))


def test_body_is_empty_not_broken_when_overrides_invert_it():
    # intro_end past outro_start leaves body_start > body_end. A musician can
    # drag two sliders into that state, so it has to serialise, not raise.
    inverted = lead_sheet.build(FIXTURE, intro_end=18, outro_start=5, simplify=False)
    body = next(s for s in serialize.sections(inverted) if s["kind"] == "body")
    assert body["bars"] == []


# ── cli_command ───────────────────────────────────────────────────────────────


def test_cli_command_omits_flags_left_on_auto():
    cmd = serialize.cli_command("out/demo", {"simplify": True, "bars_per_line": 4})
    assert cmd == "python3 real_book.py --out out/demo"


def test_cli_command_includes_structural_overrides():
    cmd = serialize.cli_command("out/demo", {
        "intro_end": 8, "outro_start": 60, "loop_len": 2,
        "simplify": True, "bars_per_line": 4,
    })
    assert "--intro-end 8" in cmd
    assert "--outro-start 60" in cmd
    assert "--loop-len 2" in cmd


def test_cli_command_quotes_titles_with_spaces():
    cmd = serialize.cli_command("out/demo", {"title": "D Lydian Soaring Guitar"})
    assert "--title 'D Lydian Soaring Guitar'" in cmd


def test_cli_command_renders_bpm_without_a_trailing_zero_tail():
    assert "--bpm 68" in serialize.cli_command("out/demo", {"bpm": 68.0})
    assert "--bpm 80.75" in serialize.cli_command("out/demo", {"bpm": 80.75})


def test_cli_command_carries_non_default_layout_flags():
    cmd = serialize.cli_command("out/demo", {"simplify": False, "bars_per_line": 8})
    assert "--no-simplify" in cmd
    assert "--bars-per-line 8" in cmd


# ── sheet_to_dict ─────────────────────────────────────────────────────────────


def test_sheet_to_dict_carries_the_metadata_the_header_needs(sheet):
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["title"] == "synthetic"
    assert d["key"] == "C Major"
    assert d["bpm"] == 120.0
    assert d["total_bars"] == 21
    assert d["bars_per_line"] == 4


def test_sheet_to_dict_reports_the_loop_as_an_object(sheet):
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["loop"] == {"length": 4, "chords": ["Am", "F", "C", "G"], "repeats": 4}


def test_sheet_to_dict_timecodes_the_departures(sheet):
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["departures"] == [
        {"bar": 18, "chord": "D#m7", "time": 34.0, "timecode": "0:34"},
    ]


def test_sheet_to_dict_includes_the_ascii_rendering(sheet):
    # The CLI and the browser render the same LeadSheet. Shipping the ASCII too
    # lets the page prove it rather than assert it.
    d = serialize.sheet_to_dict(
        sheet, bars_per_line=4, out_dir_arg="out/synthetic", overrides={},
    )
    assert d["ascii"] == lead_sheet.render_ascii(sheet, bars_per_line=4)
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
.venv/bin/python -m pytest tests/test_gui_serialize.py -q
```

Expected: collection error — `ImportError: cannot import name 'serialize' from 'gui'`.

- [ ] **Step 3: Write `gui/serialize.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_gui_serialize.py -q
```

Expected: 21 passed.

- [ ] **Step 5: Commit**

```bash
git add gui/serialize.py tests/test_gui_serialize.py
git commit -m "$(cat <<'EOF'
feat: serialise a LeadSheet into render-ready sections

render_ascii decides section order, bar membership, that a detected loop is
printed once as loop positions rather than absolute bars, and where the
repeat signs land. Leaving those decisions to the browser would have meant
two implementations of the same rules with nothing holding them together —
the page and the CLI could disagree about where the intro ends and neither
would be wrong on its own terms.

So the layout is computed server-side and app.js walks the result. The
inverted-body case is covered explicitly: dragging intro-end past
outro-start leaves body_start > body_end, which has to serialise as an empty
section rather than raise, because two sliders can reach that state.

cli_command emits only flags that depart from the default, which makes the
copyable command read as the list of the musician's disagreements with the
machine instead of a dump of every setting.
EOF
)"
```

---

### Task 4: `POST /api/sheet`

The endpoint the whole UI runs on. Also the security boundary: `out_dir` arrives from a browser and must not be able to address anything outside the active root.

**Files:**
- Modify: `gui/app.py`
- Test: `tests/test_gui_api.py`

**Interfaces:**
- Consumes: `gui.serialize.sheet_to_dict`, `gui.app._active_root`, `lead_sheet.build`.
- Produces: `POST /api/sheet` — body `{"out_dir": str, "overrides": {...}}`, response is `sheet_to_dict`'s dict. Failures are `422` with `{"detail": str}`.
- Override field names, exactly: `bpm`, `title`, `artist`, `intro_end`, `outro_start`, `loop_len`, `simplify`, `bars_per_line`. Task 5's `app.js` sends this object verbatim.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui_api.py`:

```python
# ── POST /api/sheet ───────────────────────────────────────────────────────────


def post_sheet(client, **overrides):
    return client.post(
        "/api/sheet", json={"out_dir": "synthetic", "overrides": overrides}
    )


def test_sheet_round_trips_the_fixture(client):
    res = post_sheet(client)
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "synthetic"
    assert body["total_bars"] == 21
    assert [s["kind"] for s in body["sections"]] == ["intro", "loop", "outro"]


def test_loop_len_override_reaches_build(client):
    body = post_sheet(client, loop_len=2).json()
    assert body["loop"]["length"] == 2


def test_intro_end_override_moves_the_body(client):
    body = post_sheet(client, intro_end=4).json()
    assert body["intro_end"] == 4
    assert body["body_start"] == 5


def test_outro_start_override_moves_the_body_end(client):
    body = post_sheet(client, outro_start=15).json()
    assert body["outro_start"] == 15
    assert body["body_end"] == 14


def test_title_and_artist_overrides_reach_the_header(client):
    body = post_sheet(client, title="Given", artist="Someone").json()
    assert body["title"] == "Given"
    assert body["artist"] == "Someone"


def test_bpm_override_reaches_the_header_and_the_command(client):
    body = post_sheet(client, bpm=60.0).json()
    assert body["bpm"] == 60.0
    assert body["detected_bpm"] == 120.0
    assert "--bpm 60" in body["cli_command"]


def test_simplify_false_renders_every_bar(client):
    body = post_sheet(client, simplify=False).json()
    assert body["loop"] is None
    assert [s["kind"] for s in body["sections"]] == ["intro", "body", "outro"]


def test_out_of_range_overrides_are_clamped_not_rejected(client):
    # lead_sheet clamps rather than validates so a slider can be dragged
    # anywhere. That contract has to survive the HTTP layer.
    res = post_sheet(client, intro_end=9999, outro_start=-5, loop_len=9999)
    assert res.status_code == 200
    body = res.json()
    assert 1 <= body["intro_end"] <= body["total_bars"]


def test_bars_per_line_of_zero_does_not_explode(client):
    res = post_sheet(client, bars_per_line=0)
    assert res.status_code == 200
    assert res.json()["bars_per_line"] == 1


def test_missing_track_is_a_422_not_a_500(client):
    res = client.post("/api/sheet", json={"out_dir": "no-such-track", "overrides": {}})
    assert res.status_code == 422
    assert "no-such-track" in res.json()["detail"]


def test_track_without_a_chart_names_the_command_to_run(tmp_path):
    # Analysed by analyze.py but not analyze_v3.py. The page should be able to
    # tell the user which step is missing instead of showing a stack trace.
    track = tmp_path / "half-done"
    track.mkdir()
    (track / "summary.json").write_text('{"tempo_bpm": 120}')
    app.state.out_root = tmp_path
    app.state.allow_example_fallback = False
    with TestClient(app) as c:
        res = c.post("/api/sheet", json={"out_dir": "half-done", "overrides": {}})
    assert res.status_code == 422
    assert "analyze_v3.py" in res.json()["detail"]


@pytest.mark.parametrize(
    "name", ["../secrets", "..", ".", "", "sub/dir", "/etc", "..\\windows"]
)
def test_path_traversal_is_refused(client, name):
    # out_dir arrives from a browser. A read-only chart viewer must not become
    # a file browser for the whole disk.
    res = client.post("/api/sheet", json={"out_dir": name, "overrides": {}})
    assert res.status_code == 422


def test_traversal_cannot_reach_a_real_directory_outside_the_root(client):
    # tests/fixtures is the root, so ../fixtures/synthetic resolves to a dir
    # that genuinely exists — rejection must come from the guard, not from the
    # target being absent.
    res = client.post(
        "/api/sheet", json={"out_dir": "../fixtures/synthetic", "overrides": {}}
    )
    assert res.status_code == 422


def test_response_carries_a_reproducing_cli_command(client):
    body = post_sheet(client, loop_len=2, intro_end=4).json()
    assert body["cli_command"].startswith("python3 real_book.py --out ")
    assert "--loop-len 2" in body["cli_command"]
    assert "--intro-end 4" in body["cli_command"]


def test_cli_command_points_at_a_repo_relative_path(client):
    body = post_sheet(client).json()
    assert "--out tests/fixtures/synthetic" in body["cli_command"]
```

- [ ] **Step 2: Run to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_gui_api.py -q
```

Expected: the new tests fail with 404 (route not defined); the 6 from Task 2 still pass.

- [ ] **Step 3: Add the request models, the guard, and the route to `gui/app.py`**

Add to the import block, after the existing FastAPI imports:

```python
from pydantic import BaseModel  # noqa: E402

import lead_sheet  # noqa: E402
from gui import serialize  # noqa: E402
```

Then append below the `api_tracks` route:

```python
class Overrides(BaseModel):
    """The full correction set. Every field is what the musician decided.

    None means "keep the heuristic" for the structural axes — that distinction
    is the product, so it is carried as an explicit null rather than a sentinel
    like 0 or -1 that lead_sheet would clamp into a real value.
    """

    bpm: float | None = None
    title: str = ""
    artist: str = ""
    intro_end: int | None = None
    outro_start: int | None = None
    loop_len: int | None = None
    simplify: bool = True
    bars_per_line: int = 4


class SheetRequest(BaseModel):
    out_dir: str
    overrides: Overrides = Overrides()


def _resolve_track(root: Path, name: str) -> Path:
    """Resolve a track name under `root`, refusing anything that escapes it.

    The name comes from a browser, so it is one path segment and nothing else.
    Without this, "../.." would turn a read-only chart viewer into a file
    browser for the whole disk.
    """
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise HTTPException(status_code=422, detail=f"invalid track name: {name!r}")
    root = Path(root).resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise HTTPException(
            status_code=422, detail=f"no analysed track named {name!r} in {root}"
        )
    return candidate


def _cli_out_arg(track_dir: Path) -> str:
    """The --out value to print, repo-relative when it can be."""
    try:
        return str(track_dir.relative_to(REPO_ROOT))
    except ValueError:
        return str(track_dir)


@app.post("/api/sheet")
def api_sheet(req: SheetRequest) -> dict:
    root, _ = _active_root()
    track_dir = _resolve_track(root, req.out_dir)
    ov = req.overrides

    # build() raises rather than exiting, precisely so this process survives a
    # half-analysed directory. Its messages already name the command to run, so
    # they are passed through verbatim for the page to show.
    try:
        sheet = lead_sheet.build(
            track_dir,
            bpm=ov.bpm,
            title=ov.title,
            artist=ov.artist,
            intro_end=ov.intro_end,
            outro_start=ov.outro_start,
            loop_len=ov.loop_len,
            simplify=ov.simplify,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return serialize.sheet_to_dict(
        sheet,
        bars_per_line=max(1, ov.bars_per_line),
        out_dir_arg=_cli_out_arg(track_dir),
        overrides=ov.model_dump(),
    )
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_gui_api.py -q
```

Expected: 26 passed.

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: all pass, no regressions in the original 39.

- [ ] **Step 6: Commit**

```bash
git add gui/app.py tests/test_gui_api.py
git commit -m "$(cat <<'EOF'
feat: add POST /api/sheet with clamped overrides and 422 error mapping

The endpoint the UI runs on: the full override set in, a whole rebuilt sheet
out, no session state on the server.

Two failure modes are mapped deliberately. A directory that has been through
analyze.py but not analyze_v3.py raises FileNotFoundError from build() with a
message naming the missing command; that message is passed through as a 422
so the page can print the fix instead of a stack trace, and so a mis-typed
track name cannot read as a server crash.

out_dir arrives from a browser, so it is constrained to a single path
segment resolved under the active root. Without the guard, "../.." would have
turned a read-only chart viewer into a file browser for the whole disk; the
test asserts rejection even when the traversal target genuinely exists, so a
passing result cannot come from the path merely being absent.

Out-of-range structural values are left to lead_sheet's clamping rather than
rejected at the schema, because a slider gets dragged to its end and the
musician should see the chart pinned to bar 1, not an error.
EOF
)"
```

---

### Task 5: The page — shell and chart rendering

Static shell plus enough JS to pick a track and draw the chart. Controls arrive in Task 6, styling in Task 7; this task ends with a readable, unstyled chart on screen.

**Files:**
- Modify: `gui/static/index.html` (replaces the Task 2 placeholder)
- Create: `gui/static/app.js`

**Interfaces:**
- Consumes: `GET /api/tracks`, `POST /api/sheet` from Tasks 2 and 4.
- Produces: DOM contract Task 7's CSS styles — `.sheet`, `.section`, `.section__head`, `.bars`, `.bar`, `.bar__num`, `.bar__chord`, `.chord`, `.bar__slash`, `.repeat--open`, `.repeat--close`, `.departures`, `.cli`, `.banner`, `.error`, and `id` hooks `track-picker`, `sheet-header`, `sheet-body`, `departures`, `cli-command`, `error-banner`, `example-banner`, `ascii-pane`.

- [ ] **Step 1: Write `gui/static/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lead Sheet</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <h1 class="topbar__title">Lead Sheet</h1>
    <p class="topbar__sub">Correct what the analysis got wrong. The chart redraws as you go.</p>
    <label class="topbar__picker">
      <span>Track</span>
      <select id="track-picker"></select>
    </label>
  </header>

  <p class="banner" id="example-banner" hidden></p>
  <p class="error" id="error-banner" hidden></p>

  <main class="layout">
    <aside class="controls" id="controls"></aside>

    <section class="sheet" id="sheet">
      <div class="sheet__header" id="sheet-header"></div>
      <div class="sheet__body" id="sheet-body"></div>
      <div class="departures" id="departures"></div>
      <pre class="ascii" id="ascii-pane" hidden></pre>
      <div class="cli">
        <code id="cli-command"></code>
        <button type="button" id="copy-cli" class="btn">Copy</button>
      </div>
    </section>
  </main>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `gui/static/app.js`**

```javascript
/* Lead sheet client.
 *
 * Deliberately thin. The server decides section order, which bars belong to
 * which section, and where repeat signs go, so everything here is either
 * reading a control or appending an element. The one piece of real logic is the
 * in-flight guard in refresh(): a slider drag fires far faster than a round
 * trip, and without it responses can land out of order and paint a stale chart
 * over a fresh one.
 */

const $ = (sel) => document.querySelector(sel);

const state = {
  track: null,
  overrides: {
    bpm: null,
    title: "",
    artist: "",
    intro_end: null,
    outro_start: null,
    loop_len: null,
    simplify: true,
    bars_per_line: 4,
  },
  sheet: null,
  pending: false,
  queued: false,
};

// ── Network ──────────────────────────────────────────────────────────────────

async function loadTracks() {
  const res = await fetch("/api/tracks");
  const data = await res.json();
  const picker = $("#track-picker");
  picker.replaceChildren();

  if (!data.tracks.length) {
    showError(
      `No analysed tracks in ${data.out_root}. Run: ${data.analyze_hint}`
    );
    return;
  }

  for (const track of data.tracks) {
    const opt = document.createElement("option");
    opt.value = track.name;
    opt.textContent = track.has_chart ? track.name : `${track.name} (no chord chart)`;
    picker.appendChild(opt);
  }

  const banner = $("#example-banner");
  banner.hidden = !data.is_example_fallback;
  if (data.is_example_fallback) {
    banner.textContent =
      "Showing the bundled example — nothing analysed in your out/ directory yet.";
  }

  state.track = data.tracks[0].name;
  picker.value = state.track;
  await refresh();
}

async function refresh() {
  if (!state.track) return;
  if (state.pending) {
    state.queued = true;
    return;
  }
  state.pending = true;
  try {
    const res = await fetch("/api/sheet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ out_dir: state.track, overrides: state.overrides }),
    });
    const data = await res.json();
    if (!res.ok) {
      // Keep the last good chart on screen. A 422 usually means one control is
      // wrong, and blanking the page would lose the context needed to fix it.
      showError(data.detail || `${res.status} ${res.statusText}`);
      return;
    }
    clearError();
    state.sheet = data;
    render(data);
  } catch (err) {
    showError(String(err));
  } finally {
    state.pending = false;
    if (state.queued) {
      state.queued = false;
      refresh();
    }
  }
}

// ── Rendering ────────────────────────────────────────────────────────────────

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderHeader(data) {
  const head = $("#sheet-header");
  head.replaceChildren();
  head.appendChild(el("h2", "sheet__title", data.title || "Untitled"));
  if (data.artist) head.appendChild(el("p", "sheet__artist", data.artist));

  const meta = el("p", "sheet__meta");
  meta.appendChild(el("span", "meta__item", `Key: ${data.key}`));
  meta.appendChild(el("span", "meta__item", `♩= ${Math.round(data.bpm)}`));
  meta.appendChild(el("span", "meta__item", "4/4"));
  meta.appendChild(el("span", "meta__item", `${data.total_bars} bars`));
  meta.appendChild(el("span", "meta__item", data.duration_timecode));
  head.appendChild(meta);
}

function barCell(cell) {
  const node = el("div", "bar");
  if (cell.display === "%") node.classList.add("bar--empty");
  node.appendChild(el("span", "bar__num", String(cell.number)));

  const chord = el("span", "bar__chord");
  cell.display.split(" / ").forEach((part, i) => {
    if (i > 0) chord.appendChild(el("span", "bar__slash", "/"));
    chord.appendChild(el("span", "chord", part));
  });
  node.appendChild(chord);
  return node;
}

function renderSection(section, barsPerLine) {
  const node = el("article", `section section--${section.kind}`);

  const head = el("div", "section__head");
  head.appendChild(el("h3", "section__label", section.label));
  if (section.detail) head.appendChild(el("span", "section__detail", section.detail));
  node.appendChild(head);

  const row = el("div", "bars-row");
  if (section.repeat) row.appendChild(el("span", "repeat repeat--open", "‖:"));

  const grid = el("div", "bars");
  grid.style.setProperty("--bars-per-line", barsPerLine);
  section.bars.forEach((cell) => grid.appendChild(barCell(cell)));
  row.appendChild(grid);

  if (section.repeat) row.appendChild(el("span", "repeat repeat--close", ":‖"));
  node.appendChild(row);

  if (section.note) node.appendChild(el("p", "section__note", `(${section.note})`));
  if (!section.bars.length) {
    node.appendChild(
      el("p", "section__note", "(no bars — check the intro and outro controls)")
    );
  }
  return node;
}

function renderDepartures(data) {
  const wrap = $("#departures");
  wrap.replaceChildren();
  if (!data.departures.length) return;

  wrap.appendChild(
    el("h3", "departures__label", "Harmonic departures")
  );
  wrap.appendChild(
    el("p", "departures__hint", "Bars whose root sits outside the loop's vocabulary.")
  );

  const list = el("ul", "departures__list");
  data.departures.forEach((d) => {
    const item = el("li", "departure");
    item.appendChild(el("span", "departure__bar", `bar ${d.bar}`));
    item.appendChild(el("span", "departure__time", d.timecode));
    item.appendChild(el("span", "departure__chord", d.chord));
    list.appendChild(item);
  });
  wrap.appendChild(list);
}

function render(data) {
  renderHeader(data);

  const body = $("#sheet-body");
  body.replaceChildren();
  data.sections.forEach((s) => body.appendChild(renderSection(s, data.bars_per_line)));

  renderDepartures(data);
  $("#cli-command").textContent = data.cli_command;
  $("#ascii-pane").textContent = data.ascii;
}

// ── Errors ───────────────────────────────────────────────────────────────────

function showError(message) {
  const banner = $("#error-banner");
  banner.textContent = message;
  banner.hidden = false;
}

function clearError() {
  $("#error-banner").hidden = true;
}

// ── Wiring ───────────────────────────────────────────────────────────────────

$("#track-picker").addEventListener("change", (e) => {
  state.track = e.target.value;
  refresh();
});

$("#copy-cli").addEventListener("click", async () => {
  const button = $("#copy-cli");
  await navigator.clipboard.writeText($("#cli-command").textContent);
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = "Copy"; }, 1200);
});

loadTracks();
```

- [ ] **Step 3: Start the server against the bundled example**

```bash
.venv/bin/python gui/app.py --out-root examples --port 8123
```

Run it in the background; leave it up for Tasks 6 and 7.

- [ ] **Step 4: Verify in a browser**

Open `http://127.0.0.1:8123/`. Confirm by reading the page (a screenshot is fine — `examples/demo` is Dean's own music; **never** screenshot `out/kitchen`):

- the track picker holds `demo`
- the header reads `D Lydian Soaring Guitar`, `Key: C# Minor`, `♩= 136`, `73 bars`, `2:08`
- three sections appear: Intro (1 bar, `Dmaj7`), Main body (`3-bar loop, repeats ~19×`, with `‖:` and `:‖`), Outro
- the departures list has 11 entries
- the CLI line reads `python3 real_book.py --out examples/demo`

- [ ] **Step 5: Check the console is clean**

Read the browser console. Expected: no errors, no failed requests.

- [ ] **Step 6: Commit**

```bash
git add gui/static/index.html gui/static/app.js
git commit -m "$(cat <<'EOF'
feat: render the chart as real bar cells rather than an ASCII dump

The page walks the server's section list and appends elements: bars are
cells, the repeat signs around a detected loop are their own elements, and
"C / G" is split so the two chords and the slash can be styled apart. Piping
render_ascii into a <pre> would have been fewer lines and would have made
every one of those a fixed-width character nobody can style or print well.

refresh() guards on an in-flight request and replays the last one on
completion. A slider drag fires many times faster than a round trip, and
without the guard a slow early response can land after a fast later one and
paint a stale chart over a fresh one.

A failed rebuild leaves the previous chart on screen and shows the message
above it. Blanking the page on a 422 would take away the context the
musician needs to see which control they just broke.
EOF
)"
```

---

### Task 6: The correction controls

The product. Each structural axis is an *auto vs. mine* pair: leave it on auto and the machine's guess is displayed, take it over and the chart redraws against your reading.

**Files:**
- Modify: `gui/static/index.html`
- Modify: `gui/static/app.js`

**Interfaces:**
- Consumes: the `Overrides` field names from Task 4.
- Produces: control ids `c-intro-end`, `c-outro-start`, `c-loop-len`, `c-bpm`, `c-title`, `c-artist`, `c-bars-per-line`, `c-simplify`, `c-ascii`; each structural control paired with an auto checkbox `auto-intro-end`, `auto-outro-start`, `auto-loop-len`, `auto-bpm`. Task 7's CSS styles `.control`, `.control__head`, `.control__auto`, `.control__row`, `.control__value`, `.suggestion`.

- [ ] **Step 1: Replace the empty `<aside class="controls" id="controls"></aside>` in `index.html`**

```html
    <aside class="controls">
      <h2 class="controls__title">Corrections</h2>

      <p class="suggestion" id="half-time" hidden></p>

      <div class="control">
        <div class="control__head">
          <label for="c-intro-end">Intro ends at bar</label>
          <label class="control__auto">
            <input type="checkbox" id="auto-intro-end" checked> auto
          </label>
        </div>
        <div class="control__row">
          <input type="range" id="c-intro-end" min="1" max="64" value="1" disabled>
          <output class="control__value" id="v-intro-end">1</output>
        </div>
      </div>

      <div class="control">
        <div class="control__head">
          <label for="c-outro-start">Outro starts at bar</label>
          <label class="control__auto">
            <input type="checkbox" id="auto-outro-start" checked> auto
          </label>
        </div>
        <div class="control__row">
          <input type="range" id="c-outro-start" min="1" max="64" value="1" disabled>
          <output class="control__value" id="v-outro-start">—</output>
        </div>
      </div>

      <div class="control">
        <div class="control__head">
          <label for="c-loop-len">Loop length</label>
          <label class="control__auto">
            <input type="checkbox" id="auto-loop-len" checked> auto
          </label>
        </div>
        <div class="control__row">
          <input type="range" id="c-loop-len" min="1" max="16" value="4" disabled>
          <output class="control__value" id="v-loop-len">—</output>
        </div>
      </div>

      <div class="control">
        <div class="control__head">
          <label for="c-bpm">Tempo</label>
          <label class="control__auto">
            <input type="checkbox" id="auto-bpm" checked> auto
          </label>
        </div>
        <div class="control__row">
          <input type="number" id="c-bpm" min="20" max="300" step="0.25" disabled>
          <span class="control__value">BPM</span>
        </div>
        <p class="control__note">Cosmetic — reaches the header only.</p>
      </div>

      <div class="control">
        <label class="control__head" for="c-title">Title</label>
        <input type="text" id="c-title" placeholder="from the filename">
      </div>

      <div class="control">
        <label class="control__head" for="c-artist">Artist</label>
        <input type="text" id="c-artist" placeholder="—">
      </div>

      <div class="control">
        <label class="control__head" for="c-bars-per-line">Bars per line</label>
        <select id="c-bars-per-line">
          <option value="2">2</option>
          <option value="4" selected>4</option>
          <option value="8">8</option>
        </select>
      </div>

      <div class="control control--toggle">
        <label><input type="checkbox" id="c-simplify" checked> Collapse repeats into a loop</label>
      </div>

      <div class="control control--toggle">
        <label><input type="checkbox" id="c-ascii"> Show the ASCII chart</label>
      </div>
    </aside>
```

- [ ] **Step 2: Add the control wiring to `app.js`**

Insert before the `loadTracks();` call at the bottom, after the existing listeners:

```javascript
// ── Controls ─────────────────────────────────────────────────────────────────

/* Each structural axis is a pair: an auto checkbox and a value.
 *
 * Auto sends null, which is what tells lead_sheet to keep its heuristic, and
 * the slider then displays whatever the machine decided. Unchecking hands the
 * axis to the musician, seeded with the machine's value so the first move is a
 * nudge rather than a jump. That difference — machine guess versus human
 * decision — is the whole point of the tool, so it is a visible mode, not an
 * inferred one.
 */
const AXES = [
  { key: "intro_end",   auto: "#auto-intro-end",   input: "#c-intro-end",   value: "#v-intro-end" },
  { key: "outro_start", auto: "#auto-outro-start", input: "#c-outro-start", value: "#v-outro-start" },
  { key: "loop_len",    auto: "#auto-loop-len",    input: "#c-loop-len",    value: "#v-loop-len" },
];

function readAxis(axis) {
  const isAuto = $(axis.auto).checked;
  $(axis.input).disabled = isAuto;
  state.overrides[axis.key] = isAuto ? null : Number($(axis.input).value);
}

AXES.forEach((axis) => {
  $(axis.auto).addEventListener("change", () => {
    if (!$(axis.auto).checked && state.sheet) {
      // Seed from what the machine decided, so taking over never moves the chart
      // on its own — the first change the musician sees is one they made.
      const seed = axis.key === "loop_len"
        ? (state.sheet.loop ? state.sheet.loop.length : 4)
        : state.sheet[axis.key];
      if (seed != null) $(axis.input).value = seed;
    }
    readAxis(axis);
    refresh();
  });
  $(axis.input).addEventListener("input", () => {
    readAxis(axis);
    refresh();
  });
});

$("#auto-bpm").addEventListener("change", () => {
  const isAuto = $("#auto-bpm").checked;
  $("#c-bpm").disabled = isAuto;
  if (!isAuto && state.sheet) $("#c-bpm").value = state.sheet.bpm.toFixed(2);
  state.overrides.bpm = isAuto ? null : Number($("#c-bpm").value);
  refresh();
});

$("#c-bpm").addEventListener("input", () => {
  state.overrides.bpm = $("#auto-bpm").checked ? null : Number($("#c-bpm").value);
  refresh();
});

$("#c-title").addEventListener("input", (e) => {
  state.overrides.title = e.target.value;
  refresh();
});

$("#c-artist").addEventListener("input", (e) => {
  state.overrides.artist = e.target.value;
  refresh();
});

$("#c-bars-per-line").addEventListener("change", (e) => {
  state.overrides.bars_per_line = Number(e.target.value);
  refresh();
});

$("#c-simplify").addEventListener("change", (e) => {
  state.overrides.simplify = e.target.checked;
  refresh();
});

$("#c-ascii").addEventListener("change", (e) => {
  $("#ascii-pane").hidden = !e.target.checked;
});
```

- [ ] **Step 3: Add the control-syncing render step to `app.js`**

Add this function next to the other render helpers:

```javascript
function syncControls(data) {
  // Sliders are bounded by the chart that came back. lead_sheet clamps anyway,
  // so this is about making the range mean something, not about validation.
  $("#c-intro-end").max = data.total_bars;
  $("#c-outro-start").max = data.total_bars;

  if ($("#auto-intro-end").checked) {
    $("#c-intro-end").value = data.intro_end;
    $("#v-intro-end").textContent = data.intro_end;
  } else {
    $("#v-intro-end").textContent = $("#c-intro-end").value;
  }

  if ($("#auto-outro-start").checked) {
    $("#c-outro-start").value = data.outro_start ?? data.total_bars;
    $("#v-outro-start").textContent = data.outro_start ?? "none";
  } else {
    $("#v-outro-start").textContent = $("#c-outro-start").value;
  }

  const loopLen = data.loop ? data.loop.length : null;
  if ($("#auto-loop-len").checked) {
    if (loopLen) $("#c-loop-len").value = loopLen;
    $("#v-loop-len").textContent = loopLen ?? "none";
  } else {
    $("#v-loop-len").textContent = $("#c-loop-len").value;
  }

  if ($("#auto-bpm").checked) $("#c-bpm").value = data.bpm.toFixed(2);

  const suggestion = $("#half-time");
  suggestion.replaceChildren();
  suggestion.hidden = data.half_time_suggestion == null;
  if (data.half_time_suggestion != null) {
    const bpm = data.half_time_suggestion;
    suggestion.appendChild(
      el("span", "", `Half-time feel suspected — ${Math.round(bpm)} BPM may be the true pulse.`)
    );
    const apply = el("button", "btn btn--inline", `Use ${Math.round(bpm)}`);
    apply.type = "button";
    apply.addEventListener("click", () => {
      $("#auto-bpm").checked = false;
      $("#c-bpm").disabled = false;
      $("#c-bpm").value = bpm.toFixed(2);
      state.overrides.bpm = bpm;
      refresh();
    });
    suggestion.appendChild(apply);
  }
}
```

And call it from `render()` — the function becomes:

```javascript
function render(data) {
  renderHeader(data);

  const body = $("#sheet-body");
  body.replaceChildren();
  data.sections.forEach((s) => body.appendChild(renderSection(s, data.bars_per_line)));

  renderDepartures(data);
  syncControls(data);
  $("#cli-command").textContent = data.cli_command;
  $("#ascii-pane").textContent = data.ascii;
}
```

- [ ] **Step 4: Verify the correction loop in the browser**

Reload `http://127.0.0.1:8123/`. Confirm each of these, reading the page after each change:

1. Uncheck **auto** on Loop length, set it to **2**. The Main body section becomes `Dmaj7 │ Emaj7` and the detail reads `2-bar loop, repeats ~29×`. This is the spec's headline example.
2. The CLI line now reads `python3 real_book.py --out examples/demo --loop-len 2`.
3. Uncheck **auto** on Intro ends at bar, drag to **8**. The Intro section grows to 8 bars and the body starts later.
4. The half-time suggestion is visible; clicking **Use 68** sets the header to `♩= 68` and adds `--bpm 68` to the CLI line.
5. Typing in Title changes the header live.
6. Unchecking **Collapse repeats into a loop** replaces the loop with every body bar and removes the repeat signs.
7. Setting Bars per line to 8 rewraps the grid.
8. Ticking **Show the ASCII chart** reveals a pane matching what `real_book.py` prints.

- [ ] **Step 5: Verify the CLI command actually reproduces the chart**

The copyable command is the whole persistence story, so it has to be true.

```bash
.venv/bin/python real_book.py --out examples/demo --loop-len 2 | head -20
```

Expected: a `2-bar loop` main body reading `Dmaj7 │ Emaj7`, matching what the page shows.

- [ ] **Step 6: Check the console is clean**

Read the browser console. Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add gui/static/index.html gui/static/app.js
git commit -m "$(cat <<'EOF'
feat: add the correction controls for every structural axis

Each structural axis is an explicit auto-or-mine pair rather than a plain
input. Auto sends null, which is what tells lead_sheet to keep its
heuristic; a plain input would have had to encode "no opinion" as 0 or -1,
both of which lead_sheet clamps into a real bar number — so the machine's
guess would have been silently replaced by a human decision nobody made.

Taking an axis over seeds it from the value the machine produced, so
unchecking auto never moves the chart by itself. Seeding from the control's
own default would have made the first click look like a correction the
musician did not ask for.

The half-time suggestion gets a button rather than being applied
automatically, matching lead_sheet's own reasoning: silently halving a
correct 136 BPM reading is worse than leaving an ambiguous one alone.

The demo this exists for: loop length auto gives a 3-bar loop on the bundled
track; setting it to 2 gives Dmaj7 | Emaj7, which is what the music is doing.
EOF
)"
```

---

### Task 7: Styling and the print stylesheet

The portfolio surface. A hiring manager forms an opinion here before reading a line of Python.

**Files:**
- Create: `gui/static/style.css`

**Interfaces:**
- Consumes: the class and id contract from Tasks 5 and 6.
- Produces: nothing downstream.

- [ ] **Step 1: Write `gui/static/style.css`**

```css
/* Lead sheet.
 *
 * The reference is a Real Book page: cream stock, engraved headings, chords in
 * a face you can read across a music stand. The screen layout puts corrections
 * on the left and the chart on the right; print drops the corrections entirely,
 * because what gets printed is the chart the musician just agreed with.
 */

:root {
  --paper: #faf6ec;
  --ink: #1c1a17;
  --ink-soft: #6b6355;
  --rule: #d8cfba;
  --accent: #8a5a2b;
  --flag: #a8442a;
  --panel: #f3ecdd;
  --radius: 3px;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --mono: "SF Mono", "JetBrains Mono", "IBM Plex Mono", Menlo, monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--serif);
  line-height: 1.5;
}

/* ── Top bar ───────────────────────────────────────────────────────────────── */

.topbar {
  display: flex;
  align-items: baseline;
  gap: 1.25rem;
  flex-wrap: wrap;
  padding: 1.25rem 1.75rem;
  border-bottom: 1px solid var(--rule);
}

.topbar__title {
  margin: 0;
  font-size: 1.4rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.topbar__sub {
  margin: 0;
  flex: 1;
  color: var(--ink-soft);
  font-size: 0.92rem;
}

.topbar__picker {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
}

select, input[type="text"], input[type="number"] {
  font: inherit;
  font-size: 0.95rem;
  padding: 0.3rem 0.45rem;
  background: #fff;
  color: var(--ink);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}

/* ── Banners ───────────────────────────────────────────────────────────────── */

.banner, .error {
  margin: 0;
  padding: 0.7rem 1.75rem;
  font-size: 0.9rem;
}

.banner {
  background: var(--panel);
  border-bottom: 1px solid var(--rule);
  color: var(--ink-soft);
}

.error {
  background: #f7e4de;
  border-bottom: 1px solid #e0bdb0;
  color: var(--flag);
  font-family: var(--mono);
  font-size: 0.85rem;
  white-space: pre-wrap;
}

/* ── Layout ────────────────────────────────────────────────────────────────── */

.layout {
  display: grid;
  grid-template-columns: 17rem minmax(0, 1fr);
  gap: 2rem;
  padding: 1.75rem;
  align-items: start;
}

@media (max-width: 60rem) {
  .layout { grid-template-columns: 1fr; }
}

/* ── Controls ──────────────────────────────────────────────────────────────── */

.controls {
  position: sticky;
  top: 1.75rem;
  padding: 1.1rem;
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}

.controls__title {
  margin: 0 0 1rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-soft);
}

.control { margin-bottom: 1.1rem; }

.control__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem;
  font-size: 0.9rem;
  margin-bottom: 0.35rem;
}

.control__auto {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.control__row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.control__row input[type="range"] { flex: 1; min-width: 0; }
.control__row input[type="number"] { width: 6rem; }

.control__value {
  min-width: 2.5rem;
  font-family: var(--mono);
  font-size: 0.85rem;
  color: var(--accent);
}

.control__note {
  margin: 0.3rem 0 0;
  font-size: 0.75rem;
  color: var(--ink-soft);
}

.control input[type="text"] { width: 100%; }

.control--toggle { font-size: 0.9rem; }
.control--toggle label { display: flex; align-items: center; gap: 0.45rem; }

input:disabled { opacity: 0.45; }

.suggestion {
  margin: 0 0 1rem;
  padding: 0.6rem 0.7rem;
  background: #fff;
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  font-size: 0.82rem;
  color: var(--ink-soft);
}

.btn {
  font: inherit;
  font-size: 0.8rem;
  padding: 0.25rem 0.7rem;
  background: var(--ink);
  color: var(--paper);
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
}

.btn:hover { background: var(--accent); }
.btn--inline { margin-left: 0.5rem; }

/* ── The sheet ─────────────────────────────────────────────────────────────── */

.sheet {
  padding: 2rem 2.25rem;
  background: #fff;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  box-shadow: 0 1px 3px rgba(28, 26, 23, 0.06);
}

.sheet__header {
  text-align: center;
  padding-bottom: 1.1rem;
  margin-bottom: 1.6rem;
  border-bottom: 2px solid var(--ink);
}

.sheet__title {
  margin: 0;
  font-size: 1.7rem;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

.sheet__artist {
  margin: 0.25rem 0 0;
  color: var(--ink-soft);
  font-style: italic;
}

.sheet__meta {
  margin: 0.6rem 0 0;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 1.25rem;
  font-family: var(--mono);
  font-size: 0.82rem;
  color: var(--ink-soft);
}

/* ── Sections ──────────────────────────────────────────────────────────────── */

.section { margin-bottom: 1.9rem; break-inside: avoid; }

.section__head {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  margin-bottom: 0.55rem;
}

.section__label {
  margin: 0;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--accent);
}

.section__detail {
  font-size: 0.78rem;
  font-family: var(--mono);
  color: var(--ink-soft);
}

.section__note {
  margin: 0.45rem 0 0;
  font-size: 0.8rem;
  font-style: italic;
  color: var(--ink-soft);
}

.bars-row {
  display: flex;
  align-items: stretch;
  gap: 0.35rem;
}

.bars {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(var(--bars-per-line, 4), minmax(0, 1fr));
  border-top: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink);
}

/* Interior bar lines only — the outer edges are the section's own rules, or the
   repeat signs when there is a repeat. */
.bar {
  position: relative;
  min-height: 3.4rem;
  padding: 1.15rem 0.6rem 0.5rem;
  border-left: 1px solid var(--ink);
  display: flex;
  align-items: center;
  justify-content: center;
}

.bar:first-child { border-left: none; }
.bars > .bar:nth-child(n) { border-left: 1px solid var(--ink); }
.bars > .bar:first-child { border-left: none; }

.bar__num {
  position: absolute;
  top: 0.25rem;
  left: 0.4rem;
  font-family: var(--mono);
  font-size: 0.62rem;
  color: var(--rule);
}

.bar__chord {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  font-size: 1.05rem;
  letter-spacing: 0.01em;
}

.bar__slash { color: var(--rule); }
.bar--empty .chord { color: var(--rule); }

.repeat {
  display: flex;
  align-items: center;
  font-size: 1.5rem;
  line-height: 1;
  color: var(--ink);
}

/* ── Departures ────────────────────────────────────────────────────────────── */

.departures {
  margin-top: 2rem;
  padding-top: 1.1rem;
  border-top: 1px solid var(--rule);
}

.departures__label {
  margin: 0;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--accent);
}

.departures__hint {
  margin: 0.2rem 0 0.7rem;
  font-size: 0.82rem;
  color: var(--ink-soft);
}

.departures__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: 0.3rem 1rem;
}

.departure {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  font-family: var(--mono);
  font-size: 0.82rem;
}

.departure__bar { color: var(--ink-soft); }
.departure__time { color: var(--rule); }
.departure__chord { color: var(--ink); }

/* ── ASCII pane + CLI line ─────────────────────────────────────────────────── */

.ascii {
  margin: 1.75rem 0 0;
  padding: 1rem;
  overflow-x: auto;
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  font-family: var(--mono);
  font-size: 0.72rem;
  line-height: 1.35;
}

.cli {
  margin-top: 1.75rem;
  padding-top: 1rem;
  border-top: 1px solid var(--rule);
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.cli code {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  white-space: nowrap;
  font-family: var(--mono);
  font-size: 0.78rem;
  color: var(--ink-soft);
}

/* ── Print ─────────────────────────────────────────────────────────────────── */

@media print {
  @page { margin: 1.6cm; }

  body { background: #fff; color: #000; }

  .topbar,
  .controls,
  .banner,
  .error,
  .cli,
  .ascii { display: none !important; }

  .layout {
    display: block;
    padding: 0;
  }

  .sheet {
    padding: 0;
    border: none;
    box-shadow: none;
  }

  .section { break-inside: avoid; }
  .section__label, .departures__label { color: #000; }
  .bar__num { color: #999; }
}
```

- [ ] **Step 2: Verify on screen**

Reload `http://127.0.0.1:8123/`. Confirm: cream page, centred chart header with a rule under it, bar cells with interior bar lines only, repeat signs flanking the loop, departures in a multi-column list, controls in a sticky panel on the left.

- [ ] **Step 3: Verify the print layout**

Open the browser's print preview (or emulate the print media type). Confirm: no top bar, no controls panel, no CLI line, no ASCII pane; the chart fills the page, black on white, and sections are not split across a page break.

- [ ] **Step 4: Verify the narrow layout**

Resize the viewport to 375 px wide. Confirm the layout collapses to a single column and nothing overflows horizontally.

- [ ] **Step 5: Commit**

```bash
git add gui/static/style.css
git commit -m "$(cat <<'EOF'
style: engrave the chart, and give it a print stylesheet

The reference is a Real Book page, so bars get interior bar lines only with
the section's own rules closing the ends, chord names sit in a serif face at
reading size, and the repeat signs flank the grid as their own marks rather
than characters inside a cell.

The print rules drop the top bar, the corrections panel, the ASCII pane and
the CLI line. Printing them would put a slider and a shell command on a
sheet someone is reading from a music stand — and sections carry
break-inside: avoid so a four-bar phrase is never split across a page.
EOF
)"
```

---

### Task 8: Documentation and full verification

Ends the branch: README updated, complete CI-equivalent run locally, spec's open questions marked resolved.

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-28-lead-sheet-gui-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing downstream.

- [ ] **Step 1: Add the GUI rows to the README script table**

After the `real_book.py` row, insert:

```markdown
| `gui/app.py` | `--out-root` | Local web GUI over the lead sheet: pick an analysed track, override the detected intro, outro, loop length, tempo and titles, and watch the chart redraw. Needs `requirements-gui.txt` |
```

And after the `lead_sheet.py` row, insert:

```markdown
| `gui/serialize.py` | — | Shared module behind `gui/app.py`: turns a `LeadSheet` into the JSON the page draws, and into the `real_book.py` command that reproduces it |
```

- [ ] **Step 2: Add the GUI section to the README**

Insert after the "What each script does" table, before "Output locations":

```markdown
## The lead sheet GUI

The structural analysis is a set of heuristics, and on real music they are
visibly wrong — the intro detector is "first bar unlike the dominant chord,
minus one", which calls a one-bar intro on a track that has eight. The GUI
exists so disagreeing with it is fast:

```bash
python3 -m pip install -r requirements-gui.txt
python3 gui/app.py
```

Then open http://127.0.0.1:8000. Pick a track, and every structural axis has an
**auto** toggle: leave it on and you see what the analysis decided, turn it off
and you see what you decided. The chart redraws on each change — no re-analysis
runs, because `lead_sheet.build()` only reads two text files.

`gui/app.py --out-root <dir>` points it at a different directory of analysed
tracks. With no `--out-root` and nothing analysed in `out/` yet, it serves the
bundled example in `examples/` so there is something to look at on a fresh
clone.

Nothing is written back. When a correction is right, the page shows the
`real_book.py` command that reproduces it, so it survives in your shell history
rather than in a state file this repo would then have to keep in sync.

The web dependencies are deliberately *not* in `requirements.txt` — the analysis
scripts never import them, and an install that only wants tempo and chords
should not pull an ASGI server.
```

- [ ] **Step 3: Record the resolved open questions in the spec**

Replace the "Open questions" section of `docs/superpowers/specs/2026-07-28-lead-sheet-gui-design.md` with:

```markdown
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
```

- [ ] **Step 4: Run the complete CI equivalent locally**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: every test passes.

```bash
.venv/bin/python -c "import paths, modes, lead_sheet" && .venv/bin/python -c "import gui.app" && echo "imports ok"
```

Expected: `imports ok`.

```bash
for f in analyze.py analyze_v2.py analyze_v3.py melody.py xml_analyze.py \
         xml_aligned.py xml_guitars.py generate_previews.py \
         splice_transitions.py real_book.py modal_prior.py gui/app.py; do
  .venv/bin/python "$f" --help > /dev/null || echo "FAILED: $f"
done; echo "help check done"
```

Expected: `help check done` with no FAILED lines.

- [ ] **Step 5: Verify no personal paths entered the branch**

```bash
git log -p main..HEAD | grep -n "/Users/" ; echo "exit=$?"
```

Expected: no output, `exit=1`.

- [ ] **Step 6: Confirm `lead_sheet.py` was never touched**

```bash
git diff --stat main..HEAD -- lead_sheet.py analyze_v2.py ; echo "exit=$?"
```

Expected: no output — neither file changed, so the golden-output protocol never applied.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/superpowers/specs/2026-07-28-lead-sheet-gui-design.md
git commit -m "$(cat <<'EOF'
docs: document the GUI and record the resolved open questions

The README's setup section installs requirements.txt only, so someone
following it and then running gui/app.py would have hit ModuleNotFoundError
with nothing pointing at requirements-gui.txt. The new section names the
install, the entry point, the --out-root flag and the examples/ fallback.

The spec's three open questions are answered in place rather than left
open, since a future session reading it as a cold-start handoff would
otherwise re-litigate decisions that are now implemented.
EOF
)"
```

---

## Self-Review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| `gui/app.py` serving `GET /` | 2 |
| `GET /api/tracks` listing analysed `out/*` | 2 |
| `POST /api/sheet` taking `{out_dir, overrides}` | 4 |
| Correction axes: intro end, outro start, loop length, bars-per-line, title/artist | 6 |
| Tempo displayed and overridable but cosmetic | 6 (labelled "Cosmetic — reaches the header only") |
| Bars as real cells, styled repeat signs, section headings, departures list | 5, 7 |
| Print stylesheet | 7 |
| No `out/` dirs → empty state naming the `analyze.py` command | 5 (`loadTracks` uses `analyze_hint`) |
| Missing `chord_chart_v3.txt` → the `analyze_v3.py` command in the page | 4 (422 passes `build()`'s message through), 5 (error banner) |
| `build()` raising → 422, last good chart stays on screen | 4, 5 |
| Round-trip test against `tests/fixtures/synthetic` | 4 |
| Override plumbing test: `loop_len: 2` returns a 2-bar loop | 4 |
| Error mapping test: nonexistent dir → 422 not 500 | 4 |
| Vanilla frontend, no build step | 5, 6, 7 |
| Stateless server, no session | 4 |
| Bundled demo must be Dean's own music | 1 |
| `out/kitchen` never committed or screenshotted | Global constraints; verification uses `examples/demo` |
| `analyze_v2.py` untouched | Global constraints; asserted in 8 |
| CI stays green | 2 (workflow updated), 8 (full local run) |

**Placeholder scan:** every code step carries complete file contents or an exact insertion. No "TBD", no "add error handling", no "similar to Task N".

**Type consistency checked:** `list_tracks` returns `[{"name", "has_chart"}]` in Task 2 and is consumed with those keys in Task 5. `sections()` emits `kind/label/detail/repeat/note/bars` in Task 3 and `renderSection` reads exactly those in Task 5. `Overrides` field names in Task 4 match `state.overrides` keys in Task 5 and the `overrides.get(...)` keys in Task 3's `cli_command`. `sheet_to_dict` emits `loop.length` (not `loop_len`), and Task 6's `syncControls` reads `data.loop.length`. `resolve_out_root(configured, allow_fallback)` is defined and called with two positional arguments in both places.
