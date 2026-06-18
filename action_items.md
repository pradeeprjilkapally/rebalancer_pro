# Action Items

Tracks **non-functional / process work** — anything that is *not* a change to the agent's
features or behavior. Examples: repo setup, tooling & config, launchd job registration,
credentials/secrets, dependency bumps, follow-ups, decisions to make.
Functional feature work lives in `task.md`.

**Conventions**
- `Open` = chores to act on soon (with a **Target** / tentative date). `Parking lot` = deferred/blocked. `Done` = audit trail with a **Closed** date.
- One row per item, newest on top. `Status`: `open` · `in progress` · `blocked` · `done <date>` · `dropped <date>`. Absolute dates (YYYY-MM-DD); use `—` when none.
- An item that turns out to need code changes moves to `task.md` instead.
- **Auto-logged:** when a task leaves follow-ups behind (a push, a config step, a deferred sub-item), Claude appends them here automatically.

---

## Open

| Filed | Target | Item | Owner | Notes |
|-------|--------|------|-------|-------|
| 2026-06-18 | — | Register launchd jobs for daily review | Pradeep | Create `~/Library/LaunchAgents/` plists for paytm (7:45 AM IST = 02:15 UTC) and zerodha (8:00 AM IST = 02:30 UTC) daily_review jobs |
| 2026-06-18 | — | Update .env.example with all env vars | Pradeep | Add WEBHOOK_PORT, WEBHOOK_ENCRYPTION_KEY, CLOUDFLARE_* vars — currently missing from .env.example |

## Parking lot / roadmap

| Item | Status | Notes |
|------|--------|-------|
| Reply-to-trade via WhatsApp | parked | webhook.py + tunnel_manager.py are scaffolded; needs end-to-end test of the full Twilio → Flask → order flow |

## Done

| Closed | Item | Notes |
|--------|------|-------|
| 2026-06-18 | SSH key setup + push to rebalancer_pro | SSH auth configured; rebalancer remote set to git@github.com:pradeeprjilkapally/rebalancer_pro.git; master pushed |
| 2026-06-18 | Port cartIQ skills and best practices | CLAUDE.md, task.md, action_items.md, .claude/settings.json, skills created |
