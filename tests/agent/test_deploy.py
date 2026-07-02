"""Deploy pipeline pure helpers + the dashboard_pp local-only guard."""
import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'deploy', os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'deploy.py'))
deploy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deploy)

from agent import webhook


def test_preview_and_prod_urls_and_ports():
    assert deploy.preview_url() == 'http://127.0.0.1:5002/dashboard_pp'
    assert deploy.prod_url() == 'http://127.0.0.1:5001/dashboard_main'
    assert deploy._PREVIEW_PORT == 5002 and deploy._PROD_PORT == 5001


def test_deploy_ok_only_on_200():
    assert deploy.deploy_ok(200) is True
    assert deploy.deploy_ok(404) is False
    assert deploy.deploy_ok(None) is False


@pytest.fixture
def client():
    webhook.app.config.update(TESTING=True)
    return webhook.app.test_client()


def _stub(monkeypatch):
    monkeypatch.setattr(webhook, '_load_broker_data', lambda broker: None)
    monkeypatch.setattr(webhook, '_build_gold_context', lambda: None)
    monkeypatch.setattr(webhook, '_build_mf_context', lambda: [])
    monkeypatch.setattr(webhook, '_build_fire_context', lambda mf, gold: {
        'target': 22_500_000, 'current': 0, 'gap': 22_500_000, 'progress_pct': 0.0,
        'years_to_fire': 8.2, 'monthly_investment': 127_000, 'breakdown': [],
    })


def test_dashboard_pp_serves_locally(client, monkeypatch):
    _stub(monkeypatch)
    assert client.get('/dashboard_pp').status_code == 200          # direct/local


def test_dashboard_pp_blocked_via_tunnel(client, monkeypatch):
    _stub(monkeypatch)
    # a request arriving through the Cloudflare tunnel/relay carries Cf-Connecting-Ip
    r = client.get('/dashboard_pp', headers={'Cf-Connecting-Ip': '1.2.3.4'})
    assert r.status_code == 404


def test_old_dashboard_bkp_route_gone():
    assert not hasattr(webhook, 'dashboard_bkp')
