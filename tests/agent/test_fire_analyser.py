"""FIRE math + allocation-suggestion logic."""
from agent import fire_analyser as fa


def test_fire_target_is_25x_annual_expenses():
    # 75,000/mo * 12 * 25 (4% rule)
    assert fa.fire_target() == 75_000 * 12 * 25 == 22_500_000


def test_years_to_fire_zero_when_already_funded():
    assert fa.years_to_fire(fa.fire_target()) == 0.0
    assert fa.years_to_fire(fa.fire_target() + 1) == 0.0


def test_years_to_fire_decreases_with_more_corpus():
    low  = fa.years_to_fire(1_000_000)
    high = fa.years_to_fire(15_000_000)
    assert high < low                      # closer to target ⇒ fewer years
    assert low > 0


def test_analyse_fire_fields():
    snap = {'total_portfolio': 6_800_000, 'total_equity': 6_800_000, 'holdings': []}
    out = fa.analyse_fire(snap)
    assert out['target'] == 22_500_000
    assert out['current'] == 6_800_000
    assert out['gap'] == 22_500_000 - 6_800_000
    assert round(out['progress_pct'], 1) == round(6_800_000 / 22_500_000 * 100, 1)
    assert out['years_to_fire'] > 0


def _gold_only_snapshot(value=100_000):
    return {
        'total_portfolio': value,
        'total_equity': value,
        'holdings': [{'name': 'Nippon Gold Bees ETF', 'current_value': value}],
    }


def test_gold_overweight_flagged_without_other_assets():
    # 100% gold, no manual holdings ⇒ gold is wildly overweight
    suggestions = fa.fire_aligned_suggestions(_gold_only_snapshot())
    assert any(s['category'] == 'Gold' for s in suggestions)


def test_manual_mf_is_included_in_denominator():
    """Regression: suggestions must weigh the full portfolio, not broker-only.

    With a large manual MF holding, the same gold position is only ~10% of the
    portfolio and must no longer be flagged as overweight.
    """
    suggestions = fa.fire_aligned_suggestions(
        _gold_only_snapshot(100_000), manual_mf=900_000, manual_gold=0,
    )
    assert not any(s['category'] == 'Gold' for s in suggestions)


def test_empty_portfolio_yields_no_suggestions():
    snap = {'total_portfolio': 0, 'total_equity': 0, 'holdings': []}
    assert fa.fire_aligned_suggestions(snap) == []
