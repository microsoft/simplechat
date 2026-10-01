#!/usr/bin/env python3
# test_chat_workflow_results_admin.py
"""
Functional test for the admin switch that lets chat answer from stored workflow results.
Version: 0.261.213
Implemented in: 0.261.213

This test ensures that ``enable_chat_workflow_results`` (Use Workflow Results In Chat) is off
unless an administrator turns it on, that both admin surfaces save it faithfully, and that the
gate the routes and the V2 bootstrap use follows the personal-workflow gate:

* ``get_settings`` seeds it off, and the Classic settings page fills a missing value as off.
* The V2 schema declares an off-by-default switch in the Workflow section, shown only while
  personal workflows are on.
* The V2 settings update coerces the submitted value and changes nothing else.
* The Classic pane renders the switch, and the Classic form reads it like its neighbours.
* ``update_settings`` stores only a real ``True`` as on and leaves an absent value alone.
* ``is_chat_workflow_results_enabled_for_user`` is the personal-workflow gate plus the setting,
  ``workflow_results_required`` refuses with a closed code, and the V2 bootstrap reports the
  gate's decision rather than the raw setting.
* The admin documentation names the switch by its V2 label.
"""

import ast
import copy
import itertools
import re
import sys
from contextlib import nullcontext
from functools import wraps
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from flask import Flask, jsonify
from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_app_settings_store_consistency import FakeCosmos  # noqa: E402
from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_orchestration_limits_settings import _settings_writer  # noqa: E402


KEY = "enable_chat_workflow_results"
LABEL = "Use Workflow Results In Chat"
SECTION = "workflow-settings-section"
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
ADMIN_ROUTE = APP_ROOT / "route_frontend_admin_settings.py"
BACKEND_V2 = APP_ROOT / "route_backend_v2.py"
FIELDS = import_app_module("admin_settings_fields")
ROLE_FUNCTIONS = (
    "normalize_app_role_claims", "has_workflow_user_app_role", "is_user_workflows_enabled_for_user",
    "is_chat_workflow_results_enabled_for_user",
)
MISSING = object()
ENABLED = {"allow_user_workflows": True, "require_member_of_workflow_user": False, KEY: True}


