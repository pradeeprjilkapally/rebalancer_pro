#!/usr/bin/env python3
"""
Deploy pipeline for rebalancer_pro (app-specific).

Model:  feature/<taskID-goal> -> develop -> master

  deploy dev    refresh PREVIEW (:5002, `develop` worktree, 127.0.0.1) -> dashboard_pp
                (local-only — never tunnelled; /dashboard_pp rejects relay requests)
  deploy prod   pull master + restart PRODUCTION (:5001) -> dashboard_main (public via relay)

The preview runs from a git worktree so `develop` and `master` can be live at once.
It shares .env / tokens / mydata with production via symlink (you're reviewing code,
not data). "merged" only becomes "live" through this script — closing the gap where a
stale process kept serving old code.
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

_REPO         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKTREE     = os.path.join(os.path.dirname(_REPO), 'pyPMClient-develop')
_PROD_PORT    = 5001
_PREVIEW_PORT = 5002
_PROD_SVC     = 'com.pradeep.zerodha-webhook'
# Config/data/tokens the preview needs from production, symlinked into the worktree.
_SHARED = ['.env', 'agent/.tokens.json.enc', 'agent/brokers/.zerodha_tokens.json', 'mydata']


# --- pure helpers (unit-tested) --------------------------------------------

def preview_url(path: str = '/dashboard_pp', port: int = _PREVIEW_PORT) -> str:
    return f'http://127.0.0.1:{port}{path}'


def prod_url(path: str = '/dashboard_main', port: int = _PROD_PORT) -> str:
    return f'http://127.0.0.1:{port}{path}'


def deploy_ok(status: int | None) -> bool:
    return status == 200


# --- side effects ----------------------------------------------------------

def _run(cmd: list[str], cwd: str | None = None, check: bool = True):
    print(f'  $ {" ".join(cmd)}')
    r = subprocess.run(cmd, cwd=cwd, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f'  ✗ failed: {" ".join(cmd)}')
    return r


def _http_status(url: str, timeout: int = 6) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def _refresh_snapshots(cwd: str) -> None:
    # Best-effort broker refresh (Paytm; Zerodha only if its token is valid).
    subprocess.run([sys.executable, '-m', 'agent.daily_review', '--broker', 'paytm', '--no-notify'],
                   cwd=cwd, check=False)


def _ensure_worktree() -> None:
    if not os.path.isdir(_WORKTREE):
        _run(['git', '-C', _REPO, 'worktree', 'add', _WORKTREE, 'develop'])
    for rel in _SHARED:
        src, link = os.path.join(_REPO, rel), os.path.join(_WORKTREE, rel)
        if os.path.exists(src) and not os.path.lexists(link):
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(src, link)


def _kill_port(port: int) -> None:
    r = subprocess.run(['lsof', '-ti', f'tcp:{port}'], capture_output=True, text=True)
    for pid in r.stdout.split():
        subprocess.run(['kill', pid], check=False)


def deploy_prod() -> int:
    print('[deploy prod] pull master + restart production (:5001) -> dashboard_main')
    _run(['git', '-C', _REPO, 'checkout', 'master'])
    _run(['git', '-C', _REPO, 'pull', '--ff-only', 'rebalancer', 'master'])
    uid = os.getuid() if hasattr(os, 'getuid') else 0
    _run(['launchctl', 'kickstart', '-k', f'gui/{uid}/{_PROD_SVC}'], check=False)
    time.sleep(5)
    _refresh_snapshots(_REPO)
    status = _http_status(prod_url())
    print(f'[deploy prod] dashboard_main -> {status}')
    return 0 if deploy_ok(status) else 1


def deploy_dev() -> int:
    print('[deploy dev] refresh preview (:5002, develop worktree) -> dashboard_pp (local-only)')
    _ensure_worktree()
    _run(['git', '-C', _WORKTREE, 'checkout', 'develop'], check=False)
    _run(['git', '-C', _WORKTREE, 'pull', '--ff-only', 'rebalancer', 'develop'], check=False)
    _kill_port(_PREVIEW_PORT)
    env = {**os.environ, 'WEBHOOK_PORT': str(_PREVIEW_PORT), 'WEBHOOK_BIND': '127.0.0.1'}
    os.makedirs(os.path.join(_REPO, 'logs'), exist_ok=True)
    log = open(os.path.join(_REPO, 'logs', 'preview_webhook.log'), 'a')
    subprocess.Popen([sys.executable, '-m', 'agent.webhook'], cwd=_WORKTREE, env=env,
                     stdout=log, stderr=log)
    time.sleep(6)
    _refresh_snapshots(_WORKTREE)
    status = _http_status(preview_url())
    print(f'[deploy dev] dashboard_pp (local :5002) -> {status}')
    print(f'[deploy dev] review at {preview_url()} (local only — not public)')
    return 0 if deploy_ok(status) else 1


def main() -> int:
    p = argparse.ArgumentParser(description='rebalancer_pro deploy pipeline.')
    p.add_argument('env', choices=['dev', 'prod'],
                   help='dev = preview develop on :5002/dashboard_pp; prod = master on :5001/dashboard_main')
    args = p.parse_args()
    return deploy_dev() if args.env == 'dev' else deploy_prod()


if __name__ == '__main__':
    sys.exit(main())
