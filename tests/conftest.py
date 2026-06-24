"""Pytest config"""
import os
import sys

# Make the repo root importable so both `pmClient` and `agent` resolve
# regardless of how/where pytest is invoked or whether the package is installed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from pmClient import PMClient
from pmClient.WebSocketClient import WebSocketClient
from pmClient.apiService import ApiService
import pytest


# ---------------------------------------------------------------------------
# Live-API tests
#
# These tests make real network calls to the broker API. They are inherently
# flaky (depend on the live endpoint's current behaviour) and must NOT gate CI.
# They are auto-marked `live` and excluded from the default run; CI uses
# `pytest -m "not live"`. To run them deliberately: `pytest -m live`.
#
# The autouse `_block_network` fixture blocks real httpx calls for every
# non-live test, so any newly added test that forgets to mock the API fails
# loudly with a clear message instead of silently hitting the network.
# ---------------------------------------------------------------------------
_LIVE_TESTS = {
    'test_cancel_order_attribute', 'test_cancel_order_connection',
    'test_cancel_order_connection_bracket', 'test_cancel_order_connection_cover',
    'test_cancel_order_connection_cover_type', 'test_convert_order_connection',
    'test_create_gtt_attribute', 'test_create_gtt_connection', 'test_create_gtt_v2_attribute',
    'test_create_gtt_v2_connection', 'test_delete_gtt_connection', 'test_funds_summary_attribute',
    'test_generate_tpin_connection', 'test_get_gtt__aggregate_connection',
    'test_get_gtt_by_status_or_id_attribute', 'test_get_gtt_by_status_or_id_v2_attribute',
    'test_get_gtt_connection', 'test_get_gtt_expiry_connection', 'test_get_gtt_v2_connection',
    'test_get_option_chain', 'test_get_option_chain_config', 'test_get_user_details_connection',
    'test_holdings_value_connection', 'test_modify_order_attribute', 'test_modify_order_connection',
    'test_modify_order_connection_bracket', 'test_modify_order_connection_cover',
    'test_modify_order_connection_edis', 'test_order_book_connection', 'test_order_margin_connection',
    'test_orders_connection', 'test_place_order_attribute', 'test_place_order_connection',
    'test_place_order_connection_bracket', 'test_place_order_connection_cover',
    'test_place_order_connection_edis', 'test_position_connection', 'test_scrips_margin_attribute',
    'test_scrips_margin_connection', 'test_status_connection', 'test_trade_details_connection',
    'test_update_gtt_connection', 'test_update_gtt_v2_connection', 'test_user_holdings_data_connection',
    'test_validate_tpin_attribute', 'test_validate_tpin_connection',
}


def pytest_collection_modifyitems(config, items):
    """Auto-mark known live-API tests so CI can exclude them with -m 'not live'."""
    for item in items:
        if item.name in _LIVE_TESTS:
            item.add_marker(pytest.mark.live)


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Block real httpx network for non-live tests — forces mocking."""
    if request.node.get_closest_marker('live'):
        return  # live tests are allowed to hit the real API
    def _blocked(*args, **kwargs):
        raise RuntimeError(
            f"{request.node.name}: real network call in a non-live test. "
            f"Mock the API layer, or mark the test @pytest.mark.live."
        )
    for method in ('get', 'post', 'put', 'delete', 'request', 'stream',
                   'head', 'patch', 'options'):
        if hasattr(httpx, method):
            monkeypatch.setattr(httpx, method, _blocked)


@pytest.fixture()
def pm_api():
    pm_api = PMClient(api_key="<API_KEY>", api_secret="<API_SECRET>")
    return pm_api


@pytest.fixture()
def web_socket_client():
    web_socket_client = WebSocketClient(public_access_token="<PUBLIC_ACCESS_TOKEN>")
    return web_socket_client


@pytest.fixture()
def api_service():
    api_service = ApiService()
    return api_service
