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


def fire_aligned_suggestions(snapshot: dict) -> list:
    """
    Returns FIRE-aligned investment suggestions based on allocation gaps.
    These are additive (buy) suggestions, not rebalancing sells.
    """
    total = snapshot['total_portfolio']
    if total <= 0:
        return []

    # Compute current category allocations
    gold_value    = sum(h['current_value'] for h in snapshot['holdings']
                        if any(k in h['name'].upper() for k in ('GOLD', 'BEES')))
    equity_value  = snapshot['total_equity'] - gold_value

    allocations = {
        'large_cap':    equity_value / total * 100,
        'gold':         gold_value / total * 100,
        'mid_small':    0.0,   # no mid/small cap detected yet
        'international':0.0,   # no international detected yet
        'debt':         0.0,   # debt not tracked yet
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
            'reason': f"Underweight: {allocations['mid_small']:.1f}% vs target {targets['mid_small']:.0f}%",
        })

    if allocations['international'] < targets['international']:
        suggestions.append({
            'category': 'International Equity',
            'instrument': 'Motilal Oswal Nasdaq 100 ETF',
            'current_pct': allocations['international'],
            'target_pct': targets['international'],
            'suggested_sip': 5_000,
            'reason': f"Underweight: {allocations['international']:.1f}% vs target {targets['international']:.0f}%",
        })

    if allocations['debt'] < targets['debt']:
        suggestions.append({
            'category': 'Debt / Liquid',
            'instrument': 'Nippon India Liquid Fund or HDFC Short Duration Fund',
            'current_pct': allocations['debt'],
            'target_pct': targets['debt'],
            'suggested_sip': 10_000,
            'reason': f"Underweight: {allocations['debt']:.1f}% vs target {targets['debt']:.0f}%",
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
