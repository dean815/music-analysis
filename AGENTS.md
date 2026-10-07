# Working in this repo

## Storage & git lane (policy: ~/claude/git-strategy/DECISIONS.md, 2026-09-08)
LANE: code
- Git holds code and .claude/ config only. Every other file is gitignored data.
- Code work: commit on main with a generated message. No branch, no PR.
- Never create a worktree. One session works here at a time; for a second stream, clone to `~/claude/music-analysis-2`.
- Stage explicit paths (`git add analyze.py tests/test_foo.py`, never `git add -A`): `.claude/launch.json` and `.codex/` are untracked.
- Never write output outside this directory. Durability is the publish hook; do not add snapshot logic here.

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

Read `.claude/dean-guidelines.md` before starting work and follow it. Claude Code loads it automatically through `CLAUDE.md`; other agents must open it themselves.
