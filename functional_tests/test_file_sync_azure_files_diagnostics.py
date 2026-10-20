# test_file_sync_azure_files_diagnostics.py
"""
Functional tests for safe Azure Files provider diagnostics and API responses.
Version: 0.261.358
Implemented in: 0.261.358

Validate structured classification, lazy failures, real logging sanitization,
and personal/group/public Flask error envelopes with no cloud or network I/O.
"""

import builtins
import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import Mock

from azure.core import exceptions as azure_exceptions
import pytest

from test_file_sync_azure_files_runtime import connector_functions, no_network, source
from test_file_sync_azure_blob_storage import load_functions
from test_support.agent_delegation import module_stub
from test_support import (
    group_file_source_harness,
    personal_file_source_harness,
    public_file_source_harness,
)


SECRET = "private-provider-data.example?sig=not-a-real-secret"
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
environment = group_file_source_harness.environment
personal_environment = personal_file_source_harness.personal_environment
public_environment = public_file_source_harness.environment


def provider_error(code="", status=None):
    error = azure_exceptions.HttpResponseError(SECRET)
    error.error_code = code
    error.status_code = status
    return error


@pytest.mark.parametrize("error,expected", [
    (provider_error("AuthenticationFailed"), "azure_files_authentication_failed"),
    (provider_error("InvalidAuthenticationInfo"), "azure_files_authentication_failed"),
    (provider_error(status=401), "azure_files_authentication_failed"),
    (azure_exceptions.ClientAuthenticationError(SECRET), "azure_files_authentication_failed"),
    (provider_error("AuthorizationPermissionMismatch"), "azure_files_authorization_failed"),
    (provider_error("AuthorizationFailure"), "azure_files_authorization_failed"),
    (provider_error(status=403), "azure_files_authorization_failed"),
    (provider_error("ShareNotFound"), "azure_files_resource_not_found"),
    (provider_error(status=404), "azure_files_resource_not_found"),
    (azure_exceptions.ResourceNotFoundError(SECRET), "azure_files_resource_not_found"),
    (azure_exceptions.ServiceRequestError(SECRET), "azure_files_transport_failed"),
    (azure_exceptions.ServiceResponseError(SECRET), "azure_files_transport_failed"),
    (TimeoutError(SECRET), "azure_files_transport_failed"),
    (ImportError(SECRET), "azure_files_sdk_unavailable"),
    (ValueError(SECRET), "azure_files_operation_failed"),
    (RuntimeError(SECRET), "azure_files_operation_failed"),
    (provider_error(SECRET, 500), "azure_files_operation_failed"),
])
def test_structured_evidence_not_provider_text(error, expected):
    properties, message = connector_functions()["_azure_files_error_details"](error, "azure_files_browse")
    assert properties["failure_code"] == expected
    assert properties["operation"] == "azure_files_browse"
    assert SECRET not in json.dumps(properties) + message


@pytest.mark.parametrize("status", [True, "403", -1, 99999, [], None])
def test_invalid_status_and_unknown_types_are_not_retained(status):
    error = type("UntrustedProviderClass", (Exception,), {})(SECRET)
    error.status_code = status
    properties, message = connector_functions()["_azure_files_error_details"](error, "azure_files_list")
    assert properties["failure_code"] == "azure_files_operation_failed"
    assert properties["error_type"] == "Exception"
    assert "status_code" not in properties
    assert SECRET not in message


