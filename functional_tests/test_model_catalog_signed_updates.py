# test_model_catalog_signed_updates.py
"""
Functional tests for signed catalog publication, activation, and runtime snapshots.
Version: 0.261.429
Implemented in: 0.261.425

Real cryptographic signatures and the installed Cosmos SDK response type are used.
Network operations are denied; transport and publisher infrastructure are injected.
"""

import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from functools import wraps
import socket
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from azure.core.utils import CaseInsensitiveDict
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

from app_settings_store import AppSettingsStore, SettingsConflictError, SettingsUnavailableError
import functions_model_capabilities as capabilities
from model_catalog_package import (
    CatalogUpdateError, DISCOVERY_URL, canonical_bytes, package_url, read_json,
    verify_package,
)
from model_catalog_runtime import catalog_scope, configure_catalog_provider, effective_catalog, pin_catalog_stream, pin_catalog_task
from model_catalog_updates import ACTIVE, CHECK, ONLINE, CatalogUpdates
from test_app_settings_store_consistency import FakeCosmos, FakeRedis
from test_orchestration_result_imports import run_probe
from test_support.versioning import read_app_version


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Catalog tests cannot contact external services.")
    monkeypatch.setattr(socket.socket, "connect", deny)
    yield
    configure_catalog_provider(None)
    capabilities.reset_model_capability_catalog_cache()


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


@pytest.fixture
def bundle(signing_key):
    source = read_json((APP / "static" / "json" / "model_capabilities.json").read_bytes())
    public = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    def make(revision="1", document=None, **changes):
        document = deepcopy(source if document is None else document)
        document["description"] = f"Catalog revision {revision}."
        payload = canonical_bytes(document)
        manifest = {
            "formatVersion": 1, "revision": revision, "publishedAt": "2026-11-10T12:00:00Z",
            "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
            "schemaVersion": 4, "minimumAppVersion": "0.261.425",
            "keyId": "fixture-publisher", "algorithm": "RS256", "sourceCommit": "a" * 40,
            "channel": "production",
            **changes,
        }
        manifest_raw = canonical_bytes(manifest)
        return canonical_bytes({
            "manifest": base64.b64encode(manifest_raw).decode(),
            "payload": base64.b64encode(payload).decode(),
            "signature": base64.b64encode(signing_key.sign(
                manifest_raw, padding.PKCS1v15(), hashes.SHA256(),
            )).decode(),
        })

    return make, {"fixture-publisher": public}, source


class CatalogCosmos(FakeCosmos):
    """SDK-default point responses for the actual settings and catalog owners."""

    def __init__(self):
        super().__init__()
        self.packages = {}

    def _response(self, response_hook=None):
        return CosmosDict(super()._response(response_hook), response_headers=CaseInsensitiveDict())

    def read_item(self, item, partition_key, **kwargs):
        if item == "app_settings":
            return super().read_item(item, partition_key, **kwargs)
        if item != partition_key:
            raise AssertionError("Catalog package partition routing changed.")
        if item not in self.packages:
            raise CosmosResourceNotFoundError(status_code=404, message="Missing")
        return CosmosDict(deepcopy(self.packages[item]), response_headers=CaseInsensitiveDict())

    def create_item(self, body, **kwargs):
        if body["id"] == "app_settings":
            return super().create_item(body, **kwargs)
        if body["id"] in self.packages:
            raise CosmosResourceExistsError(status_code=409, message="Exists")
        self.packages[body["id"]] = deepcopy(body)
        return CosmosDict(deepcopy(body), response_headers=CaseInsensitiveDict())


@pytest.fixture
def world(bundle):
    make, keys, source = bundle
    cosmos = CatalogCosmos()
    logs = []
    store = AppSettingsStore(cosmos)
    service = CatalogUpdates(cosmos, store, "0.261.425", lambda *args, **kwargs: logs.append((args, kwargs)), keys=keys)
    return service, cosmos, make, source, logs


