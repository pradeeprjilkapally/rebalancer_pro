from typing import List

# Any single position above this % of total portfolio is flagged as overweight.
CONCENTRATION_LIMIT = 25.0
# Suggested target after trimming an overweight position.
TRIM_TARGET_PCT = 20.0


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_portfolio(snapshot: dict):
    h_list = snapshot['holdings']
    W = 78

    print("\n" + "=" * W)
    print(f"  {'STOCK':<26} {'QTY':>7} {'AVG COST':>10} {'LTP':>10} {'VALUE':>12} {'ALLOC':>7} {'P&L':>10}")
    print("-" * W)

    for h in h_list:
        flag = " !" if h['allocation_pct'] > CONCENTRATION_LIMIT else "  "
        pnl_str = f"{h['unrealised_pnl']:>+,.0f}"
        print(
            f"  {h['name']:<24}{flag}"
            f"{h['quantity']:>7.0f}"
            f"{h['avg_price']:>10.2f}"
            f"{h['ltp']:>10.2f}"
            f"{h['current_value']:>12,.0f}"
            f"{h['allocation_pct']:>6.1f}%"
            f"  {pnl_str:>10}"
        )

    print("-" * W)
    print(f"  {'Equity total':<26} {'':>7} {'':>10} {'':>10} {snapshot['total_equity']:>12,.0f}")
    print(f"  {'Available cash':<26} {'':>7} {'':>10} {'':>10} {snapshot['available_cash']:>12,.0f}")
    print(f"  {'TOTAL PORTFOLIO':<26} {'':>7} {'':>10} {'':>10} {snapshot['total_portfolio']:>12,.0f}")
    print("=" * W)
    if any(h['allocation_pct'] > CONCENTRATION_LIMIT for h in h_list):
        print(f"  ! = position exceeds {CONCENTRATION_LIMIT:.0f}% concentration limit")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(snapshot: dict) -> List[dict]:
    """
    V1 rule: flag any position above CONCENTRATION_LIMIT and suggest
    trimming it down to TRIM_TARGET_PCT of total portfolio value.
    """
    suggestions = []
    total = snapshot['total_portfolio']
    if total <= 0:
        return suggestions

    for h in snapshot['holdings']:
        if h.get('source') in ('manual_mf', 'manual_chit'):
            continue
        if h['allocation_pct'] > CONCENTRATION_LIMIT and h['ltp'] > 0:
            target_value = total * (TRIM_TARGET_PCT / 100)
            excess_value = h['current_value'] - target_value
            qty_to_sell = int(excess_value / h['ltp'])
            if qty_to_sell > 0 and qty_to_sell <= h['quantity']:
                suggestions.append({
                    'action': 'SELL',
                    'name': h['name'],
                    'security_id': h['security_id'],
                    'isin': h['isin'],
                    'exchange': h['exchange'],
                    'quantity': qty_to_sell,
                    'ltp': h['ltp'],
                    'estimated_value': qty_to_sell * h['ltp'],
                    'reason': (
                        f"Overweight at {h['allocation_pct']:.1f}% "
                        f"(limit {CONCENTRATION_LIMIT:.0f}% → trim to {TRIM_TARGET_PCT:.0f}%)"
                    ),
                })

    return suggestions


def print_suggestions(suggestions: List[dict]):
    if not suggestions:
        print("\nNo rebalancing needed — all positions within concentration limits.")
        return

    print(f"\n--- {len(suggestions)} Rebalancing Suggestion(s) ---")
    for i, s in enumerate(suggestions, 1):
        print(
            f"\n  [{i}] {s['action']}  {s['quantity']:,} x {s['name']}"
            f"  @  ₹{s['ltp']:,.2f}"
            f"  ≈  ₹{s['estimated_value']:,.0f}"
        )
        print(f"       {s['reason']}")


# ---------------------------------------------------------------------------
# eDIS TPIN flow (required for CNC sell on NSE/BSE)
# ---------------------------------------------------------------------------

def _edis_flow(pm, isin_list: List[str]) -> bool:
    """
    Paytm Money requires eDIS authorisation before CNC sell orders.
    Guides the user through TPIN generation + validation.
    """
    print("\n  CNC sell orders require eDIS authorisation (TPIN).")
    try:
        ans = input("  Generate TPIN OTP on your registered mobile now? (y/n): ").strip().lower()
    except KeyboardInterrupt:
        return False

    if ans != 'y':
        print("  eDIS skipped — sell orders will not be placed.")
        return False

    try:
        pm.generate_tpin()
        print("  OTP sent to your registered mobile number.")
        tpin = input("  Enter TPIN/OTP: ").strip()
        isin_objects = [{'isin': isin, 'quantity': 1} for isin in isin_list]
        pm.validate_tpin(trade_type='S', isin_list=isin_objects)
        print("  eDIS authorisation successful.")
        return True
    except Exception as e:
        print(f"  eDIS failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Execution (user must confirm each trade)
# ---------------------------------------------------------------------------

def confirm_and_execute(pm, suggestions: List[dict]):
    if not suggestions:
        return

    print("\n--- Trade Authorisation ---")
    print("You will be asked to confirm each trade individually.")
    print("Type 'y' to execute, anything else to skip.\n")

    # Determine which trades are CNC sells and run eDIS once upfront
    sell_isins = list({s['isin'] for s in suggestions if s['action'] == 'SELL' and s['isin']})
    edis_ok = False
    if sell_isins:
        edis_ok = _edis_flow(pm, sell_isins)
        if not edis_ok:
            print("\n  Sell orders require eDIS. Skipping all sell suggestions.")

    executed, skipped = [], []

    for s in suggestions:
        if s['action'] == 'SELL' and not edis_ok:
            skipped.append(s)
            continue

        prompt = (
            f"  {s['action']} {s['quantity']:,} × {s['name']}"
            f" @ ~₹{s['ltp']:,.2f}  (≈ ₹{s['estimated_value']:,.0f})? [y/skip]: "
        )
        try:
            answer = input(prompt).strip().lower()
        except KeyboardInterrupt:
            print("\nAborted.")
            break

        if answer == 'y':
            try:
                result = pm.place_order(
                    txn_type='S' if s['action'] == 'SELL' else 'B',
                    exchange=s['exchange'],
                    segment='E',
                    product='C',       # CNC (delivery / long-term holding)
                    security_id=s['security_id'],
                    quantity=s['quantity'],
                    validity='DAY',
                    order_type='MKT',
                    price=0,
                    source='W',
                )
                print(f"    Order placed: {result}\n")
                executed.append(s)
            except Exception as e:
                print(f"    Order failed: {e}\n")
        else:
            print("    Skipped.\n")
            skipped.append(s)

    print(f"Done — {len(executed)} executed, {len(skipped)} skipped.")
