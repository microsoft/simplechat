# test_ai_connection_text_consumers.py
"""Behavioral regression tests for shared AI Connection text-consumer guards.

Version: 0.261.105
Implemented in: 0.261.105

Execute the real consumer function bodies with the real import-safe capability
module. SDK, credential, settings-store, and authorization seams stay in memory;
these tests do not initialize the application or contact Azure.
"""

import ast
import base64
import io
import json
import mimetypes
import sys
import unittest
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch, sentinel


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
# Only the pure capability modules are imported after establishing the app path.
import functions_ai_connections as connections
from functions_model_capabilities import (
    REASONING_IDENTIFIER_FIELDS,
    is_vision_capable_model,
    resolve_model_reasoning_policy,
)


def model(name="gpt-4o", **overrides):
    return {
        "id": "selected-model",
        "deploymentName": "custom-deployment",
        "modelName": name,
        "enabled": True,
        **overrides,
    }


def endpoint(models=None, **overrides):
    return {
        "id": "selected-endpoint",
        "name": "Test connection",
        "provider": "aoai",
        "enabled": True,
        "connection": {
            "endpoint": "https://example.test/openai",
            "openai_api_version": "2025-01-01-preview",
        },
        "auth": {"type": "api_key", "api_key": "test-only-key"},
        "models": [model()] if models is None else deepcopy(models),
        **overrides,
    }


def incompatible_models():
    return [
        model("gpt-image-1"),
        model("dall-e-3"),
        model("text-embedding-3-large"),
        model(enabled_capabilities=["image_generation"]),
        model("private-alias", supportsChat=False),
        model("private-alias", enabled=False),
    ]


@lru_cache(maxsize=None)
def source_tree(filename):
    return ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"), filename=filename)


def load_boundaries(filename, names, extra=None, *, constants=(), register_chat=False):
    namespace = {
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
        "deepcopy": deepcopy,
        "AIConnectionError": connections.AIConnectionError,
        "require_model_capability": connections.require_model_capability,
        "supports_model_capability": connections.supports_model_capability,
        "filter_model_endpoints_by_capability": connections.filter_model_endpoints_by_capability,
        "REASONING_IDENTIFIER_FIELDS": REASONING_IDENTIFIER_FIELDS,
        "resolve_model_reasoning_policy": resolve_model_reasoning_policy,
        "resolve_capability_model_selection": connections.resolve_capability_model_selection,
        "register_capability_client_factory": connections.register_capability_client_factory,
        "normalize_model_endpoints": lambda values: (deepcopy(values), False),
        "sanitize_model_endpoints_for_frontend": deepcopy,
        "keyvault_model_endpoint_get_helper": Mock(side_effect=lambda value, *args, **kwargs: deepcopy(value)),
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "build_model_endpoint_identity_headers": Mock(return_value={}),
        "debug_print": Mock(),
        "cognitive_services_scope": "https://cognitiveservices.azure.com/.default",
        "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": "azure_openai",
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": "anthropic",
        "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE": "openai_style",
        "infer_model_endpoint_protocol": lambda *args: "azure_openai",
        "AzureOpenAI": Mock(return_value=sentinel.client),
        "_build_azure_chat_completion": Mock(return_value=sentinel.service),
    }
    namespace.update(extra or {})
    tree = source_tree(filename)
    nodes = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constants for target in node.targets
        ):
            nodes.append(node)
        if register_chat and isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "register_capability_client_factory":
                nodes.append(node)
    nodes.sort(key=lambda node: node.lineno)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_ROOT / filename), "exec"), namespace)
    return namespace


