import json
import os
import webbrowser

TOKEN_FILE = os.path.join(os.path.dirname(__file__), '.tokens.json')


def _save_tokens(tokens: dict):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f)


def _load_tokens() -> dict:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return {}


def setup_session(pm) -> bool:
    """Try saved tokens first; fall back to full browser login flow."""
    tokens = _load_tokens()
    if tokens.get('access_token'):
        pm.set_access_token(tokens['access_token'])
        pm.set_public_access_token(tokens.get('public_access_token', ''))
        pm.set_read_access_token(tokens.get('read_access_token', ''))
        try:
            pm.get_user_details()
            print("Session restored from saved tokens.")
            return True
        except Exception:
            print("Saved tokens expired — starting fresh login...")

    return _login_flow(pm)


def _login_flow(pm) -> bool:
    """Full browser-based login. The request_token must be pasted by the user."""
    state_key = f"rebalance_{os.getpid()}"
    login_url = pm.login(state_key)

    print("\n--- Paytm Money Login ---")
    print(f"Login URL:\n\n  {login_url}\n")
    print("After logging in with your credentials + OTP, you will be redirected.")
    print("Copy the 'request_token' value from the redirect URL.\n")

    try:
        ans = input("Open browser now? (y/n): ").strip().lower()
        if ans == 'y':
            webbrowser.open(login_url)
    except KeyboardInterrupt:
        return False

    try:
        request_token = input("\nPaste request_token: ").strip()
    except KeyboardInterrupt:
        return False

    if not request_token:
        print("No token provided.")
        return False

    try:
        resp = pm.generate_session(request_token)
        _save_tokens({
            'access_token': resp.get('access_token', ''),
            'public_access_token': resp.get('public_access_token', ''),
            'read_access_token': resp.get('read_access_token', ''),
        })
        print("Login successful.")
        return True
    except Exception as e:
        print(f"Login failed: {e}")
        return False


def clear_session():
    """Delete saved tokens to force re-login next run."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print("Session cleared.")
