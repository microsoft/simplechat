# test_ai_connection_embedding_migration.py
"""
Functional coverage for independent legacy embedding connection import.
Version: 0.261.122
Implemented in: 0.261.106

Exercise pure planning, vector-profile preservation, optimistic concurrency and
startup credential staging without importing Azure clients or calling providers.
"""

import copy
import json
import sys
import time
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosAccessConditionFailedError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from app_settings_store import AppSettingsStore, SETTINGS_REVISION_FIELD, WRITE_LEASE_SECONDS
from functions_ai_connection_migration import (
    EMBEDDING_MIGRATION_NOTICE_KEY,
    MIGRATION_NOTICE_KEY,
    EmbeddingMigrationConflict,
    ImageMigrationConflict,
    _legacy_embedding_connection,
    build_embedding_connection_migration,
    build_image_connection_migration,
    initialize_ai_connections,
    migrate_embedding_connections,
    preserve_legacy_embedding_form_settings,
)
from functions_ai_connections import (
    AIConnectionError,
    EMBEDDINGS_CAPABILITY,
    EMBEDDING_MIGRATION_VERSION_KEY,
    EMBEDDING_SELECTION_KEY,
    EMPTY_MODEL_SELECTION,
    IMAGE_MIGRATION_VERSION_KEY,
    IMAGE_SELECTION_KEY,
    embedding_settings_use_connections,
    image_settings_use_connections,
    supports_model_capability,
)
from functions_embedding_profile import EMBEDDING_VECTOR_PROFILE_KEY, resolve_embedding_profile
from test_ai_connection_credential_staging import load_secret_save_helper
from test_ai_connection_image_migration import legacy_settings as legacy_image_settings
from test_app_settings_store_consistency import FakeRedis


def legacy_embedding_settings():
    selected = {
        "deploymentName": "knowledge-vectors",
        "modelName": "text-embedding-3-small",
        "modelVersion": "1",
        "displayName": "Knowledge embeddings",
        "maxInputTokens": 8192,
    }
    return {
        "id": "app_settings",
        "_etag": "revision-1",
        "enable_multi_model_endpoints": False,
        "enable_embedding_apim": False,
        "azure_openai_embedding_endpoint": "https://vectors.example.test/custom/base/",
        "azure_openai_embedding_authentication_type": "key",
        "azure_openai_embedding_key": "synthetic-embedding-key",
        "azure_openai_embedding_api_version": "2024-05-01-preview",
        "azure_openai_embedding_subscription_id": "synthetic-subscription",
        "azure_openai_embedding_resource_group": "synthetic-resource-group",
        "embedding_model": {
            "selected": [copy.deepcopy(selected)],
            "all": [
                copy.deepcopy(selected),
                {"deploymentName": "larger-vectors", "modelName": "text-embedding-3-large"},
            ],
        },
        "model_endpoints": [],
    }


def with_gateway(settings, *, active=True):
    result = copy.deepcopy(settings)
    result.update({
        "enable_embedding_apim": active,
        "azure_apim_embedding_endpoint": "https://gateway.example.test/tenant/vector-api/",
        "azure_apim_embedding_deployment": "gateway-vectors",
        "azure_apim_embedding_subscription_key": "synthetic-gateway-key",
        "azure_apim_embedding_api_version": "2025-04-01-preview",
    })
    return result


def selected_endpoint(updates):
    selection = updates[EMBEDDING_SELECTION_KEY]
    return next(item for item in updates["model_endpoints"] if item["id"] == selection["endpoint_id"])


class FakeAzureError(AzureError):
    pass


class FakeCosmosConflict(CosmosAccessConditionFailedError):
    pass


class MigrationRuntime:
    """Install startup collaborators backed by an in-memory settings/secret store."""

    def __init__(self, settings):
        self.settings = copy.deepcopy(settings)
        self.vault = {}
        self.reads = []
        self.writes = []
        self.stages = []
        self.discards = []
        self.resolutions = []
        self.cache_updates = []
        self.guards = []
        self.logs = []
        self.prepare_hook = None
        self.write_hook = None
        self.cleanup_hook = None
        self.save_secret = load_secret_save_helper(self.vault)
        self.cache = FakeRedis()
        redis_eval = self.cache.eval

        def publish(*args):
            updated = redis_eval(*args)
            state = json.loads(args[-1])
            if updated and state["state"] == "ready":
                self.cache_updates.append((
                    copy.deepcopy(state["document"]), {"context": "shared_settings_store"},
                ))
            return updated

        self.cache.eval = publish
        self.app_store = AppSettingsStore(
            SimpleNamespace(read_item=self.read, replace_item=self.write),
            self.cache, redis_required=True,
        )

    def read(self, **kwargs):
        self.reads.append(kwargs)
        if kwargs.get("response_hook"):
            kwargs["response_hook"]({"x-ms-session-token": self.settings["_etag"]}, self.settings)
        return copy.deepcopy(self.settings)

    def write(self, *, item, body, etag, match_condition, session_token=None, response_hook=None):
        assert match_condition == MatchConditions.IfNotModified
        self.writes.append((copy.deepcopy(body), etag))
        if self.write_hook:
            self.write_hook(body, etag)
        if etag != self.settings["_etag"]:
            raise FakeCosmosConflict(status_code=412, message="Settings changed")
        self.settings = copy.deepcopy(body)
        self.settings["_etag"] = f"committed-{len(self.writes)}"
        if response_hook:
            response_hook({"x-ms-session-token": self.settings["_etag"]}, self.settings)
        return copy.deepcopy(self.settings)

    def guard(self, current, candidate, **kwargs):
        self.guards.append((copy.deepcopy(current), copy.deepcopy(candidate), kwargs))
        return nullcontext()

    def prepare(self, endpoint, owner, **kwargs):
        self.stages.append((copy.deepcopy(endpoint), owner, kwargs))
        if self.prepare_hook:
            self.prepare_hook(endpoint)
        if not self.settings.get("enable_key_vault_secret_storage"):
            return copy.deepcopy(endpoint)
        return self.save_secret(endpoint, owner, **kwargs)

    def resolve(self, reference, **kwargs):
        self.resolutions.append((reference, kwargs))
        if kwargs.get("scope") != "global" or kwargs.get("allowed_sources") != {"other"}:
            raise ValueError("Unexpected credential source")
        return self.vault[reference]

    def discard(self, prepared, previous, owner, **kwargs):
        self.discards.append((copy.deepcopy(prepared), copy.deepcopy(previous)))
        if self.cleanup_hook:
            self.cleanup_hook(prepared)
        for field, reference in prepared.get("auth", {}).items():
            if (
                isinstance(reference, str) and "--model-endpoint--global--" in reference
                and reference != (previous or {}).get("auth", {}).get(field)
            ):
                self.vault.pop(reference, None)

    @contextmanager
    def installed(self):
        def module(name, **values):
            result = ModuleType(name)
            result.__dict__.update(values)
            return result

        modules = {
            "config": module(
                "config", cosmos_settings_container=SimpleNamespace(read_item=self.read, replace_item=self.write),
            ),
            "functions_appinsights": module(
                "functions_appinsights", log_event=lambda *args, **kwargs: self.logs.append((args, kwargs)),
            ),
            "functions_keyvault": module(
                "functions_keyvault",
                keyvault_model_endpoint_cleanup_helper=self.discard,
                keyvault_model_endpoint_save_helper=self.prepare,
                resolve_secret_reference_for_context=self.resolve,
                validate_secret_name_dynamic=lambda value: isinstance(value, str) and (
                    "--other--global--" in value or "--model-endpoint--global--" in value
                ),
            ),
            "functions_settings": module(
                "functions_settings",
                normalize_model_endpoints=lambda values: (copy.deepcopy(values), False),
                _get_app_settings_store=lambda: self.app_store,
            ),
            "functions_embedding_compatibility": module(
                "functions_embedding_compatibility", embedding_settings_write_guard=self.guard,
            ),
        }
        with patch.dict(sys.modules, modules):
            yield self