def test_genuine_signature_and_closed_schema(bundle):
    make, keys, _source = bundle
    result = verify_package(make(), "0.261.425", keys=keys)
    assert result["manifest"]["keyId"] == "fixture-publisher"
    assert len(result["document"]["models"]) > 100


@pytest.mark.parametrize("field", ["payload", "manifest", "signature"])
def test_changed_signed_bytes_are_rejected(bundle, field):
    make, keys, _source = bundle
    envelope = read_json(make())
    envelope[field] = base64.b64encode(b"modified").decode()
    with pytest.raises(CatalogUpdateError):
        verify_package(canonical_bytes(envelope), "0.261.425", keys=keys)


@pytest.mark.parametrize("changes", [
    {"minimumAppVersion": "9.0.0"}, {"algorithm": "none"}, {"keyId": "untrusted"},
    {"revision": "0"}, {"formatVersion": True}, {"publishedAt": "not-a-date"},
    {"schemaVersion": True}, {"size": True}, {"sourceCommit": "../main"},
])
def test_signed_but_unsupported_manifest_is_rejected(bundle, changes):
    make, keys, _source = bundle
    raw = make(**changes)
    with pytest.raises(CatalogUpdateError):
        verify_package(raw, "0.261.425", keys=keys)


def test_unsigned_and_duplicate_json_are_rejected(bundle):
    _make, keys, source = bundle
    with pytest.raises(CatalogUpdateError):
        verify_package(canonical_bytes(source), "0.261.425", keys=keys)
    with pytest.raises(CatalogUpdateError):
        read_json(b'{"manifest": 1, "manifest": 2}')
    with pytest.raises(CatalogUpdateError):
        read_json(b'{"number": NaN}')


def test_effective_runtime_and_second_worker_preserve_overrides(world):
    service, cosmos, make, _source, logs = world
    cosmos.document.update(model_catalog={"profiles": [], "preferences": {"gpt-5": {"favorite": True}}},
                           model_endpoints=[{"models": [{"modelName": "gpt-5", "capabilities": {"toolCalling": False}}]}])
    preview = service.preview(make(), "publisher-admin")
    saved = service.activate(preview["digest"], preview["etag"], "publisher-admin")
    assert saved["installed"]["revision"] == "1"
    other = CatalogUpdates(cosmos, AppSettingsStore(cosmos), service.version, service.log_event, keys=service.keys)
    configure_catalog_provider(other.snapshot)
    records = capabilities.get_model_capability_catalog_records()
    assert len(records) > 100
    assert effective_catalog()["description"] == "Catalog revision 1."
    assert cosmos.document["model_catalog"]["preferences"]["gpt-5"]["favorite"] is True
    assert cosmos.document["model_endpoints"][0]["models"][0]["capabilities"]["toolCalling"] is False
    assert logs[-1][1]["extra"]["actor"] == "publisher-admin"


@pytest.mark.parametrize("redis_enabled", [False, True])
def test_request_scope_pins_old_revision_and_new_scope_sees_save(world, redis_enabled):
    service, cosmos, make, source, _logs = world
    redis = FakeRedis()
    service.store = AppSettingsStore(cosmos, redis, redis_required=redis_enabled)
    configure_catalog_provider(service.snapshot)
    first = service.preview(make(), "admin")
    service.activate(first["digest"], first["etag"], "admin")
    with catalog_scope():
        before = effective_catalog()
        second = service.preview(make("2"), "admin")
        service.activate(second["digest"], second["etag"], "admin")
        pinned = effective_catalog()
        assert before["description"] == pinned["description"] == "Catalog revision 1."
    with catalog_scope():
        updated = effective_catalog()
        assert updated["description"] == "Catalog revision 2."
    # Also pin the absence of an imported package instead of changing mid-request.
    service.store.write(lambda state: {**state, ACTIVE: None})
    with catalog_scope():
        bundled = effective_catalog()
        service.store.write(lambda state: {**state, ACTIVE: second["digest"]})
        still_bundled = effective_catalog()
        assert bundled is None and still_bundled is None


