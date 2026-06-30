# rebalancer_pro — Living Reference

## What this is
A portfolio rebalancer and daily review agent for Paytm Money and Zerodha Kite.
Runs on a Mac (launchd), sends a Slack summary daily, and supports interactive
rebalancing via CLI.

Push target: **always `git push rebalancer master`** — never push to `origin` (upstream paytmmoney/pyPMClient).

---

## How to run

| Command | What it does |
|---|---|
| `python -m agent.main` | Interactive rebalancer — fetches Paytm Money portfolio, prints suggestions, asks to execute trades |
| `python -m agent.main --logout` | Clear saved Paytm Money tokens |
| `python -m agent.daily_review --broker paytm` | Daily review for Paytm Money (scheduled 7:45 AM IST = 02:15 UTC) |
| `python -m agent.daily_review --broker zerodha` | Daily review for Zerodha (scheduled 8:00 AM IST = 02:30 UTC) |
| `python -m agent.webhook` | Start Flask webhook server on `WEBHOOK_PORT` (default 5001) — OAuth callbacks + dashboards |
| `pip install -e .` | Install pmClient as local editable package (required on fresh clone) |

---

## Module map

| File | Role |
|---|---|
| `agent/main.py` | Interactive CLI entry point — full rebalancer flow |
| `agent/daily_review.py` | Scheduled review entry point — runs analyse + FIRE + Slack send |
| `agent/rebalancer.py` | Core rebalancing logic — `analyse()`, `print_portfolio()`, `confirm_and_execute()` |
| `agent/portfolio.py` | Builds a unified portfolio snapshot dict from broker data |
| `agent/fire_analyser.py` | FIRE progress analysis — `analyse_fire()`, `fire_aligned_suggestions()` |
| `agent/auth.py` | Paytm Money session management — token cache in `agent/.tokens.json` |
| `agent/brokers/zerodha.py` | Zerodha Kite integration — auth, equity/MF/SIP fetch; tokens reset 3:30 AM daily |
| `agent/notify.py` | Slack notifications — `notify()` posts to `SLACK_WEBHOOK_URL`, confirms delivery (HTTP 200 `ok`), falls back to console |
| `agent/webhook.py` | Flask server — OAuth callbacks (`/callback`, `/paytm_callback`), dashboards (gated at edge by Cloudflare Access), `/health` |
| `agent/tunnel_manager.py` | Cloudflare tunnel — exposes webhook over public URL |
| `agent/crypto.py` | Fernet encryption for stored tokens (`WEBHOOK_ENCRYPTION_KEY`) |
| `pmClient/` | Paytm Money API SDK (upstream: `paytmmoney/pyPMClient`) — do not modify |
| `mydata/` | Runtime output — `paytm_suggestions.txt`, `zerodha_suggestions.txt` (gitignored) |
| `scripts/` | Verification scripts — `scripts/verify_<feature>.py` → `testplans/<date>/results.json` |

---

## Environment variables

All loaded from `.env` via `python-dotenv`. Copy `.env.example` to `.env` on a fresh clone.

| Variable | Used by | Notes |
|---|---|---|
| `PAYTM_API_KEY` | `main.py`, `daily_review.py` | Paytm Money API key |
| `PAYTM_API_SECRET` | `main.py`, `daily_review.py` | Paytm Money API secret |
| `ZERODHA_API_KEY` | `brokers/zerodha.py` | Zerodha Kite API key |
| `ZERODHA_API_SECRET` | `brokers/zerodha.py` | Zerodha Kite API secret |
| `SLACK_WEBHOOK_URL` | `notify.py` | Slack incoming webhook for all proactive notifications |
| `SLACK_USER_ID` | `notify.py` | Your Slack member ID — @-tags you on token/auth alerts; falls back to `<!channel>` if unset |
| `WEBHOOK_PORT` | `webhook.py` | Flask port (default `5001`) |
| `WEBHOOK_ENCRYPTION_KEY` | `crypto.py` | Fernet key for token encryption |
| `CLOUDFLARE_API_TOKEN` | `tunnel_manager.py` | Cloudflare API token for tunnel |
| `CLOUDFLARE_ACCOUNT_ID` | `tunnel_manager.py` | Cloudflare account ID |
| `CLOUDFLARE_KV_NAMESPACE_ID` | `tunnel_manager.py` | Cloudflare KV namespace for tunnel URL relay |
| `WORKERS_RELAY_URL` | `tunnel_manager.py` | Cloudflare Worker relay endpoint |

