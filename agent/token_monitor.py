"""
Token monitor for the Claude <-> Codex handoff loop (launchd: com.pradeep.token-monitor).

Reads Claude Code session logs (~/.claude/projects/**/*.jsonl), estimates the
rolling 5-hour token usage, and drives a handoff baton (HANDOFF.md + Slack):

  - usage >= HANDOFF threshold AND owner == claude
        -> hand the active work to Codex (owner=codex); Slack-ping to switch terminals.
  - usage <  RESUME  threshold AND owner == codex
        -> Claude's rolling window has refreshed; hand BACK to Claude (owner=claude);
           Slack-ping to switch back. (Codex is a free account — hand back ASAP so its
           quota is barely touched.)

Runs OUTSIDE the Claude session (its own launchd job) so it keeps working when
Claude is at/near its limit and spends none of Claude's tokens.

IMPORTANT — the % is an ESTIMATE. Anthropic does not expose a live plan-% for
subscriptions, so this counts input+output+cache_creation tokens in the trailing
5h against a configurable ceiling (CLAUDE_5H_TOKEN_BUDGET). The monitor prints the
raw rolling-token count so you can calibrate the ceiling to the value at which you
actually see Claude Code's "approaching limit" warning.
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from agent.notify import notify

_REPO        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_GLOB    = os.path.expanduser('~/.claude/projects/**/*.jsonl')
_HANDOFF_MD  = os.path.join(_REPO, 'HANDOFF.md')
_STATE_FILE  = os.path.join(_REPO, '.token_monitor_state')   # gitignored; holds current owner

_WINDOW_HOURS = 5
# Pro yearly plan: the real 5h ceiling isn't published as a token number, so this
# is an estimate to calibrate. Counted metric = input + output + cache_creation
# (cache_read is excluded — it's near-free and would dominate).
_BUDGET       = int(os.getenv('CLAUDE_5H_TOKEN_BUDGET', '5000000'))
_HANDOFF_PCT  = float(os.getenv('HANDOFF_THRESHOLD_PCT', '88'))   # hand to Codex at/above this
_RESUME_PCT   = float(os.getenv('RESUME_THRESHOLD_PCT', '50'))    # hand back to Claude below this


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def parse_usage(paths: list[str]) -> list[tuple[datetime, int]]:
    """Return (timestamp, counted_tokens) for every usage record across the logs."""
    out = []
    for path in paths:
        try:
            fh = open(path, errors='ignore')
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                ts = rec.get('timestamp')
                usage = (rec.get('message') or {}).get('usage') if isinstance(rec, dict) else None
                if not ts or not usage:
                    continue
                try:
                    t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except ValueError:
                    continue
                out.append((t, _counted(usage)))
    return out


def _counted(usage: dict) -> int:
    """Tokens that count toward the estimate (exclude near-free cache_read)."""
    return (int(usage.get('input_tokens', 0))
            + int(usage.get('output_tokens', 0))
            + int(usage.get('cache_creation_input_tokens', 0)))


def rolling_tokens(records: list[tuple[datetime, int]], now: datetime,
                   hours: int = _WINDOW_HOURS) -> int:
    """Sum counted tokens in the trailing `hours` window ending at `now`."""
    cutoff = now - timedelta(hours=hours)
    return sum(tok for t, tok in records if t >= cutoff)


def usage_pct(tokens: int, budget: int = _BUDGET) -> float:
    return (tokens / budget * 100.0) if budget > 0 else 0.0


def decide(pct: float, owner: str, handoff_pct: float = _HANDOFF_PCT,
           resume_pct: float = _RESUME_PCT) -> tuple[str | None, str]:
    """
    Decide the next baton move. Returns (action, new_owner):
      ('handoff', 'codex')   -> Claude near limit, give work to Codex
      ('handback', 'claude') -> Claude refreshed, take work back from Codex
      (None, owner)          -> no change
    """
    if owner == 'claude' and pct >= handoff_pct:
        return 'handoff', 'codex'
    if owner == 'codex' and pct < resume_pct:
        return 'handback', 'claude'
    return None, owner


# ---------------------------------------------------------------------------
# State + baton I/O
# ---------------------------------------------------------------------------

def read_owner() -> str:
    try:
        owner = open(_STATE_FILE).read().strip()
        return owner if owner in ('claude', 'codex') else 'claude'
    except OSError:
        return 'claude'


def write_owner(owner: str) -> None:
    with open(_STATE_FILE, 'w') as f:
        f.write(owner)


def _git(*args) -> str:
    import subprocess
    try:
        return subprocess.run(['git', '-C', _REPO, *args],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ''


def write_handoff(to_agent: str, pct: float, tokens: int) -> None:
    """Write the HANDOFF.md baton the other agent reads on `resume`."""
    branch = _git('rev-parse', '--abbrev-ref', 'HEAD') or 'unknown'
    dirty  = _git('status', '--porcelain')
    now    = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    from_agent = 'Claude' if to_agent == 'codex' else 'Codex'
    to_name    = 'Codex' if to_agent == 'codex' else 'Claude'
    body = f"""# HANDOFF — {from_agent} → {to_name}

Owner: {to_agent}
When:  {now}
Reason: {'Claude near its 5h limit (~%.0f%% est) — continue on Codex' % pct if to_agent == 'codex' else 'Claude refreshed (~%.0f%% est) — take work back (Codex is free-tier, minimise its usage)' % pct}
Rolling-5h tokens (est): {tokens:,}  (budget {_BUDGET:,})

Branch: {branch}
Uncommitted changes:
{dirty or '  (clean working tree)'}

## To resume
1. Open the {to_name} terminal.
2. Type `resume` — it reads this file, checks out `{branch}`, and continues the
   active task in task.md from where it stopped.
3. Finish per the review-gate (tests -> commit -> PR -> Slack). Same skills both sides.
"""
    with open(_HANDOFF_MD, 'w', encoding='utf-8') as f:   # body has →/— (non-cp1252)
        f.write(body)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Claude<->Codex token handoff monitor.')
    parser.add_argument('--report', action='store_true',
                        help='Print rolling usage only — no baton/Slack writes.')
    args = parser.parse_args()

    records = parse_usage(glob.glob(_LOG_GLOB, recursive=True))
    now     = datetime.now(timezone.utc)
    tokens  = rolling_tokens(records, now)
    pct     = usage_pct(tokens)
    owner   = read_owner()

    print(f'[token-monitor] rolling-5h tokens={tokens:,} / budget={_BUDGET:,} '
          f'(~{pct:.0f}% est) | owner={owner}')

    if args.report:
        return

    action, new_owner = decide(pct, owner)
    if not action:
        return

    write_owner(new_owner)
    write_handoff(new_owner, pct, tokens)

    if action == 'handoff':
        notify(f'🔁 *Claude near its 5h limit* (~{pct:.0f}% est, {tokens:,} tok).\n'
               f'Handing the active task to *Codex*. Switch to the Codex terminal and '
               f'type `resume` (HANDOFF.md has the state). I\'ll take it back the moment '
               f'Claude refreshes.', tag=True)
    else:  # handback
        notify(f'✅ *Claude tokens refreshed* (~{pct:.0f}% est).\n'
               f'Taking the task back from Codex (free-tier — keeping its usage minimal). '
               f'Switch to the Claude terminal and type `resume`.', tag=True)
    print(f'[token-monitor] {action} → owner now {new_owner}; HANDOFF.md + Slack updated')


if __name__ == '__main__':
    main()
