"""The pre-push task-tracking guard: a branch must map to a documented task.md entry."""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    'check_task_tracked',
    os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'check_task_tracked.py'),
)
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)

_TASK_MD = "Date: 2026-07-01\nStatus: in progress\nTask:         01-010726\nGoal: x\n"


def test_documented_task_ids_parses_entries():
    assert guard.documented_task_ids(_TASK_MD) == {'01-010726'}
    assert guard.documented_task_ids('no tasks here') == set()

def test_branch_task_id_extracts_or_none():
    assert guard.branch_task_id('feature/01-010726-task-tracking') == '01-010726'
    assert guard.branch_task_id('feature/no-id-here') is None

def test_check_passes_for_documented_branch():
    ok, msg = guard.check('feature/01-010726-task-tracking', _TASK_MD)
    assert ok is True and '01-010726' in msg

def test_check_blocks_branch_without_task_id():
    ok, msg = guard.check('feature/random-thing', _TASK_MD)
    assert ok is False and 'no task id' in msg

def test_check_blocks_undocumented_task_id():
    ok, msg = guard.check('feature/09-090909-ghost', _TASK_MD)
    assert ok is False and 'not in task.md' in msg

def test_master_is_exempt():
    ok, _ = guard.check('master', _TASK_MD)
    assert ok is True
