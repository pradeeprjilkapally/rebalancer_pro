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
| 2026-06-24 | — | **Activate real-time CI alert** — add `SLACK_WEBHOOK_URL` repo secret | Pradeep | GitHub → repo Settings → Secrets and variables → Actions → add `SLACK_WEBHOOK_URL` (same value as `.env`). The CI notify job posts to Slack on failure once set. Daily 7 AM `check_ci` backstop already works without it. |
| 2026-06-24 | — | Enable branch protection on rebalancer_pro master | Pradeep | GitHub → Settings → Branches → Add rule for `master` → require status checks to pass before merge → select the "Lint/Test Conda" checks. CI is reliably green now, so this is the moment. (One-time; needs admin.) |
| 2026-06-23 | — | Enable Cloudflare Access (Zero Trust) on the relay | Pradeep | Strongest outer layer: in Cloudflare dashboard → Zero Trust → Access → Applications, add a self-hosted app for `portfolio-relay.pradeeprjilkapally.workers.dev` with a policy allowing ONLY your email (one-time-PIN). Exclude paths `/callback`, `/paytm_callback`, `/health` (machine callers) via a bypass policy. Free tier covers it. |
| 2026-06-23 | — | Verify relay forwards `/dashboard_main` | Pradeep | Cloudflare Worker relay must proxy the new `/dashboard_main` path to the tunnel; old `/dashboard` now 404s. Confirm the dashboard link opens correctly. |
| 2026-06-23 | 2026-07-01 | Update gold grams + invested after next SIP | Pradeep | On July 1st SIP: open Paytm → Gold → note new grams total and new invested total → update `mydata/manual_holdings.json` grams + invested |
| 2026-06-24 | — | Install pre-push hook on any other dev machine | Pradeep | `.git/hooks/` isn't version-controlled. On a fresh clone run: `cp scripts/hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push` |
| 2026-06-24 | — | (ref) pmClient diverges from upstream | — | The CI fix edits `pmClient/apiService.py` (catch-all → `ConnectionError`), which CLAUDE.md marks read-only upstream. A future sync from `paytmmoney/pyPMClient` could re-introduce the 2-arg `httpx.HTTPError` bug — re-apply if so. |
| 2026-06-23 | — | (ref) Dashboard login credentials | — | HTTP Basic Auth guards /dashboard_main, /dashboard_bkp, /fire-*. User `pradeep`, password in `.env` (`DASHBOARD_PASS`). Restart webhook after editing. |
| 2026-06-22 | — | Push latest changes to rebalancer_pro | Pradeep | Run `git push rebalancer master` — covers tasks 01–04 + 01-220626, tunnel fix, Paytm requestToken fix, sanity check job |
| 2026-06-19 | — | Set Paytm Money redirect URL in developer console | Pradeep | Set to `https://portfolio-relay.pradeeprjilkapally.workers.dev/paytm_callback` — one-time manual step; Paytm callback now works (requestToken fix applied 2026-06-23) |

## Parking lot / roadmap

| Item | Status | Notes |
|------|--------|-------|
| Act on WhatsApp notes in next review | parked | Notes typed during the Skip loop are saved to `mydata/whatsapp_notes.txt` with timestamps — agent does not yet read or act on them during reviews; future task |
| Reply-to-trade via WhatsApp | parked | Conversation state machine is in place; needs order execution wired into the awaiting_input handler |
| Sync updated cartIQ skill (user mentioned update not yet pushed) | parked | User said they updated a skill in cartIQ; all pushed skills dated 2026-06-16; will sync once pushed |
| Named Cloudflare tunnel (permanent subdomain) | parked | Current quick tunnel URL changes on restart and is relayed via Workers KV; named tunnel would remove the relay entirely — requires paid Cloudflare plan |

## Done

| Closed | Item | Notes |
|--------|------|-------|
| 2026-06-24 | CI green + robustness shipped | All merged to master: apiService 405 fix, live/deterministic test split + network-block, 19 agent unit tests, pre-push hook, `requests` pin (batch `29028b6`); cross-platform runners fix (PR #2 `9291d58`); CI-failure WhatsApp alerts — real-time notify job + daily `check_ci` backstop (PR #3 `9d8fcad`). Master CI green on ubuntu-latest + windows-latest. |
| 2026-06-23 | Security hardening pushed | commit `36eff52` → rebalancer/master: dashboard Basic Auth, at-rest Fernet encryption (broker snapshots + Paytm tokens), security headers, loopback bind, server-version suppression, `/dashboard_main` rename + `/dashboard_bkp` |
| 2026-06-23 | Stitch dashboard redesign complete | Stitch project `86579244734503745` generated design; HTML ported to `_DASHBOARD_HTML` in webhook.py — dark navy, Inter font, Tailwind CDN, FIRE ring sidebar, gold SVG chart, MF card |
| 2026-06-23 | Paytm & Zerodha authenticated via WhatsApp | Both brokers authenticated end-to-end on real WhatsApp; tokens confirmed written |
| 2026-06-23 | Paytm requestToken fix | `/paytm_callback` was looking for `request_token` but Paytm sends `requestToken` — fixed to accept both; all prior auth attempts were silently returning 400 |
| 2026-06-23 | Tunnel QUIC → HTTP/2 + health watchdog | cloudflared forced to http2 (no QUIC NAT timeouts); watchdog kills dead tunnel within 2 checks (~4 min) instead of hours |
| 2026-06-23 | Sanity check job registered | `com.pradeep.sanity-check` runs at 7:00 AM IST; WhatsApp alert on failure |
| 2026-06-19 | Twilio Content Templates created | 3 quick-reply templates (auth_ping, post_skip, continue_done) created via Content API; SIDs written to .env |
| 2026-06-19 | auth-reminder launchd job registered | `com.pradeep.auth-reminder.plist` loaded at 9:00 AM IST — fires only if sentinel files are present |
| 2026-06-19 | Twilio signature validation fixed for relay | `_validate_twilio()` now uses `WORKERS_RELAY_URL` — was causing 403 for all real WhatsApp inbound messages through the relay |
| 2026-06-19 | E2E WhatsApp interactive flow verified live | Both Authenticate and Skip Today → Add Input → type → Done paths confirmed on live WhatsApp |
| 2026-06-19 | Tunnel manager crash-loop fixed | `tunnel_manager.py` rewrote to auto-restart cloudflared and re-capture URL on every reconnect |
| 2026-06-19 | Register launchd jobs for daily review | `com.pradeep.paytm-daily-review.plist` (7:45 AM) and `com.pradeep.zerodha-daily-review.plist` (8:00 AM) loaded and verified |
| 2026-06-19 | Update .env.example with all env vars | Added WEBHOOK_PORT, WEBHOOK_ENCRYPTION_KEY, CLOUDFLARE_*, WORKERS_RELAY_URL, TWILIO_TMPL_* vars |
| 2026-06-18 | SSH key setup + push to rebalancer_pro | SSH auth configured; rebalancer remote set to git@github.com:pradeeprjilkapally/rebalancer_pro.git; master pushed |
| 2026-06-18 | Port cartIQ skills and best practices | CLAUDE.md, task.md, action_items.md, .claude/settings.json, skills created |
