# test_workflow_alert_client_parity.py
#!/usr/bin/env python3
"""
Functional test for the seam between the V2 alert editor and the server's alert normalizer.
Version: 0.261.144
Implemented in: 0.261.144

This test ensures that the V2 editor allows an alert save exactly when the server accepts it, and
that it shows the server's own reviewed message for the first problem.

* The client half is the production TypeScript. ``lib/workflowAlerts.ts`` and
  ``lib/workflowEditor.ts`` run under Node, using ``workflowAlertErrors``, the editor's
  ``workflowValidationErrors`` and ``workflowForSave``.
* The server half is the real ``normalize_workflow_alert_settings`` from
  ``functions_workflow_alerts.py``, loaded with the real definitions and alert-safety modules.
  Only the logger is stubbed.
* Every case asserts both directions: the client finds no problem if and only if the server
  accepts. When the server refuses, the client's first message is the server's message. Cases
  cover each condition type, every refusal, Python-exact whitespace and code-point limits, and the
  stored-record paths.
* The single documented divergence is regex syntax that Python cannot compile (C12). The client
  does not compile patterns, because Python and JavaScript regular expressions differ, so the
  server's reviewed 400 reports it. It is pinned as the only case where the client accepts and
  the server refuses.
* Also pinned: the resolved view (``workflowAlertConfig``) against
  ``resolve_workflow_alert_config``; the described rule names against ``describe_alert_condition``;
  and the editor path, covering untouched resends, priority-only records, a removed task, and
  unknown rule fields.
"""

import copy
import importlib.util
import json
import subprocess
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TASK_IDS = ["collect", "summarize"]
_MISSING = object()


@contextmanager
def _modules(names):
    originals = {name: sys.modules.get(name, _MISSING) for name in names}
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _load_alerts():
    """The real alert normalizer, with the real pure modules it imports and a silent logger."""
    names = ("functions_appinsights", "functions_workflow_alert_safety", "functions_workflow_definitions",
             "functions_workflow_alerts")
    with _modules(names):
        logger = types.ModuleType("functions_appinsights")
        logger.log_event = lambda *args, **kwargs: None
        sys.modules["functions_appinsights"] = logger
        loaded = {}
        for name in names[1:]:
            spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded[name] = module
    return loaded["functions_workflow_alerts"], loaded["functions_workflow_definitions"]


ALERTS, DEFINITIONS = _load_alerts()


def rule(condition=None, **fields):
    return {"name": "Rule", "condition": condition or {"type": "no_output"}, **fields}


VALID = rule({"type": "run_status", "statuses": ["failed"]}, name="Run failed")
EMOJI = "\U0001F514"  # One code point in Python, two UTF-16 units in JavaScript.


def rules_case(*rules, **fields):
    return {"alert_mode": "rules", "alert_rules": list(rules), **fields}


