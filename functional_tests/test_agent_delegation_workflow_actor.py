# test_agent_delegation_workflow_actor.py
"""
Exercise workflow actor capture and all three real agent execution entry points.
Version: 0.261.093
Implemented in: 0.261.093

Group workflow ownership must not impersonate its creator when another member
runs it. Azure operations are replaced; identity capture, Flask isolation,
workflow entry functions, and delegation authorization run unchanged.
"""

import importlib.util
import sys
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Flask, g, has_request_context, session

from test_support.agent_delegation import APP_ROOT, delegation_environment, execute_functions, reference
from test_support.versioning import assert_app_version_at_least


class PreparedAgent(Exception):
    """Stop after the real entry point reaches the provider preparation boundary."""


@pytest.fixture
def workflow_environment():
    with delegation_environment() as (helper, services):
        module_name = "_workflow_actor_execution_context"
        spec = importlib.util.spec_from_file_location(module_name, APP_ROOT / "agent_execution_context.py")
        contexts = importlib.util.module_from_spec(spec)
        app = Flask("workflow-actor-regression")
        app.secret_key = "test-only"
        with patch.dict(sys.modules, {module_name: contexts}):
            spec.loader.exec_module(contexts)
            namespace = {
                "contextmanager": contextmanager, "nullcontext": nullcontext,
                "ContextVar": ContextVar, "Flask": Flask, "g": g, "session": session,
                "has_request_context": has_request_context,
                "DelegationBudget": contexts.DelegationBudget,
                "capture_execution_identity": contexts.capture_execution_identity,
                "_workflow_delegation_budget": ContextVar("actor_test_budget", default=None),
                "_workflow_execution_identity": ContextVar("actor_test_identity", default=None),
                "_workflow_alert_signal_context": ContextVar("actor_test_alerts", default=None),
                "_get_workflow_runner_app": lambda: app,
                "create_workflow_run_id": lambda: "created-run",
                "_get_workflow_group_id": lambda workflow: workflow.get("group_id"),
                "_raise_if_workflow_run_cancelled": Mock(),
                "raise_if_mixed_source_cancelled": Mock(),
                "_get_document_action_config": lambda workflow: workflow.get("document_action", {}),
                "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
                "DOCUMENT_ACTION_TYPE_COMPARISON": "compare",
                "DOCUMENT_ACTION_CONTEXT_WORKFLOW": "workflow",
                "get_document_action_max_documents": lambda *args, **kwargs: 25,
                "_chain_activity_callbacks": lambda *args: None,
                "_build_document_action_activity_callback": lambda *args, **kwargs: None,
                "_is_per_document_analysis_mode": lambda config: False,
                "_create_token_usage_aggregate": lambda: {},
                "debug_print": Mock(),
                "get_plugin_logger": Mock(),
                "Kernel": lambda: SimpleNamespace(services={}),
                "get_workflow_kernel_settings": lambda settings: settings,
                "load_user_semantic_kernel": Mock(
                    return_value=(SimpleNamespace(services={}), {"primary": SimpleNamespace(name="primary")}),
                ),
            }
            execute_functions("functions_workflow_runner.py", {
                "_workflow_delegation_scope", "_workflow_agent_execution_context",
                "_ensure_execution_context", "workflow_alert_signal_scope",
                "run_personal_workflow", "run_group_workflow",
                "_execute_agent_workflow", "_execute_document_analysis_workflow",
                "_execute_document_comparison_workflow",
            }, namespace)
            yield namespace, contexts, helper, services, app


def workflow_record(action="none"):
    return {
        "id": "workflow", "user_id": "creator", "group_id": "team",
        "runner_type": "agent", "task_prompt": "Run the task.",
        "selected_agent": {
            "id": "primary-id", "name": "primary", "is_group": True, "group_id": "team",
        },
        "document_action": {"type": action, "document_ids": ["document"]},
    }


ENTRY_POINTS = [
    ("_execute_agent_workflow", "none"),
    ("_execute_document_analysis_workflow", "analyze"),
    ("_execute_document_comparison_workflow", "compare"),
]


@pytest.mark.parametrize("entry_name,action", ENTRY_POINTS)
@pytest.mark.parametrize("ambient_creator", [False, True])
def test_all_agent_sites_use_captured_member_not_workflow_creator(
    workflow_environment, entry_name, action, ambient_creator,
):
    namespace, contexts, _, _, app = workflow_environment
    workflow = workflow_record(action)
    original = deepcopy(workflow)
    captured = []

    def prepare(agent, selected, **kwargs):
        identity = contexts.capture_execution_identity(kwargs["user_id"], kwargs["conversation_id"])
        captured.append((identity, dict(session), dict(g.authorized_chat_context)))
        raise PreparedAgent()

    namespace["prepare_agent_execution"] = prepare
    with app.test_request_context("/api/group/workflows/workflow/run"):
        session["user"] = {"oid": "member", "roles": ["User"]}
        session["token_cache"] = "member-cache"
        identity = contexts.capture_execution_identity("member")
        with namespace["_workflow_delegation_scope"](identity):
            if ambient_creator:
                session["user"] = {"oid": "creator", "roles": ["Admin"]}
                session["token_cache"] = "creator-cache"
            with pytest.raises(PreparedAgent):
                namespace[entry_name](workflow, {}, conversation_id="conversation", run_id="run")
            assert session["user"]["oid"] == ("creator" if ambient_creator else "member")
    assert len(captured) == 1
    execution, captured_session, authorized = captured[0]
    assert execution.user_id == "member"
    assert execution.roles == ("User",)
    assert execution.conversation_id == "conversation"
    assert captured_session["token_cache"] == "member-cache"
    assert authorized["user_id"] == "member"
    assert namespace["load_user_semantic_kernel"].call_args.args[2] == "member"
    assert namespace["get_plugin_logger"].return_value.clear_invocations_for_conversation.call_args.args == (
        "member", "conversation",
    )
    assert namespace["_workflow_execution_identity"].get() is None
    assert namespace["_workflow_delegation_budget"].get() is None
    assert workflow == original


