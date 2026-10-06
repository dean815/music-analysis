"""Export a bar-by-bar chord chart from audio, as JSON a chart app can import.

Two pretrained engines do the listening; this file only joins them:

- **beat_this** (CPJKU, 2024, MIT) finds beats and downbeats. Its downbeats are
  the bars, so tempo drift and a fade-out cost nothing, where a single-tempo grid
  slips a bar every time the band breathes.
- **BTC** (Park et al., ISMIR 2019, MIT), large vocabulary, labels chord
  segments in seconds.

Each bar is split into `--slots` equal parts and takes BTC's chord at the middle
of each, so a chord change on beat 3 reads as `D E` and a held chord as `D D`.

Output is the `AnalysisResult` v1 contract the chord-chart-maker app reads
through **From audio analysis…**:

    {"version": 1, "title": ..., "tempoBpm": ..., "meter": {...}, "bars": [["D", "E"], ...]}

The app owns finding the song's form. This file owns only seconds-to-bars.

Setup (heavier than requirements.txt: PyTorch, about 1 GB; Python 3.10-3.12):

    python3 -m pip install -r requirements-engines.txt
    git clone https://github.com/jayg996/BTC-ISMIR19 engines/BTC-ISMIR19

    python3 chart_export.py --audio song.wav --out out/song

BTC is not on PyPI, so it is run from a clone; its weights ship in the repo.
beat_this downloads an 80 MB checkpoint on first use to ~/.cache/torch/hub.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

import paths

# BTC's Harte qualities, written the way a chart prints them.
_QUALITY = {
    "maj": "", "min": "m", "7": "7", "maj7": "maj7", "min7": "m7",
    "dim": "dim", "dim7": "dim7", "hdim7": "m7b5", "aug": "aug",
    "sus2": "sus2", "sus4": "sus4", "maj6": "6", "min6": "m6",
    "minmaj7": "m(maj7)", "9": "9", "maj9": "maj9", "min9": "m9",
}

NO_CHORD = "N.C."


def harte_to_symbol(label: str) -> str:
    """`F#:min7` -> `F#m7`, `C:maj/E` -> `C/E`, `N` -> `N.C.`.

    A bass given as a scale degree (`C:maj/3`) is dropped rather than resolved:
    the chart app only reads a bass that parses as a pitch class.
    """
    if label in ("N", "X"):
        return NO_CHORD
    root, _, rest = label.partition(":")
    quality, _, bass = (rest or "maj").partition("/")
    symbol = root + _QUALITY.get(quality, quality)
    if bass and not bass.lstrip("b#").isdigit():
        symbol += "/" + bass
    return symbol


def bar_edges(beats: np.ndarray, downbeats: np.ndarray) -> list[tuple[float, float]]:
    """(start, end) seconds of each bar, one bar per downbeat, mended where the
    tracker slipped.

    On the spike track beat_this made both mistakes: an extra downbeat 0.44 s
    after a real one, which is dropped (under half a bar), and eight downbeats
    in a row a whole bar late, each gap two bars long, which are split back
    into bars of the median length. The last bar has no next downbeat, so it is
    given the median length too.
    """
    if len(downbeats) == 0:
        return []
    if len(downbeats) > 1:
        bar_len = float(np.median(np.diff(downbeats)))
    else:
        beat = float(np.median(np.diff(beats))) if len(beats) > 1 else 0.5
        bar_len = beat * meter_numerator(beats, downbeats)
    kept = [float(downbeats[0])]
    for d in downbeats[1:]:
        if d - kept[-1] >= 0.5 * bar_len:
            kept.append(float(d))
    if len(kept) > 1:
        bar_len = float(np.median(np.diff(kept)))  # again, without the glitches skewing it
    edges: list[tuple[float, float]] = []
    for start, end in zip(kept, kept[1:] + [kept[-1] + bar_len]):
        n = max(1, round((end - start) / bar_len))
        edges.extend((start + (end - start) * i / n, start + (end - start) * (i + 1) / n) for i in range(n))
    return edges


def meter_numerator(beats: np.ndarray, downbeats: np.ndarray) -> int:
    """Beats per bar: the most common count of beats between consecutive downbeats."""
    counts = [int(np.sum((beats >= a - 0.05) & (beats < b - 0.05))) for a, b in zip(downbeats[:-1], downbeats[1:])]
    counts = [c for c in counts if c > 0]
    if not counts:
        return 4
    values, freq = np.unique(counts, return_counts=True)
    return int(values[np.argmax(freq)])


def chord_at(segments: list[tuple[float, float, str]], t: float) -> str:
    """The chart symbol sounding at `t`; past the last segment, the last chord."""
    for start, end, label in segments:
        if start <= t < end:
            return harte_to_symbol(label)
    return harte_to_symbol(segments[-1][2]) if segments else NO_CHORD


def chart_bars(segments: list[tuple[float, float, str]], edges: list[tuple[float, float]], slots: int) -> list[list[str]]:
    return [[chord_at(segments, s + (e - s) * (i + 0.5) / slots) for i in range(slots)] for s, e in edges]


def analysis_result(title: str, beats: np.ndarray, downbeats: np.ndarray,
                    segments: list[tuple[float, float, str]], slots: int) -> dict:
    edges = bar_edges(beats, downbeats)
    result: dict = {"version": 1, "title": title}
    if len(beats) > 1:
        result["tempoBpm"] = round(60.0 / float(np.median(np.diff(beats))), 1)
    result["meter"] = {"numerator": meter_numerator(beats, downbeats), "denominator": 4}
    result["bars"] = chart_bars(segments, edges, slots)
    return result


# ---------- engines (imported lazily: the helpers above need only numpy) ----------

def run_beat_this(audio: Path) -> tuple[np.ndarray, np.ndarray]:
    import torch
    from beat_this.inference import File2Beats

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    beats, downbeats = File2Beats(checkpoint_path="final0", device=device, dbn=False)(str(audio))
    return np.asarray(beats), np.asarray(downbeats)


def run_btc(audio: Path, btc_dir: Path) -> list[tuple[float, float, str]]:
    """BTC's large-vocabulary model, without editing the 2019 clone.

    Its code predates NumPy 2 and PyTorch 2.6: it uses the removed `np.float` /
    `np.int` aliases at import time, `yaml.load` without a loader, and a
    pickled checkpoint. The aliases are restored for its import; config and
    weights are loaded here instead.
    """
    import torch
    import yaml

    for alias, real in (("float", np.float64), ("int", np.int64)):
        if not hasattr(np, alias):
            setattr(np, alias, real)
    sys.path.insert(0, str(btc_dir))
    from btc_model import BTC_model
    from utils.hparams import HParams
    from utils.mir_eval_modules import audio_file_to_features, idx2voca_chord

    with open(btc_dir / "run_config.yaml") as f:
        config = HParams(**yaml.safe_load(f))
    config.feature["large_voca"] = True
    config.model["num_chords"] = 170
    # Loaded weights-only, so the checkpoint cannot run code: the only non-tensor
    # contents are the NumPy mean/std scalars, allowlisted by name.
    from numpy._core.multiarray import scalar
    allowed = [(scalar, "numpy.core.multiarray.scalar"), np.dtype, type(np.dtype(np.float64))]
    with torch.serialization.safe_globals(allowed):
        checkpoint = torch.load(btc_dir / "test" / "btc_model_large_voca.pt", weights_only=True, map_location="cpu")
    model = BTC_model(config=config.model)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    feature, seconds_per_frame, _ = audio_file_to_features(str(audio), config)
    feature = (feature.T - checkpoint["mean"]) / checkpoint["std"]
    n_frames = feature.shape[0]
    step = config.model["timestep"]
    feature = np.pad(feature, ((0, -n_frames % step), (0, 0)))

    # BTC attends within fixed windows of `step` frames, so it is run one window at a time.
    predictions: list[int] = []
    with torch.no_grad():
        x = torch.tensor(feature, dtype=torch.float32).unsqueeze(0)
        for t in range(0, x.shape[1], step):
            out, _ = model.self_attn_layers(x[:, t:t + step, :])
            pred, _ = model.output_layer(out)
            predictions.extend(pred.squeeze(0).tolist())
    predictions = predictions[:n_frames]

    labels = idx2voca_chord()
    segments: list[tuple[float, float, str]] = []
    start = 0
    for i in range(1, n_frames + 1):
        if i == n_frames or predictions[i] != predictions[start]:
            segments.append((start * seconds_per_frame, i * seconds_per_frame, labels[predictions[start]]))
            start = i
    return segments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    paths.add_args(parser, audio=True)
    parser.add_argument("--btc-dir", type=Path,
                        default=Path(os.environ.get("BTC_DIR", "engines/BTC-ISMIR19")).expanduser(),
                        help="Clone of github.com/jayg996/BTC-ISMIR19 (default: $BTC_DIR or engines/BTC-ISMIR19)")
    parser.add_argument("--title", help="Song title (default: the audio file's name)")
    parser.add_argument("--slots", type=int, default=2, help="Chords sampled per bar (default: 2, half bars)")
    args = parser.parse_args()

    audio = paths.require(args.audio, "MUSIC_AUDIO")
    if not (args.btc_dir / "btc_model.py").exists():
        sys.exit(f"error: no BTC clone at {args.btc_dir}.\n"
                 f"  git clone https://github.com/jayg996/BTC-ISMIR19 {args.btc_dir}")

    beats, downbeats = run_beat_this(audio)
    segments = run_btc(audio, args.btc_dir.resolve())
    result = analysis_result(args.title or audio.stem, beats, downbeats, segments, args.slots)

    out = paths.ensure_dir(args.out) / "chart.json"
    out.write_text(json.dumps(result, indent=1))
    print(f"{len(result['bars'])} bars, {result.get('tempoBpm')} BPM, "
          f"{result['meter']['numerator']}/4 -> {out}")


if __name__ == "__main__":
    main()