class EmbeddingMigrationBuilderTests(unittest.TestCase):
    def test_direct_import_preserves_models_transport_and_vector_profile(self):
        source = legacy_embedding_settings()
        original = copy.deepcopy(source)
        before = resolve_embedding_profile(source)
        updates = build_embedding_connection_migration(source)
        endpoint = selected_endpoint(updates)
        model = endpoint["models"][0]
        after = resolve_embedding_profile({**source, **updates})
        self.assertEqual(source["azure_openai_embedding_endpoint"], endpoint["connection"]["endpoint"])
        self.assertEqual({"type": "api_key", "api_key": "synthetic-embedding-key"}, endpoint["auth"])
        self.assertEqual({
            "api": "azure_openai", "api_version": "2024-05-01-preview", "is_apim": False,
        }, endpoint["connection"]["operation_settings"][EMBEDDINGS_CAPABILITY])
        self.assertEqual({
            "subscription_id": "synthetic-subscription", "resource_group": "synthetic-resource-group",
        }, endpoint["management"])
        for field, value in source["embedding_model"]["selected"][0].items():
            self.assertEqual(value, model[field])
        self.assertEqual("legacy_embedding_direct", endpoint["migration_source"])
        self.assertEqual({"mode": "disabled"}, endpoint["identity_header"])
        self.assertEqual([EMBEDDINGS_CAPABILITY], model["enabled_capabilities"])
        self.assertTrue(model["supportsEmbeddings"])
        self.assertTrue(supports_model_capability(model, EMBEDDINGS_CAPABILITY))
        self.assertFalse(supports_model_capability(model, "chat"))
        self.assertFalse(supports_model_capability(model, "image_generation"))
        self.assertFalse(endpoint["models"][1]["enabled"])
        self.assertTrue(endpoint["models"][1]["supportsEmbeddings"])
        self.assertEqual(before.as_state(), updates[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertEqual(before.profile_id, after.profile_id)
        self.assertEqual(before.legacy, after.legacy)
        self.assertTrue(after.legacy)
        self.assertEqual(1536, after.dimensions)
        self.assertIsNone(after.policy["request_dimensions"])
        self.assertNotIn("embedding_config", model)
        self.assertNotIn("enable_multi_model_endpoints", updates)
        self.assertNotIn("azure_openai_embedding_key", updates)
        self.assertEqual(original, source)

    def test_known_large_model_keeps_native_dimensions_without_requesting_resize(self):
        source = legacy_embedding_settings()
        source["embedding_model"]["selected"][0]["modelName"] = "text-embedding-3-large"
        updates = build_embedding_connection_migration(source)
        profile = resolve_embedding_profile({**source, **updates})
        self.assertEqual(3072, profile.dimensions)
        self.assertIsNone(profile.policy["request_dimensions"])
        self.assertEqual(3072, updates[EMBEDDING_VECTOR_PROFILE_KEY]["dimensions"])

    def test_unknown_model_gets_explicit_conservative_limits_without_dimensions_parameter(self):
        source = legacy_embedding_settings()
        source["embedding_model"] = {"selected": [{"deploymentName": "private-vectors"}], "all": []}
        before = resolve_embedding_profile(source)
        updates = build_embedding_connection_migration(source)
        model = selected_endpoint(updates)["models"][0]
        self.assertEqual({"dimensions": 1536, "max_input_tokens": 8192}, model["embedding_config"])
        self.assertNotIn("embedding_legacy", model)
        after = resolve_embedding_profile({**source, **updates})
        self.assertEqual(before.profile_id, after.profile_id)
        self.assertEqual(before.legacy, after.legacy)
        self.assertEqual(before.policy, after.policy)
        self.assertIsNone(after.policy["request_dimensions"])
        self.assertTrue(supports_model_capability(model, EMBEDDINGS_CAPABILITY))

    def test_legacy_context_aliases_preserve_known_and_unknown_model_input_limits(self):
        cases = (
            ({"context_window": "4096", "contextWindow": 2048}, 4096),
            ({"context_window": 0, "contextWindow": "invalid", "maxContextTokens": "3072"}, 3072),
            ({"context_length": 16384}, 16384),
            ({"contextLength": 8192, "maxTokens": "1024", "embedding_config": {"max_input_tokens": 2048}}, 2048),
        )
        for known in (True, False):
            for metadata, expected_limit in cases:
                with self.subTest(known=known, metadata=metadata):
                    source = legacy_embedding_settings()
                    legacy_model = source["embedding_model"]["selected"][0]
                    if not known:
                        legacy_model["modelName"] = "private-vector-model"
                    legacy_model.update(copy.deepcopy(metadata))
                    original = copy.deepcopy(source)
                    before = resolve_embedding_profile(source)
                    updates = build_embedding_connection_migration(source)
                    model = selected_endpoint(updates)["models"][0]
                    after = resolve_embedding_profile({**source, **updates})
                    self.assertEqual(expected_limit, before.policy["max_input_tokens"])
                    self.assertEqual(before.policy, after.policy)
                    self.assertEqual(before.profile_id, after.profile_id)
                    self.assertEqual(before.legacy, after.legacy)
                    self.assertIsNone(after.policy["request_dimensions"])
                    for field, value in metadata.items():
                        if field != "embedding_config":
                            self.assertEqual(value, model[field])
                    if known:
                        self.assertEqual(metadata.get("embedding_config"), model.get("embedding_config"))
                        self.assertNotIn("dimensions", model.get("embedding_config", {}))
                    else:
                        self.assertEqual(expected_limit, model["embedding_config"]["max_input_tokens"])
                        self.assertEqual(1536, model["embedding_config"]["dimensions"])
                    self.assertEqual(original, source)

    def test_oversized_legacy_context_is_not_clamped_or_replaced_by_a_later_alias(self):
        for known in (True, False):
            with self.subTest(known=known):
                source = legacy_embedding_settings()
                model = source["embedding_model"]["selected"][0]
                if not known:
                    model["modelName"] = "private-vector-model"
                model.update(context_window=1048577, maxTokens=4096)
                original = copy.deepcopy(source)
                with self.assertRaises(ValueError):
                    build_embedding_connection_migration(source)
                self.assertEqual(original, source)
                self.assertFalse(embedding_settings_use_connections(source))

    def test_both_sources_import_and_only_active_apim_is_selected(self):
        source = with_gateway(legacy_embedding_settings())
        before = resolve_embedding_profile(source)
        updates = build_embedding_connection_migration(source)
        self.assertEqual(2, len(updates["model_endpoints"]))
        endpoint = selected_endpoint(updates)
        self.assertEqual("legacy_embedding_apim", endpoint["migration_source"])
        self.assertEqual(source["azure_apim_embedding_endpoint"], endpoint["connection"]["endpoint"])
        self.assertEqual("gateway-vectors", endpoint["models"][0]["deploymentName"])
        self.assertEqual("synthetic-gateway-key", endpoint["auth"]["api_key"])
        self.assertEqual({
            "api": "azure_openai", "api_version": "2025-04-01-preview",
            "is_apim": True, "auth_header": "api-key",
        }, endpoint["connection"]["operation_settings"][EMBEDDINGS_CAPABILITY])
        self.assertEqual(before.as_state(), updates[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertIsNone(resolve_embedding_profile({**source, **updates}).policy["request_dimensions"])

    def test_apim_preserves_selected_legacy_context_without_inheriting_direct_model_identity(self):
        for alias_limit, canonical_limit, expected in (
            ("4096", None, 4096), ("16384", None, 16384), ("16384", 2048, 2048),
        ):
            with self.subTest(alias_limit=alias_limit, canonical_limit=canonical_limit):
                source = with_gateway(legacy_embedding_settings())
                source["azure_openai_embedding_endpoint"] = ""
                legacy_model = source["embedding_model"]["selected"][0]
                legacy_model.update(modelName="text-embedding-3-large", modelVersion="7")
                legacy_model["context_window"] = alias_limit
                legacy_model["embedding_config"] = {
                    "dimensions": 1024, "max_batch_size": 2, "max_batch_tokens": 32768,
                    "model_revision": "direct-only-revision",
                    "document_prefix": "direct document: ", "query_prefix": "direct query: ",
                    "openai_compatible": False,
                }
                if canonical_limit is not None:
                    legacy_model["embedding_config"]["max_input_tokens"] = canonical_limit
                original = copy.deepcopy(source)
                planned_endpoint, _ = _legacy_embedding_connection(source, True)
                planned_model = planned_endpoint["models"][0]
                self.assertEqual(
                    {"dimensions": 1536, "max_input_tokens": expected},
                    planned_model["embedding_config"],
                )
                self.assertNotIn("modelName", planned_model)
                before = resolve_embedding_profile(source)
                self.assertEqual(expected, before.policy["max_input_tokens"])
                updates = build_embedding_connection_migration(source)
                endpoint = selected_endpoint(updates)
                model = endpoint["models"][0]
                after = resolve_embedding_profile({**source, **updates})
                self.assertEqual(1, len(updates["model_endpoints"]))
                self.assertEqual("legacy_embedding_apim", endpoint["migration_source"])
                self.assertEqual("gateway-vectors", model["deploymentName"])
                self.assertNotIn("modelName", model)
                self.assertNotIn("modelVersion", model)
                self.assertEqual(expected, model["context_window"])
                self.assertEqual({"dimensions": 1536, "max_input_tokens": expected}, model["embedding_config"])
                self.assertEqual(before.policy, after.policy)
                self.assertEqual(before.profile_id, after.profile_id)
                self.assertEqual(before.legacy, after.legacy)
                self.assertEqual(1536, after.dimensions)
                self.assertEqual(16, after.policy["max_batch_size"])
                self.assertEqual(expected * 16, after.policy["max_batch_tokens"])
                self.assertEqual("", after.policy["model_revision"])
                self.assertEqual("", after.policy["document_prefix"])
                self.assertEqual("", after.policy["query_prefix"])
                self.assertIsNone(after.policy["request_dimensions"])
                self.assertEqual(original, source)

    def test_apim_rejects_an_oversized_first_positive_legacy_context_alias(self):
        source = with_gateway(legacy_embedding_settings())
        source["azure_openai_embedding_endpoint"] = ""
        source["embedding_model"]["selected"][0].update(context_window=1048577, maxTokens=4096)
        original = copy.deepcopy(source)
        with self.assertRaises(ValueError):
            build_embedding_connection_migration(source)
        self.assertEqual(original, source)
        self.assertFalse(embedding_settings_use_connections(source))

    def test_inactive_apim_is_imported_without_changing_the_active_direct_route(self):
        source = with_gateway(legacy_embedding_settings(), active=False)
        updates = build_embedding_connection_migration(source)
        self.assertEqual(2, len(updates["model_endpoints"]))
        self.assertEqual("legacy_embedding_direct", selected_endpoint(updates)["migration_source"])
        self.assertNotIn("enable_embedding_apim", updates)

    def test_managed_identity_does_not_copy_a_stale_api_key_or_enable_identity_headers(self):
        for globally_enabled in (False, True):
            with self.subTest(globally_enabled=globally_enabled):
                source = legacy_embedding_settings()
                source["azure_openai_embedding_authentication_type"] = "managed_identity"
                source["model_endpoint_identity_header_enabled"] = globally_enabled
                endpoint = selected_endpoint(build_embedding_connection_migration(source))
                self.assertEqual({"type": "managed_identity"}, endpoint["auth"])
                self.assertEqual({"mode": "disabled"}, endpoint["identity_header"])
                self.assertEqual("synthetic-embedding-key", source["azure_openai_embedding_key"])

    def test_deterministic_ids_and_independent_completion_are_idempotent(self):
        source = legacy_embedding_settings()
        source[IMAGE_MIGRATION_VERSION_KEY] = 1
        first = build_embedding_connection_migration(source)
        self.assertEqual(first, build_embedding_connection_migration(source))
        self.assertIsNone(build_embedding_connection_migration({**source, **first}))
        newer = {**source, EMBEDDING_MIGRATION_VERSION_KEY: 2}
        self.assertIsNone(build_embedding_connection_migration(newer))
        for invalid_marker in (True, "1", 0):
            self.assertIsNotNone(build_embedding_connection_migration({
                **source, EMBEDDING_MIGRATION_VERSION_KEY: invalid_marker,
            }))

    def test_endpoint_and_model_ids_do_not_depend_on_rotating_credentials(self):
        source = legacy_embedding_settings()
        first = build_embedding_connection_migration(source)
        source["azure_openai_embedding_key"] = "rotated-synthetic-key"
        second = build_embedding_connection_migration(source)
        self.assertEqual(first[EMBEDDING_SELECTION_KEY], second[EMBEDDING_SELECTION_KEY])
        self.assertNotEqual(selected_endpoint(first)["auth"], selected_endpoint(second)["auth"])

    def test_compatible_connection_reuses_ids_without_overwriting_chat_configuration(self):
        source = legacy_embedding_settings()
        model = copy.deepcopy(source["embedding_model"]["selected"][0])
        model.update(id="existing-model", enabled=True, supportsEmbeddings=True)
        source["model_endpoints"] = [{
            "id": "shared-connection",
            "name": "Retained team connection",
            "enabled": True,
            "identity_header": {"mode": "disabled"},
            "connection": {
                "endpoint": source["azure_openai_embedding_endpoint"],
                "openai_api_version": "2023-05-15",
                "operation_settings": {"chat": {"api_version": "2023-05-15"}},
            },
            "auth": {"type": "api_key", "api_key": source["azure_openai_embedding_key"]},
            "models": [model],
        }]
        original = copy.deepcopy(source)
        updates = build_embedding_connection_migration(source)
        self.assertEqual(1, len(updates["model_endpoints"]))
        self.assertEqual({
            "endpoint_id": "shared-connection", "model_id": "existing-model", "provider": "aoai",
        }, updates[EMBEDDING_SELECTION_KEY])
        endpoint = selected_endpoint(updates)
        self.assertEqual("Retained team connection", endpoint["name"])
        self.assertEqual("2023-05-15", endpoint["connection"]["openai_api_version"])
        self.assertEqual({"api_version": "2023-05-15"}, endpoint["connection"]["operation_settings"]["chat"])
        self.assertNotIn("enabled_capabilities", endpoint["models"][0])
        self.assertEqual(0, updates[EMBEDDING_MIGRATION_NOTICE_KEY]["imported_connections"])
        self.assertEqual(original, source)

    def test_model_without_id_can_reuse_its_deployment_name(self):
        source = legacy_embedding_settings()
        endpoint = selected_endpoint(build_embedding_connection_migration(source))
        endpoint["id"] = "old-connection"
        endpoint["models"][0].pop("id")
        source["model_endpoints"] = [endpoint]
        updates = build_embedding_connection_migration(source)
        self.assertEqual("old-connection", updates[EMBEDDING_SELECTION_KEY]["endpoint_id"])
        self.assertEqual("knowledge-vectors", updates[EMBEDDING_SELECTION_KEY]["model_id"])

    def test_empty_operation_profile_is_filled_without_losing_legacy_api_version(self):
        source = legacy_embedding_settings()
        source["azure_openai_embedding_api_version"] = "2025-04-01-preview"
        endpoint = selected_endpoint(build_embedding_connection_migration(source))
        endpoint["id"] = "existing-connection"
        endpoint["connection"]["operation_settings"][EMBEDDINGS_CAPABILITY] = {}
        source["model_endpoints"] = [endpoint]
        updates = build_embedding_connection_migration(source)
        self.assertEqual(1, len(updates["model_endpoints"]))
        self.assertEqual("existing-connection", updates[EMBEDDING_SELECTION_KEY]["endpoint_id"])
        self.assertEqual(
            "2025-04-01-preview",
            selected_endpoint(updates)["connection"]["operation_settings"][EMBEDDINGS_CAPABILITY]["api_version"],
        )

    def test_ambiguous_existing_model_ids_are_not_reused(self):
        source = legacy_embedding_settings()
        existing = selected_endpoint(build_embedding_connection_migration(source))
        existing["id"] = "ambiguous-connection"
        existing["models"][1]["id"] = existing["models"][0]["id"]
        source["model_endpoints"] = [existing]
        updates = build_embedding_connection_migration(source)
        self.assertEqual(2, len(updates["model_endpoints"]))
        self.assertNotEqual("ambiguous-connection", updates[EMBEDDING_SELECTION_KEY]["endpoint_id"])

    def test_connections_with_different_auth_transport_identity_or_model_policy_are_not_merged(self):
        mutations = {
            "credentials": lambda item: item["auth"].update(api_key="other-synthetic-key"),
            "managed_identity": lambda item: item["auth"].update(managed_identity_client_id="another-identity"),
            "tenant": lambda item: item["auth"].update(tenant_id="another-tenant"),
            "identity_header": lambda item: item.update(identity_header={"mode": "enabled"}),
            "identity_inheritance": lambda item: item.pop("identity_header"),
            "disabled_connection": lambda item: item.update(enabled=False),
            "endpoint_path": lambda item: item["connection"].update(endpoint="https://vectors.example.test/another"),
            "api_version": lambda item: item["connection"]["operation_settings"]["embeddings"].update(api_version="2025-01-01"),
            "api": lambda item: item["connection"]["operation_settings"]["embeddings"].update(api="openai"),
            "gateway": lambda item: item["connection"]["operation_settings"]["embeddings"].update(is_apim=True),
            "header": lambda item: item["connection"]["operation_settings"]["embeddings"].update(auth_header="authorization"),
            "model": lambda item: item["models"][0].update(modelName="text-embedding-3-large"),
            "model_version": lambda item: item["models"][0].update(modelVersion="2"),
            "model_policy": lambda item: item["models"][0].update(embedding_config={"dimensions": 1024}),
            "legacy_context_limit": lambda item: item["models"][0].update(context_window=2048),
            "disabled_model": lambda item: item["models"][0].update(enabled=False),
            "unpublished": lambda item: item["models"][0].update(enabled_capabilities=[]),
            "different_import": lambda item: item.update(migration_source="legacy_image_direct"),
        }
        for case, mutate in mutations.items():
            with self.subTest(case=case):
                source = legacy_embedding_settings()
                existing = selected_endpoint(build_embedding_connection_migration(source))
                existing["id"] = "other-connection"
                mutate(existing)
                source["model_endpoints"] = [existing]
                original = copy.deepcopy(source)
                updates = build_embedding_connection_migration(source)
                self.assertEqual(2, len(updates["model_endpoints"]))
                self.assertNotEqual("other-connection", updates[EMBEDDING_SELECTION_KEY]["endpoint_id"])
                self.assertEqual(existing, updates["model_endpoints"][0])
                self.assertEqual(original, source)

    def test_a_deterministic_id_collision_is_not_overwritten(self):
        source = legacy_embedding_settings()
        existing = selected_endpoint(build_embedding_connection_migration(source))
        existing["auth"]["api_key"] = "another-synthetic-key"
        source["model_endpoints"] = [existing]
        original = copy.deepcopy(source)
        with self.assertRaises(AIConnectionError):
            build_embedding_connection_migration(source)
        self.assertEqual(original, source)

    def test_empty_configuration_creates_no_connections_or_inferred_baseline(self):
        updates = build_embedding_connection_migration({"model_endpoints": []})
        self.assertEqual([], updates["model_endpoints"])
        self.assertEqual(EMPTY_MODEL_SELECTION, updates[EMBEDDING_SELECTION_KEY])
        self.assertNotIn(EMBEDDING_VECTOR_PROFILE_KEY, updates)
        self.assertNotIn("enable_multi_model_endpoints", updates)

    def test_an_incomplete_inactive_gateway_does_not_create_an_empty_connection(self):
        source = legacy_embedding_settings()
        source["azure_apim_embedding_endpoint"] = "https://unused.example.test"
        updates = build_embedding_connection_migration(source)
        self.assertEqual(1, len(updates["model_endpoints"]))
        self.assertTrue(all(endpoint["models"] for endpoint in updates["model_endpoints"]))

    def test_incomplete_or_malformed_active_configuration_never_becomes_an_empty_shared_default(self):
        invalid = (
            {"azure_openai_embedding_endpoint": ""},
            {"embedding_model": {"selected": [], "all": []}},
            {"embedding_model": {"selected": "not-a-list"}},
            {"embedding_model": {"selected": {}, "all": []}},
            {"embedding_model": {"selected": [{"deploymentName": ""}]}},
            {"embedding_model": {"selected": [{"deploymentName": 42}]}},
            {"embedding_model": {"selected": [None]}},
            {"embedding_model": "invalid-model-catalog"},
            {"azure_openai_embedding_key": ""},
            {"azure_openai_embedding_authentication_type": "unsupported"},
            {"azure_openai_embedding_endpoint": "not-an-endpoint"},
            {"azure_openai_embedding_endpoint": "https://vectors.example.test?credential=not-a-secret"},
            {"azure_openai_embedding_endpoint": "https://vectors.example.test:invalid"},
            {"azure_openai_embedding_api_version": "not-a-version"},
            {"enable_embedding_apim": True},
            {"model_endpoints": {}},
            {"model_endpoints": ""},
            {"model_endpoints": ["invalid-entry"]},
        )
        for change in invalid:
            with self.subTest(change=change):
                source = {**legacy_embedding_settings(), **change}
                original = copy.deepcopy(source)
                with self.assertRaises(AIConnectionError):
                    build_embedding_connection_migration(source)
                self.assertEqual(original, source)
                self.assertFalse(embedding_settings_use_connections(source))

    def test_explicit_shared_clear_and_completed_import_never_restore_legacy_fallback(self):
        for shared in ({EMBEDDING_SELECTION_KEY: {}}, {EMBEDDING_MIGRATION_VERSION_KEY: 1}):
            with self.subTest(shared=shared):
                source = {**legacy_embedding_settings(), **shared}
                updates = build_embedding_connection_migration(source)
                self.assertNotIn(EMBEDDING_SELECTION_KEY, updates or {})
                self.assertNotIn("model_endpoints", updates or {})
                self.assertTrue(embedding_settings_use_connections(source))
                with self.assertRaises(AIConnectionError):
                    resolve_embedding_profile({**source, **(updates or {})})

    def test_existing_vector_baseline_is_preserved_exactly(self):
        source = legacy_embedding_settings()
        baseline = {**resolve_embedding_profile(source).as_state(), "retained_metadata": "keep"}
        source[EMBEDDING_VECTOR_PROFILE_KEY] = baseline
        updates = build_embedding_connection_migration(source)
        self.assertNotIn(EMBEDDING_VECTOR_PROFILE_KEY, updates)
        self.assertEqual(baseline, source[EMBEDDING_VECTOR_PROFILE_KEY])

    def test_a_conflicting_existing_baseline_blocks_import_without_rewriting_legacy_status(self):
        for override in (
            {"id": "another-vector-profile"}, {"legacy": False},
            {"legacy": 1}, {"legacy": "true"},
        ):
            with self.subTest(override=override):
                source = legacy_embedding_settings()
                source[EMBEDDING_VECTOR_PROFILE_KEY] = {
                    **resolve_embedding_profile(source).as_state(), **override,
                }
                original = copy.deepcopy(source)
                with self.assertRaises(AIConnectionError):
                    build_embedding_connection_migration(source)
                self.assertEqual(original, source)
                self.assertFalse(embedding_settings_use_connections(source))

    def test_later_model_changes_do_not_inherit_the_imported_legacy_status(self):
        source = legacy_embedding_settings()
        shared = {**source, **build_embedding_connection_migration(source)}
        baseline = copy.deepcopy(shared[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertTrue(resolve_embedding_profile(shared).legacy)
        endpoint = selected_endpoint(shared)
        endpoint["models"][0]["modelVersion"] = "another-revision"
        changed = resolve_embedding_profile(shared)
        self.assertNotEqual(baseline["id"], changed.profile_id)
        self.assertFalse(changed.legacy)
        self.assertEqual("legacy_embedding_direct", endpoint["migration_source"])
        self.assertEqual(baseline, shared[EMBEDDING_VECTOR_PROFILE_KEY])
        self.assertIsNone(build_embedding_connection_migration(shared))

    def test_normalization_cannot_silently_enable_a_dimensions_request(self):
        source = legacy_embedding_settings()

        def normalize(endpoint):
            endpoint = copy.deepcopy(endpoint)
            endpoint["models"][0]["embedding_config"] = {"dimensions": 1536}
            return endpoint

        with self.assertRaises(AIConnectionError):
            build_embedding_connection_migration(source, normalize)

    def test_normalization_cannot_silently_change_legacy_context_limits(self):
        source = legacy_embedding_settings()
        source["embedding_model"]["selected"][0]["context_window"] = 4096

        def normalize(endpoint):
            endpoint = copy.deepcopy(endpoint)
            endpoint["models"][0]["context_window"] = 2048
            return endpoint

        with self.assertRaises(AIConnectionError):
            build_embedding_connection_migration(source, normalize)

    def test_image_and_embedding_builders_preserve_each_others_defaults_and_models(self):
        source = {**legacy_image_settings(), **legacy_embedding_settings()}
        image_updates = build_image_connection_migration(source)
        after_image = {**source, **image_updates}
        embedding_updates = build_embedding_connection_migration(after_image)
        combined = {**after_image, **embedding_updates}
        self.assertEqual(image_updates[IMAGE_SELECTION_KEY], combined[IMAGE_SELECTION_KEY])
        self.assertEqual(image_updates[MIGRATION_NOTICE_KEY], combined[MIGRATION_NOTICE_KEY])
        self.assertEqual(image_updates["model_endpoints"][0], combined["model_endpoints"][0])
        self.assertEqual(2, len(combined["model_endpoints"]))
        self.assertIsNone(build_image_connection_migration(combined))
        self.assertIsNone(build_embedding_connection_migration(combined))
        self.assertIsNotNone(build_image_connection_migration({
            **source, EMBEDDING_MIGRATION_VERSION_KEY: 1,
        }))


class EmbeddingMigrationCoordinatorTests(unittest.TestCase):
    def test_explicit_shared_clear_only_stamps_its_marker_without_preparing_legacy_data(self):
        source = {
            **legacy_embedding_settings(), EMBEDDING_SELECTION_KEY: {},
            "model_endpoints": {"unparsed": "retained"}, "embedding_model": "unparsed",
        }
        stages = []
        result = migrate_embedding_connections(
            lambda: copy.deepcopy(source), lambda candidate, etag: candidate,
            lambda *args: stages.append(args),
        )
        self.assertEqual([], stages)
        self.assertEqual(1, result[EMBEDDING_MIGRATION_VERSION_KEY])
        self.assertEqual({}, result[EMBEDDING_SELECTION_KEY])
        self.assertEqual(source["model_endpoints"], result["model_endpoints"])
        self.assertEqual(source["azure_openai_embedding_key"], result["azure_openai_embedding_key"])

    def test_missing_etag_prevents_preparing_credentials_or_writing(self):
        source = legacy_embedding_settings()
        source.pop("_etag")
        calls = []
        with self.assertRaises(AIConnectionError):
            migrate_embedding_connections(
                lambda: source, lambda *args: calls.append(args),
                lambda *args: calls.append(args),
            )
        self.assertEqual([], calls)

    def test_conflict_reloads_the_latest_settings_before_retrying(self):
        store = legacy_embedding_settings()
        writes = []
        discarded = []

        def write(candidate, etag):
            writes.append(etag)
            if len(writes) == 1:
                store["_etag"] = "revision-2"
                store["concurrent_admin_value"] = "keep me"
                raise EmbeddingMigrationConflict()
            self.assertEqual(store["_etag"], etag)
            store.update(copy.deepcopy(candidate))
            return copy.deepcopy(store)

        result = migrate_embedding_connections(
            lambda: copy.deepcopy(store), write, lambda endpoint, previous: endpoint,
            discard_endpoint=lambda *args: discarded.append(args),
        )
        self.assertEqual(["revision-1", "revision-2"], writes)
        self.assertEqual("keep me", result["concurrent_admin_value"])
        self.assertEqual(1, len(result["model_endpoints"]))
        self.assertEqual(1, len(discarded))
        self.assertEqual("synthetic-embedding-key", result["azure_openai_embedding_key"])

    def test_repeated_conflicts_are_bounded_and_never_become_unconditional_writes(self):
        writes = []
        discarded = []

        def write(_candidate, etag):
            writes.append(etag)
            raise ImageMigrationConflict()

        with self.assertRaises(AIConnectionError):
            migrate_embedding_connections(
                legacy_embedding_settings, write, lambda endpoint, previous: endpoint,
                attempts=2, discard_endpoint=lambda *args: discarded.append(args),
            )
        self.assertEqual(["revision-1", "revision-1"], writes)
        self.assertEqual(2, len(discarded))

    def test_preparation_failure_discards_only_this_attempts_completed_stages(self):
        for error_type in (RuntimeError, ValueError, FakeAzureError):
            with self.subTest(error_type=error_type):
                source = with_gateway(legacy_embedding_settings())
                original = copy.deepcopy(source)
                vault = {"legacy-reference": "retained-legacy-key"}
                save = load_secret_save_helper(vault)
                writes = []

                def prepare(endpoint, previous):
                    if endpoint["migration_source"] == "legacy_embedding_apim":
                        raise error_type("Synthetic staging failure")
                    return save(endpoint, endpoint["id"], existing_endpoint=previous, stage_new_secrets=True)

                with self.assertRaises(error_type):
                    migrate_embedding_connections(
                        lambda: copy.deepcopy(source), lambda *args: writes.append(args), prepare,
                        discard_endpoint=lambda endpoint, previous: vault.pop(endpoint["auth"]["api_key"]),
                    )
                self.assertEqual([], writes)
                self.assertEqual({"legacy-reference": "retained-legacy-key"}, vault)
                self.assertEqual(original, source)

    def test_losing_worker_cannot_rotate_or_delete_the_winners_credentials(self):
        store = legacy_embedding_settings()
        vault = {"legacy-reference": "retained-legacy-key"}
        save = load_secret_save_helper(vault)
        interleaved = False
        discarded = []

        def prepare(endpoint, previous):
            return save(endpoint, endpoint["id"], existing_endpoint=previous, stage_new_secrets=True)

        def write(candidate, etag):
            if etag != store["_etag"]:
                raise EmbeddingMigrationConflict()
            store.clear()
            store.update(copy.deepcopy(candidate))
            store["_etag"] = "committed-revision"
            return copy.deepcopy(store)

        def late_prepare(endpoint, previous):
            nonlocal interleaved
            if not interleaved:
                interleaved = True
                store["_etag"] = "concurrent-revision"
                store["azure_openai_embedding_key"] = "newer-synthetic-key"
                migrate_embedding_connections(lambda: copy.deepcopy(store), write, prepare)
            return prepare(endpoint, previous)

        def discard(endpoint, previous):
            reference = endpoint["auth"]["api_key"]
            discarded.append(reference)
            vault.pop(reference)

        result = migrate_embedding_connections(
            lambda: copy.deepcopy(store), write, late_prepare, discard_endpoint=discard,
        )
        winning_reference = selected_endpoint(result)["auth"]["api_key"]
        self.assertEqual("newer-synthetic-key", vault[winning_reference])
        self.assertNotIn(winning_reference, discarded)
        self.assertEqual(1, len(discarded))
        self.assertEqual("retained-legacy-key", vault["legacy-reference"])
        self.assertEqual(2, len(vault))

    def test_unknown_write_outcome_retains_possibly_committed_staged_credentials(self):
        vault = {}
        save = load_secret_save_helper(vault)
        discarded = []

        def write(_candidate, _etag):
            raise RuntimeError("The settings-write outcome is unknown")

        with self.assertRaises(RuntimeError):
            migrate_embedding_connections(
                legacy_embedding_settings, write,
                lambda endpoint, previous: save(
                    endpoint, endpoint["id"], existing_endpoint=previous, stage_new_secrets=True,
                ),
                discard_endpoint=lambda *args: discarded.append(args),
            )
        self.assertEqual([], discarded)
        self.assertEqual(1, len(vault))


class EmbeddingMigrationInitializationTests(unittest.TestCase):
    def test_completed_image_import_does_not_skip_embedding_import(self):
        source = {**legacy_embedding_settings(), IMAGE_MIGRATION_VERSION_KEY: 1}
        with MigrationRuntime(source).installed() as runtime:
            result = initialize_ai_connections(source)
        self.assertEqual(1, result[EMBEDDING_MIGRATION_VERSION_KEY])
        self.assertEqual(1, len(runtime.writes))
        self.assertEqual(1, len(result["model_endpoints"]))
        self.assertEqual(3, len(runtime.reads))
        self.assertEqual(result, runtime.cache_updates[-1][0])
        self.assertEqual(1, result[SETTINGS_REVISION_FIELD])
        self.assertTrue(runtime.guards[-1][2]["force_check"])

    def test_startup_imports_use_separate_transactions_and_new_etags(self):
        source = {**legacy_image_settings(), **legacy_embedding_settings()}
        with MigrationRuntime(source).installed() as runtime:
            result = initialize_ai_connections(source)
        self.assertEqual(["revision-1", "committed-1"], [etag for _, etag in runtime.writes])
        self.assertTrue(image_settings_use_connections(result))
        self.assertTrue(embedding_settings_use_connections(result))
        self.assertEqual(2, len(result["model_endpoints"]))
        self.assertEqual(source["azure_openai_image_gen_key"], result["azure_openai_image_gen_key"])

    def test_failed_image_import_keeps_its_notice_when_embedding_import_succeeds(self):
        source = {**legacy_image_settings(), **legacy_embedding_settings(), "image_gen_model": "invalid"}
        with MigrationRuntime(source).installed() as runtime:
            result = initialize_ai_connections(source)
        self.assertFalse(image_settings_use_connections(result))
        self.assertTrue(embedding_settings_use_connections(result))
        self.assertEqual("error", result[MIGRATION_NOTICE_KEY]["status"])
        self.assertEqual("complete", result[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])
        self.assertEqual(result[MIGRATION_NOTICE_KEY], runtime.cache_updates[-1][0][MIGRATION_NOTICE_KEY])
        self.assertEqual("invalid", result["image_gen_model"])

    def test_failed_embedding_staging_does_not_undo_a_completed_image_import(self):
        source = {
            **legacy_image_settings(), **legacy_embedding_settings(),
            "enable_key_vault_secret_storage": True, "key_vault_name": "synthetic-vault",
        }

        def fail_embedding(endpoint):
            if endpoint["migration_source"].startswith("legacy_embedding_"):
                raise FakeAzureError("synthetic-sensitive-provider-error")

        with MigrationRuntime(source).installed() as runtime:
            runtime.prepare_hook = fail_embedding
            result = initialize_ai_connections(source)
        self.assertTrue(image_settings_use_connections(result))
        self.assertFalse(embedding_settings_use_connections(result))
        self.assertEqual("error", result[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])
        self.assertEqual(1, len(result["model_endpoints"]))
        image_reference = result["model_endpoints"][0]["auth"]["api_key"]
        self.assertEqual("synthetic-image-key", runtime.vault[image_reference])
        self.assertEqual(source["azure_openai_embedding_key"], result["azure_openai_embedding_key"])
        self.assertNotIn("synthetic-sensitive-provider-error", str(result[EMBEDDING_MIGRATION_NOTICE_KEY]))
        self.assertNotIn("synthetic-sensitive-provider-error", str(runtime.logs))

    def test_both_failure_notices_survive_independent_reads(self):
        source = {
            **legacy_image_settings(), **legacy_embedding_settings(),
            "image_gen_model": "invalid", "embedding_model": "invalid",
        }
        with MigrationRuntime(source).installed() as runtime:
            result = initialize_ai_connections(source)
        self.assertEqual(2, len(runtime.writes))
        self.assertEqual([], runtime.settings["model_endpoints"])
        self.assertEqual("error", result[MIGRATION_NOTICE_KEY]["status"])
        self.assertEqual("error", result[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])
        self.assertNotIn(IMAGE_MIGRATION_VERSION_KEY, result)
        self.assertNotIn(EMBEDDING_MIGRATION_VERSION_KEY, result)

    def test_key_vault_sources_are_hydrated_then_staged_without_deleting_legacy_keys(self):
        source = with_gateway(legacy_embedding_settings())
        source.update({
            IMAGE_MIGRATION_VERSION_KEY: 1,
            "enable_key_vault_secret_storage": True,
            "key_vault_name": "synthetic-vault",
            "azure_openai_embedding_key": "embedding-key--other--global--direct",
            "azure_apim_embedding_subscription_key": "embedding-key--other--global--apim",
        })
        with MigrationRuntime(source).installed() as runtime:
            runtime.vault[source["azure_openai_embedding_key"]] = "synthetic-direct-secret"
            runtime.vault[source["azure_apim_embedding_subscription_key"]] = "synthetic-apim-secret"
            result = initialize_ai_connections(source)
        self.assertEqual(2, len(runtime.resolutions))
        for _, kwargs in runtime.resolutions:
            self.assertEqual({
                "scope": "global", "allowed_sources": {"other"},
                "context_label": "legacy embedding configuration",
            }, kwargs)
        self.assertEqual(2, len(runtime.stages))
        for endpoint, owner, kwargs in runtime.stages:
            self.assertEqual(endpoint["id"], owner)
            self.assertTrue(kwargs["stage_new_secrets"])
            self.assertEqual("global", kwargs["scope"])
        self.assertEqual(4, len(runtime.vault))
        self.assertEqual("synthetic-direct-secret", runtime.vault[source["azure_openai_embedding_key"]])
        self.assertEqual("synthetic-apim-secret", runtime.vault[source["azure_apim_embedding_subscription_key"]])
        self.assertEqual(source["azure_openai_embedding_key"], result["azure_openai_embedding_key"])
        self.assertEqual([], runtime.discards)
        self.assertEqual("synthetic-apim-secret", runtime.vault[selected_endpoint(result)["auth"]["api_key"]])

    def test_preparation_azure_error_cleans_prior_stages_and_cleanup_failure_is_bounded(self):
        source = with_gateway(legacy_embedding_settings())
        source.update({
            IMAGE_MIGRATION_VERSION_KEY: 1,
            "enable_key_vault_secret_storage": True, "key_vault_name": "synthetic-vault",
        })

        def fail_gateway(endpoint):
            if endpoint["migration_source"] == "legacy_embedding_apim":
                raise FakeAzureError("synthetic-private-key-store-failure")

        def fail_cleanup(endpoint):
            raise FakeAzureError("synthetic-private-cleanup-failure")

        with MigrationRuntime(source).installed() as runtime:
            runtime.prepare_hook = fail_gateway
            runtime.cleanup_hook = fail_cleanup
            result = initialize_ai_connections(source)
        self.assertEqual(1, len(runtime.discards))
        self.assertEqual(1, len(runtime.writes))
        self.assertEqual([], runtime.settings["model_endpoints"])
        self.assertFalse(embedding_settings_use_connections(result))
        self.assertEqual("error", result[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])
        self.assertNotIn("synthetic-private", str(runtime.logs))
        self.assertEqual(source["azure_openai_embedding_key"], result["azure_openai_embedding_key"])

    def test_initializer_uses_current_raw_key_vault_settings_not_stale_input(self):
        initial = {**legacy_embedding_settings(), IMAGE_MIGRATION_VERSION_KEY: 1}
        live = {
            **initial, "enable_key_vault_secret_storage": True,
            "key_vault_name": "", "concurrent_admin_value": "keep me",
        }
        with MigrationRuntime(live).installed() as runtime:
            result = initialize_ai_connections(initial)
        self.assertEqual([], runtime.stages)
        self.assertEqual(1, len(runtime.writes))
        self.assertEqual([], runtime.settings["model_endpoints"])
        self.assertEqual("keep me", result["concurrent_admin_value"])
        self.assertFalse(embedding_settings_use_connections(result))
        self.assertEqual("error", result[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])

    def test_completed_imports_are_a_noop_without_loading_startup_dependencies(self):
        source = {IMAGE_MIGRATION_VERSION_KEY: 1, EMBEDDING_MIGRATION_VERSION_KEY: 1}
        with patch.dict(sys.modules, {"config": None, "functions_settings": None}):
            self.assertIs(source, initialize_ai_connections(source))

    def test_shared_store_conflict_rebuilds_import_and_discards_only_uncommitted_credentials(self):
        source = {
            **legacy_embedding_settings(), IMAGE_MIGRATION_VERSION_KEY: 1,
            "enable_key_vault_secret_storage": True, "key_vault_name": "synthetic-vault",
        }
        with MigrationRuntime(source).installed() as runtime:
            def concurrent_admin_save(_endpoint):
                runtime.prepare_hook = None
                runtime.app_store.write(lambda current: {**current, "app_title": "Concurrent edit"})

            runtime.prepare_hook = concurrent_admin_save
            result = initialize_ai_connections(source)
        self.assertEqual("Concurrent edit", result["app_title"])
        self.assertEqual(2, result[SETTINGS_REVISION_FIELD])
        self.assertEqual(2, len(runtime.stages))
        self.assertEqual(1, len(runtime.discards))
        self.assertEqual(1, len(runtime.vault))
        self.assertIn(selected_endpoint(result)["auth"]["api_key"], runtime.vault)
        self.assertEqual(result, runtime.cache_updates[-1][0])

    def test_unconfirmed_publication_retains_credentials_and_can_be_confirmed_after_recovery(self):
        source = {
            **legacy_embedding_settings(), IMAGE_MIGRATION_VERSION_KEY: 1,
            "enable_key_vault_secret_storage": True, "key_vault_name": "synthetic-vault",
        }
        with MigrationRuntime(source).installed() as runtime:
            runtime.cache.fail_publication = True
            result = initialize_ai_connections(source)
            reference = selected_endpoint(result)["auth"]["api_key"]
            self.assertEqual(1, result[EMBEDDING_MIGRATION_VERSION_KEY])
            self.assertEqual("error", result[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])
            self.assertEqual("pending", json.loads(runtime.cache.raw)["state"])
            self.assertEqual([], runtime.cache_updates)
            self.assertEqual([], runtime.discards)
            self.assertIn(reference, runtime.vault)
            self.assertNotIn("settings are unchanged", result[EMBEDDING_MIGRATION_NOTICE_KEY]["message"])

            runtime.cache.fail_publication = False
            after_expiry = time.time() + WRITE_LEASE_SECONDS + 1
            with patch("app_settings_store.time.time", return_value=after_expiry):
                recovered = initialize_ai_connections(result)

        self.assertEqual("complete", recovered[EMBEDDING_MIGRATION_NOTICE_KEY]["status"])
        self.assertEqual(reference, selected_endpoint(recovered)["auth"]["api_key"])
        self.assertEqual(1, len(runtime.stages))
        self.assertEqual([], runtime.discards)
        self.assertEqual(2, len(runtime.guards))
        self.assertTrue(runtime.guards[-1][2]["force_check"])
        self.assertEqual(recovered, runtime.cache_updates[-1][0])


class EmbeddingRecoveryFormTests(unittest.TestCase):
    def test_unrelated_save_preserves_omitted_legacy_fields_after_failed_import(self):
        source = legacy_embedding_settings()
        source[EMBEDDING_MIGRATION_NOTICE_KEY] = {"status": "error"}
        updates = {
            "azure_openai_embedding_endpoint": "", "azure_openai_embedding_key": "",
            "azure_apim_embedding_deployment": "", "embedding_model": {"selected": [], "all": []},
            "enable_embedding_apim": False, "app_title": "Changed title",
        }
        original = copy.deepcopy(updates)
        self.assertEqual(
            {"app_title": "Changed title"},
            preserve_legacy_embedding_form_settings(updates, {"app_title": "Changed title"}, source),
        )
        self.assertEqual(original, updates)
        self.assertEqual("synthetic-embedding-key", source["azure_openai_embedding_key"])

    def test_explicit_recovery_edits_and_clears_preserve_other_omitted_fields(self):
        updates = {
            "azure_openai_embedding_endpoint": "", "azure_openai_embedding_key": "",
            "embedding_model": {"selected": [], "all": []}, "enable_embedding_apim": False,
        }
        submitted = {"azure_openai_embedding_endpoint": "", "embedding_model_json": "{}"}
        preserved = preserve_legacy_embedding_form_settings(updates, submitted, legacy_embedding_settings())
        self.assertEqual("", preserved["azure_openai_embedding_endpoint"])
        self.assertEqual({"selected": [], "all": []}, preserved["embedding_model"])
        self.assertFalse(preserved["enable_embedding_apim"])
        self.assertNotIn("azure_openai_embedding_key", preserved)

    def test_managed_or_explicitly_cleared_default_ignores_even_posted_recovery_controls(self):
        for state in ({EMBEDDING_SELECTION_KEY: {}}, {EMBEDDING_MIGRATION_VERSION_KEY: 1}):
            updates = {
                "azure_openai_embedding_endpoint": "https://stale.example.test",
                "azure_openai_embedding_key": "stale-synthetic-key",
                "embedding_model": {"selected": [], "all": []},
                "enable_embedding_apim": True, "app_title": "Changed title",
            }
            self.assertEqual(
                {"app_title": "Changed title"},
                preserve_legacy_embedding_form_settings(
                    updates, {**updates, "embedding_model_json": "{}"},
                    {**legacy_embedding_settings(), **state},
                ),
            )


if __name__ == "__main__":
    unittest.main()
