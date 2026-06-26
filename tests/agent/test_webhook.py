"""Webhook routes, security headers, and ₹ formatting.

The dashboards have no app-level password — they are gated at the edge by
Cloudflare Access. So at the app layer every route serves directly; the
sanity check (test_sanity_dashboard_exposure) guards against the dashboard
becoming publicly reachable if Access is ever misconfigured.
"""
import pytest

from agent import webhook


@pytest.fixture
def client():
    webhook.app.config.update(TESTING=True)
    return webhook.app.test_client()


def test_health_is_open(client):
    assert client.get('/health').status_code == 200


def test_dashboard_needs_no_app_password(client, monkeypatch):
    # No Basic Auth at the app layer — Access gates at the edge.
    monkeypatch.setattr(webhook, '_load_broker_data', lambda broker: None)
    monkeypatch.setattr(webhook, '_build_gold_context', lambda: None)
    monkeypatch.setattr(webhook, '_build_mf_context', lambda: [])
    monkeypatch.setattr(webhook, '_build_fire_context', lambda mf, gold: {
        'target': 22_500_000, 'current': 0, 'gap': 22_500_000, 'progress_pct': 0.0,
        'years_to_fire': 8.2, 'monthly_investment': 127_000, 'breakdown': [],
    })
    assert client.get('/dashboard_main').status_code == 200


def test_no_basic_auth_machinery_remains():
    # Guard against a regression that re-introduces a second password layer.
    assert not hasattr(webhook, 'require_auth')
    assert not hasattr(webhook, '_auth_ok')


def test_security_headers_present(client):
    h = client.get('/health').headers
    assert h.get('X-Frame-Options') == 'DENY'
    assert h.get('X-Content-Type-Options') == 'nosniff'
    assert 'Content-Security-Policy' in h
    assert 'Strict-Transport-Security' in h
    assert h.get('Cache-Control') == 'no-store, max-age=0'


def test_inr_indian_grouping():
    assert webhook._inr(690718) == '6,90,718'
    assert webhook._inr(100000) == '1,00,000'
    assert webhook._inr(999) == '999'
    assert webhook._inr(-1234567) == '-12,34,567'
    assert webhook._inr(0) == '0'
