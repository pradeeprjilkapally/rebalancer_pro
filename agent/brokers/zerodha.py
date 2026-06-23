"""
Zerodha Kite Connect integration.
Uses the official kiteconnect Python library.
Auth tokens are saved daily — Zerodha tokens expire at 3:30 AM next day.

Headless auth flow:
  When running without a TTY (e.g. launchd at 8 AM), a WhatsApp message is sent
  with the login URL. Drop the request_token into REQUEST_TOKEN_FILE, then the
  next invocation completes the exchange automatically.
"""
import json
import os
import sys
import webbrowser
from typing import List

from kiteconnect import KiteConnect

TOKEN_FILE             = os.path.join(os.path.dirname(__file__), '.zerodha_tokens.json')
ENC_REQUEST_TOKEN_FILE = os.path.join(os.path.dirname(__file__), '.zerodha_request_token.enc')
PENDING_FILE           = os.path.join(os.path.dirname(__file__), '.zerodha_auth_pending')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _save_tokens(tokens: dict):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f)


def _load_tokens() -> dict:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return {}


def mark_pending(login_url: str):
    with open(PENDING_FILE, 'w') as f:
        f.write(login_url)


def clear_pending():
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)


def get_kite_client() -> KiteConnect | None:
    """Return an authenticated KiteConnect client, or None on failure."""
    api_key    = os.getenv('ZERODHA_API_KEY', '').strip()
    api_secret = os.getenv('ZERODHA_API_SECRET', '').strip()

    if not api_key or not api_secret:
        print("  [Zerodha] ZERODHA_API_KEY / ZERODHA_API_SECRET not set — skipping.")
        return None

    kite = KiteConnect(api_key=api_key)

    tokens = _load_tokens()
    if tokens.get('access_token'):
        kite.set_access_token(tokens['access_token'])
        try:
            kite.profile()
            clear_pending()   # auth is good — no pending action needed
            return kite
        except Exception:
            print("  [Zerodha] Saved token expired — re-authenticating...")

    return _login_flow(kite, api_secret)


def _login_flow(kite: KiteConnect, api_secret: str) -> KiteConnect | None:
    login_url = kite.login_url()

    # Check if a request_token was received via WhatsApp webhook (encrypted)
    if os.path.exists(ENC_REQUEST_TOKEN_FILE):
        try:
            from agent.crypto import decrypt_token
            with open(ENC_REQUEST_TOKEN_FILE, 'rb') as f:
                ciphertext = f.read()
            os.remove(ENC_REQUEST_TOKEN_FILE)   # delete before decrypting to minimise exposure
            request_token = decrypt_token(ciphertext)
            del ciphertext
            print("  [Zerodha] Found encrypted pending request_token — completing session exchange...")
            result = _exchange_token(kite, api_secret, request_token)
            del request_token
            return result
        except Exception as e:
            print(f"  [Zerodha] Failed to decrypt pending token: {e}")

    headless = not sys.stdin.isatty()

    if headless:
        mark_pending(login_url)
        print(f"  [Zerodha] Headless mode — sending auth ping to WhatsApp.")
        print(f"  [Zerodha] Login URL: {login_url}")
        try:
            from agent.whatsapp import send_auth_ping
            send_auth_ping(['Zerodha'])
        except Exception as e:
            print(f"  [Zerodha] WhatsApp send failed: {e}")
        print("  [Zerodha] Review skipped — waiting for YES reply.")
        return None

    # Interactive (TTY) mode
    print("\n  --- Zerodha Login ---")
    print(f"  Login URL:\n\n    {login_url}\n")
    print("  After logging in, copy the 'request_token' from the redirect URL.\n")
    try:
        ans = input("  Open browser now? (y/n): ").strip().lower()
        if ans == 'y':
            webbrowser.open(login_url)
        request_token = input("  Paste request_token: ").strip()
    except KeyboardInterrupt:
        return None

    return _exchange_token(kite, api_secret, request_token) if request_token else None


def _exchange_token(kite: KiteConnect, api_secret: str, request_token: str) -> KiteConnect | None:
    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        kite.set_access_token(session['access_token'])
        _save_tokens({'access_token': session['access_token']})
        clear_pending()
        print("  [Zerodha] Login successful.")
        return kite
    except Exception as e:
        print(f"  [Zerodha] Token exchange failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def fetch_equity_holdings(kite: KiteConnect) -> List[dict]:
    """Fetch equity holdings from Zerodha Demat."""
    try:
        raw = kite.holdings()
    except Exception as e:
        print(f"  [Zerodha] holdings() failed: {e}")
        return []

    holdings = []
    for h in raw:
        qty = float(h.get('quantity', 0))
        if qty <= 0:
            continue
        avg  = float(h.get('average_price', 0))
        ltp  = float(h.get('last_price', 0) or avg)
        holdings.append({
            'source':        'zerodha',
            'name':          h.get('tradingsymbol', ''),
            'security_id':   h.get('instrument_token', ''),
            'isin':          h.get('isin', ''),
            'exchange':      h.get('exchange', 'NSE'),
            'quantity':      qty,
            'avg_price':     avg,
            'ltp':           ltp,
            'current_value': qty * ltp,
            'cost_value':    qty * avg,
            'unrealised_pnl': (ltp - avg) * qty,
        })
    return holdings


def fetch_mf_holdings(kite: KiteConnect) -> List[dict]:
    """Fetch mutual fund holdings (executed SIP units) from Zerodha Coin."""
    try:
        raw = kite.mf_holdings()
    except Exception as e:
        print(f"  [Zerodha] mf_holdings() failed: {e}")
        return []

    holdings = []
    for h in raw:
        qty  = float(h.get('quantity', 0))
        avg  = float(h.get('average_price', 0))
        nav  = float(h.get('last_price', 0) or avg)
        holdings.append({
            'source':        'zerodha_mf',
            'name':          h.get('fund', h.get('tradingsymbol', '')),
            'security_id':   h.get('tradingsymbol', ''),
            'isin':          h.get('isin', ''),
            'exchange':      'MF',
            'quantity':      qty,
            'avg_price':     avg,
            'ltp':           nav,
            'current_value': qty * nav,
            'cost_value':    qty * avg,
            'unrealised_pnl': (nav - avg) * qty,
        })
    return holdings


def fetch_active_sips(kite: KiteConnect) -> List[dict]:
    """Fetch active SIP mandates from Zerodha Coin."""
    try:
        raw = kite.mf_sips()
    except Exception as e:
        print(f"  [Zerodha] mf_sips() failed: {e}")
        return []

    sips = []
    for s in raw:
        if s.get('status') != 'active':
            continue
        sips.append({
            'source':          'zerodha',
            'fund':            s.get('fund', ''),
            'monthly_amount':  float(s.get('instalment_amount', 0)),
            'frequency':       s.get('frequency', 'monthly'),
            'next_instalment': s.get('next_instalment', ''),
            'status':          s.get('status', ''),
        })
    return sips


def fetch_all(kite: KiteConnect) -> dict:
    """Return equity holdings, MF holdings, and active SIPs in one call."""
    return {
        'equity':   fetch_equity_holdings(kite),
        'mf':       fetch_mf_holdings(kite),
        'sips':     fetch_active_sips(kite),
    }
