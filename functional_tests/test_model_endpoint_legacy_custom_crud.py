# test_model_endpoint_legacy_custom_crud.py
"""
Functional tests for isolated global model connection mutations.
Version: 0.261.392
Implemented in: 0.261.392

Exercise real modules and Flask routes in fresh offline processes. Incomplete
custom connections must remain repairable without blocking unrelated CRUD or
causing credentials on unchanged connections to be rewritten.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import copy
from contextlib import ExitStack
from pathlib import Path
import sys
from unittest.mock import patch

from flask import Blueprint, Flask

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports

def check(condition, message):
    if not condition:
        raise AssertionError(message)

with offline_app_imports(), ExitStack() as stack:
    import functions_settings as settings_module
    import functions_model_endpoint_validation as validation
    import route_backend_v2 as v2
    from functions_keyvault_errors import KeyVaultSecretStorageError

    def legacy(identifier):
        return {
            "id": identifier, "name": identifier, "provider": "custom",
            "enabled": True,
            "connection": {
                "endpoint": "https://gateway.example.test/prefix",
                "api_version": "2025-04-01-preview",
                "openai_api_version": "2025-04-01-preview",
                "anthropic_version": "2023-06-01",
            },
            "auth": {"type": "api_key", "api_key": "synthetic-stored-secret"},
            "models": [{
                "id": identifier + "-model", "deploymentName": "actual-deployment",
                "modelName": "actual-model", "displayName": "Friendly name",
                "vendorOptions": {"keep": [1, 2]},
            }],
            "vendorMetadata": {"preserved": True},
        }

    azure = {
        "id": "azure", "name": "Azure connection", "provider": "aoai",
        "enabled": True,
        "connection": {"endpoint": "https://offline.openai.azure.com"},
        "auth": {"type": "api_key", "api_key": "synthetic-azure-secret"},
        "models": [{"id": "azure-model", "deploymentName": "azure-chat"}],
    }
    original = [legacy("legacy-one"), legacy("legacy-two"), azure]
    state = {
        "enable_multi_model_endpoints": True,
        "model_endpoints": copy.deepcopy(original),
    }
    events = []
    staged = []
    cleaned = []
    deleted = []

    def stage(endpoint, endpoint_id, **kwargs):
        events.append("stage")
        staged.append(endpoint_id)
        check(kwargs["stage_new_secrets"], "Credentials must be staged")
        return copy.deepcopy(endpoint)

    def commit(updates):
        events.append("commit")
        state.update(copy.deepcopy(updates))
        return True

    def cleanup(previous, saved, endpoint_id, **kwargs):
        events.append("cleanup")
        cleaned.append(endpoint_id)

    def delete(endpoint, endpoint_id, **kwargs):
        events.append("delete")
        deleted.append(endpoint_id)

    for name in ("login_required", "admin_required"):
        stack.enter_context(patch.object(v2, name, lambda function: function))
    stack.enter_context(patch.object(v2, "get_settings", side_effect=lambda: copy.deepcopy(state)))
    stack.enter_context(patch.object(v2, "read_embedding_settings", side_effect=lambda: copy.deepcopy(state)))
    stack.enter_context(patch.object(v2, "update_settings", side_effect=commit))
    stack.enter_context(patch.object(v2, "log_event"))
    stack.enter_context(patch.object(v2, "keyvault_model_endpoint_save_helper", side_effect=stage))
    stack.enter_context(patch.object(v2, "keyvault_model_endpoint_cleanup_helper", side_effect=cleanup))
    stack.enter_context(patch.object(v2, "keyvault_model_endpoint_delete_helper", side_effect=delete))
    stack.enter_context(patch.object(validation, "resolve_custom_model_endpoint_addresses", return_value=("93.184.216.34",)))
    preflight = stack.enter_context(patch.object(v2, "preflight_embedding_settings", wraps=v2.preflight_embedding_settings))

    app = Flask("legacy-custom-crud", root_path=str(root / "application" / "single_app"))
    app.secret_key = "offline-test-only"
    app.config["TESTING"] = True
    blueprint = Blueprint("legacy_custom", __name__)
    v2.register_route_backend_v2_admin(blueprint)
    app.register_blueprint(blueprint)
    client = app.test_client()
    base = "/api/v2/admin/model-endpoints"

    def send(method, identifier="", payload=None, expected=200):
        response = client.open(base + ("/" + identifier if identifier else ""), method=method, json=payload)
        body = response.get_json()
        check(response.status_code == expected, f"{method} {identifier}: {response.status_code} {body}")
        check("synthetic-stored-secret" not in response.get_data(as_text=True), "Stored secret leaked")
        check("synthetic-azure-secret" not in response.get_data(as_text=True), "Azure secret leaked")
        return body

    for scenario in ("reads", "crud", "delete_legacy", "repair", "invalid", "failure"):
        state.clear()
        state.update({"enable_multi_model_endpoints": True, "model_endpoints": copy.deepcopy(original)})
        for values in (events, staged, cleaned, deleted):
            values.clear()
        preflight.reset_mock()
        if scenario == "reads":
            for api_type in (None, "unsupported-type"):
                endpoint = legacy("unresolved")
                if api_type is not None:
                    endpoint["api_type"] = api_type
                normalized, _ = settings_module.normalize_model_endpoints([endpoint])
                record = normalized[0]
                check(all(record["connection"].get(key) == value for key, value in endpoint["connection"].items()), "Normalization discarded API versions")
                check(record["models"][0]["deploymentName"] == "actual-deployment", "Deployment was discarded")
                check(record["models"][0]["modelName"] == "actual-model", "Model name was discarded")
            body = send("GET")
            record = body["endpoints"][0]
            check(record["models"][0]["deploymentName"] == "actual-deployment", "List lost repair metadata")
            check(record["has_api_key"] and "api_key" not in record["auth"], "List redaction failed")
            body = send("GET", "legacy-one")
            check(body["endpoint"]["connection"]["api_version"] == "2025-04-01-preview", "Detail lost API version")
            check(state["model_endpoints"] == original, "Reading changed stored records")
            check(not events, "Reading triggered persistence")
        elif scenario == "crud":
            send("PATCH", "azure", {"name": "Renamed Azure"})
            check(state["model_endpoints"][:2] == original[:2], "Editing rewrote legacy records")
            check(staged == ["azure"] and cleaned == ["azure"], "Editing rewrote unrelated credentials")
            candidate = {**copy.deepcopy(azure), "id": "new-azure"}
            send("POST", payload=candidate, expected=201)
            check(state["model_endpoints"][:2] == original[:2], "Creating rewrote legacy records")
            check(staged == ["azure", "new-azure"], "Creating restaged unrelated credentials")
            stage_count = len(staged)
            send("DELETE", "new-azure")
            check(len(staged) == stage_count, "Deletion restaged remaining credentials")
            send("DELETE", "azure")
            check(state["model_endpoints"] == original[:2], "Deleting valid connection rewrote legacy records")
            send("DELETE", "legacy-one")
            check(state["model_endpoints"] == [original[1]], "Deleting one legacy record changed the other")
            check(deleted == ["new-azure", "azure", "legacy-one"], "Wrong credentials deleted")
            check(preflight.call_count == 5, "Mutation bypassed embedding preflight")
            check(events.index("commit") < events.index("cleanup"), "Credentials cleaned before commit")
            check(events.index("commit") < events.index("delete"), "Credentials deleted before commit")
        elif scenario == "delete_legacy":
            for identifier in ("legacy-one", "legacy-two"):
                state["model_endpoints"] = copy.deepcopy(original)
                send("DELETE", identifier)
                expected = [item for item in original if item["id"] != identifier]
                check(state["model_endpoints"] == expected, "Deletion changed unrelated records")
            check(not staged and not cleaned, "Legacy deletion rewrote credentials")
            check(deleted == ["legacy-one", "legacy-two"], "Wrong legacy credentials deleted")
        elif scenario == "repair":
            for identifier, api_type in (("legacy-one", "azure_openai"), ("legacy-two", "openai")):
                untouched = copy.deepcopy(next(item for item in state["model_endpoints"] if item["id"] != identifier and item["id"].startswith("legacy")))
                body = send("PATCH", identifier, {"api_type": api_type, "name": "Repaired " + identifier})
                saved = body["endpoint"]
                check(saved["api_type"] == api_type, "Explicit API type was not saved")
                check(saved["models"][0]["id"] == identifier + "-model", "Model ID changed")
                check(saved["models"][0]["vendorOptions"] == {"keep": [1, 2]}, "Model metadata lost")
                field = "deploymentName" if api_type == "azure_openai" else "modelName"
                expected = "actual-deployment" if api_type == "azure_openai" else "actual-model"
                check(saved["models"][0][field] == expected, "Explicit contract lost its request identifier")
                other = next(item for item in state["model_endpoints"] if item["id"] == untouched["id"])
                check(other == untouched, "Repair changed another connection")
            check(staged == ["legacy-one", "legacy-two"], "Repair staged unrelated credentials")
            check(state["model_endpoints"][2] == azure, "Repair changed Azure connection")
        elif scenario == "invalid":
            for payload in ({"name": "Still unresolved"}, {"api_type": "unsupported-type"}):
                send("PATCH", "legacy-one", payload, expected=400)
            candidate = legacy("new-invalid")
            send("POST", payload=candidate, expected=400)
            check(state["model_endpoints"] == original and not events, "Invalid candidate wrote credentials/settings")
            check(not staged and not cleaned and not deleted, "Invalid candidate changed secrets")
        elif scenario == "failure":
            with patch.object(v2, "update_settings", return_value=False):
                send("DELETE", "legacy-one", expected=500)
            check(state["model_endpoints"] == original, "Failed commit changed stored connections")
            check(not staged and not cleaned and not deleted, "Failed delete touched credentials")
            with patch.object(v2, "_persist_global_model_endpoints", side_effect=validation.ModelEndpointValidationError("Invalid Custom connection.")):
                body = send("DELETE", "legacy-one", expected=400)
            check(body["code"] == "invalid_custom_endpoint", "Delete concealed validation failure")
            error = KeyVaultSecretStorageError(RuntimeError("private-provider-details"))
            with patch.object(v2, "keyvault_model_endpoint_save_helper", side_effect=error):
                body = send("PATCH", "azure", {"name": "Cannot commit"}, expected=500)
            check(body["code"] == "key_vault_write_failed", "Key Vault failure was concealed")
            check("private-provider-details" not in str(body), "Provider error leaked")
            check(state["model_endpoints"] == original, "Failed credential staging committed settings")
            check(not cleaned and not deleted, "Failed credential staging cleaned live credentials")
        print("PASS: " + scenario)
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_legacy_custom_global_crud(optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", PROBE, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for scenario in ("reads", "crud", "delete_legacy", "repair", "invalid", "failure"):
        assert f"PASS: {scenario}" in result.stdout
