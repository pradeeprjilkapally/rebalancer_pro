# Portfolio Rebalancing Agent

A personal finance agent that monitors your equity and mutual fund portfolio across **Paytm Money** and **Zerodha**, tracks FIRE progress, suggests rebalancing actions, and delivers a daily report to **Slack** — running entirely on your Mac with no cloud dependency.

**You retain full control** — the agent only suggests actions. No trades are placed without your explicit per-trade approval.

---

## What it does

- Fetches live holdings from Paytm Money (equity) and Zerodha (equity + mutual funds + active SIPs)
- Analyses concentration risk and flags positions that exceed 25% of portfolio
- Tracks progress toward your FIRE corpus (₹2.25 Cr target at 12% p.a.)
- Suggests FIRE-aligned investments in underweight categories (mid/small-cap, international, debt)
- Sends a daily Slack summary at 8 AM IST (delivery confirmed via the webhook's HTTP 200 `ok`)
- Handles Zerodha re-authentication fully automatically — no manual token copying

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Your Mac (3 always-on launchd services)                 │
│                                                          │
│  ┌─────────────────────┐   ┌──────────────────────────┐  │
│  │  daily_review.py    │   │  webhook.py (Flask :5001) │  │
│  │  fires at 8 AM IST  │   │  /callback   ← Zerodha   │  │
│  │                     │   │  /paytm_callback ← Paytm │  │
│  └────────┬────────────┘   └────────────┬─────────────┘  │
│           │                             │                │
│     Paytm Money API             Cloudflare Tunnel        │
│     Zerodha Kite API            tunnel_manager.py        │
└───────────┼─────────────────────────────┼────────────────┘
            │                             │
            ▼                             ▼
        Slack webhook            Public HTTPS URL
    (daily report +          (broker OAuth callbacks
     auth login links)        + dashboards)
```

---

## How the daily review works (8 AM IST)

1. `daily_review.py` wakes via launchd
2. Loads saved Paytm Money and Zerodha tokens
3. If a token is expired → posts a Slack login link → you tap it on your phone → broker login page opens → after login, the browser redirects to `/callback` (Zerodha) or `/paytm_callback` (Paytm) → token is encrypted and saved automatically → you see a green-tick page and close the tab
4. Fetches all holdings across both brokers
5. Runs concentration and FIRE gap analysis
6. Writes `mydata/{broker}_suggestions.txt` + encrypted snapshot
7. Posts the Slack summary

---

## Zerodha re-authentication flow (fully automatic)

Zerodha tokens expire daily around 3:30 AM. When the 8 AM review runs:

```
8 AM  daily_review detects expired token
       → Slack message posted: "Zerodha — login required" + link

You    tap link on phone → Zerodha login page → log in

        browser redirects to https://[tunnel-url]/callback?request_token=...

/callback  encrypts token immediately (Fernet, PBKDF2 480k iterations)
           saves to agent/brokers/.zerodha_request_token.enc
           deletes plaintext from memory
           shows "Authentication successful ✓" in browser

8 AM+  next daily_review decrypts token → completes session exchange
```

The request token never appears in any log file.

---

## What happens when your Mac restarts

The Cloudflare quick tunnel gets a new URL on every restart. The tunnel manager handles this automatically:

1. `tunnel_manager.py` starts, gets a new public URL
2. Saves URL to `.tunnel_url`
3. Pushes the new URL to Cloudflare KV, which the permanent Workers relay reads — so `https://portfolio-relay.pradeeprjilkapally.workers.dev` always points at the live tunnel
4. One manual step on a redirect-URL change: update your broker developer app Redirect URL to `[relay-url]/callback` (Zerodha) / `/paytm_callback` (Paytm)

---

## File structure

```
pyPMClient/
├── agent/
│   ├── auth.py              # Paytm Money session management
│   ├── portfolio.py         # Holdings aggregation (Paytm + Zerodha)
│   ├── rebalancer.py        # Concentration analysis + trade confirmation
│   ├── fire_analyser.py     # FIRE progress and gap analysis
│   ├── notify.py            # Slack sender (incoming webhook) + delivery confirmation
│   ├── daily_review.py      # 8 AM orchestrator (main entry point)
│   ├── crypto.py            # Fernet encryption for tokens + snapshots at rest
│   ├── webhook.py           # Flask server (/callback + /paytm_callback + dashboards + /health)
│   ├── tunnel_manager.py    # Cloudflare tunnel lifecycle + change detection
│   └── brokers/
│       └── zerodha.py       # Zerodha Kite Connect integration
├── mydata/
│   ├── my_investment_suggestions.txt   # Your FIRE roadmap and financial data
│   └── {broker}_suggestions.txt        # Written by daily_review at 8 AM
├── logs/
├── .env                     # All secrets — never commit
├── .tunnel_url              # Current public tunnel URL (auto-managed)
└── requirements.txt
```

---

## Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `PAYTM_API_KEY` | Paytm Money developer app key |
| `PAYTM_API_SECRET` | Paytm Money developer app secret |
| `ZERODHA_API_KEY` | Zerodha Kite Connect app key |
| `ZERODHA_API_SECRET` | Zerodha Kite Connect app secret |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook for all notifications |
| `DASHBOARD_USER` / `DASHBOARD_PASS` | HTTP Basic Auth for the dashboards |
| `WEBHOOK_ENCRYPTION_KEY` | Key for Fernet encryption of tokens + snapshots at rest |
| `WEBHOOK_PORT` | Flask port (default `5001`) |

---

## launchd services

| Label | Runs | Schedule |
|---|---|---|
| `com.pradeep.paytm-daily-review` | `daily_review.py` | 8:00 AM IST daily |
| `com.pradeep.zerodha-webhook` | `webhook.py` | Always on, auto-restarts |
| `com.pradeep.zerodha-tunnel` | `tunnel_manager.py` | Always on, auto-restarts |

```bash
launchctl list | grep pradeep        # status
tail -f logs/daily_review.log        # live logs
cat .tunnel_url                      # current public tunnel URL
```

---

## One-time setup checklist

- [x] Paytm Money developer app created, IP whitelisted
- [x] Zerodha Kite Connect app created
- [x] Slack incoming webhook created (`SLACK_WEBHOOK_URL` in `.env`)
- [x] cloudflared installed, tunnel running
- [ ] **Broker redirect URLs** — set the Zerodha (`developers.kite.trade`) and Paytm developer app Redirect URLs to the relay's `/callback` and `/paytm_callback`

---

## FIRE goal

| | |
|---|---|
| Target corpus | ₹2,25,00,000 (25× annual expenses) |
| Monthly investment | ₹1,27,000 |
| Expected return | 12% p.a. |
| Estimated years to FIRE | ~8 years |

---

## Security

- `.env` is never committed — all secrets stay local
- Broker tokens and portfolio snapshots are encrypted at rest (Fernet + PBKDF2, 480k iterations); request tokens are erased immediately after use
- Dashboards are gated by HTTP Basic Auth; the app binds to loopback and is reached only through the Cloudflare tunnel
- No trades execute without explicit per-trade confirmation in the terminal
