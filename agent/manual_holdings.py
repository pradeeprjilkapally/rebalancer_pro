"""
Manual holdings loader — MF and Gold positions not accessible via broker APIs.

Data file: mydata/manual_holdings.json  (gitignored — personal data)
MF NAV:    live from AMFI daily NAV file (primary) → mfapi.in (fallback)
           AMFI: https://www.amfiindia.com/spages/NAVAll.txt
           One HTTP call fetches all scheme NAVs; format: SchemeCode;ISIN;ISIN2;Name;NAV;Date
Gold price: live from IBJA via agent.gold_price (₹/gram)

Returns holdings in the same dict shape used by portfolio.py so they merge
seamlessly into the snapshot.
"""
import json
import os
from datetime import datetime

import requests

from agent.gold_price import get_price as get_gold_price_per_gram

_MYDATA      = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mydata')
_MANUAL_FILE = os.path.join(_MYDATA, 'manual_holdings.json')
_AMFI_URL    = 'https://www.amfiindia.com/spages/NAVAll.txt'
_MFAPI_BASE  = 'https://api.mfapi.in/mf'
_TIMEOUT     = 15


# ---------------------------------------------------------------------------
# NAV helpers
# ---------------------------------------------------------------------------

def _fetch_navs_amfi(scheme_codes: list[str]) -> dict[str, float]:
    """
    Fetch NAVs for the given scheme codes from the AMFI daily NAV bulk file.
    One HTTP call covers all schemes. Returns {scheme_code: nav}.
    """
    needed = set(scheme_codes)
    result: dict[str, float] = {}
    try:
        r = requests.get(_AMFI_URL, timeout=_TIMEOUT, stream=True)
        for raw_line in r.iter_lines(decode_unicode=True):
            line = raw_line.strip()
            if not line or ';' not in line:
                continue
            parts = line.split(';')
            if len(parts) < 5:
                continue
            code = parts[0]
            if code in needed:
                try:
                    result[code] = float(parts[4])
                except ValueError:
                    pass
            if len(result) == len(needed):
                break
    except Exception as e:
        print(f'  [manual] AMFI NAV fetch failed: {e}')
    return result


