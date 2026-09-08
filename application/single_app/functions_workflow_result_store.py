# functions_workflow_result_store.py
"""
Private, immutable persistence for workflow task result envelopes.
Version: 0.261.106
Implemented in: 0.261.106

Callers must authorize the workflow and run before using this module. Storage
additionally binds every object to personal user/group, workflow, run, and task.
It does not interpret or alter the result contract inside the JSON envelope.

Configured Blob storage is the write backend. Without an optional Blob client,
payloads use bounded chunks in the existing workflow_run_items container. A Blob
failure never switches backends. Both backends keep a small completion manifest;
all internal Cosmos records have type and item_type 'workflow_result_chunk'.

References contain only storage, schema_version (the storage format, not the
envelope contract), sha256, size_bytes, and chunk_count. Paths are reconstructed
from hashed identities. JSON is canonical ASCII, so page offsets count serialized
bytes and page content may split a JSON token or Unicode escape. A partial page
does not claim to verify the full-result digest. No local persistence is used.
"""

import hashlib
import json
import re
from collections.abc import Mapping

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from azure.storage.blob import ContentSettings


STORAGE_SCHEMA_VERSION = 1
RESULT_RECORD_TYPE = "workflow_result_chunk"
RESULT_MEDIA_TYPE = "application/json"
DEFAULT_MAX_RESULT_SIZE_MB = 500
MAX_COSMOS_CHUNK_BYTES = 256 * 1024
MAX_PAGE_BYTES = 256 * 1024
DEFAULT_PAGE_BYTES = 65536
REFERENCE_FIELDS = ("storage", "schema_version", "sha256", "size_bytes", "chunk_count")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class WorkflowResultIntegrityError(ValueError):
    """Stored identity, metadata, or payload does not match the expected result."""


class WorkflowResultTooLargeError(ValueError):
    """The complete serialized result exceeds the configured artifact quota."""


class WorkflowResultStorageUnavailableError(RuntimeError):
    """The backend required by an existing result is no longer configured."""


def _positive_integer(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _identifier(value):
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise ValueError("Workflow result identifiers must be nonempty strings of at most 1024 bytes.")
    return value


def _workflow_scope(workflow):
    if not isinstance(workflow, Mapping):
        raise ValueError("An authorized workflow mapping is required.")
    workflow_id = _identifier(workflow.get("id"))
    user_id = _identifier(workflow.get("user_id"))
    group_id = workflow.get("group_id")
    is_group = group_id is not None and group_id != ""
    return {
        "scope_type": "group" if is_group else "personal",
        "scope_id": _identifier(group_id) if is_group else user_id,
        "workflow_id": workflow_id,
    }


def _scope(workflow, run_id):
    return {**_workflow_scope(workflow), "run_id": _identifier(run_id)}


def _identity(workflow, run_id, task_id):
    return {**_scope(workflow, run_id), "task_id": _identifier(task_id)}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _hash_identifier(value):
    return _sha256(value.encode("utf-8"))


def _record_id(identity, reference, kind, index=None):
    token = _sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("ascii"))
    suffix = kind if index is None else f"{kind}:{index}"
    return f"workflow-result:v{STORAGE_SCHEMA_VERSION}:{token}:{reference['storage']}:{reference['sha256']}:{suffix}"


def _run_blob_prefix(scope):
    return (
        f"workflow-results/v{STORAGE_SCHEMA_VERSION}/{scope['scope_type']}/"
        f"{_hash_identifier(scope['scope_id'])}/{_hash_identifier(scope['workflow_id'])}/"
        f"{_hash_identifier(scope['run_id'])}/"
    )


def _blob_name(identity, reference):
    return f"{_run_blob_prefix(identity)}{_hash_identifier(identity['task_id'])}/{reference['sha256']}.json"


def _blob_metadata(identity, reference):
    return {
        "schema_version": str(STORAGE_SCHEMA_VERSION),
        "scope_type": identity["scope_type"],
        "scope_hash": _hash_identifier(identity["scope_id"]),
        "workflow_hash": _hash_identifier(identity["workflow_id"]),
        "run_hash": _hash_identifier(identity["run_id"]),
        "task_hash": _hash_identifier(identity["task_id"]),
        "sha256": reference["sha256"],
        "size_bytes": str(reference["size_bytes"]),
        "media_type": RESULT_MEDIA_TYPE,
    }


def _require_fields(record, expected):
    if not isinstance(record, Mapping) or any(
        type(record.get(key)) is not type(value) or record.get(key) != value
        for key, value in expected.items()
    ):
        raise WorkflowResultIntegrityError("Stored workflow result identity or metadata does not match.")