class AIConnectionTextConsumerTests(unittest.TestCase):
    def test_chat_catalog_projects_each_scope_without_mutating_connections(self):
        records = [
            model(),
            model("private-chat-alias", id="legacy", deploymentName="legacy"),
            *incompatible_models(),
        ]
        shared = endpoint(records)
        original = deepcopy(shared)
        governance_checks = []
        helpers = load_boundaries("route_frontend_chats.py", {
            "_build_chat_model_catalog", "_chat_model_reasoning_metadata",
        }, {
            "_filter_chat_model_endpoints_by_governance": lambda user, values, feature: (
                governance_checks.append((user, feature)) or values
            ),
            "get_group_model_endpoints": lambda group: [shared],
        })
        catalog = helpers["_build_chat_model_catalog"](
            user_id="reader",
            settings={
                "enable_multi_model_endpoints": True,
                "model_endpoints": [shared],
                "allow_user_custom_endpoints": True,
                "enable_group_workspaces": True,
                "allow_group_custom_endpoints": True,
            },
            user_settings_dict={"personal_model_endpoints": [shared]},
            user_groups_raw=[{"id": "group-one", "name": "Group"}],
        )
        self.assertEqual(len(catalog), 6)
        self.assertEqual({item["model_id"] for item in catalog}, {"selected-model", "legacy"})
        self.assertEqual(len({item["selection_key"] for item in catalog}), 6)
        self.assertEqual({item["scope_type"] for item in catalog}, {"global", "personal", "group"})
        self.assertEqual(len(governance_checks), 3)
        self.assertEqual(shared, original)

    def test_scoped_context_resolution_rejects_images_before_secret_hydration(self):
        for scope in ("global", "user", "group"):
            for record in [*incompatible_models(), model("private-chat-alias")]:
                with self.subTest(scope=scope, record=record):
                    selected = endpoint([record])
                    settings = {
                        "enable_multi_model_endpoints": True,
                        "model_endpoints": [selected] if scope == "global" else [],
                        "allow_user_custom_endpoints": scope == "user",
                        "allow_group_custom_endpoints": scope == "group",
                    }
                    helpers = load_boundaries("functions_model_endpoint_runtime.py", {
                        "_append_model_endpoint_candidate", "resolve_model_endpoint_from_context",
                    })
                    role_check = Mock()
                    governed = Mock(side_effect=lambda user, values, feature: values)
                    stores = {
                        "functions_group": SimpleNamespace(
                            get_group_model_endpoints=lambda group: [selected], assert_group_role=role_check,
                        ),
                        "functions_settings": SimpleNamespace(
                            get_user_settings=lambda user: {"settings": {"personal_model_endpoints": [selected]}},
                            normalize_model_endpoints=helpers["normalize_model_endpoints"],
                        ),
                        "functions_keyvault": SimpleNamespace(
                            SecretReturnType=helpers["SecretReturnType"],
                            keyvault_model_endpoint_get_helper=helpers["keyvault_model_endpoint_get_helper"],
                        ),
                        "functions_governance": SimpleNamespace(filter_governed_model_endpoints=governed),
                    }
                    context = {
                        "endpoint_id": selected["id"], "model_id": record["id"], "user_id": "reader",
                        "active_group_ids": ["group-one"] if scope == "group" else [],
                    }
                    with patch.dict(sys.modules, stores):
                        if connections.supports_model_capability(record):
                            resolved = helpers["resolve_model_endpoint_from_context"](settings, context, authorize=True)
                            self.assertEqual(resolved["models"], [record])
                            self.assertEqual(helpers["keyvault_model_endpoint_get_helper"].call_args.kwargs["scope"], scope)
                        else:
                            with self.assertRaises(connections.AIConnectionError):
                                helpers["resolve_model_endpoint_from_context"](settings, context, authorize=True)
                            helpers["keyvault_model_endpoint_get_helper"].assert_not_called()
                    if scope == "group":
                        role_check.assert_called_once_with(
                            "reader", "group-one", allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
                        )
                    self.assertTrue(governed.called)

    def test_chat_factories_validate_metadata_and_name_only_overrides(self):
        helpers = load_boundaries("functions_model_endpoint_runtime.py", {
            "_require_chat_model_for_endpoint", "build_model_endpoint_sync_chat_client",
            "build_semantic_kernel_chat_service_for_model",
        })
        for record in incompatible_models():
            with self.subTest(record=record):
                selected = endpoint([record])
                with self.assertRaises(connections.AIConnectionError):
                    helpers["build_model_endpoint_sync_chat_client"](
                        selected["auth"], "aoai", selected["connection"]["endpoint"], "v1",
                        record["deploymentName"], endpoint_config=selected,
                    )
                with self.assertRaises(connections.AIConnectionError):
                    helpers["build_semantic_kernel_chat_service_for_model"](
                        "gpt-4o", {}, model_context={"model_id": record["id"]},
                        resolved_model_endpoint=selected,
                    )
        with self.assertRaises(connections.AIConnectionError):
            helpers["build_semantic_kernel_chat_service_for_model"]("gpt-image-1", {})
        with self.assertRaises(connections.AIConnectionError):
            helpers["build_model_endpoint_sync_chat_client"](
                {"type": "api_key", "api_key": "test-key"}, "aoai", "https://example.test", "v1", "gpt-image-1",
            )
        helpers["AzureOpenAI"].assert_not_called()
        helpers["_build_azure_chat_completion"].assert_not_called()
        selected = endpoint([model("private-chat-alias")])
        service, protocol = helpers["build_semantic_kernel_chat_service_for_model"](
            "stale-deployment", {}, model_context={"model_id": "selected-model"},
            resolved_model_endpoint=selected,
        )
        self.assertIs(service, sentinel.service)
        self.assertEqual(protocol, "azure_openai")
        self.assertEqual(helpers["_build_azure_chat_completion"].call_args.kwargs["deployment_name"], "custom-deployment")
        with self.assertRaises(connections.AIConnectionError):
            helpers["build_semantic_kernel_chat_service_for_model"](
                "custom-deployment", {}, model_context={"model_id": "forged-model"}, resolved_model_endpoint=selected,
            )
        selected["models"].insert(0, model(
            "custom-deployment", id="image-alias", deploymentName="images", enabled_capabilities=["image_generation"],
        ))
        client, _ = helpers["build_model_endpoint_sync_chat_client"](
            selected["auth"], "aoai", selected["connection"]["endpoint"], "v1",
            "custom-deployment", endpoint_config=selected,
        )
        self.assertIs(client, sentinel.client)

    def test_chat_binding_registers_adapter_and_preserves_factory_arguments(self):
        selected = endpoint()
        settings = {"enable_multi_model_endpoints": True, "model_endpoints": [selected]}
        binding = connections.ModelBinding("chat", {
            "endpoint_id": selected["id"], "model_id": "selected-model", "provider": "aoai",
        }, selected, selected["models"][0])
        builder = Mock(return_value=(sentinel.client, "azure_openai"))
        hydrated = deepcopy(selected)
        hydrated["auth"]["api_key"] = "hydrated-test-key"
        hydrate = Mock(return_value=hydrated)
        vault = SimpleNamespace(
            SecretReturnType=SimpleNamespace(VALUE="value"),
            keyvault_model_endpoint_get_helper=hydrate,
        )
        with patch.dict(connections._CLIENT_FACTORIES), patch.dict(sys.modules, {"functions_keyvault": vault}):
            load_boundaries("functions_model_endpoint_runtime.py", {
                "_require_chat_model_for_endpoint", "build_chat_connection_client",
            }, {
                "build_model_endpoint_sync_chat_client": builder,
            }, register_chat=True)
            self.assertIs(connections.create_capability_client(binding, settings), sentinel.client)
        hydrate.assert_called_once_with(selected, selected["id"], scope="global", return_type="value")
        builder.assert_called_once_with(
            hydrated["auth"], "aoai", selected["connection"]["endpoint"],
            selected["connection"]["openai_api_version"], deployment_name="custom-deployment",
            settings=settings, endpoint_config=hydrated,
        )

    def test_agent_catalog_keeps_foundry_projects_without_forcing_chat_mode(self):
        image = endpoint([model("gpt-image-1")], provider="new_foundry")
        project = endpoint([], id="foundry-project", provider="new_foundry")
        settings = {"model_endpoints": [image, project], "enable_multi_model_endpoints": False}
        original = deepcopy(settings)
        helpers = load_boundaries("route_backend_agents.py", {
            "build_combined_model_endpoints", "get_global_agent_settings",
        }, {
            "get_settings": lambda: settings,
            "get_global_agents": lambda: [],
            "jsonify": lambda values: values,
        })
        result = helpers["get_global_agent_settings"]()
        self.assertFalse(result["enable_multi_model_endpoints"])
        self.assertEqual([item["id"] for item in result["model_endpoints"]], [image["id"], project["id"]])
        self.assertTrue(all(item["models"] == [] for item in result["model_endpoints"]))
        self.assertEqual(settings, original)

    def test_native_agent_options_filter_models_but_retain_project_choices(self):
        selected = endpoint([model(), *incompatible_models()], scope="global")
        project = endpoint([], id="foundry-project", provider="new_foundry", scope="global")
        image = endpoint([model("gpt-image-1")], scope="global")
        settings_module = SimpleNamespace(sanitize_settings_for_user=deepcopy)
        governance = SimpleNamespace(
            ensure_governance_access=Mock(), filter_governed_model_endpoints=lambda user, values, feature: values,
        )
        helpers = load_boundaries("functions_workspace_authoring.py", {"build_agent_editor_options"}, {
            "ensure_editor_options_access": lambda user, settings: True,
            "ensure_editor_access": Mock(),
            "import_module": lambda name: {"functions_settings": settings_module, "functions_governance": governance}[name],
            "editor_secret_paths": lambda *args: [],
        }, constants=("_OPTION_DEFAULTS", "_BUILTIN_ACTIONS", "_AGENT_TYPES"))
        options = helpers["build_agent_editor_options"]("reader", {}, [selected, project])
        self.assertEqual(options["model_endpoints"][0]["models"], [model()])
        self.assertEqual(options["model_endpoints"][1]["id"], "foundry-project")
        legacy = helpers["build_agent_editor_options"]("reader", {}, [image, project])
        self.assertFalse(legacy["settings"]["enable_multi_model_endpoints"])
        self.assertEqual(len(legacy["model_endpoints"]), 2)
        self.assertEqual(len(selected["models"]), 1 + len(incompatible_models()))

    def test_agent_saved_bindings_and_semantic_kernel_binding_are_guarded(self):
        summaries = load_boundaries("route_backend_agents.py", {
            "_summarize_model_binding", "_format_model_provider_label",
        })
        runtime = load_boundaries("semantic_kernel_loader.py", {"resolve_multi_endpoint_agent_binding"})
        for record in incompatible_models():
            with self.subTest(record=record):
                selected = endpoint([record], _endpoint_scope="group")
                summary = summaries["_summarize_model_binding"]([selected], {
                    "endpoint_id": selected["id"], "model_id": record["id"],
                })
                self.assertFalse(summary["valid"])
                with self.assertRaises(connections.AIConnectionError):
                    runtime["resolve_multi_endpoint_agent_binding"]([selected], selected["id"], record["id"])
        runtime["keyvault_model_endpoint_get_helper"].assert_not_called()
        selected = endpoint([model("private-chat-alias")], _endpoint_scope="group")
        binding = runtime["resolve_multi_endpoint_agent_binding"]([selected], selected["id"], "selected-model")
        self.assertEqual(binding["deployment"], "custom-deployment")
        self.assertEqual(runtime["keyvault_model_endpoint_get_helper"].call_args.kwargs["scope"], "group")

    def test_personal_and_group_workflow_bindings_require_text_models(self):
        for filename in ("functions_personal_workflows.py", "functions_group_workflows.py"):
            helpers = load_boundaries(filename, {"_summarize_model_binding"})
            for record in incompatible_models():
                with self.subTest(filename=filename, record=record):
                    selected = endpoint([record])
                    with self.assertRaises(ValueError):
                        helpers["_summarize_model_binding"]([selected], selected["id"], record["id"])
            selected = endpoint([model("private-chat-alias")])
            self.assertTrue(helpers["_summarize_model_binding"]([selected], selected["id"], "selected-model")["valid"])

    def test_workflow_defaults_validate_real_model_references(self):
        helpers = load_boundaries("functions_personal_workflows.py", {"_build_default_model_summary", "first_if_comma"})
        for record in [*incompatible_models(), model("private-chat-alias")]:
            with self.subTest(record=record):
                selected = endpoint([record])
                summary = helpers["_build_default_model_summary"]({
                    "model_endpoints": [selected],
                    "default_model_selection": {
                        "endpoint_id": selected["id"], "model_id": record["id"], "provider": "forged-provider",
                    },
                    "enable_gpt_apim": True,
                })
                self.assertEqual(summary["valid"], connections.supports_model_capability(record))
                self.assertEqual(summary["mode"], "default_selection")
                if summary["valid"]:
                    self.assertEqual(summary["provider"], "aoai")
        self.assertFalse(helpers["_build_default_model_summary"]({
            "default_model_selection": {"endpoint_id": "missing"}, "enable_gpt_apim": True,
        })["valid"])

    def test_workflow_runtime_rechecks_disabled_and_incompatible_saved_models(self):
        builder = Mock(return_value=(sentinel.client, "azure_openai"))
        helpers = load_boundaries("functions_workflow_runner.py", {"_build_multi_endpoint_client"}, {
            "build_model_endpoint_sync_chat_client": builder,
        })
        cases = [endpoint([record]) for record in incompatible_models()] + [endpoint(enabled=False)]
        for selected in cases:
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    helpers["_build_multi_endpoint_client"](
                        "reader", selected["id"], "selected-model", {"model_endpoints": [selected]},
                    )
        helpers["keyvault_model_endpoint_get_helper"].assert_not_called()
        builder.assert_not_called()
        selected = endpoint([model("private-chat-alias")])
        self.assertEqual(helpers["_build_multi_endpoint_client"](
            "reader", selected["id"], "selected-model", {"model_endpoints": [selected]},
        ), (sentinel.client, "custom-deployment", "aoai"))

    def test_metadata_rejects_incompatible_models_before_loading_credentials(self):
        builder = Mock(return_value=sentinel.client)
        helpers = load_boundaries("functions_documents.py", {
            "_normalize_model_endpoint_selection", "_resolve_metadata_extraction_client",
        }, {
            "_build_model_endpoint_client": builder,
            "MODEL_ENDPOINT_PROVIDER_ALLOWLIST": {"aoai", "new_foundry"},
        })
        for record in incompatible_models():
            with self.subTest(record=record):
                selected = endpoint([record])
                with self.assertRaises(ValueError):
                    helpers["_resolve_metadata_extraction_client"]({
                        "enable_multi_model_endpoints": True, "model_endpoints": [selected],
                        "metadata_extraction_model_selection": {
                            "endpoint_id": selected["id"], "model_id": record["id"],
                        },
                    })
        helpers["keyvault_model_endpoint_get_helper"].assert_not_called()
        builder.assert_not_called()
        selected = endpoint([model("private-chat-alias")])
        client, deployment = helpers["_resolve_metadata_extraction_client"]({
            "enable_multi_model_endpoints": True, "model_endpoints": [selected],
            "metadata_extraction_model_selection": {"endpoint_id": selected["id"], "model_id": "selected-model"},
        })
        self.assertIs(client, sentinel.client)
        self.assertEqual(deployment, "custom-deployment")

    def test_vision_analysis_requires_both_image_input_and_text_output(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"description":"A drawing."}'))],
        )
        helpers = load_boundaries("functions_documents.py", {"analyze_image_with_vision_model"}, {
            "open": lambda *args, **kwargs: io.BytesIO(b"test-image"),
            "base64": base64, "mimetypes": mimetypes, "json": json,
            "traceback": SimpleNamespace(print_exc=Mock()), "print": Mock(),
            "is_vision_capable_model": is_vision_capable_model,
            "clean_json_codeFence": lambda value: value,
            "AzureOpenAI": Mock(return_value=client),
        })
        for record in [
            model("gpt-image-1", supportsVision=True),
            model("private-text", supportsVision=False),
            model(supportsVision=True, enabled_capabilities=["image_generation"]),
        ]:
            with self.subTest(record=record):
                self.assertIsNone(helpers["analyze_image_with_vision_model"](
                    "image.png", "reader", "document", {
                        "multimodal_vision_model": "custom-deployment", "gpt_model": {"selected": [record]},
                    },
                ))
        helpers["AzureOpenAI"].assert_not_called()
        record = model("private-vision-chat", supportsVision=True)
        result = helpers["analyze_image_with_vision_model"]("image.png", "reader", "document", {
            "multimodal_vision_model": "custom-deployment", "gpt_model": {"selected": [record]},
        })
        self.assertEqual(result["description"], "A drawing.")
        client.chat.completions.create.assert_called_once()

    def test_summary_resolution_rejects_image_aliases_without_legacy_fallback(self):
        builder = Mock(return_value=sentinel.client)
        helpers = load_boundaries("route_backend_conversation_export.py", {
            "_normalize_summary_model_value", "_summary_model_matches", "_find_summary_endpoint_model",
            "_resolve_summary_multi_endpoint_client",
        }, {"_build_summary_model_endpoint_client": builder})
        for record in incompatible_models():
            selected = endpoint([record])
            helpers["_get_summary_model_endpoint_candidates"] = lambda *args, **kwargs: [selected]
            for explicit in (True, False):
                with self.subTest(record=record, explicit=explicit):
                    with self.assertRaises(ValueError):
                        helpers["_resolve_summary_multi_endpoint_client"](
                            {"enable_multi_model_endpoints": True}, requested_model="custom-deployment",
                            requested_endpoint_id=selected["id"] if explicit else "",
                            requested_model_id=record["id"] if explicit else "",
                        )
        helpers["keyvault_model_endpoint_get_helper"].assert_not_called()
        builder.assert_not_called()
        selected = endpoint([model("private-chat-alias")])
        selected["models"].insert(0, model(
            "custom-deployment", id="image-alias", deploymentName="images", enabled_capabilities=["image_generation"],
        ))
        helpers["_get_summary_model_endpoint_candidates"] = lambda *args, **kwargs: [selected]
        result = helpers["_resolve_summary_multi_endpoint_client"](
            {"enable_multi_model_endpoints": True}, requested_endpoint_id=selected["id"],
            requested_model_id="selected-model", requested_provider="forged-provider",
        )
        self.assertEqual(result, (sentinel.client, "custom-deployment"))
        self.assertEqual(builder.call_args.args[1], "aoai")
        self.assertEqual(
            helpers["_resolve_summary_multi_endpoint_client"](
                {"enable_multi_model_endpoints": True}, requested_model="custom-deployment",
            ),
            (sentinel.client, "custom-deployment"),
        )
        for selection in (
            {"endpoint_id": selected["id"], "model_id": "missing"},
            {"endpoint_id": "missing", "model_id": "selected-model"},
        ):
            with self.assertRaises(ValueError):
                helpers["_resolve_summary_multi_endpoint_client"]({
                    "enable_multi_model_endpoints": True, "default_model_selection": selection,
                })

    def test_knowledge_fill_independently_validates_resolved_default_models(self):
        selection = {"endpoint_id": "selected-endpoint", "model_id": "selected-model", "provider": "aoai"}
        builder = Mock(return_value=(sentinel.client, "azure_openai"))
        resolver = Mock()
        helpers = load_boundaries("functions_prompt_variables.py", {"PromptKnowledgeFillError", "resolve_fill_client"}, {
            "resolve_default_model_selection": lambda *args: (selection, None),
            "resolve_model_endpoint_from_context": resolver,
            "build_model_endpoint_sync_chat_client": builder,
        })
        for record in incompatible_models():
            with self.subTest(record=record):
                resolver.return_value = endpoint([record])
                with self.assertRaises(helpers["PromptKnowledgeFillError"]) as error:
                    helpers["resolve_fill_client"]({"enable_multi_model_endpoints": True}, "reader")
                self.assertEqual(error.exception.status_code, 503)
        builder.assert_not_called()
        resolver.return_value = endpoint([model("private-chat-alias")])
        self.assertEqual(
            helpers["resolve_fill_client"]({"enable_multi_model_endpoints": True}, "reader"),
            (sentinel.client, "custom-deployment", "private-chat-alias"),
        )
        resolver.side_effect = connections.AIConnectionError("The selected model is unavailable.")
        with self.assertRaises(helpers["PromptKnowledgeFillError"]) as error:
            helpers["resolve_fill_client"]({"enable_multi_model_endpoints": True}, "reader")
        self.assertEqual(error.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