def _fetch_nav_mfapi(scheme_code: str) -> float | None:
    """Fallback: fetch individual NAV from mfapi.in."""
    try:
        r = requests.get(f'{_MFAPI_BASE}/{scheme_code}', timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                return float(data[0]['nav'])
    except Exception as e:
        print(f'  [manual] mfapi fallback failed for {scheme_code}: {e}')
    return None


# ---------------------------------------------------------------------------
# Chit valuation (shared by load(), the dashboard, and the FIRE corpus)
# ---------------------------------------------------------------------------

def _num(v) -> float | None:
    """A value only if it's genuinely numeric — formula strings return None."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip().replace('.', '', 1).isdigit():
        return float(v)
    return None


def chit_valuation(chit: dict, now: datetime | None = None) -> dict:
    """
    Value one chit entry.
    - months_paid: a numeric months_paid wins; else computed from Start_Month
      ("<Month>-<YYYY>") to `now`, floored at 0 and capped at tenure_months.
    - invested = numeric `invested`, else monthly_installment × months_paid.
    - current_value = numeric `current_value`, else invested.
    Formula-string fields (e.g. "Current Month - Start_Month") are treated as
    "compute this", not literal values.
    """
    now = now or datetime.now()
    monthly = float(chit.get('monthly_installment', 0) or chit.get('monthly_sip', 0) or 0)
    tenure  = int(chit.get('tenure_months', 0) or 0)

    months_paid = _num(chit.get('months_paid'))
    if months_paid is None:
        start = chit.get('Start_Month') or chit.get('start_month')
        try:
            sd = datetime.strptime(str(start).strip(), '%B-%Y')
            months_paid = max(0, (now.year - sd.year) * 12 + (now.month - sd.month))
        except (ValueError, TypeError, AttributeError):
            months_paid = 0
    months_paid = int(months_paid)
    if tenure:
        months_paid = min(months_paid, tenure)

    invested      = _num(chit.get('invested')) or (monthly * months_paid)
    current_value = _num(chit.get('current_value')) or invested
    return {'monthly': monthly, 'tenure': tenure, 'months_paid': months_paid,
            'invested': invested, 'current_value': current_value}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load(snapshot: dict | None = None) -> list[dict]:
    """
    Load and return manual holdings merged with live prices.
    Returns [] if the file doesn't exist or has no valid entries.
    """
    if not os.path.exists(_MANUAL_FILE):
        return []

    try:
        data = json.load(open(_MANUAL_FILE))
    except Exception as e:
        print(f'  [manual] Could not read {_MANUAL_FILE}: {e}')
        return []

    holdings: list[dict] = []

    # ---- Mutual funds -------------------------------------------------------
    mf_entries = [
        mf for mf in data.get('mutual_funds', [])
        if float(mf.get('units', 0) or 0) > 0
    ]

    if mf_entries:
        scheme_codes = [str(mf.get('scheme_code', '')).strip() for mf in mf_entries]
        nav_map      = _fetch_navs_amfi(scheme_codes)

        for mf, scheme in zip(mf_entries, scheme_codes):
            name     = mf.get('name', 'Unknown Fund')
            units    = float(mf.get('units', 0))
            invested = float(mf.get('invested', 0) or 0)

            nav = nav_map.get(scheme) or _fetch_nav_mfapi(scheme)

            if nav:
                current_value = units * nav
                print(f'  [manual] {name}: {units} units × NAV ₹{nav:.4f} = ₹{current_value:,.0f}')
            else:
                current_value = invested
                nav           = (invested / units) if units > 0 else 0
                print(f'  [manual] {name}: NAV unavailable — using invested ₹{invested:,.0f}')

            holdings.append({
                'source':         'manual_mf',
                'name':           name,
                'security_id':    scheme or name,
                'isin':           mf.get('isin', ''),
                'exchange':       'MF',
                'quantity':       units,
                'avg_price':      (invested / units) if units > 0 else 0,
                'ltp':            nav,
                'current_value':  current_value,
                'cost_value':     invested,
                'unrealised_pnl': current_value - invested,
            })

    # ---- Gold ---------------------------------------------------------------
    gold_pgram = get_gold_price_per_gram(snapshot)
    if gold_pgram:
        print(f'  [manual] Gold price: ₹{gold_pgram:,.2f}/g (IBJA 24K rate)')

    for gold in data.get('gold', []):
        platform = gold.get('platform', 'Paytm Gold')
        grams    = float(gold.get('grams', 0) or 0)
        invested = float(gold.get('invested', 0) or 0)

        if grams <= 0 and invested <= 0:
            continue

        if gold_pgram and grams > 0:
            current_value = grams * gold_pgram
            ltp           = gold_pgram
        else:
            current_value = invested
            ltp           = (invested / grams) if grams > 0 else 0

        print(f'  [manual] {platform}: {grams:.4f}g × ₹{ltp:,.0f}/g = ₹{current_value:,.0f}')

        holdings.append({
            'source':         'manual_gold',
            'name':           f'{platform} (Gold)',
            'security_id':    'GOLD',
            'isin':           '',
            'exchange':       'GOLD',
            'quantity':       grams,
            'avg_price':      (invested / grams) if grams > 0 else 0,
            'ltp':            ltp,
            'current_value':  current_value,
            'cost_value':     invested,
            'unrealised_pnl': current_value - invested,
        })

    # ---- Chit funds ---------------------------------------------------------
    # months_paid computed from Start_Month; invested = installment × months_paid;
    # current_value = explicit or invested. See chit_valuation() for the rules.
    for chit in data.get('chits', []):
        platform = chit.get('platform', 'Chit Fund')
        v = chit_valuation(chit)

        print(f"  [manual] {platform}: {v['months_paid']} × ₹{v['monthly']:,.0f} "
              f"= invested ₹{v['invested']:,.0f}, value ₹{v['current_value']:,.0f}")

        holdings.append({
            'source':         'manual_chit',
            'name':           f'{platform} (Chit)',
            'security_id':    'CHIT',
            'isin':           '',
            'exchange':       'CHIT',
            'quantity':       v['months_paid'],
            'avg_price':      v['monthly'],
            'ltp':            0,
            'current_value':  v['current_value'],
            'cost_value':     v['invested'],
            'unrealised_pnl': v['current_value'] - v['invested'],
        })

    return holdings
