# Working in this repo

More than one Claude Code session runs here at a time, against the same checkout.
Everything below is the consequence of that.

## Work in a worktree, not the shared checkout

The repo root is shared. A linked worktree gets its own working tree *and* its own
index, so two sessions cannot see or stage each other's edits:

```bash
git worktree add .claude/worktrees/<name> -b <branch> origin/main
```

`.claude/worktrees/` is gitignored. Remove yours when the branch is merged:

```bash
git worktree remove .claude/worktrees/<name>
```

## Branch from `origin/main`, never from HEAD

```bash
git checkout -b <name> origin/main      # not: git checkout -b <name>
```

HEAD in a shared checkout may be another session's branch. Cutting from it silently
adopts their commits as ancestors of yours, and whichever PR merges first takes
credit for both.

That is not hypothetical. On 2026-07-29 a branch cut from a shared HEAD carried the
half-time tests written for #10 into #11, a PR about demo audio. #11 merged first,
so #10 merged as an empty commit and `git log -- tests/test_half_time.py` still
points at the wrong PR.

## Stage explicit paths

```bash
git add analyze.py tests/test_foo.py    # not: git add -A / git add .
```

The shared checkout may hold another session's uncommitted work, and
`.claude/launch.json` is untracked. Name what you mean.

## Confirm what actually landed

After a squash merge, check the diff rather than the merge status:

```bash
git show --stat origin/main
```

An empty diff means your change reached `main` by another route — usually absorbed
into someone else's PR — and the merge you just did was a no-op. A green "MERGED"
does not by itself mean your code moved.

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
