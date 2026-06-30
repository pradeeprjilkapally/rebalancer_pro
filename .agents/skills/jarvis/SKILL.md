---
name: jarvis
description: >-
  Triggered when the user types "jarvis". Reads task.md, parses the active
  (non-commented) task section, and immediately starts executing it without
  further prompting. Also fires at the start of each session to show the
  current task state for review. Covers the full task lifecycle: intake,
  execution, completion (comment-out + fresh template), and parking.
---

# Jarvis — task execution skill

AGENTS.md mandates: when the user types `jarvis`, read `task.md` and start the
task without further prompting.

## 1. Read task.md

```bash
cat task.md
```

The file follows a strict template. Completed tasks are HTML-commented out
(`<!-- Status: complete … -->`). The **active task** is the first non-commented
block that has a non-empty `Goal:` field.

## 2. Identify the active task

Scan for the first uncommented section with a filled `Goal:` line. That is the
task to execute right now. If every section is commented out or `Goal:` is blank,
respond:

> No active task found in task.md. File a task (fill in the template fields) and
> type `jarvis` again.

## 3. Execute without prompting

Read Goal, Constraints, Inputs, Outputs, Done-check, and Out-of-scope. Then act
immediately. Do not ask clarifying questions unless the task is genuinely
ambiguous in a way that blocks starting (e.g. a missing file path with no
reasonable default).

Adhere strictly to Out-of-scope — do not touch anything listed there even if
it looks related.

## 4. Mark complete

When the Done-check passes, comment out the entire task section:

```
<!-- Status: complete 2026-MM-DD — <one-line result>

Date:         ...
Status:       complete 2026-MM-DD
Task:         ...
...all fields...
-->
```

Then append a fresh blank template **below** the separator line:

```
--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:
Status:
Task:
Goal:
Constraints:
Inputs:
Outputs:
Done-check:
Out-of-scope:
```

## 5. Park a task

If Pradeep says to park the task mid-execution, set `Status: pending — parked
2026-MM-DD` in-place (leave the section visible, do not comment it out), then
append a fresh blank template below the separator so the next task can be filed.

## 6. Append follow-ups to action_items.md

After completing or parking any task, append any leftover items — a pending push,
a config step, a deferred sub-item, a manual verification step — to `action_items.md`
under the **Open** table. One row per item, newest on top, with today's date.

## 7. Session start

At the start of each session (settings.json SessionStart hook already handles
printing), briefly summarise:
- The active task (Goal + Status), if one exists
- Whether any tasks are parked (pending)

Then wait for `jarvis` to start execution.

## Conventions

- **Never** touch files listed in Out-of-scope.
- **Always** end delivery with: `verified / not-verified / known-issues` plus the
  Done-check result.
- If the task requires a push, do not push automatically — add a push item to
  `action_items.md` and remind Pradeep to run `git push rebalancer master`.
- Task numbering: `<NN>-<DDMMYY>` — `NN` resets to `01` for the first task each day.