def _validate_reference(reference):
    if not isinstance(reference, Mapping) or set(reference) != set(REFERENCE_FIELDS):
        raise ValueError("Invalid workflow result reference.")
    reference = dict(reference)
    if reference["storage"] not in ("blob", "cosmos"):
        raise ValueError("Invalid workflow result storage backend.")
    if type(reference["schema_version"]) is not int or reference["schema_version"] != STORAGE_SCHEMA_VERSION:
        raise ValueError("Unsupported workflow result storage version.")
    if not isinstance(reference["sha256"], str) or not _DIGEST_PATTERN.fullmatch(reference["sha256"]):
        raise ValueError("Invalid workflow result digest.")
    _positive_integer(reference["size_bytes"], "Result size")
    count = reference["chunk_count"]
    if type(count) is not int or (count != 0 if reference["storage"] == "blob" else count <= 0):
        raise ValueError("Invalid workflow result chunk count.")
    return reference


def _verify_payload(data, reference):
    if len(data) != reference["size_bytes"] or _sha256(data) != reference["sha256"]:
        raise WorkflowResultIntegrityError("Stored workflow result size or digest does not match.")


def _quota_bytes(settings):
    if not isinstance(settings, Mapping):
        raise ValueError("Workflow result settings must be a mapping.")
    value = settings.get("max_generated_chat_artifact_size_mb", DEFAULT_MAX_RESULT_SIZE_MB)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    return _positive_integer(value, "Generated artifact size limit in MB") * 1024 * 1024


