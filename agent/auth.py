import json
import os
import sys
import webbrowser

from agent.crypto import read_encrypted, write_encrypted

TOKEN_FILE   = os.path.join(os.path.dirname(__file__), '.tokens.json.enc')
_LEGACY_FILE = os.path.join(os.path.dirname(__file__), '.tokens.json')
PENDING_FILE = os.path.join(os.path.dirname(__file__), '.paytm_auth_pending')


def _save_tokens(tokens: dict):
    """Persist Paytm session tokens encrypted at rest (0600)."""
    write_encrypted(TOKEN_FILE, tokens)


def _load_tokens() -> dict:
    if os.path.exists(TOKEN_FILE):
        try:
            return read_encrypted(TOKEN_FILE)
        except Exception:
            return {}
    # One-time migration: encrypt any legacy plaintext token file, then delete it.
    if os.path.exists(_LEGACY_FILE):
        try:
            with open(_LEGACY_FILE) as f:
                tokens = json.load(f)
            _save_tokens(tokens)
            os.remove(_LEGACY_FILE)
            return tokens
        except Exception:
            return {}
    return {}


def mark_pending(login_url: str):
    """Write sentinel so the reminder job and webhook know auth is needed."""
    with open(PENDING_FILE, 'w') as f:
        f.write(login_url)


def clear_pending():
    """Remove sentinel after successful auth."""
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)


def setup_session(pm) -> bool:
    """Try saved tokens first; fall back to login flow."""
    tokens = _load_tokens()
    if tokens.get('access_token'):
        pm.set_access_token(tokens['access_token'])
        pm.set_public_access_token(tokens.get('public_access_token', ''))
        pm.set_read_access_token(tokens.get('read_access_token', ''))
        try:
            pm.get_user_details()
            print("  [Paytm] Session restored from saved tokens.")
            clear_pending()   # auth is good — no pending action needed
            return True
        except Exception:
            print("  [Paytm] Saved tokens expired — re-authenticating...")

    return _login_flow(pm)


def _login_flow(pm) -> bool:
    state_key = f"rebalance_{os.getpid()}"
    login_url = pm.login(state_key)
    headless  = not sys.stdin.isatty()

    if headless:
        mark_pending(login_url)
        print(f"  [Paytm] Headless mode — sending auth ping to WhatsApp.")
        try:
            from agent.whatsapp import send_auth_ping
            send_auth_ping(['Paytm Money'])
        except Exception as e:
            print(f"  [Paytm] WhatsApp send failed: {e}")
            print(f"  [Paytm] Login URL: {login_url}")
        print("  [Paytm] Review skipped — waiting for YES reply.")
        return False

    # Interactive (TTY) mode
    print("\n--- Paytm Money Login ---")
    print(f"Login URL:\n\n  {login_url}\n")
    print("After logging in with your credentials + OTP, you will be redirected.")
    print("Copy the 'request_token' value from the redirect URL.\n")

    try:
        ans = input("Open browser now? (y/n): ").strip().lower()
        if ans == 'y':
            webbrowser.open(login_url)
        request_token = input("\nPaste request_token: ").strip()
    except (KeyboardInterrupt, EOFError):
        return False

    return _exchange_token(pm, request_token)


def _exchange_token(pm, request_token: str) -> bool:
    """Exchange a request_token for session tokens and persist them."""
    if not request_token:
        print("  [Paytm] No token provided.")
        return False
    try:
        resp = pm.generate_session(request_token)
        _save_tokens({
            'access_token':        resp.get('access_token', ''),
            'public_access_token': resp.get('public_access_token', ''),
            'read_access_token':   resp.get('read_access_token', ''),
        })
        pm.set_access_token(resp.get('access_token', ''))
        pm.set_public_access_token(resp.get('public_access_token', ''))
        pm.set_read_access_token(resp.get('read_access_token', ''))
        clear_pending()
        print("  [Paytm] Login successful.")
        return True
    except Exception as e:
        print(f"  [Paytm] Login failed: {e}")
        return False


def clear_session():
    """Delete saved tokens to force re-login next run."""
    removed = False
    for f in (TOKEN_FILE, _LEGACY_FILE):
        if os.path.exists(f):
            os.remove(f)
            removed = True
    if removed:
        print("Session cleared.")
