"""Dashboard ping snapshot loading."""
from agent import crypto
from agent import dashboard_ping


def test_ping_loads_encrypted_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBHOOK_ENCRYPTION_KEY', 'unit-test-key-do-not-use-in-prod')
    monkeypatch.setattr(dashboard_ping, '_MYDATA', str(tmp_path))

    payload = {
        'snapshot': {
            'total_portfolio': 65_331,
            'holdings': [{'name': 'LIC'}],
        },
    }
    crypto.write_encrypted(str(tmp_path / 'paytm_data.json.enc'), payload)

    assert dashboard_ping._load_snapshot('paytm') == payload


def test_ping_falls_back_to_empty_when_snapshot_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard_ping, '_MYDATA', str(tmp_path))

    assert dashboard_ping._load_snapshot('paytm') == {}


def test_broker_total_excludes_manual_holdings():
    data = {
        'snapshot': {
            'available_cash': 100,
            'holdings': [
                {'source': 'broker', 'current_value': 1_000},
                {'source': 'manual_mf', 'current_value': 5_000},
                {'source': 'manual_gold', 'current_value': 2_000},
            ],
        },
    }

    assert dashboard_ping._broker_total(data) == 1_100
