"""Webhook access control, security headers, and ₹ formatting."""
import base64

import pytest

from agent import webhook


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(webhook, '_DASH_USER', 'tester')
    monkeypatch.setattr(webhook, '_DASH_PASS', 'secret-pass')
    webhook.app.config.update(TESTING=True)
    return webhook.app.test_client()


def _basic(user, pw):
    raw = base64.b64encode(f'{user}:{pw}'.encode()).decode()
    return {'Authorization': f'Basic {raw}'}


def test_health_is_open(client):
    assert client.get('/health').status_code == 200


def test_dashboard_requires_auth(client):
    assert client.get('/dashboard_main').status_code == 401
    assert client.get('/dashboard_bkp').status_code == 401


def test_dashboard_rejects_wrong_password(client):
    r = client.get('/dashboard_main', headers=_basic('tester', 'wrong'))
    assert r.status_code == 401


def test_auth_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(webhook, '_DASH_USER', '')
    monkeypatch.setattr(webhook, '_DASH_PASS', '')
    c = webhook.app.test_client()
    # even "correct-looking" empty creds must not pass
    assert c.get('/dashboard_main', headers=_basic('', '')).status_code == 401


def test_security_headers_present(client):
    h = client.get('/health').headers
    assert h.get('X-Frame-Options') == 'DENY'
    assert h.get('X-Content-Type-Options') == 'nosniff'
    assert 'Content-Security-Policy' in h
    assert 'Strict-Transport-Security' in h
    assert h.get('Cache-Control') == 'no-store, max-age=0'


def test_dashboard_renders_with_valid_auth(client, monkeypatch):
    # Stub the data layer so the view renders without touching disk or network.
    monkeypatch.setattr(webhook, '_load_broker_data', lambda broker: None)
    monkeypatch.setattr(webhook, '_build_gold_context', lambda: None)
    monkeypatch.setattr(webhook, '_build_mf_context', lambda: [])
    monkeypatch.setattr(webhook, '_build_fire_context', lambda mf, gold: {
        'target': 22_500_000, 'current': 0, 'gap': 22_500_000, 'progress_pct': 0.0,
        'years_to_fire': 8.2, 'monthly_investment': 127_000, 'breakdown': [],
    })
    r = client.get('/dashboard_main', headers=_basic('tester', 'secret-pass'))
    assert r.status_code == 200


def test_inr_indian_grouping():
    assert webhook._inr(690718) == '6,90,718'
    assert webhook._inr(100000) == '1,00,000'
    assert webhook._inr(999) == '999'
    assert webhook._inr(-1234567) == '-12,34,567'
    assert webhook._inr(0) == '0'
