"""
Verify the tunnel + webhook recovery chain end-to-end.

Checks, in dependency order:
  1. cloudflared process is running
  2. webhook Flask server answers on localhost:<WEBHOOK_PORT>/health
  3. the direct tunnel URL (.tunnel_url) answers /health
  4. the permanent Workers relay answers /health (it proxies to the tunnel URL
     via Cloudflare KV, so this is green only when 1-3 are healthy)

Writes testplans/<date>/results.json and exits 2 on any failure, matching the
repo's scripts/verify_<feature>.py convention.

Usage:  python -m scripts.verify_tunnel
"""
import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
load_dotenv()

_REPO    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TURL    = os.path.join(_REPO, '.tunnel_url')
_RELAY   = os.getenv('WORKERS_RELAY_URL', '').rstrip('/')
_PORT    = os.getenv('WEBHOOK_PORT', '5001')
_TIMEOUT = 10

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'
results = []


def record(label, ok, detail=''):
    results.append({'check': label, 'ok': ok, 'detail': detail})
    print(f'  {PASS if ok else FAIL} {label}' + (f' — {detail}' if detail else ''))
    return ok


def check_cloudflared():
    r = subprocess.run(['pgrep', '-f', 'cloudflared'], capture_output=True, text=True)
    ok = r.returncode == 0
    return record('cloudflared process', ok,
                  f'pid {r.stdout.split()[0]}' if ok else 'not running')


def check_webhook():
    try:
        r = requests.get(f'http://localhost:{_PORT}/health', timeout=_TIMEOUT)
        return record(f'webhook :{_PORT}/health', r.status_code == 200,
                      f'HTTP {r.status_code}')
    except Exception as e:
        return record(f'webhook :{_PORT}/health', False, str(e))


def check_tunnel_direct():
    try:
        url = open(_TURL).read().strip()
    except FileNotFoundError:
        return record('tunnel direct /health', False, 'no .tunnel_url file')
    try:
        r = requests.get(f'{url}/health', timeout=_TIMEOUT)
        return record('tunnel direct /health', r.status_code < 500,
                      f'{url} -> HTTP {r.status_code}')
    except Exception as e:
        return record('tunnel direct /health', False, f'{url}: {e}')


def check_relay():
    if not _RELAY:
        return record('relay /health', False, 'WORKERS_RELAY_URL not set')
    try:
        r = requests.get(f'{_RELAY}/health', timeout=_TIMEOUT)
        return record('relay /health', r.status_code < 500, f'HTTP {r.status_code}')
    except Exception as e:
        return record('relay /health', False, str(e))


def main():
    print('Verifying tunnel + webhook recovery chain...')
    checks = [check_cloudflared, check_webhook, check_tunnel_direct, check_relay]
    all_ok = all(fn() for fn in checks)

    out_dir = os.path.join(_REPO, 'testplans', datetime.now().strftime('%Y-%m-%d'))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'results.json')
    with open(out_path, 'w') as f:
        json.dump({
            'feature': 'tunnel_recovery',
            'timestamp': datetime.now().isoformat(),
            'all_passed': all_ok,
            'checks': results,
        }, f, indent=2)
    print(f'\nResults written to {out_path}')
    print('PASS' if all_ok else 'FAIL')
    sys.exit(0 if all_ok else 2)


if __name__ == '__main__':
    main()
