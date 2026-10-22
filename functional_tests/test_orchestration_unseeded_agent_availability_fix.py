#!/usr/bin/env python3
# test_orchestration_unseeded_agent_availability_fix.py
"""
Functional test for V2 orchestration unseeded agent availability, workflow catalog
ranking, and group chat upload attachment status sync.
Version: 0.261.378
Implemented in: 0.261.378

This test ensures that:
1. Unseeded V2 orchestration requests (including multi-capability requests that combine
   agent_invoke, action_invoke, and document_compare without pinning seeds['agent'])
   offer and execute accessible agents even when user_settings.settings.enable_agents
   is False in Cosmos DB.
2. update_user_settings() defaults missing enable_agents to True rather than False.
3. Workflow planning context (_agent_entries, _handoff_agent_entries, _source_entries)
   ranks agents and sources named in request_text first before applying the 25-entry cap.
4. sync_chat_upload_workspace_attachment_status() preserves group scope and URL for
   group workspace chat uploads.
"""

import ast
from copy import deepcopy
import importlib
import os
import sys
import types
from unittest.mock import Mock, patch

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app"))

from test_orchestration_external_sources import ExternalSourceWorld  # noqa: E402
from functions_orchestration_context import resolve_action_catalog, resolve_agent_catalog  # noqa: E402
from functions_orchestration_registry import (  # noqa: E402
    CAPABILITY_ACTION_INVOKE,
    CAPABILITY_AGENT_INVOKE,
    CAPABILITY_DOCUMENT_COMPARE,
    resolve_available_capability_ids,
)
from functions_orchestration_results import ResultUnavailableError  # noqa: E402
from test_support.orchestration_revisions import AtomicMemoryContainer  # noqa: E402
from test_support.orchestration_research import _definitions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")


def _production_catalog(world):
    builder = Mock(side_effect=lambda user_id, *, settings, user_groups=None: world.catalog(
        user_id, settings=settings,
    ))
    module = types.ModuleType("functions_agent_catalog")
    module.build_accessible_agent_catalog = builder
    module.build_agent_catalog_key = _definitions(
        "functions_agent_catalog.py", names={"build_agent_catalog_key"},
    )["build_agent_catalog_key"]
    world.stack.enter_context(patch.dict(sys.modules, {"functions_agent_catalog": module}))
    return builder


def test_version_at_least_0_261_378():
    assert_app_version_at_least("0.261.378")


def test_update_user_settings_defaults_missing_enable_agents_to_true():
    from azure.cosmos import exceptions as cosmos_exceptions

    settings_path = os.path.join(APP_ROOT, "functions_settings.py")
    tree = ast.parse(open(settings_path, encoding="utf-8-sig").read())
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "update_user_settings"
    )
    container = AtomicMemoryContainer("id")
    namespace = {
        "_authorize_user_settings_access": lambda user_id, *args, **kwargs: user_id,
        "sanitize_settings_for_logging": lambda changes: {"fields": list(changes)},
        "log_event": lambda *args, **kwargs: None,
        "cosmos_user_settings_container": container,
        "exceptions": cosmos_exceptions,
        "MatchConditions": types.SimpleNamespace(IfNotModified="if_not_modified"),
        "validate_legacy_plugin_settings_update": lambda *args, **kwargs: None,
        "get_settings": lambda: {},
        "datetime": __import__("datetime").datetime,
        "timezone": __import__("datetime").timezone,
        "_set_request_cached_user_settings": lambda *args, **kwargs: None,
        "_delete_user_ui_settings_cache": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), settings_path, "exec"), namespace)
    update_fn = namespace["update_user_settings"]

    saved = update_fn("user-1", {"orchestrationApprovalMode": "manual"})
    assert saved is True
    stored = container.read_item(item="user-1", partition_key="user-1")
    assert stored["settings"]["enable_agents"] is True


def test_request_and_execution_identity_enable_agents_for_v2_orchestration():
    route_fns = _definitions(
        "route_backend_orchestration.py", names={"_request_identity", "_text"},
    )
    route_fns.update({
        "get_current_user_info": lambda: {"email": "owner@example.com"},
        "session": {"user": {"roles": ["User"]}},
    })
    identity = route_fns["_request_identity"]("user-1", seeded_agent=None)
    assert identity == {
        "user_email": "owner@example.com",
        "user_roles": ["User"],
        "user_enable_agents": True,
    }

    bootstrap_fns = _definitions(
        "functions_orchestration_bootstrap.py", names={"current_execution_identity"},
    )
    bootstrap_fns.update({
        "read_owned_conversation": lambda user_id, conversation_id: {"id": conversation_id, "user_id": user_id},
        "capture_execution_identity": lambda user_id, conversation_id: types.SimpleNamespace(
            roles=("User",), email="owner@example.com",
        ),
    })
    exec_identity = bootstrap_fns["current_execution_identity"]("user-1", "conv-1", seeded_agent=None)
    assert exec_identity == {
        "user_roles": ["User"],
        "user_email": "owner@example.com",
        "user_enable_agents": True,
    }


