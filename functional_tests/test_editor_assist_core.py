#!/usr/bin/env python3
# test_editor_assist_core.py
"""
Functional test for the agent and action editor Ask AI core.
Version: 0.261.278
Implemented in: 0.261.278

This test ensures that ``functions_editor_assist`` reads the editor's field descriptors strictly,
never sends secret fields to the model, maps choice options to opaque handles and back, applies
``set`` and ``create_item`` operations with type variants, corrects invalid model output once,
refunds the rate-limit lease when the model never ran, and returns closed error codes. The
limiter's ``document_type`` keeps editor and workflow lease documents apart. No Azure service,
model or Flask app is used.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_editor_assist as ea  # noqa: E402
import functions_workflow_assist_limits as limits  # noqa: E402
from functions_workflow_assist import WorkflowAssistError  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


USER_ID = "user-0001"
SUBMISSION_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
SECRET = "SECRET-VALUE-0b7e"


class FakeLimiter:
    def __init__(self, error=None):
        self.events = []
        self.error = error

    def acquire(self, user_id):
        self.events.append(("acquire", user_id))
        if self.error is not None:
            raise self.error
        return "lease"

    def release(self, lease, refund=False):
        self.events.append(("release", refund))


class ScriptedModel:
    """Returns each scripted reply in turn; a callable reply sees the envelope."""

    def __init__(self, *replies, finish="stop"):
        self.replies = list(replies)
        self.finish = finish
        self.calls = []

    def __call__(self, messages, timeout):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(json.loads(messages[1]["content"]))
        return (reply if isinstance(reply, str) else json.dumps(reply)), self.finish


def run(body, model, *, kind="agent", limiter=None):
    services = ea.EditorAssistServices(limiter=limiter or FakeLimiter(), call_model=model)
    return ea.run_editor_assist(body, kind=kind, scope="personal", user_id=USER_ID, services=services)


def agent_body(**extra):
    body = {
        "submission_id": SUBMISSION_ID,
        "instruction": "Make it a helpful SQL agent.",
        "sections": [{"id": "identity", "label": "Identity"}, {"id": "actions", "label": "Actions"}],
        "fields": [
            {"path": "/display_name", "label": "Name", "section": "identity", "kind": "text", "required": True},
            {"path": "/instructions", "label": "Instructions", "section": "identity", "kind": "textarea"},
            {"path": "/max_completion_tokens", "label": "Max tokens", "kind": "number", "min": 1, "max": 4000, "integer": True},
            {"path": "/actions", "label": "Actions", "section": "actions", "kind": "choices", "options": [
                {"value": "action-a", "label": "Weather"}, {"value": "action-b", "label": "Search"},
            ]},
        ],
        "values": {"/display_name": "Old", "/instructions": "", "/max_completion_tokens": 100, "/actions": ["action-a"]},
    }
    body.update(extra)
    return body


def handle_for(envelope, path, value_label):
    field = next(item for item in envelope["draft"]["fields"] if item["path"] == path)
    return next(option["handle"] for option in field["options"] if option["label"] == value_label)


def test_version():
    assert_app_version_at_least("0.261.278")


def test_set_operations_change_the_candidate_and_report_changes():
    model = ScriptedModel(lambda env: {"reply": "Done.", "operations": [
        {"op": "set", "path": "/display_name", "value": "SQL helper"},
        {"op": "set", "path": "/actions", "value": [handle_for(env, "/actions", "Search")]},
    ]})
    limiter = FakeLimiter()
    result = run(agent_body(), model, limiter=limiter)

    assert result["outcome"] == "changed"
    assert result["candidate"]["values"]["/display_name"] == "SQL helper"
    assert result["candidate"]["values"]["/actions"] == ["action-b"]
    assert [change["path"] for change in result["changes"]] == ["/display_name", "/actions"]
    assert limiter.events == [("acquire", USER_ID), ("release", False)]
    # Real option values never reach the model; only handles do.
    assert "action-b" not in json.dumps(model.calls[0])


def test_secret_fields_are_dropped_before_the_model():
    body = {
        "submission_id": SUBMISSION_ID,
        "instruction": "Name it.",
        "fields": [
            {"path": "/displayName", "label": "Name", "kind": "text"},
            {"path": "/additionalFields/api_key", "label": "Key", "kind": "text"},
            {"path": "/additionalFields/client_secret", "label": "Secret", "kind": "text"},
            {"path": "/additionalFields/token_hint", "label": "Hint", "kind": "secret"},
        ],
        "values": {
            "/displayName": "x", "/additionalFields/api_key": SECRET,
            "/additionalFields/client_secret": SECRET, "/additionalFields/token_hint": SECRET,
        },
    }
    model = ScriptedModel({"reply": "Ok.", "operations": [{"op": "set", "path": "/displayName", "value": "Y"}]})
    result = run(body, model, kind="action")

    assert SECRET not in json.dumps(model.calls)
    assert SECRET not in json.dumps(result)


def test_the_model_cannot_set_a_secret_or_undescribed_path():
    body = agent_body()
    bad = {"reply": "Ok.", "operations": [{"op": "set", "path": "/model", "value": "gpt"}]}
    fixed = {"reply": "Ok.", "operations": [{"op": "set", "path": "/display_name", "value": "New"}]}
    model = ScriptedModel(bad, fixed)
    result = run(body, model)

    assert len(model.calls) == 2  # one correction round
    assert result["candidate"]["values"]["/display_name"] == "New"
    assert "/model" not in result["candidate"]["values"]


@pytest.mark.parametrize("path, expected", [
    ("/additionalFields/api_key", True),
    ("/additionalFields/access_token", True),
    ("/additionalFields/connection_string", True),
    ("/max_completion_tokens", False),
    ("/display_name", False),
])
def test_is_secret_path(path, expected):
    assert ea.is_secret_path(path) is expected


def test_number_limits_are_corrected_then_refused():
    over = {"reply": "Ok.", "operations": [{"op": "set", "path": "/max_completion_tokens", "value": 99999}]}
    model = ScriptedModel(over, over)
    with pytest.raises(ea.EditorAssistError) as caught:
        run(agent_body(), model)
    assert caught.value.code == "assistant_output_invalid"
    assert len(model.calls) == 2


def test_an_explanation_changes_nothing():
    model = ScriptedModel({"reply": "Agents call actions to reach tools.", "operations": []})
    result = run(agent_body(), model)
    assert result["outcome"] == "explained"
    assert result["candidate"] is None and result["changes"] == []


def test_operations_that_change_nothing_are_explained():
    model = ScriptedModel({"reply": "Renamed.", "operations": [{"op": "set", "path": "/display_name", "value": "Old"}]})
    result = run(agent_body(), model)
    assert result["outcome"] == "explained"
    assert result["reply"] == ea._NO_CHANGE_REPLY


def test_create_item_drafts_a_new_action_and_assigns_it():
    new_items = {
        "target": "/actions", "noun": "action", "max": 2,
        "types": [{"value": "sql_query", "label": "SQL query"}],
        "common": [{"path": "/displayName", "label": "Name", "kind": "text", "required": True}],
        "variants": {"sql_query": [
            {"path": "/additionalFields/max_rows", "label": "Rows", "kind": "number", "min": 1, "max": 100, "integer": True},
            {"path": "/additionalFields/connection_string", "label": "Connection", "kind": "text"},
        ]},
    }
    model = ScriptedModel({"reply": "Drafted.", "operations": [{
        "op": "create_item", "handle": "N1", "type": "sql_query",
        "values": {"/displayName": "Orders", "/additionalFields/max_rows": 25},
    }]})
    result = run(agent_body(new_items=new_items), model)

    assert result["candidate"]["values"]["/actions"] == ["action-a", "new:N1"]
    assert result["candidate"]["new_items"] == [{
        "handle": "new:N1", "type": "sql_query",
        "values": {"/displayName": "Orders", "/additionalFields/max_rows": 25},
    }]
    # Secret fields of a drafted type are never offered to the model.
    assert "connection_string" not in json.dumps(model.calls[0])


def test_new_items_are_agent_only():
    body = {
        "submission_id": SUBMISSION_ID, "instruction": "x",
        "fields": [{"path": "/displayName", "label": "Name"}], "values": {},
        "new_items": {"target": "/displayName", "noun": "x", "types": [], "common": [], "variants": {}},
    }
    with pytest.raises(ea.EditorAssistError) as caught:
        run(body, ScriptedModel())
    assert caught.value.status == 400


def test_a_type_change_validates_against_the_new_variant():
    body = {
        "submission_id": SUBMISSION_ID, "instruction": "Make it a SQL action.",
        "fields": [
            {"path": "/displayName", "label": "Name", "kind": "text"},
            {"path": "/type", "label": "Type", "kind": "select", "options": [
                {"value": "openapi", "label": "OpenAPI"}, {"value": "sql_query", "label": "SQL"},
            ]},
        ],
        "variant": {"path": "/type", "fields": {
            "openapi": [{"path": "/endpoint", "label": "Endpoint", "kind": "text"}],
            "sql_query": [{"path": "/additionalFields/database", "label": "Database", "kind": "text", "required": True}],
        }},
        "values": {"/displayName": "A", "/type": "openapi", "/endpoint": "https://example.com"},
    }
    model = ScriptedModel({"reply": "Switched.", "operations": [
        {"op": "set", "path": "/type", "value": "sql_query"},
    ]})
    result = run(body, model, kind="action")

    values = result["candidate"]["values"]
    assert values["/type"] == "sql_query"
    assert "/endpoint" not in values
    assert {"code": "required_fields_missing", "paths": ["/additionalFields/database"]} in [
        {key: warning.get(key) for key in ("code", "paths")} for warning in result["warnings"]
    ]


@pytest.mark.parametrize("mutate, code", [
    (lambda body: body.pop("instruction"), "invalid_request"),
    (lambda body: body.update(instruction=""), "instruction_invalid"),
    (lambda body: body.update(surprise=True), "invalid_request"),
    (lambda body: body.update(focus="nowhere"), "focus_invalid"),
])
def test_invalid_requests_are_refused_before_the_limiter(mutate, code):
    body = agent_body()
    mutate(body)
    limiter = FakeLimiter()
    with pytest.raises(ea.EditorAssistError) as caught:
        run(body, ScriptedModel(), limiter=limiter)
    assert caught.value.code == code
    assert limiter.events == []


def test_a_model_failure_before_any_call_is_refunded():
    limiter = FakeLimiter()
    model = ScriptedModel(WorkflowAssistError("assistant_unavailable"))
    with pytest.raises(ea.EditorAssistError) as caught:
        run(agent_body(), model, limiter=limiter)
    assert caught.value.code == "assistant_unavailable"
    assert limiter.events[-1][0] == "release"


def test_shared_limiter_errors_are_converted():
    limiter = FakeLimiter(error=WorkflowAssistError("assistant_busy"))
    with pytest.raises(ea.EditorAssistError) as caught:
        run(agent_body(), ScriptedModel(), limiter=limiter)
    assert (caught.value.code, caught.value.status) == ("assistant_busy", 429)


def test_a_content_filter_finish_is_a_refusal():
    model = ScriptedModel({"reply": "", "operations": []}, finish="content_filter")
    with pytest.raises(ea.EditorAssistError) as caught:
        run(agent_body(), model)
    assert caught.value.code == "assistant_refused"


def test_parse_body_is_strict_json():
    for raw in (b"{\"a\": NaN}", b"not json", "{}".encode("utf-16")):
        with pytest.raises(ea.EditorAssistError):
            ea.parse_editor_assist_body(raw)
    assert ea.parse_editor_assist_body(b"{\"a\": 1}") == {"a": 1}


def test_limiter_document_type_keeps_editor_and_workflow_leases_apart():
    workflow_id = limits.assist_limit_document_id(USER_ID)
    editor_id = limits.assist_limit_document_id(USER_ID, document_type="editor_assist_rate_limit")
    assert workflow_id != editor_id
    assert limits.assist_limit_document_id(USER_ID) == workflow_id


def _settings_helpers():
    import ast
    path = ROOT / "application" / "single_app" / "functions_settings.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = ("is_agent_assistant_enabled", "is_action_assistant_enabled")
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return path.read_text(encoding="utf-8"), namespace


@pytest.mark.parametrize("helper, key", [
    ("is_agent_assistant_enabled", "enable_agent_ai_assistant"),
    ("is_action_assistant_enabled", "enable_action_ai_assistant"),
])
def test_admin_toggles_default_on_and_need_agents(helper, key):
    source, helpers = _settings_helpers()
    enabled = helpers[helper]
    assert f"'{key}': True" in source
    assert enabled({"enable_semantic_kernel": True}) is True
    assert enabled({"enable_semantic_kernel": True, key: False}) is False
    assert enabled({"enable_semantic_kernel": False, key: True}) is False
    assert enabled(None) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
