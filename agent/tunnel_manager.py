"""
Manages the cloudflared quick tunnel.

- Forces HTTP/2 protocol to avoid QUIC NAT-timeout crashes (root cause of recurring failures)
- Active health watchdog: kills cloudflared when the public URL stops responding,
  triggering a clean restart with a fresh URL + immediate KV update
- Restarts cloudflared automatically if it crashes or is killed by the watchdog
- Updates Cloudflare KV on every URL change
- Permanent relay URL (never changes): https://portfolio-relay.pradeeprjilkapally.workers.dev
"""
import os
import re
import subprocess
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_URL_FILE = os.path.join(_REPO_DIR, '.tunnel_url')
_CF_BIN   = '/opt/anaconda3/bin/cloudflared'
_URL_RE   = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')

_CF_TOKEN   = os.getenv('CLOUDFLARE_API_TOKEN', '')
_CF_ACCOUNT = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
_CF_KV_NS   = os.getenv('CLOUDFLARE_KV_NAMESPACE_ID', '')

_RESTART_DELAY    = 2    # seconds before restarting after exit
_HEALTH_INTERVAL  = 120  # check tunnel URL every 2 minutes
_HEALTH_TIMEOUT   = 10   # seconds per health request
_HEALTH_STRIKES   = 2    # consecutive failures before killing cloudflared
_URL_WAIT_TIMEOUT = 60   # warn if URL not captured within this many seconds


def _load_url() -> str:
    try:
        return open(_URL_FILE).read().strip()
    except FileNotFoundError:
        return ''


def _save_url(url: str):
    with open(_URL_FILE, 'w') as f:
        f.write(url)


def _update_kv(url: str) -> bool:
    if not all([_CF_TOKEN, _CF_ACCOUNT, _CF_KV_NS]):
        print('[Tunnel] KV credentials missing — skipping update.')
        return False
    try:
        r = requests.put(
            f'https://api.cloudflare.com/client/v4/accounts/{_CF_ACCOUNT}'
            f'/storage/kv/namespaces/{_CF_KV_NS}/values/tunnel_url',
            headers={'Authorization': f'Bearer {_CF_TOKEN}', 'Content-Type': 'text/plain'},
            data=url,
            timeout=10,
        )
        ok = r.json().get('success', False)
        print(f'[Tunnel] KV {"updated" if ok else "FAILED"} → {url}')
        return ok
    except Exception as e:
        print(f'[Tunnel] KV update error: {e}')
        return False


def _health_watchdog(proc: subprocess.Popen, get_url):
    """
    Daemon thread: periodically GETs <tunnel_url>/health.
    Kills the cloudflared process after _HEALTH_STRIKES consecutive failures,
    which unblocks _run_once and triggers a fresh restart with a new URL.
    """
    # Wait for tunnel to establish before first check
    time.sleep(_HEALTH_INTERVAL)

    strikes = 0
    while proc.poll() is None:
        url = get_url()
        if url:
            try:
                r = requests.get(f'{url}/health', timeout=_HEALTH_TIMEOUT)
                if r.status_code < 500:
                    strikes = 0
                else:
                    strikes += 1
                    print(f'[Tunnel][watchdog] {r.status_code} from tunnel '
                          f'(strike {strikes}/{_HEALTH_STRIKES})', flush=True)
            except Exception as e:
                strikes += 1
                print(f'[Tunnel][watchdog] health check failed: {e} '
                      f'(strike {strikes}/{_HEALTH_STRIKES})', flush=True)

            if strikes >= _HEALTH_STRIKES:
                print('[Tunnel][watchdog] tunnel is dead — killing cloudflared to force restart',
                      flush=True)
                proc.kill()
                return

        time.sleep(_HEALTH_INTERVAL)


def _run_once() -> int:
    """Start cloudflared, stream output, update KV on URL change. Returns exit code."""
    # --protocol http2 forces TCP-based HTTP/2, avoiding QUIC NAT-timeout crashes
    proc = subprocess.Popen(
        [_CF_BIN, 'tunnel', '--url', 'http://localhost:5001',
         '--no-autoupdate', '--protocol', 'http2'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    print(f'[Tunnel] cloudflared started (pid={proc.pid})', flush=True)

    # Shared mutable ref so watchdog always sees the latest URL
    active_url = [_load_url()]

    watchdog = threading.Thread(
        target=_health_watchdog,
        args=(proc, lambda: active_url[0]),
        daemon=True,
    )
    watchdog.start()

    deadline = time.time() + _URL_WAIT_TIMEOUT
    warned   = False

    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()

        m = _URL_RE.search(line)
        if m:
            found = m.group(0)
            if found != active_url[0]:
                active_url[0] = found
                _save_url(found)
                print(f'\n[Tunnel] Active URL: {found}', flush=True)
                _update_kv(found)

        if not warned and time.time() > deadline and not active_url[0]:
            print('[Tunnel] WARNING: no URL found within 60s', file=sys.stderr, flush=True)
            warned = True

    proc.wait()
    return proc.returncode


def main():
    print('[Tunnel] Manager starting — target: http://localhost:5001  protocol: http2')
    while True:
        code = _run_once()
        print(f'[Tunnel] cloudflared exited (code={code}) — restarting in {_RESTART_DELAY}s...',
              flush=True)
        time.sleep(_RESTART_DELAY)


if __name__ == '__main__':
    main()
