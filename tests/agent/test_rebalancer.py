"""Rebalancing concentration rules."""
from agent import rebalancer


def test_manual_mf_is_not_trimmed_as_single_position():
    snapshot = {
        'total_portfolio': 600_000,
        'holdings': [
            {
                'source': 'manual_mf',
                'name': 'ICICI Prudential Multi-Asset Fund',
                'security_id': '120334',
                'isin': 'INF109K015K4',
                'exchange': 'MF',
                'quantity': 600,
                'ltp': 900,
                'current_value': 540_000,
                'allocation_pct': 90.0,
            },
        ],
    }

    assert rebalancer.analyse(snapshot) == []


def test_broker_position_above_limit_is_still_trimmed():
    snapshot = {
        'total_portfolio': 100_000,
        'holdings': [
            {
                'source': 'broker',
                'name': 'Nippon India Gold Bees ETF',
                'security_id': '123',
                'isin': 'INF204KB17I5',
                'exchange': 'NSE',
                'quantity': 500,
                'ltp': 100,
                'current_value': 50_000,
                'allocation_pct': 50.0,
            },
        ],
    }

    suggestions = rebalancer.analyse(snapshot)

    assert len(suggestions) == 1
    assert suggestions[0]['name'] == 'Nippon India Gold Bees ETF'
    assert suggestions[0]['quantity'] == 300