def test_stale_preview_and_replay_are_rejected(world):
    service, _cosmos, make, _source, _logs = world
    preview = service.preview(make(), "admin")
    service.set_online(True, preview["etag"], "admin")
    with pytest.raises(SettingsConflictError):
        service.activate(preview["digest"], preview["etag"], "admin")
    refreshed = service.preview_staged(preview["digest"])
    service.activate(refreshed["digest"], refreshed["etag"], "admin")
    with pytest.raises(CatalogUpdateError):
        service.preview(make(), "admin")


def test_rollback_restores_previous_verified_package(world):
    service, _cosmos, make, _source, _logs = world
    first = service.preview(make(), "admin")
    service.activate(first["digest"], first["etag"], "admin")
    second = service.preview(make("2"), "admin")
    service.activate(second["digest"], second["etag"], "admin")
    rollback = service.rollback_target()
    restored = service.activate(rollback["digest"], rollback["etag"], "admin", rollback=True)
    assert restored["installed"]["revision"] == "1"


def test_invalid_active_package_never_silently_returns_baseline(world):
    service, cosmos, _make, _source, logs = world
    cosmos.document[ACTIVE] = "f" * 64
    with pytest.raises(CosmosResourceNotFoundError):
        service.snapshot()
    assert logs[-1][1]["level"] == 40


def test_stream_retains_request_revision_after_scope_is_closed(world):
    service, _cosmos, make, _source, _logs = world
    first = service.preview(make(), "admin")
    service.activate(first["digest"], first["etag"], "admin")
    configure_catalog_provider(service.snapshot)

    def stream():
        yield effective_catalog()["description"]

    with catalog_scope():
        initial = effective_catalog()
        response = pin_catalog_stream(stream())
    second = service.preview(make("2"), "admin")
    service.activate(second["digest"], second["etag"], "admin")
    chunks = list(response)
    assert chunks == [initial["description"]] == ["Catalog revision 1."]


def test_custom_alias_collisions_and_removals_rejected(world):
    service, cosmos, make, source, _logs = world
    cosmos.document["model_catalog"] = {"profiles": [{"id": "custom:test", "aliases": ["gpt-5"]}]}
    with pytest.raises(CatalogUpdateError, match="custom profile"):
        service.preview(make(), "admin")
    cosmos.document["model_catalog"] = {}
    source["models"] = source["models"][1:]
    with pytest.raises(CatalogUpdateError, match="removes"):
        service.preview(make(document=source), "admin")


def test_disabled_online_means_zero_outbound_calls(world):
    service, _cosmos, _make, _source, _logs = world
    calls = []
    service.download = lambda *args: calls.append(args)
    with pytest.raises(CatalogUpdateError, match="Enable online"):
        service.check("admin")
    assert calls == []


def test_fixed_source_discovery_preview_and_rate_limit(world):
    service, _cosmos, make, _source, _logs = world
    calls = []
    source = {"commit": "a" * 40, "filename": "catalog-1-2026-11-10.json"}
    raw = make()

    def download(url, _maximum):
        calls.append(url)
        return canonical_bytes(source) if url == DISCOVERY_URL else raw

    service.download = download
    status = service.status()
    service.set_online(True, status["etag"], "admin")
    checked = service.check("admin")
    assert calls == [DISCOVERY_URL, package_url(source["commit"], source["filename"])]
    assert checked["check"]["status"] == "available"
    assert not checked["digest"]
    preview = service.preview_staged(checked["check"]["digest"])
    assert preview["etag"] == checked["etag"]
    with pytest.raises(CatalogUpdateError, match="one minute"):
        service.check("admin")


@pytest.mark.parametrize("source", [
    {"commit": "main", "filename": "catalog-1-2026-11-10.json"},
    {"commit": "a" * 40, "filename": "../../evil.json"},
    {"commit": "a" * 40, "filename": "https://evil.test/package.json"},
])
def test_hostile_discovery_rejected(source):
    with pytest.raises(CatalogUpdateError):
        package_url(source["commit"], source["filename"])


