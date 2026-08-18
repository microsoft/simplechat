#!/usr/bin/env python3
# test_data_management_backup_source_blob_etag.py
"""
Functional test for source blob backup ETag normalization and checkpoint batching.
Version: 0.250.219
Implemented in: 0.250.219

This test ensures source blob backups survive the ETag quoting difference between
list_blobs() (XML <Etag> element, unquoted) and get_blob_properties() (HTTP ETag
header, RFC quoted). That mismatch previously failed every source blob with
"Source blob changed while it was being backed up." and zero retries, so no
source document or chat attachment was ever backed up.

Test functions assert directly and return None so pytest reports real failures.
"""

import importlib.util
from pathlib import Path
import sys
import types

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

RAW_ETAG = "0x8DE9A1B2C3D4E5F"


class FakeListedBlobProperties:
    """Model a list_blobs() result, whose XML ETag element carries no quotes."""

    def __init__(self, name, size, etag):
        self.name = name
        self.size = size
        self.etag = etag
        self.last_modified = "2026-08-18T03:00:00+00:00"


class FakeFetchedBlobProperties:
    """Model a get_blob_properties() result, whose HTTP ETag header is RFC quoted."""

    def __init__(self, size, etag, metadata=None):
        self.size = size
        self.etag = f'"{etag}"'
        self.metadata = metadata or {}


class FakeNotFound(Exception):
    """Stand in for a missing destination blob or a failed precondition."""

    status_code = 404


class FakeDownload:
    """Return a fixed payload for a ranged source read."""

    def __init__(self, payload):
        self._payload = payload

    def readinto(self, buffer):
        buffer.write(self._payload)
        return len(self._payload)


class FakeSourceBlobClient:
    """Serve ranged reads and a quoted ETag, mirroring real Blob Storage behavior."""

    def __init__(self, payload, etag, etag_after_download=None):
        self._payload = payload
        self._etag = etag
        self._etag_after_download = etag_after_download
        self._downloaded = False
        self.download_calls = []

    def download_blob(self, offset=0, length=None, **kwargs):
        condition_etag = kwargs.get("etag")
        self.download_calls.append(condition_etag)
        # Azure accepts If-Match with or without transport quoting.
        if condition_etag and condition_etag.strip('"') != self._etag.strip('"'):
            raise FakeNotFound()
        self._downloaded = True
        end = offset + (length if length is not None else len(self._payload))
        return FakeDownload(self._payload[offset:end])

    def get_blob_properties(self):
        current_etag = self._etag
        if self._downloaded and self._etag_after_download:
            current_etag = self._etag_after_download
        return FakeFetchedBlobProperties(len(self._payload), current_etag)


class FakeTargetBlobClient:
    """Accept staged blocks and record the committed artifact."""

    def __init__(self):
        self.blocks = {}
        self.committed = None
        self.metadata = {}

    def get_blob_properties(self):
        if self.committed is None:
            raise FakeNotFound()
        return FakeFetchedBlobProperties(len(self.committed), "0xTARGETETAG", self.metadata)

    def upload_blob(self, data=None, **kwargs):
        self.committed = data
        self.metadata = dict(kwargs.get("metadata") or {})

    def stage_block(self, block_id=None, data=None, **_kwargs):
        self.blocks[block_id] = data

    def commit_block_list(self, block_list, **kwargs):
        self.committed = b"".join(self.blocks[block.id] for block in block_list)
        self.metadata = dict(kwargs.get("metadata") or {})

    def set_blob_metadata(self, metadata=None, **_kwargs):
        self.metadata = dict(metadata or {})


class FakeTargetContainerClient:
    """Hand out a single reusable destination blob client."""

    def __init__(self, blob_client):
        self._blob_client = blob_client

    def get_blob_client(self, _name):
        return self._blob_client


def load_data_management_module():
    """Load production backup helpers with stubbed infrastructure dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.219"
    config_module.cosmos_data_management_jobs_container = None
    config_module.cosmos_data_management_job_items_container = None
    config_module.cosmos_settings_container = None
    sys.modules["config"] = config_module

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_a, **_k: None
    sys.modules["functions_appinsights"] = appinsights_module

    throughput_module = types.ModuleType("functions_cosmos_throughput")

    class FakeCosmosThroughputError(Exception):
        pass

    throughput_module.CosmosThroughputError = FakeCosmosThroughputError
    throughput_module.get_container_throughput = lambda *_a, **_k: {}
    throughput_module.get_database_throughput = lambda *_a, **_k: {}
    throughput_module.set_database_throughput = lambda *_a, **_k: {}
    sys.modules["functions_cosmos_throughput"] = throughput_module

    module_name = "data_management_backup_etag_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    sys.modules.pop(module_name, None)
    return module


def run_transfer(module, source_client, source_item, retry_count=1):
    """Run the production transfer against in-memory blob clients."""
    target_client = FakeTargetBlobClient()
    result = module._transfer_backup_source_blob(
        FakeTargetContainerClient(target_client),
        source_client,
        "backups/source_blobs/personal-chat/attachment.bin",
        source_item,
        fernet=None,
        backup_job={"id": "job-1", "backup_attempt_id": "attempt-1", "lease_generation": 1},
        chunk_size_bytes=None,
        retry_count=retry_count,
    )
    return result, target_client


def test_etag_normalization_strips_transport_quoting():
    """Quoted, unquoted, and weak ETags must normalize to the same value."""
    module = load_data_management_module()
    normalize = module._normalize_backup_etag

    assert normalize(RAW_ETAG) == RAW_ETAG
    assert normalize(f'"{RAW_ETAG}"') == RAW_ETAG, "Quoted header ETag must normalize"
    assert normalize(f'W/"{RAW_ETAG}"') == RAW_ETAG, "Weak validator must normalize"
    assert normalize(f'  "{RAW_ETAG}"  ') == RAW_ETAG, "Surrounding space must normalize"
    assert normalize(None) == "", "Missing ETag must normalize to empty"
    assert normalize("") == ""


def test_listed_and_fetched_etags_compare_equal():
    """A list_blobs ETag must match the same blob's get_blob_properties ETag."""
    module = load_data_management_module()

    listed = FakeListedBlobProperties("chat/abc.png", 2048, RAW_ETAG)
    source_item = module._build_backup_blob_source_item("personal-chat", listed.name, listed)

    assert source_item["source_etag"] == RAW_ETAG, (
        "The conditional-header ETag must be preserved exactly as listed"
    )

    fetched = FakeFetchedBlobProperties(2048, RAW_ETAG)
    assert fetched.etag != source_item["source_etag"], (
        "This test is meaningless unless the two transport formats differ"
    )
    assert (
        module._normalize_backup_etag(fetched.etag) ==
        module._normalize_backup_etag(source_item["source_etag"])
    ), "Listed and fetched ETags must compare equal after normalization"


