"""
9 AM IST reminder job — runs only if auth is still pending for either broker.
Sends one combined nudge; does nothing if both brokers are authenticated.

Scheduled via: com.pradeep.auth-reminder launchd plist
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agent.auth import PENDING_FILE as _PAYTM_PENDING
from agent.brokers.zerodha import PENDING_FILE as _ZERODHA_PENDING
from agent.notify import notify_auth_needed


def _pending_url(path: str) -> str | None:
    """Return the saved login URL from a pending sentinel, or None if absent."""
    if not os.path.isfile(path):
        return None
    return open(path).read().strip() or None


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auth reminder check...")

    pending = [(b, u) for b, u in (
        ('Paytm Money', _pending_url(_PAYTM_PENDING)),
        ('Zerodha',     _pending_url(_ZERODHA_PENDING)),
    ) if u]

    if not pending:
        print("  All sessions authenticated — nothing to remind.")
        return

    print(f"  Pending auth for: {', '.join(b for b, _ in pending)} — posting reminders to Slack.")
    for broker, url in pending:
        sent = notify_auth_needed(broker, url)
        print(f"  {'Sent' if sent else 'FAILED'}: {broker}")


if __name__ == '__main__':
    main()
