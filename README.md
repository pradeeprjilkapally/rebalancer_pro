# Portfolio Rebalancing Agent

A personal finance agent that monitors your equity and mutual fund portfolio across **Paytm Money** and **Zerodha**, tracks FIRE progress, suggests rebalancing actions, and delivers a daily report to WhatsApp — running entirely on your Mac with no cloud dependency.

**You retain full control** — the agent only suggests actions. No trades are placed without your explicit per-trade approval.

---

## What it does

- Fetches live holdings from Paytm Money (equity) and Zerodha (equity + mutual funds + active SIPs)
- Analyses concentration risk and flags positions that exceed 25% of portfolio
- Tracks progress toward your FIRE corpus (₹2.25 Cr target at 12% p.a.)
- Suggests FIRE-aligned investments in underweight categories (mid/small-cap, international, debt)
- Sends a daily WhatsApp summary at 8 AM IST via Twilio
- Handles Zerodha re-authentication fully automatically — no manual token copying

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Your Mac (3 always-on launchd services)                 │
│                                                          │
│  ┌─────────────────────┐   ┌──────────────────────────┐  │
│  │  daily_review.py    │   │  webhook.py (Flask :5001) │  │
│  │  fires at 8 AM IST  │   │  /callback  ← Zerodha    │  │
│  │                     │   │  /whatsapp  ← Twilio     │  │
│  └────────┬────────────┘   └────────────┬─────────────┘  │
│           │                             │                │
│     Paytm Money API             Cloudflare Tunnel        │
│     Zerodha Kite API            tunnel_manager.py        │
└───────────┼─────────────────────────────┼────────────────┘
            │                             │
            ▼                             ▼
    Twilio WhatsApp              Public HTTPS URL
    (daily report +         (Zerodha OAuth callback +
     auth requests)          Twilio inbound webhook)
```

---

## How the daily review works (8 AM IST)

1. `daily_review.py` wakes via launchd
2. Loads saved Paytm Money and Zerodha tokens
3. If Zerodha token is expired → sends a WhatsApp login link → you tap it on your phone → Zerodha login page opens → after login, Zerodha redirects to `/callback` → token is encrypted and saved automatically → you see a green tick page and close the tab
4. Fetches all holdings across both brokers
5. Runs concentration and FIRE gap analysis
6. Writes `mydata/daily_suggestions.txt`
7. Sends WhatsApp summary

---

## Zerodha re-authentication flow (fully automatic)

Zerodha tokens expire daily around 3:30 AM. When the 8 AM review runs:

```
8 AM  daily_review detects expired token
       → WhatsApp sent: "Zerodha Login Required — tap link"

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

1. `tunnel_manager.py` starts, gets new public URL
2. Saves URL to `.tunnel_url`
3. Detects the URL changed → updates Twilio webhook URL via API automatically
4. Sends you a WhatsApp message with the new URL and one manual step:
   - Update your Zerodha developer app Redirect URL to `[new-url]/callback` (30 seconds at `developers.kite.trade`)

---

## File structure

```
pyPMClient/
├── agent/
│   ├── auth.py              # Paytm Money session management
│   ├── portfolio.py         # Holdings aggregation (Paytm + Zerodha)
│   ├── rebalancer.py        # Concentration analysis + trade confirmation
│   ├── fire_analyser.py     # FIRE progress and gap analysis
│   ├── whatsapp.py          # Twilio WhatsApp sender + auth notifications
│   ├── daily_review.py      # 8 AM orchestrator (main entry point)
│   ├── crypto.py            # Fernet encryption for tokens at rest
│   ├── webhook.py           # Flask server (/callback + /whatsapp + /health)
│   ├── tunnel_manager.py    # Cloudflare tunnel lifecycle + change detection
│   └── brokers/
│       └── zerodha.py       # Zerodha Kite Connect integration
├── mydata/
│   ├── my_investment_suggestions.txt   # Your FIRE roadmap and financial data
│   └── daily_suggestions.txt          # Written by daily_review at 8 AM
├── logs/
│   ├── daily_review.log
│   ├── webhook.log
│   └── tunnel.log
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
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | Twilio sandbox number (`whatsapp:+14155238886`) |
| `TWILIO_WHATSAPP_TO` | Your WhatsApp number (`whatsapp:+91XXXXXXXXXX`) |
| `WEBHOOK_ENCRYPTION_KEY` | Key for Fernet encryption of Zerodha tokens at rest |
| `WEBHOOK_PORT` | Flask port (default `5001`) |

---

## launchd services

| Label | Runs | Schedule |
|---|---|---|
| `com.pradeep.paytm-daily-review` | `daily_review.py` | 8:00 AM IST daily |
| `com.pradeep.zerodha-webhook` | `webhook.py` | Always on, auto-restarts |
| `com.pradeep.zerodha-tunnel` | `tunnel_manager.py` | Always on, auto-restarts |

```bash
# Check status
launchctl list | grep pradeep

# View live logs
tail -f logs/daily_review.log
tail -f logs/webhook.log
tail -f logs/tunnel.log

# Current public tunnel URL
cat .tunnel_url
```

---

## One-time setup checklist

- [x] Paytm Money developer app created, IP whitelisted (`14.98.171.134`)
- [x] Zerodha Kite Connect app created
- [x] Twilio WhatsApp sandbox configured, phone number joined
- [x] cloudflared installed, tunnel running
- [ ] **Zerodha redirect URL** — go to `developers.kite.trade` → your app → set Redirect URL to `$(cat .tunnel_url)/callback`
- [ ] **Twilio sandbox webhook** — Twilio Console → Messaging → Try it out → WhatsApp → Sandbox Settings → "When a message comes in" → `$(cat .tunnel_url)/whatsapp`

---

## FIRE goal

| | |
|---|---|
| Target corpus | ₹2,25,00,000 (25× annual expenses of ₹9L) |
| Monthly investment | ₹1,27,000 |
| Expected return | 12% p.a. |
| Estimated years to FIRE | ~8–10 years |

Full allocation breakdown in `mydata/my_investment_suggestions.txt`.

---

## Security

- `.env` is never committed — all secrets stay local
- Zerodha request tokens are encrypted at rest (Fernet + PBKDF2, 480k iterations) and erased immediately after use
- Twilio inbound webhook validates every request using `X-Twilio-Signature` — requests from any other source are rejected (HTTP 403)
- Cloudflare tunnel uses QUIC (encrypted); Cloudflare handles TLS termination before forwarding to local Flask on `localhost`
- No trades execute without explicit per-trade confirmation in the terminal
