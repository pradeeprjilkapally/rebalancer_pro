"""The auto-fix cooldown must gate repeated Claude invocations at the hourly cadence."""
import os
import time

from agent import sanity_check


def test_cooldown_clear_when_no_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(sanity_check, '_AUTOFIX_COOLDOWN_FILE', str(tmp_path / 'cd'))
    assert sanity_check._autofix_cooldown_remaining() == 0.0


def test_cooldown_active_after_mark(tmp_path, monkeypatch):
    monkeypatch.setattr(sanity_check, '_AUTOFIX_COOLDOWN_FILE', str(tmp_path / 'cd'))
    sanity_check._mark_autofix()
    remaining = sanity_check._autofix_cooldown_remaining()
    assert 0 < remaining <= sanity_check._AUTOFIX_COOLDOWN_HOURS


def test_cooldown_expires(tmp_path, monkeypatch):
    f = tmp_path / 'cd'
    monkeypatch.setattr(sanity_check, '_AUTOFIX_COOLDOWN_FILE', str(f))
    monkeypatch.setattr(sanity_check, '_AUTOFIX_COOLDOWN_HOURS', 6)
    f.write_text('x')
    old = time.time() - 7 * 3600          # 7h ago, past the 6h window
    os.utime(f, (old, old))
    assert sanity_check._autofix_cooldown_remaining() == 0.0