@pytest.mark.parametrize("entry_name,action", ENTRY_POINTS)
def test_creator_authorization_cannot_grant_a_member_access_to_a_global_target(
    workflow_environment, entry_name, action,
):
    namespace, contexts, helper, services, app = workflow_environment
    services.add_agent("private-global", "global", "global")

    def authorize(feature, user_id, **kwargs):
        if user_id == "member" and kwargs.get("item_id") == "private-global":
            raise PermissionError("Member denied.")

    services.governance.ensure_governance_access.side_effect = authorize
    helper.resolve_delegation_agent(
        reference("private-global", "global", "global"), user_id="creator",
    )

    def prepare(agent, selected, **kwargs):
        helper.resolve_delegation_agent(
            reference("private-global", "global", "global"), user_id=kwargs["user_id"],
        )
        raise AssertionError("A member used the creator's permission.")

    namespace["prepare_agent_execution"] = prepare
    with app.test_request_context("/api/group/workflows/workflow/run"):
        session["user"] = {"oid": "member", "roles": ["User"]}
        identity = contexts.capture_execution_identity("member")
        with namespace["_workflow_delegation_scope"](identity):
            with pytest.raises(PermissionError, match="Member denied"):
                namespace[entry_name](workflow_record(action), {}, conversation_id="conversation", run_id="run")


def test_public_group_dispatch_captures_trusted_actor_and_preserves_storage_owner(workflow_environment):
    namespace, _, _, _, app = workflow_environment
    workflow = workflow_record()
    captured = []

    def dispatch(record, **kwargs):
        with namespace["_workflow_agent_execution_context"](record) as user_id:
            captured.append((user_id, session["user"]["oid"], record["user_id"], kwargs["actor_user_id"]))
        return {"success": True}

    namespace["_run_personal_workflow_impl"] = dispatch
    with app.test_request_context("/api/group/workflows/workflow/run"):
        session["user"] = {"oid": "member", "roles": ["User"]}
        namespace["run_group_workflow"](workflow, actor_user_id="member")
    assert captured == [("member", "member", "creator", "member")]
    assert namespace["_workflow_execution_identity"].get() is None


@pytest.mark.parametrize("entry_name,action", ENTRY_POINTS)
def test_private_entry_without_run_scope_does_not_impersonate_creator(workflow_environment, entry_name, action):
    namespace, _, _, _, app = workflow_environment
    observed = []

    def prepare(agent, selected, **kwargs):
        observed.append((kwargs["user_id"], session["user"]["oid"]))
        raise PreparedAgent()

    namespace["prepare_agent_execution"] = prepare
    with app.test_request_context("/workflow"):
        session["user"] = {"oid": "member", "roles": ["User"]}
        with pytest.raises(PreparedAgent):
            namespace[entry_name](workflow_record(action), {}, conversation_id="conversation", run_id="run")
    assert observed == [("member", "member")]


def test_scheduled_dispatch_uses_declared_owner_without_a_request(workflow_environment):
    namespace, _, _, _, _ = workflow_environment
    captured = []

    def dispatch(record, **kwargs):
        with namespace["_workflow_agent_execution_context"](record) as user_id:
            captured.append((user_id, session["user"]["oid"], session["user"]["roles"]))
        return {"success": True}

    namespace["_run_personal_workflow_impl"] = dispatch
    assert not has_request_context()
    namespace["run_group_workflow"](workflow_record(), trigger_source="scheduled")
    assert captured == [("creator", "creator", ["User"])]
    assert not has_request_context()
    assert namespace["_workflow_execution_identity"].get() is None


def test_actor_must_match_authenticated_request_before_dispatch(workflow_environment):
    namespace, _, _, _, app = workflow_environment
    dispatch = Mock()
    namespace["_run_personal_workflow_impl"] = dispatch
    with app.test_request_context("/api/group/workflows/workflow/run"):
        session["user"] = {"oid": "member", "roles": ["User"]}
        with pytest.raises(PermissionError):
            namespace["run_group_workflow"](workflow_record(), actor_user_id="creator")
    dispatch.assert_not_called()


def test_implementation_version():
    assert_app_version_at_least("0.261.093")