def test_failed_download_preserves_catalog_and_reports_failure(world):
    service, cosmos, _make, _source, _logs = world
    service.set_online(True, service.status()["etag"], "admin")
    service.download = lambda *_args: b'{"url":"https://evil.test"}'
    with pytest.raises(CatalogUpdateError, match="Unable to verify"):
        service.check("admin")
    assert cosmos.document[CHECK]["status"] == "failed"
    assert not cosmos.document.get(ACTIVE)


def test_publisher_prepares_exact_source_bytes(tmp_path):
    spec = importlib.util.spec_from_file_location("catalog_publisher", ROOT / "scripts" / "publish_model_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.build_candidate("a" * 40, tmp_path)
    raw = (tmp_path / "payload.json").read_bytes()
    assert raw == (APP / "static" / "json" / "model_capabilities.json").read_bytes()
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()


def test_background_chat_worker_carries_catalog_and_isolates_public_records(world):
    service, _cosmos, make, _source, _logs = world
    configure_catalog_provider(service.snapshot)

    def read_worker():
        records = capabilities.get_model_capability_catalog_records()
        original = records[0]["id"]
        records[0]["id"] = "mutated-worker-copy"
        restored = capabilities.get_model_capability_catalog_records()
        assert restored[0]["id"] == original
        document = effective_catalog()
        return document["description"] if document else "bundled"

    with catalog_scope():
        baseline_worker = pin_catalog_task(read_worker)
        preview = service.preview(make(), "admin")
        service.activate(preview["digest"], preview["etag"], "admin")
        assert effective_catalog() is None
    with ThreadPoolExecutor(max_workers=1) as executor:
        baseline = executor.submit(baseline_worker).result()
        imported = executor.submit(pin_catalog_task(read_worker)).result()
    assert baseline == "bundled"
    assert imported == "Catalog revision 1."
    source = (APP / "route_backend_chats.py").read_text(encoding="utf-8")
    assert "stream_worker = pin_catalog_task(stream_worker)" in source


def test_publisher_signs_digest_and_reuses_application_verifier(tmp_path, bundle, signing_key, monkeypatch):
    import azure.identity
    import model_catalog_package
    spec = importlib.util.spec_from_file_location("catalog_publisher_signing", ROOT / "scripts" / "publish_model_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build_candidate("a" * 40, tmp_path)
    calls = []

    class SigningClient:
        def __init__(self, key_url, credential):
            calls.append(key_url)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def sign(self, algorithm, digest):
            if algorithm != "RS256":
                raise AssertionError("Unexpected signing algorithm")
            return SimpleNamespace(signature=signing_key.sign(
                digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()),
            ))

    crypto = ModuleType("azure.keyvault.keys.crypto")
    crypto.CryptographyClient = SigningClient
    crypto.SignatureAlgorithm = SimpleNamespace(rs256="RS256")
    monkeypatch.setitem(sys.modules, "azure.keyvault.keys.crypto", crypto)
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(module, "trusted_keys", lambda **_kwargs: bundle[1])
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    app_version = read_app_version()
    filename = module.sign_candidate(tmp_path, "fixture-publisher", "https://fixture.vault.azure.net/keys/catalog/version", app_version)
    verified = verify_package((tmp_path / filename).read_bytes(), app_version, keys=bundle[1])
    assert verified["manifest"]["sourceCommit"] == "a" * 40
    assert calls == ["https://fixture.vault.azure.net/keys/catalog/version"]


def test_publisher_refuses_environment_without_reviewers(monkeypatch):
    spec = importlib.util.spec_from_file_location("catalog_publisher_gate", ROOT / "scripts" / "publish_model_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("GITHUB_REPOSITORY", "microsoft/simplechat")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GH_TOKEN", "test-token")
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"protection_rules": []})
    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: response)
    with pytest.raises(ValueError, match="required reviewers"):
        module.require_publishing_approval()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("fail_commit", [None, 1, 2])
