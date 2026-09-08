# test_prompt_variable_knowledge_fill.py
"""
Functional tests for scoped, document-grounded prompt variable filling.
Version: 0.261.102
Implemented in: 0.261.096

Execute the service with mocked retrieval/model/storage boundaries and the real
Flask route body in a test application. No Azure services or chat turns are used.
"""

import ast
from functools import wraps
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from flask import Blueprint, Flask, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from werkzeug.test import Client


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
SERVICE_PATH = APP_ROOT / "functions_prompt_variables.py"
ROUTE_PATH = APP_ROOT / "route_backend_v2.py"
USER_ID = "user-1"
PASSAGE = "Apollo project is owned by Priya Shah. Its budget is 200 dollars."
QUOTE = "Apollo project is owned by Priya Shah."


class MissingRecord(Exception):
    """Stand in for the Cosmos not-found error without importing Azure clients."""


class OpenAIStyleClientStub:
    def __init__(self, client):
        self._client = client


class AnthropicClientStub:
    def __init__(self, client):
        self.timeout = 90
        self.chat = client.chat


def _module(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


def document_context(document_id="doc-1", scope="personal", **overrides):
    document = {"id": document_id, "user_id": USER_ID, "tags": ["finance"]}
    context = {"scope": scope, "group_id": None, "public_workspace_id": None, "document": document}
    if scope == "group":
        context["group_id"] = "group-1"
        document["group_id"] = "group-1"
    elif scope == "public":
        context["public_workspace_id"] = "public-1"
        document["public_workspace_id"] = "public-1"
    document.update(overrides)
    return context


def search_result(document_id="doc-1", **overrides):
    result = {
        "document_id": document_id, "chunk_id": f"{document_id}-chunk-1",
        "chunk_text": PASSAGE, "title": "Project register", "file_name": "projects.pdf",
        "page_number": 4, "user_id": USER_ID,
    }
    result.update(overrides)
    return result


def filled_result(key="project_owner", value="Priya Shah", source_id="e1", quote=QUOTE):
    return {
        "key": key, "status": "filled", "value": value,
        "sources": [{"source_id": source_id, "quote": quote}],
    }


def request_payload(**overrides):
    data = {
        "prompt_content": "Find {{Project owner}} and {{budget}}. Draft: {{composer}}",
        "variables": [{"key": "project_owner", "name": "Project owner"}],
        "composer_text": "For Apollo",
        "selected_document_ids": ["doc-1"], "tags": [], "doc_scope": "personal",
        "active_group_ids": [], "active_public_workspace_ids": [],
        "document_filter_mode": "intersection", "search_all": False,
    }
    data.update(overrides)
    return data


def context_item(kind, item_id, scope_kind="personal", scope_id=None):
    return {"kind": kind, "id": item_id, "scope": {"kind": scope_kind, "id": scope_id}}


def scoped_payload(items, **overrides):
    kinds = list(dict.fromkeys(item["scope"]["kind"] for item in items))
    data = request_payload(
        context_items=items,
        selected_document_ids=list(dict.fromkeys(item["id"] for item in items if item["kind"] == "document")),
        tags=list(dict.fromkeys(item["id"] for item in items if item["kind"] == "tag")),
        active_group_ids=list(dict.fromkeys(item["scope"]["id"] for item in items if item["scope"]["kind"] == "group")),
        active_public_workspace_ids=list(dict.fromkeys(item["scope"]["id"] for item in items if item["scope"]["kind"] == "public")),
        doc_scope=kinds[0] if len(kinds) == 1 else "all",
        scope_selected=any(item["kind"] == "scope" for item in items),
        document_filter_mode="union" if any(item["kind"] == "document" for item in items) and any(item["kind"] == "tag" for item in items) else "intersection",
    )
    data.update(overrides)
    return data


def load_model_behavior():
    """Execute the existing provider policy without importing its SDK transport adapters."""
    path = APP_ROOT / "model_endpoint_clients.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if (
            isinstance(node, ast.ClassDef) and node.name == "ModelEndpointBehavior"
        ) or (
            isinstance(node, ast.Assign)
            and any(getattr(target, "id", None) == "OPENAI_REASONING_MODEL_PREFIXES" for target in node.targets)
        )
    ]
    namespace = {"Any": object, "__name__": "_prompt_fill_model_behavior"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["ModelEndpointBehavior"]


def load_service():
    """Import the real service, stubbing only its external dependency seams."""
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = types.SimpleNamespace(choices=[
        types.SimpleNamespace(
            finish_reason="stop",
            message=types.SimpleNamespace(
                content=json.dumps({"results": [filled_result()]}), tool_calls=None, refusal=None,
            ),
        ),
    ])
    metadata_spec = importlib.util.spec_from_file_location(
        "_prompt_fill_metadata", APP_ROOT / "functions_prompt_metadata.py",
    )
    metadata = importlib.util.module_from_spec(metadata_spec)
    metadata_spec.loader.exec_module(metadata)
    modules = {
        "functions_prompt_metadata": metadata,
        "azure.cosmos.exceptions": _module(
            "azure.cosmos.exceptions", CosmosResourceNotFoundError=MissingRecord,
        ),
        "config": _module(
            "config", cosmos_conversations_container=Mock(
                read_item=Mock(return_value={"id": "conversation-1", "user_id": USER_ID}),
            ),
        ),
        "functions_agent_delegation": _module(
            "functions_agent_delegation", resolve_delegation_agent=Mock(return_value={"id": "agent-1"}),
        ),
        "functions_appinsights": _module("functions_appinsights", log_event=Mock()),
        "functions_assigned_knowledge": _module(
            "functions_assigned_knowledge", build_assigned_knowledge_runtime_filters=Mock(return_value=None),
        ),
        "functions_collaboration": _module(
            "functions_collaboration",
            get_collaboration_conversation=Mock(return_value={"id": "shared-1", "conversation_kind": "collaborative"}),
            assert_user_can_participate_in_collaboration_conversation=Mock(return_value={}),
        ),
        "functions_group": _module(
            "functions_group", assert_group_role=Mock(return_value="User"),
            get_user_groups=Mock(return_value=[{"id": "group-1"}, {"id": "group-2"}]),
        ),
        "functions_model_endpoint_runtime": _module(
            "functions_model_endpoint_runtime",
            resolve_model_endpoint_from_context=Mock(return_value=None),
            build_model_endpoint_sync_chat_client=Mock(return_value=(client, "azure_openai")),
        ),
        "functions_orchestration_planner": _module(
            "functions_orchestration_planner", resolve_planner_client=Mock(return_value=(client, "gpt-4o")),
        ),
        "functions_public_workspaces": _module(
            "functions_public_workspaces",
            get_user_visible_public_workspace_ids_from_settings=Mock(return_value=["public-1", "public-2"]),
            find_public_workspace_by_id=Mock(side_effect=lambda workspace_id: {"id": workspace_id}),
        ),
        "functions_search": _module("functions_search", hybrid_search=Mock(return_value=[search_result()])),
        "functions_search_service": _module("functions_search_service", resolve_document_contexts=Mock()),
        "functions_settings": _module(
            "functions_settings", resolve_default_model_selection=Mock(return_value=({}, "Unavailable")),
        ),
        "model_endpoint_clients": _module(
            "model_endpoint_clients", OpenAIStyleChatCompletionClient=OpenAIStyleClientStub,
            AnthropicChatCompletionClient=AnthropicClientStub,
            ModelEndpointBehavior=load_model_behavior(),
        ),
    }
    spec = importlib.util.spec_from_file_location("_prompt_knowledge_fill_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.object(sys, "path", [str(APP_ROOT), *sys.path]):
        spec.loader.exec_module(module)
    return module, client


class PromptKnowledgeFillTests(unittest.TestCase):
    def setUp(self):
        self.service, self.client = load_service()
        self.settings = {
            "enable_user_workspace": True, "enable_group_workspaces": True,
            "enable_public_workspaces": True, "enable_file_sharing": True,
            "enable_collaborative_conversations": True,
            "gpt_model": {"selected": [{"deploymentName": "gpt-4o"}]},
        }
        self.contexts = {"doc-1": document_context()}
        self.service.resolve_document_contexts.side_effect = self.resolve_contexts

    def resolve_contexts(self, document_ids, doc_scope="all", **_kwargs):
        contexts = []
        for document_id in document_ids:
            context = self.contexts.get(document_id)
            if context and doc_scope not in ("all", context["scope"]):
                context = None
            contexts.append(context)
        return contexts

    def output(self, results):
        self.client.chat.completions.create.return_value.choices[0].message.content = json.dumps({"results": results})

    def fill(self, data=None):
        return self.service.fill_prompt_variables(data or request_payload(), USER_ID, self.settings)

    def assert_safe_error(self, data, status):
        with self.assertRaises(self.service.PromptKnowledgeFillError) as caught:
            self.fill(data)
        self.assertEqual(caught.exception.status_code, status)
        self.assertNotIn("SECRET", caught.exception.public_message)
        return caught.exception

    def test_single_fill_returns_retrieval_sources_and_never_runs_tools(self):
        result = self.fill()
        self.assertEqual(result["values"][0]["value"], "Priya Shah")
        self.assertEqual(result["values"][0]["sources"], [{
            "document_id": "doc-1", "chunk_id": "doc-1-chunk-1", "title": "Project register",
            "page_number": 4, "excerpt": QUOTE,
        }])
        self.assertEqual(result["unresolved"], [])
        search = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(search["doc_scope"], "personal")
        self.assertEqual(search["document_ids"], ["doc-1"])
        self.assertEqual(search["active_public_workspace_id"], [])
        params = self.client.chat.completions.create.call_args.kwargs
        self.assertNotIn("tools", params)
        self.assertNotIn("functions", params)
        self.assertEqual(params["max_tokens"], self.service.MAX_OUTPUT_TOKENS)
        self.client.with_options.assert_called_once_with(max_retries=0, timeout=30)
        self.client.close.assert_called_once()
        self.service.cosmos_conversations_container.read_item.assert_not_called()
        self.service.resolve_delegation_agent.assert_not_called()

    def test_batch_and_partial_results_preserve_requested_keys_and_order(self):
        fields = [{"key": "PROJECT_OWNER", "name": "Project owner"}, {"key": "budget", "name": "Budget"}]
        data = request_payload(variables=fields)
        self.output([
            filled_result(key="budget", value="200", quote="Its budget is 200 dollars."),
            filled_result(key="PROJECT_OWNER"),
        ])
        result = self.fill(data)
        self.assertEqual([item["key"] for item in result["values"]], ["PROJECT_OWNER", "budget"])
        self.output([filled_result(key="PROJECT_OWNER"), {"key": "budget", "status": "unresolved"}])
        result = self.fill(data)
        self.assertEqual([item["key"] for item in result["values"]], ["PROJECT_OWNER"])
        self.assertEqual(result["unresolved"], [{"key": "budget", "reason": self.service.NO_MATCH_REASON}])

    def test_no_results_does_not_call_model_or_widen_scope(self):
        self.service.hybrid_search.return_value = []
        result = self.fill()
        self.assertEqual(result["values"], [])
        self.assertEqual(result["unresolved"][0]["key"], "project_owner")
        self.client.chat.completions.create.assert_not_called()
        self.assertEqual(self.service.hybrid_search.call_count, 1)

    def test_conflicting_evidence_returns_grounded_alternatives(self):
        self.service.hybrid_search.return_value.append(search_result(
            chunk_id="doc-1-chunk-2", chunk_text="Apollo project is owned by Sam Lee.",
        ))
        first = filled_result()
        second = filled_result(value="Sam Lee", source_id="e2", quote="Apollo project is owned by Sam Lee.")
        self.output([{
            "key": "project_owner", "status": "conflict",
            "alternatives": [
                {"value": item["value"], "sources": item["sources"]} for item in (first, second)
            ],
        }])
        result = self.fill()
        self.assertEqual(result["values"], [])
        self.assertEqual([item["value"] for item in result["unresolved"][0]["alternatives"]], ["Priya Shah", "Sam Lee"])

    def test_malformed_requests_and_non_custom_fields_are_rejected_before_retrieval(self):
        cases = [
            [], {"prompt_content": 1}, request_payload(variables=[]),
            request_payload(variables=[{"key": "project_owner"}]),
            request_payload(variables=[{"key": "budget", "name": "Project owner"}]),
            request_payload(variables=[{"key": "other", "name": "other"}]),
            request_payload(variables=[{"key": "composer", "name": "composer"}]),
            request_payload(variables=[{"key": "project_owner", "name": "Project owner"}] * 2),
            request_payload(search_all="false"), request_payload(doc_scope="invalid"),
            request_payload(document_filter_mode="or"),
            request_payload(selected_document_ids="doc-1"),
            request_payload(selected_document_ids=[123]),
            request_payload(tags=["not a valid tag"]),
            request_payload(conversation_kind="group"),
            request_payload(agent_info="agent-1"),
            request_payload(known_values={"project_owner": "Existing manual value"}),
            request_payload(known_values={"deleted": "Old value"}),
            request_payload(doc_scope="personal", active_group_ids=["group-1"]),
            request_payload(doc_scope="group", personal_scope_selected=True),
        ]
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(self.service.PromptKnowledgeFillError) as caught:
                    self.service.fill_prompt_variables(data, USER_ID, self.settings)
                self.assertEqual(caught.exception.status_code, 400)
        self.service.hybrid_search.assert_not_called()
        self.service.resolve_planner_client.assert_not_called()

    def test_parser_ignores_code_and_escaped_fields_but_accepts_defaults(self):
        for content in (r"\{{Project owner}}", "`{{Project owner}}`", "```\n{{Project owner}}\n```", "~~~\n{{Project owner}}"):
            with self.subTest(content=content):
                self.assert_safe_error(request_payload(prompt_content=content), 400)
        self.fill(request_payload(prompt_content="{{Project owner|Unknown}} and {{project-owner}}"))

    def test_all_input_limits_fail_explicitly_without_truncating_variables(self):
        cases = [
            request_payload(prompt_content="x" * (self.service.MAX_PROMPT_CHARS + 1)),
            request_payload(composer_text="x" * (self.service.MAX_COMPOSER_CHARS + 1)),
            request_payload(variables=[{"key": "project_owner", "name": "Project owner"}] * (self.service.MAX_VARIABLES + 1)),
            request_payload(selected_document_ids=["doc-1"] * (self.service.MAX_DOCUMENT_IDS + 1)),
            request_payload(active_group_ids=["group-1"] * (self.service.MAX_SCOPE_IDS + 1), doc_scope="group"),
            request_payload(tags=["tag"] * (self.service.MAX_TAGS + 1)),
            request_payload(agent_info={"data": "x" * self.service.MAX_REQUEST_BYTES}),
        ]
        for data in cases:
            with self.subTest(field_sizes={key: len(value) for key, value in data.items() if isinstance(value, (str, list))}):
                self.assert_safe_error(data, 413)
        self.service.hybrid_search.assert_not_called()

    def test_empty_scope_never_falls_back_to_active_or_all_workspaces(self):
        for scope in ("personal", "group", "public", "all"):
            self.assert_safe_error(request_payload(selected_document_ids=[], doc_scope=scope), 400)
        self.service.resolve_document_contexts.assert_not_called()
        self.service.hybrid_search.assert_not_called()
        self.service.get_user_groups.assert_not_called()

    def test_document_resolution_cannot_add_unspecified_workspaces(self):
        for kind in ("group", "public"):
            self.contexts["doc-1"] = document_context(scope=kind)
            self.assert_safe_error(request_payload(doc_scope="all"), 403)
        self.service.hybrid_search.assert_not_called()

    def test_shared_resolver_explicit_scope_mode_preserves_legacy_default(self):
        path = APP_ROOT / "functions_search_service.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "resolve_document_contexts")
        group_resolver = Mock(return_value=["group-1"])
        public_resolver = Mock(return_value=["public-1"])
        namespace = {
            "normalize_search_scope": lambda value: value,
            "normalize_search_id_list": lambda value: value or [],
            "_resolve_active_group_ids": group_resolver,
            "_resolve_public_workspace_ids": public_resolver,
            "_resolve_personal_document_context": Mock(return_value=None),
            "_resolve_group_document_context": Mock(return_value=None),
            "_resolve_public_document_context": Mock(return_value=None),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        resolve = namespace["resolve_document_contexts"]
        self.assertEqual(resolve(["missing"], USER_ID, allow_scope_fallback=False), [None])
        group_resolver.assert_not_called()
        public_resolver.assert_not_called()
        self.assertEqual(resolve(["missing"], USER_ID), [None])
        group_resolver.assert_called_once()
        public_resolver.assert_called_once()

    def test_personal_workspace_requires_explicit_selection(self):
        self.fill(request_payload(selected_document_ids=[], scope_selected=True))
        self.service.hybrid_search.assert_called_once()
        search = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(search["doc_scope"], "personal")
        self.assertEqual(search["document_ids"], [])
        self.assertEqual(search["tags_filter"], [])
        self.assertEqual(search["active_group_ids"], [])
        self.assertEqual(search["active_public_workspace_id"], [])
        self.service.get_user_groups.assert_not_called()
        self.assert_safe_error(request_payload(selected_document_ids=[], doc_scope="group", tags=["finance"]), 403)

    def test_group_only_tags_never_include_personal_or_public_knowledge(self):
        self.contexts["doc-1"] = document_context(scope="group")
        self.service.hybrid_search.return_value = [search_result(group_id="group-1")]
        result = self.fill(request_payload(
            selected_document_ids=[], tags=["finance"], doc_scope="group",
            active_group_ids=["group-1"], scope_selected=False,
        ))
        self.assertEqual(result["values"][0]["value"], "Priya Shah")
        self.service.hybrid_search.assert_called_once()
        search = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(search["doc_scope"], "group")
        self.assertEqual(search["tags_filter"], ["finance"])
        self.assertEqual(search["document_ids"], [])
        self.assertEqual(search["active_group_ids"], ["group-1"])
        self.assertEqual(search["active_public_workspace_id"], [])
        self.service.get_user_groups.assert_not_called()
        self.service.assert_group_role.assert_called_with(
            USER_ID, "group-1", allowed_roles=self.service.GROUP_READ_ROLES,
        )

    def test_unauthorized_personal_and_pending_or_disabled_shares_are_rejected(self):
        for sharing, shared_ids in (
            (True, []), (True, [f"{USER_ID},pending"]), (False, [f"{USER_ID},approved"]),
        ):
            self.settings["enable_file_sharing"] = sharing
            self.contexts["doc-1"] = document_context(user_id="other-user", shared_user_ids=shared_ids)
            self.assert_safe_error(request_payload(), 403)
        self.service.hybrid_search.assert_not_called()
        self.client.chat.completions.create.assert_not_called()

    def test_approved_personal_share_is_allowed_only_after_metadata_check(self):
        self.contexts["doc-1"] = document_context(user_id="other-user", shared_user_ids=[f"{USER_ID},approved"])
        self.service.hybrid_search.return_value = [search_result(user_id="other-user")]
        self.assertEqual(self.fill()["values"][0]["value"], "Priya Shah")
        self.assertTrue(self.service.hybrid_search.call_args.kwargs["enable_file_sharing"])

    def test_revoked_access_in_cached_retrieval_is_not_sent_to_model(self):
        self.service.resolve_document_contexts.side_effect = [
            [document_context()], [None],
        ]
        self.assert_safe_error(request_payload(), 403)
        self.client.chat.completions.create.assert_not_called()

    def test_group_scope_membership_is_revalidated_even_for_active_ids(self):
        self.service.assert_group_role.side_effect = PermissionError("SECRET membership")
        self.assert_safe_error(request_payload(
            selected_document_ids=[], doc_scope="group", active_group_ids=["group-1"],
        ), 403)
        self.service.hybrid_search.assert_not_called()

    def test_pending_group_shares_and_disabled_group_sharing_are_rejected(self):
        for sharing, status in ((True, "pending"), (False, "approved")):
            self.settings["enable_file_sharing"] = sharing
            self.contexts["doc-1"] = document_context(
                scope="group", group_id="owner-group", shared_group_ids=[f"group-1,{status}"],
            )
            self.assert_safe_error(request_payload(doc_scope="group", active_group_ids=["group-1"]), 403)
        self.service.hybrid_search.assert_not_called()

    def test_approved_group_share_requires_current_recipient_membership(self):
        self.contexts["doc-1"] = document_context(
            scope="group", group_id="owner-group", shared_group_ids=["group-1,approved"],
        )
        self.service.hybrid_search.return_value = [search_result(group_id="owner-group")]
        result = self.fill(request_payload(doc_scope="group", active_group_ids=["group-1"]))
        self.assertEqual(result["values"][0]["sources"][0]["group_id"], "owner-group")
        self.service.assert_group_role.assert_called_with(USER_ID, "group-1", allowed_roles=self.service.GROUP_READ_ROLES)

    def test_pending_share_cannot_hide_access_through_another_selected_group(self):
        path = APP_ROOT / "functions_search_service.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {"resolve_document_contexts", "_resolve_group_document_context"}
        namespace = {
            "normalize_search_scope": lambda value: value,
            "normalize_search_id_list": lambda value: value or [],
            "_resolve_active_group_ids": lambda _user, active_group_ids=None, **_kwargs: active_group_ids or [],
            "_resolve_public_workspace_ids": lambda _user, **_kwargs: [],
            "_resolve_personal_document_context": Mock(return_value=None),
            "_resolve_public_document_context": Mock(return_value=None),
        }
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        document = document_context(
            scope="group", group_id="group-2", shared_group_ids=["group-1,pending"],
        )["document"]
        namespace["get_document_record"] = Mock(return_value=document)
        self.service.resolve_document_contexts.side_effect = namespace["resolve_document_contexts"]
        self.service.hybrid_search.return_value = [search_result(group_id="group-2")]
        for groups in (["group-1", "group-2"], ["group-2", "group-1"]):
            with self.subTest(groups=groups):
                result = self.fill(scoped_payload([
                    context_item("scope", group, "group", group) for group in groups
                ]))
                self.assertEqual(result["values"][0]["value"], "Priya Shah")
                self.assertEqual(result["values"][0]["sources"][0]["group_id"], "group-2")
        self.assert_safe_error(scoped_payload([
            context_item("scope", "group-1", "group", "group-1"),
        ]), 403)

    def test_invisible_missing_and_disabled_public_workspaces_are_rejected(self):
        data = request_payload(selected_document_ids=[], doc_scope="public", active_public_workspace_ids=["hidden"])
        self.assert_safe_error(data, 403)
        data["active_public_workspace_ids"] = ["public-1"]
        self.service.find_public_workspace_by_id.return_value = None
        self.service.find_public_workspace_by_id.side_effect = None
        self.assert_safe_error(data, 403)
        self.service.find_public_workspace_by_id.return_value = {"id": "public-1"}
        self.settings["enable_public_workspaces"] = False
        self.assert_safe_error(data, 403)
        self.service.hybrid_search.assert_not_called()

    def test_multiple_workspaces_union_filters_and_no_personal_widening(self):
        self.contexts = {
            "doc-1": document_context(scope="group"),
            "tag-doc": document_context("tag-doc", scope="public"),
        }
        self.service.hybrid_search.side_effect = [
            [search_result(group_id="group-1")],
            [search_result("tag-doc", public_workspace_id="public-1")],
        ]
        result = self.fill(scoped_payload([
            context_item("tag", "finance", "group", "group-1"),
            context_item("tag", "finance", "group", "group-2"),
            context_item("tag", "finance", "public", "public-1"),
            context_item("tag", "finance", "public", "public-2"),
        ], document_filter_mode="union"))
        self.assertEqual(result["values"][0]["value"], "Priya Shah")
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual([call["doc_scope"] for call in calls], ["group", "public"])
        self.assertEqual(calls[0]["active_group_ids"], ["group-1", "group-2"])
        self.assertEqual(calls[1]["active_public_workspace_id"], ["public-1", "public-2"])
        for call in calls:
            self.assertEqual(call["document_filter_mode"], "union")
            self.assertEqual(call["document_ids"], [])
            self.assertEqual(call["tags_filter"], ["finance"])
            self.assertTrue(call["enforce_public_workspace_visibility"])

    def test_flat_mixed_tags_are_rejected_rather_than_applied_to_every_workspace(self):
        self.assert_safe_error(request_payload(
            doc_scope="all", tags=["finance"], active_group_ids=["group-1"],
        ), 400)
        self.assert_safe_error(request_payload(
            selected_document_ids=[], doc_scope="group", tags=["finance"],
            active_group_ids=["group-1", "group-2"],
        ), 400)
        self.service.hybrid_search.assert_not_called()
        self.service.resolve_planner_client.assert_not_called()

    def test_scoped_tags_cannot_widen_document_selection_in_another_group(self):
        second_group = document_context("tag-doc", scope="group", group_id="group-2")
        second_group["group_id"] = "group-2"
        self.contexts = {
            "doc-1": document_context(scope="group", tags=[]),
            "unselected": document_context("unselected", scope="group"),
            "tag-doc": second_group,
        }
        self.service.hybrid_search.side_effect = [
            [
                search_result(group_id="group-1"),
                search_result("unselected", group_id="group-1", chunk_text="WRONG-WORKSPACE-TAG evidence."),
            ],
            [search_result("tag-doc", group_id="group-2")],
        ]
        self.fill(scoped_payload([
            context_item("document", "doc-1", "group", "group-1"),
            context_item("tag", "finance", "group", "group-2"),
        ]))
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual(calls[0]["active_group_ids"], ["group-1"])
        self.assertEqual(calls[0]["document_ids"], ["doc-1"])
        self.assertEqual(calls[0]["tags_filter"], [])
        self.assertEqual(calls[1]["active_group_ids"], ["group-2"])
        self.assertEqual(calls[1]["document_ids"], [])
        self.assertEqual(calls[1]["tags_filter"], ["finance"])
        self.assertNotIn("WRONG-WORKSPACE-TAG", json.dumps(self.client.chat.completions.create.call_args.kwargs))

    def test_different_workspace_tags_are_not_globally_intersected(self):
        first = document_context(scope="group", tags=["alpha"])
        second = document_context("doc-2", scope="group", group_id="group-2", tags=["beta"])
        second["group_id"] = "group-2"
        self.contexts = {"doc-1": first, "doc-2": second}
        self.service.hybrid_search.side_effect = [
            [search_result(group_id="group-1")], [search_result("doc-2", group_id="group-2")],
        ]
        self.fill(scoped_payload([
            context_item("tag", "alpha", "group", "group-1"),
            context_item("tag", "beta", "group", "group-2"),
        ]))
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual([call["tags_filter"] for call in calls], [["alpha"], ["beta"]])
        self.assertEqual([call["active_group_ids"] for call in calls], [["group-1"], ["group-2"]])

    def test_document_and_tag_union_is_preserved_within_one_scoped_workspace(self):
        self.contexts["doc-1"] = document_context(scope="group", tags=[])
        self.service.hybrid_search.return_value = [search_result(group_id="group-1")]
        self.fill(scoped_payload([
            context_item("document", "doc-1", "group", "group-1"),
            context_item("tag", "finance", "group", "group-1"),
        ]))
        params = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(params["document_ids"], ["doc-1"])
        self.assertEqual(params["tags_filter"], ["finance"])
        self.assertEqual(params["document_filter_mode"], "union")

    def test_personal_whole_workspace_chip_remains_unfiltered_in_mixed_selection(self):
        self.contexts["doc-2"] = document_context("doc-2", scope="group")
        self.service.hybrid_search.side_effect = [
            [search_result()], [search_result("doc-2", group_id="group-1")],
        ]
        self.fill(scoped_payload([
            context_item("scope", ""),
            context_item("document", "doc-2", "group", "group-1"),
        ]))
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual([call["doc_scope"] for call in calls], ["personal", "group"])
        self.assertEqual(calls[0]["document_ids"], [])
        self.assertEqual(calls[1]["document_ids"], ["doc-2"])

    def test_one_whole_workspace_chip_does_not_remove_another_workspaces_tag_filter(self):
        self.contexts["doc-1"] = document_context(scope="group", tags=[])
        self.contexts["public-doc"] = document_context("public-doc", scope="public")
        self.service.hybrid_search.side_effect = [
            [search_result(group_id="group-1")],
            [search_result("public-doc", public_workspace_id="public-1")],
        ]
        self.fill(scoped_payload([
            context_item("scope", "group-1", "group", "group-1"),
            context_item("tag", "finance", "public", "public-1"),
        ]))
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual([call["tags_filter"] for call in calls], [[], ["finance"]])
        self.assertEqual(calls[0]["active_group_ids"], ["group-1"])
        self.assertEqual(calls[1]["active_public_workspace_id"], ["public-1"])

    def test_scoped_context_validation_rejects_empty_inconsistent_or_invalid_items(self):
        cases = [
            request_payload(context_items=[]),
            request_payload(context_items={}),
            request_payload(context_items=[context_item("invalid", "doc-1")]),
            scoped_payload([context_item("tag", "finance", "group", None)]),
            scoped_payload([context_item("tag", "finance", "personal", "other-user")]),
            scoped_payload([context_item("scope", "wrong-id", "group", "group-1")]),
            scoped_payload([context_item("tag", "invalid tag", "group", "group-1")]),
            scoped_payload([context_item("tag", "finance", "group", "group-1")], active_group_ids=["group-2"]),
            scoped_payload([context_item("document", "doc-1")], selected_document_ids=["other-document"]),
            scoped_payload([context_item("tag", "finance")], tags=["different"]),
            scoped_payload([context_item("scope", "")], scope_selected=False),
            scoped_payload([context_item("tag", "finance")], doc_scope="group"),
            scoped_payload([context_item("tag", "finance")], search_all=True),
            request_payload(context_items=[], search_all=True),
        ]
        for data in cases:
            with self.subTest(context_items=data["context_items"]):
                self.assert_safe_error(data, 400)
        self.service.hybrid_search.assert_not_called()

    def test_scoped_document_ids_are_authorized_in_their_exact_declared_workspace(self):
        self.contexts["doc-1"] = document_context(scope="group")
        self.assert_safe_error(scoped_payload([
            context_item("document", "doc-1", "group", "group-2"),
            context_item("tag", "finance", "group", "group-1"),
        ]), 403)
        self.service.hybrid_search.assert_not_called()

    def test_scoped_public_visibility_and_group_membership_are_not_permissions_from_chips(self):
        self.assert_safe_error(scoped_payload([
            context_item("tag", "finance", "public", "hidden-workspace"),
        ]), 403)
        self.service.assert_group_role.side_effect = PermissionError("SECRET")
        self.assert_safe_error(scoped_payload([
            context_item("tag", "finance", "group", "group-1"),
        ]), 403)
        self.service.hybrid_search.assert_not_called()

    def test_scoped_request_count_and_context_item_count_are_bounded(self):
        self.assert_safe_error(request_payload(
            context_items=[context_item("document", "doc-1")] * (self.service.MAX_CONTEXT_ITEMS + 1),
        ), 413)
        self.assert_safe_error(scoped_payload([
            context_item("tag", f"tag-{index}", "group", f"group-{index}")
            for index in range(self.service.MAX_SEARCH_REQUESTS + 1)
        ]), 413)
        self.service.hybrid_search.assert_not_called()
        self.service.resolve_planner_client.assert_not_called()

    def test_explicit_widening_accepts_empty_scoped_context_without_fallback_to_stale_filters(self):
        self.service.hybrid_search.return_value = []
        self.fill(scoped_payload([], search_all=True))
        self.assertEqual(
            [call.kwargs["doc_scope"] for call in self.service.hybrid_search.call_args_list],
            ["personal", "group", "public"],
        )

    def test_stale_tag_matches_do_not_bypass_intersection(self):
        self.contexts["doc-1"]["document"]["tags"] = []
        result = self.fill(request_payload(tags=["finance"]))
        self.assertEqual(result["values"], [])
        self.client.chat.completions.create.assert_not_called()

    def test_explicit_widening_is_bounded_to_accessible_enabled_workspaces(self):
        self.service.hybrid_search.return_value = []
        self.fill(request_payload(
            selected_document_ids=[], tags=[], active_group_ids=[], active_public_workspace_ids=[],
            search_all=True, scope_selected=False, doc_scope="all",
        ))
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual([call["doc_scope"] for call in calls], ["personal", "group", "public"])
        self.assertEqual(calls[1]["active_group_ids"], ["group-1", "group-2"])
        self.assertEqual(calls[2]["active_public_workspace_id"], ["public-1", "public-2"])
        self.assertTrue(all(call["top_n"] == self.service.MAX_SEARCH_RESULTS_PER_SCOPE for call in calls))
        self.service.get_user_groups.assert_called_once_with(USER_ID)
        self.assertEqual(self.service.assert_group_role.call_count, 2)
        self.assertEqual(self.service.find_public_workspace_by_id.call_count, 2)

    def test_widening_discovery_skips_revoked_memberships_and_deleted_visible_workspaces(self):
        def current_group_role(_user_id, group_id, **_kwargs):
            if group_id == "group-2":
                raise PermissionError("Membership revoked")
            return "User"

        self.service.assert_group_role.side_effect = current_group_role
        self.service.find_public_workspace_by_id.side_effect = (
            lambda workspace_id: {"id": workspace_id} if workspace_id == "public-1" else None
        )
        self.service.hybrid_search.return_value = []
        self.fill(scoped_payload([], search_all=True))
        calls = [call.kwargs for call in self.service.hybrid_search.call_args_list]
        self.assertEqual(calls[1]["active_group_ids"], ["group-1"])
        self.assertEqual(calls[2]["active_public_workspace_id"], ["public-1"])

    def test_rejected_widening_discovery_never_becomes_an_unrestricted_search(self):
        self.service.assert_group_role.side_effect = PermissionError("Membership revoked")
        self.service.find_public_workspace_by_id.side_effect = None
        self.service.find_public_workspace_by_id.return_value = None
        self.settings["enable_user_workspace"] = False
        self.assert_safe_error(scoped_payload([], search_all=True), 403)
        self.service.hybrid_search.assert_not_called()
        self.service.resolve_planner_client.assert_not_called()

    def test_personal_conversation_ownership_is_checked_before_search(self):
        self.service.cosmos_conversations_container.read_item.return_value = {
            "id": "conversation-1", "user_id": "other-user",
        }
        self.assert_safe_error(request_payload(conversation_id="conversation-1"), 403)
        self.service.hybrid_search.assert_not_called()
        self.service.cosmos_conversations_container.read_item.side_effect = MissingRecord("SECRET")
        self.assert_safe_error(request_payload(conversation_id="missing"), 403)

    def test_personal_conversation_read_does_not_load_messages(self):
        self.fill(request_payload(conversation_id="conversation-1"))
        self.service.cosmos_conversations_container.read_item.assert_called_once_with(
            item="conversation-1", partition_key="conversation-1",
        )
        self.service.cosmos_conversations_container.query_items.assert_not_called()
        for call in self.service.resolve_document_contexts.call_args_list:
            self.assertNotIn("conversation_id", call.kwargs)

    def test_collaborative_participation_and_feature_are_checked(self):
        data = request_payload(conversation_id="shared-1", conversation_kind="collaborative")
        self.fill(data)
        self.service.assert_user_can_participate_in_collaboration_conversation.assert_called_once()
        self.service.assert_user_can_participate_in_collaboration_conversation.side_effect = PermissionError("SECRET")
        self.assert_safe_error(data, 403)
        self.settings["enable_collaborative_conversations"] = False
        self.assert_safe_error(data, 403)

    def assigned_policy(self):
        return {
            "enabled": True, "has_workspace_knowledge": True,
            "assigned_knowledge": {"scopes": {"personal": True}},
            "active_group_ids": [], "active_public_workspace_ids": [],
            "document_ids": ["doc-1"], "tags_filter": ["finance"], "document_filter_mode": "union",
            "allow_user_workspace_context": False, "allowed_user_workspace_actions": ["search"],
        }

    def test_agent_policy_is_loaded_from_storage_not_browser_configuration(self):
        policy = self.assigned_policy()
        self.service.build_assigned_knowledge_runtime_filters.return_value = policy
        self.fill(request_payload(agent_info={
            "id": "agent-1", "assigned_knowledge": {"enabled": False}, "instructions": "SECRET ignored",
        }))
        self.service.resolve_delegation_agent.assert_called_once()
        self.service.build_assigned_knowledge_runtime_filters.assert_called_once_with({"id": "agent-1"})
        self.assertNotIn("SECRET", json.dumps(self.client.chat.completions.create.call_args.kwargs))
        self.service.resolve_delegation_agent.side_effect = PermissionError("SECRET")
        self.assert_safe_error(request_payload(agent_info={"id": "someone-elses-agent"}), 403)

    def test_agent_info_accepts_the_frontend_selection_shape(self):
        agent_info = {
            "id": "agent-1", "name": "ProjectAgent", "display_name": "Project helper",
            "is_global": False, "is_group": True, "group_id": "group-1", "group_name": "Project group",
        }
        self.fill(request_payload(agent_info=agent_info))
        self.service.resolve_delegation_agent.assert_called_once_with(
            agent_info, user_id=USER_ID, settings=self.settings,
        )

    def test_assigned_knowledge_restricts_widening_and_forwards_its_union_mode(self):
        self.service.build_assigned_knowledge_runtime_filters.return_value = self.assigned_policy()
        self.fill(request_payload(agent_info={"id": "agent-1"}, selected_document_ids=[], search_all=True, doc_scope="all"))
        calls = self.service.hybrid_search.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["doc_scope"], "personal")
        self.assertEqual(calls[0].kwargs["document_ids"], ["doc-1"])
        self.assertEqual(calls[0].kwargs["tags_filter"], ["finance"])
        self.assertEqual(calls[0].kwargs["document_filter_mode"], "union")

    def test_assigned_document_filter_precedes_the_search_cutoff(self):
        policy = self.assigned_policy()
        policy["tags_filter"] = []
        self.service.build_assigned_knowledge_runtime_filters.return_value = policy
        unassigned = [search_result(f"other-{index}") for index in range(12)]
        self.contexts.update({
            result["document_id"]: document_context(result["document_id"]) for result in unassigned
        })

        def ranked_search(**kwargs):
            if kwargs["document_ids"] == ["doc-1"]:
                return [search_result()]
            return (unassigned + [search_result()])[:kwargs["top_n"]]

        self.service.hybrid_search.side_effect = ranked_search
        result = self.fill(scoped_payload([
            context_item("tag", "finance"),
        ], agent_info={"id": "agent-1"}))
        self.assertEqual(result["values"][0]["value"], "Priya Shah")
        query = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(query["document_ids"], ["doc-1"])
        self.assertEqual(query["tags_filter"], ["finance"])
        self.assertEqual(query["document_filter_mode"], "intersection")

    def test_filter_intersection_preserves_both_union_and_intersection_semantics(self):
        for composer_mode in ("union", "intersection"):
            for policy_mode in ("union", "intersection"):
                with self.subTest(composer=composer_mode, policy=policy_mode):
                    plan = {
                        "kind": "personal", "groups": [], "public": [],
                        "document_ids": ["composer"], "tags": ["finance"], "mode": composer_mode,
                    }
                    policy = {
                        "document_ids": ["assigned"], "tags_filter": ["approved"],
                        "document_filter_mode": policy_mode,
                    }
                    queries = self.service._intersect_plan_filters(plan, policy)
                    for document_id in ("composer", "assigned", "other"):
                        for tags in ([], ["finance"], ["approved"], ["finance", "approved"]):
                            document = {"id": document_id, "tags": tags}
                            expected = self.service._matches_filters(
                                document, plan["document_ids"], plan["tags"], composer_mode,
                            ) and self.service._matches_filters(
                                document, policy["document_ids"], policy["tags_filter"], policy_mode,
                            )
                            actual = any(self.service._matches_filters(
                                document, query["document_ids"], query["tags"], query["mode"],
                            ) for query in queries)
                            self.assertEqual(actual, expected, (document, queries))

    def test_disjoint_assigned_and_composer_ids_never_produce_an_unfiltered_search(self):
        plan = {
            "kind": "personal", "groups": [], "public": [],
            "document_ids": ["composer"], "tags": [], "mode": "intersection",
        }
        self.assertEqual(self.service._intersect_plan_filters(
            plan, {"document_ids": ["assigned"], "tags_filter": []},
        ), [])

    def test_assignment_narrowing_cannot_move_a_rejected_workspaces_tag_to_another_scope(self):
        self.service.build_assigned_knowledge_runtime_filters.return_value = self.assigned_policy()
        self.assert_safe_error(request_payload(
            agent_info={"id": "agent-1"}, doc_scope="all", tags=["finance"],
            active_group_ids=["group-1"],
        ), 400)
        self.service.hybrid_search.assert_not_called()

        self.contexts["unselected"] = document_context("unselected")
        self.service.hybrid_search.return_value = [
            search_result(), search_result("unselected", chunk_text="UNSELECTED-PERSONAL-FINANCE evidence"),
        ]
        self.fill(scoped_payload([
            context_item("document", "doc-1"),
            context_item("tag", "finance", "group", "group-1"),
        ], agent_info={"id": "agent-1"}))
        self.service.hybrid_search.assert_called_once()
        params = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(params["doc_scope"], "personal")
        self.assertEqual(params["document_ids"], ["doc-1"])
        self.assertEqual(params["tags_filter"], [])
        self.assertNotIn("UNSELECTED-PERSONAL-FINANCE", json.dumps(self.client.chat.completions.create.call_args.kwargs))

    def test_empty_or_web_only_assigned_knowledge_never_falls_back_to_documents(self):
        data = request_payload(agent_info={"id": "agent-1"})
        self.service.build_assigned_knowledge_runtime_filters.return_value = {
            "enabled": True, "has_workspace_knowledge": False, "has_web_sources": True,
        }
        self.assert_safe_error(data, 403)
        self.service.build_assigned_knowledge_runtime_filters.return_value = None
        self.service.resolve_delegation_agent.return_value = {
            "id": "agent-1", "other_settings": {"assigned_knowledge": {"enabled": True}},
        }
        self.assert_safe_error(data, 403)
        self.service.hybrid_search.assert_not_called()

    def test_assigned_knowledge_blocks_unassigned_documents_unless_search_context_allowed(self):
        policy = self.assigned_policy()
        policy["document_ids"] = ["other"]
        policy["tags_filter"] = []
        self.service.build_assigned_knowledge_runtime_filters.return_value = policy
        data = request_payload(agent_info={"id": "agent-1"})
        self.assert_safe_error(data, 403)
        policy["allow_user_workspace_context"] = True
        policy["allowed_user_workspace_actions"] = ["analyze"]
        self.assert_safe_error(data, 403)
        policy["allowed_user_workspace_actions"] = ["search"]
        self.assertEqual(self.fill(data)["values"][0]["value"], "Priya Shah")

    def test_invalid_model_json_keys_types_sources_and_quotes_fail_safely(self):
        wrong_values = [
            {"results": []}, {"results": [filled_result(key="unexpected")]},
            {"results": [filled_result(value="Invented Person")]},
            {"results": [filled_result(source_id="https://example.invalid/evidence")]},
            {"results": [filled_result(quote="A fabricated supporting quotation.")]},
            {"results": [filled_result(value="")]},
            {"results": [filled_result(value=3)]},
            {"results": [filled_result(value="x" * (self.service.MAX_VALUE_CHARS + 1))]},
            {"results": [{**filled_result(), "sources": []}]},
            {"results": [{**filled_result(), "sources": [{"source_id": "e1", "quote": QUOTE, "url": "https://bad.invalid"}]}]},
            {"results": [{**filled_result(), "confidence": 0.99}]},
            {"results": [{"key": "project_owner", "status": "unresolved", "reason": "SECRET"}]},
            {"results": [{"key": "project_owner", "status": "conflict", "alternatives": []}]},
        ]
        response_message = self.client.chat.completions.create.return_value.choices[0].message
        for output in wrong_values:
            with self.subTest(output=output):
                response_message.content = json.dumps(output)
                self.assert_safe_error(request_payload(), 502)
        for content in ("not json", "```json\n{}\n```", '{"results":[],"results":[]}', "x" * 32001):
            with self.subTest(content=content[:60]):
                response_message.content = content
                self.assert_safe_error(request_payload(), 502)

    def test_duplicate_or_missing_batch_keys_are_not_a_partial_success(self):
        data = request_payload(variables=[
            {"key": "project_owner", "name": "Project owner"}, {"key": "budget", "name": "Budget"},
        ])
        self.output([filled_result(), filled_result()])
        self.assert_safe_error(data, 502)

    def test_model_refusal_tool_call_or_truncated_response_is_not_a_success(self):
        choice = self.client.chat.completions.create.return_value.choices[0]
        choice.finish_reason = "length"
        self.assert_safe_error(request_payload(), 502)
        choice.finish_reason = "stop"
        choice.message.refusal = "SECRET refusal"
        self.assert_safe_error(request_payload(), 502)
        choice.message.refusal = None
        choice.message.tool_calls = [{"name": "run_agent"}]
        self.assert_safe_error(request_payload(), 502)

    def test_retrieval_and_model_errors_never_return_raw_sdk_messages(self):
        self.service.hybrid_search.side_effect = RuntimeError("SECRET search endpoint")
        self.assert_safe_error(request_payload(), 503)
        self.service.hybrid_search.side_effect = None
        self.service.hybrid_search.return_value = None
        self.assert_safe_error(request_payload(), 503)
        self.service.hybrid_search.return_value = [search_result()]
        self.client.chat.completions.create.side_effect = RuntimeError("SECRET provider key")
        self.assert_safe_error(request_payload(), 502)
        self.assertNotIn("SECRET", repr(self.service.log_event.call_args_list))

    def test_missing_or_disabled_model_configuration_does_not_search(self):
        self.settings["gpt_model"]["selected"][0]["enabled"] = False
        self.assert_safe_error(request_payload(), 503)
        self.settings["gpt_model"]["selected"][0]["enabled"] = True
        self.service.resolve_planner_client.side_effect = RuntimeError("SECRET no deployment")
        self.assert_safe_error(request_payload(), 503)
        self.service.hybrid_search.assert_not_called()

    def test_multi_endpoint_default_is_resolved_with_stored_credentials(self):
        self.settings["enable_multi_model_endpoints"] = True
        self.settings["model_endpoints"] = [{"id": "endpoint-1"}]
        selection = {"endpoint_id": "endpoint-1", "model_id": "model-1", "provider": "aoai"}
        self.settings["default_model_selection"] = selection
        self.service.resolve_default_model_selection.return_value = (selection, None)
        endpoint = {
            "id": "endpoint-1", "provider": "aoai", "enabled": True,
            "connection": {"endpoint": "https://configured.invalid", "api_version": "configured"},
            "auth": {"type": "api_key", "api_key": "SECRET"},
            "models": [{"id": "model-1", "deploymentName": "gpt-5", "enabled": True}],
        }
        self.service.resolve_model_endpoint_from_context.return_value = endpoint
        self.fill()
        self.service.resolve_planner_client.assert_not_called()
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs["max_completion_tokens"], 4096)
        self.assertNotIn("temperature", self.client.chat.completions.create.call_args.kwargs)
        self.assertNotIn("SECRET", json.dumps(self.client.chat.completions.create.call_args.kwargs))
        endpoint["models"][0]["enabled"] = False
        self.assert_safe_error(request_payload(), 503)

    def test_existing_provider_adapters_remain_bounded_without_sdk_only_methods(self):
        for adapter_type in (OpenAIStyleClientStub, AnthropicClientStub):
            with self.subTest(adapter=adapter_type.__name__):
                adapter = adapter_type(self.client)
                self.service.resolve_planner_client.return_value = (adapter, "configured-deployment")
                self.client.chat.completions.create.return_value.choices[0].finish_reason = (
                    "end_turn" if isinstance(adapter, AnthropicClientStub) else "stop"
                )
                self.assertEqual(self.fill()["values"][0]["value"], "Priya Shah")
                if isinstance(adapter, AnthropicClientStub):
                    self.assertEqual(adapter.timeout, self.service.MODEL_TIMEOUT_SECONDS)

    def test_reasoning_model_metadata_survives_deployment_aliases(self):
        for multi in (False, True):
            for model_name in ("gpt-5", "o3", "gpt-4o"):
                with self.subTest(multi=multi, model=model_name):
                    self.settings["enable_multi_model_endpoints"] = multi
                    model = {
                        "id": "model-1", "deploymentName": "fill-prod",
                        "modelName": model_name, "enabled": True,
                    }
                    if multi:
                        selection = {"endpoint_id": "endpoint-1", "model_id": "model-1", "provider": "aoai"}
                        self.service.resolve_default_model_selection.return_value = (selection, None)
                        self.service.resolve_model_endpoint_from_context.return_value = {
                            "id": "endpoint-1", "provider": "aoai", "enabled": True, "models": [model],
                            "connection": {"endpoint": "https://configured.invalid", "api_version": "configured"},
                        }
                    else:
                        self.settings["gpt_model"]["selected"] = [model]
                        self.service.resolve_planner_client.return_value = (self.client, "fill-prod")
                    self.fill()
                    params = self.client.chat.completions.create.call_args.kwargs
                    self.assertEqual(params["model"], "fill-prod")
                    if model_name in ("gpt-5", "o3"):
                        self.assertEqual(params["max_completion_tokens"], 4096)
                        self.assertNotIn("max_tokens", params)
                        self.assertNotIn("temperature", params)
                    else:
                        self.assertEqual(params["max_tokens"], 4096)
                        self.assertEqual(params["temperature"], 0)
    def test_evidence_query_and_model_input_are_bounded(self):
        self.service.hybrid_search.return_value = [
            search_result(chunk_id=f"chunk-{index}", chunk_text=PASSAGE + "x" * 10000)
            for index in range(100)
        ]
        self.fill()
        self.assertLessEqual(len(self.service.hybrid_search.call_args.kwargs["query"]), self.service.MAX_SEARCH_QUERY_CHARS)
        params = self.client.chat.completions.create.call_args.kwargs
        model_data = json.loads(params["messages"][1]["content"])
        self.assertLessEqual(len(model_data["evidence"]), self.service.MAX_EVIDENCE_ITEMS)
        self.assertLessEqual(
            sum(len(item["excerpt"].encode("utf-8")) for item in model_data["evidence"]),
            self.service.MAX_EVIDENCE_BYTES,
        )
        self.assertNotIn("document_id", model_data["evidence"][0])

    def test_combined_model_input_bound_is_an_explicit_error(self):
        with patch.object(self.service, "MAX_MODEL_INPUT_BYTES", 10):
            self.assert_safe_error(request_payload(), 413)
        self.client.chat.completions.create.assert_not_called()

    def test_known_values_help_retrieval_but_cannot_ground_an_invented_value(self):
        data = request_payload(known_values={"budget": "Contoso context"})
        self.fill(data)
        self.assertIn("Contoso context", self.service.hybrid_search.call_args.kwargs["query"])
        self.output([filled_result(value="Contoso context", quote=QUOTE)])
        self.assert_safe_error(data, 502)

    def test_company_context_defaults_and_builtins_disambiguate_retrieval_without_changing_scope(self):
        acme_quote = "Acme contract date is 2026-10-12."
        beta_quote = "BetaCo contract date is 2026-05-01."
        self.contexts["doc-2"] = document_context("doc-2")

        def retrieve_for_company(**kwargs):
            if '"company_name": "Acme"' in kwargs["query"]:
                return [search_result(chunk_text=acme_quote)]
            return [search_result("doc-2", chunk_text=beta_quote)]

        self.service.hybrid_search.side_effect = retrieve_for_company
        self.output([filled_result(key="contract_date", value="2026-10-12", quote=acme_quote)])
        known_values = {
            "composer": "Existing draft context. " * 40,
            "company_name": "Acme",
            "today": "2026-09-05",
            "style": "formal",
        }
        data = request_payload(
            prompt_content="Find {{contract_date}} for {{company_name|Acme}}. {{style|formal}} {{today}} {{composer}}",
            variables=[{"key": "contract_date", "name": "Contract date"}],
            selected_document_ids=["doc-1", "doc-2"],
            composer_text="",
            known_values=known_values,
        )
        result = self.fill(data)
        self.assertEqual([(item["key"], item["value"]) for item in result["values"]], [
            ("contract_date", "2026-10-12"),
        ])
        self.assertEqual(result["values"][0]["sources"][0]["document_id"], "doc-1")
        self.assertEqual(data["known_values"], known_values)
        self.service.hybrid_search.assert_called_once()
        search = self.service.hybrid_search.call_args.kwargs
        self.assertEqual(search["doc_scope"], "personal")
        self.assertEqual(search["document_ids"], ["doc-1", "doc-2"])
        self.assertEqual(search["tags_filter"], [])
        self.assertEqual(search["active_group_ids"], [])
        self.assertEqual(search["active_public_workspace_id"], [])
        self.assertIn(json.dumps(known_values, ensure_ascii=False), search["query"])
        messages = self.client.chat.completions.create.call_args.kwargs["messages"]
        model_input = json.loads(messages[1]["content"])
        self.assertEqual(model_input["known_values"], known_values)
        self.assertEqual(model_input["variables"], data["variables"])
        self.assertIn("untrusted DATA", messages[0]["content"])
        self.assertIn("Known values alone never justify a proposed value", messages[0]["content"])
        self.assertNotIn("Acme", repr(self.service.log_event.call_args_list))

    def test_known_values_reject_unknown_inactive_duplicate_and_overwriting_keys(self):
        cases = [
            request_payload(known_values={"today": "2026-09-05"}),
            request_payload(prompt_content=request_payload()["prompt_content"] + " `{{hidden}}`", known_values={"hidden": "Acme"}),
            request_payload(prompt_content=request_payload()["prompt_content"] + r" \{{escaped}}", known_values={"escaped": "Acme"}),
            request_payload(known_values={"Budget": "100", "budget": "200"}),
            request_payload(known_values={"Project Owner": "Existing value"}),
            request_payload(known_values={"budget": 200}),
        ]
        for data in cases:
            with self.subTest(known_values=data["known_values"]):
                self.assert_safe_error(data, 400)
        self.service.hybrid_search.assert_not_called()
        self.service.resolve_planner_client.assert_not_called()

    def test_known_value_aliases_are_canonicalized_and_empty_values_are_not_constraints(self):
        normalized = self.service.normalize_fill_request(request_payload(
            known_values={"Budget": "200", "composer": "   "},
        ))
        self.assertEqual(normalized["known_values"], {"budget": "200"})
        self.assertIn('"budget": "200"', normalized["search_query"])
        self.assertNotIn('"composer": "   "', normalized["search_query"])

    def test_large_known_context_fails_instead_of_dropping_disambiguating_values(self):
        self.assert_safe_error(request_payload(known_values={
            "budget": "x" * self.service.MAX_VALUE_CHARS,
            "composer": "y" * self.service.MAX_VALUE_CHARS,
        }), 413)
        self.service.hybrid_search.assert_not_called()
        self.service.resolve_planner_client.assert_not_called()

    def test_known_context_neither_creates_a_scope_nor_triggers_widening_after_a_miss(self):
        self.assert_safe_error(request_payload(
            selected_document_ids=[], known_values={"budget": "Acme"},
        ), 400)
        self.service.hybrid_search.assert_not_called()
        self.service.hybrid_search.return_value = []
        result = self.fill(request_payload(known_values={"budget": "Acme"}))
        self.assertEqual(result["values"], [])
        self.assertEqual(result["unresolved"][0]["key"], "project_owner")
        self.service.hybrid_search.assert_called_once()
        self.assertEqual(self.service.hybrid_search.call_args.kwargs["doc_scope"], "personal")
        self.assertEqual(self.service.hybrid_search.call_args.kwargs["document_ids"], ["doc-1"])
        self.client.chat.completions.create.assert_not_called()

    def test_empty_or_malformed_model_envelopes_have_a_safe_failure(self):
        for envelope in (
            types.SimpleNamespace(choices=[]),
            types.SimpleNamespace(choices={"choice": "invalid"}),
            types.SimpleNamespace(choices=[None]),
            types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason="stop")]),
        ):
            self.client.chat.completions.create.return_value = envelope
            self.assert_safe_error(request_payload(), 502)

    def test_source_metadata_cannot_be_swapped_by_stale_search_results(self):
        self.service.hybrid_search.return_value = [search_result(user_id="other-owner")]
        self.assert_safe_error(request_payload(), 502)
        self.client.chat.completions.create.assert_not_called()

    def test_shared_source_scope_ids_must_still_be_well_formed(self):
        self.contexts["doc-1"] = document_context(
            scope="group", group_id=None, shared_group_ids=["group-1,approved"],
        )
        self.service.hybrid_search.return_value = [search_result(group_id=None)]
        self.assert_safe_error(request_payload(doc_scope="group", active_group_ids=["group-1"]), 502)
        self.client.chat.completions.create.assert_not_called()


