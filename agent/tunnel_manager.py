"""
Starts cloudflared quick tunnel, captures the public HTTPS URL, and on
URL change updates the Cloudflare KV store so the permanent Workers relay
always forwards to the live tunnel.

Permanent relay URL (never changes):
  https://portfolio-relay.pradeeprjilkapally.workers.dev

Run via launchd: python3 -m agent.tunnel_manager
"""
import os
import re
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

_REPO_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_URL_FILE  = os.path.join(_REPO_DIR, '.tunnel_url')
_CF_BIN    = '/opt/anaconda3/bin/cloudflared'
_URL_RE    = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')

_CF_TOKEN    = os.getenv('CLOUDFLARE_API_TOKEN', '')
_CF_ACCOUNT  = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
_CF_KV_NS    = os.getenv('CLOUDFLARE_KV_NAMESPACE_ID', '')
_RELAY_URL   = os.getenv('WORKERS_RELAY_URL', '')


def _load_prev_url() -> str:
    try:
        with open(_URL_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def _save_url(url: str):
    with open(_URL_FILE, 'w') as f:
        f.write(url)


def _update_kv(tunnel_url: str) -> bool:
    """Push new tunnel URL into Cloudflare KV so the Worker relay picks it up."""
    if not all([_CF_TOKEN, _CF_ACCOUNT, _CF_KV_NS]):
        print('  [Tunnel] Cloudflare KV credentials missing — skipping KV update.')
        return False
    try:
        resp = requests.put(
            f'https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT}'
            f'/storage/kv/namespaces/{_CF_KV_NS}/values/tunnel_url',
            headers={
                'Authorization': f'Bearer {_CF_TOKEN}',
                'Content-Type': 'text/plain',
            },
            data=tunnel_url,
            timeout=10,
        )
        ok = resp.json().get('success', False)
        print(f'  [Tunnel] KV updated → {tunnel_url} ({"OK" if ok else "FAILED"})')
        return ok
    except Exception as e:
        print(f'  [Tunnel] KV update failed: {e}')
        return False


def main():
    print(f'[Tunnel] Starting cloudflared → http://localhost:5001')

    proc = subprocess.Popen(
        [_CF_BIN, 'tunnel', '--url', 'http://localhost:5001', '--no-autoupdate'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    new_url  = ''
    prev_url = _load_prev_url()

    deadline = time.time() + 30
    for line in proc.stdout:
        print(line, end='', flush=True)
        if not new_url:
            m = _URL_RE.search(line)
            if m:
                new_url = m.group(0)
                _save_url(new_url)
                print(f'\n[Tunnel] Public URL: {new_url}')
                if new_url != prev_url:
                    print(f'[Tunnel] URL changed — updating Cloudflare KV...')
                    _update_kv(new_url)
                    print(f'[Tunnel] Relay URL unchanged: {_RELAY_URL}')
                    print(f'[Tunnel] All traffic now forwarding through permanent relay.')
                else:
                    print('[Tunnel] URL unchanged — no KV update needed.')
        if time.time() > deadline and not new_url:
            print('[Tunnel] ERROR: URL not found within 30s', file=sys.stderr)

    proc.wait()
    print(f'[Tunnel] cloudflared exited with code {proc.returncode}')


if __name__ == '__main__':
    main()
