"""
Install / repair the KeepAlive launchd daemons (tunnel + webhook) from the
canonical plists tracked in launchd/.

Why this exists
---------------
launchd opens a job's StandardOutPath / StandardErrorPath *itself*, before exec,
and macOS TCC denies launchd write access to ~/Documents. The original plists
wrote logs into the repo's logs/ folder (under ~/Documents), so every spawn
failed with EX_CONFIG (78) — no exec, no output — and KeepAlive respawned
~1/sec indefinitely. The canonical plists in launchd/ log to ~/Library/Logs,
which is not TCC-protected.

This script copies the canonical plists into ~/Library/LaunchAgents, creates the
log directory, then boots each job out and back in so the new definition takes
effect. It is idempotent — safe to run repeatedly.

Usage:  python -m scripts.install_launchd
"""
import os
import plistlib
import shutil
import subprocess
import sys

_REPO       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR    = os.path.join(_REPO, 'launchd')
_AGENTS_DIR = os.path.expanduser('~/Library/LaunchAgents')
_LOG_DIR    = os.path.expanduser('~/Library/Logs/rebalancer')
_UID        = os.getuid()


def _log_paths(plist_path: str) -> list[str]:
    with open(plist_path, 'rb') as f:
        data = plistlib.load(f)
    return [data[k] for k in ('StandardOutPath', 'StandardErrorPath') if k in data]


def _reject_documents_logs(plist_path: str):
    """Guard: a TCC-protected log path would silently re-break the job."""
    for p in _log_paths(plist_path):
        protected = ('/Documents/', '/Desktop/', '/Downloads/')
        if any(seg in p for seg in protected):
            sys.exit(f'ERROR: {os.path.basename(plist_path)} logs to TCC-protected '
                     f'path {p} — launchd cannot open it (EX_CONFIG). Move it under '
                     f'~/Library/Logs.')


def install_one(src: str) -> str:
    label = os.path.splitext(os.path.basename(src))[0]
    dst   = os.path.join(_AGENTS_DIR, os.path.basename(src))

    _reject_documents_logs(src)
    shutil.copyfile(src, dst)
    print(f'  copied {label} -> {dst}')

    # bootout is best-effort: the job may not be loaded yet.
    subprocess.run(['launchctl', 'bootout', f'gui/{_UID}/{label}'],
                   capture_output=True)
    r = subprocess.run(['launchctl', 'bootstrap', f'gui/{_UID}', dst],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f'  bootstrap {label} failed: {r.stderr.strip() or r.stdout.strip()}')
    else:
        print(f'  bootstrapped {label}')
    return label


def main():
    os.makedirs(_LOG_DIR, exist_ok=True)
    print(f'Log directory ready: {_LOG_DIR}')

    plists = sorted(
        os.path.join(_SRC_DIR, f)
        for f in os.listdir(_SRC_DIR) if f.endswith('.plist')
    )
    if not plists:
        sys.exit(f'No plists found in {_SRC_DIR}')

    print(f'Installing {len(plists)} launchd job(s):')
    for src in plists:
        install_one(src)


if __name__ == '__main__':
    main()
