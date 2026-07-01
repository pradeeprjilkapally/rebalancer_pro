#!/usr/bin/env python3
"""
Pre-push guard: every feature branch must map to a documented task in task.md.

Policy (CLAUDE.md/AGENTS.md): EVERY repo change — code, config, or infra — is
tracked in task.md before it ships. This guard enforces the "entry at the start"
rule at push time: the branch name must carry a task id (NN-DDMMYY) that already
exists as a `Task: <id>` entry in task.md. Small fix/re-land commits on the branch
inherit the branch's task id, so they don't each need their own.

Exit 0 = tracked (or nothing to enforce); exit 1 = blocked with guidance.
"""
import os
import re
import subprocess
import sys

_TASK_ID_RE = re.compile(r'(\d{2}-\d{6})')


def current_branch() -> str:
    return subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def documented_task_ids(task_md_text: str) -> set[str]:
    """Task ids that have a real entry (a `Task: NN-DDMMYY` line) in task.md."""
    return set(re.findall(r'^Task:\s+(\d{2}-\d{6})', task_md_text, re.MULTILINE))


def branch_task_id(branch: str) -> str | None:
    m = _TASK_ID_RE.search(branch)
    return m.group(1) if m else None


def check(branch: str, task_md_text: str) -> tuple[bool, str]:
    """Return (ok, message). Protected branches are exempt (direct pushes shouldn't happen)."""
    if branch in ('master', 'main', 'HEAD'):
        return True, f'[task-guard] {branch}: protected branch, skipped.'
    tid = branch_task_id(branch)
    if not tid:
        return False, (f"[task-guard] ❌ branch '{branch}' has no task id (NN-DDMMYY).\n"
                       "    Every change must be tracked: name the branch "
                       "feature/<NN-DDMMYY>-<slug> and add the task.md entry first.")
    if tid not in documented_task_ids(task_md_text):
        return False, (f"[task-guard] ❌ task {tid} (from branch '{branch}') is not in task.md.\n"
                       "    Add its entry (Date/Status/Task/Goal/Constraints/Inputs/Outputs/"
                       "Done-check/Out-of-scope) before pushing.")
    return True, f'[task-guard] ✅ branch maps to documented task {tid}.'


def main() -> int:
    repo = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                          capture_output=True, text=True).stdout.strip()
    try:
        task_md = open(os.path.join(repo, 'task.md')).read()
    except OSError:
        print('[task-guard] ❌ task.md not found at repo root.')
        return 1
    ok, msg = check(current_branch(), task_md)
    print(msg)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