class PromptKnowledgeRouteTests(unittest.TestCase):
    def setUp(self):
        self.service, _client = load_service()
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        self.user_id = USER_ID
        self.user_allowed = True
        self.call = Mock(return_value={"values": [], "unresolved": []})
        self.settings = {"api_key": "SECRET"}

        def login_required(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not self.user_id:
                    return jsonify({"error": "User not authenticated."}), 401
                return function(*args, **kwargs)
            return wrapped

        def user_required(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                if not self.user_allowed:
                    return jsonify({"error": "Access denied."}), 403
                return function(*args, **kwargs)
            return wrapped

        namespace = {
            "json": json, "logging": logging, "jsonify": jsonify, "request": request,
            "log_event": Mock(), "get_current_user_id": lambda: self.user_id,
            "get_settings": lambda: self.settings, "fill_prompt_variables": self.call,
            "PromptKnowledgeFillError": self.service.PromptKnowledgeFillError,
            "BadRequest": BadRequest, "RequestEntityTooLarge": RequestEntityTooLarge,
            "PROMPT_FILL_MAX_REQUEST_BYTES": self.service.MAX_REQUEST_BYTES,
            "login_required": login_required, "user_required": user_required,
            "swagger_route": lambda **_kwargs: lambda function: function,
            "get_auth_security": lambda: [],
        }
        tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
        registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_v2")
        exec(compile(ast.Module(body=[registrar], type_ignores=[]), str(ROUTE_PATH), "exec"), namespace)
        blueprint = Blueprint("backend_v2", __name__)
        namespace["register_route_backend_v2"](blueprint)
        self.app.register_blueprint(blueprint)
        self.client = Client(self.app, self.app.response_class)

    def post(self, **kwargs):
        return self.client.post("/api/v2/prompts/fill-variables", **kwargs)

    def test_route_passes_only_server_identity_and_settings_to_service(self):
        data = request_payload()
        response = self.post(json=data)
        self.assertEqual(response.status_code, 200)
        self.call.assert_called_once_with(data, USER_ID, self.settings)
        self.assertNotIn("SECRET", response.get_data(as_text=True))

    def test_route_is_user_authenticated_post_only(self):
        self.user_id = None
        self.assertEqual(self.post(json=request_payload()).status_code, 401)
        self.user_id = USER_ID
        self.user_allowed = False
        self.assertEqual(self.post(json=request_payload()).status_code, 403)
        self.assertEqual(self.client.get("/api/v2/prompts/fill-variables").status_code, 405)
        self.call.assert_not_called()

    def test_a_blueprint_guard_can_parse_json_before_the_endpoint(self):
        @self.app.before_request
        def inspect_json():
            request.get_json(silent=True)

        response = self.post(json=request_payload())
        self.assertEqual(response.status_code, 200)
        self.call.assert_called_once()

    def test_bad_json_wrong_content_type_and_oversized_body_are_safe_errors(self):
        self.assertEqual(self.post(data="{", content_type="application/json").status_code, 400)
        self.assertEqual(self.post(data="not json", content_type="text/plain").status_code, 400)
        self.assertEqual(self.post(data="x" * 65537, content_type="application/json").status_code, 413)
        self.call.assert_not_called()

    def test_service_errors_keep_their_status_and_unexpected_errors_are_redacted(self):
        for status in (400, 403, 413, 502, 503):
            self.call.side_effect = self.service.PromptKnowledgeFillError("Stable safe error.", status)
            response = self.post(json=request_payload())
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.get_json(), {"error": "Stable safe error."})
        self.call.side_effect = RuntimeError("SECRET raw SDK exception")
        response = self.post(json=request_payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(set(response.get_json()), {"error"})
        self.assertNotIn("SECRET", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
