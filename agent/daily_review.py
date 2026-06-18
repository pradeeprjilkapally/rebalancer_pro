#!/usr/bin/env python3
"""
Daily portfolio review.
  --broker paytm   → Paytm Money only  (scheduled 7:45 AM IST)
  --broker zerodha → Zerodha only      (scheduled 8:00 AM IST)
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agent.rebalancer import analyse, print_portfolio, print_suggestions
from agent.fire_analyser import analyse_fire, fire_aligned_suggestions
from agent.whatsapp import send_whatsapp

_MYDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mydata')


# ---------------------------------------------------------------------------
# Shared: write suggestions file
# ---------------------------------------------------------------------------

def _write_file(broker: str, snapshot: dict, rebalance: list, fire: dict, fire_sugg: list) -> str:
    label = 'Paytm Money' if broker == 'paytm' else 'Zerodha'
    now   = datetime.now().strftime('%Y-%m-%d %H:%M IST')
    lines = [
        f"{label.upper()} PORTFOLIO REVIEW — {now}",
        "=" * 60, "",
        "FIRE PROGRESS", "-" * 40,
        f"Target corpus    : ₹{fire['target']:>15,.0f}",
        f"Current corpus   : ₹{fire['current']:>15,.0f}",
        f"Progress         : {fire['progress_pct']:>14.1f}%",
        f"Gap remaining    : ₹{fire['gap']:>15,.0f}",
        f"Est. years       : {fire['years_to_fire']:>14.1f} yrs",
        "",
        "CURRENT HOLDINGS", "-" * 40,
    ]

    for h in snapshot['holdings']:
        sign = "+" if h['unrealised_pnl'] >= 0 else ""
        lines.append(
            f"  {h['name']:<28} {h['quantity']:>6.0f} units"
            f"  LTP: ₹{h['ltp']:>8.2f}"
            f"  Value: ₹{h['current_value']:>10,.0f}"
            f"  Alloc: {h['allocation_pct']:>5.1f}%"
            f"  P&L: {sign}₹{h['unrealised_pnl']:>+,.0f}"
        )
    lines += [
        f"\n  Total equity   : ₹{snapshot['total_equity']:,.0f}",
        f"  Available cash : ₹{snapshot['available_cash']:,.0f}",
        f"  Total portfolio: ₹{snapshot['total_portfolio']:,.0f}",
        "",
    ]

    if rebalance:
        lines += ["REBALANCING SUGGESTIONS", "-" * 40]
        for s in rebalance:
            lines.append(f"  [{s['action']}] {s['quantity']} x {s['name']} @ ₹{s['ltp']:,.2f}")
            lines.append(f"        Est. value: ₹{s['estimated_value']:,.0f}")
            lines.append(f"        Reason: {s['reason']}")
        lines.append("")

    if fire_sugg:
        lines += ["FIRE-ALIGNED INVESTMENT SUGGESTIONS", "-" * 40]
        for s in fire_sugg:
            lines.append(f"  Category  : {s['category']}")
            lines.append(f"  Instrument: {s['instrument']}")
            lines.append(f"  Add SIP   : ₹{s['suggested_sip']:,}/month" if s['suggested_sip'] else "  Action: Review")
            lines.append(f"  Reason    : {s['reason']}")
            lines.append("")

    sips = snapshot.get('sips', [])
    if sips:
        lines += ["ACTIVE SIPs", "-" * 40]
        total = 0.0
        for s in sips:
            lines.append(f"  {s['fund']:<45} ₹{s['monthly_amount']:>8,.0f}/month  Next: {s['next_instalment']}")
            total += s['monthly_amount']
        lines += [f"\n  Total SIP: ₹{total:,.0f}/month", ""]

    if not rebalance and not fire_sugg:
        lines.append("Portfolio is well-balanced. No actions required today.")

    content = "\n".join(lines)
    os.makedirs(_MYDATA, exist_ok=True)
    path = os.path.join(_MYDATA, f'{broker}_suggestions.txt')
    with open(path, 'w') as f:
        f.write(content)
    print(f"  Suggestions written to: {path}")
    return content


# ---------------------------------------------------------------------------
# Shared: WhatsApp message formatter
# ---------------------------------------------------------------------------

def _format_whatsapp(broker: str, snapshot: dict, rebalance: list, fire: dict, fire_sugg: list) -> str:
    label    = 'Paytm Money' if broker == 'paytm' else 'Zerodha'
    holdings = snapshot['holdings']
    lines    = [
        f"*{label} — Daily Portfolio Review*",
        f"Total: ₹{snapshot['total_portfolio']:,.0f}  |  Cash: ₹{snapshot['available_cash']:,.0f}",
        "",
        "*Holdings:*",
    ]
    for h in holdings:
        sign = "+" if h['unrealised_pnl'] >= 0 else ""
        lines.append(
            f"• {h['name']}: {h['quantity']:.0f} units @ ₹{h['ltp']:,.2f}"
            f"  ({sign}₹{h['unrealised_pnl']:,.0f})  [{h['allocation_pct']:.1f}%]"
        )

    sips = snapshot.get('sips', [])
    if sips:
        lines += ["", "*Active SIPs:*"]
        for s in sips:
            lines.append(f"• {s['fund']}: ₹{s['monthly_amount']:,.0f}/month")

    lines += [
        "",
        "*FIRE Progress:*",
        f"Target : ₹{fire['target']:,.0f}",
        f"Current: ₹{fire['current']:,.0f}  ({fire['progress_pct']:.1f}%)",
        f"Gap    : ₹{fire['gap']:,.0f}",
        f"Est.   : ~{fire['years_to_fire']:.1f} yrs to FIRE",
    ]

    all_sugg = rebalance + [
        {'action': 'ADD SIP', 'name': s['instrument'],
         'quantity': 1, 'estimated_value': s['suggested_sip'], 'reason': s['reason']}
        for s in fire_sugg
    ]
    if all_sugg:
        lines += ["", "*Suggestions:*"]
        for s in all_sugg[:4]:
            lines.append(f"• {s['action']} {s['quantity']}× {s['name']}  (~₹{s['estimated_value']:,.0f})")
            lines.append(f"  _{s['reason']}_")
    else:
        lines += ["", "*No rebalancing needed today.*"]

    lines += ["", "_Reply to authorize any trade._"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Paytm Money review
# ---------------------------------------------------------------------------

def run_paytm():
    from pmClient.pmClient import PMClient
    from agent.auth import setup_session
    from agent.portfolio import build_snapshot

    api_key    = os.getenv('PAYTM_API_KEY', '').strip()
    api_secret = os.getenv('PAYTM_API_SECRET', '').strip()
    if not api_key or not api_secret:
        print("Error: PAYTM_API_KEY / PAYTM_API_SECRET not set.")
        sys.exit(1)

    pm = PMClient(api_secret=api_secret, api_key=api_key)
    if not setup_session(pm):
        print("Paytm Money auth failed — review aborted.")
        sys.exit(1)

    snapshot     = build_snapshot(pm, zerodha_data=None)
    if not snapshot['holdings']:
        print("  No Paytm Money holdings found.")
        sys.exit(0)

    print_portfolio(snapshot)
    rebalance  = analyse(snapshot)
    fire_data  = analyse_fire(snapshot)
    fire_sugg  = fire_aligned_suggestions(snapshot)
    print_suggestions(rebalance)

    print(f"\n  FIRE: {fire_data['progress_pct']:.1f}% — ~{fire_data['years_to_fire']:.1f} yrs to go")

    _write_file('paytm', snapshot, rebalance, fire_data, fire_sugg)
    send_whatsapp(_format_whatsapp('paytm', snapshot, rebalance, fire_data, fire_sugg))


# ---------------------------------------------------------------------------
# Zerodha review
# ---------------------------------------------------------------------------

def run_zerodha():
    from agent.brokers.zerodha import get_kite_client, fetch_all as zerodha_fetch_all
    from agent.portfolio import build_snapshot
    from pmClient.pmClient import PMClient
    from agent.auth import setup_session

    kite = get_kite_client()
    if not kite:
        print("  Zerodha auth pending — review skipped.")
        sys.exit(0)

    zerodha_data = zerodha_fetch_all(kite)
    eq  = len(zerodha_data.get('equity', []))
    mf  = len(zerodha_data.get('mf', []))
    sip = len(zerodha_data.get('sips', []))
    print(f"  Zerodha: {eq} equity, {mf} MF, {sip} SIP(s)")

    if not eq and not mf:
        print("  No Zerodha holdings found.")
        sys.exit(0)

    # Build snapshot from Zerodha data only (no Paytm)
    # Use a minimal PM client for funds_summary cash figure; skip gracefully if unavailable
    available_cash = 0.0
    try:
        api_key    = os.getenv('PAYTM_API_KEY', '').strip()
        api_secret = os.getenv('PAYTM_API_SECRET', '').strip()
        if api_key and api_secret:
            pm = PMClient(api_secret=api_secret, api_key=api_key)
            setup_session(pm)
    except Exception:
        pm = None

    holdings = zerodha_data.get('equity', []) + zerodha_data.get('mf', [])
    total_equity = sum(h['current_value'] for h in holdings)
    total_portfolio = total_equity + available_cash
    for h in holdings:
        h['allocation_pct'] = (h['current_value'] / total_portfolio * 100) if total_portfolio > 0 else 0.0
    holdings.sort(key=lambda x: x['current_value'], reverse=True)

    snapshot = {
        'holdings':        holdings,
        'total_equity':    total_equity,
        'available_cash':  available_cash,
        'total_portfolio': total_portfolio,
        'sips':            zerodha_data.get('sips', []),
    }

    print_portfolio(snapshot)
    rebalance  = analyse(snapshot)
    fire_data  = analyse_fire(snapshot)
    fire_sugg  = fire_aligned_suggestions(snapshot)
    print_suggestions(rebalance)

    print(f"\n  FIRE: {fire_data['progress_pct']:.1f}% — ~{fire_data['years_to_fire']:.1f} yrs to go")

    _write_file('zerodha', snapshot, rebalance, fire_data, fire_sugg)
    send_whatsapp(_format_whatsapp('zerodha', snapshot, rebalance, fire_data, fire_sugg))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--broker', choices=['paytm', 'zerodha'], default='paytm')
    args = parser.parse_args()

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {args.broker.title()} review starting...")

    if args.broker == 'paytm':
        run_paytm()
    else:
        run_zerodha()

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {args.broker.title()} review complete.")


if __name__ == '__main__':
    main()
