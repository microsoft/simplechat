# test_workflow_repeat_limits.py
"""
Functional tests for the independent administrator Repeat batch ceiling.
Version: 0.261.120
Implemented in: 0.261.120

Validates explicit settings without changing the existing For-each policy.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated repository path setup.
from functions_workflow_limits import (
    WORKFLOW_REPEAT_ITERATIONS_DEFAULT, WORKFLOW_REPEAT_ITERATIONS_MAX,
    WorkflowLoopLimitError, get_workflow_max_loop_items, get_workflow_max_repeat_iterations,
    validate_workflow_max_repeat_iterations,
)


def test_repeat_and_for_each_defaults_are_independent():
    assert WORKFLOW_REPEAT_ITERATIONS_DEFAULT == 25
    assert WORKFLOW_REPEAT_ITERATIONS_MAX == 1000
    assert get_workflow_max_repeat_iterations({}) == 25
    assert get_workflow_max_loop_items({}) == 500
    settings = {"workflow_max_loop_items": 5000, "workflow_max_repeat_iterations": 7}
    assert get_workflow_max_repeat_iterations(settings) == 7
    assert get_workflow_max_loop_items(settings) == 5000


@pytest.mark.parametrize("value,expected", [(1, 1), (25, 25), (1000, 1000), ("1", 1), (" 25 ", 25), ("1000", 1000)])
def test_administrator_repeat_limit_accepts_whole_numbers(value, expected):
    assert validate_workflow_max_repeat_iterations(value) == expected


@pytest.mark.parametrize("value", [None, 0, -1, 1001, 5000, True, False, 25.0, "", "25.0", "1e2", "twenty", [], {}, "\uff11\uff12"])
def test_invalid_administrator_repeat_limit_is_not_clamped_or_defaulted(value):
    with pytest.raises(WorkflowLoopLimitError) as failure:
        get_workflow_max_repeat_iterations({"workflow_max_repeat_iterations": value})
    assert failure.value.code == "workflow_repeat_limit_invalid"
    assert "1,000" in failure.value.public_message


@pytest.mark.parametrize("settings", [[], "unavailable", 25])
def test_unavailable_settings_are_not_replaced_by_successful_defaults(settings):
    with pytest.raises(WorkflowLoopLimitError) as failure:
        get_workflow_max_repeat_iterations(settings)
    assert failure.value.code == "workflow_repeat_limit_unavailable"
