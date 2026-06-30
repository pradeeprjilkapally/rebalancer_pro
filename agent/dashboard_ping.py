"""
Dashboard ping — sends a compact Slack snapshot 3× daily.
Scheduled at 7:50 AM, 12:00 PM, 3:00 PM IST via launchd.

Refreshes broker snapshots first, reads the encrypted dashboard data for broker
totals, fetches live MF NAV and gold price for manual holdings, and sends a
single link-first message to Slack.

Separate from the morning review notification (which includes suggestions).
"""
import argparse
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

_REPO    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MYDATA  = os.path.join(_REPO, 'mydata')
_RELAY   = os.getenv('WORKERS_RELAY_URL', 'https://portfolio-relay.pradeeprjilkapally.workers.dev')


def _load_snapshot(broker: str) -> dict:
    enc_path = os.path.join(_MYDATA, f'{broker}_data.json.enc')
    try:
        from agent.crypto import read_encrypted
        return read_encrypted(enc_path)
    except FileNotFoundError:
        legacy = os.path.join(_MYDATA, f'{broker}_data.json')
        try:
            return json.load(open(legacy))
        except Exception:
            return {}
    except Exception as e:
        print(f'[ping] could not load {broker} snapshot: {e}')
        return {}


def refresh_snapshots() -> None:
    """Refresh broker dashboard snapshots without sending review summaries."""
    from agent import daily_review

    for broker, runner in (('paytm', daily_review.run_paytm), ('zerodha', daily_review.run_zerodha)):
        try:
            print(f'[ping] refreshing {broker} snapshot')
            runner(send_slack=False)
        except SystemExit as e:
            print(f'[ping] {broker} refresh exited: {e.code}')
        except Exception as e:
            print(f'[ping] {broker} refresh failed: {e}')


def _manual_values() -> dict:
    """Fetch live MF NAV and gold price; return totals for manual holdings."""
    try:
        from agent.manual_holdings import _fetch_navs_amfi
        from agent.gold_price import get_price as gold_price

        manual_file = os.path.join(_MYDATA, 'manual_holdings.json')
        if not os.path.exists(manual_file):
            return {}
        manual = json.load(open(manual_file))

        mf_value    = 0.0
        mf_invested = 0.0
        scheme_codes = [
            str(mf.get('scheme_code', '')).strip()
            for mf in manual.get('mutual_funds', [])
            if float(mf.get('units', 0) or 0) > 0
        ]
        if scheme_codes:
            nav_map = _fetch_navs_amfi(scheme_codes)
            for mf in manual.get('mutual_funds', []):
                units    = float(mf.get('units', 0) or 0)
                invested = float(mf.get('invested', 0) or 0)
                nav      = nav_map.get(str(mf.get('scheme_code', '')).strip(), 0)
                if units > 0 and nav > 0:
                    mf_value    += units * nav
                    mf_invested += invested

        gold_value    = 0.0
        gold_invested = 0.0
        gold_grams    = 0.0
        gprice = gold_price()
        for g in manual.get('gold', []):
            grams    = float(g.get('grams', 0) or 0)
            invested = float(g.get('invested', 0) or 0)
            if grams > 0 and gprice:
                gold_value    += grams * gprice
                gold_invested += invested
                gold_grams    += grams

        return {
            'mf_value':     mf_value,
            'mf_invested':  mf_invested,
            'gold_value':   gold_value,
            'gold_invested': gold_invested,
            'gold_grams':   gold_grams,
        }
    except Exception as e:
        print(f'[ping] manual values failed: {e}')
        return {}


def _fmt_pnl(value: float, invested: float) -> str:
    if invested <= 0:
        return ''
    pnl_pct = (value - invested) / invested * 100
    sign    = '+' if pnl_pct >= 0 else ''
    return f'{sign}{pnl_pct:.1f}%'


def _broker_total(data: dict) -> float:
    snapshot = data.get('snapshot', {})
    holdings = snapshot.get('holdings', [])
    equity = sum(
        h.get('current_value', 0)
        for h in holdings
        if h.get('source', 'broker') not in ('manual_gold', 'manual_mf')
    )
    return equity + snapshot.get('available_cash', 0)


def build_message(label: str) -> str:
    paytm   = _load_snapshot('paytm')
    zerodha = _load_snapshot('zerodha')
    manual  = _manual_values()

    paytm_total   = _broker_total(paytm)
    zerodha_total = _broker_total(zerodha)
    mf_value      = manual.get('mf_value', 0)
    gold_value    = manual.get('gold_value', 0)

    total = paytm_total + zerodha_total + mf_value + gold_value

    lines = [f'*Portfolio — {label}*']

    broker_parts = []
    if paytm_total > 0:
        broker_parts.append(f'Paytm ₹{paytm_total:,.0f}')
    if zerodha_total > 0:
        broker_parts.append(f'Zerodha ₹{zerodha_total:,.0f}')
    if broker_parts:
        lines.append('  '.join(broker_parts))

    manual_parts = []
    if mf_value > 0:
        tag = _fmt_pnl(mf_value, manual.get('mf_invested', 0))
        manual_parts.append(f'MF ₹{mf_value:,.0f} ({tag})')
    if gold_value > 0:
        tag = _fmt_pnl(gold_value, manual.get('gold_invested', 0))
        manual_parts.append(f'Gold ₹{gold_value:,.0f} ({tag})')
    if manual_parts:
        lines.append('  '.join(manual_parts))

    lines.append(f'*Total ₹{total:,.0f}*')
    lines.append('')
    lines.append(f'{_RELAY}/dashboard_main')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-refresh', action='store_true',
                        help='Send the Slack ping from the last encrypted snapshots only.')
    args = parser.parse_args()

    now   = datetime.now()
    label = now.strftime('%-I:%M %p IST')

    if not args.skip_refresh:
        refresh_snapshots()

    try:
        msg = build_message(label)
    except Exception as e:
        print(f'[ping] build_message failed: {e}')
        sys.exit(1)

    print(f'[ping] {label}')
    print(msg)

    try:
        from agent.notify import notify
        import threading
        t = threading.Thread(target=notify, args=(msg,), daemon=True)
        t.start()
        t.join(timeout=15)
    except Exception as e:
        print(f'[ping] send failed: {e}')


if __name__ == '__main__':
    main()
