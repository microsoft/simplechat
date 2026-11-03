# test_blob_container_readiness.py
"""Functional tests for bounded private Blob container recovery.

Version: 0.261.396
Implemented in: 0.261.396

Real recovery code executes against SDK-shaped storage failures, without Azure.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import threading

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
import blob_container_readiness as readiness


def storage_error(code, status=404):
    error = HttpResponseError(message="PRIVATE storage diagnostics")
    error.error_code = code
    error.status_code = status
    return error


class Storage:
    def __init__(self):
        self.exists = False
        self.creates = 0
        self.writes = 0
        self.error = None
        self.options = None

    def get_container_client(self, container):
        assert container == "personal-chat"
        return self

    def create_container(self, **kwargs):
        self.creates += 1
        self.options = kwargs
        if self.error is not None:
            raise self.error
        if self.exists:
            raise storage_error("ContainerAlreadyExists", 409)
        self.exists = True

    def write(self):
        self.writes += 1
        if not self.exists:
            raise storage_error("ContainerNotFound")
        return "saved"


def write(storage, **kwargs):
    return readiness.write_blob_with_container_recovery(
        storage, "personal-chat", storage.write, **kwargs,
    )


def test_healthy_writes_do_not_probe_or_create():
    storage = Storage()
    storage.exists = True
    values = [write(storage) for _ in range(100)]
    assert values == ["saved"] * 100
    assert storage.writes == 100 and storage.creates == 0


def test_missing_container_repairs_once_and_rechecks_authority():
    storage = Storage()
    checks = []
    result = write(storage, before_retry=lambda: checks.append("checked"))
    assert result == "saved" and checks == ["checked", "checked"]
    assert storage.writes == 2 and storage.creates == 1
    assert storage.options == {
        "public_access": None, "connection_timeout": 5, "read_timeout": 10, "retry_total": 0,
    }


def test_concurrent_missing_responses_share_one_repair():
    storage = Storage()
    barrier = threading.Barrier(16)
    local = threading.local()

    def upload():
        if not getattr(local, "attempted", False):
            local.attempted = True
            barrier.wait(timeout=10)
            raise storage_error("ContainerNotFound")
        return storage.write()

    def run(_):
        return readiness.write_blob_with_container_recovery(storage, "personal-chat", upload)

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(run, range(16)))
    assert results == ["saved"] * 16 and storage.creates == 1


def test_failure_cooldown_and_explicit_repair(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(readiness.time, "monotonic", lambda: clock[0])
    storage = Storage()
    storage.error = storage_error("AuthorizationPermissionMismatch", 403)
    for _ in range(20):
        with pytest.raises(readiness.BlobContainerUnavailableError) as raised:
            write(storage)
        assert raised.value.reason == "storage_access_denied"
        assert "PRIVATE" not in str(raised.value)
    assert storage.creates == 1 and storage.writes == 20
    clock[0] += readiness.REPAIR_FAILURE_COOLDOWN_SECONDS
    with pytest.raises(readiness.BlobContainerUnavailableError):
        write(storage)
    assert storage.creates == 2 and storage.writes == 21
    storage.error = None
    created = readiness.create_missing_blob_container(storage, "personal-chat")
    result = write(storage)
    assert created is True and result == "saved" and storage.creates == 3


@pytest.mark.parametrize("code,status", [
    ("BlobNotFound", 404), ("AuthorizationFailure", 403), ("ContainerBeingDeleted", 409),
])
def test_other_write_errors_are_not_repaired(code, status):
    storage = Storage()
    error = storage_error(code, status)

    def unavailable():
        raise error

    with pytest.raises(HttpResponseError) as raised:
        readiness.write_blob_with_container_recovery(storage, "personal-chat", unavailable)
    assert raised.value is error and storage.creates == 0


def test_unstructured_404_is_not_container_absence():
    storage = Storage()

    def unavailable():
        raise ResourceNotFoundError("PRIVATE missing source")

    with pytest.raises(ResourceNotFoundError):
        readiness.write_blob_with_container_recovery(storage, "personal-chat", unavailable)
    assert storage.creates == 0


def test_only_actual_already_exists_conflicts_are_success():
    storage = Storage()
    storage.error = storage_error("ContainerBeingDeleted", 409)
    with pytest.raises(readiness.BlobContainerUnavailableError):
        readiness.create_missing_blob_container(storage, "personal-chat")
    assert storage.creates == 1 and not storage.exists


def test_subsequently_deleted_container_can_be_repaired():
    storage = Storage()
    first = write(storage)
    storage.exists = False
    second = write(storage)
    assert first == second == "saved" and storage.creates == 2


def test_second_missing_response_is_terminal_and_cooled_down():
    storage = Storage()
    calls = []

    def still_missing():
        calls.append("write")
        raise storage_error("ContainerNotFound")

    for _ in range(2):
        with pytest.raises(readiness.BlobContainerUnavailableError):
            readiness.write_blob_with_container_recovery(storage, "personal-chat", still_missing)
    assert calls == ["write", "write", "write"] and storage.creates == 1


def test_recovery_does_not_write_after_authority_is_revoked():
    storage = Storage()

    def denied():
        raise PermissionError("Access changed")

    with pytest.raises(PermissionError):
        write(storage, before_retry=denied)
    assert storage.writes == 1 and storage.creates == 0


def test_cache_is_bounded_and_configuration_changes_do_not_inherit_failures():
    storages = [Storage() for _ in range(readiness.MAX_CACHED_CONTAINERS + 1)]
    for storage in storages:
        storage.exists = True
        write(storage)
    assert len(readiness._states) <= readiness.MAX_CACHED_CONTAINERS
    first = Storage()
    first.error = storage_error("AuthorizationFailure", 403)
    with pytest.raises(readiness.BlobContainerUnavailableError):
        write(first)
    replacement = Storage()
    result = write(replacement)
    assert result == "saved" and replacement.creates == 1


def test_actual_module_import_is_bootstrap_free():
    probe = """
import socket
import sys
def blocked(*args, **kwargs):
    raise AssertionError('Network access during import')
socket.socket.connect = blocked
socket.getaddrinfo = blocked
import blob_container_readiness
for name in ('config', 'functions_settings', 'functions_appinsights'):
    if name in sys.modules:
        raise AssertionError('Storage helper imported its bootstrap owner')
"""
    for flags in ([], ["-O"]):
        result = subprocess.run(
            [sys.executable, *flags, "-c", probe], cwd=APP, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
