"""PR-flow guard: feature/* → develop → master, enforced on PRs."""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    'check_pr_flow', os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'check_pr_flow.py'))
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)


def test_feature_to_develop_ok():
    assert guard.check('feature/05-020726-x', 'develop')[0] is True

def test_feature_to_master_blocked():
    ok, msg = guard.check('feature/05-020726-x', 'master')
    assert ok is False and 'develop' in msg

def test_fix_to_master_blocked():
    assert guard.check('fix/urgent', 'master')[0] is False

def test_develop_to_master_ok():
    assert guard.check('develop', 'master')[0] is True

def test_develop_to_develop_blocked():
    assert guard.check('develop', 'develop')[0] is False

def test_unknown_head_allowed():
    # release/hotfix-style branches have no rule → not blocked
    assert guard.check('release/1.2.0', 'master')[0] is True
