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
from agent.whatsapp import send_auth_reminder


def _pending(path: str) -> bool:
    return os.path.isfile(path)


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Auth reminder check...")

    brokers = []
    if _pending(_PAYTM_PENDING):
        brokers.append('Paytm Money')
    if _pending(_ZERODHA_PENDING):
        brokers.append('Zerodha')

    if not brokers:
        print("  All sessions authenticated — nothing to remind.")
        return

    print(f"  Pending auth for: {', '.join(brokers)} — sending separate reminders.")
    for broker in brokers:
        sent = send_auth_reminder([broker])
        print(f"  {'Sent' if sent else 'FAILED'}: {broker}")


if __name__ == '__main__':
    main()