def test_unseeded_multi_capability_turn_offers_and_runs_agent_when_classic_preference_is_off():
    """Reproduces the FED-19 failure: unseeded agent_invoke + action_invoke + document_compare."""
    with ExternalSourceWorld("agent_invoke") as world:
        _production_catalog(world)
        world.services.add_agent(
            "policy-agent-id", scope="personal", scope_id="owner",
            name="FED-19-policy-agent",
        )
        world.run["plan"]["steps"][0]["arguments"] = {
            "agent_name": "FED-19-policy-agent",
            "task": "Check the assigned policy.",
        }
        world.agent_selector = "personal:owner:policy-agent-id"
        world.run["seeds"] = {
            "model_routing": "auto",
            "document_ids": ["doc-v1", "doc-v2"],
            "agent": None,
            "active_group_ids": ["group-a"],
        }
        world.user_enable_agents = False

        # 1. Both agent_catalog and action_catalog resolve when seeds['agent'] is None.
        agents = resolve_agent_catalog("owner", seeds=world.run["seeds"], settings=world.settings)
        assert any(agent["name"] == "FED-19-policy-agent" for agent in agents)

        action_module = types.ModuleType("functions_action_catalog")
        action_module.build_accessible_action_catalog = lambda *args, **kwargs: [
            {"id": "grants-id", "name": "FED-19-grants", "action_ref": world.action_selector},
        ]
        with patch.dict(sys.modules, {"functions_action_catalog": action_module}):
            actions = resolve_action_catalog(
                "owner", seeds=world.run["seeds"], settings=world.settings, user_roles=["User"],
            )
        assert len(actions) == 1

        # 2. Capability resolution offers agent_invoke, action_invoke, and document_compare together.
        available = resolve_available_capability_ids(
            world.settings,
            allowed_ids=world.settings.get("chat_orchestration_enabled_capabilities"),
            candidate_ids=(CAPABILITY_AGENT_INVOKE, CAPABILITY_ACTION_INVOKE),
            request_context={
                "user_id": "owner",
                "user_roles": ["User"],
                "user_enable_agents": True,
                "agent_catalog": agents,
                "action_catalog": actions,
                "external_source_admission": lambda **kwargs: {},
                "external_source_preflight": lambda **kwargs: None,
                "capture_external_source_configuration": lambda *args, **kwargs: None,
                "external_source_authorizer": lambda *args, **kwargs: None,
            },
        )
        assert set(available) == {CAPABILITY_AGENT_INVOKE, CAPABILITY_ACTION_INVOKE}

        # 3. External source preflight, admission, and read succeed even with user_enable_agents=False.
        current = world.provider(agent_catalog_reader=resolve_agent_catalog)
        world.preflight(current)
        current.preflight_session_acquisition(
            "agent", producer=world.fixture.producer, selector=world.agent_selector,
        )
        admitted = world.admit(current)
        assert len(admitted) == 1
        output = world.persist(world.service(current, admitted), admitted).output("prepared")
        reopened = world.service(world.provider(agent_catalog_reader=resolve_agent_catalog)).open_result(
            output, require_current_sources=True,
        ).read_value()
        assert reopened == world.prepared


