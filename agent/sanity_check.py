"""
7 AM IST daily sanity check.

On failures:
  - invokes `claude -p` to diagnose + fix + test + open a PR autonomously
  - sends a WhatsApp notification with the PR link (or failure summary if unfixable)

Issues that require human action (auth sentinels, stale tokens) are flagged
via WhatsApp directly without invoking Claude.
"""
import os
import re
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
from agent.whatsapp import send_whatsapp

_REPO      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TASK      = os.path.join(_REPO, 'task.md')
_AI        = os.path.join(_REPO, 'action_items.md')
_TURL      = os.path.join(_REPO, '.tunnel_url')
_CLAUDE    = '/Users/pradeepreddyjilkapally/.local/bin/claude'

_RELAY     = os.getenv('WORKERS_RELAY_URL', '').rstrip('/')
_TIMEOUT   = 8
_TODAY     = datetime.now().strftime('%Y-%m-%d')
_DATE_TAG  = datetime.now().strftime('%Y%m%d')
_NOW_LABEL = datetime.now().strftime('%Y-%m-%d %H:%M IST')

# Checks that can be auto-fixed by Claude (code / infra issues)
_AUTO_FIXABLE = {
    'Cloudflared process',
    'Tunnel (direct)',
    'Relay (Workers)',
    'Webhook (:5001)',
    'Twilio API',
    'Open tasks',
}

# Checks that require human action — Claude can alert but not fix
_HUMAN_REQUIRED = {
    'Auth sentinels',
    'Tokens freshness',
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


def check_twilio() -> tuple[bool, str]:
    sid   = os.getenv('TWILIO_ACCOUNT_SID', '')
    token = os.getenv('TWILIO_AUTH_TOKEN', '')
    if not sid or not token:
        return False, 'TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not set'
    try:
        r = requests.get(
            f'https://api.twilio.com/2010-04-01/Accounts/{sid}.json',
            auth=(sid, token), timeout=_TIMEOUT,
        )
        ok = r.status_code == 200
        return ok, '' if ok else f'Twilio API returned {r.status_code}'
    except Exception as e:
        return False, f'Twilio API unreachable: {e}'


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


def check_task_md() -> tuple[bool, str]:
    try:
        content = open(_TASK).read()
        stripped = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        active = re.findall(r'^Task:\s+(\d{2}-\d{6})', stripped, re.MULTILINE)
        if active:
            return False, f'Open tasks in task.md: {", ".join(active)}'
        return True, ''
    except Exception as e:
        return False, f'Could not read task.md: {e}'


CHECKS = [
    ('Cloudflared process', check_cloudflared),
    ('Tunnel (direct)',     check_tunnel_direct),
    ('Relay (Workers)',     check_relay),
    ('Webhook (:5001)',     check_webhook),
    ('Twilio API',         check_twilio),
    ('Auth sentinels',     check_auth_sentinels),
    ('Tokens freshness',   check_tokens),
    ('Open tasks',         check_task_md),
]


# ---------------------------------------------------------------------------
# Claude auto-fix
# ---------------------------------------------------------------------------

def _invoke_claude(fixable: list[tuple[str, str]]) -> str | None:
    """
    Invoke claude CLI to fix `fixable` issues, create a PR, return PR URL.
    Returns the PR URL string or None if it couldn't be determined.
    """
    if not os.path.isfile(_CLAUDE):
        print(f'  [sanity] claude CLI not found at {_CLAUDE}')
        return None

    issues_text = '\n'.join(f'- {label}: {detail}' for label, detail in fixable)

    prompt = f"""Morning sanity check at {_NOW_LABEL} found these issues in the pyPMClient portfolio agent:

{issues_text}

Repository: {_REPO}
Git remotes: origin = paytmmoney/pyPMClient (upstream, read-only), rebalancer = pradeeprjilkapally/rebalancer_pro (push here)
PR target: master branch on pradeeprjilkapally/rebalancer_pro

Execute the following fully without asking for confirmation:
1. Diagnose each issue — read logs, check processes, inspect code
2. Implement the code fix
3. Test end-to-end (use existing scripts in scripts/ where applicable)
4. Create git branch named: {_DATE_TAG}-<2-to-3-hyphenated-words-describing-the-fix>
5. Commit with message: "<branch-name> - <what changed and why>"
6. Push: git push rebalancer <branch-name>
7. Create PR using: gh pr create --repo pradeeprjilkapally/rebalancer_pro --base master
8. Print the PR URL as the absolute last line of your response — no other text after it

Rules: never push to origin. Never create a PR to paytmmoney/pyPMClient."""

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f'\n[{_NOW_LABEL}] Morning sanity check starting...')
    failures = []

    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f'check crashed: {e}'
        status = 'OK  ' if ok else 'FAIL'
        print(f'  [{status}] {label}' + (f' — {detail}' if detail else ''))
        if not ok:
            failures.append((label, detail))

    if not failures:
        print('  All checks passed — no action needed.')
        return

    fixable      = [(l, d) for l, d in failures if l in _AUTO_FIXABLE]
    human_needed = [(l, d) for l, d in failures if l in _HUMAN_REQUIRED]

    print(f'\n  {len(failures)} failure(s): {len(fixable)} auto-fixable, {len(human_needed)} need human action')

    # Auto-fix infra/code issues via Claude
    pr_url = None
    if fixable:
        try:
            pr_url = _invoke_claude(fixable)
        except subprocess.TimeoutExpired:
            print('  [sanity] Claude timed out after 600s')
        except Exception as e:
            print(f'  [sanity] Claude invocation failed: {e}')

    # Log human-required issues to action_items.md
    for label, detail in human_needed:
        _append_action_item(
            f'[sanity {_TODAY}] {label}',
            detail.replace('|', '/'),
        )

    # Compose WhatsApp notification — short and glanceable.
    hhmm = datetime.now().strftime('%H:%M')
    n    = len(failures)
    lines = [f'⚠️ Sanity check {hhmm} IST — {n} issue{"s" if n != 1 else ""}']

    if fixable:
        names = ', '.join(label for label, _ in fixable)
        if pr_url:
            lines += [f'Auto-fixed: {names}', f'Review PR → {pr_url}']
        else:
            lines.append(f'Auto-fix tried: {names} (no PR — see logs/sanity_autofix.log)')

    if human_needed:
        lines.append('Needs you:')
        lines += [f'• {detail}' for _, detail in human_needed]

    send_whatsapp('\n'.join(lines))
    print('  WhatsApp notification sent.')


if __name__ == '__main__':
    main()
