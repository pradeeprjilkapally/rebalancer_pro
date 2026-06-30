---
name: no-slop
description: >-
  Structured quality pass to run before any code task is considered complete,
  and whenever the user asks for a "no-slop", "slop check", or quality review.
  Walks a fixed checklist over every created/modified file — dead code,
  unhandled errors, duplication, vague names, untested edges, restating
  comments, inconsistent style, scope creep, fake-done markers, and unverified
  claims — and requires each hit to be fixed or justified in one line before
  the work can be called done.
---

# No-Slop Review

Slop is a list. This skill runs that list as a review pass. Without it,
inattention multiplies across a task.

## Process

1. List every file created or modified in the current task.
2. Walk the checklist below over each file, top to bottom.
3. For each hit: **fix it**, or **justify the exception in one line**.
4. Work is not complete while any unexplained checklist hit remains.

## The checklist

### 1. Dead code
- No unused variables, imports, parameters, or functions.
- No commented-out code blocks.
- No unreachable branches.
- No config, flags, or dependencies added "just in case".
- *Dead code is a lie about what the program does. Delete it.*

### 2. Unhandled errors
- Every fallible call (I/O, network, parse, external command) has a real failure path.
- No swallowed exceptions with empty handlers.
- No errors logged and then ignored as if handled.
- Failure messages say what failed and what to do — not just generic text.

### 3. Duplication
- No copy-pasted blocks with minor edits — third occurrence means extract.
- No parallel structures that must be synchronised by hand.
- Shared logic lives in one place.

### 4. Naming
- Avoid unqualified generic names: `data`, `info`, `temp`, `obj`, `handle`,
  `doStuff`, `process`, `manager`.
- A name specifies what the thing is or does.
- Booleans read as questions (`is_ready`, `has_access`).
- Consistent vocabulary throughout.

### 5. Untested edges
- Empty input, null/undefined, zero, negative, max-size cases.
- The unhappy path when a dependency is unavailable.
- Concurrency scenarios where they apply.
- The checks named in the brief actually verify completion.

### 6. Comments
- No comments restating the code.
- Comments explain **why**, not **what** — the non-obvious decisions.
- No stale comments describing code that has since changed.

### 7. Consistency with the codebase
- Match surrounding file idioms, structure, and naming.
- Use existing utilities instead of reinventing them.
- Same error-handling, logging, and import style as neighbouring code.

### 8. Scope
- Everything aligns with the brief.
- Extra work is flagged explicitly, not slipped in.
- Nothing from the brief was silently dropped.

### 9. Fake done
- No `TODO`/`FIXME`/`XXX` without a tracked follow-up.
- No stubbed returns or hardcoded placeholder values.
- No "works on my machine" assumptions.
- No leftover console logs or debug prints.

### 10. Verified, not claimed
- Anything reported as working was actually run.
- "Deployed" / "done" claims carry same-session proof.
- Test failures are reported with their output, not hidden.

## Pre-push review — mandatory before every `git push`

A push is the last gate before code becomes shared. **Before any `git push`,
review the entire diff being pushed** — not just the files you remember editing:

```bash
git diff --stat @{u}..        # or origin/<base>... — see the full set
git diff @{u}..               # read it
```

Walk the checklist over that whole diff, with extra weight on:

- **Dead config** — unused env vars (grep each one: is it read anywhere?),
  orphaned settings, dependencies, launchd/CI entries, or example-file lines
  left behind by a removed feature. If nothing reads it, it goes.
- **Dead code** — modules/functions/imports/routes that the change orphaned.
  When you remove a feature, remove *everything* it touched (config, docs,
  tests, env, scripts), not just its main file.
- **Stale docs** — README / CLAUDE.md / .env.example lines that still describe
  the old behaviour.

Verify "unused" before deleting (grep the codebase — no-slop's "verify, not
claim"). Then remove it as part of the push. This is routine tidying, not a
decision to escalate — clean it without asking, and only the genuine judgement
calls get raised.

## Enforcement

Work is ineligible to be called complete if any item above is unexplained.
Fix it, or justify it in one line. The pre-push review runs every push — a push
that ships dead code or config is a failed no-slop pass.
