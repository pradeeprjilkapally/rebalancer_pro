"""The dashboard-exposure guard must flag a public dashboard and stay quiet when gated."""
from agent import sanity_check


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_flags_public_dashboard(monkeypatch):
    monkeypatch.setattr(sanity_check, '_RELAY', 'https://relay.example')
    monkeypatch.setattr(sanity_check.requests, 'get', lambda *a, **k: _Resp(200))
    ok, detail = sanity_check.check_dashboard_exposure()
    assert ok is False and 'EXPOSED' in detail


def test_ok_when_access_gated(monkeypatch):
    monkeypatch.setattr(sanity_check, '_RELAY', 'https://relay.example')
    monkeypatch.setattr(sanity_check.requests, 'get', lambda *a, **k: _Resp(302))
    assert sanity_check.check_dashboard_exposure() == (True, '')


def test_fails_open_on_error(monkeypatch):
    monkeypatch.setattr(sanity_check, '_RELAY', 'https://relay.example')
    def boom(*a, **k): raise RuntimeError('network')
    monkeypatch.setattr(sanity_check.requests, 'get', boom)
    assert sanity_check.check_dashboard_exposure() == (True, '')
