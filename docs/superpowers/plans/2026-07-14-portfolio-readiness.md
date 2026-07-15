# music-analysis Portfolio Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three concrete portfolio-readiness gaps identified in `docs/superpowers/specs/2026-07-14-portfolio-readiness-design.md` — a broken/undocumented script, a stale README table, and a copyright-adjacent docstring example — and add a lightweight CI smoke test so this class of breakage is caught automatically going forward.

**Architecture:** No new subsystems. This is three independent, additive/subtractive edits to an existing flat-file Python CLI toolkit (one script per analysis step, `paths.py` as the shared config helper) plus one new GitHub Actions workflow file. Each task is a standalone PR-sized unit.

**Tech Stack:** Python 3 (stdlib `argparse`, no test framework in this repo — verification is via direct script execution, not pytest), GitHub Actions (`ubuntu-latest`, `actions/setup-python@v5`).

## Global Constraints

- Every CLI script in this repo uses the shared `paths.py` pattern: `import paths; paths.add_args(parser, ...); ...; paths.require(args.x, "MUSIC_X")` (see `README.md`'s "Notes on the pipeline" section). Any script kept in the repo must follow it — this plan only *removes* the one script that doesn't (`lyria_clip.py`), it does not add a new one.
- No personal file paths, secrets, API keys, or other people's data may be introduced into any file or commit (per the spec's clean dimension-2 audit — don't regress it).
- `requirements.txt` must remain accurate: every import in every remaining script must resolve from a package listed there.
- MIT LICENSE and existing README structure (Setup / script table / Output locations / Notes on the pipeline / Privacy / License) stay intact — edits are surgical, not rewrites.
- `modal_prior.py` stays as-is (intentionally unimplemented WIP scaffold, already correctly documented as such in the README) — out of scope for this plan.

---

### Task 1: Remove `lyria_clip.py` and add the missing `real_book.py` README row

**Files:**
- Delete: `lyria_clip.py`
- Modify: `README.md` (script table, lines 34–47)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing consumed by other tasks — independent of Tasks 2 and 3.

- [ ] **Step 1: Delete `lyria_clip.py`**

```bash
git rm lyria_clip.py
```

- [ ] **Step 2: Add a `real_book.py` row to the README script table**

Open `README.md`. The script table currently reads (lines 34–47):

```markdown
| Script | Inputs | Purpose |
|---|---|---|
| `analyze.py` | `--audio` | First-pass audio analysis: tempo, key (Krumhansl), chromagram, structural segmentation |
| `analyze_v2.py` | `--audio` | Refined audio: bar-level chord smoothing, per-section key detection |
| `analyze_v3.py` | `--audio` | Fine-grained chord track with Viterbi smoothing, Dorian-vs-Aeolian diagnostic |
| `melody.py` | `--audio` | Monophonic pitch extraction via pyin; tests Lydian #4 vs natural 4 |
| `xml_analyze.py` | `--xml` | Symbolic analysis: exact notes from MusicXML, Roman numerals, key signature events |
| `xml_aligned.py` | `--xml` | Bar-by-bar chord chart with measure-to-time alignment |
| `xml_guitars.py` | `--guitars-xml` | Pitch histograms per section for guitar/lead parts |
| `generate_previews.py` | `--previews` (out) | Synthesizes audio + MIDI of hypothetical chord progressions |
| `splice_transitions.py` | `--audio`, `--previews` | Crossfades synth previews into the start of your bounce for transition auditioning |
| `paths.py` | — | Shared config helper (env vars + argparse) used by all scripts |
| `modal_prior.py` | — | **Work-in-progress.** Scaffold for a modal-diatonic prior to bias chord detection toward harmonically plausible chords. The function body is intentionally unimplemented; see the docstring for the policy choices to fill in. |
```

Replace it with (adds a `real_book.py` row after `splice_transitions.py`, since it consumes `analyze_v3.py`'s output like that script does; no other rows change):

```markdown
| Script | Inputs | Purpose |
|---|---|---|
| `analyze.py` | `--audio` | First-pass audio analysis: tempo, key (Krumhansl), chromagram, structural segmentation |
| `analyze_v2.py` | `--audio` | Refined audio: bar-level chord smoothing, per-section key detection |
| `analyze_v3.py` | `--audio` | Fine-grained chord track with Viterbi smoothing, Dorian-vs-Aeolian diagnostic |
| `melody.py` | `--audio` | Monophonic pitch extraction via pyin; tests Lydian #4 vs natural 4 |
| `xml_analyze.py` | `--xml` | Symbolic analysis: exact notes from MusicXML, Roman numerals, key signature events |
| `xml_aligned.py` | `--xml` | Bar-by-bar chord chart with measure-to-time alignment |
| `xml_guitars.py` | `--guitars-xml` | Pitch histograms per section for guitar/lead parts |
| `generate_previews.py` | `--previews` (out) | Synthesizes audio + MIDI of hypothetical chord progressions |
| `splice_transitions.py` | `--audio`, `--previews` | Crossfades synth previews into the start of your bounce for transition auditioning |
| `real_book.py` | `--out` | Renders a Real Book-style ASCII lead sheet from `analyze_v3.py`'s chord chart, with loop detection and section labels |
| `paths.py` | — | Shared config helper (env vars + argparse) used by all scripts |
| `modal_prior.py` | — | **Work-in-progress.** Scaffold for a modal-diatonic prior to bias chord detection toward harmonically plausible chords. The function body is intentionally unimplemented; see the docstring for the policy choices to fill in. |
```

- [ ] **Step 3: Verify no remaining references to the deleted script**

Run: `grep -rn "lyria" --include="*.py" --include="*.md" .`
Expected: no output (empty — confirms the file is gone and nothing else references it).

- [ ] **Step 4: Verify the README table renders the new row correctly**

Run: `grep -n "real_book.py" README.md`
Expected: one match, the new table row.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
chore: remove lyria_clip.py, add real_book.py to README table

lyria_clip.py imported google-genai (not in requirements.txt, so it
broke on a clean clone), hardcoded a one-off prompt/output path
instead of following the paths.py CLI convention every other script
uses, and needed undocumented API auth. It was a scratch experiment
that landed in the "make everything reusable" refactor commit.

real_book.py shipped in that same commit but was never added to the
README's script table.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add a lightweight CI smoke-test workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the final script list (this task should run *after* Task 1 merges, so `lyria_clip.py` is already gone and doesn't need special-casing in the smoke-test loop). If run before Task 1 merges, drop `lyria_clip.py` from the loop below manually — it has no `--help` support and would fail the workflow.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  smoke-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: python -m pip install -r requirements.txt

      - name: Import-check shared modules
        run: python -c "import paths, modes"

      - name: Smoke-test each script (--help)
        run: |
          set -e
          for f in analyze.py analyze_v2.py analyze_v3.py melody.py \
                   xml_analyze.py xml_aligned.py xml_guitars.py \
                   generate_previews.py splice_transitions.py real_book.py \
                   modal_prior.py; do
            echo "=== $f ==="
            python3 "$f" --help
          done
```

Note: `modal_prior.py` has no `argparse` (it's a WIP scaffold with a `__main__` self-test block), so `--help` is ignored and it just runs its self-test loop, which catches its own `NotImplementedError` and exits 0 by design — this is expected, not a special case to work around.

- [ ] **Step 2: Verify the smoke-test logic locally before pushing**

Run the same loop locally to confirm every script still exits 0 (this mirrors exactly what CI will do):

```bash
set -e
for f in analyze.py analyze_v2.py analyze_v3.py melody.py \
         xml_analyze.py xml_aligned.py xml_guitars.py \
         generate_previews.py splice_transitions.py real_book.py \
         modal_prior.py; do
  echo "=== $f ==="
  python3 "$f" --help
done
echo "ALL OK"
```

Expected: `ALL OK` printed at the end, no non-zero exits.

- [ ] **Step 3: Validate the YAML is well-formed**

Run: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid yaml')"`
Expected: `valid yaml` (if `pyyaml` isn't installed, `python3 -c "import json,sys; import yaml"` will fail with `ModuleNotFoundError` — in that case, skip this step and rely on GitHub's own workflow validation after push, since the file is otherwise a direct copy of a standard `setup-python` + install + run pattern).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: add lightweight smoke-test workflow

Installs requirements.txt, then import-checks the shared modules and
runs --help against every CLI script. Catches the class of breakage
lyria_clip.py had (missing dependency, script that doesn't actually
run) without requiring a full test suite.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Genericize the `real_book.py` docstring usage examples

**Files:**
- Modify: `real_book.py:9-11`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing consumed by other tasks — independent of Tasks 1 and 2.

- [ ] **Step 1: Replace the song-specific usage examples**

In `real_book.py`, the module docstring (lines 1–12) currently ends with:

```python
Usage:
    python3 real_book.py --out ./out/kitchen
    python3 real_book.py --out ./out/kitchen --title "Kitchen" --artist "SZA"
    python3 real_book.py --out ./out/kitchen --bpm 80.75 --bars-per-line 4
"""
```

Replace the three usage lines with generic placeholders:

```python
Usage:
    python3 real_book.py --out ./out/my-song
    python3 real_book.py --out ./out/my-song --title "Song Title" --artist "Artist Name"
    python3 real_book.py --out ./out/my-song --bpm 80.75 --bars-per-line 4
"""
```

- [ ] **Step 2: Verify no real song/artist references remain**

Run: `grep -in "kitchen\|SZA" real_book.py`
Expected: no output (empty).

- [ ] **Step 3: Verify the script still runs after the docstring edit**

Run: `python3 real_book.py --help`
Expected: exit code 0, argparse help text printed (confirms the docstring edit didn't break the module — `__doc__` feeds directly into `argparse.ArgumentParser(description=__doc__)` on line 22).

- [ ] **Step 4: Commit**

```bash
git add real_book.py
git commit -m "$(cat <<'EOF'
docs: genericize real_book.py usage examples

Replaces the "Kitchen" / SZA example with a generic placeholder,
matching the README's framing that this toolkit isn't tied to a
specific piece.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Out of scope (tracked separately, not implemented by this plan)

- **Exploratory issue:** "Investigate a proper Lyria-based audio-generation feature" — filed as a standalone, non-blocking Linear issue per the spec. No implementation tasks here; it's a future investigation, not a readiness fix.
- Test suite / pytest coverage for the audio DSP pipeline (explicitly deferred in the spec).
- README demo content — ASCII lead sheet snippet or PNG plot screenshot (explicitly deferred in the spec).
- `modal_prior.py` implementation (intentionally WIP, not a readiness issue).
