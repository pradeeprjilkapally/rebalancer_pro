"""Pre-push merge-guard: block pushing to a branch whose PR is already merged."""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    'mg', os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'check_branch_not_merged.py'))
mg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mg)


def test_merged_pr_detected():
    assert mg.merged_pr_number('[{"number": 22}]') == 22

def test_no_merged_pr():
    assert mg.merged_pr_number('[]') is None
    assert mg.merged_pr_number('') is None

def test_bad_json_fails_open():
    assert mg.merged_pr_number('not json') is None       # → None → push allowed

def test_first_pr_wins():
    assert mg.merged_pr_number('[{"number": 22}, {"number": 9}]') == 22


def test_gh_query_targets_the_fork(monkeypatch):
    # regression: the gh call MUST pass --repo <fork>, else it queries origin (upstream)
    calls = []
    class _R:
        def __init__(self, out='', rc=0): self.stdout, self.returncode = out, rc
    def fake_run(cmd, **k):
        calls.append(cmd)
        if cmd[:3] == ['git', 'rev-parse', '--abbrev-ref']:
            return _R('feature/09-020726-x')
        return _R('[]')
    monkeypatch.setattr(mg.subprocess, 'run', fake_run)
    mg.main()
    gh_call = next(c for c in calls if c and c[0] == 'gh')
    assert '--repo' in gh_call and mg._GH_REPO in gh_call
