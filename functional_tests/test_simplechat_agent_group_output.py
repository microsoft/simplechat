# test_simplechat_agent_group_output.py
"""
Functional test for the group summary and the conflict answer the SimpleChat agent tools give.
Version: 0.261.161
Implemented in: 0.261.160

The ``create_group``, ``add_user_to_group`` and ``make_group_inactive`` tools
answered the model with the whole stored group document: every member's email,
pending join requests, status history and, with Key Vault storage off, inline model
endpoint credentials. Each now answers ``{id, name, status}`` for the group, through
one ``_agent_group_summary`` helper at the plugin boundary; the operations
themselves, which classic and native routes also call, still return the document.
Every other field of each answer is unchanged: ``add_user_to_group`` keeps its
``member``, and ``make_group_inactive`` keeps ``old_status`` and ``new_status``.

A group that kept changing while ``add_user_to_group`` or ``make_group_inactive``
saved (``GroupDocumentWriteConflict``) fell into the plugin's generic answer, "Failed
to ..." with the exception's text, logged at ERROR with its traceback. It now answers
a failure the model can relay: the shared sentence and code,
``GROUP_WRITE_CONFLICT_MESSAGE`` and ``GROUP_WRITE_CONFLICT_CODE``, with
``error_type`` ``conflict``, logged at WARNING with only the operation's name. Every
other failure keeps its answer.

The plugin module is loaded unchanged. Its application imports are stubs that
define every name the real modules define, refusing unless modelled here;
``functions_group``'s conflict exception, code and sentence are its real
definitions, run from source. The invocation logger is a pass-through, since it only
records the call.
"""

import copy
import importlib.util
import json
import logging
import sys
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.app_source import refusing_module_stub, run_definitions


STORED_GROUP = {
    "id": "group-1",
    "name": "Research",
    "description": "Private notes",
    "status": "active",
    "owner": {"id": "owner-1", "email": "olive.owner@example.test", "displayName": "Olive Owner"},
    "admins": ["admin-1"],
    "documentManagers": [],
    "users": [
        {"userId": "owner-1", "email": "olive.owner@example.test", "displayName": "Olive Owner"},
        {"userId": "admin-1", "email": "adam.admin@example.test", "displayName": "Adam Admin"},
    ],
    "pendingUsers": [{"userId": "applicant-1", "email": "ana.applicant@example.test"}],
    "statusHistory": [{"old_status": "locked", "new_status": "active", "changed_by_email": "cc.admin@example.test"}],
    "model_endpoints": [{"id": "ep-1", "auth": {"type": "api_key", "api_key": "sk-inline-endpoint-secret"}}],
    "retention_policy": {"conversation_retention_days": "default"},
    "_etag": '"etag-7"',
}
PRIVATE_VALUES = (
    "olive.owner@example.test", "adam.admin@example.test", "ana.applicant@example.test",
    "cc.admin@example.test", "sk-inline-endpoint-secret", "Private notes", "etag-7",
)
MEMBER = {"userId": "newcomer-1", "email": "nia.newcomer@example.test", "displayName": "Nia Newcomer"}
GROUP_CONFLICT_NAMES = ("GroupDocumentWriteConflict", "GROUP_WRITE_CONFLICT_CODE", "GROUP_WRITE_CONFLICT_MESSAGE")


