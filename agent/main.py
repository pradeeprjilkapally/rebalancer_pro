#!/usr/bin/env python3
"""
Paytm Money Portfolio Rebalancer
Usage:
    python -m agent.main              # run rebalancer
    python -m agent.main --logout     # clear saved tokens
"""
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pmClient.pmClient import PMClient
from agent.auth import setup_session, clear_session
from agent.portfolio import build_snapshot
from agent.rebalancer import analyse, print_portfolio, print_suggestions, confirm_and_execute

load_dotenv()


def main():
    if '--logout' in sys.argv:
        clear_session()
        return

    api_key = os.getenv('PAYTM_API_KEY', '').strip()
    api_secret = os.getenv('PAYTM_API_SECRET', '').strip()

    if not api_key or not api_secret:
        print("Error: PAYTM_API_KEY and PAYTM_API_SECRET must be set in your .env file.")
        sys.exit(1)

    pm = PMClient(api_secret=api_secret, api_key=api_key)

    print("Paytm Money Portfolio Rebalancer")
    print("=" * 34)

    if not setup_session(pm):
        print("Authentication failed.")
        sys.exit(1)

    print("\nFetching portfolio data...")
    snapshot = build_snapshot(pm)

    if not snapshot['holdings']:
        print("No holdings found in your account.")
        sys.exit(0)

    print_portfolio(snapshot)

    suggestions = analyse(snapshot)
    print_suggestions(suggestions)

    if suggestions:
        confirm_and_execute(pm, suggestions)
    else:
        print("\nNothing to do.")


if __name__ == '__main__':
    main()
