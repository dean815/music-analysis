# music-analysis — Portfolio Readiness Design

**Date:** 2026-07-14
**Program:** [GitHub Portfolio](https://linear.app/dean815/project/github-portfolio-b9ccc4dc8657) — Phase 1 analysis for `music-analysis` (seed issue DEA-60)
**Status:** Approved by Dean 2026-07-14

## Context

`music-analysis` is a private repo containing an audio + symbolic (MusicXML) music analysis toolkit — tempo/key/chord/form detection, plus generation of MIDI/audio renderings of suggested musical ideas. It's one of four repos in Dean's GitHub Portfolio readiness program (see `~/claude/github-portfolio/PROGRAM.md`). This spec covers the Phase 1 analysis: scoring the repo on the program's four dimensions and defining the concrete fix list before any Linear issues are filed.

## Audit findings

### 1. Working & useful

All 11 Python scripts were smoke-tested (`--help` invocation) against the declared dependencies in `requirements.txt` — every one runs cleanly. `paths.py` provides a consistent env-var + CLI-flag pattern that all analysis/generation scripts follow.

**Exception: `lyria_clip.py`.** It imports `google-genai`, which is not declared in `requirements.txt` — a fresh clone following the README's own setup instructions (`pip install -r requirements.txt`) gets an `ImportError` the moment they try this script. It also:
- Hardcodes a single prompt string and output path (`out/lyria/jam-band-intro-001.mp3`) instead of exposing CLI flags via `paths.py`, breaking the convention every other script follows (and that the same commit's message claims to have established repo-wide: "All song-specific hardcoding has been removed").
- Requires Google GenAI API credentials with no documentation of what's needed or where to get them.
- Isn't listed in the README's script table at all.

This reads as a scratch experiment that landed in the same commit as a "make everything reusable" refactor, not as part of the toolkit's story.

### 2. Public-ready structure

**Audit is clean.** Verified:
- README present and covers what/why/install/usage, plus a script reference table and an explicit "Privacy" section documenting that no personal paths are committed.
- MIT LICENSE present, correctly attributed.
- `.gitignore` excludes `.env`, generated artifacts (`out/`, `previews/`), and audio/MIDI files.
- Full commit history (`git log -p --all`) grepped for secrets (API keys, tokens, passwords, private-key blocks) — no matches.
- Full commit history grepped for personal file paths (`/Users/`) — the only match is the README's own line instructing readers how to run this same check; no actual personal paths are committed.
- `.env.example` contains only placeholder paths (`/path/to/your/bounce.wav`), no real data.

**One polish item:** `real_book.py`'s module docstring includes usage examples referencing a real song title and artist ("Kitchen" — SZA). Not a legal or secrets issue, but it cuts against the repo's stated "not tied to a specific piece" framing. Genericizing it is a one-line-per-example fix.

**Verdict: publish gate can pass** once the fixes below merge and the repo is re-verified (see Sequencing).

### 3. Hiring-manager value

Weighted per the program's four signals:

- **Docs-first DevRel polish:** README is already good structurally (setup, usage, per-script table, explicit assumptions/limitations section, privacy note) — but the script table is stale. `real_book.py` (added in the most recent commit) is missing from it entirely; `lyria_clip.py` will need its row removed once deleted.
- **AI-native engineering process:** Already visible without extra work — commit messages carry real design rationale (e.g. the latest commit's multi-paragraph explanation of the reusability refactor) and consistent `Co-Authored-By: Claude ...` attribution. This spec itself, once committed, becomes the first artifact of a documented spec → plan → PR flow for this repo.
- **Engineering depth:** No tests today. Full test coverage for audio DSP code is out of scope for this pass (per Dean — see Decisions below), but a lightweight CI smoke-test workflow is in scope and gives a real, visible signal (green checks, catches exactly the class of breakage `lyria_clip.py` has) for low effort.
- **Product sense & demos:** README currently has no visible output — just a script reference table. `real_book.py`'s ASCII lead sheet and `analyze.py`'s PNG plots are the strongest demo candidates. **Explicitly deferred per Dean's call** — good candidate for a future pass, not blocking this one.

### 4. Effort & sequencing

Everything identified is small and independently shippable. Decision: 3 small child Linear issues (one Cyrus PR each) rather than one bundle, since they touch different concerns and can be reviewed/reverted independently.

## Decisions on record (from brainstorming)

| Decision | Answer |
|---|---|
| Scope for this pass | Quick, high-leverage pass — no test suite, no README demo content |
| `lyria_clip.py` disposition | Remove from this repo; file a **separate, non-blocking** exploratory issue about a proper Lyria-based generation feature |
| README demo/screenshot content | Skip for this pass |
| Lightweight CI | Yes — smoke-test workflow (install deps, import-check + `--help` every script) |
| `real_book.py` docstring example | Genericize (drop the specific song title/artist) |

## Action items → Linear issues

1. **Remove `lyria_clip.py` and refresh the README script table.** Delete the file; remove its (nonexistent) README row; add the missing `real_book.py` row.
2. **Add lightweight CI.** `.github/workflows/ci.yml`: install `requirements.txt`, then run an import-check + `--help` smoke test across every remaining script. No test framework, no fixtures — just "does it still run."
3. **Genericize the `real_book.py` docstring usage examples.** Replace the "Kitchen" / "SZA" example with a generic placeholder (e.g. `--title "Song Title" --artist "Artist Name"`).

Plus one standalone, non-blocking issue:

4. **[Exploratory, not gating] Investigate a proper Lyria-based audio-generation feature** — captures the idea `lyria_clip.py` was reaching for (AI-generated audio previews via Google's Lyria model), scoped and parameterized properly if pursued. Not part of the portfolio-readiness gate.

## Publish gate

Dimension 2's audit passes today (no secrets, no personal data, README/LICENSE in place). Per program rules, the recommendation is to **hold the visibility flip until after issues 1–3 merge**, then re-run the secrets/personal-data grep once more before Dean flips the repo to public in the GitHub UI. This spec does not itself authorize publishing — that remains a manual step for Dean per the program runbook.

## Out of scope for this pass

- Test suite / pytest coverage for the audio DSP pipeline.
- README demo content (ASCII lead sheet snippet, PNG plot screenshot).
- Any changes to `modal_prior.py` (intentionally unimplemented WIP scaffold — already clearly documented as such, not a readiness issue).
- Building out the Lyria audio-generation feature itself (tracked as exploratory issue #4 above, not executed here).
