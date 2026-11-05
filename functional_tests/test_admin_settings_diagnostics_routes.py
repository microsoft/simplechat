# test_admin_settings_diagnostics_routes.py
"""
Real-module regression coverage for administrator diagnostics and save revisions.
Version: 0.261.401
Implemented in: 0.261.125
Image result contracts and Key Vault cleanup reporting added in: 0.261.400
Cold-process timeout evidence preserved in: 0.261.401

Fresh processes retain the real configuration, route registration, dispatcher,
settings store, embedding maintenance fence, and Key Vault credential factory.
External services are faked, authentication decorators are covered separately,
and V2 save failures are injected at the persistence boundary. Explicit checks
also execute under optimized Python.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import atexit
import copy
import faulthandler
import importlib
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import time
from unittest.mock import MagicMock, Mock, patch

from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError
from azure.search.documents.indexes.models import SearchIndex
from flask import Blueprint, Flask
from werkzeug.test import Client

root = Path(sys.argv[1])
app_root = root / "application" / "single_app"
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(app_root))
from test_support.offline_bootstrap import offline_app_imports

def check(condition, message):
    if not condition:
        raise AssertionError(message)

started = time.monotonic()
started_cpu = time.process_time()

def phase(name):
    print(
        f"PHASE {name}: wall={time.monotonic() - started:.3f}s "
        f"cpu={time.process_time() - started_cpu:.3f}s",
        flush=True,
    )

faulthandler.dump_traceback_later(30, repeat=True)
atexit.register(faulthandler.cancel_dump_traceback_later)
atexit.register(phase, "interpreter exit reached")
phase("offline bootstrap start")
with offline_app_imports(), ExitStack() as stack:
    phase(f"first import {sys.argv[2]} start")
    importlib.import_module(sys.argv[2])
    phase("first import complete")
    import functions_embedding_compatibility as compatibility
    import functions_keyvault as keyvault
    import functions_keyvault_test as vault_probe
    phase("shared settings route import start")
    import route_backend_settings as classic
    phase("shared settings route import complete")
    phase("v2 route import start")
    import route_backend_v2 as v2
    phase("v2 route import complete")
    from app_settings_store import AppSettingsStore
    from functions_embedding_profile import EMBEDDING_VECTOR_PROFILE_KEY, resolve_embedding_profile
    from functions_image_api_route import ImageGenerationError
    from functions_keyvault_errors import KeyVaultSecretStorageError
    from test_ai_connection_embedding_runtime import custom_settings
    from test_app_settings_store_consistency import FakeCosmos
    from test_data_management_search_write_fence import FakeGateContainer
    from test_key_vault_connection_permissions import ProbeClient, forbidden

    phase("fixture setup")
    cosmos = FakeCosmos()
    settings = custom_settings()
    profile = resolve_embedding_profile(settings)
    settings.update({
        EMBEDDING_VECTOR_PROFILE_KEY: profile.as_state(),
        "azure_ai_search_endpoint": "https://offline.search.windows.net",
        "key_vault_identity": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    })
    cosmos.document.update(settings)
    store = AppSettingsStore(cosmos)
    search = Mock()
    indexes = {}
    for scope in ("user", "group", "public"):
        schema_path = app_root / "static" / "json" / f"ai_search-index-{scope}.json"
        definition = json.loads(schema_path.read_text(encoding="utf-8"))
        definition = compatibility.build_embedding_index_schema(definition, settings)
        indexes[definition["name"]] = SearchIndex.deserialize(definition)
    search.get_index.side_effect = lambda name: copy.deepcopy(indexes[name])

    def save_index(index):
        indexes[index.name] = copy.deepcopy(index)
        return copy.deepcopy(index)

    search.create_or_update_index.side_effect = save_index
    stack.enter_context(patch.object(classic, "get_settings", side_effect=lambda **kwargs: store.read(use_cosmos=True)))
    stack.enter_context(patch.object(classic, "get_index_client", return_value=search))
    stack.enter_context(patch.object(classic, "get_current_user_info", return_value={"userId": "offline-admin"}))
    stack.enter_context(patch.object(classic, "log_event"))
    stack.enter_context(patch.object(classic, "log_general_admin_action"))
    stack.enter_context(patch.object(v2, "log_event"))
    stack.enter_context(patch.object(vault_probe, "log_event"))
    stack.enter_context(patch.object(compatibility, "_get_embedding_settings_store", return_value=store))
    stack.enter_context(patch.object(compatibility, "_runtime_containers", return_value=(None, FakeGateContainer(), Mock())))
    for module in (classic, v2):
        for decorator in ("login_required", "admin_required"):
            stack.enter_context(patch.object(module, decorator, lambda function: function))

    app = Flask("admin-diagnostics-regressions", root_path=str(app_root))
    app.secret_key = "offline-test-only"
    app.config["TESTING"] = True
    blueprint = Blueprint("diagnostics", __name__)
    classic.register_route_backend_settings(blueprint)
    v2.register_route_backend_v2_admin(blueprint)
    app.register_blueprint(blueprint)
    client = Client(app, app.response_class)

    phase("index diagnostics")
    revision = "1"
    for scope in ("user", "group", "public"):
        response = client.post("/api/admin/settings/check_index_fields", json={
            "indexType": scope, "settings_etag": revision,
        })
        body = response.get_json()
        check(response.status_code == 200, str(body))
        check(body["settings_etag"] != revision, "First observation did not record its metadata")
        revision = body["settings_etag"]
    check(cosmos.writes == 3, "Initial checks did not serialize three metadata writes")

    for scope in ("user", "group", "public"):
        response = client.post("/api/admin/settings/check_index_fields", json={
            "indexType": scope, "settings_etag": revision,
        })
        body = response.get_json()
        check(response.status_code == 200 and body["settings_etag"] == revision, str(body))
    check(cosmos.writes == 3, "Repeated checks invalidated the form")
    saved = store.write(lambda current: {**current, "app_title": "Saved after checks"}, expected_etag=revision)
    check(saved["app_title"] == "Saved after checks", "The originating form cannot save")

    response = client.post("/api/admin/settings/check_index_fields", json={
        "indexType": "user", "settings_etag": revision,
    })
    body = response.get_json()
    check(response.status_code == 409 and body["needsReload"], str(body))
    check("settings_etag" not in body and not body["needsRecreation"], "A conflict fast-forwarded the form")
    revision = saved["_etag"]

    group = indexes["simplechat-group-index"]
    group.fields = [field for field in group.fields if field.name != "embedding_profile_id"]
    response = client.post("/api/admin/settings/check_index_fields", json={
        "indexType": "group", "settings_etag": revision,
    })
    body = response.get_json()
    check(response.status_code == 200 and body["autoFixed"], str(body))
    check("embedding_profile_id" in body["fieldsAdded"], "Field repair was skipped")
    check(body["settings_etag"] == revision, "Identical repaired metadata changed the revision")
    check(search.create_or_update_index.call_count == 1, "The real field repair did not run")

    for invalid_revision in ("", [], {}, 1):
        response = client.post("/api/admin/settings/check_index_fields", json={
            "indexType": "user", "settings_etag": invalid_revision,
        })
        check(response.status_code == 400, "Invalid form revision was accepted")
    with patch.object(search, "get_index", side_effect=ResourceNotFoundError("missing")):
        response = client.post("/api/admin/settings/check_index_fields", json={"indexType": "public"})
        body = response.get_json()
        check(response.status_code == 404 and body["needsCreation"], str(body))
    with patch.object(search, "get_index", side_effect=ServiceRequestError("private provider details")):
        response = client.post("/api/admin/settings/check_index_fields", json={"indexType": "user"})
        body = response.get_json()
        check(response.status_code == 500 and body["code"] == "index_check_failed", str(body))
        check("private provider details" not in str(body), "Search details leaked to the browser")
        response = client.post("/api/admin/settings/create_index", json={"indexType": "user"})
        check(response.status_code == 500, "An unknown index-read failure triggered index creation")
        check(search.create_index.call_count == 0, "Creation continued after an uncertain read")

    phase("image diagnostics")
    endpoints = ("/api/admin/settings/test_connection", "/api/v2/admin/settings/test-connection")
    image_selection = {"endpoint_id": "saved-images", "model_id": "image-model", "provider": "aoai"}
    for endpoint in endpoints:
        for image_payload in (
            {"test_type": "image", "selection": image_selection},
            {"test_type": "image", "direct": {"endpoint": "https://offline.openai.azure.com", "auth_type": "managed_identity"}},
        ):
            before = copy.deepcopy(store.read(use_cosmos=True))
            with patch.object(classic, "request_generated_image_source", return_value="data:image/png;base64,synthetic") as generate:
                response = client.post(endpoint, json=image_payload)
                body = response.get_json()
                check(response.status_code == 200 and body.get("success") is True, str(body))
                check(body["message"] == "Image generation connection successful", "Legacy success message changed")
                check("synthetic" not in str(body), "Image data was returned by the connection test")
                check(generate.call_count == 1, "The image operation was not exercised exactly once")
                tested_settings = generate.call_args.args[0]
                check(tested_settings["enable_image_generation"] is True, "The explicit image test was disabled")
                if "selection" in image_payload:
                    check(tested_settings["image_generation_model_selection"] == image_selection, "Saved binding was replaced")
            check(store.read(use_cosmos=True) == before, "The image test changed saved settings")

        for error, expected_status, expected_code in (
            (ImageGenerationError("The image service returned no usable image.", "image_output_missing"), 502, "image_output_missing"),
            (ImageGenerationError("Image generation was blocked by content safety policies.", "image_content_refused", 400), 400, "image_content_refused"),
            (ImageGenerationError("The selected image service is unavailable.", "image_service_unavailable", 503), 503, "image_service_unavailable"),
            (RuntimeError("private provider details"), 502, "image_generation_failed"),
        ):
            with patch.object(classic, "request_generated_image_source", side_effect=error):
                response = client.post(endpoint, json={"test_type": "image", "selection": image_selection})
                body = response.get_json()
                check(response.status_code == expected_status and body.get("success") is False, str(body))
                check(body["error_code"] == expected_code and body.get("error"), "The safe image diagnostic was lost")
                check("private provider details" not in str(body), "Image provider details leaked")

        with patch.object(classic, "_resolve_admin_settings_test_secrets", side_effect=RuntimeError("private provider details")):
            response = client.post(endpoint, json={"test_type": "image", "selection": image_selection})
            body = response.get_json()
            check(response.status_code == 502 and body.get("success") is False, str(body))
            check("private provider details" not in str(body), "Secret resolution details leaked")

    phase("key vault diagnostics")
    credential = MagicMock()
    credential.__enter__.return_value = credential
    credential.__exit__.return_value = False
    factory = stack.enter_context(patch.object(keyvault, "DefaultAzureCredential", return_value=credential))
    vault = ProbeClient()
    stack.enter_context(patch.object(vault_probe, "SecretClient", return_value=vault))
    draft_id = "11111111-2222-3333-4444-555555555555"
    for endpoint in endpoints:
        response = client.post(endpoint, json={
            "test_type": "key_vault", "vault_name": "draft-vault", "client_id": draft_id,
        })
        body = response.get_json()
        check(response.status_code == 200 and all(value == "passed" for value in body["checks"].values()), str(body))
        check(factory.call_args.kwargs["managed_identity_client_id"] == draft_id, "Saved identity replaced the draft")
        check(factory.call_args.kwargs["process_timeout"] == 10, "Credential timeouts were dropped")
        vault.failures["write"] = forbidden()
        response = client.post(endpoint, json={
            "test_type": "key_vault", "vault_name": "draft-vault", "client_id": "",
        })
        body = response.get_json()
        check(response.status_code == 400 and body["code"] == "key_vault_write_forbidden", str(body))
        check("Key Vault Secrets Officer" in body["error"], "The failed write is not actionable")
        check(factory.call_args.kwargs["managed_identity_client_id"] is None, "Blank identity did not select the system identity")
        vault.failures.clear()
        vault.failures["cleanup"] = TypeError("private provider details")
        response = client.post(endpoint, json={
            "test_type": "key_vault", "vault_name": "draft-vault", "client_id": "",
        })
        body = response.get_json()
        check(response.status_code == 400 and body["success"] is False, str(body))
        check(body["checks"] == {"list": "passed", "write": "passed", "read": "passed", "cleanup": "failed"}, str(body))
        check(len(body["details"]) == 4 and body["cleanup_secret_name"] in body["error"], "Partial cleanup reporting was lost")
        check("private provider details" not in str(body), "SDK exception details leaked")
        vault.failures.clear()

    phase("secret persistence failure checks")
    current_endpoint = settings["model_endpoints"][0]
    with (
        patch.object(v2, "_load_global_model_endpoints", return_value=[current_endpoint]),
        patch.object(v2, "normalize_model_endpoints", side_effect=lambda values: (values, [])),
        patch.object(v2, "_persist_global_model_endpoints", side_effect=KeyVaultSecretStorageError(forbidden())),
    ):
        for method, endpoint, payload in (
            ("POST", "/api/v2/admin/model-endpoints", {"id": "new"}),
            ("PATCH", f"/api/v2/admin/model-endpoints/{current_endpoint['id']}", {"name": "Updated"}),
            ("DELETE", f"/api/v2/admin/model-endpoints/{current_endpoint['id']}", None),
        ):
            response = client.open(endpoint, method=method, json=payload)
            body = response.get_json()
            check(response.status_code == 500 and body.get("code") == "key_vault_write_forbidden", str(body))
            check("private provider details" not in str(body), "Provider details leaked during a V2 save")

phase("offline cleanup complete")
print("PASS: real admin diagnostics, revisions, and shared Key Vault routes", flush=True)
'''


def _probe_output(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _run_real_admin_probe(first_import, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    label = f"first_import={first_import}, optimized={optimized}"
    try:
        result = subprocess.run(
            command + ["-c", PROBE, str(ROOT), first_import],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        pytest.fail(
            f"Admin diagnostics subprocess exceeded 120s ({label}).\n"
            f"Child stdout:\n{_probe_output(error.stdout)}\n"
            f"Child stderr / delayed stacks:\n{_probe_output(error.stderr)}",
            pytrace=False,
        )
    if result.returncode != 0:
        pytest.fail(
            f"Admin diagnostics subprocess exited {result.returncode} ({label}).\n"
            f"Child stdout:\n{result.stdout}\nChild stderr:\n{result.stderr}",
            pytrace=False,
        )
    if "PASS: real admin diagnostics" not in result.stdout:
        pytest.fail(f"Admin diagnostics subprocess did not complete ({label}).\n{result.stdout}", pytrace=False)
    for line in result.stdout.splitlines():
        if line.startswith("PHASE "):
            print(f"{label}: {line}")


@pytest.mark.parametrize("first_import", ["functions_keyvault", "route_backend_settings"])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_admin_diagnostics_and_revision_contract(first_import, optimized):
    _run_real_admin_probe(first_import, optimized)


@pytest.mark.parametrize("first_import", ["functions_keyvault", "route_backend_settings"])
@pytest.mark.parametrize("optimized", [False, True])
def test_probe_harness_keeps_fresh_import_orders_modes_and_deadline(monkeypatch, first_import, optimized):
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, "PASS: real admin diagnostics", "")

    monkeypatch.setattr(subprocess, "run", run)
    _run_real_admin_probe(first_import, optimized)
    command, options = calls[0]
    assert command == [sys.executable, "-B", *(["-O"] if optimized else []), "-c", PROBE, str(ROOT), first_import]
    assert options == {"capture_output": True, "text": True, "timeout": 120, "check": False}
    assert len(calls) == 1


def test_probe_harness_timeout_preserves_child_phases_and_stacks(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            ["large embedded command"], 120,
            output=b"PHASE first import functions_keyvault start: wall=0.1s cpu=0.1s\n",
            stderr=b"Timeout (0:00:30)!\nThread waiting in import_lock\n",
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(pytest.fail.Exception) as caught:
        _run_real_admin_probe("functions_keyvault", True)
    message = str(caught.value)
    assert "exceeded 120s (first_import=functions_keyvault, optimized=True)" in message
    assert "PHASE first import functions_keyvault start" in message
    assert "Thread waiting in import_lock" in message
    assert "large embedded command" not in message


@pytest.mark.parametrize("returncode,stdout,stderr,expected", [
    (1, "PHASE first import start", "ImportError: incomplete import", "exited 1"),
    (0, "PHASE first import start", "", "did not complete"),
])
def test_probe_harness_never_accepts_incomplete_children(monkeypatch, returncode, stdout, stderr, expected):
    def run(command, **options):
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(pytest.fail.Exception, match=expected):
        _run_real_admin_probe("functions_keyvault", False)
