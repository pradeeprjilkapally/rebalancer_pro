"""
FIRE (Financial Independence, Retire Early) analyser.
Calculates progress toward corpus target and projects time to FIRE.
"""

FIRE_MONTHLY_EXPENSES = 75_000          # current monthly expenses
FIRE_MULTIPLIER       = 25              # 4% safe withdrawal rule
ANNUAL_RETURN_RATE    = 0.12            # 12% assumed avg annual return
MONTHLY_RETURN_RATE   = ANNUAL_RETURN_RATE / 12
MONTHLY_INVESTMENT    = 1_27_000        # total committed monthly investment


def fire_target() -> float:
    return FIRE_MONTHLY_EXPENSES * 12 * FIRE_MULTIPLIER   # ₹2.25 Cr


def years_to_fire(current_corpus: float, monthly_investment: float = MONTHLY_INVESTMENT) -> float:
    """
    Solve for n months where:
      FV = PV*(1+r)^n + PMT*((1+r)^n - 1)/r  >= target
    Uses binary search since closed form requires logarithms with two growth terms.
    """
    target = fire_target()
    if current_corpus >= target:
        return 0.0

    r = MONTHLY_RETURN_RATE
    for n in range(1, 600):   # cap search at 50 years
        fv = current_corpus * (1 + r) ** n + monthly_investment * ((1 + r) ** n - 1) / r
        if fv >= target:
            return n / 12
    return float('inf')


def analyse_fire(snapshot: dict) -> dict:
    """Return a FIRE progress dict to include in daily report."""
    current = snapshot['total_portfolio']
    target  = fire_target()
    gap     = max(0, target - current)
    pct     = min(100.0, current / target * 100) if target > 0 else 0.0
    yrs     = years_to_fire(current)

    return {
        'target':         target,
        'current':        current,
        'gap':            gap,
        'progress_pct':   pct,
        'years_to_fire':  yrs,
    }


def fire_aligned_suggestions(
    snapshot: dict,
    manual_mf: float = 0.0,
    manual_gold: float = 0.0,
) -> list:
    """
    Returns FIRE-aligned investment suggestions based on allocation gaps.

    manual_mf   — current value of manually-tracked mutual funds (e.g. ICICI Multi-Asset)
    manual_gold — current value of manually-tracked gold (e.g. Paytm Gold)

    Both are included in the total corpus denominator so allocation percentages
    reflect the full portfolio, not just broker equity.
    """
    holdings = snapshot.get('holdings', [])
    snapshot_manual_mf = sum(
        h['current_value'] for h in holdings
        if h.get('source') == 'manual_mf'
    )
    snapshot_manual_gold = sum(
        h['current_value'] for h in holdings
        if h.get('source') == 'manual_gold'
    )
    external_manual_mf = 0.0 if snapshot_manual_mf else manual_mf
    external_manual_gold = 0.0 if snapshot_manual_gold else manual_gold

    total = snapshot['total_portfolio'] + external_manual_mf + external_manual_gold
    if total <= 0:
        return []

    # Broker gold (Gold Bees ETF in equity holdings)
    broker_gold = sum(
        h['current_value'] for h in holdings
        if h.get('source') not in ('manual_gold', 'manual_mf')
        and any(k in h['name'].upper() for k in ('GOLD', 'BEES'))
    )
    total_gold = broker_gold + snapshot_manual_gold + external_manual_gold

    # Broker pure equity (exclude Gold Bees)
    broker_equity = sum(
        h['current_value'] for h in holdings
        if h.get('source') not in ('manual_gold', 'manual_mf')
        and not any(k in h['name'].upper() for k in ('GOLD', 'BEES'))
    )

    # ICICI Multi-Asset is counted in the total but not in any single category bucket;
    # it already provides internal equity/debt/gold diversification.
    # For category allocation gaps we compare against the full-corpus denominator.
    allocations = {
        'large_cap':     broker_equity / total * 100,
        'gold':          total_gold / total * 100,
        'mid_small':     0.0,
        'international': 0.0,
        'debt':          0.0,
    }

    targets = {
        'large_cap':     30.0,
        'mid_small':     20.0,
        'international': 10.0,
        'debt':          25.0,
        'gold':          10.0,
    }

    suggestions = []

    if allocations['mid_small'] < targets['mid_small']:
        suggestions.append({
            'category': 'Mid & Small Cap',
            'instrument': 'Nifty Midcap 150 Index Fund (Motilal Oswal / Nippon)',
            'current_pct': allocations['mid_small'],
            'target_pct': targets['mid_small'],
            'suggested_sip': 8_000,
            'reason': f"Underweight: {allocations['mid_small']:.1f}% vs target {targets['mid_small']:.0f}% (full portfolio basis)",
        })

    if allocations['international'] < targets['international']:
        suggestions.append({
            'category': 'International Equity',
            'instrument': 'Motilal Oswal Nasdaq 100 ETF',
            'current_pct': allocations['international'],
            'target_pct': targets['international'],
            'suggested_sip': 5_000,
            'reason': f"Underweight: {allocations['international']:.1f}% vs target {targets['international']:.0f}% (full portfolio basis)",
        })

    if allocations['debt'] < targets['debt']:
        suggestions.append({
            'category': 'Debt / Liquid',
            'instrument': 'Nippon India Liquid Fund or HDFC Short Duration Fund',
            'current_pct': allocations['debt'],
            'target_pct': targets['debt'],
            'suggested_sip': 10_000,
            'reason': f"Underweight: {allocations['debt']:.1f}% vs target {targets['debt']:.0f}% (full portfolio basis)",
        })

    if allocations['gold'] > targets['gold'] + 5:
        suggestions.append({
            'category': 'Gold',
            'instrument': 'Nippon Gold Bees ETF',
            'current_pct': allocations['gold'],
            'target_pct': targets['gold'],
            'suggested_sip': 0,
            'reason': f"Overweight: {allocations['gold']:.1f}% vs target {targets['gold']:.0f}% — consider pausing Gold SIP",
        })

    return suggestions
