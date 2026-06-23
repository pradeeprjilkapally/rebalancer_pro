from typing import List


def _extract_list(resp) -> List[dict]:
    """Walk Paytm Money response shapes to find the holdings list."""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        # Shape: { data: { results: [...] } }
        data = resp.get('data')
        if isinstance(data, dict):
            for key in ('results', 'holdings', 'holding', 'data'):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        # Shape: { data: [...] }
        if isinstance(data, list):
            return data
        # Shape: { results: [...] }
        for key in ('results', 'holdings', 'holding'):
            val = resp.get(key)
            if isinstance(val, list):
                return val
    return []


def fetch_holdings(pm) -> List[dict]:
    """Fetch holdings. LTP is already included in the holdings response."""
    resp = pm.user_holdings_data()
    raw = _extract_list(resp)

    if not raw:
        return []

    raw = [h for h in raw if isinstance(h, dict)]

    holdings = []
    for h in raw:
        # Actual field names from Paytm Money API
        # Prefer NSE security_id; fall back to BSE
        sid = str(h.get('nse_security_id') or h.get('bse_security_id') or '')
        exchange = 'NSE' if h.get('nse_security_id') else 'BSE'

        qty  = float(h.get('quantity') or 0)
        avg  = float(h.get('cost_price') or 0)
        ltp  = float(h.get('last_traded_price') or h.get('pc') or avg)
        name = (h.get('display_name') or h.get('nse_symbol') or h.get('bse_symbol') or sid).strip()
        isin = h.get('isin_code') or ''

        holdings.append({
            'name': name,
            'security_id': sid,
            'isin': isin,
            'exchange': exchange,
            'quantity': qty,
            'avg_price': avg,
            'ltp': ltp,
            'current_value': qty * ltp,
            'cost_value': qty * avg,
            'unrealised_pnl': (ltp - avg) * qty,
        })

    return holdings


def build_snapshot(pm, zerodha_data: dict | None = None, include_manual: bool = True) -> dict:
    """Return a complete portfolio snapshot with allocation percentages.

    zerodha_data: optional dict from agent.brokers.zerodha.fetch_all()
    """
    print("  Fetching Paytm Money holdings...")
    holdings = fetch_holdings(pm)

    # Merge manual holdings (MF + Gold) — pass partial snapshot for gold price
    if include_manual:
        from agent.manual_holdings import load as load_manual
        partial = {'holdings': holdings}
        manual = load_manual(snapshot=partial)
        if manual:
            print(f"  Merging {len(manual)} manual holding(s) (MF/Gold)...")
            holdings.extend(manual)

    # Merge Zerodha equity + MF holdings if available
    if zerodha_data:
        zerodha_equity = zerodha_data.get('equity', [])
        zerodha_mf     = zerodha_data.get('mf', [])
        if zerodha_equity:
            print(f"  Merging {len(zerodha_equity)} Zerodha equity holding(s)...")
            holdings.extend(zerodha_equity)
        if zerodha_mf:
            print(f"  Merging {len(zerodha_mf)} Zerodha MF holding(s)...")
            holdings.extend(zerodha_mf)

    print("  Fetching funds...")
    available_cash = 0.0
    try:
        funds_resp = pm.funds_summary()
        if isinstance(funds_resp, dict):
            data = funds_resp.get('data')
            data = data if isinstance(data, dict) else funds_resp
            available_cash = float(
                data.get('net') or
                data.get('available_cash') or
                data.get('payin_amount') or
                data.get('available_balance') or 0
            )
    except Exception as e:
        print(f"  (Funds unavailable: {e})")

    total_equity = sum(h['current_value'] for h in holdings)
    total_portfolio = total_equity + available_cash

    for h in holdings:
        h['allocation_pct'] = (h['current_value'] / total_portfolio * 100) if total_portfolio > 0 else 0.0

    holdings.sort(key=lambda x: x['current_value'], reverse=True)

    return {
        'holdings':       holdings,
        'total_equity':   total_equity,
        'available_cash': available_cash,
        'total_portfolio': total_portfolio,
        'sips':           zerodha_data.get('sips', []) if zerodha_data else [],
    }