def test_publisher_exposes_pointer_only_after_both_commits(tmp_path, monkeypatch, existing, fail_commit):
    spec = importlib.util.spec_from_file_location("catalog_publisher_order", ROOT / "scripts" / "publish_model_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    filename = "catalog-2-2026-11-10.json"
    (tmp_path / "candidate.json").write_bytes(canonical_bytes({"revision": "2"}))
    (tmp_path / filename).write_bytes(b"signed-package")
    calls = []
    commits = []

    def request(method, url, *, json, timeout):
        path = url.removeprefix("https://api.github.com/repos/microsoft/simplechat")
        calls.append((method, path, json))
        status = 200
        if path == "/git/ref/heads/model-catalog":
            result = {"object": {"sha": "parent"}}
            status = 200 if existing else 404
        elif path == "/git/commits/parent":
            result = {"tree": {"sha": "base"}}
        elif path.startswith("/contents/"):
            result = {"content": base64.b64encode(canonical_bytes({
                "filename": "catalog-1-2026-11-09.json", "commit": "old",
            })).decode()}
        elif path == "/git/commits":
            commits.append(json)
            if len(commits) == fail_commit:
                raise RuntimeError("Injected publication failure")
            result = {"sha": f"commit-{len(commits)}"}
        else:
            result = {"sha": "generated"}
        return SimpleNamespace(status_code=status, raise_for_status=lambda: None, json=lambda: result)

    session = SimpleNamespace(headers={}, request=request)
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    if fail_commit is None:
        module.publish(tmp_path, filename)
        assert calls[-1] == (
            ("PATCH", "/git/refs/heads/model-catalog", {"sha": "commit-2", "force": False})
            if existing else
            ("POST", "/git/refs", {"ref": "refs/heads/model-catalog", "sha": "commit-2"})
        )
        assert commits[1]["parents"] == ["commit-1"]
        blobs = [read_json(base64.b64decode(body["content"])) for method, path, body in calls
                 if path == "/git/blobs" and base64.b64decode(body["content"]) != b"signed-package"]
        assert blobs == [{"commit": "commit-1", "filename": filename}] * 2
    else:
        with pytest.raises(RuntimeError, match="Injected publication failure"):
            module.publish(tmp_path, filename)
        assert not any(method in {"POST", "PATCH"} and path.startswith("/git/refs")
                       for method, path, _body in calls)


@pytest.fixture
def api(world):
    service = world[0]
    app = Flask(__name__)
    app.config["TESTING"] = True

    def role_guard(admin=False):
        def decorate(function):
            @wraps(function)
            def guarded(*args, **kwargs):
                role = request.headers.get("X-Test-Role")
                if not role:
                    return jsonify(error="Sign in"), 401
                if admin and role != "admin":
                    return jsonify(error="Administrator required"), 403
                return function(*args, **kwargs)
            return guarded
        return decorate

    namespace = {
        "request": request, "jsonify": jsonify, "logging": __import__("logging"),
        "get_model_catalog_update_service": lambda: service,
        "get_current_user_id": lambda: "admin",
        "login_required": role_guard(), "admin_required": role_guard(True),
        "swagger_route": lambda **_kwargs: lambda function: function, "get_auth_security": lambda: [],
        "CatalogUpdateError": CatalogUpdateError, "MAX_PACKAGE_BYTES": 1536000,
        "SettingsConflictError": SettingsConflictError, "SettingsUnavailableError": SettingsUnavailableError,
        "log_event": service.log_event,
    }
    source = APP / "route_backend_model_catalog_updates.py"
    tree = ast.parse(source.read_text())
    register = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    exec(compile(ast.Module(body=[register], type_ignores=[]), str(source), "exec"), namespace)
    namespace["register_catalog_update_routes"](app)
    return app.test_client()


def test_update_api_requires_admin_and_projects_metadata_only(api):
    path = "/api/admin/model-catalog/updates"
    anonymous = api.get(path)
    user = api.get(path, headers={"X-Test-Role": "user"})
    assert anonymous.status_code == 401
    assert user.status_code == 403
    response = api.get(path, headers={"X-Test-Role": "admin"})
    assert response.status_code == 200
    assert "model_endpoints" not in response.json
    assert response.json["onlineEnabled"] is False


def test_update_api_upload_preview_apply_and_conflict(api, world):
    make = world[2]
    path = "/api/admin/model-catalog/updates"
    headers = {"X-Test-Role": "admin"}
    preview = api.post(path, headers=headers, json={"operation": "upload", "package": make().decode()})
    assert preview.status_code == 200
    assert preview.json["signatureVerified"]
    applied = api.post(path, headers=headers, json={
        "operation": "apply", "digest": preview.json["digest"], "etag": preview.json["etag"],
    })
    assert applied.status_code == 200
    assert applied.json["installed"]["revision"] == "1"
    stale = api.post(path, headers=headers, json={
        "operation": "online", "enabled": True, "etag": preview.json["etag"],
    })
    assert stale.status_code == 409


def test_update_api_rejects_unsigned_and_direct_disabled_check(api, world):
    path = "/api/admin/model-catalog/updates"
    headers = {"X-Test-Role": "admin"}
    calls = []
    world[0].download = lambda *args: calls.append(args)
    unsigned = api.post(path, headers=headers, json={"operation": "upload", "package": "{}"})
    disabled = api.post(path, headers=headers, json={"operation": "check"})
    invalid = api.post(path, headers=headers, json={"operation": []})
    assert unsigned.status_code == disabled.status_code == invalid.status_code == 400
    assert calls == []


@pytest.mark.parametrize("optimized", [False, True])
def test_catalog_leaf_import_orders_are_network_free(optimized):
    probe = """
import socket
def deny(*args, **kwargs): raise RuntimeError('network forbidden')
socket.socket.connect = deny
import model_catalog_updates
import functions_model_capabilities
import model_catalog_runtime
if model_catalog_runtime.effective_catalog() is not None: raise RuntimeError('unexpected provider')
if 'config' in __import__('sys').modules: raise RuntimeError('bootstrap imported')
"""
    for imports in (probe, probe.replace("import model_catalog_updates\nimport functions_model_capabilities",
                                       "import functions_model_capabilities\nimport model_catalog_updates")):
        command = [sys.executable, *(["-O"] if optimized else []), "-c", imports]
        result = subprocess.run(command, cwd=APP, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("optimized", [False, True])
def test_real_web_and_scheduler_configure_injected_catalog_owner(optimized):
    probe = r'''
from unittest.mock import patch
from contextlib import ExitStack
import sys
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from test_model_catalog_signed_updates import CatalogCosmos
with offline_app_imports():
    import app as web
    import simplechat_scheduler as scheduler
    import functions_settings as settings
    import app_settings_cache as cache
    from app_settings_store import AppSettingsStore
    from model_catalog_runtime import configure_catalog_provider, effective_catalog
    cosmos = CatalogCosmos()
    with patch.object(cache, "APP_SETTINGS_STORE", AppSettingsStore(cosmos)), \
         patch.object(settings, "cosmos_settings_container", cosmos), \
         patch.object(settings, "_catalog_update_service", None):
        settings.configure_model_catalog_runtime()
        if effective_catalog() is not None: raise AssertionError("Unexpected imported catalog")
        with patch.object(web, "initialize_application"), web.app.test_request_context("/"):
            web.ensure_application_initialized()
            if effective_catalog() is not None: raise AssertionError("Web scope lost bundled baseline")
        with ExitStack() as stack:
            stack.enter_context(patch.object(scheduler, "get_settings", return_value={}))
            for name in ("configure_application_cache", "initialize_clients",
                         "configure_action_credential_state", "configure_action_credential_runtime",
                         "setup_appinsights_logging"):
                stack.enter_context(patch.object(scheduler, name))
            scheduler.initialize_scheduler_runtime()
            if effective_catalog() is not None: raise AssertionError("Scheduler lost bundled baseline")
    configure_catalog_provider(None)
    print("PASS: real web and scheduler catalog owner configured without network")
'''
    run_probe(probe, (), optimized)