# name: (sent alert fields, existing record or None, task ids)
CASES = {
    # Accepted: one or more cases for every condition type and shape.
    "empty_payload": ({}, None, TASK_IDS),
    "off": ({"alert_mode": "off"}, None, TASK_IDS),
    "every_run_with_priority": ({"alert_mode": "every_run", "alert_priority": "high"}, None, TASK_IDS),
    "every_run_priority_from_existing": ({"alert_mode": "every_run"}, {"alert_priority": "low"}, TASK_IDS),
    "run_status_multiple": (rules_case(rule({"type": "run_status", "statuses": ["FAILED", " completed ", "failed"]})), None, TASK_IDS),
    "run_status_bare_string": (rules_case(rule({"type": "run_status", "statuses": "cancelled"})), None, TASK_IDS),
    "task_status_task_scope": (rules_case(rule({"type": "task_status", "statuses": ["succeeded"]},
                                               scope={"type": "task", "task_id": "collect"})), None, TASK_IDS),
    "text_match_any_task": (rules_case(rule({"type": "text_match", "mode": "contains_all", "values": [" a ", "", "a", "b"]},
                                            scope={"type": "any_task"})), None, TASK_IDS),
    "text_match_bare_value": (rules_case(rule({"type": "text_match", "values": "penalty"})), None, TASK_IDS),
    "text_match_regex": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": r"expires in \d+ days"})), None, TASK_IDS),
    "file_sync_outcome": (rules_case(rule({"type": "file_sync", "outcome": "Sync_Failed"})), None, TASK_IDS),
    "no_output": (rules_case(rule({"type": "no_output"})), None, TASK_IDS),
    "model_evaluation": (rules_case(rule({"type": "model_evaluation", "prompt": "Any certificate expires soon."}),
                                    alert_evaluation={"on_error": "alert"}), None, TASK_IDS),
    "agent_signal_bad_min_severity_is_silent": (rules_case(rule({"type": "agent_signal", "min_severity": "urgent"})), None, TASK_IDS),
    "off_keeps_valid_rules": ({"alert_mode": "off", "alert_rules": [VALID]}, None, TASK_IDS),
    "rules_null_is_empty": ({"alert_rules": None}, None, TASK_IDS),
    "rules_without_mode": ({"alert_rules": [VALID]}, None, TASK_IDS),
    "priority_only_new_record_materializes": ({"alert_priority": "medium"}, None, TASK_IDS),
    "priority_only_resend": ({"alert_priority": "high"}, {"alert_priority": "high"}, TASK_IDS),
    "stored_rules_not_sent_skip_task_check": ({}, {"alert_mode": "rules", "alert_rules": [
        rule(scope={"type": "task", "task_id": "removed"})]}, TASK_IDS),
    "twenty_rules": (rules_case(*[copy.deepcopy(VALID) for _ in range(20)]), None, TASK_IDS),
    "limits_at_maximum": (rules_case(
        rule({"type": "text_match", "values": [f"v{index}" for index in range(24)] + ["x" * 400]}, name="n" * 120),
        rule({"type": "text_match", "mode": "regex", "pattern": "p" * 200}, name="regex"),
        rule({"type": "model_evaluation", "prompt": "q" * 2000}),
        rule({"type": "agent_signal", "signal_name": "s" * 120}),
    ), None, TASK_IDS),
    "name_120_astral": (rules_case(rule(name=EMOJI * 120)), None, TASK_IDS),
    "whitespace_delivery_defaults": (rules_case(rule(delivery="   ")), None, TASK_IDS),
    "scope_type_blank_defaults_to_final": (rules_case(rule(scope={"type": "  "})), None, TASK_IDS),
    "unknown_rule_fields_accepted": (rules_case(rule(category="failure", extra={"kept": True})), None, TASK_IDS),
    "enabled_string_is_accepted": (rules_case(rule(enabled="no")), None, TASK_IDS),
    "python_whitespace_stripped_from_mode": ({"alert_mode": "\x1crules\x85", "alert_rules": [VALID]}, None, TASK_IDS),
    "feff_is_not_regex_whitespace": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": "(a+)\ufeff+"})), None, TASK_IDS),

    # Refused: W1-W7.
    "W1_priority": ({"alert_priority": "urgent"}, None, TASK_IDS),
    "W1_stored_invalid_priority_resent": ({"alert_priority": "Urgent"}, {"alert_priority": "Urgent"}, TASK_IDS),
    "W2_mode": ({"alert_mode": "sometimes"}, None, TASK_IDS),
    "W2_feff_is_not_stripped": ({"alert_mode": "\ufeffrules", "alert_rules": [VALID]}, None, TASK_IDS),
    "W3_rules_without_rules": ({"alert_mode": "rules", "alert_rules": []}, None, TASK_IDS),
    "W3_rules_mode_only": ({"alert_mode": "rules"}, None, TASK_IDS),
    "W4_every_run_without_priority": ({"alert_mode": "every_run"}, None, TASK_IDS),
    "W5_on_error": ({"alert_evaluation": {"on_error": "retry"}}, None, TASK_IDS),
    "W5_stored_on_error_not_sent": ({}, {"alert_evaluation": {"on_error": "retry"}}, TASK_IDS),
    "W6_rules_not_a_list": ({"alert_rules": "rules"}, None, TASK_IDS),
    "W7_twenty_one_rules": (rules_case(*[copy.deepcopy(VALID) for _ in range(21)]), None, TASK_IDS),

    # Refused: R1-R4.
    "R1_rule_not_an_object": (rules_case(VALID, "not a rule"), None, TASK_IDS),
    "R2_name_too_long": (rules_case(VALID, rule(name="n" * 121)), None, TASK_IDS),
    "R2_name_121_astral": (rules_case(rule(name=EMOJI * 121)), None, TASK_IDS),
    "R2_described_name_too_long": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": "p" * 150}, name="")), None, TASK_IDS),
    "R3_delivery": (rules_case(rule(delivery="email")), None, TASK_IDS),
    "R4_severity": (rules_case(rule(severity="urgent")), None, TASK_IDS),
    "R4_whitespace_severity": (rules_case(rule(severity="   ")), None, TASK_IDS),
    "R4_stored_rule_not_sent": ({}, {"alert_mode": "rules", "alert_rules": [rule(severity="urgent")]}, TASK_IDS),

    # Refused: S1-S3.
    "S1_scope_type": (rules_case(rule(scope={"type": "everything"})), None, TASK_IDS),
    "S2_scope_task_missing": (rules_case(rule(scope={"type": "task"})), None, TASK_IDS),
    "S3_scope_task_removed": (rules_case(VALID, rule(scope={"type": "task", "task_id": "removed"})), None, TASK_IDS),

    # Refused: C1-C20 (C12 is the documented divergence below).
    "C1_condition_type": (rules_case(rule({"type": "sometimes"})), None, TASK_IDS),
    "C1_condition_missing": (rules_case({"name": "No condition"}), None, TASK_IDS),
    "C2_run_statuses_not_a_list": (rules_case(rule({"type": "run_status"})), None, TASK_IDS),
    "C3_run_status_unsupported": (rules_case(rule({"type": "run_status", "statuses": ["exploded"]})), None, TASK_IDS),
    "C4_run_status_missing": (rules_case(rule({"type": "run_status", "statuses": [" ", ""]})), None, TASK_IDS),
    "C5_task_statuses_not_a_list": (rules_case(rule({"type": "task_status", "statuses": {"failed": True}})), None, TASK_IDS),
    "C6_task_status_unsupported": (rules_case(rule({"type": "task_status", "statuses": ["completed"]})), None, TASK_IDS),
    "C7_task_status_missing": (rules_case(rule({"type": "task_status", "statuses": []})), None, TASK_IDS),
    "C8_text_match_mode": (rules_case(rule({"type": "text_match", "mode": "fuzzy", "values": ["x"]})), None, TASK_IDS),
    "C9_regex_missing": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": "  "})), None, TASK_IDS),
    "C10_regex_too_long": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": "p" * 201})), None, TASK_IDS),
    "C11_regex_nested_quantifier": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": "(a+)+"})), None, TASK_IDS),
    "C11_python_whitespace_between": (rules_case(rule({"type": "text_match", "mode": "regex", "pattern": "(a+)\x1c+"})), None, TASK_IDS),
    "C13_values_not_a_list": (rules_case(rule({"type": "text_match", "values": 7})), None, TASK_IDS),
    "C14_value_too_long": (rules_case(rule({"type": "text_match", "values": ["x" * 401]})), None, TASK_IDS),
    "C15_values_missing": (rules_case(rule({"type": "text_match", "values": ["", "   "]})), None, TASK_IDS),
    "C16_too_many_values": (rules_case(rule({"type": "text_match", "values": [f"v{index}" for index in range(26)]})), None, TASK_IDS),
    "C17_file_sync_outcome": (rules_case(rule({"type": "file_sync", "outcome": "maybe"})), None, TASK_IDS),
    "C18_model_prompt_missing": (rules_case(rule({"type": "model_evaluation", "prompt": " "})), None, TASK_IDS),
    "C19_model_prompt_too_long": (rules_case(rule({"type": "model_evaluation", "prompt": "q" * 2001})), None, TASK_IDS),
    "C20_signal_name_too_long": (rules_case(rule({"type": "agent_signal", "signal_name": "s" * 121})), None, TASK_IDS),
}

