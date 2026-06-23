"""
Pre-flight session validator.

Silently tests Paytm, Zerodha, and tunnel connectivity using saved tokens.
Never triggers a login flow, never sends WhatsApp, never writes sentinel files.

Usage:
    from agent.preflight import validate_all
    status = validate_all()
    # status = {
    #   'paytm':   {'ok': True,  'detail': ''},
    #   'zerodha': {'ok': False, 'detail': 'token expired'},
    #   'tunnel':  {'ok': True,  'detail': ''},
    # }
"""
import json
import os
import requests

_TIMEOUT = 6
_RELAY   = os.getenv('WORKERS_RELAY_URL', '').rstrip('/')


# ---------------------------------------------------------------------------
# Individual checks — never side-effect, never prompt, never send messages
# ---------------------------------------------------------------------------

def _check_paytm() -> tuple[bool, str]:
    token_path = os.path.join(os.path.dirname(__file__), '.tokens.json')
    if not os.path.exists(token_path):
        return False, 'no saved tokens'
    try:
        tokens = json.load(open(token_path))
    except Exception:
        return False, 'tokens file unreadable'
    access_token = tokens.get('access_token', '')
    if not access_token:
        return False, 'access_token missing in tokens file'

    api_key    = os.getenv('PAYTM_API_KEY', '').strip()
    api_secret = os.getenv('PAYTM_API_SECRET', '').strip()
    if not api_key or not api_secret:
        return False, 'PAYTM_API_KEY / PAYTM_API_SECRET not set'

    try:
        from pmClient.pmClient import PMClient
        pm = PMClient(api_secret=api_secret, api_key=api_key)
        pm.set_access_token(access_token)
        pm.set_public_access_token(tokens.get('public_access_token', ''))
        pm.set_read_access_token(tokens.get('read_access_token', ''))
        pm.get_user_details()
        return True, ''
    except Exception as e:
        return False, f'session test failed: {e}'


def _check_zerodha() -> tuple[bool, str]:
    token_path = os.path.join(os.path.dirname(__file__), 'brokers', '.zerodha_tokens.json')
    if not os.path.exists(token_path):
        return False, 'no saved tokens'
    try:
        tokens = json.load(open(token_path))
    except Exception:
        return False, 'tokens file unreadable'
    access_token = tokens.get('access_token', '')
    if not access_token:
        return False, 'access_token missing in tokens file'

    api_key = os.getenv('ZERODHA_API_KEY', '').strip()
    if not api_key:
        return False, 'ZERODHA_API_KEY not set'

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        kite.profile()
        return True, ''
    except Exception as e:
        return False, f'session test failed: {e}'


def _check_tunnel() -> tuple[bool, str]:
    if not _RELAY:
        return False, 'WORKERS_RELAY_URL not set'
    try:
        r = requests.get(f'{_RELAY}/health', timeout=_TIMEOUT)
        if r.status_code == 200:
            return True, ''
        return False, f'relay returned HTTP {r.status_code}'
    except Exception as e:
        return False, f'relay unreachable: {e}'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_all(verbose: bool = False) -> dict:
    """
    Run all pre-flight checks. Returns status dict.
    Set verbose=True to print a summary line per check.
    Never triggers auth flows or sends messages.
    """
    checks = {
        'paytm':   _check_paytm,
        'zerodha': _check_zerodha,
        'tunnel':  _check_tunnel,
    }
    results = {}
    for name, fn in checks.items():
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f'check crashed: {e}'
        results[name] = {'ok': ok, 'detail': detail}
        if verbose:
            status = 'OK  ' if ok else 'FAIL'
            print(f'  [preflight] [{status}] {name}' + (f' — {detail}' if detail else ''))
    return results


def needs_auth(results: dict) -> list[str]:
    """Return list of broker names that need re-authentication."""
    brokers = []
    if not results.get('paytm', {}).get('ok'):
        brokers.append('Paytm Money')
    if not results.get('zerodha', {}).get('ok'):
        brokers.append('Zerodha')
    return brokers


def summary(results: dict) -> str:
    """One-line human-readable summary of pre-flight results."""
    parts = []
    for name, r in results.items():
        icon = 'OK' if r['ok'] else f'FAIL ({r["detail"]})'
        parts.append(f'{name}: {icon}')
    return ' | '.join(parts)
