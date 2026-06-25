"""
Slack notifications via an incoming webhook (replaces the Twilio/WhatsApp sender).

Unlike WhatsApp free-form messages (which silently fail outside a 24h window),
a Slack webhook returns HTTP 200 + body "ok" only when the message is actually
posted to the channel — so `notify()` reports TRUE delivery, never a blind
"queued" guess.
"""
import os

import requests

_TIMEOUT = 15


def _webhook() -> str:
    return os.getenv('SLACK_WEBHOOK_URL', '').strip()


def notify(text: str) -> bool:
    """
    Post `text` to Slack. Returns True only on confirmed delivery (HTTP 200 'ok').
    Falls back to console output if the webhook is unset or the post fails.
    """
    url = _webhook()
    if not url:
        print('  [Slack] SLACK_WEBHOOK_URL not set — printing to console.')
        _fallback_print(text)
        return False
    try:
        r = requests.post(url, json={'text': text}, timeout=_TIMEOUT)
        ok = (r.status_code == 200 and r.text == 'ok')
        if ok:
            print('  [Slack] delivered ✓')
        else:
            print(f'  [Slack] NOT delivered — HTTP {r.status_code}: {r.text[:120]}')
            _fallback_print(text)
        return ok
    except Exception as e:
        print(f'  [Slack] send failed: {e}')
        _fallback_print(text)
        return False


def notify_auth_needed(broker_label: str, login_url: str) -> bool:
    """Post a login-required alert with the tappable OAuth link (one-way)."""
    return notify(
        f"*{broker_label} — login required*\n"
        f"Your session expired and the review was skipped.\n"
        f"Tap to log in (you'll be redirected automatically):\n{login_url}"
    )


def _fallback_print(text: str):
    print('\n' + '=' * 60)
    print('PORTFOLIO AGENT (Slack fallback — console output)')
    print('=' * 60)
    print(text)
    print('=' * 60 + '\n')
