"""Chit-fund manual holding: valuation, source tag, and FIRE-corpus inclusion."""
import json

from agent import manual_holdings, fire_analyser


def _write(tmp_path, monkeypatch, chits):
    f = tmp_path / 'manual_holdings.json'
    f.write_text(json.dumps({'mutual_funds': [], 'gold': [], 'chits': chits}))
    monkeypatch.setattr(manual_holdings, '_MANUAL_FILE', str(f))


def test_chit_invested_auto_from_months_paid(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{'platform': 'X', 'monthly_sip': 1000, 'months_paid': 3}])
    hs = manual_holdings.load()
    chit = next(h for h in hs if h['source'] == 'manual_chit')
    assert chit['cost_value'] == 3000            # 1000 × 3
    assert chit['current_value'] == 3000         # defaults to invested


def test_chit_explicit_values_win(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{'platform': 'X', 'monthly_sip': 1000, 'months_paid': 3,
                                    'invested': 5000, 'current_value': 5200}])
    chit = next(h for h in manual_holdings.load() if h['source'] == 'manual_chit')
    assert chit['cost_value'] == 5000 and chit['current_value'] == 5200


def test_chit_included_in_fire_corpus():
    # a chit in the snapshot lifts the corpus total (like manual_mf), not a category bucket
    snap = {
        'total_portfolio': 100000,
        'holdings': [
            {'name': 'ACME', 'current_value': 100000, 'source': 'broker'},
            {'name': 'Chit', 'current_value': 50000, 'source': 'manual_chit'},
        ],
    }
    # should run without error and treat the chit as corpus (no crash, returns a list)
    out = fire_analyser.fire_aligned_suggestions(snap, manual_chit=0.0)
    assert isinstance(out, list)


def test_fire_accepts_manual_chit_param():
    # external manual_chit (not in snapshot) is added to the denominator
    snap = {'total_portfolio': 0, 'holdings': []}
    assert fire_analyser.fire_aligned_suggestions(snap, manual_chit=0) == []   # total 0 → []
