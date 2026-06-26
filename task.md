# Task

<!--
TEMPLATE — keep this comment block as reference. Each task section starts with a
date line, then the fields.

Lifecycle (maintained by Claude):
- COMPLETE  → the whole task section is commented out with "Status: complete
              <date> — <result>", and a fresh dated template is added for the
              next task.
- PENDING   → if Pradeep says to park the task, its Status becomes
              "pending — parked <date>", the section stays VISIBLE (not
              commented), and a fresh template is added below for the next task.
- REVIEW    → at the start of each day/session, Claude shows the current state
              of this file (pending + open tasks) for review.

Date:         when the task was filed
Status:       (leave empty; Claude sets complete/pending)
Task:         <Incremental_Number_First_task_for_day_starts_With_01>-<DDMMYY>
Goal:         the one outcome, in a sentence.
Constraints:  what it must (and must not) do. Stack, perf, style, security.
Inputs:       what the agent starts with. Files, data, an API, an example.
Outputs:      what exists when it's finished. Files, endpoints, behavior.
Done-check:   the concrete test that proves it works.
Out-of-scope: what NOT to touch, so it doesn't wander.
-->
--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-27
Status:       complete 2026-06-27 — Basic Auth removed; exposure guard added + verified (relay 302 = not exposed); suite 90 passed
Task:         01-270627
Goal:         Drop the second dashboard auth layer (HTTP Basic Auth) now that Cloudflare Access (Google + email OTP) gates the dashboards, and add a sanity-check guard that alerts if the dashboard ever becomes publicly reachable.
Constraints:  Single sign-on (Access only) for dashboards; no app-level password to maintain. Machine paths (/callback, /paytm_callback, /health) stay Access-bypassed. Exposure guard must fail open on network blips (only a confirmed public 200 trips it). Security headers stay.
Inputs:       agent/webhook.py (require_auth + _DASH_USER/_DASH_PASS), agent/sanity_check.py, tests/agent/.
Outputs:      webhook.py: removed require_auth/_auth_ok/_DASH_* + hmac/functools imports + 4 @require_auth decorators; sanity_check.py: check_dashboard_exposure() (relay /dashboard_main must NOT be 200) in CHECKS + _HUMAN_REQUIRED; tests updated (test_webhook.py, test_sanity_dashboard_exposure.py); .env.example + CLAUDE.md updated.
Done-check:   deterministic suite 90 passed; check_dashboard_exposure() returns OK against live relay (302); /dashboard_main serves 200 at app layer (Access gates at edge).
Out-of-scope: Cloudflare Access dashboard config, tunnel/relay, notification channel.

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

Date:         2026-06-25
Status:       complete 2026-06-25 — verify-before-publish + metrics-based watchdog; relay 200, chain green
Task:         01-250625
Goal:         Stop the morning sanity check failing on a dead tunnel URL — never publish an unverified URL to KV, and detect edge-disconnection fast via cloudflared metrics instead of flaky public DNS.
Constraints:  Only touch agent/tunnel_manager.py. Quick-tunnel architecture stays. No secrets logged. Watchdog must not false-kill a healthy tunnel on a local-DNS blip.
Inputs:       agent/tunnel_manager.py, scripts/verify_tunnel.py, live logs in ~/Library/Logs/rebalancer/
Outputs:      tunnel_manager.py: pinned --metrics port; _ha_connections() liveness; verify-before-publish to .tunnel_url + KV.
Done-check:   launchctl kickstart reloads tunnel job on new code; live log shows "Active URL"/"KV updated" only after reachable; python -m scripts.verify_tunnel → PASS.
Out-of-scope: Cloudflare Worker (relay) source, named-tunnel migration, daily_review/webhook logic.

<!-- Status: complete 2026-06-19 — split working, plists registered, both WhatsApp messages confirmed

Date:         2026-06-18
Status:       complete 2026-06-19
Task:         01-180626
Goal:         Split daily portfolio review into two separate WhatsApp messages — Paytm Money at 7:45 AM and Zerodha at 8:00 AM.
Constraints:  Each broker review must be fully independent. No shared state between runs. Secrets never logged.
Inputs:       agent/daily_review.py (single combined run), existing launchd plist at 8 AM
Outputs:      daily_review.py with --broker flag; com.pradeep.paytm-daily-review.plist (7:45 AM); com.pradeep.zerodha-daily-review.plist (8:00 AM)
Done-check:   launchctl list shows both plists loaded; python3 -m agent.daily_review --broker paytm and --broker zerodha run without error.
Out-of-scope: Portfolio analysis logic, FIRE calculations, WhatsApp message content.
-->