class WorkflowResultStore:
    """Dependency-injected store; clients may be real SDK clients or isolated fakes.

    ``container`` is the existing personal/group workflow_run_items container,
    partitioned by run_id. ``blob_client`` is a BlobServiceClient, not a BlobClient.
    Quotas apply to new writes, not to already-saved results after a quota change.
    Chunk sizing can be reduced for tests but can never exceed the Cosmos bound.
    """

    def __init__(
        self,
        container,
        blob_client=None,
        blob_container_name=None,
        *,
        max_size_bytes=DEFAULT_MAX_RESULT_SIZE_MB * 1024 * 1024,
        chunk_size_bytes=MAX_COSMOS_CHUNK_BYTES,
    ):
        if container is None:
            raise ValueError("A workflow run-items container is required.")
        if blob_client is not None and (
            not isinstance(blob_container_name, str) or not blob_container_name.strip()
        ):
            raise ValueError("The configured workflow result Blob container name is required.")
        self.container = container
        self.blob_client = blob_client
        self.blob_container_name = blob_container_name
        self.max_size_bytes = _positive_integer(max_size_bytes, "Result size limit")
        self.chunk_size_bytes = _positive_integer(chunk_size_bytes, "Cosmos chunk size")
        if self.chunk_size_bytes > MAX_COSMOS_CHUNK_BYTES:
            raise ValueError("Workflow result chunks exceed the Cosmos payload bound.")

    def _serialize(self, result):
        if not isinstance(result, dict):
            raise ValueError("A workflow task result must be a JSON object.")
        encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        payload = bytearray()
        for fragment in encoder.iterencode(result):
            encoded = fragment.encode("ascii")
            if len(payload) + len(encoded) > self.max_size_bytes:
                raise WorkflowResultTooLargeError(
                    f"Workflow task result exceeds the {self.max_size_bytes} byte size limit."
                )
            payload.extend(encoded)
        return bytes(payload)

    def _manifest(self, identity, reference, chunk_size_bytes):
        return {
            **identity,
            **reference,
            "id": _record_id(identity, reference, "manifest"),
            "type": RESULT_RECORD_TYPE,
            "item_type": RESULT_RECORD_TYPE,
            "record_kind": "manifest",
            "chunk_size_bytes": chunk_size_bytes,
            "media_type": RESULT_MEDIA_TYPE,
        }

    def _create_immutable_record(self, record):
        try:
            self.container.create_item(body=record)
        except CosmosResourceExistsError:
            existing = self.container.read_item(item=record["id"], partition_key=record["run_id"])
            _require_fields(existing, record)

    def _get_blob(self, identity, reference):
        if self.blob_client is None:
            raise WorkflowResultStorageUnavailableError("Workflow result Blob storage is unavailable.")
        return self.blob_client.get_blob_client(
            container=self.blob_container_name, blob=_blob_name(identity, reference),
        )

    def _checked_blob(self, identity, reference):
        blob = self._get_blob(identity, reference)
        properties = blob.get_blob_properties()
        _require_fields(properties.metadata, _blob_metadata(identity, reference))
        if properties.size != reference["size_bytes"]:
            raise WorkflowResultIntegrityError("Stored workflow result Blob size does not match.")
        return blob, properties

    def _blob_chunks(self, identity, reference):
        blob, properties = self._checked_blob(identity, reference)
        return blob.download_blob(
            etag=properties.etag, match_condition=MatchConditions.IfNotModified, validate_content=True,
        ).chunks()

    def save(self, workflow, run_id, task_id, result):
        """Persist an envelope without overwriting another immutable result."""
        identity = _identity(workflow, run_id, task_id)
        payload = self._serialize(result)
        storage = "blob" if self.blob_client is not None else "cosmos"
        reference = {
            "storage": storage,
            "schema_version": STORAGE_SCHEMA_VERSION,
            "sha256": _sha256(payload),
            "size_bytes": len(payload),
            "chunk_count": (
                (len(payload) + self.chunk_size_bytes - 1) // self.chunk_size_bytes
                if storage == "cosmos" else 0
            ),
        }
        manifest = self._manifest(identity, reference, self.chunk_size_bytes if storage == "cosmos" else 0)
        if storage == "blob":
            blob = self._get_blob(identity, reference)
            try:
                blob.upload_blob(
                    data=payload,
                    overwrite=False,
                    metadata=_blob_metadata(identity, reference),
                    content_settings=ContentSettings(content_type=RESULT_MEDIA_TYPE),
                )
            except ResourceExistsError:
                digest = hashlib.sha256()
                size = 0
                for chunk in self._blob_chunks(identity, reference):
                    size += len(chunk)
                    if size > reference["size_bytes"]:
                        raise WorkflowResultIntegrityError("Stored workflow result Blob size does not match.")
                    digest.update(chunk)
                if size != len(payload) or digest.hexdigest() != reference["sha256"]:
                    raise WorkflowResultIntegrityError("An existing workflow result Blob is corrupt.")
        else:
            for index in range(reference["chunk_count"]):
                start = index * self.chunk_size_bytes
                chunk = payload[start:start + self.chunk_size_bytes]
                self._create_immutable_record({
                    **manifest,
                    "id": _record_id(identity, reference, "chunk", index),
                    "record_kind": "chunk",
                    "chunk_index": index,
                    "payload": chunk.decode("ascii"),
                    "payload_size_bytes": len(chunk),
                    "payload_sha256": _sha256(chunk),
                })
        # Publishing the manifest last makes an interrupted write unreadable.
        self._create_immutable_record(manifest)
        return dict(reference)

    def _read_manifest(self, identity, reference):
        reference = _validate_reference(reference)
        manifest = self.container.read_item(
            item=_record_id(identity, reference, "manifest"), partition_key=identity["run_id"],
        )
        chunk_size = manifest.get("chunk_size_bytes")
        if reference["storage"] == "cosmos":
            if type(chunk_size) is not int or not 0 < chunk_size <= MAX_COSMOS_CHUNK_BYTES:
                raise WorkflowResultIntegrityError("Stored workflow result chunk size is invalid.")
            if reference["chunk_count"] != (reference["size_bytes"] + chunk_size - 1) // chunk_size:
                raise WorkflowResultIntegrityError("Stored workflow result chunk count does not match.")
        elif type(chunk_size) is not int or chunk_size != 0:
            raise WorkflowResultIntegrityError("Stored workflow result Blob manifest is invalid.")
        _require_fields(manifest, self._manifest(identity, reference, chunk_size))
        return reference, manifest

    def _read_chunk(self, identity, reference, manifest, index):
        record_id = _record_id(identity, reference, "chunk", index)
        record = self.container.read_item(item=record_id, partition_key=identity["run_id"])
        size = min(manifest["chunk_size_bytes"], reference["size_bytes"] - index * manifest["chunk_size_bytes"])
        expected = {
            **self._manifest(identity, reference, manifest["chunk_size_bytes"]),
            "id": record_id,
            "record_kind": "chunk",
            "chunk_index": index,
            "payload_size_bytes": size,
        }
        _require_fields(record, expected)
        payload = record.get("payload")
        if not isinstance(payload, str) or not payload.isascii():
            raise WorkflowResultIntegrityError("Stored workflow result chunk payload is invalid.")
        payload = payload.encode("ascii")
        if len(payload) != size or _sha256(payload) != record.get("payload_sha256"):
            raise WorkflowResultIntegrityError("Stored workflow result chunk size or digest does not match.")
        return payload

    def load(self, workflow, run_id, task_id, reference):
        """Read the full envelope, verifying metadata, reconstructed size, and SHA-256."""
        identity = _identity(workflow, run_id, task_id)
        reference, manifest = self._read_manifest(identity, reference)
        if reference["storage"] == "blob":
            chunks = self._blob_chunks(identity, reference)
        else:
            chunks = (
                self._read_chunk(identity, reference, manifest, index)
                for index in range(reference["chunk_count"])
            )
        payload = bytearray()
        for chunk in chunks:
            payload.extend(chunk)
            if len(payload) > reference["size_bytes"]:
                raise WorkflowResultIntegrityError("Stored workflow result size does not match.")
        _verify_payload(payload, reference)
        try:
            result = json.loads(payload.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WorkflowResultIntegrityError("Stored workflow result is not a valid JSON envelope.") from None
        if not isinstance(result, dict):
            raise WorkflowResultIntegrityError("Stored workflow result is not a JSON object.")
        return result

    def read_page(self, workflow, run_id, task_id, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES):
        """Read bounded ASCII JSON bytes; complete means EOF, not a complete envelope."""
        if type(offset) is not int or offset < 0:
            raise ValueError("Workflow result page offset must be a nonnegative integer.")
        if type(limit) is not int or not 0 < limit <= MAX_PAGE_BYTES:
            raise ValueError(f"Workflow result page limit must be an integer from 1 to {MAX_PAGE_BYTES}.")
        identity = _identity(workflow, run_id, task_id)
        reference, manifest = self._read_manifest(identity, reference)
        if offset > reference["size_bytes"]:
            raise ValueError("Workflow result page offset is beyond the result size.")
        end = min(offset + limit, reference["size_bytes"])
        payload = bytearray()
        if reference["storage"] == "blob":
            blob, properties = self._checked_blob(identity, reference)
            if end > offset:
                payload.extend(blob.download_blob(
                    offset=offset, length=end - offset,
                    etag=properties.etag, match_condition=MatchConditions.IfNotModified,
                    validate_content=True,
                ).readall())
        elif end > offset:
            chunk_size = manifest["chunk_size_bytes"]
            for index in range(offset // chunk_size, (end - 1) // chunk_size + 1):
                chunk = self._read_chunk(identity, reference, manifest, index)
                start_in_chunk = max(0, offset - index * chunk_size)
                end_in_chunk = min(len(chunk), end - index * chunk_size)
                payload.extend(chunk[start_in_chunk:end_in_chunk])
        if len(payload) != end - offset:
            raise WorkflowResultIntegrityError("Stored workflow result page size does not match.")
        full_verified = offset == 0 and end == reference["size_bytes"]
        if full_verified:
            _verify_payload(payload, reference)
        try:
            content = payload.decode("ascii")
        except UnicodeDecodeError:
            raise WorkflowResultIntegrityError("Stored workflow result page is not canonical JSON bytes.") from None
        return {
            "content": content,
            "offset": offset,
            "next_offset": end if end < reference["size_bytes"] else None,
            "total_bytes": reference["size_bytes"],
            "complete": end == reference["size_bytes"],
            "media_type": RESULT_MEDIA_TYPE,
            "sha256": reference["sha256"],
            "integrity": {
                "full_sha256_verified": full_verified,
                "chunk_sha256_verified": reference["storage"] == "cosmos" and end > offset,
                "page_sha256": _sha256(payload),
            },
        }

    def _delete_run_blobs(self, scope):
        prefix = _run_blob_prefix(scope)
        container = self.blob_client.get_container_client(self.blob_container_name)
        for properties in container.list_blobs(name_starts_with=prefix, include=["metadata"]):
            name = properties.name
            suffix = name[len(prefix):] if isinstance(name, str) and name.startswith(prefix) else ""
            if not re.fullmatch(r"[0-9a-f]{64}/[0-9a-f]{64}\.json", suffix):
                raise WorkflowResultIntegrityError("Unexpected object in the private workflow result prefix.")
            task_hash, digest_filename = suffix.split("/")
            expected = {
                "schema_version": str(STORAGE_SCHEMA_VERSION),
                "scope_type": scope["scope_type"],
                "scope_hash": _hash_identifier(scope["scope_id"]),
                "workflow_hash": _hash_identifier(scope["workflow_id"]),
                "run_hash": _hash_identifier(scope["run_id"]),
                "task_hash": task_hash,
                "sha256": digest_filename[:-5],
                "media_type": RESULT_MEDIA_TYPE,
            }
            _require_fields(properties.metadata, expected)
            blob = self.blob_client.get_blob_client(container=self.blob_container_name, blob=name)
            try:
                blob.delete_blob(
                    delete_snapshots="include",
                    etag=properties.etag, match_condition=MatchConditions.IfNotModified,
                )
            except ResourceNotFoundError:
                continue

    def delete_run_results(self, workflow, run_id):
        """Stream all private records and run-prefix blobs, including interrupted writes.

        No history limit is applied. Missing objects during deletion are already
        cleaned up; other SDK errors propagate so callers retain the run history.
        Source Analyze artifacts and published documents are never followed.
        """
        scope = _scope(workflow, run_id)
        if self.blob_client is not None:
            self._delete_run_blobs(scope)
        records = self.container.query_items(
            query=(
                "SELECT c.id, c.run_id, c.workflow_id, c.scope_type, c.scope_id, c.task_id, "
                "c.type, c.item_type, c.storage, c.schema_version, c.sha256, c.size_bytes, "
                "c.chunk_count, c.record_kind, c.chunk_index FROM c "
                "WHERE c.run_id = @run_id AND c.workflow_id = @workflow_id "
                "AND c.scope_type = @scope_type AND c.scope_id = @scope_id "
                "AND c.type = @record_type AND c.item_type = @record_type"
            ),
            parameters=[
                *({"name": f"@{key}", "value": value} for key, value in scope.items()),
                {"name": "@record_type", "value": RESULT_RECORD_TYPE},
            ],
            partition_key=run_id,
            max_item_count=100,
        )
        for record in records:
            _require_fields(record, {**scope, "type": RESULT_RECORD_TYPE, "item_type": RESULT_RECORD_TYPE})
            identity = {**scope, "task_id": _identifier(record.get("task_id"))}
            reference = _validate_reference({key: record.get(key) for key in REFERENCE_FIELDS})
            kind = record.get("record_kind")
            if kind == "manifest":
                expected_id = _record_id(identity, reference, "manifest")
            elif kind == "chunk" and reference["storage"] == "cosmos":
                index = record.get("chunk_index")
                if type(index) is not int or not 0 <= index < reference["chunk_count"]:
                    raise WorkflowResultIntegrityError("Stored workflow result chunk index is invalid.")
                expected_id = _record_id(identity, reference, "chunk", index)
            else:
                raise WorkflowResultIntegrityError("Stored workflow result record kind is invalid.")
            _require_fields(record, {"id": expected_id})
            if reference["storage"] == "blob" and self.blob_client is None:
                raise WorkflowResultStorageUnavailableError("Workflow result Blob storage is required for cleanup.")
            try:
                self.container.delete_item(item=expected_id, partition_key=run_id)
            except CosmosResourceNotFoundError:
                continue


def _configured_store(workflow, *, settings=None, for_write=False):
    """Load app clients only at an authorized call boundary, never at import time.

    Config initializes SDK clients and imports workflow stores elsewhere during
    startup. This documented local import keeps the persistence leaf testable
    without app startup or a workflow-store import cycle. An omitted write-settings
    mapping is read from the fixed app_settings document; only the quota is used.
    Reads/cleanup do not depend on current settings or a changed write quota.
    """
    import config

    is_group = _workflow_scope(workflow)["scope_type"] == "group"
    if for_write and settings is None:
        settings = config.cosmos_settings_container.read_item(
            item="app_settings", partition_key="app_settings",
        )
    return WorkflowResultStore(
        container=(
            config.cosmos_group_workflow_run_items_container if is_group
            else config.cosmos_personal_workflow_run_items_container
        ),
        blob_client=config.CLIENTS.get("storage_account_office_docs_client"),
        blob_container_name=config.storage_account_personal_chat_container_name,
        max_size_bytes=_quota_bytes(settings if settings is not None else {}),
    )


def save_workflow_task_result(workflow, run_id, task_id, result, *, settings=None):
    """Save a complete result and return a small, path-free storage reference."""
    return _configured_store(workflow, settings=settings, for_write=True).save(workflow, run_id, task_id, result)


def load_workflow_task_result(workflow, run_id, task_id, reference):
    """Load and verify an authorized workflow task's full result envelope."""
    return _configured_store(workflow).load(workflow, run_id, task_id, reference)


def read_workflow_task_result_page(workflow, run_id, task_id, reference, *, offset=0, limit=65536):
    """Read only the bounded serialized byte range of an authorized task result."""
    return _configured_store(workflow).read_page(workflow, run_id, task_id, reference, offset=offset, limit=limit)


def delete_workflow_run_results(workflow, run_id):
    """Clean up private task results before the caller removes authorized run history."""
    return _configured_store(workflow).delete_run_results(workflow, run_id)
