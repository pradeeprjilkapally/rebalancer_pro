# rebalancer_pro — Living Reference

## What this is
A portfolio rebalancer and daily review agent for Paytm Money and Zerodha Kite.
Runs on a Mac (launchd), sends a WhatsApp summary daily, and supports interactive
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
| `python -m agent.webhook` | Start Flask webhook server on `WEBHOOK_PORT` (default 5001) — receives WhatsApp replies |
| `pip install -e .` | Install pmClient as local editable package (required on fresh clone) |

---

## Module map

| File | Role |
|---|---|
| `agent/main.py` | Interactive CLI entry point — full rebalancer flow |
| `agent/daily_review.py` | Scheduled review entry point — runs analyse + FIRE + WhatsApp send |
| `agent/rebalancer.py` | Core rebalancing logic — `analyse()`, `print_portfolio()`, `confirm_and_execute()` |
| `agent/portfolio.py` | Builds a unified portfolio snapshot dict from broker data |
| `agent/fire_analyser.py` | FIRE progress analysis — `analyse_fire()`, `fire_aligned_suggestions()` |
| `agent/auth.py` | Paytm Money session management — token cache in `agent/.tokens.json` |
| `agent/brokers/zerodha.py` | Zerodha Kite integration — auth, equity/MF/SIP fetch; tokens reset 3:30 AM daily |
| `agent/whatsapp.py` | Twilio WhatsApp send — `send_whatsapp()` is fire-and-forget; falls back to console |
| `agent/webhook.py` | Flask server receiving Twilio WhatsApp replies; validates via `TWILIO_AUTH_TOKEN` |
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
| `TWILIO_ACCOUNT_SID` | `whatsapp.py` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | `whatsapp.py`, `webhook.py` | Twilio auth token (also used to validate inbound webhook) |
| `TWILIO_WHATSAPP_FROM` | `whatsapp.py` | Sender number e.g. `whatsapp:+14155238886` |
| `TWILIO_WHATSAPP_TO` | `whatsapp.py` | Your number e.g. `whatsapp:+91XXXXXXXXXX` |
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
| Paytm Money daily review | 7:45 AM IST | 02:15 UTC | `python -m agent.daily_review --broker paytm` | Writes `mydata/paytm_suggestions.txt` + WhatsApp |
| Zerodha daily review | 8:00 AM IST | 02:30 UTC | `python -m agent.daily_review --broker zerodha` | Zerodha tokens reset ~3:30 AM; headless auth via WhatsApp |

Scheduled via macOS **launchd** (`~/Library/LaunchAgents/`). Wrap each command in `try/except`; prefix logs with `[cron]`.

---

## External services

| Service | Purpose | Docs |
|---|---|---|
| Paytm Money API | Portfolio data, order placement | pmClient SDK (this repo) |
| Zerodha Kite Connect | Equity/MF holdings, SIPs | `kiteconnect` PyPI package |
| Twilio WhatsApp | Daily summary delivery + reply-to-trade flow | `twilio` PyPI package |
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
- **Notifications** — `send_whatsapp()` must never block the main flow. In scheduled jobs, wrap in `threading.Thread(target=send_whatsapp, args=(msg,), daemon=True).start()` if needed.
- **Input validation** — at webhook/CLI boundaries: validate → normalize → act. Never trust raw Twilio webhook bodies without signature check (`TWILIO_AUTH_TOKEN`).
- **Scheduled jobs** — all jobs wrapped in `try/except Exception as e: print(f"[cron] {e}")`. IST→UTC conversion documented as a comment on every schedule expression.
- **Secrets** — never log or print env var values. `.env` is gitignored.
- **pmClient** — treat as read-only upstream. All agent logic lives in `agent/`.