<!-- Status: complete 2026-06-19 — headless mode sends WhatsApp ping instead of crashing; /paytm_callback auto-exchanges token

Date:         2026-06-19
Status:       complete 2026-06-19
Task:         02-190626
Goal:         Fix Paytm Money headless auth — EOFError crash when launchd job can't call input(); add /paytm_callback OAuth route for automatic token exchange.
Constraints:  Request token must never be logged. Token exchange must happen in the callback, not deferred. Graceful fallback if Paytm API is down.
Inputs:       agent/auth.py (crashing on input()), agent/webhook.py (Zerodha callback only)
Outputs:      auth.py detects headless via sys.stdin.isatty(); webhook.py /paytm_callback route; whatsapp.py send_paytm_auth_required()
Done-check:   Run daily_review --broker paytm from launchd context (no TTY) → WhatsApp ping sent, no crash. POST /paytm_callback with valid token → tokens saved, sentinel cleared.
Out-of-scope: Zerodha auth flow, FIRE analysis, WhatsApp formatting.
-->

<!-- Status: complete 2026-06-19 — full interactive flow E2E verified on live WhatsApp; all state transitions confirmed

Date:         2026-06-19
Status:       complete 2026-06-19
Task:         03-190626
Goal:         Replace raw YES/NO text replies with Twilio quick-reply buttons and a conversation state machine covering auth ping → skip → add input → done loop.
Constraints:  Max 3 buttons per message (WhatsApp limit). State must persist across webhook restarts (file-backed). No secrets in state file. Single TwiML response per inbound message (no dual-message conflicts). Twilio signature validated against permanent relay URL.
Inputs:       agent/webhook.py (text YES/NO only), agent/whatsapp.py (plain text auth messages), Twilio Content API
Outputs:
  - 3 Twilio Content Templates (auth_ping, post_skip, continue_done) — SIDs in .env
  - agent/conversation.py — state machine (idle/auth_pending/post_skip/awaiting_input)
  - agent/whatsapp.py — send_auth_ping(), send_post_skip_prompt(), send_interactive()
  - agent/webhook.py — full state machine handler; Twilio sig validated against WORKERS_RELAY_URL
  - agent/auth_reminder.py — 9 AM launchd job checks both sentinels, sends combined nudge
  - com.pradeep.auth-reminder.plist — registered and loaded
Done-check:   E2E live test: auth ping → Skip Today → Add Input → type query → Done. All state transitions observed in watcher. Note saved to mydata/whatsapp_notes.txt.
Out-of-scope: Answering portfolio queries from WhatsApp input (future task). Paytm Money redirect URL setup in developer console (one-time manual step).
-->

<!-- Status: complete 2026-06-19 — tunnel auto-restarts on crash, re-captures URL, KV updated immediately

Date:         2026-06-19
Status:       complete 2026-06-19
Task:         04-190626
Goal:         Fix tunnel_manager.py crash-loop — cloudflared was dying and restarting with a new URL that never updated KV, breaking the Workers relay.
Constraints:  Must never hard-code a tunnel URL. Must handle URL changes on reconnect. KV update must be idempotent.
Inputs:       agent/tunnel_manager.py (captured URL once, never re-captured on reconnect)
Outputs:      tunnel_manager.py with outer restart loop and per-line URL re-detection; KV updated on every URL change.
Done-check:   curl https://portfolio-relay.pradeeprjilkapally.workers.dev/health returns {"status":"ok"} after tunnel restart.
Out-of-scope: Switching to a named Cloudflare tunnel (future, requires paid plan).
-->

<!-- Status: complete 2026-06-23 — all 3 root causes fixed; Paytm + Zerodha authenticated live on real WhatsApp

Date:         2026-06-22
Status:       complete 2026-06-23
Task:         01-220626
Goal:         no response to my pings from whatsapp. Fix all the broken connections
Constraints:  Whenever I respond to morning 7:45 or 8 AM messages, there should be a response.
Done-check:   Pradeep taps buttons on real WhatsApp and gets a response — end to end on the live device