def parsed(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def top_level_functions(path, names):
    found = {
        node.name: node for node in parsed(path).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    assert sorted(set(names) - set(found)) == [], f"{path.name} no longer defines every expected function"
    return [found[name] for name in names]


def top_level_constant(path, name):
    for node in parsed(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} no longer defines {name}")


def run_source(nodes, path, namespace):
    exec(compile(ast.Module(body=list(nodes), type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def lifted_gates(**extra):
    """The real role and workflow-results gates from ``functions_settings.py``."""
    return run_source(top_level_functions(SETTINGS_MODULE, ROLE_FUNCTIONS), SETTINGS_MODULE, {
        "WORKFLOW_USER_APP_ROLE": top_level_constant(SETTINGS_MODULE, "WORKFLOW_USER_APP_ROLE"),
        **extra,
    })


def settings_with(**changes):
    settings = dict(ENABLED)
    for key, value in changes.items():
        if value is MISSING:
            settings.pop(key, None)
        else:
            settings[key] = value
    return settings


def _render_classic_pane(settings):
    environment = Environment(
        loader=FileSystemLoader(APP_ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    return environment.get_template("admin/_panes/workflow.html").render(
        settings=settings, admin_landing_tab="workflow",
    )


def test_version_is_at_least_the_workflow_results_release():
    assert_app_version_at_least("0.261.213")


def test_the_setting_is_seeded_off():
    get_settings = next(
        node for node in parsed(SETTINGS_MODULE).body
        if isinstance(node, ast.FunctionDef) and node.name == "get_settings"
    )
    seeded = [
        value
        for node in ast.walk(get_settings) if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value == KEY
    ]
    assert len(seeded) == 1
    assert isinstance(seeded[0], ast.Constant) and seeded[0].value is False


def test_the_classic_settings_page_fills_a_missing_value_as_off():
    fills = [
        node for node in ast.walk(parsed(ADMIN_ROUTE))
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == f"'{KEY}' not in settings"
    ]
    assert len(fills) == 1
    assert [ast.unparse(statement) for statement in fills[0].body] == [f"settings['{KEY}'] = False"]


def test_the_v2_field_is_an_off_by_default_switch_gated_on_personal_workflows():
    field = FIELDS.get_field_definition(KEY)
    assert (field["type"], field["label"], field["default"]) == ("switch", LABEL, False)
    assert field["depends_on"] == {"key": "allow_user_workflows", "equals": True}
    keys = [item.get("key") for item in FIELDS.ADMIN_SETTINGS_FIELDS[SECTION]]
    # It sits with the other personal-workflow switches, after the AI workflow assistant.
    assert keys.index(KEY) == keys.index("enable_workflow_ai_assistant") + 1
    assert "role" not in field

    for workflows in (False, True):
        assert FIELDS.field_dependencies_are_satisfied(field, {"allow_user_workflows": workflows}) is workflows

    assert "not re-run" in field["help"]
    assert "private chats" in field["help"]


@pytest.mark.parametrize("value, expected", [(True, True), (False, False), ("on", True), ("false", False)])
def test_the_v2_update_coerces_the_switch_and_changes_nothing_else(value, expected):
    current = {KEY: not expected, "allow_user_workflows": True, "enable_workflow_ai_assistant": True}
    before = copy.deepcopy(current)
    normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({KEY: value}, current)
    assert errors == {}
    assert normalized == {KEY: expected}
    assert current == before


def test_the_classic_pane_renders_the_switch():
    for stored, checked in ((True, True), (False, False), (None, False)):
        markup = _render_classic_pane({} if stored is None else {KEY: stored})
        match = re.search(rf'<input[^>]*\bid="{KEY}"[^>]*>', markup, re.S)
        assert match, "The Classic Workflow pane has no input for the switch"
        tag = match.group(0)
        assert 'type="checkbox"' in tag and f'name="{KEY}"' in tag
        assert bool(re.search(r"\schecked\b", tag)) is checked, stored

    label = re.search(rf'<label[^>]*\bfor="{KEY}"[^>]*>(.*?)</label>', markup, re.S)
    assert label and " ".join(label.group(1).split()) == LABEL
    # The switch follows the AI workflow assistant in the personal-workflow block.
    assert markup.index('id="enable_workflow_ai_assistant"') < markup.index(f'id="{KEY}"')
    assert markup.index(f'id="{KEY}"') < markup.index('id="workflow_max_auto_invoke_attempts"')


def test_the_classic_form_reads_the_switch_like_its_neighbours():
    entries = {
        key.value: ast.unparse(value)
        for node in ast.walk(parsed(ADMIN_ROUTE)) if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and key.value in {KEY, "enable_workflow_ai_assistant"}
        and isinstance(value, ast.Compare)
    }
    # A browser posts a ticked checkbox as "on" and leaves an unticked one out.
    assert entries == {
        "enable_workflow_ai_assistant": "form_data.get('enable_workflow_ai_assistant') == 'on'",
        KEY: f"form_data.get('{KEY}') == 'on'",
    }


def test_the_settings_writer_stores_only_a_real_true():
    storage = FakeCosmos()
    writer = _settings_writer(storage)
    embedding = ModuleType("functions_embedding_compatibility")
    embedding.embedding_settings_write_guard = lambda *_args, **_kwargs: nullcontext()

    with patch.dict(sys.modules, {"functions_embedding_compatibility": embedding}):
        for value, stored in ((True, True), ("true", False), (1, False), ("on", False), (None, False), (False, False)):
            update = {KEY: value}
            saved = writer(update)
            assert saved, value
            assert storage.document[KEY] is stored, value
            # The caller's dictionary is not rewritten.
            assert update == {KEY: value} and type(update[KEY]) is type(value)

        storage.document[KEY] = True
        saved = writer({"allow_user_workflows": True})
        assert saved
        assert storage.document[KEY] is True


def test_the_gate_is_the_personal_workflow_gate_plus_a_real_true():
    gates = lifted_gates()
    personal_gate = gates["is_user_workflows_enabled_for_user"]
    results_gate = gates["is_chat_workflow_results_enabled_for_user"]
    checked = 0

    for allow, require, roles, value in itertools.product(
        [True, False, MISSING], [True, False, MISSING], [None, ["Reader"], ["WorkflowUser"], ["workflowuser"]],
        [True, False, "true", 1, None, MISSING],
    ):
        settings = settings_with(
            allow_user_workflows=allow, require_member_of_workflow_user=require, **{KEY: value},
        )
        personal = personal_gate(settings, user_roles=roles)
        enabled = results_gate(settings, user_roles=roles)

        assert enabled is (personal and value is True), (allow, require, roles, value)
        checked += 1

    assert checked == 3 * 3 * 4 * 6
    assert results_gate(None) is False
    assert results_gate({}) is False
    assert results_gate(None, user_roles=["WorkflowUser"]) is False


def test_the_route_decorator_refuses_with_a_closed_code():
    settings = dict(ENABLED)
    session = {"user": {"roles": []}}
    calls = []
    gates = lifted_gates()
    decorator = run_source(top_level_functions(SETTINGS_MODULE, ("workflow_results_required",)), SETTINGS_MODULE, {
        "wraps": wraps, "jsonify": jsonify, "session": session, "get_settings": lambda: settings,
        "is_chat_workflow_results_enabled_for_user": gates["is_chat_workflow_results_enabled_for_user"],
    })["workflow_results_required"]

    @decorator
    def view():
        calls.append("view")
        return "answered"

    app = Flask("chat-workflow-results-admin")
    with app.test_request_context("/"):
        answered = view()
        assert answered == "answered"
        assert calls == ["view"]

        for changes, roles in (
            ({KEY: False}, []), ({KEY: "true"}, []), ({KEY: MISSING}, []),
            ({"allow_user_workflows": False}, ["WorkflowUser"]),
            ({"require_member_of_workflow_user": True}, ["Reader"]),
        ):
            settings.clear()
            settings.update(settings_with(**changes))
            session["user"]["roles"] = roles
            response, status = view()
            assert status == 403
            assert response.get_json() == {
                "error": "Workflow results in chat are not available.", "code": "workflow_results_disabled",
            }
        assert calls == ["view"]

        settings.clear()
        settings.update(settings_with(require_member_of_workflow_user=True))
        session["user"]["roles"] = ["WorkflowUser"]
        answered_again = view()
        assert answered_again == "answered"
        assert calls == ["view", "view"]
    assert view.__name__ == "view"


def test_the_v2_bootstrap_reports_the_gate_not_the_raw_setting():
    bootstrap = next(
        node for node in ast.walk(parsed(BACKEND_V2))
        if isinstance(node, ast.FunctionDef) and node.name == "v2_bootstrap"
    )
    [overrides] = [
        node.value for node in ast.walk(bootstrap)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "per_user_overrides" for target in node.targets)
    ]
    values = {
        key.value: ast.unparse(value) for key, value in zip(overrides.keys, overrides.values)
        if isinstance(key, ast.Constant)
    }
    assert values[KEY] == "is_chat_workflow_results_enabled_for_user(settings, user_roles=current_user_roles)"

    build_feature_flags = run_source(
        top_level_functions(BACKEND_V2, ("_build_feature_flags",)), BACKEND_V2, {},
    )["_build_feature_flags"]
    gate = lifted_gates()["is_chat_workflow_results_enabled_for_user"]

    def flag(settings, roles):
        return build_feature_flags(dict(settings), {KEY: gate(settings, user_roles=roles)})[KEY]

    assert flag(ENABLED, []) is True
    # The raw setting alone would say on; the override follows the personal-workflow rule.
    assert flag(settings_with(allow_user_workflows=False), []) is False
    assert flag(settings_with(require_member_of_workflow_user=True), []) is False
    assert flag(settings_with(require_member_of_workflow_user=True), ["WorkflowUser"]) is True
    assert flag(settings_with(**{KEY: False}), ["WorkflowUser"]) is False


def test_the_admin_docs_name_the_switch_by_its_v2_label():
    page = (ROOT / "docs" / "admin" / "workflow.md").read_text(encoding="utf-8")
    row = next((line for line in page.splitlines() if line.startswith("|") and f"`{KEY}`" in line), None)
    assert row, f"docs/admin/workflow.md has no settings row for {KEY}"
    assert row.startswith(f"| {LABEL} |")
    assert "| Off |" in row


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
