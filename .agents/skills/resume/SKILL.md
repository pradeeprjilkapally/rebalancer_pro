---
name: resume
description: >-
  Triggered when Pradeep types "resume" — typically after switching terminals on a
  Claude<->Codex handoff. Reads the HANDOFF.md baton, checks out the named branch,
  re-reads the active task in task.md, and continues the work from exactly where the
  other agent stopped, finishing per the review-gate (tests → commit → PR → Slack).
---

# Resume — pick up the baton from the other agent

When Pradeep types `resume`, another agent (Claude or Codex) handed work over — the
state is in `HANDOFF.md` at the repo root, written by the token-monitor or the
`handoff` skill.

## Do this

1. **Read `HANDOFF.md`.** Note: `Owner`, `Branch`, the reason, and the "what's left".
   - If `Owner` is **not this agent**, stop and tell Pradeep he's in the wrong terminal
     (e.g. baton says `codex` but he's in Claude) — switch, don't double-drive.
2. `git checkout <Branch>` from the baton; `git status` to see the uncommitted state it
   described.
3. Re-read the active (non-complete) task block in `task.md` for the full Goal /
   Constraints / Done-check.
4. **Continue from where it stopped** — implement what's left, applying the shared
   conventions (no-slop pre-push review, task/ledger tracking).
5. Finish per the **review-gate**: tests green → commit to the SAME feature branch →
   PR → Slack. If this agent is Claude and the handback reason was "Claude refreshed",
   that's expected — take it back so Codex's free-tier usage stays minimal.
6. Clear the baton when the task is done: set `.token_monitor_state` to the running
   agent and note completion in `task.md`.

## Notes

- The two agents share the identical skill set and `AGENTS.md`/`CLAUDE.md`, so the work
  continues with the same standards regardless of who resumes.
- If `HANDOFF.md` is missing or stale (task already complete), say so and just show the
  current `task.md` state rather than inventing work.
