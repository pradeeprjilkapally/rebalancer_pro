#!/usr/bin/env python3
"""
PR-flow guard — enforce the deploy model's branch flow on every pull request.

  feature/* (also fix/ hotfix/ docs/ chore/)  ->  develop   (never straight to master)
  develop                                      ->  master
  anything else                                ->  allowed (no rule; e.g. release/*)

Runs in CI on pull_request with the head/base branch names. Exit 1 on a violation,
so a feature branch physically cannot merge to master without going through develop.
"""
import sys

_FEATURE_PREFIXES = ('feature/', 'fix/', 'hotfix/', 'docs/', 'chore/')


def check(head: str, base: str) -> tuple[bool, str]:
    if head == 'develop':
        if base == 'master':
            return True, 'develop → master ✓'
        return False, f"develop must PR to master, not '{base}'."
    if head.startswith(_FEATURE_PREFIXES):
        if base == 'develop':
            return True, f'{head} → develop ✓'
        return False, (f"'{head}' must PR to develop, not '{base}' — feature work never "
                       "goes straight to master (deploy model: feature → develop → master).")
    return True, f'{head} → {base} (no flow rule; allowed)'


def main() -> int:
    if len(sys.argv) != 3:
        print('usage: check_pr_flow.py <head_ref> <base_ref>')
        return 2
    ok, msg = check(sys.argv[1], sys.argv[2])
    print(('[pr-flow] ✅ ' if ok else '[pr-flow] ❌ ') + msg)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
