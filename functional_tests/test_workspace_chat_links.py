# test_workspace_chat_links.py
"""
Functional tests for workspace chat launch links.
Version: 0.261.483
Implemented in: 0.261.473
Whole-workspace and reasoning support: 0.261.474

These tests verify strict configuration capture, selectable lifetimes, exact
recipient authorization, send-time binding, and creator/admin revocation.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cosmos._cosmos_responses import CosmosDict


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
ROOT_DIR = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
REFERENCE_A = "ABCDEFGHIJKLMNOPQRSTUV"
REFERENCE_B = "WXYZ0123456789abcdefgh"


class FakePages:
    def __init__(self, rows, continuation_token=None):
        self.rows = rows
        self.continuation_token = continuation_token
        self._read = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._read:
            raise StopIteration
        self._read = True
        self.continuation_token = None
        return [dict(row) for row in self.rows]


class FakeQuery:
    def __init__(self, rows, continuation_token=None):
        self.rows = rows
        self.continuation_token = continuation_token

    def by_page(self, continuation_token=None):
        assert continuation_token in (None, self.continuation_token)
        return FakePages(self.rows, self.continuation_token)


class FakeChatLinkContainer:
    def __init__(self):
        self.items = {}
        self.create_count = 0
        self.query_token = None
        self.last_query = None

    def create_item(self, body):
        from azure.cosmos.exceptions import CosmosResourceExistsError

        self.create_count += 1
        if body["id"] in self.items:
            raise CosmosResourceExistsError(message="Collision")
        self.items[body["id"]] = dict(body)
        return CosmosDict(body, response_headers={})

    def read_item(self, item, partition_key):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        assert item == partition_key
        if item not in self.items:
            raise CosmosResourceNotFoundError(message="Missing")
        return CosmosDict(self.items[item], response_headers={})

    def delete_item(self, item, partition_key):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        assert item == partition_key
        if item not in self.items:
            raise CosmosResourceNotFoundError(message="Missing")
        del self.items[item]

    def query_items(self, **kwargs):
        self.last_query = kwargs
        rows = list(self.items.values())
        parameters = {
            item["name"]: item["value"]
            for item in kwargs.get("parameters", [])
        }
        owner = parameters.get("@created_by_user_id")
        if owner:
            rows = [row for row in rows if row["created_by_user_id"] == owner]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return FakeQuery(rows, self.query_token)


def dependency(monkeypatch, name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def chat_links(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_DIR))
    monkeypatch.delitem(sys.modules, "functions_chat_links", raising=False)
    container = FakeChatLinkContainer()
    settings = {
        "enable_user_workspace": True,
        "enable_group_workspaces": True,
        "enable_public_workspaces": True,
    }
    dependency(monkeypatch, "config", cosmos_chat_links_container=container)
    @contextmanager
    def strict_source_authority():
        yield

    access = dependency(monkeypatch, "content_screening.access")
    access.strict_source_authority = strict_source_authority
    contracts = dependency(monkeypatch, "content_screening.contracts")
    for name in (
        "DocumentHeldError",
        "ScreeningConflictError",
        "SourceAuthorityUnavailableError",
        "SourceAuthorityUnverifiedError",
    ):
        setattr(contracts, name, type(name, (Exception,), {}))

    agents = {
        "global:global:agent-1": {
            "id": "agent-1",
            "name": "Planner",
            "display_name": "Planner",
            "catalog_key": "global:global:agent-1",
            "scope_type": "global",
            "scope_id": None,
            "assigned_knowledge": {"enabled": False},
        }
    }
    dependency(
        monkeypatch,
        "functions_agent_catalog",
        build_accessible_agent_catalog=lambda user_id, **kwargs: list(agents.values()),
        build_agent_catalog_key=lambda agent: str(agent.get("catalog_key") or ""),
        is_chat_agent_allowed_by_governance=lambda *args, **kwargs: True,
    )
    dependency(monkeypatch, "functions_appinsights", log_event=Mock())
    dependency(
        monkeypatch,
        "functions_chat_model_catalog",
        build_chat_model_catalog=lambda **kwargs: [{
            "selection_key": "global:global:endpoint-1:model-1",
            "display_name": "Example model",
            "deployment_name": "deployment-1",
            "model_id": "model-1",
            "endpoint_id": "endpoint-1",
            "provider": "aoai",
            "scope_type": "global",
            "scope_id": "global",
            "reasoning_capabilities": {
                "status": "supported",
                "efforts": ["low", "medium", "high"],
                "default_effort": "medium",
            },
        }],
    )
    dependency(
        monkeypatch,
        "functions_document_source_discovery",
        source_catalog=lambda *args, **kwargs: [
            {"kind": "personal", "id": None, "name": "My workspace"},
            {"kind": "group", "id": "group-1", "name": "Policy team"},
            {"kind": "public", "id": "public-1", "name": "Policy library"},
        ],
        admit_document_source_selection=lambda value, *args, **kwargs: (value, value["sources"]),
    )
    dependency(monkeypatch, "functions_group", get_user_groups=lambda user_id: [
        {"id": "group-1", "name": "Policy team"},
    ])
    dependency(
        monkeypatch,
        "functions_settings",
        get_settings=lambda: settings,
        get_user_settings=lambda user_id: {"settings": {}},
    )
    module = importlib.import_module("functions_chat_links")
    return SimpleNamespace(
        module=module,
        container=container,
        agents=agents,
        settings=settings,
    )


def payload(lifetime_days=90):
    return {
        "routing": {
            "kind": "agent",
            "selection_key": "global:global:agent-1",
        },
        "workspace": {"kind": "personal"},
        "document_source_selection": {
            "version": 1,
            "mode": "selected",
            "sources": [{
                "kind": "document",
                "id": "document-1",
                "scope": {"kind": "personal"},
            }],
        },
        "lifetime_days": lifetime_days,
        "reasoning_effort": None,
    }


def test_chat_link_contract_is_exact_and_lifetime_is_explicit(chat_links):
    normalized = chat_links.module.normalize_chat_link_configuration(payload())
    assert normalized["lifetime_days"] == 90
    assert normalized["document_source_selection"]["mode"] == "selected"
    assert chat_links.module.normalize_chat_link_configuration(
        payload(None)
    )["lifetime_days"] is None

    for invalid in (
        {"version": 1, "mode": "all", "sources": []},
        {
            "version": 1,
            "mode": "selected",
            "sources": [{
                "kind": "tag",
                "tag": "policy",
                "scope": {"kind": "personal"},
            }],
        },
    ):
        value = payload()
        value["document_source_selection"] = invalid
        with pytest.raises(chat_links.module.ChatLinkValidationError):
            chat_links.module.normalize_chat_link_configuration(value)

    mixed = payload()
    mixed["document_source_selection"]["sources"].append({
        "kind": "document",
        "id": "document-2",
        "scope": {"kind": "group", "id": "group-1"},
    })
    with pytest.raises(chat_links.module.ChatLinkValidationError):
        chat_links.module.normalize_chat_link_configuration(mixed)


@pytest.mark.parametrize("workspace", [
    {"kind": "personal"},
    {"kind": "group", "id": "group-1"},
    {"kind": "public", "id": "public-1"},
])
def test_whole_workspace_sources_are_allowed(chat_links, workspace, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(return_value=REFERENCE_A),
    )
    value = payload()
    value["workspace"] = workspace
    value["document_source_selection"] = {
        "version": 1,
        "mode": "selected",
        "sources": [{
            "kind": "workspace",
            "scope": workspace,
        }],
    }
    normalized = chat_links.module.normalize_chat_link_configuration(value)
    assert normalized["document_source_selection"]["sources"] == [{
        "kind": "workspace",
        "scope": workspace,
    }]
    created = chat_links.module.create_chat_link(
        "creator-1",
        value,
        now=FIXED_NOW,
    )
    assert created["projection"]["workspace"]["kind"] == workspace["kind"]
    assert created["projection"]["all_documents"] is True


def test_creation_uses_opaque_reference_and_selected_lifetime(chat_links, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(side_effect=[REFERENCE_A, REFERENCE_B]),
    )
    created = chat_links.module.create_chat_link(
        "creator-1",
        payload(90),
        now=FIXED_NOW,
    )
    record = chat_links.container.items[REFERENCE_A]
    assert record["id"] == REFERENCE_A
    assert record["ttl"] == 90 * 24 * 60 * 60
    assert record["expires_at"] == "2027-02-22T12:00:00Z"
    assert created["projection"]["document_count"] == 1
    assert "instructions" not in created["projection"]

    never = chat_links.module.create_chat_link(
        "creator-1",
        payload(None),
        now=FIXED_NOW,
    )
    record = chat_links.container.items[REFERENCE_B]
    assert record["expires_at"] is None and "ttl" not in record
    assert never["projection"]["lifetime_days"] is None


def test_whole_workspace_projection_reports_all_documents(chat_links, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(return_value=REFERENCE_A),
    )
    value = payload()
    value["document_source_selection"] = {
        "version": 1,
        "mode": "selected",
        "sources": [{
            "kind": "workspace",
            "scope": {"kind": "personal"},
        }],
    }
    created = chat_links.module.create_chat_link(
        "creator-1",
        value,
        now=FIXED_NOW,
    )
    assert created["projection"]["all_documents"] is True
    assert created["projection"]["document_count"] is None
    assert created["projection"]["reasoning_effort"] is None


def test_reference_collision_retries_without_reusing_an_item(chat_links, monkeypatch):
    chat_links.container.items[REFERENCE_A] = {"id": REFERENCE_A}
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(side_effect=[REFERENCE_A, REFERENCE_B]),
    )
    created = chat_links.module.create_chat_link(
        "creator-1",
        payload(),
        now=FIXED_NOW,
    )
    assert created["record"]["id"] == REFERENCE_B
    assert chat_links.container.items[REFERENCE_A] == {"id": REFERENCE_A}


def test_expiry_and_missing_permission_are_fail_closed(chat_links):
    chat_links.container.items[REFERENCE_A] = {
        "id": REFERENCE_A,
        "record_type": chat_links.module.CHAT_LINK_RECORD_TYPE,
        "schema_version": chat_links.module.CHAT_LINK_SCHEMA_VERSION,
        "created_by_user_id": "creator-1",
        "created_at": "2026-11-01T00:00:00Z",
        "expires_at": "2026-11-02T00:00:00Z",
        "ttl": 86400,
        **payload(1),
    }
    # One-day is intentionally not a supported stored lifetime.
    with pytest.raises(chat_links.module.ChatLinkUnavailableError):
        chat_links.module.resolve_chat_link(
            REFERENCE_A,
            "recipient-1",
            now=FIXED_NOW,
        )

    valid = chat_links.module.create_chat_link(
        "creator-1",
        {**payload(90), "lifetime_days": 90},
        now=FIXED_NOW,
        container=chat_links.container,
    )
    chat_links.agents.clear()
    with pytest.raises(chat_links.module.ChatLinkPermissionError):
        chat_links.module.resolve_chat_link(
            valid["record"]["id"],
            "recipient-1",
        )


def test_exact_configuration_is_bound_again_at_send_time(chat_links, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(return_value=REFERENCE_A),
    )
    created = chat_links.module.create_chat_link(
        "creator-1",
        payload(),
        now=FIXED_NOW,
    )
    request = {
        **payload(),
        "chat_link_reference": created["record"]["id"],
        "agent_info": {
            "catalog_key": "global:global:agent-1",
            "id": "agent-1",
            "name": "Planner",
            "is_global": True,
            "is_group": False,
        },
    }
    request.pop("routing")
    request.pop("workspace")
    request.pop("lifetime_days")
    assert chat_links.module.authorize_chat_link_request(
        request,
        "creator-1",
    )["record"]["id"] == created["record"]["id"]

    request["document_source_selection"]["sources"][0]["id"] = "document-2"
    with pytest.raises(chat_links.module.ChatLinkConflictError):
        chat_links.module.authorize_chat_link_request(request, "creator-1")


def test_model_link_requires_the_exact_multi_endpoint_identity(chat_links, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(return_value=REFERENCE_A),
    )
    value = payload()
    value["routing"] = {
        "kind": "model",
        "selection_key": "global:global:endpoint-1:model-1",
    }
    value["reasoning_effort"] = "high"
    created = chat_links.module.create_chat_link(
        "creator-1",
        value,
        now=FIXED_NOW,
    )
    assert created["record"]["reasoning_effort"] == "high"
    assert created["record"]["_reasoning_effort_bound"] is True
    request = {
        "chat_link_reference": created["record"]["id"],
        "document_source_selection": value["document_source_selection"],
        "agent_info": None,
        "model_deployment": "deployment-1",
        "model_id": "model-1",
        "model_endpoint_id": "endpoint-1",
        "model_provider": "aoai",
        "model_scope_type": "global",
        "model_scope_id": "global",
        "reasoning_effort": "high",
    }
    chat_links.module.authorize_chat_link_request(request, "creator-1")
    request["model_endpoint_id"] = "endpoint-2"
    with pytest.raises(chat_links.module.ChatLinkConflictError):
        chat_links.module.authorize_chat_link_request(request, "creator-1")

    request["model_endpoint_id"] = "endpoint-1"
    request["reasoning_effort"] = "medium"
    with pytest.raises(chat_links.module.ChatLinkConflictError):
        chat_links.module.authorize_chat_link_request(request, "creator-1")


def test_model_link_rejects_an_unsupported_reasoning_effort(chat_links):
    value = payload()
    value["routing"] = {
        "kind": "model",
        "selection_key": "global:global:endpoint-1:model-1",
    }
    value["reasoning_effort"] = "xhigh"
    with pytest.raises(chat_links.module.ChatLinkValidationError):
        chat_links.module.create_chat_link(
            "creator-1",
            value,
            now=FIXED_NOW,
        )


def test_legacy_link_without_reasoning_remains_readable(chat_links, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(return_value=REFERENCE_A),
    )
    created = chat_links.module.create_chat_link(
        "creator-1",
        payload(),
        now=FIXED_NOW,
    )
    legacy = dict(chat_links.container.items[REFERENCE_A])
    legacy.pop("reasoning_effort")
    chat_links.container.items[REFERENCE_A] = legacy

    resolved = chat_links.module.resolve_chat_link(
        created["record"]["id"],
        "creator-1",
    )
    assert resolved["record"]["reasoning_effort"] is None
    assert resolved["record"]["_reasoning_effort_bound"] is False
    assert resolved["projection"]["reasoning_effort_bound"] is False


def test_owner_and_control_center_revocation_are_object_checked(chat_links, monkeypatch):
    references = iter((REFERENCE_A, REFERENCE_B))
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        lambda length: next(references),
    )
    first = chat_links.module.create_chat_link("creator-1", payload(), now=FIXED_NOW)
    second = chat_links.module.create_chat_link("creator-1", payload(None), now=FIXED_NOW)

    with pytest.raises(chat_links.module.ChatLinkUnavailableError):
        chat_links.module.revoke_chat_link(first["record"]["id"], "other-user")
    chat_links.module.revoke_chat_link(first["record"]["id"], "creator-1")
    assert first["record"]["id"] not in chat_links.container.items
    chat_links.module.revoke_chat_link(
        second["record"]["id"],
        "control-center-admin",
        allow_admin=True,
    )
    assert second["record"]["id"] not in chat_links.container.items


def test_admin_listing_uses_parameterized_cross_partition_query(chat_links, monkeypatch):
    monkeypatch.setattr(
        chat_links.module.secrets,
        "token_urlsafe",
        Mock(return_value=REFERENCE_A),
    )
    chat_links.module.create_chat_link("creator-1", payload(), now=FIXED_NOW)
    result = chat_links.module.list_chat_links(now=FIXED_NOW)
    assert len(result["links"]) == 1
    assert result["links"][0]["created_by_user_id"] == "creator-1"
    assert chat_links.container.last_query["enable_cross_partition_query"] is True
    assert "@created_by_user_id" not in chat_links.container.last_query["query"]
    assert "@now" in chat_links.container.last_query["query"]
    assert chat_links.container.last_query["parameters"]


def test_storage_deployment_parity_and_backup_exclusion_are_explicit():
    config_source = (APP_DIR / "config.py").read_text(encoding="utf-8")
    bicep_source = (
        ROOT_DIR / "deployers" / "bicep" / "modules" / "cosmosDb.bicep"
    ).read_text(encoding="utf-8")
    terraform_source = (
        ROOT_DIR / "deployers" / "terraform" / "main.tf"
    ).read_text(encoding="utf-8")
    cli_source = (
        ROOT_DIR / "deployers" / "azurecli" / "deploy-simplechat.ps1"
    ).read_text(encoding="utf-8")
    generated_arm = (
        ROOT_DIR / "deployers" / "bicep" / "main.json"
    ).read_text(encoding="utf-8")
    data_management = (
        APP_DIR / "functions_data_management.py"
    ).read_text(encoding="utf-8")

    assert 'cosmos_chat_links_container_name = "chat_links"' in config_source
    assert "name: 'chat_links'" in bicep_source and "defaultTtl: -1" in bicep_source
    assert '"chat_links"' in generated_arm
    assert 'chat_links                         = { partition_key_path = "/id", default_ttl = -1 }' in terraform_source
    assert 'Name = "chat_links"; PartitionKeyPath = "/id"; DefaultTtl = -1' in cli_source
    assert '"name": "chat_links"' not in data_management


def test_control_center_and_both_chat_interfaces_keep_admin_and_launch_wiring():
    control_routes = (
        APP_DIR / "route_backend_control_center.py"
    ).read_text(encoding="utf-8")
    chat_routes = (
        APP_DIR / "route_backend_chats.py"
    ).read_text(encoding="utf-8")
    classic_template = (
        APP_DIR / "templates" / "chats.html"
    ).read_text(encoding="utf-8")
    classic_admin = (
        APP_DIR / "templates" / "control_center.html"
    ).read_text(encoding="utf-8")
    v2_composer = (
        ROOT_DIR / "application" / "v2_ui" / "src" / "components" / "chat" / "Composer.tsx"
    ).read_text(encoding="utf-8")
    v2_admin = (
        ROOT_DIR / "application" / "v2_ui" / "src" / "pages" / "ControlCenterPage.tsx"
    ).read_text(encoding="utf-8")
    classic_launch = (
        APP_DIR / "static" / "js" / "chat" / "chat-onload.js"
    ).read_text(encoding="utf-8")
    classic_requests = (
        APP_DIR / "static" / "js" / "chat" / "chat-messages.js"
    ).read_text(encoding="utf-8")
    classic_reasoning = (
        APP_DIR / "static" / "js" / "chat" / "chat-reasoning.js"
    ).read_text(encoding="utf-8")
    classic_documents = (
        APP_DIR / "static" / "js" / "chat" / "chat-documents.js"
    ).read_text(encoding="utf-8")

    assert "api_v2_control_center_chat_links" in control_routes
    assert "api_v2_control_center_revoke_chat_link" in control_routes
    assert "control_center_required('admin')" in control_routes
    assert chat_routes.count("@_with_chat_link_request") == 2
    assert 'id="create-chat-link-btn"' in classic_template
    assert 'id="chat-link-lifetime"' in classic_template
    assert 'id="chat-links-tab"' in classic_admin
    assert "ChatLinkDialog" in v2_composer and "Create chat link" in v2_composer
    assert "ChatLinksSection" in v2_admin and "'chat-links'" in v2_admin
    assert "hasActiveChatLinkBinding()" in classic_launch
    assert "getChatLinkReferenceForRequest" in classic_requests
    assert "documentActionType === DOCUMENT_ACTION_NONE" in classic_requests
    assert "selectReasoningForChatLink" in classic_reasoning
    assert "kind: 'workspace'" in classic_documents
