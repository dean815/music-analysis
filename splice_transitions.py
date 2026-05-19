"""Splice each pre-intro WAV with the first ~10s of the user's existing bounce,
crossfading the boundary so the transition into m17 is audible."""
import argparse
from pathlib import Path
import numpy as np
import soundfile as sf

import paths

_parser = argparse.ArgumentParser(description=__doc__)
paths.add_args(_parser, audio=True, needs_out=False, needs_previews=True)
_args = _parser.parse_args()
BOUNCE = paths.require(_args.audio, "MUSIC_AUDIO")
PREVIEWS = paths.require(_args.previews, "MUSIC_PREVIEWS")

CROSSFADE_S = 0.4   # 400ms blend so the synth doesn't cut abruptly into the real recording
INTRO_FROM_BOUNCE_S = 12.0  # how much of the existing bounce to include

bounce_audio, sr = sf.read(str(BOUNCE))
# Convert stereo bounce to mono to match our mono previews.
if bounce_audio.ndim > 1:
    bounce_audio = bounce_audio.mean(axis=1)

intro_samples = int(INTRO_FROM_BOUNCE_S * sr)
bounce_head = bounce_audio[:intro_samples]
# Trim the existing bounce to start at first non-silent sample (the keyboard entry)
# In case there's any leading silence in the file.
loud_thresh = 0.005
first_loud = next((i for i, v in enumerate(np.abs(bounce_head)) if v > loud_thresh), 0)
bounce_head = bounce_head[first_loud:]
print(f"bounce sr={sr}, mono frames={len(bounce_audio)}, trimmed head starts at sample {first_loud}")

xfade_samples = int(CROSSFADE_S * sr)

for preview_wav in sorted(PREVIEWS.glob("approach*.wav")):
    if "_with_transition" in preview_wav.stem:
        continue
    pre_audio, pre_sr = sf.read(str(preview_wav))
    if pre_sr != sr:
        raise SystemExit(f"sample rate mismatch: {preview_wav} is {pre_sr}, bounce is {sr}")

    # Boost the bounce loudness gently to match the synth amplitude.
    pre_peak = np.max(np.abs(pre_audio))
    bounce_peak = np.max(np.abs(bounce_head)) + 1e-9
    target_peak = pre_peak * 0.95
    bounce_matched = bounce_head * (target_peak / bounce_peak)

    # Build the spliced output.
    # Layout: [pre_audio][crossfade][bounce_matched]
    total = len(pre_audio) + len(bounce_matched) - xfade_samples
    out = np.zeros(total, dtype=np.float32)

    # Place the pre audio.
    out[: len(pre_audio)] = pre_audio
    # Apply fade-out on the tail of the pre.
    xf_out = np.linspace(1, 0, xfade_samples)
    out[len(pre_audio) - xfade_samples : len(pre_audio)] *= xf_out
    # Add the bounce starting at len(pre_audio) - xfade_samples.
    start = len(pre_audio) - xfade_samples
    # Fade-in on the head of the bounce.
    xf_in = np.linspace(0, 1, xfade_samples)
    bounce_faded = bounce_matched.copy()
    bounce_faded[:xfade_samples] *= xf_in
    out[start : start + len(bounce_faded)] += bounce_faded

    # Soft-clip.
    peak = np.max(np.abs(out))
    if peak > 0.95:
        out *= 0.95 / peak

    out_path = preview_wav.with_name(preview_wav.stem + "_with_transition.wav")
    sf.write(str(out_path), out, sr, subtype="PCM_24")
    print(f"  → {out_path.name}  ({len(out)/sr:.2f}s)")
