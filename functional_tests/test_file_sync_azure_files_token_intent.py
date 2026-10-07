#!/usr/bin/env python3
# test_file_sync_azure_files_token_intent.py
"""
Functional test for the File Sync Azure Files managed identity and service principal fix.
Version: 0.261.294
Implemented in: 0.261.294

This test ensures that File Sync builds Azure Files clients with backup token intent for
token credentials (the real azure-storage-file-share SDK refuses to build them otherwise),
that Azure Files failures are classified into reviewed, actionable messages without leaking
raw exception text, and that a failed run notifies the source's managers once a day plus app
admins when an Azure role or credential must change.
"""

import ast
import contextlib
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
FUNCTIONAL_TESTS_ROOT = REPO_ROOT / "functional_tests"
for _path in (str(APP_ROOT), str(FUNCTIONAL_TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError, ServiceRequestError  # noqa: E402
from azure.identity import ClientSecretCredential  # noqa: E402
from azure.storage.fileshare import ShareServiceClient  # noqa: E402

from test_support.versioning import assert_app_version_at_least  # noqa: E402

ACCOUNT_URL = "https://scfiletest.file.core.windows.net"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
CLIENT_ID = "66666666-7777-8888-9999-000000000000"


@contextlib.contextmanager
def _file_sync_module():
    """Import functions_file_sync against a stub config.py, then restore sys.modules.

    config.py builds live Azure clients at import time. Stub names are harvested from the real
    module so `from config import ...` consumers still resolve every symbol they expect.
    Cached application modules, including stubs other tests may have left behind, are dropped
    first so the import is real; the snapshot restore puts them back afterwards.
    """
    saved_modules = dict(sys.modules)
    application_modules = {path.stem for path in APP_ROOT.glob("*.py")} | {"semantic_kernel_plugins"}
    for name, module in list(sys.modules.items()):
        top_level = name.split(".")[0]
        if top_level in application_modules or (top_level == "azure" and getattr(module, "__spec__", None) is None):
            del sys.modules[name]
    config_stub = types.ModuleType("config")
    config_stub._is_test_stub = True
    config_tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
    for node in ast.walk(config_tree):
        names = []
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [(alias.asname or alias.name).split(".")[0] for alias in node.names if alias.name != "*"]
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        for name in names:
            if hasattr(config_stub, name):
                continue
            try:
                setattr(config_stub, name, __import__(name))
            except Exception:
                setattr(config_stub, name, MagicMock(name=f"config.{name}"))
    sys.modules["config"] = config_stub
    try:
        import functions_file_sync

        yield functions_file_sync
    finally:
        for name in list(sys.modules):
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)


@pytest.fixture(scope="module")
def file_sync():
    with _file_sync_module() as module:
        yield module


@contextlib.contextmanager
def _replaced(target, name, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


def _storage_error(error_type, error_code, status_code):
    error = error_type(message="storage request failed")
    error.error_code = error_code
    error.status_code = status_code
    return error


def _azure_files_source(auth):
    return {
        "id": "source-1",
        "name": "Finance share",
        "scope_type": "personal",
        "user_id": "user-1",
        "source_type": "azure_files",
        "connection": {"account_url": ACCOUNT_URL, "share_name": "docs", "directory_path": ""},
        "auth": auth,
    }


def test_version():
    """The fix ships in 0.261.294 or later."""
    assert_app_version_at_least("0.261.294")


def test_sdk_rejects_token_credentials_without_intent():
    """Prove the failure the fix addresses: the pinned SDK refuses token credentials without intent."""
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, "not-a-real-secret")
    with pytest.raises(ValueError, match="token_intent"):
        ShareServiceClient(account_url=ACCOUNT_URL, credential=credential)


def test_managed_identity_and_service_principal_clients_use_backup_intent(file_sync):
    """Both token-credential auth types build clients whose derived share and file clients keep backup intent."""
    for auth in (
        {"auth_type": "managed_identity"},
        {"auth_type": "client_secret", "identity": CLIENT_ID, "tenant_id": TENANT_ID, "secret": "not-a-real-secret"},
    ):
        source = _azure_files_source(auth)
        service_client = file_sync._get_azure_files_service_client(source)
        assert service_client.file_request_intent == "backup", auth["auth_type"]
        share_client = file_sync._get_azure_files_share_client(source)
        assert share_client.file_request_intent == "backup", auth["auth_type"]
        file_client = share_client.get_file_client("reports/q1.txt")
        assert file_client.file_request_intent == "backup", auth["auth_type"]


def test_connection_string_auth_is_unchanged(file_sync):
    """Account-key connection strings keep working without a token intent."""
    connection_string = (
        "DefaultEndpointsProtocol=https;AccountName=scfiletest;"
        "AccountKey=bm90LWEtcmVhbC1rZXk=;EndpointSuffix=core.windows.net"
    )
    source = _azure_files_source({"auth_type": "connection_string", "secret": connection_string})
    service_client = file_sync._get_azure_files_service_client(source)
    assert service_client.account_name == "scfiletest"


def test_error_classification(file_sync):
    """Storage error codes, HTTP status, and credential failures map to reviewed categories."""
    cases = [
        (_storage_error(ClientAuthenticationError, "AuthorizationPermissionMismatch", 403), file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED),
        (_storage_error(HttpResponseError, "AuthorizationFailure", 403), file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED),
        (_storage_error(HttpResponseError, "AuthorizationSourceIPMismatch", 403), file_sync.AZURE_FILES_ERROR_NETWORK_BLOCKED),
        (_storage_error(ClientAuthenticationError, "AuthenticationFailed", 403), file_sync.AZURE_FILES_ERROR_AUTHENTICATION_FAILED),
        (_storage_error(ResourceNotFoundError, "ShareNotFound", 404), file_sync.AZURE_FILES_ERROR_NOT_FOUND),
        (_storage_error(HttpResponseError, "", 403), file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED),
        (ClientAuthenticationError(message="token acquisition failed"), file_sync.AZURE_FILES_ERROR_AUTHENTICATION_FAILED),
        (ServiceRequestError(message="name resolution failed"), file_sync.AZURE_FILES_ERROR_NETWORK_BLOCKED),
        (ValueError("unrelated"), ""),
    ]
    for error, expected in cases:
        assert file_sync.classify_azure_files_error(error) == expected, (type(error).__name__, expected)


def test_connection_test_returns_actionable_message_without_raw_error(file_sync):
    """A permission failure becomes the reviewed role guidance, never the SDK's text."""
    raw_detail = "RequestId:secret-request-detail Server failed to authorize"
    permission_error = _storage_error(ClientAuthenticationError, "AuthorizationPermissionMismatch", 403)
    permission_error.message = raw_detail
    failing_share = MagicMock()
    failing_share.list_directories_and_files.side_effect = permission_error
    with _replaced(file_sync, "_get_azure_files_share_client", lambda source: failing_share):
        source = _azure_files_source({"auth_type": "managed_identity"})
        with pytest.raises(file_sync.FileSyncPublicValidationError) as raised:
            file_sync._test_azure_files_connection(source)
    assert "Storage File Data Privileged Reader" in raised.value.public_message
    assert raw_detail not in raised.value.public_message


def test_run_sanitizer_keeps_only_reviewed_category_messages(file_sync):
    """Clients receive a category message for known categories and the generic text otherwise."""
    known = file_sync.sanitize_file_sync_run({
        "error_message": "raw provider text",
        "error_category": file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED,
    })
    assert known["error_message"] == file_sync.FILE_SYNC_RUN_ERROR_CATEGORY_MESSAGES[file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED]
    assert known["error_category"] == file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED
    unknown = file_sync.sanitize_file_sync_run({"error_message": "raw provider text", "error_category": "made_up"})
    assert unknown["error_message"] == file_sync.FILE_SYNC_PUBLIC_RUN_ERROR_MESSAGE
    assert "error_category" not in unknown
    clean = file_sync.sanitize_file_sync_run({"status": "completed"})
    assert "error_message" not in clean


def test_run_failure_notifies_managers_daily_and_admins_for_access_errors(file_sync):
    """Managers get one notification per source per day; admins only for role or credential failures."""
    created = []
    fake_notifications = types.ModuleType("functions_notifications")
    fake_notifications.create_notification = lambda **kwargs: created.append(kwargs) or kwargs
    saved = sys.modules.get("functions_notifications")
    sys.modules["functions_notifications"] = fake_notifications
    try:
        source = _azure_files_source({"auth_type": "managed_identity"})
        run = {"id": "run-1"}
        file_sync._notify_file_sync_run_failed(source, run, file_sync.AZURE_FILES_ERROR_PERMISSION_DENIED)
        manager_notices = [notice for notice in created if notice.get("user_id")]
        admin_notices = [notice for notice in created if notice.get("assignment")]
        assert [notice["user_id"] for notice in manager_notices] == ["user-1"]
        assert manager_notices[0]["notification_type"] == "file_sync_run_failed"
        assert manager_notices[0]["link_url"] == "/workspace"
        assert manager_notices[0]["idempotency_key"].startswith("file-sync-run-failed:source-1:")
        assert admin_notices and admin_notices[0]["assignment"] == {"roles": ["Admin"]}
        assert "Storage File Data Privileged Reader" in admin_notices[0]["message"]

        created.clear()
        file_sync._notify_file_sync_run_failed(source, run, file_sync.AZURE_FILES_ERROR_NOT_FOUND)
        assert all(not notice.get("assignment") for notice in created)
        assert len(created) == 1

        created.clear()
        file_sync._notify_file_sync_run_failed(source, run, "")
        assert created[0]["message"] == file_sync.FILE_SYNC_PUBLIC_RUN_ERROR_MESSAGE
    finally:
        if saved is None:
            sys.modules.pop("functions_notifications", None)
        else:
            sys.modules["functions_notifications"] = saved


def test_manager_recipients_follow_workspace_roles(file_sync):
    """Group and public sources notify only owners, admins, and document managers."""
    group_doc = {
        "id": "group-1",
        "owner": {"id": "owner-1"},
        "admins": ["admin-1"],
        "documentManagers": ["manager-1"],
        "users": [{"userId": "member-1"}],
    }
    public_doc = {
        "id": "public-1",
        "owner": {"userId": "public-owner"},
        "admins": [{"userId": "public-admin"}],
        "documentManagers": ["public-manager"],
    }
    with _replaced(file_sync, "find_group_by_id", lambda group_id: group_doc), \
            _replaced(file_sync, "find_public_workspace_by_id", lambda workspace_id: public_doc):
        group_source = {"id": "s1", "scope_type": "group", "group_id": "group-1"}
        public_source = {"id": "s2", "scope_type": "public", "public_workspace_id": "public-1"}
        assert file_sync._file_sync_manager_recipient_ids(group_source) == ["admin-1", "manager-1", "owner-1"]
        assert file_sync._file_sync_manager_recipient_ids(public_source) == ["public-admin", "public-manager", "public-owner"]
        assert file_sync._file_sync_workspace_link(public_source) == "/public_workspaces/public-1"


def test_ui_guidance_names_required_role_in_v1_and_v2():
    """Both editors explain the role and that synced files bypass NTFS permissions."""
    v1_text = (APP_ROOT / "static" / "js" / "workspace" / "workspace-file-sync.js").read_text(encoding="utf-8")
    v2_text = (REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "fileSourceFields.ts").read_text(encoding="utf-8")
    for text in (v1_text, v2_text):
        assert "Storage File Data Privileged Reader" in text
        assert "regardless of NTFS permissions" in text


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    results = []
    with _file_sync_module() as module:
        for test in tests:
            try:
                if "file_sync" in inspect.signature(test).parameters:
                    test(module)
                else:
                    test()
                print(f"PASS {test.__name__}")
                results.append(True)
            except Exception as exc:
                print(f"FAIL {test.__name__}: {exc}")
                results.append(False)
    sys.exit(0 if all(results) else 1)
