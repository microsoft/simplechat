#!/usr/bin/env python3
# test_data_management_blob_backup_transfers.py
"""
Functional test for high-throughput resumable source-blob backups.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures source blobs use bounded block transfers, framed encryption,
verified resume, adaptive retry, isolated failures, and coordinator-owned
durable outcomes without leaking sensitive provider errors.
"""

import copy
import importlib.util
import io
from pathlib import Path
import struct
import sys
import threading
import time
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
BENCHMARK_PATH = REPO_ROOT / "functional_tests" / "benchmark_data_management_blob_backup.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_backup_state import initialize_backup_state


class FakeBlobError(Exception):
    """Expose Azure-like status and retry headers."""

    def __init__(self, status_code, message="blob operation failed", headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = types.SimpleNamespace(
            status_code=status_code,
            headers=headers or {},
        )


class FakeDownload:
    """Write one bounded range into a caller-provided stream."""

    def __init__(self, payload):
        self.payload = payload

    def readinto(self, stream):
        stream.write(self.payload)
        return len(self.payload)


class FakeSourceBlobClient:
    """Serve immutable ranges and optionally inject one provider failure."""

    def __init__(self, data, etag, transient_error=None, permanent_error=None):
        self.data = data
        self.etag = etag
        self.transient_error = transient_error
        self.permanent_error = permanent_error
        self.range_lengths = []
        self.download_calls = 0
        self.mutate_after_download = False

    def get_blob_properties(self):
        return types.SimpleNamespace(
            name="source.bin",
            size=len(self.data),
            etag=self.etag,
            last_modified="2026-07-30T12:00:00+00:00",
        )

    def download_blob(self, **kwargs):
        self.download_calls += 1
        if self.permanent_error is not None:
            raise self.permanent_error
        if self.transient_error is not None:
            error = self.transient_error
            self.transient_error = None
            raise error
        if kwargs.get("etag") and kwargs["etag"] != self.etag:
            raise FakeBlobError(412, "source condition failed")
        offset = int(kwargs.get("offset") or 0)
        length = int(kwargs.get("length") or len(self.data))
        self.range_lengths.append(length)
        payload = self.data[offset:offset + length]
        if self.mutate_after_download and offset + length >= len(self.data):
            self.etag = '"etag-mutated"'
        return FakeDownload(payload)


class FakeSourceContainer:
    """List source properties and return matching range clients."""

    def __init__(self, blobs):
        self.blobs = blobs

    def list_blobs(self):
        for blob_name, blob_client in self.blobs.items():
            properties = blob_client.get_blob_properties()
            properties.name = blob_name
            yield properties

    def get_blob_client(self, blob_name):
        return self.blobs[blob_name]


class FakeTargetBlobClient:
    """Stage blocks and retain metadata for verification and resume."""

    def __init__(self, container, blob_name):
        self.container = container
        self.blob_name = blob_name
        self.uncommitted = {}
        self.committed_blocks = []
        self.content = None
        self.metadata = {}
        self.etag_counter = 0

    def _start_transfer(self):
        self.container.start_transfer(self.blob_name)

    def _finish_transfer(self):
        self.container.finish_transfer(self.blob_name)

    def get_blob_properties(self):
        if self.blob_name in self.container.property_error_names:
            raise FakeBlobError(500, "target lookup failed")
        if self.content is None:
            raise FakeBlobError(404, "missing")
        return types.SimpleNamespace(
            size=len(self.content),
            metadata=copy.deepcopy(self.metadata),
            etag=f'"target-{self.etag_counter}"',
        )

    def stage_block(self, block_id, data, **_kwargs):
        self._start_transfer()
        if self.container.stage_delay:
            time.sleep(self.container.stage_delay)
        payload = data.read() if hasattr(data, "read") else bytes(data)
        self.uncommitted[block_id] = payload

    def commit_block_list(self, block_list, metadata=None, **_kwargs):
        self._check_condition(_kwargs)
        self.committed_blocks = [
            self.uncommitted[block.id]
            for block in block_list
        ]
        self.content = b"".join(self.committed_blocks)
        self.metadata = copy.deepcopy(metadata or {})
        self.etag_counter += 1

    def upload_blob(self, data, metadata=None, **_kwargs):
        self._check_condition(_kwargs)
        self._start_transfer()
        self.content = data.read() if hasattr(data, "read") else bytes(data)
        self.committed_blocks = [self.content]
        self.metadata = copy.deepcopy(metadata or {})
        self.etag_counter += 1

    def set_blob_metadata(self, metadata, **_kwargs):
        self._check_condition(_kwargs)
        self.metadata = copy.deepcopy(metadata)
        self.etag_counter += 1
        self._finish_transfer()

    def _check_condition(self, kwargs):
        condition = kwargs.get("match_condition")
        if condition is None:
            return
        condition_name = getattr(condition, "name", "")
        if condition_name == "IfMissing" and self.content is not None:
            raise FakeBlobError(412, "target already exists")
        if condition_name == "IfNotModified":
            current_etag = f'"target-{self.etag_counter}"'
            if kwargs.get("etag") != current_etag:
                raise FakeBlobError(412, "target changed")


class FakeTargetContainer:
    """Track target content and maximum concurrent file transfers."""

    def __init__(self, stage_delay=0.0, property_error_names=None):
        self.clients = {}
        self.stage_delay = stage_delay
        self.active_names = set()
        self.max_active_transfers = 0
        self.lock = threading.Lock()
        self.property_error_names = set(property_error_names or [])

    def get_blob_client(self, blob_name):
        self.clients.setdefault(blob_name, FakeTargetBlobClient(self, blob_name))
        return self.clients[blob_name]

    def start_transfer(self, blob_name):
        with self.lock:
            self.active_names.add(blob_name)
            self.max_active_transfers = max(
                self.max_active_transfers,
                len(self.active_names),
            )

    def finish_transfer(self, blob_name):
        with self.lock:
            self.active_names.discard(blob_name)


class FakeCosmosContainer:
    """Persist jobs, manifests, and latest-only state in memory."""

    def __init__(self):
        self.documents = {}
        self.counter = 0

    def create_item(self, body):
        return self.upsert_item(body)

    def upsert_item(self, body):
        self.counter += 1
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{self.counter}"
        partition_key = saved.get("source_scope") or saved.get("id")
        self.documents[(partition_key, saved["id"])] = saved
        return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        document = self.documents.get((partition_key, item))
        if document is None:
            raise FakeBlobError(404, "missing")
        return copy.deepcopy(document)

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(list(self.documents.values())))