---

## Scheduled jobs

| Job | Schedule (IST) | Schedule (UTC) | Entry point | Notes |
|---|---|---|---|---|
| Paytm Money daily review | 7:45 AM IST | 02:15 UTC | `python -m agent.daily_review --broker paytm` | Writes `mydata/paytm_suggestions.txt` + Slack |
| Zerodha daily review | 8:00 AM IST | 02:30 UTC | `python -m agent.daily_review --broker zerodha` | Zerodha tokens reset ~3:30 AM; headless auth link posted to Slack |
| Dashboard ping + refresh | 7:50 AM, 12:00 PM, 3:00 PM IST | — | `python -m agent.dashboard_ping` | Refreshes Paytm/Zerodha encrypted dashboard snapshots, then posts compact Slack link |
| Hourly health check | every hour | — | `python -m agent.sanity_check` | Auto-fixes infra/code failures via `claude -p`, **auto-merges to master after a green test suite**, posts the merged PR to Slack. 6h cooldown. Read-only status: `--report`. |

Scheduled via macOS **launchd** (`~/Library/LaunchAgents/`). Wrap each command in `try/except`; prefix logs with `[cron]`.

**Sanity-check auto-merge (project opt-in):** the hourly health check is allowed to
**merge its own fix to master** — but ONLY when (a) the failure is an auto-fixable
infra/code check, and (b) the deterministic suite (`pytest -m "not live"`) passes
first. This keeps the app self-healing without waiting on a manual merge. It does
**not** extend to regular/feature work, which always goes via PR for review. Every
auto-merge is announced on Slack with the PR link so it can be reviewed/reverted.

---

## External services

| Service | Purpose | Docs |
|---|---|---|
| Paytm Money API | Portfolio data, order placement | pmClient SDK (this repo) |
| Zerodha Kite Connect | Equity/MF holdings, SIPs | `kiteconnect` PyPI package |
| Slack | Daily summary + alert delivery (incoming webhook) | `SLACK_WEBHOOK_URL` |
| Cloudflare Tunnel | Expose local webhook over public HTTPS | `tunnel_manager.py` |

---

## Test helpers

| Script | What it verifies |
|---|---|
| `scripts/verify_<feature>.py` | Feature-specific verification — saves `testplans/<date>/results.json`; exits `sys.exit(2)` on failure |

Every task delivery ends with: **verified / not-verified / known-issues** stated explicitly.

---

## Working conventions

**Task intake (`jarvis`)** — Pradeep files feature/fix requests in `task.md` (repo root) using the template fields (Date, Goal, Constraints, Inputs, Outputs, Done-check, Out-of-scope), then types `jarvis`. On that trigger, read `task.md` and start the task without further prompting.
- Lifecycle: completed task → comment out the section with `Status: complete <date> — <result>`, append a fresh blank template below the separator. Parked task → `Status: pending — parked <date>`, stays visible, fresh template added below.
- At the start of each session, show the current `task.md` state for review.
- Task numbering: `<NN>-<DDMMYY>` — `NN` resets to `01` for the first task each new day.

**Action items (`ledger`)** — Non-functional / process work (config steps, pushes, deferred items, tooling) goes in `action_items.md` (not `task.md`). Typing `ledger` reads the file, shows the Open items, and acts on / updates whatever Pradeep points to.
- After finishing any task, append leftover follow-ups (pending push, config step, deferred sub-item) to `action_items.md` automatically.
- When Pradeep types `exit`, ask whether to review the open action items before closing; on "yes", list them.

**Push** — never push automatically. Always add a push item to `action_items.md` and remind Pradeep to run `git push rebalancer master`.

**Code conventions**
- **Notifications** — `notify()` (Slack) must never block the main flow. In scheduled jobs, wrap in `threading.Thread(target=notify, args=(msg,), daemon=True).start()` if needed. It confirms delivery (HTTP 200 `ok`) — never assume a send succeeded without that.
- **Input validation** — at webhook/CLI boundaries: validate → normalize → act. OAuth callback tokens are format-checked before use.
- **Scheduled jobs** — all jobs wrapped in `try/except Exception as e: print(f"[cron] {e}")`. IST→UTC conversion documented as a comment on every schedule expression.
- **Secrets** — never log or print env var values. `.env` is gitignored.
- **pmClient** — treat as read-only upstream. All agent logic lives in `agent/`.
