"""
Live 24K gold price fetcher — IBJA (India Bullion & Jewellers Association) rates.

IBJA publishes the authoritative domestic India 24K (999 purity) gold rate twice
daily. This is the same base rate used by Paytm Gold (MMTC-PAMP) before their
buy/sell spread (~3–5% markup on buy, ~1% discount on sell).

Source: https://ibjarates.com (no API key required, free public site)
  - Current rate:  <span id="GoldRatesCompare999">XXXX</span>  (₹/gram)
  - History:       <input id="HdnGold"> value contains JSON with purity999[]
                   array (₹ per 10g); labels[] for dates (DD/MM/YYYY format)
"""
import html as html_mod
import json
import os
import re
from datetime import date, datetime

_MYDATA       = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mydata')
_HISTORY_FILE = os.path.join(_MYDATA, 'gold_price_history.json')
_IBJA_URL     = 'https://ibjarates.com/'
_HEADERS      = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
}


def _fetch_ibja_page() -> str | None:
    try:
        import requests
        r = requests.get(_IBJA_URL, timeout=12, headers=_HEADERS)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f'  [gold_price] IBJA fetch failed: {e}')
    return None


def fetch_live_price_per_gram() -> float | None:
    """
    Fetch current 24K gold price per gram from IBJA.
    Returns None if the site is unreachable.
    """
    page = _fetch_ibja_page()
    if not page:
        return None
    m = re.search(r'GoldRatesCompare999[^>]*>(\d+(?:\.\d+)?)<', page)
    if m:
        price = round(float(m.group(1)), 2)
        return price
    print('  [gold_price] GoldRatesCompare999 span not found in IBJA page')
    return None


def seed_history() -> list[dict]:
    """
    Seed price history from IBJA's embedded historical chart JSON.
    Returns the list of {date, price} entries written to the history file.
    """
    page = _fetch_ibja_page()
    if not page:
        return []
    m = re.search(r'id=["\']HdnGold["\'][^>]*value=["\']([^"\']+)["\']', page)
    if not m:
        print('  [gold_price] HdnGold hidden field not found')
        return []
    try:
        data    = json.loads(html_mod.unescape(m.group(1)))
        labels  = data.get('labels', [])
        p999    = data.get('purity999', [])
        entries = []
        for label, raw_price in zip(labels, p999):
            try:
                d = datetime.strptime(label, '%d/%m/%Y').date().isoformat()
                entries.append({'date': d, 'price': round(raw_price / 10, 2)})
            except ValueError:
                continue
        entries = sorted(entries, key=lambda x: x['date'])
        os.makedirs(_MYDATA, exist_ok=True)
        with open(_HISTORY_FILE, 'w') as f:
            json.dump(entries, f)
        print(f'  [gold_price] Seeded {len(entries)} days of IBJA history '
              f'({entries[0]["date"]} → {entries[-1]["date"]})')
        return entries
    except Exception as e:
        print(f'  [gold_price] History seed failed: {e}')
        return []


def update_history(price_per_gram: float) -> list[dict]:
    """Append today's price to the history file (upsert by date). Returns full history."""
    today   = date.today().isoformat()
    history = load_history(days=90)
    history = [e for e in history if e.get('date') != today]
    history.append({'date': today, 'price': round(price_per_gram, 2)})
    history = sorted(history, key=lambda x: x['date'])[-90:]
    os.makedirs(_MYDATA, exist_ok=True)
    with open(_HISTORY_FILE, 'w') as f:
        json.dump(history, f)
    return history


def load_history(days: int = 30) -> list[dict]:
    """Load price history, most recent N days, sorted ascending."""
    if not os.path.exists(_HISTORY_FILE):
        return seed_history()
    try:
        history = json.load(open(_HISTORY_FILE))
        return sorted(history, key=lambda x: x['date'])[-days:]
    except Exception:
        return []


def get_price(snapshot: dict | None = None) -> float | None:
    """
    Get 24K gold price per gram — IBJA live first, then most recent history entry.
    The `snapshot` parameter is kept for API compatibility but no longer used.
    """
    price = fetch_live_price_per_gram()
    if price:
        update_history(price)
        return price

    hist = load_history(days=1)
    if hist:
        print(f'  [gold_price] Using cached price from {hist[-1]["date"]}')
        return hist[-1]['price']

    return None


def build_svg_chart(history: list[dict], width: int = 560, height: int = 100) -> str:
    """Generate an inline SVG sparkline. Returns empty string if fewer than 2 data points."""
    if len(history) < 2:
        return ''
    prices = [h['price'] for h in history]
    min_p  = min(prices)
    max_p  = max(prices)
    spread = max_p - min_p or 1

    pad_x, pad_y = 4, 8
    w = width  - pad_x * 2
    h = height - pad_y * 2
    n = len(prices)

    coords = []
    for i, p in enumerate(prices):
        x = pad_x + (i / (n - 1)) * w
        y = pad_y + h - ((p - min_p) / spread) * h
        coords.append((x, y))

    path     = 'M ' + ' L '.join(f'{x:.1f},{y:.1f}' for x, y in coords)
    area_pts = (
        f'{coords[0][0]:.1f},{height} '
        + ' '.join(f'{x:.1f},{y:.1f}' for x, y in coords)
        + f' {coords[-1][0]:.1f},{height}'
    )

    last  = prices[-1]
    first = prices[0]
    color = '#34d399' if last >= first else '#f87171'
    fill  = '#34d39922' if last >= first else '#f8717122'

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:{height}px;display:block">'
        f'<polygon points="{area_pts}" fill="{fill}"/>'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
        f'<circle cx="{coords[-1][0]:.1f}" cy="{coords[-1][1]:.1f}" r="3" fill="{color}"/>'
        f'</svg>'
    )