def test_workflow_planning_ranks_named_agents_and_sources_before_25_item_cap():
    wf_context = importlib.import_module("functions_orchestration_workflow_context")
    agents = [
        {
            "id": f"agent-id-{idx:02d}",
            "name": f"FED-batch-{idx:02d}-agent",
            "display_name": f"FED-batch-{idx:02d}-agent",
            "description": "Synthetic agent",
            "is_enabled": True,
            "user_id": "owner",
            "agent_type": "local",
            "actions_to_load": [],
        }
        for idx in range(35)
    ]
    target_agent_name = "FED-batch-34-agent"

    sources = [
        {
            "source_id": f"source-id-{idx:02d}",
            "name": f"FED-source-{idx:02d}",
            "source_type": "azure_files",
            "scope_type": "personal",
            "scope_id": "owner",
            "enabled": True,
        }
        for idx in range(30)
    ]
    target_source_name = "FED-source-29"

    settings = {
        "enable_chat_orchestration": True,
        "allow_user_workflows": True,
        "enable_chat_orchestration_workflows": True,
        "enable_chat_orchestration_workflow_runs": True,
        "enable_chat_workflow_results": True,
        "enable_chat_orchestration_workflow_handoff": True,
        "enable_semantic_kernel": True,
        "allow_user_agents": True,
        "enable_user_workspace": True,
    }
    readers = {
        "personal_agents": lambda _user_id: deepcopy(agents),
        "global_agents": lambda: [],
        "actions": lambda _scope, _id: [],
        "govern": lambda _user_id, _scope, items: items,
        "sources": lambda _user_id, _settings, _info: deepcopy(sources),
        "workflows": lambda _user_id: [],
        "wait_workflows": lambda _user_id, _ids: [],
        "quota_count": lambda _user_id: 0,
        "max_tasks": lambda _settings: 5,
        "default_model": lambda _settings: True,
    }
    conversation = {"id": "conv-1", "user_id": "owner"}
    prompt = f"Have {target_agent_name} check the policy and monitor {target_source_name}."

    settings_stub = types.ModuleType("functions_settings")
    settings_stub.is_user_workflows_enabled_for_user = lambda *_args, **_kwargs: True
    settings_stub.is_chat_workflow_results_enabled_for_user = lambda *_args, **_kwargs: True
    with patch.dict(sys.modules, {"functions_settings": settings_stub}):
        context = wf_context.build_workflow_planning_context(
            settings,
            user_id="owner",
            user_info={"userId": "owner", "roles": ["User"]},
            conversation=conversation,
            readers=readers,
            request_text=prompt,
        )

    catalog_agent_names = [entry["name"] for entry in context["catalog"]["agents"]]
    handoff_agent_names = [entry["name"] for entry in context["workflow_handoff"]["catalog"]["agents"]]
    catalog_source_names = [entry["name"] for entry in context["catalog"]["sources"]]

    assert len(catalog_agent_names) == wf_context.CATALOG_MAX_AGENTS
    assert catalog_agent_names[0] == target_agent_name
    assert handoff_agent_names[0] == target_agent_name
    assert len(catalog_source_names) == wf_context.CATALOG_MAX_SOURCES
    assert catalog_source_names[0] == target_source_name


def test_sync_chat_upload_workspace_attachment_status_preserves_group_scope():
    fns = _definitions("functions_documents.py", names={"sync_chat_upload_workspace_attachment_status"})
    container = AtomicMemoryContainer("conversation_id")
    container.upsert_item({
        "id": "msg-group",
        "conversation_id": "conv-1",
        "workspace_document_id": "doc-group-1",
        "metadata": {
            "workspace_attachment": {
                "document_id": "doc-group-1",
                "scope": "group",
                "group_id": "group-123",
                "group_name": "Civic Bridge",
                "workspace_url": "/group_workspaces?document_id=doc-group-1&group_id=group-123",
            },
        },
    })
    container.upsert_item({
        "id": "msg-personal",
        "conversation_id": "conv-1",
        "workspace_document_id": "doc-personal-1",
        "metadata": {},
    })

    fns["cosmos_messages_container"] = container
    fns["log_event"] = lambda *args, **kwargs: None
    sync_fn = fns["sync_chat_upload_workspace_attachment_status"]

    ok_group = sync_fn({
        "id": "doc-group-1",
        "created_from_chat_upload": True,
        "conversation_id": "conv-1",
        "chat_message_id": "msg-group",
        "file_name": "policy-v1.md",
        "status": "Processing complete",
        "percentage_complete": 100,
        "tags": ["conversations"],
        "group_id": "group-123",
    })
    assert ok_group is True
    group_msg = container.read_item(item="msg-group", partition_key="conv-1")
    group_att = group_msg["metadata"]["workspace_attachment"]
    assert group_att["scope"] == "group"
    assert group_att["group_id"] == "group-123"
    assert group_att["group_name"] == "Civic Bridge"
    assert group_att["workspace_url"] == "/group_workspaces?document_id=doc-group-1&group_id=group-123"

    ok_personal = sync_fn({
        "id": "doc-personal-1",
        "created_from_chat_upload": True,
        "conversation_id": "conv-1",
        "chat_message_id": "msg-personal",
        "file_name": "notes.md",
        "status": "Processing complete",
        "percentage_complete": 100,
        "tags": ["conversations"],
    })
    assert ok_personal is True
    personal_msg = container.read_item(item="msg-personal", partition_key="conv-1")
    personal_att = personal_msg["metadata"]["workspace_attachment"]
    assert personal_att["scope"] == "personal"
    assert personal_att["group_id"] is None
    assert personal_att["workspace_url"] == "/workspace?document_id=doc-personal-1"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
