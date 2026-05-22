import sys
from pathlib import Path

from google import genai

PROMPT = """Energetic jam-band rock intro built around a guitar riff — the opening of a live concert. ~140 BPM in A Mixolydian. Two electric guitars (lead and rhythm), electric bass, Hammond B3 organ, full drum kit. Warm analog rock production, slightly roomy drum sound, live-feel mix.

[0:00 - 0:04] Tight hi-hat count-in from the drummer, then the lead electric guitar enters alone with a swaggering bluesy riff — syncopated, with quick double-stops and bends, featuring the flat-7 of A Mixolydian prominently.

[0:04 - 0:14] Full band locks in. Rhythm guitar adds chunky chord stabs underneath the riff. Bass walks confidently around the root. Hammond B3 sustains warm, glowing chords. Drums settle into a driving rock beat — snare on 2 and 4, active ride cymbal, occasional ghost notes.

[0:14 - 0:24] The riff repeats and develops. Organ pushes into higher voicings with a melodic counter-line above the riff. Rhythm guitar opens up the chords. Drums add tom fills. Energy builds steadily.

[0:24 - 0:30] Climactic band hit, big drum fill into a crash cymbal — the intro lands, ready to launch into a verse.

Instrumental, no vocals. Loose and live-feeling, like a jam band one-take."""

OUT_PATH = Path("out/lyria/jam-band-intro-001.mp3")


def main() -> int:
    client = genai.Client()
    response = client.models.generate_content(
        model="lyria-3-clip-preview",
        contents=PROMPT,
    )

    audio_bytes: bytes | None = None
    for part in response.parts:
        if part.inline_data is not None:
            audio_bytes = part.inline_data.data
            break
        if part.text is not None:
            print(f"[lyria text]: {part.text}")

    if audio_bytes is None:
        print("ERROR: no audio in response", file=sys.stderr)
        print(f"response: {response}", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(audio_bytes)
    print(f"wrote {OUT_PATH} ({len(audio_bytes):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
