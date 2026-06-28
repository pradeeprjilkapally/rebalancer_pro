"""Alert cooldown + ledger dedup must stop the hourly repeat-alert flood."""
from agent import sanity_check


def test_same_failures_suppressed_within_window(tmp_path, monkeypatch):
    monkeypatch.setattr(sanity_check, '_ALERT_STATE_FILE', str(tmp_path / 'st'))
    fails = [('Tokens freshness', 'stale')]
    assert sanity_check._alert_suppressed(fails) is False   # first time → alert
    assert sanity_check._alert_suppressed(fails) is True    # same set → suppressed


def test_changed_failures_alert_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(sanity_check, '_ALERT_STATE_FILE', str(tmp_path / 'st'))
    assert sanity_check._alert_suppressed([('Tokens freshness', 'x')]) is False
    # a different failure set is a state change → alert now, not suppressed
    assert sanity_check._alert_suppressed([('Relay (Workers)', 'y')]) is False


def test_action_item_dedup(tmp_path, monkeypatch):
    ai = tmp_path / 'action_items.md'
    ai.write_text('|-------|--------|------|-------|-------|\n')
    monkeypatch.setattr(sanity_check, '_AI', str(ai))
    sanity_check._append_action_item('[sanity] Tokens freshness', 'stale')
    sanity_check._append_action_item('[sanity] Tokens freshness', 'stale again')
    assert ai.read_text().count('[sanity] Tokens freshness') == 1   # only one row