Root causes fixed:
  1. QUIC NAT timeout — cloudflared forced to --protocol http2 (TCP); QUIC idle-dropped by router after ~2h
  2. No health watchdog — tunnel_manager now kills dead cloudflared within 4 min; previously took 11+ hours
  3. Paytm requestToken mismatch — /paytm_callback looked for request_token (snake) but Paytm sends requestToken (camelCase); every auth attempt returned 400 silently since day 1
Also: send_auth_links split into per-broker messages; auth_reminder sends separate pings per broker
Verified: Pradeep authenticated Paytm + Zerodha live on WhatsApp 2026-06-23 10:31 IST; tokens confirmed written
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — /dashboard live (200, all sections verified); WhatsApp condensed to 6 lines with relay link; JSON written alongside txt on each review run

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         01-230626
Goal:         Add a /dashboard web route showing both broker portfolios in a clean HTML table, and condense the WhatsApp morning message to a 5-line summary + dashboard link.
Constraints:  Dashboard reads structured JSON written by daily_review.py — no text parsing. Mobile-first HTML. No external CDNs. WhatsApp message must fit without scrolling (≤10 lines). Dashboard URL uses the permanent Workers relay.
Inputs:       agent/daily_review.py (_write_file, _format_whatsapp), agent/webhook.py (Flask app)
Outputs:      mydata/{broker}_data.json written alongside the txt; /dashboard Flask route in webhook.py; condensed _format_whatsapp() in daily_review.py
Done-check:   curl localhost:5001/dashboard returns 200 with both broker sections visible; WhatsApp message is ≤10 lines with dashboard link.
Out-of-scope: Stitch redesign (future), auth flow changes, FIRE calculation logic.
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — preflight.py built; validate_all() passes on live tokens; daily_review reports session state before any auth trigger

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         02-230626
Goal:         Add a pre-flight validation step that silently tests Paytm + Zerodha sessions and tunnel health before triggering any auth prompt — never ask for auth unless the silent test actually fails.
Constraints:  Validation must be silent (no user-facing output unless a check fails). Must not trigger headless auth flow or send WhatsApp. Only report what's broken. Tunnel check included.
Inputs:       agent/auth.py (setup_session), agent/brokers/zerodha.py (get_kite_client), agent/sanity_check.py (check_relay, check_tunnel_direct)
Outputs:      agent/preflight.py — validate_all() returns {paytm, zerodha, tunnel} status dict; agent/daily_review.py updated to call preflight before data fetch.
Done-check:   Running preflight with valid tokens returns all-ok with no auth prompts. Running with expired tokens reports exactly which broker needs auth and why.
Out-of-scope: Fixing MCP kitemcp session (separate tool, separate auth path), UI changes.
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — Gold live in dashboard (₹10,005, manual badge); MF placeholder ready; portfolio total now ₹76,794

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         03-230626
Goal:         Add manual holdings support (MF + Gold) — read mydata/manual_holdings.json, fetch live MF NAV from mfapi.in, derive gold price from Gold Bees ETF, merge into portfolio snapshot and dashboard.
Constraints:  mfapi.in is public/free — no auth needed. Gold price derived from Gold Bees LTP already in snapshot — no extra API. Manual file is gitignored (personal data). Holdings show a [manual] badge in dashboard. No changes to pmClient SDK.
Inputs:       agent/portfolio.py (build_snapshot), agent/webhook.py (dashboard), mydata/ dir
Outputs:      agent/manual_holdings.py; mydata/manual_holdings.json (template); portfolio.py updated; dashboard shows manual holdings with badge
Done-check:   With manual_holdings.json populated, daily review prints manual MF + gold holdings; dashboard shows them alongside Paytm/Zerodha data.
Out-of-scope: CAMS CAS parsing, MF Central API, Zerodha Coin SIP setup.
-->

--------------------------------------------------------------------------------------------------
--------------------------------------------------------------------------------------------------

<!-- Status: complete 2026-06-23 — IBJA-sourced 24K rate (₹14,479/g); dashboard gold section live with stats, 30-day SVG chart, 7-day colour-coded table; corrected from bogus Gold Bees proxy to real IBJA rates.

Date:         2026-06-23
Status:       complete 2026-06-23
Task:         04-230626
Goal:         Live Paytm Gold tracking — IBJA 24K rate, 79-day seeded history, dashboard gold section with invested/current/grams/P&L + SVG trend + 7-day table.
Verified:     IBJA ₹14,479/g; portfolio value ₹80,186; P&L -2.85%; 30-day chart SVG; 7-day table with colour-coded changes; Paytm markup note displayed.
-->