@contextmanager
def plugin_environment():
    calls = []
    logs = []
    answers = {}
    group = run_definitions("functions_group.py", set(GROUP_CONFLICT_NAMES), {"__name__": "functions_group"})

    def operation(name):
        def run(**kwargs):
            calls.append((name, kwargs))
            answer = answers[name]
            if isinstance(answer, Exception):
                raise answer
            return copy.deepcopy(answer)
        return run

    stubs = {
        "functions_appinsights": refusing_module_stub(
            "functions_appinsights.py", "functions_appinsights",
            log_event=lambda *args, **kwargs: logs.append((args, kwargs)),
        ),
        "functions_group": refusing_module_stub(
            "functions_group.py", "functions_group", **{name: group[name] for name in GROUP_CONFLICT_NAMES},
        ),
        "functions_simplechat_operations": refusing_module_stub(
            "functions_simplechat_operations.py", "functions_simplechat_operations",
            normalize_simplechat_capabilities=lambda capabilities=None: dict(capabilities or {}),
            create_group_for_current_user=operation("create_group_for_current_user"),
            add_group_member_for_current_user=operation("add_group_member_for_current_user"),
            make_group_inactive_for_current_user=operation("make_group_inactive_for_current_user"),
        ),
        "semantic_kernel_plugins.plugin_invocation_logger": refusing_module_stub(
            "semantic_kernel_plugins/plugin_invocation_logger.py", "semantic_kernel_plugins.plugin_invocation_logger",
            plugin_function_logger=lambda plugin_name: (lambda function: function),
        ),
    }
    with ExitStack() as stack:
        stack.enter_context(patch.object(sys, "path", [str(APP_ROOT), *sys.path]))
        stack.enter_context(patch.dict(sys.modules, stubs))
        name = "semantic_kernel_plugins.simplechat_plugin"
        spec = importlib.util.spec_from_file_location(name, APP_ROOT / "semantic_kernel_plugins" / "simplechat_plugin.py")
        module = importlib.util.module_from_spec(spec)
        stack.enter_context(patch.dict(sys.modules, {name: module}))
        spec.loader.exec_module(module)
        plugin = module.SimpleChatPlugin({
            "name": "simplechat_tools", "type": "simplechat", "default_group_id": "group-1",
            "enabled_functions": ["create_group", "add_group_member", "make_group_inactive"],
        })
        yield SimpleNamespace(
            module=module, plugin=plugin, calls=calls, logs=logs, answers=answers,
            group=SimpleNamespace(**{name: group[name] for name in GROUP_CONFLICT_NAMES}),
        )


@pytest.fixture(scope="module")
def module_env():
    with plugin_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.calls.clear()
    module_env.logs.clear()
    module_env.answers.clear()
    yield module_env


def assert_private_values_absent(result):
    text = json.dumps(result)
    leaked = [value for value in PRIVATE_VALUES if value in text]
    assert leaked == [], f"The tool answer carries stored group data: {leaked}"


def test_create_group_answers_the_group_summary(env):
    env.answers["create_group_for_current_user"] = STORED_GROUP
    result = env.plugin.create_group(name="Research", description="Private notes")
    assert result == {"group": {"id": "group-1", "name": "Research", "status": "active"}, "success": True}
    assert env.calls == [("create_group_for_current_user", {"name": "Research", "description": "Private notes"})]
    assert_private_values_absent(result)


def test_a_group_without_a_stored_status_is_active(env):
    env.answers["create_group_for_current_user"] = {key: value for key, value in STORED_GROUP.items() if key != "status"}
    assert env.plugin.create_group(name="Research")["group"] == {"id": "group-1", "name": "Research", "status": "active"}


def test_add_user_to_group_answers_the_summary_and_keeps_the_member(env):
    env.answers["add_group_member_for_current_user"] = {
        "success": True, "message": "Member added", "group_id": "group-1", "group_name": "Research",
        "member": MEMBER, "member_role": "user", "group": STORED_GROUP,
    }
    result = env.plugin.add_user_to_group(user_identifier="nia.newcomer@example.test", role="user")
    assert result == {
        "success": True, "message": "Member added", "group_id": "group-1", "group_name": "Research",
        "member": MEMBER, "member_role": "user", "group": {"id": "group-1", "name": "Research", "status": "active"},
    }
    assert env.calls == [("add_group_member_for_current_user", {
        "group_id": "", "user_identifier": "nia.newcomer@example.test", "email": "", "display_name": "",
        "role": "user", "default_group_id": "group-1",
    })]
    assert_private_values_absent(result)


@pytest.mark.parametrize("old_status,message", [
    ("active", "Marked group 'Research' as inactive."),
    ("inactive", "Group 'Research' is already inactive."),
])
def test_make_group_inactive_answers_the_summary_and_both_statuses(env, old_status, message):
    env.answers["make_group_inactive_for_current_user"] = {
        "group": {**STORED_GROUP, "status": "inactive"}, "old_status": old_status, "new_status": "inactive",
        "message": message,
    }
    result = env.plugin.make_group_inactive(reason="Cleanup")
    assert result == {
        "group": {"id": "group-1", "name": "Research", "status": "inactive"},
        "old_status": old_status, "new_status": "inactive", "message": message, "success": True,
    }
    assert env.calls == [("make_group_inactive_for_current_user", {
        "group_id": "", "reason": "Cleanup", "default_group_id": "group-1",
    })]
    assert_private_values_absent(result)


