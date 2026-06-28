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


def _mention() -> str:
    """
    Slack mention prefix for action-required alerts. Uses the personal member ID
    (`SLACK_USER_ID`, e.g. U0123ABCD) for a direct @-ping; falls back to
    <!channel> so it still notifies even if the ID isn't configured.
    """
    uid = os.getenv('SLACK_USER_ID', '').strip()
    return f'<@{uid}> ' if uid else '<!channel> '


def notify(text: str, tag: bool = False) -> bool:
    """
    Post `text` to Slack. Returns True only on confirmed delivery (HTTP 200 'ok').
    When `tag` is True, prefixes an @-mention so an action-required alert pings you.
    Falls back to console output if the webhook is unset or the post fails.
    """
    url = _webhook()
    if tag:
        text = _mention() + text
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
    """
    Post a token/login-required alert that @-tags you and carries the tappable
    OAuth link — open it on your phone, log in, and the token resets via the
    callback. No laptop needed.
    """
    return notify(
        f"*{broker_label} — token needed* 🔑\n"
        f"The session expired. Tap on your phone to re-auth "
        f"(you'll be redirected automatically; the new token saves itself):\n{login_url}",
        tag=True,
    )


def _fallback_print(text: str):
    print('\n' + '=' * 60)
    print('PORTFOLIO AGENT (Slack fallback — console output)')
    print('=' * 60)
    print(text)
    print('=' * 60 + '\n')