# Patterns Python refuses to compile but the client cannot check: the single documented divergence.
REGEX_DIVERGENCE = {
    "C12_unclosed_group": "(unclosed",
    "C12_javascript_named_group": "(?<name>x)",
}

RESOLVE_RECORDS = {
    "empty": {},
    "priority_only": {"alert_priority": "high"},
    "unknown_priority": {"alert_priority": "urgent"},
    "every_run": {"alert_mode": "every_run", "alert_priority": "low", "alert_rules": []},
    "rules": {"alert_mode": "rules", "alert_rules": [VALID], "alert_evaluation": {"on_error": " ALERT "}},
    "rules_without_mode": {"alert_rules": [VALID, VALID]},
    "spaced_mode": {"alert_mode": " Off ", "alert_rules": [VALID]},
    "unknown_mode_with_priority": {"alert_mode": "sometimes", "alert_priority": "medium"},
    "rules_not_a_list": {"alert_mode": "rules", "alert_rules": "no"},
}

UNNAMED_CONDITIONS = [
    {"type": "run_status", "statuses": ["failed", "cancelled"]},
    {"type": "task_status", "statuses": ["succeeded"]},
    {"type": "text_match", "mode": "contains_any", "values": ["a", "b"]},
    {"type": "text_match", "mode": "not_contains", "values": ["c"]},
    {"type": "text_match", "mode": "regex", "pattern": r"\d+"},
    {"type": "file_sync", "outcome": "no_changes"},
    {"type": "no_output"},
    {"type": "model_evaluation", "prompt": "Anything risky."},
    {"type": "agent_signal"},
    {"type": "agent_signal", "signal_name": "expiring"},
]

