"""
Hourly health check (launchd: com.pradeep.sanity-check, StartInterval 3600).

Checks app/webhook, Cloudflare tunnel + relay, dashboard exposure, GitHub CI,
broker tokens, and Slack. On failures:
  - auto-fixable infra/code issues → invokes `claude -p` to diagnose + fix +
    test + open a PR, then posts the PR link to Slack. An auto-fix cooldown
    (_AUTOFIX_COOLDOWN_HOURS) stops a persistent failure from re-invoking Claude
    every hour (token burn + duplicate PRs).
  - human-action issues (auth sentinels, stale tokens, Slack/Access config) →
    alerted to Slack directly, no Claude.

`python -m agent.sanity_check --report` runs the checks read-only (no auto-fix,
no Slack, no file writes) — used by the on-demand `monitor` skill.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from agent.auth import PENDING_FILE as _PAYTM_PENDING
from agent.brokers.zerodha import PENDING_FILE as _ZERODHA_PENDING
from agent.notify import notify, notify_auth_needed

_REPO      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AI        = os.path.join(_REPO, 'action_items.md')
_TURL      = os.path.join(_REPO, '.tunnel_url')
_CLAUDE    = '/Users/pradeepreddyjilkapally/.local/bin/claude'
_GH        = shutil.which('gh') or '/opt/anaconda3/bin/gh'
_GH_REPO   = os.getenv('GH_REPO', 'pradeeprjilkapally/rebalancer_pro')

_RELAY     = os.getenv('WORKERS_RELAY_URL', '').rstrip('/')
_TIMEOUT   = 8
_TODAY     = datetime.now().strftime('%Y-%m-%d')
_DATE_TAG  = datetime.now().strftime('%Y%m%d')
_NOW_LABEL = datetime.now().strftime('%Y-%m-%d %H:%M IST')

# Auto-fix cooldown — at the hourly cadence, a persistent failure must NOT
# re-invoke Claude every hour (token burn + duplicate PRs). After an auto-fix
# attempt, suppress further Claude invocations for this window; the hourly run
# still alerts to Slack that the issue persists.
_AUTOFIX_COOLDOWN_FILE  = os.path.join(_REPO, '.sanity_autofix_cooldown')
_AUTOFIX_COOLDOWN_HOURS = 6

# Alert cooldown — at the hourly cadence, an unchanged set of failures must not
# re-ping Slack / re-log to action_items every hour. Re-alert the SAME failure
# set at most once per window (a changed set or a fresh auto-merge alerts now).
_ALERT_STATE_FILE     = os.path.join(_REPO, '.sanity_alert_state')
_ALERT_COOLDOWN_HOURS = 12

# Checks that can be auto-fixed by Claude (code / infra issues)
_AUTO_FIXABLE = {
    'Cloudflared process',
    'Tunnel (direct)',
    'Relay (Workers)',
    'Webhook (:5001)',
}

# Checks that require human action — Claude can alert but not fix
_HUMAN_REQUIRED = {
    'Auth sentinels',
    'Tokens freshness',
    'CI (GitHub)',
    'Slack webhook',
    'Dashboard exposure',
}


# ---------------------------------------------------------------------------
# Individual checks — each returns (ok: bool, detail: str)
# ---------------------------------------------------------------------------

def check_cloudflared() -> tuple[bool, str]:
    result = subprocess.run(['pgrep', '-f', 'cloudflared'], capture_output=True)
    ok = result.returncode == 0
    return ok, '' if ok else 'cloudflared process not running'


def check_tunnel_direct() -> tuple[bool, str]:
    url = ''
    try:
        url = open(_TURL).read().strip()
        r = requests.get(f'{url}/health', timeout=_TIMEOUT)
        ok = r.status_code < 500
        return ok, '' if ok else f'tunnel returned {r.status_code}'
    except Exception as e:
        return False, f'tunnel unreachable ({url or "no URL"}): {e}'


def check_relay() -> tuple[bool, str]:
    if not _RELAY:
        return False, 'WORKERS_RELAY_URL not set'
    try:
        r = requests.get(f'{_RELAY}/health', timeout=_TIMEOUT)
        ok = r.status_code < 500
        return ok, '' if ok else f'relay returned {r.status_code}'
    except Exception as e:
        return False, f'relay unreachable: {e}'


def check_webhook() -> tuple[bool, str]:
    port = os.getenv('WEBHOOK_PORT', '5001')
    try:
        r = requests.get(f'http://localhost:{port}/health', timeout=_TIMEOUT)
        ok = r.status_code == 200
        return ok, '' if ok else f'webhook returned {r.status_code}'
    except Exception as e:
        return False, f'webhook on :{port} not responding: {e}'


def check_dashboard_exposure() -> tuple[bool, str]:
    """
    The dashboards carry full portfolio data and are protected ONLY by
    Cloudflare Access (no app-level password). Verify they are NOT publicly
    reachable: an unauthenticated hit to the relay /dashboard_main must NOT
    return 200 — it should redirect to the Access login (302). A 200 means
    Access is misconfigured and the portfolio is exposed.

    Fails open on a network error (relay-reachability is covered by check_relay),
    so a blip never false-alarms; only a confirmed 200 trips it.
    """
    if not _RELAY:
        return True, ''
    try:
        r = requests.get(f'{_RELAY}/dashboard_main',
                         allow_redirects=False, timeout=_TIMEOUT)
    except Exception:
        return True, ''
    if r.status_code == 200:
        return False, ('EXPOSED: /dashboard_main is publicly reachable (HTTP 200) — '
                       'Cloudflare Access is not gating it; portfolio data is open')
    return True, ''


def check_slack() -> tuple[bool, str]:
    url = os.getenv('SLACK_WEBHOOK_URL', '').strip()
    if not url:
        return False, 'SLACK_WEBHOOK_URL not set — alerts cannot deliver'
    if not url.startswith('https://hooks.slack.com/'):
        return False, 'SLACK_WEBHOOK_URL malformed'
    return True, ''


def check_auth_sentinels() -> tuple[bool, str]:
    pending = []
    if os.path.isfile(_PAYTM_PENDING):
        age_h = (time.time() - os.path.getmtime(_PAYTM_PENDING)) / 3600
        pending.append(f'Paytm Money (sentinel {age_h:.0f}h old)')
    if os.path.isfile(_ZERODHA_PENDING):
        age_h = (time.time() - os.path.getmtime(_ZERODHA_PENDING)) / 3600
        pending.append(f'Zerodha (sentinel {age_h:.0f}h old)')
    if pending:
        return False, 'Auth still pending: ' + ', '.join(pending)
    return True, ''


def check_tokens() -> tuple[bool, str]:
    issues = []
    # Tokens are encrypted at rest (.tokens.json.enc); fall back to the legacy
    # plaintext path only if the encrypted file is absent.
    enc_path    = os.path.join(_REPO, 'agent', '.tokens.json.enc')
    legacy_path = os.path.join(_REPO, 'agent', '.tokens.json')
    tokens_path = enc_path if os.path.isfile(enc_path) else legacy_path
    if not os.path.isfile(tokens_path):
        issues.append('Paytm tokens missing — re-authenticate from the app')
    else:
        age_h = (time.time() - os.path.getmtime(tokens_path)) / 3600
        if age_h > 26:
            issues.append(f'Paytm tokens {age_h:.0f}h old (may be stale) — re-authenticate')
    return (not issues), '; '.join(issues)


def check_ci() -> tuple[bool, str]:
    """
    Daily backstop for the real-time GitHub Action alert: flag master if its
    most recent completed CI run failed. Fails open (no alarm) if gh is
    unavailable or a run is still in progress — never block on tooling.
    """
    try:
        result = subprocess.run(
            [_GH, 'run', 'list', '--repo', _GH_REPO, '--branch', 'master',
             '--limit', '1', '--json', 'status,conclusion,displayTitle,url'],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            return True, ''                       # gh missing/unauthed — don't false-alarm
        import json as _json
        runs = _json.loads(result.stdout or '[]')
        if not runs:
            return True, ''
        run = runs[0]
        if run.get('status') != 'completed':
            return True, ''                       # still running — judge it next time
        if run.get('conclusion') == 'failure':
            title = (run.get('displayTitle') or '')[:45]
            return False, f"master CI red: {title} — {run.get('url', '')}"
        return True, ''
    except Exception:
        return True, ''                           # fail open


CHECKS = [
    ('Cloudflared process', check_cloudflared),
    ('Tunnel (direct)',     check_tunnel_direct),
    ('Relay (Workers)',     check_relay),
    ('Webhook (:5001)',     check_webhook),
    ('Dashboard exposure', check_dashboard_exposure),
    ('Slack webhook',      check_slack),
    ('Auth sentinels',     check_auth_sentinels),
    ('Tokens freshness',   check_tokens),
    ('CI (GitHub)',        check_ci),
]


# ---------------------------------------------------------------------------
# Claude auto-fix
# ---------------------------------------------------------------------------

def _invoke_claude(fixable: list[tuple[str, str]]) -> str | None:
    """
    Invoke claude CLI to fix `fixable` issues, open a PR, and — because these are
    uptime-critical health incidents — MERGE it to master once the test suite is
    green, so the app self-heals without waiting on a manual merge. Returns the
    PR URL. (Auto-merge is scoped to sanity-check infra fixes only; regular task
    work still goes via PR + Pradeep's review.)
    """
    if not os.path.isfile(_CLAUDE):
        print(f'  [sanity] claude CLI not found at {_CLAUDE}')
        return None

    issues_text = '\n'.join(f'- {label}: {detail}' for label, detail in fixable)

    prompt = f"""Hourly sanity check at {_NOW_LABEL} found these issues in the pyPMClient portfolio agent:

{issues_text}

Repository: {_REPO}
Git remotes: origin = paytmmoney/pyPMClient (upstream, read-only), rebalancer = pradeeprjilkapally/rebalancer_pro (push here)
PR target: master branch on pradeeprjilkapally/rebalancer_pro

This is an uptime-critical health fix. Execute fully without asking for confirmation:
1. Diagnose each issue — read logs, check processes, inspect code.
2. Implement the minimal code fix.
3. Run the deterministic suite: (cd tests && python3 -m pytest -m "not live" -q). It MUST pass before you go further.
4. Create branch: {_DATE_TAG}-<2-to-3-hyphenated-words-describing-the-fix>
5. Commit (NO AI attribution — no Co-Authored-By, no "Generated with"): "<branch-name> - <what changed and why>"
6. Push: git push rebalancer <branch-name>   (the pre-push hook re-runs the suite)
7. Open the PR: gh pr create --repo pradeeprjilkapally/rebalancer_pro --base master
8. AUTO-MERGE — only if step 3's suite passed: gh pr merge <pr> --repo pradeeprjilkapally/rebalancer_pro --squash --delete-branch
   If the suite did NOT pass, DO NOT merge — leave the PR open for Pradeep.
9. Print the PR URL as the absolute last line of your response — no other text after it.

Rules: never push to origin; never PR to paytmmoney/pyPMClient; merge ONLY if tests pass; this auto-merge authority is for sanity-check infra fixes only."""

    log_path = os.path.join(_REPO, 'logs', 'sanity_autofix.log')
    print(f'  [sanity] invoking claude — log: {log_path}')

    env = {**os.environ, 'HOME': os.path.expanduser('~')}

    with open(log_path, 'w') as log_f:
        result = subprocess.run(
            [_CLAUDE, '-p', prompt, '--dangerously-skip-permissions'],
            stdout=log_f,
            stderr=subprocess.STDOUT,
            timeout=600,
            cwd=_REPO,
            env=env,
        )

    # Read back output to extract PR URL
    try:
        output = open(log_path).read()
    except Exception:
        output = ''

    pr_url = None
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith('https://github.com/'):
            pr_url = line
            break

    print(f'  [sanity] claude exited (code={result.returncode})  PR: {pr_url or "not found"}')
    return pr_url


# ---------------------------------------------------------------------------
# action_items.md writer
# ---------------------------------------------------------------------------

def _append_action_item(item: str, notes: str):
    try:
        content = open(_AI).read()
        # Dedup: don't add a row whose item label already appears (hourly runs
        # otherwise pile up identical rows for the same persisting issue).
        if f'| {item} |' in content:
            return
        new_row = f'| {_TODAY} | — | {item} | Claude | {notes} |'
        content = content.replace(
            '|-------|--------|------|-------|-------|',
            f'|-------|--------|------|-------|-------|\n{new_row}',
            1,
        )
        with open(_AI, 'w') as f:
            f.write(content)
    except Exception as e:
        print(f'  [sanity] Could not update action_items.md: {e}')


def _alert_suppressed(failures: list[tuple[str, str]]) -> bool:
    """
    True if this exact set of failure labels was already alerted within the
    cooldown window — so an unchanged situation doesn't re-ping every hour.
    A new/changed failure set (or first occurrence) returns False and refreshes
    the stamp.
    """
    sig = hashlib.sha1('|'.join(sorted(l for l, _ in failures)).encode()).hexdigest()[:12]
    try:
        prev_sig, prev_ts = open(_ALERT_STATE_FILE).read().split(',')
        if sig == prev_sig and (time.time() - float(prev_ts)) / 3600 < _ALERT_COOLDOWN_HOURS:
            return True
    except (OSError, ValueError):
        pass
    with open(_ALERT_STATE_FILE, 'w') as f:
        f.write(f'{sig},{time.time()}')
    return False


def _broker_login_url(broker: str) -> str | None:
    """
    Build a fresh OAuth login URL for re-auth (offline — no session needed), so a
    token alert can carry a tappable link. Returns None if creds are missing.
    """
    try:
        if broker == 'paytm':
            key, secret = os.getenv('PAYTM_API_KEY', ''), os.getenv('PAYTM_API_SECRET', '')
            if not key or not secret:
                return None
            from pmClient.pmClient import PMClient
            return PMClient(api_secret=secret, api_key=key).login(f'sanity_{os.getpid()}')
        if broker == 'zerodha':
            key = os.getenv('ZERODHA_API_KEY', '')
            if not key:
                return None
            from kiteconnect import KiteConnect
            return KiteConnect(api_key=key).login_url()
    except Exception as e:
        print(f'  [sanity] could not build {broker} login URL: {e}')
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _autofix_cooldown_remaining() -> float:
    """Hours left on the auto-fix cooldown, or 0.0 if clear to invoke Claude."""
    try:
        age_h = (time.time() - os.path.getmtime(_AUTOFIX_COOLDOWN_FILE)) / 3600
    except OSError:
        return 0.0
    # Clamp to [0, window]: filesystem mtime resolution can make age slightly
    # negative right after writing (seen on Windows CI), which would otherwise
    # push 'remaining' above the window.
    return min(_AUTOFIX_COOLDOWN_HOURS, max(0.0, _AUTOFIX_COOLDOWN_HOURS - age_h))


def _mark_autofix():
    """Stamp the cooldown so the next hourly runs don't re-invoke Claude."""
    with open(_AUTOFIX_COOLDOWN_FILE, 'w') as f:
        f.write(_NOW_LABEL)


def _run_checks() -> list[tuple[str, str]]:
    """Run every check; print a line per check; return the list of failures."""
    failures = []
    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f'check crashed: {e}'
        print(f'  [{"OK  " if ok else "FAIL"}] {label}' + (f' — {detail}' if detail else ''))
        if not ok:
            failures.append((label, detail))
    return failures


def main():
    parser = argparse.ArgumentParser(description='Portfolio agent health check.')
    parser.add_argument('--report', action='store_true',
                        help='Run checks and print status only — no auto-fix, no Slack, '
                             'no action_items writes. Used by the on-demand `monitor` skill.')
    args = parser.parse_args()

    print(f'\n[{_NOW_LABEL}] Sanity check starting...')
    failures = _run_checks()

    # Read-only mode: report and exit non-zero on any failure.
    if args.report:
        print(f"\n  {'All checks passed ✓' if not failures else f'{len(failures)} failure(s)'}")
        sys.exit(1 if failures else 0)

    if not failures:
        print('  All checks passed — no action needed.')
        return

    fixable      = [(l, d) for l, d in failures if l in _AUTO_FIXABLE]
    human_needed = [(l, d) for l, d in failures if l in _HUMAN_REQUIRED]

    print(f'\n  {len(failures)} failure(s): {len(fixable)} auto-fixable, {len(human_needed)} need human action')

    # Auto-fix infra/code issues via Claude — but only if not on cooldown, so a
    # persistent failure at the hourly cadence never re-triggers fixes/PRs.
    pr_url = None
    on_cooldown = _autofix_cooldown_remaining() if fixable else 0.0
    if fixable and not on_cooldown:
        try:
            pr_url = _invoke_claude(fixable)
            _mark_autofix()
        except subprocess.TimeoutExpired:
            print('  [sanity] Claude timed out after 600s')
            _mark_autofix()
        except Exception as e:
            print(f'  [sanity] Claude invocation failed: {e}')
    elif fixable:
        print(f'  [sanity] auto-fix on cooldown ({on_cooldown:.1f}h left) — alerting only, not re-invoking Claude')

    # Suppress repeat alerts for an unchanged failure set (hourly cadence would
    # otherwise ping every hour). A fresh auto-merge always announces.
    if not pr_url and _alert_suppressed(failures):
        print('  [sanity] same failures alerted within cooldown — staying quiet this run')
        return

    # Token/auth issues → send a tagged Slack message with a tappable login link
    # so the token can be reset from a phone, no laptop. (check label → broker)
    token_brokers = []
    if any(l == 'Tokens freshness' for l, _ in human_needed):
        token_brokers.append('paytm')
    for _, detail in human_needed:
        if 'Zerodha' in detail and 'zerodha' not in token_brokers:
            token_brokers.append('zerodha')
    for broker in token_brokers:
        url = _broker_login_url(broker)
        label = 'Paytm Money' if broker == 'paytm' else 'Zerodha'
        if url:
            notify_auth_needed(label, url)        # tagged + tappable link
        else:
            notify(f'*{label} — token needed* but a login link could not be built '
                   f'(check API creds). Reset it from the app.', tag=True)

    # Log human-required issues to action_items.md (deduped inside). The label
    # carries NO date (the row's Filed column has it), so a persistent issue
    # maps to one stable row instead of one-per-day.
    for label, detail in human_needed:
        _append_action_item(f'[sanity] {label}', detail.replace('|', '/'))

    # Summary message — short and glanceable; tag only when something needs you.
    hhmm = datetime.now().strftime('%H:%M')
    n    = len(failures)
    lines = [f'⚠️ Sanity check {hhmm} IST — {n} issue{"s" if n != 1 else ""}']

    if fixable:
        names = ', '.join(label for label, _ in fixable)
        if pr_url:
            lines += [f'Auto-fixed & merged to master: {names}', f'PR (FYI) → {pr_url}']
        elif on_cooldown:
            lines.append(f'Still failing: {names} (auto-fix on cooldown {on_cooldown:.0f}h)')
        else:
            lines.append(f'Auto-fix tried: {names} (not merged — tests failed or no PR; see logs/sanity_autofix.log)')

    if human_needed:
        lines.append('Needs you:')
        lines += [f'• {detail}' for _, detail in human_needed]

    notify('\n'.join(lines), tag=bool(human_needed))
    print('  Slack notification sent.')


if __name__ == '__main__':
    main()