def load_module(monkeypatch):
    """Load production helpers with in-memory configuration dependencies."""
    jobs = FakeCosmosContainer()
    latest_state = FakeCosmosContainer()
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.102"
    config_module.cosmos_data_management_jobs_container = jobs
    config_module.cosmos_data_management_job_items_container = jobs
    config_module.cosmos_settings_container = jobs
    config_module.cosmos_data_management_backup_item_states_container = latest_state
    monkeypatch.setitem(sys.modules, "config", config_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    throughput_module = types.ModuleType("functions_cosmos_throughput")
    throughput_module.CosmosThroughputError = RuntimeError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)

    module_name = "data_management_blob_backup_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module, jobs, latest_state


def load_benchmark_module():
    """Load the operator harness without running its command-line entry point."""
    module_name = "data_management_blob_backup_benchmark_test_module"
    spec = importlib.util.spec_from_file_location(module_name, BENCHMARK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def build_plan(parallel_operations=2, chunk_size_mib=1, retry_count=3):
    """Build the immutable source-blob execution contract."""
    return {
        "backup_type": "partial",
        "source_scope": "simplechat-primary",
        "source_cutoff_at": "2099-01-01T00:00:00+00:00",
        "differential_mode": "latest_item_state",
        "include_cosmos": False,
        "include_ai_search": False,
        "include_source_blobs": True,
        "backup_storage_container_name": "simplechat-backups",
        "backup_storage_path_prefix": "simplechat-backups",
        "storage_identity": "test-storage",
        "encryption_enabled": False,
        "encryption_key_fingerprint": "",
        "source_blob_execution": {
            "max_parallel_operations": parallel_operations,
            "chunk_size_mib": chunk_size_mib,
            "retry_count": retry_count,
            "clean_transfer_recovery_count": 3,
        },
        "resource_contract": ["cosmos", "ai_search", "source_blobs"],
    }


def build_job(module, plan):
    """Create a running job accepted by the source-blob resource helper."""
    job_id = "11111111-1111-1111-1111-111111111111"
    state = initialize_backup_state(
        None,
        job_id,
        plan,
        plan["source_scope"],
        plan["source_cutoff_at"],
    )
    return {
        "id": job_id,
        "operation": "backup",
        "status": "running",
        "backup_attempt_id": "attempt-1",
        "lease_generation": 1,
        "backup_plan": plan,
        "backup_state": state,
    }


def source_item(module, source_client, blob_name="source.bin"):
    """Build source identity/version from the same properties used by production."""
    return module._build_backup_blob_source_item(
        "documents",
        blob_name,
        source_client.get_blob_properties(),
    )


def decode_encrypted_blocks(module, fernet, blocks):
    """Decode the framed Fernet block format without joining encrypted input first."""
    decoded = io.BytesIO()
    expected_source_digest = None
    for index, block in enumerate(blocks):
        payload = block
        if index == 0:
            assert payload.startswith(module.DATA_MANAGEMENT_BLOB_BACKUP_ENCRYPTED_MAGIC)
            payload = payload[len(module.DATA_MANAGEMENT_BLOB_BACKUP_ENCRYPTED_MAGIC):]
        token_length = struct.unpack(">I", payload[:4])[0]
        token = payload[4:4 + token_length]
        assert len(token) == token_length
        authenticated = fernet.decrypt(token)
        source_digest = authenticated[:32]
        chunk_index, total_chunks, is_final = struct.unpack(
            ">QQ?",
            authenticated[32:module.DATA_MANAGEMENT_BLOB_BACKUP_ENCRYPTED_HEADER_SIZE],
        )
        expected_source_digest = expected_source_digest or source_digest
        assert source_digest == expected_source_digest
        assert chunk_index == index
        assert total_chunks == len(blocks)
        assert is_final is (index == len(blocks) - 1)
        decoded.write(authenticated[module.DATA_MANAGEMENT_BLOB_BACKUP_ENCRYPTED_HEADER_SIZE:])
    return decoded.getvalue()


def test_transfer_chunks_and_reuses_verified_unencrypted_artifact(monkeypatch):
    """Verify raw blobs never require whole-file buffering and resume avoids reads."""
    module, _jobs, _latest_state = load_module(monkeypatch)
    data = (b"bounded-transfer-" * 200000) + b"tail"
    source = FakeSourceBlobClient(data, '"etag-1"')
    target = FakeTargetContainer()
    job = build_job(module, build_plan())

    result = module._transfer_backup_source_blob(
        target,
        source,
        "backup/documents/source.bin",
        source_item(module, source),
        backup_job=job,
        chunk_size_bytes=1024 * 1024,
        retry_count=3,
    )

    assert result["status"] == "succeeded"
    assert max(source.range_lengths) <= 1024 * 1024
    assert len(source.range_lengths) > 1
    target_blob = target.get_blob_client(result["artifact_path"])
    assert target_blob.content == data
    assert target_blob.metadata["simplechatbackupstatus"] == "succeeded"

    download_calls = source.download_calls
    reused = module._transfer_backup_source_blob(
        target,
        source,
        "backup/documents/source.bin",
        source_item(module, source),
        backup_job=job,
        chunk_size_bytes=1024 * 1024,
        retry_count=3,
    )
    assert reused["status"] == "reused"
    assert source.download_calls == download_calls


def test_encrypted_transfer_uses_versioned_authenticated_frames(monkeypatch):
    """Verify encrypted artifacts preserve plaintext through bounded Fernet frames."""
    module, _jobs, _latest_state = load_module(monkeypatch)
    data = (b"encrypted-bounded-transfer-" * 100000) + b"tail"
    source = FakeSourceBlobClient(data, '"etag-encrypted"')
    target = FakeTargetContainer()
    job = build_job(module, build_plan())
    fernet = module.Fernet(module.Fernet.generate_key())

    result = module._transfer_backup_source_blob(
        target,
        source,
        "backup/documents/encrypted.bin",
        source_item(module, source, "encrypted.bin"),
        fernet=fernet,
        backup_job=job,
        chunk_size_bytes=1024 * 1024,
        retry_count=3,
    )

    assert result["transfer_format"] == "fernet-chunked-v1"
    target_blob = target.get_blob_client(result["artifact_path"])
    assert decode_encrypted_blocks(module, fernet, target_blob.committed_blocks) == data
    assert target_blob.metadata["simplechatbackupformat"] == "fernet-chunked-v1"
    with pytest.raises(AssertionError):
        decode_encrypted_blocks(
            module,
            fernet,
            list(reversed(target_blob.committed_blocks)),
        )


def test_transfer_retries_throttle_and_sanitizes_terminal_failure(monkeypatch):
    """Verify Retry-After pressure is counted and provider secrets never persist."""
    module, _jobs, _latest_state = load_module(monkeypatch)
    monkeypatch.setattr(module, "_get_backup_retry_delay", lambda *_args: 0.001)
    throttled_source = FakeSourceBlobClient(
        b"retry-me",
        '"etag-retry"',
        transient_error=FakeBlobError(
            429,
            "throttled token=must-not-leak",
            {"x-ms-retry-after-ms": "1"},
        ),
    )
    target = FakeTargetContainer()
    job = build_job(module, build_plan())

    result = module._transfer_backup_source_blob(
        target,
        throttled_source,
        "backup/documents/retry.bin",
        source_item(module, throttled_source, "retry.bin"),
        backup_job=job,
        chunk_size_bytes=1024 * 1024,
        retry_count=3,
    )
    assert result["status"] == "succeeded"
    assert result["retry_attempt_count"] == 1
    assert result["throttle_count"] == 1

    failed_source = FakeSourceBlobClient(
        b"fail-me",
        '"etag-fail"',
        permanent_error=FakeBlobError(403, "denied token=must-not-leak"),
    )
    failed = module._transfer_backup_source_blob(
        target,
        failed_source,
        "backup/documents/fail.bin",
        source_item(module, failed_source, "fail.bin"),
        backup_job=job,
        chunk_size_bytes=1024 * 1024,
        retry_count=3,
    )
    assert failed["status"] == "failed"
    assert failed["failure_summary"] == "[redacted operational detail]"
    assert "must-not-leak" not in str(failed)


def test_source_mutation_does_not_mark_artifact_succeeded(monkeypatch):
    """Verify a changed ETag leaves a pending artifact eligible for safe retry."""
    module, _jobs, _latest_state = load_module(monkeypatch)
    source = FakeSourceBlobClient(b"mutable", '"etag-before"')
    source.mutate_after_download = True
    target = FakeTargetContainer()
    job = build_job(module, build_plan())

    result = module._transfer_backup_source_blob(
        target,
        source,
        "backup/documents/mutable.bin",
        source_item(module, source, "mutable.bin"),
        backup_job=job,
        chunk_size_bytes=1024 * 1024,
        retry_count=2,
    )

    assert result["status"] == "failed"
    artifact = target.get_blob_client(result["artifact_path"])
    assert artifact.metadata["simplechatbackupstatus"] == "pending"


def test_newer_target_generation_fences_stale_attempt(monkeypatch):
    """Verify an older worker cannot accept or overwrite a newer attempt artifact."""
    module, _jobs, _latest_state = load_module(monkeypatch)
    source = FakeSourceBlobClient(b"fenced", '"etag-fenced"')
    target = FakeTargetContainer()
    plan = build_plan()
    newer_job = build_job(module, plan)
    newer_job["backup_attempt_id"] = "attempt-2"
    newer_job["lease_generation"] = 2
    item = source_item(module, source, "fenced.bin")
    succeeded = module._transfer_backup_source_blob(
        target,
        source,
        "backup/documents/fenced.bin",
        item,
        backup_job=newer_job,
        chunk_size_bytes=1024 * 1024,
        retry_count=2,
    )
    assert succeeded["status"] == "succeeded"

    stale_job = build_job(module, plan)
    stale_job["backup_attempt_id"] = "attempt-1"
    stale_job["lease_generation"] = 1
    with pytest.raises(module.DataManagementBackupLeaseLostError):
        module._transfer_backup_source_blob(
            target,
            source,
            "backup/documents/fenced.bin",
            item,
            backup_job=stale_job,
            chunk_size_bytes=1024 * 1024,
            retry_count=2,
        )


def test_resource_bounds_parallelism_and_isolates_failed_files(monkeypatch):
    """Verify one failed file does not abort concurrent neighboring transfers."""
    module, jobs, _latest_state = load_module(monkeypatch)
    monkeypatch.setattr(module, "_sync_backup_latest_item_state_from_manifest", lambda *_args: None)
    monkeypatch.setattr(module, "_assert_backup_job_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_persist_backup_heartbeat", lambda *_args, **_kwargs: None)

    def persist(_job, state, _settings, resource_name, progress, checkpoint, _message):
        module.update_backup_resource(state, resource_name, progress, checkpoint=checkpoint)
        return state

    def complete(_job, state, _settings, resource_name, result, _message):
        module.complete_backup_resource(state, resource_name, result)
        return state

    def fail(_job, state, _settings, resource_name, error_message, _message, result=None):
        resource = module.fail_backup_resource(state, resource_name, error_message)
        resource["result"] = copy.deepcopy(result or {})
        return state

    monkeypatch.setattr(module, "_persist_backup_checkpoint", persist)
    monkeypatch.setattr(module, "_complete_backup_resource_checkpoint", complete)
    monkeypatch.setattr(module, "_fail_backup_resource_checkpoint", fail)
    monkeypatch.setattr(module, "_get_backup_retry_delay", lambda *_args: 0.001)

    plan = build_plan(parallel_operations=2)
    job = build_job(module, plan)
    source_container = FakeSourceContainer({
        "one.bin": FakeSourceBlobClient(b"one" * 400000, '"etag-one"'),
        "two.bin": FakeSourceBlobClient(
            b"two",
            '"etag-two"',
            transient_error=FakeBlobError(429, "pressure", {"retry-after": "0.001"}),
        ),
        "three.bin": FakeSourceBlobClient(b"three" * 300000, '"etag-three"'),
        "failed.bin": FakeSourceBlobClient(b"failed", '"etag-failed"'),
    })
    target = FakeTargetContainer(
        stage_delay=0.01,
        property_error_names={"simplechat-backups/job/source_blobs/documents/failed.bin"},
    )

    result = module._execute_backup_source_blob_resource(
        job,
        job["backup_state"],
        {},
        target,
        "simplechat-backups/job",
        None,
        source_container,
        "documents",
    )

    assert result["blob_count"] == 3
    assert result["failed_count"] == 1
    assert result["throttle_count"] == 1
    assert 2 <= target.max_active_transfers <= 2
    manifests = [
        document
        for document in jobs.documents.values()
        if document.get("type") == module.DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE
    ]
    outcomes = [
        entry["status"]
        for manifest in manifests
        for entry in manifest["entries"]
    ]
    assert outcomes.count("succeeded") == 3
    assert outcomes.count("failed") == 1


def test_transfer_observes_cancellation_before_remote_work(monkeypatch):
    """Verify cooperative cancellation prevents any source or target operation."""
    module, _jobs, _latest_state = load_module(monkeypatch)
    source = FakeSourceBlobClient(b"cancel", '"etag-cancel"')
    target = FakeTargetContainer()
    job = build_job(module, build_plan())
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(module.DataManagementBackupCanceledError):
        module._transfer_backup_source_blob(
            target,
            source,
            "backup/documents/cancel.bin",
            source_item(module, source, "cancel.bin"),
            backup_job=job,
            chunk_size_bytes=1024 * 1024,
            retry_count=3,
            cancel_event=cancel_event,
        )
    assert source.download_calls == 0


def test_benchmark_never_places_sas_values_in_azcopy_arguments():
    """Verify process-visible AzCopy URLs reject SAS-bearing candidates."""
    benchmark = load_benchmark_module()
    result = benchmark.run_azcopy_candidate(
        "https://source.example/container?sig=source-secret",
        "https://target.example/container?sig=target-secret",
        "benchmark/run",
    )
    assert result["status"] == "skipped"
    assert "process-visible" in result["reason"]
    assert "source-secret" not in str(result)
    assert "target-secret" not in str(result)