NODE_SCRIPT = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const lib = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
const [alerts, editor] = await Promise.all([import(lib('workflowAlerts')), import(lib('workflowEditor'))]);
const output = { cases: {}, resolved: {}, described: [], editor: {} };
for (const [name, testCase] of Object.entries(input.cases)) {
    output.cases[name] = alerts.workflowAlertErrors(testCase.sent, testCase.existing, testCase.task_ids);
}
for (const [name, record] of Object.entries(input.resolved)) {
    const { legacy, ...config } = alerts.workflowAlertConfig(record);
    output.resolved[name] = { config, legacy, summary: alerts.workflowAlertSummary(record) };
}
output.described = input.described.map((condition) => alerts.describeWorkflowAlertCondition(condition));

// The editor path: normalize the loaded record, edit it the way the editor does, validate, and save.
const scopes = { personal: { type: 'personal' }, group: { type: 'group', groupId: input.group_id } };
const options = (scope) => ({
    definition_version: 2, supported_definition_versions: [1, 2, 3], can_manage: true, max_tasks: 20,
    agents: [], models: [], default_model: { label: 'Default model', valid: true },
    scope: scope.type === 'group' ? { type: 'group', id: scope.groupId } : { type: 'personal', id: 'owner-1' },
});
const edits = {
    none: (draft) => draft,
    every_run_high: (draft) => alerts.workflowAlertsEdited(draft, (settings) => ({ ...settings, alert_mode: 'every_run', alert_priority: 'high' })),
    remove_second_task: (draft) => ({ ...draft, tasks: draft.tasks.slice(0, 1) }),
    rename_first_rule: (draft) => alerts.workflowAlertsEdited(draft, (settings) => ({
        ...settings, alert_rules: settings.alert_rules.map((rule, index) => index === 0 ? { ...rule, name: 'Renamed' } : rule),
    })),
    change_condition_type: (draft) => alerts.workflowAlertsEdited(draft, (settings) => ({
        ...settings, alert_rules: settings.alert_rules.map((rule, index) => index === 0
            ? { ...rule, condition: alerts.workflowAlertConditionForType(rule.condition, 'file_sync') } : rule),
    })),
    add_default_rule: (draft) => alerts.workflowAlertsEdited(draft, (settings) => ({
        ...settings, alert_mode: 'rules', alert_rules: [...settings.alert_rules, alerts.newWorkflowAlertRule()],
    })),
};
for (const [name, testCase] of Object.entries(input.editor)) {
    const scope = scopes[testCase.scope];
    const original = editor.normalizeWorkflowDefinition(testCase.record, scope);
    const draft = edits[testCase.edit](structuredClone(original));
    const errors = editor.workflowValidationErrors(draft, options(scope), original);
    let payload = null;
    try {
        payload = editor.workflowForSave(draft, original, scope);
    } catch (cause) {
        payload = { save_error: String(cause) };
    }
    output.editor[name] = { errors, payload };
}
console.log(JSON.stringify(output));
"""


def _definition(**alert_fields):
    """A valid stored V2 definition with two tasks, carrying the given alert fields."""
    return {
        "id": "alerted", "name": "Alerted workflow", "description": "", "definition_version": 2,
        "definition_revision": "revision:alerted:1", "runner_type": "model", "model_endpoint_id": "", "model_id": "",
        "trigger_type": "manual", "schedule": {"unit": "minutes", "value": 15}, "is_enabled": True,
        "error_handling": {"strategy": "halt", "retry_count": 0}, "chat_capabilities_enabled": False,
        "reference_inputs": [],
        "tasks": [
            {"id": "collect", "type": "instructions", "name": "Collect", "instructions": "Collect.", "order": 1,
             "runner": {"type": "inherit"}},
            {"id": "summarize", "type": "instructions", "name": "Summarize", "instructions": "Summarize.", "order": 2,
             "runner": {"type": "inherit"}},
        ],
        **alert_fields,
    }


TASK_RULE = rule({"type": "text_match", "values": ["penalty"]}, name="Summary risk", id="risk",
                 scope={"type": "task", "task_id": "summarize"}, category="failure", x_extra={"kept": True})
EDITOR_CASES = {
    "untouched_rules_resent_exactly": ("personal", _definition(
        alert_mode="rules", alert_priority="none", alert_rules=[VALID, TASK_RULE], alert_evaluation={"on_error": "skip"},
    ), "none"),
    "priority_only_untouched": ("group", _definition(alert_priority="high"), "none"),
    "priority_only_edited": ("personal", _definition(alert_priority="high"), "every_run_high"),
    "removed_task_is_flagged": ("group", _definition(
        alert_mode="rules", alert_priority="none", alert_rules=[VALID, TASK_RULE],
    ), "remove_second_task"),
    "rule_fields_survive_an_edit": ("personal", _definition(
        alert_mode="rules", alert_priority="none", alert_rules=[TASK_RULE],
    ), "rename_first_rule"),
    "condition_type_change_keeps_unknown_keys": ("group", _definition(
        alert_mode="rules", alert_priority="none",
        alert_rules=[rule({"type": "text_match", "values": ["a"], "x_condition": 1}, id="c")],
    ), "change_condition_type"),
    "new_rule_on_a_new_mode": ("personal", _definition(), "add_default_rule"),
}


def _server(sent, existing, task_ids):
    """(accepted, message) from the real normalizer; any other exception fails the test."""
    try:
        ALERTS.normalize_workflow_alert_settings(copy.deepcopy(sent), existing_workflow=copy.deepcopy(existing),
                                                 task_ids=list(task_ids))
    except DEFINITIONS.WorkflowPublicValidationError as exc:
        return False, exc.public_message
    return True, ""


@pytest.fixture(scope="module")
def client():
    cases = {name: {"sent": sent, "existing": existing, "task_ids": task_ids}
             for name, (sent, existing, task_ids) in CASES.items()}
    for name, pattern in REGEX_DIVERGENCE.items():
        cases[name] = {"sent": rules_case(rule({"type": "text_match", "mode": "regex", "pattern": pattern})),
                       "existing": None, "task_ids": TASK_IDS}
    payload = {
        "group_id": "group-alpha",
        "cases": cases,
        "resolved": RESOLVE_RECORDS,
        "described": UNNAMED_CONDITIONS,
        "editor": {name: {"scope": scope, "record": record, "edit": edit}
                   for name, (scope, record, edit) in EDITOR_CASES.items()},
    }
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", NODE_SCRIPT, str(REPO_ROOT)],
        input=json.dumps(payload), cwd=REPO_ROOT, text=True, encoding="utf-8",
        capture_output=True, timeout=90, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript check failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_client_refuses_exactly_what_the_server_refuses(client, name):
    sent, existing, task_ids = CASES[name]
    accepted, message = _server(sent, existing, task_ids)
    errors = client["cases"][name]

    if accepted:
        assert errors == [], f"The client refused a save the server accepts: {errors}"
    else:
        assert errors, f"The client allowed a save the server refuses with: {message}"
        assert errors[0] == message


def test_every_refusal_is_covered_by_a_case():
    """Each reviewed message the server can raise is produced by at least one case above."""
    produced = {_server(*CASES[name])[1] for name in CASES} - {""}
    families = {name.split("_", 1)[0] for name in CASES if name[:1] in "WRSC" and name[1:2].isdigit()}
    assert families == {
        *(f"W{number}" for number in range(1, 8)), *(f"R{number}" for number in range(1, 5)),
        *(f"S{number}" for number in range(1, 4)), *(f"C{number}" for number in range(1, 21) if number != 12),
    }
    assert len(produced) >= 33


@pytest.mark.parametrize("name", sorted(REGEX_DIVERGENCE))
def test_python_only_regex_syntax_is_the_single_documented_divergence(client, name):
    """The client cannot compile Python patterns, so the server's reviewed 400 reports these."""
    accepted, message = _server(
        rules_case(rule({"type": "text_match", "mode": "regex", "pattern": REGEX_DIVERGENCE[name]})), None, TASK_IDS,
    )
    assert not accepted
    assert message == "Alert rule 1 regex pattern is not a valid regular expression."
    assert client["cases"][name] == []