@pytest.fixture
def logging_runtime(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", module_stub(
        "azure.monitor.opentelemetry", configure_azure_monitor=Mock(),
    ))
    settings = {"enable_debug_logging": False}
    monkeypatch.setitem(sys.modules, "app_settings_cache", module_stub(
        "app_settings_cache", get_settings_cache=lambda: settings,
    ))
    spec = importlib.util.spec_from_file_location("functions_appinsights", APP_ROOT / "functions_appinsights.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "functions_appinsights", module)
    spec.loader.exec_module(module)
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.Logger("azure-files-diagnostic-test", level=logging.DEBUG)
    logger.addHandler(Capture())
    module._appinsights_logger = logger
    return module, settings, records


def failing_entries():
    yield {"name": "already-seen.md", "is_directory": False}
    raise provider_error("AuthorizationPermissionMismatch", 403)


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("operation,expected_operation", [
    ("test", "azure_files_test_connection"), ("browse", "azure_files_browse"),
    ("list", "azure_files_list"), ("download", "azure_files_download"),
])
def test_lazy_failures_are_safe_and_queryable(logging_runtime, monkeypatch, tmp_path, capsys, debug, operation, expected_operation):
    logger, settings, records = logging_runtime
    settings["enable_debug_logging"] = debug
    share = Mock()
    share.list_directories_and_files.side_effect = lambda **kwargs: failing_entries()
    share.get_file_client.return_value.get_file_properties.return_value = {"size": 1}
    share.get_file_client.return_value.download_file.return_value.chunks.side_effect = failing_entries
    functions = connector_functions(
        log_event=logger.log_event, _get_azure_files_share_client=lambda source: share,
    )
    if operation == "test":
        action = lambda: functions["_test_azure_files_connection"](source())
    elif operation == "browse":
        action = lambda: functions["_browse_azure_files_path"](source(), "")
    elif operation == "list":
        action = lambda: functions["_list_azure_files"](source(), {"file_sync_max_files_per_run": 10})
    else:
        original_temp_file = tempfile.NamedTemporaryFile
        monkeypatch.setattr(tempfile, "NamedTemporaryFile", lambda **kwargs: original_temp_file(
            **{**kwargs, "dir": tmp_path},
        ))

        def chunks():
            yield b"partial contents"
            raise provider_error("AuthorizationPermissionMismatch", 403)

        share.get_file_client.return_value.download_file.return_value.chunks.side_effect = chunks
        action = lambda: functions["_stage_azure_files_file"](source(), {"file_name": "policy.md"})
    with pytest.raises(functions["FileSyncPublicValidationError"]) as caught:
        action()
    assert "denied access" in str(caught.value)
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.sc_failure_code == "azure_files_authorization_failed"
    assert record.sc_operation == expected_operation
    assert record.sc_error_type == "HttpResponseError"
    assert record.sc_status_code == 403
    assert record.exc_info is None
    assert SECRET not in json.dumps(record.__dict__, default=str)
    assert SECRET not in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_client_initialization_failure_has_no_secret_traceback(monkeypatch):
    from azure.storage import fileshare

    logs = Mock()
    monkeypatch.setattr(fileshare, "ShareServiceClient", Mock(side_effect=ValueError(SECRET)))
    functions = connector_functions(log_event=logs)
    with pytest.raises(functions["FileSyncPublicValidationError"]) as caught:
        functions["_get_azure_files_service_client"](source())
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert logs.call_args.kwargs["extra"]["failure_code"] == "azure_files_configuration_failed"


def test_missing_sdk_is_an_explicit_safe_failure(monkeypatch):
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "azure.storage.fileshare":
            raise ImportError(SECRET)
        return original_import(name, *args, **kwargs)

    functions = connector_functions()
    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(functions["FileSyncPublicValidationError"], match="SDK is unavailable"):
        functions["_get_azure_files_service_client"](source())
    assert functions["log_event"].call_args.kwargs["extra"]["failure_code"] == "azure_files_sdk_unavailable"


def test_identity_authorization_errors_are_not_translated():
    resolve = Mock(side_effect=PermissionError("identity is not in this workspace"))
    functions = connector_functions(_get_identity_auth_for_source=resolve)
    with pytest.raises(PermissionError):
        functions["_get_azure_files_service_client"](source(saved=True))
    functions["log_event"].assert_not_called()


def test_selected_directory_fallback_and_missing_directory_remain_distinct():
    share = Mock()
    share.get_file_client.return_value.get_file_properties.side_effect = azure_exceptions.ResourceNotFoundError(SECRET)
    share.list_directories_and_files.return_value = []
    functions = connector_functions(_get_azure_files_share_client=lambda source: share)
    item = source()
    item["connection"]["selected_paths"] = ["reports"]
    files = functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
    assert files == []
    share.list_directories_and_files.assert_called_once_with(directory_name="team/reports")
    functions["log_event"].assert_not_called()
    share.list_directories_and_files.side_effect = azure_exceptions.ResourceNotFoundError(SECRET)
    with pytest.raises(functions["FileSyncPublicValidationError"], match="could not find"):
        functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
    assert functions["log_event"].call_args.kwargs["extra"]["failure_code"] == "azure_files_resource_not_found"


def test_failed_partial_listing_cannot_trigger_remote_deletions():
    share = Mock()
    share.list_directories_and_files.side_effect = lambda **kwargs: failing_entries()
    share.get_file_client.return_value.get_file_properties.return_value = {"size": 1}
    functions = connector_functions(_get_azure_files_share_client=lambda source: share)
    delete = Mock()
    public_error = "File Sync run failed. Contact an administrator if the problem continues."
    runner = load_functions("functions_file_sync.py", {"_process_file_sync_source"}, {
        "debug_file_sync": Mock(), "_now_iso": lambda: "2026-10-20T00:00:00Z",
        "_update_run": lambda run, fields: {**run, **fields},
        "get_file_sync_config": lambda: {"enable_file_sync": True, "file_sync_max_files_per_run": 10},
        "_load_existing_items": lambda source: {"existing": {"document_id": "keep-this-document"}},
        "_list_remote_files": functions["_list_azure_files"],
        "_handle_remote_deletes": delete, "_update_source_after_run": Mock(),
        "_log_file_sync_activity": Mock(), "log_event": Mock(), "logging": logging,
        "FILE_SYNC_PUBLIC_RUN_ERROR_MESSAGE": public_error,
    })
    result = runner["_process_file_sync_source"](source(), {"id": "run", "counts": {}}, "owner", "manual")
    assert result["status"] == "failed"
    assert result["error_message"] == public_error
    delete.assert_not_called()
    assert SECRET not in str(runner["log_event"].call_args)


@pytest.mark.parametrize("scope,fixture_name,path", [
    ("personal", "personal_environment", "/api/file-sync/personal/sources"),
    ("group", "environment", "/api/groups/group-a/file-sources"),
    ("public", "public_environment", "/api/public-workspaces/public-a/file-sources"),
])
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("operation", ["test-connection", "browse"])
def test_safe_error_envelopes_across_scopes(request, monkeypatch, scope, fixture_name, path, saved, operation):
    env = request.getfixturevalue(fixture_name)
    payload = {
        "name": "Azure Files regression", "source_type": "azure_files",
        "connection": source()["connection"], "credentials": {"auth_type": "managed_identity"},
        "schedule": {"enabled": False},
    }
    if saved:
        created = env.client.post(path, json=payload)
        assert created.status_code == 201
        body = created.get_json()
        record = body["source" if scope == "personal" else "file_source"]
        path = f"{path}/{record['id']}"
    share = Mock()
    share.list_directories_and_files.side_effect = lambda **kwargs: failing_entries()
    monkeypatch.setattr(env.filesync, "azure_exceptions", azure_exceptions)
    monkeypatch.setattr(env.filesync, "_get_azure_files_share_client", lambda source: share)
    result = env.client.post(f"{path}/{operation}", json=payload)
    assert result.status_code == 400
    assert "denied access" in result.get_json()["error"]
    assert set(result.get_json()) == {"error"}
    assert SECRET not in result.get_data(as_text=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
