"""Relay/tunnel checks must catch a wrong/stale origin (the api.trycloudflare blind spot)."""
from agent import sanity_check


class _Resp:
    def __init__(self, code): self.status_code = code


def test_relay_404_flags_wrong_origin(monkeypatch):
    monkeypatch.setattr(sanity_check, '_RELAY', 'https://relay.example')
    monkeypatch.setattr(sanity_check.requests, 'get', lambda *a, **k: _Resp(404))
    ok, detail = sanity_check.check_relay()
    assert ok is False and 'not reaching the webhook' in detail


def test_relay_400_is_healthy_webhook(monkeypatch):
    monkeypatch.setattr(sanity_check, '_RELAY', 'https://relay.example')
    monkeypatch.setattr(sanity_check.requests, 'get', lambda *a, **k: _Resp(400))
    assert sanity_check.check_relay() == (True, '')


def test_tunnel_rejects_infra_host(tmp_path, monkeypatch):
    turl = tmp_path / 't'; turl.write_text('https://api.trycloudflare.com')
    monkeypatch.setattr(sanity_check, '_TURL', str(turl))
    ok, detail = sanity_check.check_tunnel_direct()
    assert ok is False and 'infra host' in detail


def test_restart_map_targets_tunnel_service(monkeypatch):
    calls = []
    monkeypatch.setattr(sanity_check.subprocess, 'run', lambda *a, **k: calls.append(a[0]) or None)
    restarted = sanity_check._restart_services({'Relay (Workers)', 'Tokens freshness'})
    assert restarted == {'com.pradeep.zerodha-tunnel'}      # token-freshness isn't infra
    assert any('zerodha-tunnel' in ' '.join(c) for c in calls)
