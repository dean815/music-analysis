# CLAUDE.md

Dean's portable guidelines. On his Mac these come from `~/.claude/CLAUDE.md`. This copy
travels with the repo so cloud sessions behave the same way.

## Build Mode: Prototype by Default

**Every build starts in prototype mode and stays there until Dean says otherwise.** The goal
is a working thing he can look at, fast, so he can iterate. Throwaway is fine: anything worth
publishing gets rebuilt clean later.

- **Get it running end to end first.** Thinnest slice that works in a real run, then widen.
- **Decide, don't ask.** Pick sensible defaults and note them in one line. Ask only when a
  wrong guess would make the result useless, and then ask one question.
- **Skip tests, specs, plans and docs unless asked.** A quick run that proves it works is enough.
- **Stub what's slow.** Fake external services, auth and hard integrations behind an obvious
  seam, and say what's faked.
- **No speculative structure.** No abstractions, config layers or error handling for cases
  that haven't happened.
- **Finish before polishing.** Keep going until the described thing exists.

This outranks project process rules (specs, TDD, worktrees, review gates, planning docs). A
project's facts still apply, and so does safety: never commit or print secrets, never run
destructive commands on real data, never touch production or send anything outward without
asking.

**Production mode starts only when Dean says so** ("clean this up", "productionize",
"harden", "get this ready to ship"). Then follow the project's rules in full, add tests and
handle errors.

## Working from a cloud session

When `CLAUDE_CODE_REMOTE=true`, you are on a disposable Ubuntu VM, not Dean's Mac:

- **No local machine.** His laptop is likely offline, and he may be reading on a phone. Keep
  responses scannable and decisions explicit.
- **Only pushed state exists.** If something referenced is missing, say so rather than
  reconstructing it from guesswork.
- **Push is branch-scoped.** `git push` only works against the session's working branch.
- **Prefer durable output.** Commit plans, notes and scaffolding; the transcript expires.
