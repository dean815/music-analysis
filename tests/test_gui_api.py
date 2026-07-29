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
