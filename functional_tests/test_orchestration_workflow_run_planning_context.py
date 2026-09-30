#!/usr/bin/env python3
# test_orchestration_workflow_run_planning_context.py
"""
Functional test for the workflow planning context when chat orchestration may start saved workflows.
Version: 0.261.211
Implemented in: 0.261.211

This test ensures that the ``workflow_run`` gates read ``enable_chat_orchestration_workflow_runs``
as a real boolean only, independently of the workflow proposals setting, and that they check the
capability allowlist for ``workflow_run`` itself, personal workflows and the WorkflowUser rule.
"""

import importlib
from itertools import product

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_support.versioning import assert_app_version_at_least


OWNER = "owner"
PROPOSALS = "enable_chat_orchestration_workflows"
RUNS = "enable_chat_orchestration_workflow_runs"
RUN_SETTINGS = {
    "enable_chat_orchestration": True,
    RUNS: True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "chat_orchestration_enabled_capabilities": [],
}


@pytest.fixture
def wf(modules):
    return importlib.import_module("functions_orchestration_workflow_context")


def test_version_is_at_least_the_workflow_runs_release():
    assert_app_version_at_least("0.261.211")


@pytest.mark.parametrize("value", [None, False, "true", "True", 1, "on", [True]])
def test_only_a_real_true_configures_workflow_runs(wf, value):
    settings = {**RUN_SETTINGS}
    if value is None:
        settings.pop(RUNS)
    else:
        settings[RUNS] = value
    configured = wf.workflow_runs_configured(settings)
    reason = wf.workflow_run_gate(settings, ["User"])
    assert configured is False
    assert reason == wf.WORKFLOW_RUNS_REASON_DISABLED == "workflow_runs_disabled"


def test_workflow_runs_need_chat_orchestration(wf):
    settings = {**RUN_SETTINGS, "enable_chat_orchestration": False}
    configured = wf.workflow_runs_configured(settings)
    reason = wf.workflow_run_gate(settings, ["User"])
    assert configured is False
    assert reason == "workflow_runs_disabled"
    assert wf.workflow_runs_configured(None) is False


def test_the_two_workflow_settings_are_independent(wf):
    for proposals, runs in product((None, False, True), repeat=2):
        settings = {"enable_chat_orchestration": True, "allow_user_workflows": True}
        if proposals is not None:
            settings[PROPOSALS] = proposals
        if runs is not None:
            settings[RUNS] = runs
        proposals_configured = wf.workflow_proposals_configured(settings)
        runs_configured = wf.workflow_runs_configured(settings)
        either = wf.workflow_planning_configured(settings)
        assert proposals_configured is (proposals is True), (proposals, runs)
        assert runs_configured is (runs is True), (proposals, runs)
        assert either is (proposals is True or runs is True), (proposals, runs)
        # The proposals gate keeps its exact Phase 4 meaning whatever the runs setting says.
        proposal_reason = wf.workflow_planning_gate(settings, ["User"])
        assert proposal_reason == (None if proposals is True else "workflow_proposals_disabled"), (proposals, runs)


def test_workflow_runs_need_personal_workflows(wf):
    settings = {**RUN_SETTINGS, "allow_user_workflows": False}
    settings_reason = wf.workflow_run_settings_gate(settings)
    reason = wf.workflow_run_gate(settings, ["WorkflowUser"])
    assert settings_reason == reason == "workflow_runs_disabled"


@pytest.mark.parametrize("allowlist, admitted", [
    ([], True),
    (["workflow_run"], True),
    (["compose", "workflow_run"], True),
    (["workflow_propose"], False),
    (["compose", "web_search"], False),
    ("workflow_run", False),
    ([""], False),
])
def test_the_capability_allowlist_is_checked_for_workflow_run_itself(wf, allowlist, admitted):
    settings = {**RUN_SETTINGS, PROPOSALS: True, "chat_orchestration_enabled_capabilities": allowlist}
    settings_reason = wf.workflow_run_settings_gate(settings)
    reason = wf.workflow_run_gate(settings, ["User"])
    expected = None if admitted else "workflow_runs_disabled"
    assert settings_reason == reason == expected


def test_the_proposal_allowlist_entry_does_not_admit_runs_and_the_reverse(wf):
    both = {**RUN_SETTINGS, PROPOSALS: True}
    runs_only = {**both, "chat_orchestration_enabled_capabilities": ["workflow_run"]}
    proposals_only = {**both, "chat_orchestration_enabled_capabilities": ["workflow_propose"]}
    run_reasons = (wf.workflow_run_gate(runs_only, []), wf.workflow_run_gate(proposals_only, []))
    proposal_reasons = (wf.workflow_planning_gate(runs_only, []), wf.workflow_planning_gate(proposals_only, []))
    assert run_reasons == (None, "workflow_runs_disabled")
    assert proposal_reasons == ("workflow_proposals_disabled", None)


@pytest.mark.parametrize("roles, expected", [
    ([], "workflow_role_required"),
    (["User"], "workflow_role_required"),
    (None, "workflow_role_required"),
    ("WorkflowUser", "workflow_role_required"),
    (["WorkflowUser"], None),
    (("User", "workflowuser"), None),
])
def test_the_workflow_user_rule_is_checked_after_the_settings(wf, roles, expected):
    settings = {**RUN_SETTINGS, "require_member_of_workflow_user": True}
    settings_reason = wf.workflow_run_settings_gate(settings)
    reason = wf.workflow_run_gate(settings, roles)
    # The settings part never looks at roles, so linking an already started run needs none.
    assert settings_reason is None
    assert reason == expected


def test_no_role_rule_means_any_signed_in_user(wf):
    reason = wf.workflow_run_gate(RUN_SETTINGS, [])
    assert reason is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