def test_the_resolved_view_matches_resolve_workflow_alert_config(client):
    for name, record in RESOLVE_RECORDS.items():
        server = ALERTS.resolve_workflow_alert_config(copy.deepcopy(record))
        view = client["resolved"][name]
        assert view["config"]["alert_mode"] == server["alert_mode"], name
        assert view["config"]["alert_priority"] == server["alert_priority"], name
        assert view["config"]["alert_rules"] == server["alert_rules"], name
        assert view["config"]["alert_evaluation"]["on_error"] == server["alert_evaluation"]["on_error"], name
        assert view["summary"] == {
            "mode": server["alert_mode"], "priority": server["alert_priority"], "ruleCount": len(server["alert_rules"]),
        }, name
    assert client["resolved"]["priority_only"]["legacy"] is True
    assert client["resolved"]["rules"]["legacy"] is False


def test_described_names_match_the_names_the_server_assigns(client):
    stored = ALERTS.normalize_alert_rules([{"condition": condition} for condition in UNNAMED_CONDITIONS])
    assert client["described"] == [item["name"] for item in stored]


def _editor(client, name):
    scope, record, _ = EDITOR_CASES[name]
    outcome = client["editor"][name]
    payload = outcome["payload"]
    alert_errors = [error for error in outcome["errors"] if error.startswith(("Alert", "Add at least", "Choose", "A workflow can"))]
    return record, outcome["errors"], alert_errors, payload