def test_transfer_succeeds_across_list_and_get_etag_formats():
    """The real transfer path must not treat quoting differences as a changed blob."""
    module = load_data_management_module()

    payload = b"simplechat source blob payload" * 64
    listed = FakeListedBlobProperties("chat/attachment.bin", len(payload), RAW_ETAG)
    source_item = module._build_backup_blob_source_item("personal-chat", listed.name, listed)
    source_client = FakeSourceBlobClient(payload, RAW_ETAG)

    result, target_client = run_transfer(module, source_client, source_item)

    assert result["status"] == "succeeded", (
        f"Transfer must succeed, got {result['status']!r} ({result.get('failure_summary')!r})"
    )
    assert result["source_bytes"] == len(payload)
    assert target_client.committed == payload, "Committed artifact must match the source"
    assert target_client.metadata.get("simplechatbackupstatus") == "succeeded", (
        "Artifact metadata must be promoted from pending to succeeded"
    )
    assert result["retry_attempt_count"] == 0, "A clean transfer must not retry"


def test_genuinely_changed_source_blob_still_fails():
    """A real mid-transfer source change must still be rejected."""
    module = load_data_management_module()

    payload = b"payload"
    listed = FakeListedBlobProperties("chat/changed.bin", len(payload), RAW_ETAG)
    source_item = module._build_backup_blob_source_item("personal-chat", listed.name, listed)
    source_client = FakeSourceBlobClient(
        payload,
        RAW_ETAG,
        etag_after_download="0xCHANGEDMIDTRANSFER",
    )

    result, _target_client = run_transfer(module, source_client, source_item)

    assert result["status"] == "failed", (
        f"A changed source blob must still fail, got {result['status']!r}"
    )
    assert "changed while it was being backed up" in result["failure_summary"], (
        f"Failure summary must name the source change, got {result['failure_summary']!r}"
    )


def test_verified_artifact_matches_source_version():
    """Reused-artifact detection must still key off the recorded source version."""
    module = load_data_management_module()

    listed = FakeListedBlobProperties("docs/report.pdf", 4096, RAW_ETAG)
    source_item = module._build_backup_blob_source_item("user-documents", listed.name, listed)
    backup_job = {"id": "job-1", "backup_attempt_id": "attempt-1", "lease_generation": 2}
    transfer_format = module.DATA_MANAGEMENT_BLOB_BACKUP_RAW_FORMAT

    metadata = module._build_backup_blob_target_metadata(
        backup_job,
        source_item,
        transfer_format,
        "succeeded",
    )
    target_properties = {"metadata": metadata, "size": 4096}

    assert module._is_verified_backup_blob_artifact(
        target_properties,
        backup_job,
        source_item,
        transfer_format,
    ), "A succeeded artifact for the same source version must verify as reusable"

    changed = module._build_backup_blob_source_item(
        "user-documents",
        listed.name,
        FakeListedBlobProperties(listed.name, 4096, "0xDIFFERENTETAG"),
    )
    assert not module._is_verified_backup_blob_artifact(
        target_properties,
        backup_job,
        changed,
        transfer_format,
    ), "A genuinely changed source version must not verify as reusable"


def test_checkpoint_interval_is_bounded():
    """Checkpoint batching must stay bounded so resume work stays small."""
    module = load_data_management_module()
    interval = module.DATA_MANAGEMENT_BACKUP_CHECKPOINT_INTERVAL_SECONDS
    batch_size = module.DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE

    assert 1 <= interval <= 60, f"Checkpoint interval must stay within a minute, got {interval}"
    assert 1 <= batch_size <= 500, f"Manifest batch size must stay bounded, got {batch_size}"


def test_version_is_at_least_fix_version():
    """The shipped app version must include this fix."""
    assert_app_version_at_least("0.250.219")


if __name__ == "__main__":
    tests = [
        test_etag_normalization_strips_transport_quoting,
        test_listed_and_fetched_etags_compare_equal,
        test_transfer_succeeds_across_list_and_get_etag_formats,
        test_genuinely_changed_source_blob_still_fails,
        test_verified_artifact_matches_source_version,
        test_checkpoint_interval_is_bounded,
        test_version_is_at_least_fix_version,
    ]
    failures = 0
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed!")
        except Exception as exc:
            failures += 1
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()

    print(f"\nResults: {len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
