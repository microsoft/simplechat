# test_ai_connection_credential_staging.py
"""
Functional tests for credential isolation during concurrent image imports.
Version: 0.261.102
Implemented in: 0.261.102

Run the real Key Vault save helper against an in-memory secret service. A losing
settings writer must neither overwrite nor delete the winning writer's credential.
"""

import ast
import copy
import re
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_ai_connection_migration import ImageMigrationConflict, migrate_image_connections
from functions_ai_connections import IMAGE_SELECTION_KEY
from test_ai_connection_image_migration import legacy_settings


def load_secret_save_helper(vault):
    source = APP_ROOT / "functions_keyvault.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"keyvault_model_endpoint_save_helper", "_build_model_endpoint_secret_name"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]

    def store(name, value, scope_value, *, source, scope):
        reference = f"{scope_value}--{source}--{scope}--{name}"
        vault[reference] = value
        return reference

    def valid_reference(value):
        return isinstance(value, str) and "--model-endpoint--global--" in value

    def existing_reference(endpoint, path):
        value = (endpoint or {}).get("auth", {}).get(path[1])
        return value if valid_reference(value) else None

    namespace = {
        "uuid": uuid,
        "supported_scopes": ["global"],
        "MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS": {
            "api_key": {"api_key"},
            "client_secret": {"service_principal"},
        },
        "app_settings_cache": SimpleNamespace(
            get_settings_cache=lambda: {"enable_key_vault_secret_storage": True, "key_vault_name": "synthetic-vault"}
        ),
        "log_event": lambda *_args, **_kwargs: None,
        "_get_existing_secret_reference": existing_reference,
        "validate_secret_name_dynamic": valid_reference,
        "secret_reference_matches_context": lambda value, **kwargs: value.startswith(
            f"{kwargs['scope_value']}--model-endpoint--{kwargs['scope']}--"
        ),
        "_log_secret_reference_context_mismatch": lambda *_args, **_kwargs: None,
        "clean_name_for_keyvault": lambda value: re.sub(r"[^a-zA-Z0-9-]", "-", value),
        "store_secret_in_key_vault": store,
        "ui_trigger_word": "Stored_In_KeyVault",
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["keyvault_model_endpoint_save_helper"]


class CredentialStagingTests(unittest.TestCase):
    def test_regular_callers_keep_the_existing_secret_name_contract(self):
        vault = {}
        save = load_secret_save_helper(vault)
        result = save({"auth": {"type": "api_key", "api_key": "synthetic-a"}}, "owner")
        self.assertEqual(
            "owner--model-endpoint--global--model-endpoint-api-key",
            result["auth"]["api_key"],
        )

    def test_staging_is_unique_and_keeps_scope_ownership(self):
        vault = {}
        save = load_secret_save_helper(vault)
        owner = "12345678-1234-5678-1234-567812345678"
        first = save({"auth": {"type": "api_key", "api_key": "synthetic-a"}}, owner, stage_new_secrets=True)
        second = save({"auth": {"type": "api_key", "api_key": "synthetic-b"}}, owner, stage_new_secrets=True)
        first_ref = first["auth"]["api_key"]
        second_ref = second["auth"]["api_key"]
        self.assertNotEqual(first_ref, second_ref)
        self.assertTrue(first_ref.startswith(f"{owner}--model-endpoint--global--"))
        self.assertEqual("synthetic-a", vault[first_ref])
        self.assertEqual("synthetic-b", vault[second_ref])
        self.assertLessEqual(len(first_ref), 127)

    def test_existing_reference_is_reused_without_a_new_secret(self):
        vault = {}
        save = load_secret_save_helper(vault)
        existing = save({"auth": {"type": "api_key", "api_key": "synthetic-a"}}, "owner", stage_new_secrets=True)
        result = save(existing, "owner", existing_endpoint=existing, stage_new_secrets=True)
        self.assertEqual(existing, result)
        self.assertEqual(1, len(vault))

    def test_staged_names_fit_an_identifier_that_filled_the_old_name_limit(self):
        vault = {}
        save = load_secret_save_helper(vault)
        owner = "a" * 79
        result = save({"auth": {"type": "api_key", "api_key": "synthetic-a"}}, owner, stage_new_secrets=True)
        reference = result["auth"]["api_key"]
        self.assertLessEqual(len(reference), 127)
        self.assertTrue(reference.startswith(f"{owner}--model-endpoint--global--s-"))

    def test_a_late_losing_worker_cannot_corrupt_a_committed_credential(self):
        vault = {}
        save = load_secret_save_helper(vault)
        store = legacy_settings()
        interleaved = False
        discarded = []

        def prepare(endpoint, previous):
            return save(endpoint, endpoint["id"], existing_endpoint=previous, stage_new_secrets=True)

        def write(candidate, etag):
            if etag != store["_etag"]:
                raise ImageMigrationConflict()
            store.clear()
            store.update(copy.deepcopy(candidate))
            store["_etag"] = "committed-revision"
            return copy.deepcopy(store)

        def late_prepare(endpoint, previous):
            nonlocal interleaved
            if not interleaved:
                interleaved = True
                store["_etag"] = "concurrent-revision"
                store["azure_openai_image_gen_key"] = "newer-synthetic-key"
                migrate_image_connections(lambda: copy.deepcopy(store), write, prepare)
            return prepare(endpoint, previous)

        def discard(endpoint, _previous):
            reference = endpoint["auth"]["api_key"]
            discarded.append(reference)
            vault.pop(reference)

        result = migrate_image_connections(
            lambda: copy.deepcopy(store), write, late_prepare, discard_endpoint=discard
        )
        selected = result[IMAGE_SELECTION_KEY]
        winner = next(item for item in result["model_endpoints"] if item["id"] == selected["endpoint_id"])
        winning_reference = winner["auth"]["api_key"]
        self.assertEqual("newer-synthetic-key", vault[winning_reference])
        self.assertNotIn(winning_reference, discarded)
        self.assertEqual(1, len(discarded))
        self.assertEqual(1, len(result["model_endpoints"]))

    def test_uncertain_write_outcome_does_not_delete_possibly_committed_credentials(self):
        vault = {}
        save = load_secret_save_helper(vault)
        discarded = []

        def write(_candidate, _etag):
            raise RuntimeError("The write outcome is unknown")

        with self.assertRaises(RuntimeError):
            migrate_image_connections(
                legacy_settings, write,
                lambda endpoint, previous: save(endpoint, endpoint["id"], existing_endpoint=previous, stage_new_secrets=True),
                discard_endpoint=lambda *args: discarded.append(args),
            )
        self.assertEqual([], discarded)
        self.assertEqual(1, len(vault))

    def test_preparation_failure_discards_only_this_attempts_completed_stages(self):
        vault = {}
        save = load_secret_save_helper(vault)
        source = legacy_settings()
        source.update({
            "azure_apim_image_gen_endpoint": "https://gateway.example.test",
            "azure_apim_image_gen_deployment": "image-gateway",
            "azure_apim_image_gen_subscription_key": "synthetic-subscription",
        })
        writes = []
        discarded = []

        def prepare(endpoint, previous):
            if endpoint["migration_source"] == "legacy_image_apim":
                raise RuntimeError("Simulated preparation failure")
            return save(endpoint, endpoint["id"], existing_endpoint=previous, stage_new_secrets=True)

        def discard(endpoint, _previous):
            reference = endpoint["auth"]["api_key"]
            discarded.append(reference)
            vault.pop(reference)

        with self.assertRaises(RuntimeError):
            migrate_image_connections(
                lambda: copy.deepcopy(source), lambda *args: writes.append(args),
                prepare, discard_endpoint=discard,
            )
        self.assertEqual([], writes)
        self.assertEqual(1, len(discarded))
        self.assertEqual({}, vault)
        self.assertEqual("synthetic-image-key", source["azure_openai_image_gen_key"])


if __name__ == "__main__":
    unittest.main()