@pytest.mark.parametrize("error,expected", [
    (PermissionError("Insufficient permissions (Admin role required)"),
     {"success": False, "error": "Insufficient permissions (Admin role required)", "error_type": "permission"}),
    (LookupError("Group not found"), {"success": False, "error": "Group not found", "error_type": "not_found"}),
    (ValueError("User is already a member"),
     {"success": False, "error": "User is already a member", "error_type": "validation"}),
])
def test_refusals_keep_their_answers(env, error, expected):
    for name in ("create_group_for_current_user", "add_group_member_for_current_user", "make_group_inactive_for_current_user"):
        env.answers[name] = error
    assert env.plugin.create_group(name="Research") == expected
    assert env.plugin.add_user_to_group(user_identifier="x") == expected
    assert env.plugin.make_group_inactive() == expected
    assert env.logs == []


CONFLICT_TOOLS = {
    "add_user_to_group": (
        "add_group_member_for_current_user", "add_group_member",
        lambda plugin: plugin.add_user_to_group(user_identifier="nia.newcomer@example.test"),
    ),
    "make_group_inactive": (
        "make_group_inactive_for_current_user", "make_group_inactive",
        lambda plugin: plugin.make_group_inactive(reason="Cleanup"),
    ),
}


@pytest.mark.parametrize("tool", CONFLICT_TOOLS)
def test_a_group_that_keeps_changing_is_a_conflict_the_model_can_relay(env, tool):
    operation, operation_name, call = CONFLICT_TOOLS[tool]
    # The exception's own text is never relayed or logged, whatever it holds.
    env.answers[operation] = env.group.GroupDocumentWriteConflict(
        "group-1 kept changing for olive.owner@example.test (Private notes)",
    )
    result = call(env.plugin)
    assert result == {
        "success": False,
        "error": env.group.GROUP_WRITE_CONFLICT_MESSAGE,
        "error_type": "conflict",
        "error_code": env.group.GROUP_WRITE_CONFLICT_CODE,
    }
    assert (result["error"], result["error_code"]) == (
        "The group changed while your request was being saved. Try again.", "group_write_conflict",
    )
    assert env.logs == [(
        ("[SIMPLE_CHAT_PLUGIN] A group change was not saved because the group kept changing.",),
        {"extra": {"operation": operation_name}, "level": logging.WARNING},
    )]
    assert_private_values_absent(result)
    assert_private_values_absent(env.logs)
    assert "group-1" not in json.dumps(env.logs)


def test_any_other_failure_keeps_the_unexpected_answer(env):
    """A plain RuntimeError, the conflict's base class, is still unexpected."""
    env.answers["add_group_member_for_current_user"] = RuntimeError("storage unavailable")
    assert env.plugin.add_user_to_group(user_identifier="x") == {
        "success": False, "error": "Failed to add group member", "error_type": "unexpected",
        "details": "storage unavailable",
    }
    assert env.logs == [(
        ("[SIMPLE_CHAT_PLUGIN] add_group_member failed: storage unavailable",),
        {"level": logging.ERROR, "exceptionTraceback": True},
    )]


def test_the_summary_is_the_only_group_shape_a_tool_answers():
    """Each tool that answers a group projects it through the one helper."""
    import ast

    tree = ast.parse((APP_ROOT / "semantic_kernel_plugins" / "simplechat_plugin.py").read_text(encoding="utf-8"))
    plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SimpleChatPlugin")
    projected = {
        method.name for method in plugin.body if isinstance(method, ast.FunctionDef)
        and any(isinstance(node, ast.Name) and node.id in {"_agent_group_summary", "_with_agent_group_summary"}
                for node in ast.walk(method))
    }
    assert projected == {"create_group", "make_group_inactive", "add_user_to_group"}
