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
