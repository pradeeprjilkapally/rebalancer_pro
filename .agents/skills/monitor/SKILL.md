---
name: monitor
description: >-
  Triggered when Pradeep types "monitor". Runs the full health check on demand
  (app/webhook, Cloudflare tunnel + relay, dashboard exposure, GitHub CI, broker
  tokens, Slack) and reports the live status. Read-only — never auto-fixes, never
  posts to Slack, never edits files. For the automatic recurring version, the
  hourly launchd job (com.pradeep.sanity-check) runs the same checks and only
  escalates to an auto-fix PR when something is actually broken.
---

# Monitor — on-demand health check

When Pradeep types `monitor`, give him an instant, read-only status of the whole
stack. This is the manual counterpart to the hourly `sanity-check` job.

## Run it

```bash
python -m agent.sanity_check --report
```

`--report` runs every check and prints one line each, with **no side effects** —
no auto-fix, no Slack message, no `action_items.md` writes. Exits non-zero if any
check fails.

## What it checks

Cloudflared process · tunnel (direct) · relay (Workers) · webhook (:5001) ·
dashboard exposure (must be Access-gated, never public) · Slack webhook ·
broker auth sentinels · token freshness · GitHub CI (master) · open tasks.

## Report back

Summarise plainly: lead with **all green** or the count of failures, then list any
`[FAIL]` lines with their detail. For each failure, say whether it's:

- **auto-fixable** (cloudflared/tunnel/relay/webhook/CI/open-tasks) — the hourly job
  would raise a fix PR to Slack; offer to investigate now if Pradeep wants.
- **needs-him** (token re-auth, Slack/Access/exposure config) — give the one concrete
  next step.

Do not auto-fix or push anything from this skill — it is observation only. If a fix
is warranted, surface it and let Pradeep decide.
