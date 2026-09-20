# test_m365_chat_preflight_order.py
"""
Regression coverage for binding chat actions before Semantic Kernel loading.
Version: 0.261.032
Implemented in: 0.261.032

Reproduces the empty-tool selection with the real execution preflight, then
exercises the production chat authorization helper with scoped storage seams.
"""

import ast
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

from flask import Flask, g, request
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Repository imports follow the standalone source-path setup.
import functions_m365_execution as execution
from m365_interaction import M365SignInRequired
from test_support.m365 import CosmosContainer


def production_chat_helpers(namespace):
    path = APP / "route_backend_chats.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = {"_set_authorized_chat_request_context", "_create_personal_conversation"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(nodes) != len(names):
        raise AssertionError("The production chat authorization helpers were not found.")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("pause_for_auth", [False, True])
def test_selected_action_is_bound_before_preflight_and_new_chat_survives_auth_pause(monkeypatch, pause_for_auth):
    manifest = {
        "id": "calendar", "name": "Calendar", "type": "m365_calendar",
        "enabled_functions": ["get_my_events"],
    }
    agent = {"id": "agent", "name": "M365", "is_global": False}
    conversations = CosmosContainer("id")
    logged = Mock()
    selections = []
    effective = []
    pending = M365SignInRequired("interactive_auth_required", {"scopes": ["Calendars.Read"], "sources": ["calendar"]})

    def selected_ids(context):
        selected = getattr(g, "m365_selected_agent_ref", None)
        selections.append(selected)
        return ["calendar"] if selected == agent else []

    monkeypatch.setattr(execution, "_action_selection_resolver", selected_ids)
    monkeypatch.setattr(execution, "_action_config_resolver", lambda *args: manifest)
    monkeypatch.setattr(execution, "get_m365_approval_service", lambda: SimpleNamespace(
        authorize_sources=lambda context, sources: {source: {"private": True} for source in sources},
    ))

    def preflight(manifests):
        permitted = execution.preflight_m365_manifests(manifests)
        effective.extend(permitted)
        if pause_for_auth:
            raise pending
        return permitted

    namespace = production_chat_helpers({
        "g": g, "request": request, "datetime": datetime, "uuid": uuid,
        "cosmos_conversations_container": conversations,
        "log_conversation_creation": logged, "invalidate_conversation_cache_for_item": Mock(),
        "get_m365_execution_context": execution.get_m365_execution_context,
        "initialize_m365_chat_context": Mock(side_effect=AssertionError("The stream already owns its context.")),
        "_resolve_canonical_chat_agent": lambda user, settings, supplied: agent,
        "get_settings": lambda: {},
        "workflow_m365_manifests": lambda workflow: ([manifest], workflow),
        "preflight_m365_manifests": preflight,
    })
    app = Flask(__name__)
    with app.test_request_context(json={"agent_info": {"id": "agent", "name": "M365"}}):
        context = execution.M365ExecutionContext(
            "owner", "owner", "tenant", request_id="request", conversation_id="new-conversation",
        )
        with execution.m365_execution_context(context):
            before_binding = execution.preflight_m365_manifests([manifest])
            g.m365_new_conversation = True
            if pause_for_auth:
                with pytest.raises(M365SignInRequired) as raised:
                    namespace["_set_authorized_chat_request_context"]("owner", "new-conversation", {})
                assert raised.value is pending
            else:
                namespace["_set_authorized_chat_request_context"]("owner", "new-conversation", {})
                namespace["_set_authorized_chat_request_context"]("owner", "new-conversation", {})
            saved = conversations.read_item("new-conversation", "new-conversation")
            selected = dict(g.m365_selected_agent_ref)
            initial = dict(g.m365_initial_conversation)
            bound = execution.get_m365_execution_context()
    assert before_binding == []
    assert [item["id"] for item in effective] == ["calendar"]
    assert selected == agent
    assert saved["user_id"] == "owner"
    assert saved["id"] == initial["id"] == "new-conversation"
    assert saved["context"] == []
    assert "calendar" in bound.action_configs
    logged.assert_called_once()
    assert selections[0] is None
    assert agent in selections[1:]


def test_stream_authorizes_selected_actions_before_any_kernel_initialization():
    tree = ast.parse((APP / "route_backend_chats.py").read_text(encoding="utf-8-sig"))
    streams = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "generate"
        and any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            and child.func.id == "initialize_m365_chat_context"
            for child in ast.walk(node)
        )
    ]
    assert len(streams) == 1
    calls = [
        node for node in ast.walk(streams[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    authorizations = [call.lineno for call in calls if call.func.id == "_set_authorized_chat_request_context"]
    initializations = [call.lineno for call in calls if call.func.id == "initialize_semantic_kernel"]
    assert authorizations and initializations
    assert max(authorizations) < min(initializations)


def test_registered_login_callback_routes_m365_state_to_its_own_validated_flow():
    tree = ast.parse((APP / "route_frontend_authentication.py").read_text(encoding="utf-8-sig"))
    authorized = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "authorized"
    )
    first = authorized.body[0]
    assert isinstance(first, ast.If)
    assert "CHAT_AUTH_STATE_PREFIX" in ast.unparse(first.test)
    assert "complete_m365_chat_connection_callback" in ast.unparse(first)


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
