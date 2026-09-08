# test_ai_connection_image_migration.py
"""
Functional coverage for automatic image-connection import.
Version: 0.261.102
Implemented in: 0.261.102

Exercise the real migration builder and optimistic-concurrency coordinator without
Azure services, including active-route preservation and non-destructive failure.
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_ai_connection_migration import (
    ImageMigrationConflict,
    build_image_connection_migration,
    migrate_image_connections,
    preserve_legacy_image_form_settings,
)
from functions_ai_connections import (
    AIConnectionError,
    IMAGE_MIGRATION_VERSION_KEY,
    IMAGE_SELECTION_KEY,
    supports_model_capability,
)


def legacy_settings():
    return {
        "id": "app_settings",
        "_etag": "revision-1",
        "enable_image_generation": True,
        "enable_multi_model_endpoints": False,
        "azure_openai_image_gen_endpoint": "https://images.example.test",
        "azure_openai_image_gen_authentication_type": "key",
        "azure_openai_image_gen_key": "synthetic-image-key",
        "azure_openai_image_gen_api_version": "2024-12-01-preview",
        "image_gen_model": {
            "selected": [{"deploymentName": "creative", "modelName": "gpt-5.6-terra"}],
            "all": [
                {"deploymentName": "creative", "modelName": "gpt-5.6-terra"},
                {"deploymentName": "pixels", "modelName": "gpt-image-1"},
            ],
        },
        "model_endpoints": [],
    }


class ImageConnectionMigrationTests(unittest.TestCase):
    def test_unrelated_form_save_cannot_erase_failed_import_recovery_settings(self):
        source = legacy_settings()
        source["ai_connections_image_migration_notice"] = {"status": "error", "message": "Import failed"}
        updates = {
            "azure_openai_image_gen_endpoint": "",
            "azure_openai_image_gen_key": "",
            "azure_apim_image_gen_deployment": "",
            "image_gen_model": {"selected": [], "all": []},
            "enable_image_gen_apim": False,
            "app_title": "Changed title",
        }
        preserved = preserve_legacy_image_form_settings(updates, {"app_title": "Changed title"}, source)
        self.assertEqual({"app_title": "Changed title"}, preserved)
        self.assertEqual("creative", source["image_gen_model"]["selected"][0]["deploymentName"])
        self.assertEqual("synthetic-image-key", source["azure_openai_image_gen_key"])
        self.assertEqual("", updates["azure_openai_image_gen_endpoint"])

    def test_recovery_form_preserves_omitted_fields_but_accepts_explicit_clears(self):
        updates = {
            "azure_openai_image_gen_endpoint": "",
            "azure_openai_image_gen_key": "",
            "image_gen_model": {"selected": [], "all": []},
            "enable_image_gen_apim": False,
        }
        submitted = {"azure_openai_image_gen_endpoint": "", "image_gen_model_json": "{}"}
        preserved = preserve_legacy_image_form_settings(updates, submitted, legacy_settings())
        self.assertEqual("", preserved["azure_openai_image_gen_endpoint"])
        self.assertEqual({"selected": [], "all": []}, preserved["image_gen_model"])
        self.assertFalse(preserved["enable_image_gen_apim"])
        self.assertNotIn("azure_openai_image_gen_key", preserved)

    def test_shared_selection_ignores_all_legacy_recovery_fields_even_when_posted(self):
        settings = {**legacy_settings(), IMAGE_SELECTION_KEY: {}}
        updates = {"azure_openai_image_gen_endpoint": "https://old.example.test", "enable_image_generation": True}
        self.assertEqual(
            {"enable_image_generation": True},
            preserve_legacy_image_form_settings(updates, updates, settings),
        )

    def test_active_model_and_credentials_survive_without_changing_chat_mode(self):
        source = legacy_settings()
        original = copy.deepcopy(source)
        updates = build_image_connection_migration(source)
        endpoint = updates["model_endpoints"][0]
        selection = updates[IMAGE_SELECTION_KEY]
        model = next(item for item in endpoint["models"] if item["id"] == selection["model_id"])
        self.assertEqual("creative", model["deploymentName"])
        self.assertEqual("responses", model["image_generation_api"])
        self.assertEqual("synthetic-image-key", endpoint["auth"]["api_key"])
        self.assertEqual("api_key", endpoint["auth"]["type"])
        self.assertEqual("2024-12-01-preview", endpoint["connection"]["operation_settings"]["image_generation"]["api_version"])
        self.assertTrue(supports_model_capability(model, "image_generation"))
        self.assertFalse(supports_model_capability(model, "chat"))
        self.assertNotIn("enable_multi_model_endpoints", updates)
        self.assertNotIn("azure_openai_image_gen_key", updates)
        self.assertEqual(original, source)

    def test_import_ids_are_stable_and_completed_import_is_a_noop(self):
        source = legacy_settings()
        first = build_image_connection_migration(source)
        self.assertEqual(first, build_image_connection_migration(source))
        self.assertIsNone(build_image_connection_migration({**source, **first}))

    def test_a_newer_migration_marker_is_never_downgraded(self):
        source = legacy_settings()
        source[IMAGE_MIGRATION_VERSION_KEY] = 2
        self.assertIsNone(build_image_connection_migration(source))
        self.assertEqual(2, source[IMAGE_MIGRATION_VERSION_KEY])

    def test_both_routes_import_but_only_active_gateway_is_selected(self):
        source = legacy_settings()
        source.update({
            "enable_image_gen_apim": True,
            "azure_apim_image_gen_endpoint": "https://gateway.example.test/custom/images",
            "azure_apim_image_gen_deployment": "gateway-deployment",
            "azure_apim_image_gen_subscription_key": "synthetic-subscription",
            "azure_apim_image_gen_api_version": "2025-04-01-preview",
        })
        updates = build_image_connection_migration(source)
        self.assertEqual(2, len(updates["model_endpoints"]))
        selected = next(item for item in updates["model_endpoints"] if item["id"] == updates[IMAGE_SELECTION_KEY]["endpoint_id"])
        self.assertEqual(source["azure_apim_image_gen_endpoint"], selected["connection"]["endpoint"])
        self.assertEqual("synthetic-subscription", selected["auth"]["api_key"])
        profile = selected["connection"]["operation_settings"]["image_generation"]
        self.assertTrue(profile["is_apim"])
        self.assertEqual("api-key", profile["auth_header"])

    def test_reuses_compatible_connection_and_model_ids(self):
        source = legacy_settings()
        source["model_endpoints"] = [{
            "id": "shared-connection",
            "name": "Team connection",
            "provider": "aoai",
            "enabled": True,
            "connection": {"endpoint": source["azure_openai_image_gen_endpoint"], "openai_api_version": "2024-05-01-preview"},
            "auth": {"type": "api_key", "api_key": source["azure_openai_image_gen_key"], "management_cloud": "public"},
            "models": [{
                "id": "existing-model", "deploymentName": "creative", "modelName": "gpt-5.6-terra",
                "enabled": True, "supportsImageGeneration": True,
            }],
        }]

        def normalize(endpoint):
            endpoint = copy.deepcopy(endpoint)
            endpoint["auth"]["management_cloud"] = "public"
            return endpoint

        updates = build_image_connection_migration(source, normalize)
        self.assertEqual(1, len(updates["model_endpoints"]))
        self.assertEqual("shared-connection", updates[IMAGE_SELECTION_KEY]["endpoint_id"])
        self.assertEqual("existing-model", updates[IMAGE_SELECTION_KEY]["model_id"])
        self.assertEqual("2024-05-01-preview", updates["model_endpoints"][0]["connection"]["openai_api_version"])
        self.assertNotIn("enabled_capabilities", updates["model_endpoints"][0]["models"][0])

    def test_different_credentials_are_not_merged(self):
        source = legacy_settings()
        existing = copy.deepcopy(build_image_connection_migration(source)["model_endpoints"][0])
        existing["id"] = "different-auth"
        existing["auth"]["api_key"] = "a-different-synthetic-key"
        source["model_endpoints"] = [existing]
        updates = build_image_connection_migration(source)
        self.assertEqual(2, len(updates["model_endpoints"]))
        self.assertEqual("a-different-synthetic-key", updates["model_endpoints"][0]["auth"]["api_key"])

    def test_reused_legacy_model_can_lack_id_and_connection_can_lack_provider(self):
        source = legacy_settings()
        image = {"deploymentName": "pixels", "modelName": "gpt-image-1"}
        source["image_gen_model"] = {"selected": [image], "all": [image]}
        source["model_endpoints"] = [{
            "id": "old-connection",
            "connection": {"endpoint": source["azure_openai_image_gen_endpoint"]},
            "auth": {"type": "api_key", "api_key": source["azure_openai_image_gen_key"]},
            "models": [dict(image)],
        }]
        original = copy.deepcopy(source)
        updates = build_image_connection_migration(source)
        self.assertEqual(1, len(updates["model_endpoints"]))
        self.assertEqual(
            {"endpoint_id": "old-connection", "model_id": "pixels", "provider": "aoai"},
            updates[IMAGE_SELECTION_KEY],
        )
        self.assertEqual("pixels", updates["model_endpoints"][0]["models"][0]["id"])
        self.assertEqual(original, source)

    def test_empty_config_does_not_create_connections_or_enable_images(self):
        updates = build_image_connection_migration({"model_endpoints": []})
        self.assertEqual([], updates["model_endpoints"])
        self.assertEqual("", updates[IMAGE_SELECTION_KEY]["endpoint_id"])
        self.assertNotIn("enable_image_generation", updates)

    def test_explicitly_cleared_default_is_not_replaced_by_legacy(self):
        source = legacy_settings()
        source[IMAGE_SELECTION_KEY] = {}
        updates = build_image_connection_migration(source)
        self.assertNotIn(IMAGE_SELECTION_KEY, updates)
        self.assertNotIn("model_endpoints", updates)
        self.assertEqual(1, updates[IMAGE_MIGRATION_VERSION_KEY])

    def test_prepare_failure_does_not_commit_or_mutate_credentials(self):
        source = legacy_settings()
        original = copy.deepcopy(source)
        writes = []

        def prepare(_endpoint, _previous):
            raise RuntimeError("Simulated secret-store failure")

        with self.assertRaises(RuntimeError):
            migrate_image_connections(
                lambda: copy.deepcopy(source), lambda *args: writes.append(args), prepare
            )
        self.assertEqual([], writes)
        self.assertEqual(original, source)

    def test_conflict_reloads_and_preserves_concurrent_settings(self):
        store = legacy_settings()
        writes = []

        def write(candidate, etag):
            writes.append(etag)
            if len(writes) == 1:
                store["_etag"] = "revision-2"
                store["concurrent_admin_value"] = "keep me"
                raise ImageMigrationConflict()
            self.assertEqual(store["_etag"], etag)
            store.update(candidate)
            store["_etag"] = "revision-3"
            return copy.deepcopy(store)

        result = migrate_image_connections(
            lambda: copy.deepcopy(store), write, lambda endpoint, _previous: endpoint
        )
        self.assertEqual(["revision-1", "revision-2"], writes)
        self.assertEqual("keep me", result["concurrent_admin_value"])
        self.assertEqual(1, len(result["model_endpoints"]))
        self.assertEqual("synthetic-image-key", result["azure_openai_image_gen_key"])

    def test_missing_etag_and_repeated_conflicts_do_not_fall_back_to_unconditional_writes(self):
        source = legacy_settings()
        source.pop("_etag")
        writes = []
        with self.assertRaises(AIConnectionError):
            migrate_image_connections(lambda: source, lambda *args: writes.append(args), lambda endpoint, _previous: endpoint)
        self.assertEqual([], writes)

        def conflict(_candidate, _etag):
            raise ImageMigrationConflict()

        with self.assertRaises(AIConnectionError):
            migrate_image_connections(legacy_settings, conflict, lambda endpoint, _previous: endpoint, attempts=2)


if __name__ == "__main__":
    unittest.main()
