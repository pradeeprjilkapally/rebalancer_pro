---
name: ledger
description: >-
  Triggered when the user types "ledger". Reads action_items.md, shows the
  Open items table, and acts on or updates whatever the user points to. Also
  fires on "exit" to ask whether to review open items before ending the session.
  Covers closing done items, moving items between Open/Parking lot/Done, and
  appending new follow-ups after a task completes.
---

# Ledger — action items skill

AGENTS.md mandates: when the user types `ledger`, read `action_items.md`, show
the open items, and act on / update whatever the user points to.

## 1. Read action_items.md

```bash
cat action_items.md
```

The file has three sections:
- **Open** — chores to act on soon (with a Target date or `—`)
- **Parking lot / roadmap** — deferred or blocked items
- **Done** — closed items with a Closed date (audit trail)

## 2. Show open items

Print the Open table. If it is empty:

> No open action items. The parking lot has N item(s) — type `ledger parking` to
> see them, or file a new item.

## 3. Act on what Pradeep points to

| Pradeep says | What to do |
|---|---|
| "do X" / "close X" | Execute the item, then move its row to Done with today's date |
| "park X" | Move row from Open to Parking lot |
| "drop X" | Update Status to `dropped <date>` and move to Done |
| "add: <description>" | Append a new row to Open (Filed = today, Owner = Pradeep unless stated) |
| "update X: <note>" | Update the Notes cell for that row in-place |

## 4. Closing an item

When an item is done, move its row from Open to the **Done** table (newest on top):

```
| 2026-MM-DD | <Item description> | <Notes — how it was resolved> |
```

Remove it from the Open table entirely.

## 5. After any jarvis task — auto-append follow-ups

When `jarvis` marks a task complete or parked, automatically append any leftover
items here. Typical follow-ups:
- Push to rebalancer_pro (`git push rebalancer master`)
- Manual config steps (redirect URLs, console settings, credentials)
- Deferred sub-items explicitly marked Out-of-scope in the task
- One-time verification steps the user must run

One row per item, `Filed = today`, `Target = —` unless a date is known.

## 6. Exit review

When the user types `exit`, ask:

> Before you go — want a quick run-through of the open action items? (yes / skip)

On "yes": print the Open table and briefly note any items with a past Target date
that are overdue. On "skip" (or no reply): close silently.

Note: this only fires when `exit` arrives as a chat message. The literal CLI
Ctrl-D / quit bypasses Codex entirely.

## Conventions

- One row per item — no compound rows.
- Absolute dates everywhere (`YYYY-MM-DD`); convert relative dates ("Thursday",
  "next week") to absolute before writing.
- Status values: `open` · `in progress` · `blocked` · `done <date>` · `dropped <date>`.
- Never delete Done rows — they are the audit trail.
- Items that turn out to need code changes → move to `task.md` instead (file a
  proper task section there, remove from action_items.md Open).
