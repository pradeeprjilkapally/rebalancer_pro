"""
Manages the cloudflared quick tunnel.

- Forces HTTP/2 protocol to avoid QUIC NAT-timeout crashes (root cause of recurring failures)
- Pins cloudflared's metrics port so liveness can be read locally
- Active health watchdog: keys off cloudflared's local metrics
  (cloudflared_tunnel_ha_connections) rather than the ephemeral public hostname.
  ha_connections is the authoritative, DNS-independent signal — a quick-tunnel
  hostname can stop resolving locally while the tunnel is fine, and (the failure
  this guards against) cloudflared can stay alive with zero edge connections for
  hours. The watchdog kills cloudflared once it is provably disconnected, forcing
  a clean restart with a fresh URL.
- Restarts cloudflared automatically if it crashes or is killed by the watchdog
- Verify-before-publish: a freshly minted quick-tunnel URL is written to
  .tunnel_url + Cloudflare KV only once the tunnel is provably live —
  edge-connected (ha_connections > 0) with a healthy local origin. Both checks
  are DNS-independent, so a network that NXDOMAINs trycloudflare hostnames can no
  longer withhold a good URL (the source of relay 530s and morning failures).
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

# Pin cloudflared's metrics server so the watchdog always knows where to read
# ha_connections (cloudflared otherwise picks a random port per run).
_METRICS_ADDR = '127.0.0.1:20241'
_METRICS_URL  = f'http://{_METRICS_ADDR}/metrics'

_CF_TOKEN   = os.getenv('CLOUDFLARE_API_TOKEN', '')
_CF_ACCOUNT = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
_CF_KV_NS   = os.getenv('CLOUDFLARE_KV_NAMESPACE_ID', '')

_RESTART_DELAY    = 2    # seconds before restarting after exit
_HEALTH_INTERVAL  = 30   # check liveness every 30s
_HEALTH_TIMEOUT   = 10   # seconds per health/metrics request
_HEALTH_STRIKES   = 3    # consecutive disconnected checks before killing (~90s)
_URL_WAIT_TIMEOUT = 60   # warn if URL not captured within this many seconds
_PUBLISH_TIMEOUT  = 90   # wait this long for a fresh URL to answer /health before publishing
_PUBLISH_POLL     = 3    # seconds between reachability polls while publishing


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


def _ha_connections() -> int | None:
    """
    Active edge-connection count from cloudflared's local metrics, or None if the
    metrics endpoint can't be read. This is the authoritative liveness signal:
    it reflects the tunnel's real state at Cloudflare's edge and never depends on
    the ephemeral public hostname resolving locally.
    """
    try:
        r = requests.get(_METRICS_URL, timeout=_HEALTH_TIMEOUT)
    except Exception:
        return None
    for line in r.text.splitlines():
        if line.startswith('cloudflared_tunnel_ha_connections'):
            try:
                return int(float(line.split()[-1]))
            except ValueError:
                return None
    return None


def _url_reachable(url: str) -> bool:
    """True if <url>/health answers below 500. Empty url / any error -> False.

    NOTE: this resolves the public hostname via the LOCAL resolver, which can
    NXDOMAIN trycloudflare hostnames on some networks. Use only as a watchdog
    fallback — never to gate publishing (see _publishable)."""
    if not url:
        return False
    try:
        return requests.get(f'{url}/health', timeout=_HEALTH_TIMEOUT).status_code < 500
    except Exception:
        return False


def _origin_healthy() -> bool:
    """Is the local webhook (the tunnel's origin) up? DNS-independent (localhost)."""
    try:
        return requests.get('http://localhost:5001/health', timeout=_HEALTH_TIMEOUT).status_code == 200
    except Exception:
        return False


def _publishable() -> bool:
    """
    Safe to publish the current URL to .tunnel_url + KV?

    Gates on DNS-independent signals only: cloudflared is edge-connected
    (ha_connections > 0) and the local origin is healthy. The relay resolves
    trycloudflare at Cloudflare's edge, so once cloudflared has live edge
    connections the hostname is routable there regardless of whether THIS
    machine's resolver can see it. Probing the public URL locally (the old
    gate) wrongly withheld good URLs whenever the router NXDOMAIN'd trycloudflare
    — leaving a dead URL in KV and 530s on the relay.
    """
    return (_ha_connections() or 0) > 0 and _origin_healthy()


def _health_watchdog(proc: subprocess.Popen, get_url):
    """
    Daemon thread: keys off cloudflared's local metrics (ha_connections).
    ha_connections == 0 means the tunnel is provably disconnected from the edge
    even if the process is still alive — the exact wedged state that left a dead
    URL in KV for hours. Falls back to a public /health probe only when metrics
    are unreadable. Kills cloudflared after _HEALTH_STRIKES consecutive
    disconnected checks, unblocking _run_once for a fresh restart.
    """
    # Wait for tunnel to establish before first check
    time.sleep(_HEALTH_INTERVAL)

    strikes = 0
    while proc.poll() is None:
        ha = _ha_connections()
        # ha is None -> metrics unreadable; fall back to probing the public URL so
        # a real outage still trips the watchdog. ha > 0 -> connected at the edge,
        # so a local-DNS blip on the hostname can never false-kill a good tunnel.
        healthy = _url_reachable(get_url()) if ha is None else ha > 0

        if healthy:
            strikes = 0
        else:
            strikes += 1
            print(f'[Tunnel][watchdog] tunnel disconnected (ha_connections={ha}) '
                  f'(strike {strikes}/{_HEALTH_STRIKES})', flush=True)
            if strikes >= _HEALTH_STRIKES:
                print('[Tunnel][watchdog] tunnel is dead — killing cloudflared to force restart',
                      flush=True)
                proc.kill()
                return

        time.sleep(_HEALTH_INTERVAL)


def _publish_when_reachable(url: str):
    """
    Write url to .tunnel_url + KV, but only once the tunnel is provably live —
    edge-connected (ha_connections > 0) with a healthy local origin. Both signals
    are DNS-independent, so a router that NXDOMAINs trycloudflare no longer blocks
    a good URL from reaching the relay. Runs in its own thread so the stdout
    reader keeps draining cloudflared.
    """
    deadline = time.time() + _PUBLISH_TIMEOUT
    while time.time() < deadline:
        if _publishable():
            _save_url(url)
            print(f'\n[Tunnel] Active URL: {url}', flush=True)
            _update_kv(url)
            return
        time.sleep(_PUBLISH_POLL)
    print(f'[Tunnel] new URL {url} not edge-connected within {_PUBLISH_TIMEOUT}s '
          f'— not publishing; watchdog will recycle the tunnel', flush=True)


def _run_once() -> int:
    """Start cloudflared, stream output, update KV on URL change. Returns exit code."""
    # --protocol http2 forces TCP-based HTTP/2, avoiding QUIC NAT-timeout crashes
    # --metrics pins the metrics port so the watchdog can read ha_connections
    proc = subprocess.Popen(
        [_CF_BIN, 'tunnel', '--url', 'http://localhost:5001',
         '--no-autoupdate', '--protocol', 'http2', '--metrics', _METRICS_ADDR],
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
                # Track immediately so the watchdog's fallback probe has a target,
                # but publish to .tunnel_url + KV only after it answers /health.
                active_url[0] = found
                threading.Thread(
                    target=_publish_when_reachable,
                    args=(found,),
                    daemon=True,
                ).start()

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
