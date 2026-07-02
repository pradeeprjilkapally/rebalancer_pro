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


# --- date-based valuation (chit_valuation) ---------------------------------
from datetime import datetime as _dt
from agent.manual_holdings import chit_valuation

_NOW = _dt(2026, 7, 2)   # fixed for deterministic month math


def test_chit_months_from_start_month():
    v = chit_valuation({'monthly_installment': 16000, 'tenure_months': 25,
                        'Start_Month': 'January-2025'}, now=_NOW)
    assert v['months_paid'] == 18                    # Jan-2025 → Jul-2026
    assert v['current_value'] == 18 * 16000


def test_chit_formula_strings_are_ignored():
    # the user's placeholders are formulas, not values → computed, not literal
    v = chit_valuation({'monthly_installment': 16000, 'tenure_months': 25,
                        'Start_Month': 'May-2026',
                        'months_paid': 'Current Month - Start_Month',
                        'current_value': 'months_paid * monthly_installment'}, now=_NOW)
    assert v['months_paid'] == 2 and v['current_value'] == 32000


def test_chit_months_capped_at_tenure():
    v = chit_valuation({'monthly_installment': 1000, 'tenure_months': 5,
                        'Start_Month': 'January-2020'}, now=_NOW)
    assert v['months_paid'] == 5                     # capped, not 78


def test_chit_numeric_months_paid_wins():
    v = chit_valuation({'monthly_installment': 1000, 'months_paid': 4,
                        'Start_Month': 'January-2020'}, now=_NOW)
    assert v['months_paid'] == 4 and v['current_value'] == 4000


def test_chit_future_start_is_zero():
    v = chit_valuation({'monthly_installment': 1000, 'Start_Month': 'January-2099'}, now=_NOW)
    assert v['months_paid'] == 0 and v['current_value'] == 0


# --- sip_day-aware timing (Fable's off-by-one fix) -------------------------
def test_chit_counts_current_month_after_due_day():
    # sip_day=1, now the 2nd → July's installment IS paid → 19 (was 18 before the fix)
    v = chit_valuation({'monthly_installment': 16000, 'tenure_months': 25,
                        'sip_day': 1, 'Start_Month': 'January-2025'}, now=_dt(2026, 7, 2))
    assert v['months_paid'] == 19

def test_chit_last_day_before_and_on_month_end():
    base = {'monthly_installment': 16000, 'tenure_months': 25,
            'sip_day': 'last day of month', 'Start_Month': 'January-2025'}
    assert chit_valuation(base, now=_dt(2026, 7, 2))['months_paid'] == 18   # July not due yet
    assert chit_valuation(base, now=_dt(2026, 7, 31))['months_paid'] == 19  # July's last day → due

def test_chit_start_month_due_day_boundary():
    base = {'monthly_installment': 1000, 'tenure_months': 25, 'sip_day': 15,
            'Start_Month': 'January-2025'}
    assert chit_valuation(base, now=_dt(2025, 1, 14))['months_paid'] == 0    # before the 15th
    assert chit_valuation(base, now=_dt(2025, 1, 15))['months_paid'] == 1    # on the due day

def test_chit_sip_day_overflow_clamps_to_month_end():
    # sip_day=31 in June (30 days) → due on the 30th
    v = chit_valuation({'monthly_installment': 1000, 'tenure_months': 25, 'sip_day': 31,
                        'Start_Month': 'January-2025'}, now=_dt(2026, 6, 30))
    assert v['months_paid'] == 18   # Jan-2025 … Jun-2026 inclusive
