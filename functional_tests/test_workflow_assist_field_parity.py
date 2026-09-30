#!/usr/bin/env python3
# test_workflow_assist_field_parity.py
"""
Functional test for the parity of the AI workflow assistant's field lists with the V2 editor.
Version: 0.261.206
Implemented in: 0.261.206

The assistant (functions_workflow_assist_editor.py) keeps its own copy of the lists that decide
what an assist candidate may change, because the server is the source of truth for what it
returns. The V2 editor applies the candidate with ``applyAssist``, which checks the same lists in
application/v2_ui/src/components/workflows/WorkflowAuthoringHistory.tsx.

This test ensures that the two copies never drift: WORKFLOW_AUTHORED_FIELDS,
ASSIST_FORBIDDEN_FIELDS and ASSIST_FORBIDDEN_TASK_FIELDS match in content and order, and so do
the editor constants the server's port of ``normalizeWorkflowDefinition`` and ``workflowForSave``
depends on (alert modes and priorities, trigger types, schedule units, frequencies and days,
output kinds, input outputs, reference scopes, task runner types, the alias pattern and the
read-only reasons). It also pins the alert vocabulary the assistant's operations may use to the
editor's, and checks that every field the assistant refuses is one the editor refuses too.

The TypeScript is read as text, following test_workflow_run_as_fingerprint_parity.py.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "application" / "single_app"))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

import functions_workflow_assist_editor as editor  # noqa: E402
import functions_workflow_assist_operations as operations  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
AUTHORING_TSX = V2_SRC / "components" / "workflows" / "WorkflowAuthoringHistory.tsx"
ALERTS_TS = V2_SRC / "lib" / "workflowAlerts.ts"
SETTINGS_TS = V2_SRC / "lib" / "workflowSettings.ts"
EDITOR_TS = V2_SRC / "lib" / "workflowEditor.ts"
FLOW_TS = V2_SRC / "lib" / "workflowFlow.ts"


def _source(path):
    return path.read_text(encoding="utf-8")


def _strings(text):
    return re.findall(r"'([^']*)'", text)


def _frozen_list(source, name, spreads=None):
    """``export const NAME: readonly string[] = Object.freeze([...]);``, with ``...SPREAD`` expanded."""
    match = re.search(rf"export const {name}\b[^=]*=\s*Object\.freeze\(\[(.*?)\]\)", source, re.DOTALL)
    assert match, f"{name} was not found as a frozen list"
    values = []
    for token in re.findall(r"'[^']*'|\.\.\.[A-Z_]+", match.group(1)):
        if token.startswith("..."):
            spread = token[3:]
            assert spreads and spread in spreads, f"{name} spreads {spread}, which this test does not expand"
            values.extend(spreads[spread])
        else:
            values.append(token[1:-1])
    return values


def _const_list(source, name):
    """``export const NAME = [...] as const;``."""
    match = re.search(rf"export const {name}\s*=\s*\[(.*?)\]\s*as const;", source, re.DOTALL)
    assert match, f"{name} was not found as a const list"
    return _strings(match.group(1))


def _typed_list(source, name):
    """``export const NAME: Type[] = [...];``."""
    match = re.search(rf"export const {name}\s*:\s*\w+\[\]\s*=\s*\[(.*?)\];", source, re.DOTALL)
    assert match, f"{name} was not found as a typed list"
    return _strings(match.group(1))


def _string_set(source, name):
    """``export const NAME = new Set<string>([...]);``."""
    match = re.search(rf"export const {name}\s*=\s*new Set<\w+>\(\[(.*?)\]\);", source, re.DOTALL)
    assert match, f"{name} was not found as a set"
    return set(_strings(match.group(1)))


def _number(source, name):
    match = re.search(rf"export const {name}\s*=\s*(\d+);", source)
    assert match, f"{name} was not found as a number"
    return int(match.group(1))


def _alert_fields():
    return _const_list(_source(ALERTS_TS), "WORKFLOW_ALERT_FIELDS")


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.206")


# ---------------------------------------------------------------------------------------------
# The lists applyAssist checks
# ---------------------------------------------------------------------------------------------

def test_authored_fields_match_the_editor_in_order():
    typescript = _frozen_list(
        _source(AUTHORING_TSX), "WORKFLOW_AUTHORED_FIELDS", spreads={"WORKFLOW_ALERT_FIELDS": _alert_fields()},
    )
    assert list(editor.WORKFLOW_AUTHORED_FIELDS) == typescript, (
        "WORKFLOW_AUTHORED_FIELDS drifted from WorkflowAuthoringHistory.tsx: "
        f"server {list(editor.WORKFLOW_AUTHORED_FIELDS)}, editor {typescript}"
    )
    assert "file_sync" in typescript and set(_alert_fields()) <= set(typescript)


def test_forbidden_fields_match_the_editor_in_order():
    typescript = _frozen_list(_source(AUTHORING_TSX), "ASSIST_FORBIDDEN_FIELDS")
    assert list(editor.ASSIST_FORBIDDEN_FIELDS) == typescript, (
        "ASSIST_FORBIDDEN_FIELDS drifted from WorkflowAuthoringHistory.tsx: "
        f"server {list(editor.ASSIST_FORBIDDEN_FIELDS)}, editor {typescript}"
    )
    for field in ("is_enabled", "m365_run_as_user_id", "definition_version", "id", "user_id", "group_id",
                  "url_access_enabled"):
        assert field in typescript, f"the roadmap's never-allowed field {field} is missing from the editor list"


def test_forbidden_task_fields_match_the_editor_in_order():
    typescript = _frozen_list(_source(AUTHORING_TSX), "ASSIST_FORBIDDEN_TASK_FIELDS")
    assert list(editor.ASSIST_FORBIDDEN_TASK_FIELDS) == typescript == ["approval"], typescript


def test_the_violation_messages_match_the_editor():
    source = _source(AUTHORING_TSX)
    match = re.search(r"export function workflowAssistViolation\(.*?\n}\n", source, re.DOTALL)
    assert match, "workflowAssistViolation was not found"
    body = match.group(0)
    for message in (
        "'The assist candidate is not a workflow.'",
        "`AI assist cannot change ${field}. Change it yourself if it needs to change.`",
        "`AI assist cannot change ${field}, which the workflow editor does not author.`",
        "'AI assist cannot add, change, or remove a task approval. Change approvals yourself.'",
    ):
        assert message in body, f"workflowAssistViolation no longer returns {message}; update the server's port"
    assert "return workflowIdentityChange(current, candidate);" in body, (
        "workflowAssistViolation no longer ends with the identity check the server's stricter flow rule covers"
    )


# ---------------------------------------------------------------------------------------------
# The editor constants the server's port depends on
# ---------------------------------------------------------------------------------------------

CONST_LISTS = [
    (ALERTS_TS, "WORKFLOW_ALERT_FIELDS", "WORKFLOW_ALERT_FIELDS"),
    (ALERTS_TS, "WORKFLOW_ALERT_MODES", "WORKFLOW_ALERT_MODES"),
    (ALERTS_TS, "WORKFLOW_ALERT_PRIORITIES", "WORKFLOW_ALERT_PRIORITIES"),
    (SETTINGS_TS, "WORKFLOW_TRIGGER_TYPES", "WORKFLOW_TRIGGER_TYPES"),
    (SETTINGS_TS, "WORKFLOW_SCHEDULE_UNITS", "WORKFLOW_SCHEDULE_UNITS"),
    (SETTINGS_TS, "WORKFLOW_SCHEDULE_FREQUENCIES", "WORKFLOW_SCHEDULE_FREQUENCIES"),
    (SETTINGS_TS, "WORKFLOW_SCHEDULE_DAYS", "WORKFLOW_SCHEDULE_DAYS"),
]


@pytest.mark.parametrize(
    "path, typescript_name, python_name", CONST_LISTS, ids=[entry[1] for entry in CONST_LISTS],
)
def test_editor_const_lists_match(path, typescript_name, python_name):
    typescript = _const_list(_source(path), typescript_name)
    server = list(getattr(editor, python_name))
    assert server == typescript, f"{python_name} drifted from {path.name}: server {server}, editor {typescript}"


TYPED_LISTS = [
    (EDITOR_TS, "WORKFLOW_OUTPUT_KINDS", "WORKFLOW_OUTPUT_KINDS"),
    (EDITOR_TS, "WORKFLOW_INPUT_OUTPUTS", "WORKFLOW_INPUT_OUTPUTS"),
    (FLOW_TS, "FLOW_OUTPUT_KINDS", "FLOW_OUTPUT_KINDS"),
]


@pytest.mark.parametrize(
    "path, typescript_name, python_name", TYPED_LISTS, ids=[entry[1] for entry in TYPED_LISTS],
)
def test_editor_typed_lists_match(path, typescript_name, python_name):
    typescript = _typed_list(_source(path), typescript_name)
    server = list(getattr(editor, python_name))
    assert server == typescript, f"{python_name} drifted from {path.name}: server {server}, editor {typescript}"


def test_reference_scopes_and_runner_types_match_normalization():
    source = _source(EDITOR_TS)
    scopes = re.search(
        r"scope_type:\s*\[([^\]]*)\]\.includes\(String\(entry\.scope_type\)\)", source,
    )
    assert scopes, "normalizeWorkflowDefinition no longer lists reference scopes inline; update this test"
    assert list(editor.WORKFLOW_REFERENCE_SCOPES) == _strings(scopes.group(1))
    runner = re.search(
        r"function normalizeRunner\(.*?const type = \[([^\]]*)\]\.includes\(String\(value\.type\)\)", source, re.DOTALL,
    )
    assert runner, "normalizeRunner no longer lists runner types inline; update this test"
    assert set(editor.WORKFLOW_TASK_RUNNER_TYPES) == set(_strings(runner.group(1)))
    trigger = re.search(
        r"export function normalizeWorkflowDefinition\(.*?const trigger = \[([^\]]*)\]\.includes", source, re.DOTALL,
    )
    assert trigger, "normalizeWorkflowDefinition no longer lists trigger types inline; update this test"
    assert list(editor.WORKFLOW_TRIGGER_TYPES) == _strings(trigger.group(1))


def test_alias_pattern_matches_the_flow_pattern():
    match = re.search(r"export const FLOW_ALIAS_PATTERN\s*=\s*/(.*?)/;", _source(FLOW_TS))
    assert match, "FLOW_ALIAS_PATTERN was not found"
    assert f"^{editor.WORKFLOW_ALIAS_PATTERN.pattern}$" == match.group(1)
    assert "export const WORKFLOW_ALIAS_PATTERN = FLOW_ALIAS_PATTERN;" in _source(EDITOR_TS)


def test_read_only_reasons_match_word_for_word():
    source = _source(EDITOR_TS)
    schedule = re.search(r"export const WORKFLOW_UNSUPPORTED_SCHEDULE_REASON\s*=\s*'([^']*)';", source)
    assert schedule, "WORKFLOW_UNSUPPORTED_SCHEDULE_REASON was not found"
    assert editor.WORKFLOW_UNSUPPORTED_SCHEDULE_REASON == schedule.group(1)
    tasks = re.search(r"\?\s*'(This workflow contains task configuration or bindings[^']*)'", source)
    assert tasks, "the unsupported task configuration reason was not found"
    assert editor.WORKFLOW_UNSUPPORTED_TASKS_REASON == tasks.group(1)


# ---------------------------------------------------------------------------------------------
# The vocabulary the assistant's operations may use
# ---------------------------------------------------------------------------------------------

def test_alert_operation_vocabulary_is_the_editors():
    source = _source(ALERTS_TS)
    assert list(operations.ASSIST_ALERT_SEVERITIES) == _const_list(source, "WORKFLOW_ALERT_SEVERITIES")
    assert list(operations.ASSIST_ALERT_DELIVERIES) == _const_list(source, "WORKFLOW_ALERT_DELIVERIES")
    assert list(operations.ASSIST_ALERT_SCOPES) == _const_list(source, "WORKFLOW_ALERT_SCOPE_TYPES")
    assert list(operations.ASSIST_ALERT_TEXT_MODES) == _const_list(source, "WORKFLOW_ALERT_TEXT_MATCH_MODES")
    assert set(operations.ASSIST_ALERT_RUN_STATUSES) == set(_const_list(source, "WORKFLOW_ALERT_RUN_STATUSES"))
    assert set(operations.ASSIST_ALERT_TASK_STATUSES) == set(_const_list(source, "WORKFLOW_ALERT_TASK_STATUSES"))
    # Every condition but File Sync's, which waits for Phase 4's personal File Sync authoring.
    conditions = _const_list(source, "WORKFLOW_ALERT_CONDITION_TYPES")
    assert set(conditions) - set(operations.ASSIST_ALERT_CONDITIONS) == {"file_sync"}
    assert set(operations.ASSIST_ALERT_CONDITIONS) <= set(conditions)
    scopeless = _string_set(source, "WORKFLOW_ALERT_SCOPELESS_CONDITIONS")
    assert set(operations.ASSIST_SCOPELESS_CONDITIONS) == scopeless & set(operations.ASSIST_ALERT_CONDITIONS)
    # An every-run alert names a real priority; 'none' is what "off" stores.
    priorities = _const_list(source, "WORKFLOW_ALERT_PRIORITIES")
    assert set(operations.ASSIST_ALERT_PRIORITIES) == set(priorities) - {"none"}


def test_operation_limits_stay_within_the_editors():
    alerts = _source(ALERTS_TS)
    assert operations.ASSIST_ALERT_MAX_RULES == _number(alerts, "WORKFLOW_ALERT_MAX_RULES")
    assert operations.ASSIST_ALERT_NAME_MAX_LENGTH == _number(alerts, "WORKFLOW_ALERT_RULE_NAME_MAX_LENGTH")
    assert operations.ASSIST_ALERT_MAX_VALUES == _number(alerts, "WORKFLOW_ALERT_MAX_TEXT_VALUES")
    assert operations.ASSIST_ALERT_VALUE_MAX_LENGTH == _number(alerts, "WORKFLOW_ALERT_TEXT_VALUE_MAX_LENGTH")
    assert operations.ASSIST_ALERT_REGEX_MAX_LENGTH == _number(alerts, "WORKFLOW_ALERT_REGEX_MAX_LENGTH")
    assert operations.ASSIST_ALERT_PROMPT_MAX_LENGTH == _number(alerts, "WORKFLOW_ALERT_EVALUATION_PROMPT_MAX_LENGTH")
    assert operations.ASSIST_TASK_INSTRUCTIONS_MAX_LENGTH == _number(_source(EDITOR_TS), "WORKFLOW_TASK_INSTRUCTIONS_LIMIT")


def test_every_field_the_server_refuses_the_editor_refuses():
    """The server's violation check and the editor's agree on which top-level fields are off limits."""
    typescript_authored = set(_frozen_list(
        _source(AUTHORING_TSX), "WORKFLOW_AUTHORED_FIELDS", spreads={"WORKFLOW_ALERT_FIELDS": _alert_fields()},
    ))
    typescript_forbidden = set(_frozen_list(_source(AUTHORING_TSX), "ASSIST_FORBIDDEN_FIELDS"))
    draft = {"name": "Before", "tasks": []}
    for field in sorted(typescript_forbidden | {"created_at", "modified_at", "active_run_id", "shared_with"}):
        candidate = {**draft, field: "changed"}
        message = editor.workflow_assist_violation(draft, candidate)
        assert message, f"the server let an assist change {field}"
        if field in typescript_forbidden:
            assert message == f"AI assist cannot change {field}. Change it yourself if it needs to change."
        else:
            assert field not in typescript_authored
            assert message == f"AI assist cannot change {field}, which the workflow editor does not author."


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
