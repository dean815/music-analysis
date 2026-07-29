"""Guards for the stereo-width metrics in analyze.py.

Three inputs have no meaningful width to report, and each used to produce
something worse than a null:

  - mono            IndexError on y_stereo[:, 1] — the whole run died, even though
                    tempo, key, chords and structure would all have been fine
  - dual-mono       side signal is exactly zero, so the dB ratio is -inf
  - silent channel  corrcoef divides by a zero standard deviation, giving nan

The last two reached summary.json as bare `-Infinity` / `NaN` tokens. Python's
json module reads those back without complaint, which is why they survived: the
repo's own tooling never noticed. Other consumers disagree — JavaScript's
JSON.parse raises, and jq silently converts -Infinity to -1.8e308, a
plausible-looking number that is not the measurement. So the JSON validity test
below parses with parse_constant, which is what makes those tokens visible.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np
import pytest
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import analyze  # noqa: E402

SR = 44100
CLIP_SECONDS = 4.0


def _clicks() -> np.ndarray:
    times = np.arange(0.0, CLIP_SECONDS, 60.0 / 135)
    return librosa.clicks(times=times, sr=SR, length=int(CLIP_SECONDS * SR)).astype(np.float32)


def _strict_loads(raw: str):
    """json.loads that refuses Infinity/-Infinity/NaN instead of accepting them."""
    def reject(token: str):
        raise ValueError(f"non-JSON token in output: {token}")

    return json.loads(raw, parse_constant=reject)


# ── finite_or_none ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [np.inf, -np.inf, np.nan])
def test_non_finite_becomes_none(value):
    assert analyze.finite_or_none(value) is None


@pytest.mark.parametrize("value", [0.0, -1.0, 1.0, -120.5])
def test_finite_values_pass_through(value):
    assert analyze.finite_or_none(value) == pytest.approx(value)


# ── stereo_metrics ───────────────────────────────────────────────────────────


def test_mono_reports_neither_metric():
    """The crash case. A single-channel array has no second channel to compare."""
    mono = _clicks().reshape(-1, 1)
    assert analyze.stereo_metrics(mono) == (None, None)


def test_dual_mono_keeps_correlation_but_not_width():
    """Identical channels: correlation is a real 1.0, but the dB ratio is -inf."""
    y = _clicks()
    lr_corr, side_to_mid_db = analyze.stereo_metrics(np.stack([y, y], axis=1))

    assert lr_corr == pytest.approx(1.0), "perfectly correlated channels"
    assert side_to_mid_db is None, "zero side energy is -inf dB, not a number"


def test_silent_channel_reports_no_correlation():
    """corrcoef divides by the silent channel's zero standard deviation -> nan."""
    y = _clicks()
    lr_corr, side_to_mid_db = analyze.stereo_metrics(np.stack([y, np.zeros_like(y)], axis=1))

    assert lr_corr is None
    assert side_to_mid_db == pytest.approx(0.0), (
        "a hard-panned signal splits energy evenly between mid and side, so 0.0 dB "
        "here is a real measurement and must not be nulled out with the rest"
    )


def test_genuine_stereo_reports_both():
    """The ordinary case must still produce two finite numbers."""
    rng = np.random.default_rng(0)
    y = _clicks()
    left = y + 0.05 * rng.standard_normal(len(y)).astype(np.float32)
    right = y + 0.05 * rng.standard_normal(len(y)).astype(np.float32)

    lr_corr, side_to_mid_db = analyze.stereo_metrics(np.stack([left, right], axis=1))

    assert lr_corr is not None and -1.0 <= lr_corr <= 1.0
    assert side_to_mid_db is not None and side_to_mid_db < 0.0, "narrower than mid"


def test_no_runtime_warnings_on_degenerate_input():
    """The nan and -inf paths are expected, so they must not print numpy warnings."""
    y = _clicks()
    with np.errstate(all="raise"):  # any unguarded divide/invalid would raise here
        analyze.stereo_metrics(np.stack([y, np.zeros_like(y)], axis=1))
        analyze.stereo_metrics(np.stack([y, y], axis=1))


# ── end to end ───────────────────────────────────────────────────────────────


def test_mono_file_runs_to_completion(tmp_path):
    """The actual bug: analyze.py used to die partway through on a mono file.

    Asserts the run survives *and* still produces the sections that never depended
    on stereo, so a future "fix" that bails out early on mono fails here.
    """
    wav = tmp_path / "mono.wav"
    sf.write(wav, _clicks(), SR)  # 1-D -> genuinely single-channel

    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "analyze.py"), "--audio", str(wav), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, f"mono run failed:\n{proc.stderr[-2000:]}"

    summary = _strict_loads((out / "summary.json").read_text())
    assert summary["channels"] == 1
    assert summary["lr_correlation"] is None
    assert summary["side_to_mid_db"] is None
    assert summary["tempo_bpm"] is not None, "tempo does not depend on stereo"
    assert summary["key_candidates"], "key detection does not depend on stereo"
    assert (out / "overview.png").exists()