def _server_save(payload, existing):
    task_ids = [task["id"] for task in payload["tasks"]]
    fields = {key: payload[key] for key in ("alert_mode", "alert_priority", "alert_rules", "alert_evaluation") if key in payload}
    try:
        return ALERTS.normalize_workflow_alert_settings(copy.deepcopy(fields), existing_workflow=copy.deepcopy(existing),
                                                        task_ids=task_ids)
    except DEFINITIONS.WorkflowPublicValidationError as exc:
        return exc.public_message


def test_an_untouched_configuration_is_sent_exactly_as_loaded(client):
    record, errors, _, payload = _editor(client, "untouched_rules_resent_exactly")
    assert errors == []
    for field in ("alert_mode", "alert_priority", "alert_rules", "alert_evaluation"):
        assert payload[field] == record[field], field
    assert isinstance(_server_save(payload, record), dict)


def test_a_priority_only_record_is_not_rewritten_by_the_client(client):
    """The client resends only alert_priority; the server itself turns it into the legacy rules (C3)."""
    record, errors, _, payload = _editor(client, "priority_only_untouched")
    assert errors == []
    assert payload["alert_priority"] == "high"
    assert not {"alert_mode", "alert_rules", "alert_evaluation"} & set(payload)
    saved = _server_save(payload, record)
    assert saved["alert_mode"] == "rules"
    assert [item["id"] for item in saved["alert_rules"]] == ["legacy-run-failed", "legacy-run-completed"]


