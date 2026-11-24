# Working in this repo

## Committing

- Git holds code and agent config (`.claude/settings.json`, `.codex/config.toml`). Audio, generated output and other data files are gitignored.
- Stage explicit paths (`git add analyze.py tests/test_foo.py`, never `git add -A`), so untracked machine-local files such as `.claude/settings.local.json` stay out of commits.

## Verifying changes to analyze.py

Its output is deterministic for a given input, so a refactor can be checked instead
of argued about. `overview.png` is byte-identical between runs, which makes it the
strictest signal available:

```bash
python3 demo_bounce.py --out /tmp/demo          # public-domain fixture, no private audio needed

# The old version has to run from the repo root — it imports paths, and Python puts
# the script's own directory on sys.path, not the repo.
git show origin/main:analyze.py > analyze_before.py
python3 analyze_before.py --audio /tmp/demo/demo_bounce.wav --out /tmp/before
python3 analyze.py        --audio /tmp/demo/demo_bounce.wav --out /tmp/after
rm analyze_before.py

diff /tmp/before/summary.json /tmp/after/summary.json
cmp  /tmp/before/overview.png  /tmp/after/overview.png
```

For a change that is *meant* to alter behaviour, the equivalent check is to break
the fix deliberately and confirm the new tests fail — a test that passes both
before and after guards nothing. Every fix in `analyze.py` has been checked this
way; the counts live in the commit messages.

```bash
python3 -m pytest tests/ -q     # ~10s
```
