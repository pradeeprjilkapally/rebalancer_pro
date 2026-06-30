"""Token monitor: rolling-window math, the handoff/handback decision, and the baton."""
import json
from datetime import datetime, timedelta, timezone

from agent import token_monitor as tm


NOW = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


# --- decide(): the Claude<->Codex state machine ---------------------------------

def test_handoff_when_claude_near_limit():
    assert tm.decide(90.0, 'claude', handoff_pct=88, resume_pct=50) == ('handoff', 'codex')

def test_no_handoff_when_claude_below_threshold():
    assert tm.decide(70.0, 'claude', handoff_pct=88, resume_pct=50) == (None, 'claude')

def test_handback_when_claude_refreshed():
    # owner is codex; usage fell back below the resume mark → take it back to Claude
    assert tm.decide(40.0, 'codex', handoff_pct=88, resume_pct=50) == ('handback', 'claude')

def test_stay_on_codex_until_refreshed():
    # still elevated → don't bounce back to Claude yet
    assert tm.decide(75.0, 'codex', handoff_pct=88, resume_pct=50) == (None, 'codex')


# --- rolling window -------------------------------------------------------------

def test_rolling_tokens_excludes_old_records():
    recs = [
        (NOW - timedelta(hours=1), 100),   # in window
        (NOW - timedelta(hours=4), 200),   # in window
        (NOW - timedelta(hours=6), 999),   # outside 5h window
    ]
    assert tm.rolling_tokens(recs, NOW, hours=5) == 300

def test_usage_pct():
    assert tm.usage_pct(2500, budget=5000) == 50.0
    assert tm.usage_pct(0, budget=5000) == 0.0


# --- parsing real-shaped logs ---------------------------------------------------

def test_parse_usage_counts_in_out_and_cache_creation_only(tmp_path):
    log = tmp_path / 's.jsonl'
    rec = {
        'timestamp': '2026-06-30T11:30:00.000Z',
        'message': {'usage': {
            'input_tokens': 10, 'output_tokens': 20,
            'cache_creation_input_tokens': 5,
            'cache_read_input_tokens': 9999,   # near-free → must be excluded
        }},
    }
    log.write_text(json.dumps(rec) + '\n' + 'not-json\n')   # bad line ignored
    parsed = tm.parse_usage([str(log)])
    assert len(parsed) == 1
    assert parsed[0][1] == 35          # 10 + 20 + 5, cache_read excluded


# --- baton + owner state --------------------------------------------------------

def test_owner_roundtrip_and_default(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, '_STATE_FILE', str(tmp_path / 'state'))
    assert tm.read_owner() == 'claude'        # default when absent
    tm.write_owner('codex')
    assert tm.read_owner() == 'codex'

def test_write_handoff_records_owner_and_branch(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, '_HANDOFF_MD', str(tmp_path / 'HANDOFF.md'))
    monkeypatch.setattr(tm, '_git', lambda *a: 'feature/x' if a[0] == 'rev-parse' else '')
    tm.write_handoff('codex', 91.0, 4_800_000)
    text = (tmp_path / 'HANDOFF.md').read_text()
    assert 'Owner: codex' in text and 'feature/x' in text and '`resume`' in text