def test_an_edited_priority_only_record_sends_all_four_fields(client):
    record, errors, _, payload = _editor(client, "priority_only_edited")
    assert errors == []
    assert payload["alert_mode"] == "every_run"
    assert payload["alert_priority"] == "high"
    assert [item["id"] for item in payload["alert_rules"]] == ["legacy-run-failed", "legacy-run-completed"]
    assert payload["alert_evaluation"] == {"on_error": "skip"}
    assert _server_save(payload, record)["alert_mode"] == "every_run"


def test_a_rule_watching_a_removed_task_is_flagged_before_saving(client):
    """C5: the removed task is flagged with the server's own reviewed message, before any request."""
    record, _, alert_errors, payload = _editor(client, "removed_task_is_flagged")
    message = "Alert rule 2 watches a task that is no longer in this workflow."
    assert alert_errors == [message]
    assert _server_save(payload, record) == message


def test_the_client_never_drops_a_rule_field(client):
    """Unknown rule fields are sent back; the server's allow-lists then drop them (C2)."""
    record, errors, _, payload = _editor(client, "rule_fields_survive_an_edit")
    assert errors == []
    sent_rule = payload["alert_rules"][0]
    assert sent_rule["name"] == "Renamed"
    assert sent_rule["category"] == "failure"
    assert sent_rule["x_extra"] == {"kept": True}
    stored_rule = _server_save(payload, record)["alert_rules"][0]
    assert "category" not in stored_rule and "x_extra" not in stored_rule


def test_a_condition_type_change_keeps_fields_the_editor_does_not_model(client):
    record, errors, _, payload = _editor(client, "condition_type_change_keeps_unknown_keys")
    assert errors == []
    assert payload["alert_rules"][0]["condition"] == {"x_condition": 1, "type": "file_sync", "outcome": "changes_found"}
    assert _server_save(payload, record)["alert_rules"][0]["condition"] == {"type": "file_sync", "outcome": "changes_found"}


def test_the_default_new_rule_saves(client):
    record, errors, _, payload = _editor(client, "new_rule_on_a_new_mode")
    assert errors == []
    saved = _server_save(payload, record)
    assert saved["alert_mode"] == "rules"
    assert saved["alert_rules"][0]["condition"] == {"type": "run_status", "statuses": ["failed"]}
    assert (saved["alert_rules"][0]["severity"], saved["alert_rules"][0]["delivery"]) == ("high", "default")
    # An unnamed rule is named by the server from its condition, as the editor's heading showed it.
    assert payload["alert_rules"][0]["name"] == ""
    assert saved["alert_rules"][0]["name"] == "Run status is failed"
