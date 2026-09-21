# functions_workflow_result_store.py
"""
Private, immutable persistence for workflow, chat, and orchestration results.
Version: 0.261.107
Implemented in: 0.261.106

Callers must authorize the current workflow/chat/orchestration context and
contributing sources before using this module. Storage additionally binds every
object to its personal user/group, workflow, run, and task; its original chat owner,
conversation, and real assistant message; or its original owner, conversation,
real orchestration run, and step. It does not interpret the result contract or
enforce source ACLs. Registered Analyze work units additionally use a bounded
conditional-write lifecycle row in that same run-items partition. Tombstones
fence chunks, manifests, claims, and subsequent final-result writes; caller-owned
execution leases and current authorization remain mandatory. No general lease
or scheduling mechanism is introduced for legacy workflow results.

Configured Blob storage is the write backend. Without an optional Blob client,
payloads use bounded chunks in the existing workflow_run_items container. A Blob
failure never switches backends. Both backends keep a small completion manifest;
workflow records retain type and item_type 'workflow_result_chunk'; chat records
use 'chat_analysis_result_chunk' in the existing personal run-items container,
with the real assistant message ID as run_id. Orchestration records use
'orchestration_analysis_result_chunk' there with their real run_id and step_id.
None of these payloads enter the message feed or orchestration UI step list.

Generic orchestration results reuse that same private run/step namespace and
mandatory lifecycle fence. Digest-keyed commits resolve their transport references
server-side; they do not claim the strict analyze-final-v1 result contract.

References contain only storage, schema_version (the storage format, not the
envelope contract), sha256, size_bytes, and chunk_count. Paths are reconstructed
from hashed identities. JSON is canonical ASCII, so page offsets count serialized
bytes and page content may split a JSON token or Unicode escape. A partial page
does not claim to verify the full-result digest. No local persistence is used.
"""

import hashlib
import json
import re
import uuid
from collections.abc import Mapping

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from azure.storage.blob import ContentSettings

from functions_workflow_runtime_store import WorkflowRuntimeConflict
from functions_workflow_identity import workflow_execution_id, workflow_node_identity

STORAGE_SCHEMA_VERSION = 1
RESULT_RECORD_TYPE = "workflow_result_chunk"
CHAT_RESULT_RECORD_TYPE = "chat_analysis_result_chunk"
ORCHESTRATION_RESULT_RECORD_TYPE = "orchestration_analysis_result_chunk"
ANALYSIS_CONTROL_RECORD_TYPE = "analysis_work_unit_checkpoint"
ORCHESTRATION_RESULT_COMMIT_KEY = "orchestration-task-result-v1"
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


class AnalysisWorkUnitConflictError(RuntimeError):
    """An Analyze attempt changed, was superseded, or lost a conditional write."""

    def __init__(self, code="analysis_work_ownership_lost"):
        self.code = code
        super().__init__("Saved analysis progress is unavailable for this attempt. Retry the current request.")


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


def _identity(workflow, run_id, task_id, *, execution_id=None, attempt=None, node_id=None, iteration_path=None):
    if any(value is not None for value in (execution_id, attempt, node_id, iteration_path)):
        identity = workflow_node_identity(
            workflow, run_id, node_id, execution_id, attempt, task_id=task_id, iteration_path=iteration_path,
        )
        # Compact transport bindings remain hashable; the manifest retains the verified path.
        return {**_scope(workflow, run_id), **{key: value for key, value in identity.items() if key != "iteration_path"}}
    return {**_scope(workflow, run_id), "task_id": _identifier(task_id)}


def read_workflow_node_result_page(workflow, run_id, task_id, reference, *, node_id, execution_id, attempt,
                                   iteration_path=None, offset=0, limit=2000):
    return _configured_store(workflow).read_page(
        workflow, run_id, task_id, reference, node_id=node_id, execution_id=execution_id,
        attempt=attempt, iteration_path=[] if iteration_path is None else iteration_path, offset=offset, limit=limit,
    )


def _chat_scope(user_id, conversation_id, message_id=None):
    scope = {
        "scope_type": "chat",
        "scope_id": _identifier(conversation_id),
        "user_id": _identifier(user_id),
        "conversation_id": _identifier(conversation_id),
    }
    if message_id is not None:
        scope.update(run_id=_identifier(message_id), message_id=_identifier(message_id))
    return scope


def _chat_identity(user_id, conversation_id, message_id):
    return _chat_scope(user_id, conversation_id, _identifier(message_id))


def _orchestration_scope(user_id, conversation_id, run_id=None):
    scope = {
        "scope_type": "orchestration",
        "scope_id": _identifier(conversation_id),
        "user_id": _identifier(user_id),
        "conversation_id": _identifier(conversation_id),
    }
    if run_id is not None:
        scope["run_id"] = _identifier(run_id)
    return scope


def _orchestration_identity(user_id, conversation_id, run_id, step_id):
    return {
        **_orchestration_scope(user_id, conversation_id, _identifier(run_id)),
        "step_id": _identifier(step_id),
    }


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _hash_identifier(value):
    return _sha256(value.encode("utf-8"))


def _record_id(identity, reference, kind, index=None):
    token = _sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("ascii"))
    suffix = kind if index is None else f"{kind}:{index}"
    namespace = {
        "chat": "chat-analysis-result",
        "orchestration": "orchestration-analysis-result",
    }.get(identity["scope_type"], "workflow-result")
    return f"{namespace}:v{STORAGE_SCHEMA_VERSION}:{token}:{reference['storage']}:{reference['sha256']}:{suffix}"


def _record_type(scope):
    return {
        "chat": CHAT_RESULT_RECORD_TYPE,
        "orchestration": ORCHESTRATION_RESULT_RECORD_TYPE,
    }.get(scope["scope_type"], RESULT_RECORD_TYPE)


def _analysis_control_id(identity, kind, key=""):
    digest = _sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("ascii"))
    return f"analysis-work:v1:{digest}:{kind}:{_hash_identifier(key)}"


def _run_blob_prefix(scope):
    return (
        f"workflow-results/v{STORAGE_SCHEMA_VERSION}/{scope['scope_type']}/"
        f"{_hash_identifier(scope['scope_id'])}/{_hash_identifier(scope['workflow_id'])}/"
        f"{_hash_identifier(scope['run_id'])}/"
    )


def _chat_blob_prefix(scope):
    prefix = (
        f"chat-analysis-results/v{STORAGE_SCHEMA_VERSION}/chat/"
        f"{_hash_identifier(scope['user_id'])}/{_hash_identifier(scope['conversation_id'])}/"
    )
    if "message_id" in scope:
        prefix += f"{_hash_identifier(scope['message_id'])}/"
    return prefix


def _orchestration_blob_prefix(scope):
    prefix = (
        f"orchestration-analysis-results/v{STORAGE_SCHEMA_VERSION}/orchestration/"
        f"{_hash_identifier(scope['user_id'])}/{_hash_identifier(scope['conversation_id'])}/"
    )
    if "run_id" in scope:
        prefix += f"{_hash_identifier(scope['run_id'])}/"
    return prefix


def _blob_name(identity, reference):
    if identity["scope_type"] == "chat":
        return f"{_chat_blob_prefix(identity)}{reference['sha256']}.json"
    if identity["scope_type"] == "orchestration":
        return f"{_orchestration_blob_prefix(identity)}{_hash_identifier(identity['step_id'])}/{reference['sha256']}.json"
    key = f"{identity['execution_id']}:{identity['attempt']}" if identity.get("execution_id") else identity["task_id"]
    return f"{_run_blob_prefix(identity)}{_hash_identifier(key)}/{reference['sha256']}.json"


def _conversation_blob_scope_metadata(scope):
    return {
        "schema_version": str(STORAGE_SCHEMA_VERSION),
        "scope_type": scope["scope_type"],
        "scope_hash": _hash_identifier(scope["scope_id"]),
        "user_hash": _hash_identifier(scope["user_id"]),
        "conversation_hash": _hash_identifier(scope["conversation_id"]),
        "media_type": RESULT_MEDIA_TYPE,
    }


def _blob_metadata(identity, reference):
    if identity["scope_type"] == "chat":
        return {
            **_conversation_blob_scope_metadata(identity),
            "run_hash": _hash_identifier(identity["run_id"]),
            "message_hash": _hash_identifier(identity["message_id"]),
            "sha256": reference["sha256"],
            "size_bytes": str(reference["size_bytes"]),
        }
    if identity["scope_type"] == "orchestration":
        return {
            **_conversation_blob_scope_metadata(identity),
            "run_hash": _hash_identifier(identity["run_id"]),
            "step_hash": _hash_identifier(identity["step_id"]),
            "sha256": reference["sha256"],
            "size_bytes": str(reference["size_bytes"]),
        }
    return {
        "schema_version": str(STORAGE_SCHEMA_VERSION),
        "scope_type": identity["scope_type"],
        "scope_hash": _hash_identifier(identity["scope_id"]),
        "workflow_hash": _hash_identifier(identity["workflow_id"]),
        "run_hash": _hash_identifier(identity["run_id"]),
        **({"execution_hash": identity["execution_id"], "attempt": str(identity["attempt"]),
            "execution_storage_hash": _hash_identifier(f"{identity['execution_id']}:{identity['attempt']}"),
            "node_hash": _hash_identifier(identity["node_id"])} if identity.get("execution_id")
           else {"task_hash": _hash_identifier(identity["task_id"])}),
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


def _active_workflow_execution():
    # The runtime imports this storage leaf; resolve the request-local owner only
    # at an I/O boundary to avoid a module cycle and preserve ordinary chat use.
    from functions_workflow_execution import current_workflow_execution

    return current_workflow_execution()


def _workflow_execution_guard(identity, execution=None):
    execution = execution or _active_workflow_execution()
    if execution is None or "workflow_id" not in identity:
        return None
    if (
        execution.workflow["id"] != identity["workflow_id"] or execution.run_id != identity["run_id"]
        or any(identity.get(key) != value for key, value in _workflow_scope(execution.workflow).items())
    ):
        raise WorkflowResultIntegrityError("Workflow result write does not match the active execution.")
    execution.check()
    return execution


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
        self._workflow_execution = _active_workflow_execution()
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
            "type": _record_type(identity),
            "item_type": _record_type(identity),
            "record_kind": "manifest",
            "chunk_size_bytes": chunk_size_bytes,
            "media_type": RESULT_MEDIA_TYPE,
        }

    def _create_immutable_record(self, record, *, analysis_identity=None, guard_token=None):
        execution = _workflow_execution_guard(record, self._workflow_execution)
        if analysis_identity is not None:
            return self._write_analysis_record(
                analysis_identity, record, token=guard_token, immutable=True,
            )
        if execution is not None:
            return execution.store.write_record(execution.lease.token, record, immutable=True)
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

    def save(self, workflow, run_id, task_id, result, **selectors):
        """Persist an envelope without overwriting another immutable result."""
        return self._save(_identity(workflow, run_id, task_id, **selectors), result)

    def save_chat(
        self, user_id, conversation_id, message_id, result, *, guard_token=None, require_analysis_guard=False,
    ):
        """Save under an authorized original owner, conversation, and assistant message."""
        return self._save(
            _chat_identity(user_id, conversation_id, message_id), result,
            guard_token=guard_token, require_analysis_guard=require_analysis_guard,
        )

    def save_orchestration(
        self, user_id, conversation_id, run_id, step_id, result, *,
        guard_token=None, require_analysis_guard=False,
    ):
        """Save under a real authorized orchestration run/step before a final message."""
        return self._save(
            _orchestration_identity(user_id, conversation_id, run_id, step_id), result,
            guard_token=guard_token, require_analysis_guard=require_analysis_guard,
        )

    def prepare_orchestration_result(self, user_id, conversation_id, run_id, step_id, *, guard_token):
        """Register an authorized producer using the existing execution/deletion fence."""
        return self.prepare_analysis_attempt(
            _orchestration_identity(user_id, conversation_id, run_id, step_id), token=guard_token,
        )

    def commit_orchestration_result(
        self, user_id, conversation_id, run_id, step_id, reference, *, guard_token,
    ):
        """Commit a private digest-addressed manifest pointer, never a downloadable file."""
        identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
        reference, manifest = self._read_manifest(identity, reference)
        if manifest.get("analysis_fenced") is not True:
            raise WorkflowResultIntegrityError("An orchestration result requires its lifecycle fence.")
        key = f"{ORCHESTRATION_RESULT_COMMIT_KEY}:{reference['sha256']}"
        row = {
            **identity, "id": _analysis_control_id(identity, "final", key),
            "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
            "record_kind": "final", "key": key, "reference": reference,
        }
        self._write_analysis_record(identity, row, token=guard_token, immutable=True)

    def load_committed_orchestration_result(self, user_id, conversation_id, run_id, step_id, manifest_sha256):
        """Resolve storage only from a producer-bound immutable server commit."""
        if not isinstance(manifest_sha256, str) or not _DIGEST_PATTERN.fullmatch(manifest_sha256):
            raise WorkflowResultIntegrityError("The orchestration result digest is invalid.")
        identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
        key = f"{ORCHESTRATION_RESULT_COMMIT_KEY}:{manifest_sha256}"
        row = self.read_analysis_checkpoint(identity, "final", key)
        if row is None:
            raise WorkflowResultIntegrityError("The orchestration result has not been committed.")
        reference = _validate_reference(row.get("reference"))
        if reference["sha256"] != manifest_sha256:
            raise WorkflowResultIntegrityError("The orchestration result commit does not match.")
        return self._load(identity, reference)

    def _save(self, identity, result, *, guard_token=None, require_analysis_guard=False):
        """Persist using a validated result binding, with identical I/O."""
        payload = self._serialize(result)
        execution = _workflow_execution_guard(identity, self._workflow_execution)
        guard = self._analysis_guard(
            identity, required=require_analysis_guard, writable=True, token=guard_token,
        )
        fenced_identity = identity if guard is not None else None
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
        if guard is not None:
            manifest["analysis_fenced"] = True
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
                }, analysis_identity=fenced_identity, guard_token=guard_token)
        # Publishing the manifest last makes an interrupted write unreadable.
        try:
            self._create_immutable_record(
                manifest, analysis_identity=fenced_identity, guard_token=guard_token,
            )
        except (AnalysisWorkUnitConflictError, WorkflowRuntimeConflict):
            if storage == "blob":
                current = self._analysis_guard(identity, required=guard is not None)
                runtime_deleted = execution is not None and execution.store.read(allow_deleted=True).get("deleted")
                if (current or {}).get("deleted") or runtime_deleted:
                    try:
                        blob, properties = self._checked_blob(identity, reference)
                        blob.delete_blob(
                            delete_snapshots="include", etag=properties.etag,
                            match_condition=MatchConditions.IfNotModified,
                        )
                    except ResourceNotFoundError:
                        pass
            raise
        return dict(reference)

    def _read_manifest(self, identity, reference):
        reference = _validate_reference(reference)
        manifest = self.container.read_item(
            item=_record_id(identity, reference, "manifest"), partition_key=identity["run_id"],
        )
        if manifest.get("analysis_fenced"):
            guard = self._analysis_guard(identity, required=True)
            if guard.get("deleted"):
                raise AnalysisWorkUnitConflictError("analysis_work_deleted")
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

    def _analysis_guard(self, identity, *, required=False, writable=False, token=None):
        item_id = _analysis_control_id(identity, "lifecycle")
        try:
            guard = self.container.read_item(item=item_id, partition_key=identity["run_id"])
        except CosmosResourceNotFoundError:
            if required:
                raise AnalysisWorkUnitConflictError("analysis_work_missing") from None
            return None
        _require_fields(guard, {
            **identity, "id": item_id, "type": ANALYSIS_CONTROL_RECORD_TYPE,
            "item_type": ANALYSIS_CONTROL_RECORD_TYPE, "record_kind": "lifecycle",
        })
        if writable:
            if guard.get("deleted"):
                raise AnalysisWorkUnitConflictError("analysis_work_deleted")
            if guard.get("stopped"):
                code = {
                    "timed_out": "analysis_work_timeout", "disconnected": "analysis_work_disconnected",
                    "failed": "analysis_work_stopped",
                }.get(guard.get("stop_reason"), "analysis_work_cancelled")
                raise AnalysisWorkUnitConflictError(code)
            if guard.get("successor"):
                raise AnalysisWorkUnitConflictError("analysis_work_superseded")
            if not guard.get("token") or (token is not None and guard.get("token") != token):
                raise AnalysisWorkUnitConflictError()
        return guard

    def _analysis_control(self, identity, kind, key=""):
        item_id = _analysis_control_id(identity, kind, key)
        try:
            row = self.container.read_item(item=item_id, partition_key=identity["run_id"])
        except CosmosResourceNotFoundError:
            return None
        _require_fields(row, {
            **identity, "id": item_id, "type": ANALYSIS_CONTROL_RECORD_TYPE,
            "item_type": ANALYSIS_CONTROL_RECORD_TYPE, "record_kind": kind, "key": key,
        })
        return row

    def _write_analysis_record(self, identity, record, *, token, immutable=False, previous=None):
        """Fence a bounded control/payload write in the existing run-items partition."""
        for _ in range(8):
            guard = self._analysis_guard(identity, required=True, writable=True, token=token)
            replacement = {key: value for key, value in guard.items() if not key.startswith("_")}
            replacement["write_id"] = uuid.uuid4().hex
            if not guard.get("_etag"):
                raise WorkflowResultIntegrityError("Analysis lifecycle is missing its conditional-write version.")
            operations = [
                ("replace", (guard["id"], replacement), {"if_match_etag": guard["_etag"]}),
            ]
            if previous is None:
                operations.append(("create", (record,)))
            else:
                if not previous.get("_etag"):
                    raise WorkflowResultIntegrityError("Analysis claim is missing its conditional-write version.")
                operations.append(("replace", (record["id"], record), {"if_match_etag": previous["_etag"]}))
            execution = _workflow_execution_guard(identity, self._workflow_execution)
            if execution is not None:
                operations = execution.fence_batch(operations)
            try:
                self.container.execute_item_batch(
                    batch_operations=operations, partition_key=identity["run_id"],
                )
                return
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                if exc.status_code == 412:
                    if previous is None:
                        continue
                    latest = self.container.read_item(item=record["id"], partition_key=identity["run_id"])
                    if latest.get("_etag") == previous.get("_etag"):
                        continue
                if immutable and exc.status_code == 409:
                    saved = self.container.read_item(item=record["id"], partition_key=identity["run_id"])
                    _require_fields(saved, record)
                    self._analysis_guard(identity, required=True, writable=True, token=token)
                    _workflow_execution_guard(identity, self._workflow_execution)
                    return
                if exc.status_code in (409, 412):
                    raise AnalysisWorkUnitConflictError() from None
                raise
        raise AnalysisWorkUnitConflictError()

    def _write_analysis_lifecycle(self, record, *, previous=None):
        """Admit first-use guards and request registration behind the run fence."""
        execution = _workflow_execution_guard(record, self._workflow_execution)
        if execution is None:
            if previous is None:
                return self.container.create_item(body=record)
            return self.container.replace_item(
                item=record["id"], body=record, etag=previous["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        operation = (
            ("create", (record,)) if previous is None else
            ("replace", (record["id"], record), {"if_match_etag": previous["_etag"]})
        )
        for _ in range(8):
            try:
                return self.container.execute_item_batch(
                    batch_operations=execution.fence_batch([operation]), partition_key=record["run_id"],
                )
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                if exc.status_code == 409:
                    raise CosmosResourceExistsError(status_code=409) from exc
                if exc.status_code != 412:
                    raise
                execution.check()
                if previous is not None:
                    latest = self.container.read_item(item=record["id"], partition_key=record["run_id"])
                    if latest["_etag"] != previous["_etag"]:
                        raise cosmos_exceptions.CosmosAccessConditionFailedError(status_code=412) from exc
        raise AnalysisWorkUnitConflictError()

    def _link_analysis_parent(self, identity, resume_from, *, request_digest=None):
        """A trusted retry gets one successor; the previous actual attempt loses writes."""
        same_context = (
            ("scope_type", "scope_id", "user_id", "conversation_id") if identity["scope_type"] == "chat"
            else ("scope_type", "scope_id", "user_id", "conversation_id", "step_id")
            if identity["scope_type"] == "orchestration"
            else ("scope_type", "scope_id", "workflow_id", "task_id")
        )
        if (
            not isinstance(resume_from, Mapping) or resume_from == identity
            or any(resume_from.get(key) != identity.get(key) for key in same_context)
        ):
            raise AnalysisWorkUnitConflictError("analysis_resume_binding_invalid")
        for _ in range(8):
            parent = self._analysis_guard(resume_from, required=True)
            parent_digest = parent.get("request_digest")
            if parent.get("deleted") or (
                request_digest is not None and parent_digest is not None and parent_digest != request_digest
            ):
                raise AnalysisWorkUnitConflictError("analysis_resume_changed")
            if parent_digest is None and not parent.get("prepared"):
                raise AnalysisWorkUnitConflictError("analysis_resume_unregistered")
            successor = parent.get("successor")
            if successor is not None and successor != identity:
                raise AnalysisWorkUnitConflictError("analysis_retry_already_started")
            if successor == identity:
                return parent
            replacement = {key: value for key, value in parent.items() if not key.startswith("_")}
            replacement.update(successor=dict(identity), token=None)
            try:
                return self.container.replace_item(
                    item=parent["id"], body=replacement, etag=parent["_etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
            except cosmos_exceptions.CosmosAccessConditionFailedError:
                continue
        raise AnalysisWorkUnitConflictError()

    def prepare_analysis_attempt(self, identity, *, token, resume_from=None):
        """Register a real attempt before source work or byte-only result saving.

        This is an execution fence, not a lease. The existing runner supplies its
        server-owned token and authorizes any previous-attempt association.
        """
        token = _identifier(token)
        parent = self._link_analysis_parent(identity, resume_from) if resume_from is not None else {}
        row = {
            **identity, "id": _analysis_control_id(identity, "lifecycle"),
            "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
            "record_kind": "lifecycle", "token": token, "deleted": False, "prepared": True,
            "request_registered": False, "resume_from": resume_from,
            **{key: parent[key] for key in ("request_digest", "source_count", "source_snapshot_digest") if key in parent},
        }
        try:
            self._write_analysis_lifecycle(row)
        except CosmosResourceExistsError:
            guard = self._analysis_guard(identity, required=True, writable=True, token=token)
            _require_fields(guard, {"resume_from": resume_from})
        return {"binding": dict(identity)}

    def begin_analysis_attempt(self, identity, request, sources, *, token, resume_from=None):
        """Bind actual request/source snapshots without allocating another execution engine."""
        if not isinstance(request, dict) or not isinstance(sources, list) or not sources:
            raise ValueError("Analysis checkpoint request and source snapshots are required.")
        token = _identifier(token)
        request_digest = _sha256(self._serialize({"request": request, "sources": sources}))
        row = {
            **identity, "id": _analysis_control_id(identity, "lifecycle"),
            "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
            "record_kind": "lifecycle", "token": token, "deleted": False,
            "request_registered": True,
            "request_digest": request_digest, "source_count": len(sources),
            "source_snapshot_digest": _sha256(self._serialize({"sources": sources})),
            "resume_from": resume_from,
        }
        if len(self._serialize(row)) > MAX_COSMOS_CHUNK_BYTES:
            raise WorkflowResultTooLargeError("Analysis source checkpoint metadata exceeds its bounded size.")
        if resume_from is not None:
            self._link_analysis_parent(identity, resume_from, request_digest=request_digest)
        try:
            self._write_analysis_lifecycle(row)
        except CosmosResourceExistsError:
            for _ in range(8):
                guard = self._analysis_guard(identity, required=True, writable=True, token=token)
                if guard.get("prepared") and guard.get("request_registered") is False:
                    if guard.get("request_digest") not in (None, request_digest) or guard.get("resume_from") != resume_from:
                        raise AnalysisWorkUnitConflictError("analysis_resume_changed")
                    replacement = {key: value for key, value in guard.items() if not key.startswith("_")}
                    replacement.update(row)
                    try:
                        self._write_analysis_lifecycle(replacement, previous=guard)
                        break
                    except cosmos_exceptions.CosmosAccessConditionFailedError:
                        continue
                expected = dict(row)
                if "request_registered" not in guard:
                    expected.pop("request_registered")
                _require_fields(guard, expected)
                break
            else:
                raise AnalysisWorkUnitConflictError()
        return {"binding": dict(identity), "request_digest": request_digest}

    def _analysis_request_guard(self, identity, token):
        guard = self._analysis_guard(identity, required=True, writable=True, token=token)
        if guard.get("request_registered") is False or not isinstance(guard.get("request_digest"), str):
            raise AnalysisWorkUnitConflictError("analysis_request_not_registered")
        return guard

    def read_analysis_checkpoint(self, identity, kind, key=""):
        """Read a small pointer; full bytes still use the shared digest-checked I/O."""
        guard = self._analysis_guard(identity, required=True)
        if guard.get("deleted"):
            raise AnalysisWorkUnitConflictError("analysis_work_deleted")
        return self._analysis_control(identity, kind, key)

    def write_analysis_checkpoint(self, identity, kind, key, value, *, token):
        self._analysis_request_guard(identity, token)
        row = {
            **value, **identity, "id": _analysis_control_id(identity, kind, key),
            "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
            "record_kind": kind, "key": key,
        }
        if len(self._serialize(row)) > MAX_COSMOS_CHUNK_BYTES:
            raise WorkflowResultTooLargeError("Analysis checkpoint metadata exceeds its bounded size.")
        self._write_analysis_record(identity, row, token=token, immutable=True)
        return row

    def claim_analysis_unit(self, identity, unit_id, *, token):
        self._analysis_request_guard(identity, token)
        previous = self.read_analysis_checkpoint(identity, "unit", unit_id)
        if previous is not None and previous.get("status") == "completed":
            return previous
        if previous is not None and previous.get("status") == "running":
            raise AnalysisWorkUnitConflictError("analysis_unit_already_claimed")
        row = {
            **identity, "id": _analysis_control_id(identity, "unit", unit_id),
            "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
            "record_kind": "unit", "key": unit_id, "status": "running", "claim_token": uuid.uuid4().hex,
        }
        self._write_analysis_record(identity, row, token=token, previous=previous)
        return row

    def finish_analysis_unit(self, identity, claim, payload, *, token):
        """Only the current claim may publish an immutable completed unit pointer."""
        unit_id = claim["key"]
        current = self.read_analysis_checkpoint(identity, "unit", unit_id)
        if current is None or current.get("claim_token") != claim.get("claim_token"):
            raise AnalysisWorkUnitConflictError()
        if current.get("status") == "completed":
            self._analysis_guard(identity, required=True, writable=True, token=token)
            encoded = self._serialize(payload)
            reference = _validate_reference(current.get("reference"))
            _verify_payload(encoded, reference)
            self._load(identity, reference)
            return dict(reference)
        if current.get("status") != "running":
            raise AnalysisWorkUnitConflictError()
        reference = self._save(identity, payload, guard_token=token, require_analysis_guard=True)
        row = {key: value for key, value in current.items() if not key.startswith("_")}
        row.update(status="completed", reference=reference)
        self._write_analysis_record(identity, row, token=token, previous=current)
        return reference

    def fail_analysis_unit(self, identity, claim, *, token):
        current = self.read_analysis_checkpoint(identity, "unit", claim["key"])
        if current is None or current.get("claim_token") != claim.get("claim_token") or current.get("status") != "running":
            raise AnalysisWorkUnitConflictError()
        row = {key: value for key, value in current.items() if not key.startswith("_")}
        row["status"] = "failed"
        self._write_analysis_record(identity, row, token=token, previous=current)

    def fence_analysis_attempt(self, identity):
        """Retain a small tombstone, including when an initializer has not written yet."""
        for _ in range(8):
            guard = self._analysis_guard(identity)
            tombstone = {
                **identity, "id": _analysis_control_id(identity, "lifecycle"),
                "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
                "record_kind": "lifecycle", "deleted": True, "token": None,
            }
            try:
                if guard is None:
                    self.container.create_item(body=tombstone)
                elif guard.get("deleted"):
                    return
                else:
                    self.container.replace_item(
                        item=guard["id"], body=tombstone, etag=guard["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                return
            except (CosmosResourceExistsError, cosmos_exceptions.CosmosAccessConditionFailedError):
                continue
        raise AnalysisWorkUnitConflictError()

    def cancel_analysis_attempt(self, identity, *, token=None, reason="cancelled"):
        """Stop writes atomically while keeping completed work readable for a retry."""
        if reason not in {"cancelled", "timed_out", "disconnected", "failed"}:
            raise ValueError("Unsupported analysis stop reason.")
        for _ in range(8):
            guard = self._analysis_guard(identity)
            if guard is not None:
                if guard.get("deleted") or guard.get("stopped") or guard.get("successor"):
                    return
                if token is not None and guard.get("token") != token:
                    raise AnalysisWorkUnitConflictError()
                stopped = {key: value for key, value in guard.items() if not key.startswith("_")}
                stopped.update(token=None, stopped=True, stop_reason=reason)
            else:
                stopped = {
                    **identity, "id": _analysis_control_id(identity, "lifecycle"),
                    "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
                    "record_kind": "lifecycle", "prepared": True, "request_registered": False,
                    "deleted": False, "stopped": True, "stop_reason": reason,
                    "token": None, "resume_from": None,
                }
            try:
                if guard is None:
                    self.container.create_item(body=stopped)
                else:
                    self.container.replace_item(
                        item=guard["id"], body=stopped, etag=guard["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                return
            except (CosmosResourceExistsError, cosmos_exceptions.CosmosAccessConditionFailedError):
                continue
        raise AnalysisWorkUnitConflictError()

    def _analysis_scope_rows(self, scope):
        identity_fields = (
            "c.user_id, c.conversation_id, c.message_id" if scope["scope_type"] == "chat"
            else "c.user_id, c.conversation_id, c.step_id" if scope["scope_type"] == "orchestration"
            else "c.workflow_id, c.task_id, c.execution_id, c.node_id, c.attempt"
        )
        return self.container.query_items(
            query=(
                f"SELECT c.id, c.run_id, c.scope_type, c.scope_id, {identity_fields}, c.type, c.item_type, "
                "c.record_kind, c.key FROM c WHERE "
                + " AND ".join(f"c.{key} = @{key}" for key in scope)
                + " AND c.type = @record_type AND c.item_type = @record_type"
            ),
            parameters=[
                *({"name": f"@{key}", "value": value} for key, value in scope.items()),
                {"name": "@record_type", "value": ANALYSIS_CONTROL_RECORD_TYPE},
            ],
            max_item_count=100,
            **({"partition_key": scope["run_id"]} if "run_id" in scope else {"enable_cross_partition_query": True}),
        )

    def _analysis_row_identity(self, scope, row):
        _require_fields(row, {
            **scope, "type": ANALYSIS_CONTROL_RECORD_TYPE, "item_type": ANALYSIS_CONTROL_RECORD_TYPE,
        })
        if scope["scope_type"] == "chat":
            identity = _chat_identity(scope["user_id"], scope["conversation_id"], row.get("message_id"))
        elif scope["scope_type"] == "orchestration":
            identity = _orchestration_identity(
                scope["user_id"], scope["conversation_id"], row.get("run_id"), row.get("step_id"),
            )
        else:
            identity = {**scope, "task_id": _identifier(row.get("task_id"))}
            if row.get("execution_id"):
                identity.update(execution_id=row["execution_id"], node_id=row["node_id"], attempt=row["attempt"])
        _require_fields(row, identity)
        return identity

    def _fence_analysis_scope(self, scope):
        for row in self._analysis_scope_rows(scope):
            identity = self._analysis_row_identity(scope, row)
            if row.get("record_kind") == "lifecycle":
                _require_fields(row, {"id": _analysis_control_id(identity, "lifecycle")})
                self.fence_analysis_attempt(identity)

    def _delete_analysis_controls(self, scope):
        for row in self._analysis_scope_rows(scope):
            identity = self._analysis_row_identity(scope, row)
            kind = row.get("record_kind")
            if kind == "lifecycle":
                continue
            if kind not in {"source", "unit", "final"}:
                raise WorkflowResultIntegrityError("Stored analysis checkpoint kind is invalid.")
            key = row.get("key")
            if not isinstance(key, str):
                raise WorkflowResultIntegrityError("Stored analysis checkpoint key is invalid.")
            _require_fields(row, {"id": _analysis_control_id(identity, kind, key)})
            try:
                self.container.delete_item(item=row["id"], partition_key=identity["run_id"])
            except CosmosResourceNotFoundError:
                pass

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

    def load(self, workflow, run_id, task_id, reference, **selectors):
        """Read the full envelope, verifying metadata, reconstructed size, and SHA-256."""
        return self._load(_identity(workflow, run_id, task_id, **selectors), reference)

    def load_chat(self, user_id, conversation_id, message_id, reference):
        """Load and verify the complete result for an authorized chat binding."""
        return self._load(_chat_identity(user_id, conversation_id, message_id), reference)

    def load_orchestration(self, user_id, conversation_id, run_id, step_id, reference):
        """Load and verify the result of an authorized orchestration run/step."""
        return self._load(_orchestration_identity(user_id, conversation_id, run_id, step_id), reference)

    def _load(self, identity, reference):
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

    def read_page(self, workflow, run_id, task_id, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES, **selectors):
        """Read bounded ASCII JSON bytes; complete means EOF, not a complete envelope."""
        return self._read_page(_identity(workflow, run_id, task_id, **selectors), reference, offset=offset, limit=limit)

    def read_chat_page(self, user_id, conversation_id, message_id, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES):
        """Read bounded serialized bytes, not semantic records or model-ready content."""
        return self._read_page(
            _chat_identity(user_id, conversation_id, message_id), reference, offset=offset, limit=limit,
        )

    def read_orchestration_page(
        self, user_id, conversation_id, run_id, step_id, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES,
    ):
        """Read serialized byte transport for an authorized orchestration step."""
        return self._read_page(
            _orchestration_identity(user_id, conversation_id, run_id, step_id),
            reference, offset=offset, limit=limit,
        )

    def _read_page(self, identity, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES):
        if type(offset) is not int or offset < 0:
            raise ValueError("Workflow result page offset must be a nonnegative integer.")
        if type(limit) is not int or not 0 < limit <= MAX_PAGE_BYTES:
            raise ValueError(f"Workflow result page limit must be an integer from 1 to {MAX_PAGE_BYTES}.")
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

    def _delete_scoped_blobs(self, scope):
        is_chat = scope["scope_type"] == "chat"
        is_orchestration = scope["scope_type"] == "orchestration"
        if is_chat:
            prefix = _chat_blob_prefix(scope)
        elif is_orchestration:
            prefix = _orchestration_blob_prefix(scope)
        else:
            prefix = _run_blob_prefix(scope)
        container = self.blob_client.get_container_client(self.blob_container_name)
        for properties in container.list_blobs(name_starts_with=prefix, include=["metadata"]):
            name = properties.name
            suffix = name[len(prefix):] if isinstance(name, str) and name.startswith(prefix) else ""
            if is_orchestration and "run_id" not in scope:
                if not re.fullmatch(r"[0-9a-f]{64}/[0-9a-f]{64}/[0-9a-f]{64}\.json", suffix):
                    raise WorkflowResultIntegrityError("Unexpected object in the private result prefix.")
                run_hash, object_hash, digest_filename = suffix.split("/")
            elif is_chat and "message_id" in scope:
                if not re.fullmatch(r"[0-9a-f]{64}\.json", suffix):
                    raise WorkflowResultIntegrityError("Unexpected object in the private result prefix.")
                object_hash, digest_filename = _hash_identifier(scope["message_id"]), suffix
            else:
                if not re.fullmatch(r"[0-9a-f]{64}/[0-9a-f]{64}\.json", suffix):
                    raise WorkflowResultIntegrityError("Unexpected object in the private result prefix.")
                object_hash, digest_filename = suffix.split("/")
            if is_orchestration:
                expected = {
                    **_conversation_blob_scope_metadata(scope),
                    "run_hash": _hash_identifier(scope["run_id"]) if "run_id" in scope else run_hash,
                    "step_hash": object_hash,
                    "sha256": digest_filename[:-5],
                }
            elif is_chat:
                expected = {
                    **_conversation_blob_scope_metadata(scope),
                    "run_hash": object_hash,
                    "message_hash": object_hash,
                    "sha256": digest_filename[:-5],
                }
            else:
                expected = {
                    "schema_version": str(STORAGE_SCHEMA_VERSION),
                    "scope_type": scope["scope_type"],
                    "scope_hash": _hash_identifier(scope["scope_id"]),
                    "workflow_hash": _hash_identifier(scope["workflow_id"]),
                    "run_hash": _hash_identifier(scope["run_id"]),
                    "sha256": digest_filename[:-5],
                    "media_type": RESULT_MEDIA_TYPE,
                }
                metadata = properties.metadata or {}
                if metadata.get("execution_hash"):
                    execution_hash, attempt = metadata.get("execution_hash"), metadata.get("attempt")
                    if (
                        not isinstance(execution_hash, str) or not _DIGEST_PATTERN.fullmatch(execution_hash)
                        or not isinstance(attempt, str) or not re.fullmatch(r"[1-9][0-9]{0,11}", attempt)
                        or _hash_identifier(f"{execution_hash}:{attempt}") != object_hash
                    ):
                        raise WorkflowResultIntegrityError("The execution Blob identity is invalid.")
                    expected["execution_storage_hash"] = object_hash
                else:
                    expected["task_hash"] = object_hash
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
        self._fence_analysis_scope(scope)
        if self.blob_client is not None:
            self._delete_scoped_blobs(scope)
        records = self.container.query_items(
            query=(
                "SELECT c.id, c.run_id, c.workflow_id, c.scope_type, c.scope_id, c.task_id, c.node_id, c.execution_id, c.attempt, "
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
        self._delete_records(scope, records)
        self._delete_analysis_controls(scope)
        journal_rows = self.container.query_items(
            query=(
                "SELECT c.id, c.workflow_id, c.run_id, c.scope_type, c.scope_id FROM c "
                "WHERE c.run_id = @run_id AND c.workflow_id = @workflow_id AND c.scope_type = @scope_type "
                "AND c.scope_id = @scope_id AND c.type = @record_type AND c.item_type = @record_type"
            ),
            parameters=[*({"name": f"@{key}", "value": value} for key, value in scope.items()),
                        {"name": "@record_type", "value": "workflow_runtime_journal"}],
            partition_key=run_id, max_item_count=100,
        )
        for row in journal_rows:
            _require_fields(row, scope)
            try:
                self.container.delete_item(item=row["id"], partition_key=run_id)
            except CosmosResourceNotFoundError:
                pass

    def delete_chat_results(self, user_id, conversation_id, message_id=None):
        """Delete every private section/revision for a real message or conversation.

        Callers must fence execution first and remove message/conversation history
        only after cleanup succeeds. This does not follow published document links.
        """
        return self._delete_conversation_results(_chat_scope(user_id, conversation_id, message_id))

    def delete_orchestration_results(self, user_id, conversation_id, run_id=None):
        """Sweep all private step sections/revisions in a fenced run or conversation.

        Chat-message results and independently published documents are separate
        lifecycles. Remove run/checkpoint history only after cleanup succeeds.
        """
        return self._delete_conversation_results(_orchestration_scope(user_id, conversation_id, run_id))

    def _delete_conversation_results(self, scope):
        self._fence_analysis_scope(scope)
        if self.blob_client is not None:
            self._delete_scoped_blobs(scope)
        query_options = (
            {"partition_key": scope["run_id"]} if "run_id" in scope
            else {"enable_cross_partition_query": True}
        )
        item_identity_field = "message_id" if scope["scope_type"] == "chat" else "step_id"
        records = self.container.query_items(
            query=(
                "SELECT c.id, c.run_id, c.scope_type, c.scope_id, c.user_id, "
                f"c.conversation_id, c.{item_identity_field}, c.type, c.item_type, c.storage, "
                "c.schema_version, c.sha256, c.size_bytes, c.chunk_count, "
                "c.record_kind, c.chunk_index FROM c WHERE "
                + " AND ".join(f"c.{key} = @{key}" for key in scope)
                + " AND c.type = @record_type AND c.item_type = @record_type"
            ),
            parameters=[
                *({"name": f"@{key}", "value": value} for key, value in scope.items()),
                {"name": "@record_type", "value": _record_type(scope)},
            ],
            max_item_count=100,
            **query_options,
        )
        self._delete_records(scope, records)
        self._delete_analysis_controls(scope)

    def _delete_records(self, scope, records):
        record_type = _record_type(scope)
        for record in records:
            _require_fields(record, {**scope, "type": record_type, "item_type": record_type})
            if scope["scope_type"] == "chat":
                identity = _chat_identity(scope["user_id"], scope["conversation_id"], record.get("message_id"))
                _require_fields(record, identity)
            elif scope["scope_type"] == "orchestration":
                identity = _orchestration_identity(
                    scope["user_id"], scope["conversation_id"], record.get("run_id"), record.get("step_id"),
                )
                _require_fields(record, identity)
            else:
                if record.get("execution_id"):
                    identity = {
                        **scope, "execution_id": _identifier(record.get("execution_id")),
                        "node_id": _identifier(record.get("node_id")), "attempt": _positive_integer(record.get("attempt"), "Attempt"),
                        **({"task_id": _identifier(record["task_id"])} if record.get("task_id") else {}),
                    }
                else:
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
                self.container.delete_item(item=expected_id, partition_key=identity["run_id"])
            except CosmosResourceNotFoundError:
                continue


def _configured_result_store(binding, *, settings=None, for_write=False):
    """Load app clients only at an authorized call boundary, never at import time.

    Config initializes SDK clients and imports workflow stores elsewhere during
    startup. This documented local import keeps the persistence leaf testable
    without app startup or a workflow-store import cycle. An omitted write-settings
    mapping is read from the fixed app_settings document; only the quota is used.
    Reads/cleanup do not depend on current settings or a changed write quota.
    """
    import config

    is_group = binding["scope_type"] == "group"
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


def _configured_store(workflow, *, settings=None, for_write=False):
    return _configured_result_store(_workflow_scope(workflow), settings=settings, for_write=for_write)


def save_workflow_task_result(workflow, run_id, task_id, result, *, settings=None):
    """Save a complete result and return a small, path-free storage reference."""
    return _configured_store(workflow, settings=settings, for_write=True).save(workflow, run_id, task_id, result)


def load_workflow_task_result(workflow, run_id, task_id, reference):
    """Load and verify an authorized workflow task's full result envelope."""
    return _configured_store(workflow).load(workflow, run_id, task_id, reference)


def save_workflow_node_result(workflow, run_id, task_id, result, *, node_id, execution_id, attempt,
                              iteration_path=None, settings=None):
    return _configured_store(workflow, settings=settings, for_write=True).save(
        workflow, run_id, task_id, result, node_id=node_id, execution_id=execution_id,
        attempt=attempt, iteration_path=[] if iteration_path is None else iteration_path,
    )


def load_workflow_node_result(workflow, run_id, task_id, reference, *, node_id, execution_id, attempt,
                              iteration_path=None):
    return _configured_store(workflow).load(
        workflow, run_id, task_id, reference, node_id=node_id, execution_id=execution_id,
        attempt=attempt, iteration_path=[] if iteration_path is None else iteration_path,
    )


def save_workflow_runtime_result(workflow, run_id, result, *, settings=None):
    node_id = workflow["flow"]["id"]
    return save_workflow_node_result(
        workflow, run_id, None, result, settings=settings, node_id=node_id,
        execution_id=workflow_execution_id(workflow, run_id, node_id), attempt=1, iteration_path=[],
    )


def load_workflow_runtime_result(workflow, run_id, control, reference):
    """Load using a verified control's frozen identity, before its definition can be read."""
    if any(control.get(key) != value for key, value in _scope(workflow, run_id).items()):
        raise WorkflowResultIntegrityError("The runtime snapshot scope is invalid.")
    selectors = control.get("snapshot_identity") or {}
    if set(selectors) != {"node_id", "execution_id", "attempt", "iteration_path"} or selectors["iteration_path"] != []:
        raise WorkflowResultIntegrityError("The runtime snapshot identity is invalid.")
    identity = {**_scope(workflow, run_id), **{key: value for key, value in selectors.items() if key != "iteration_path"}}
    return _configured_store(workflow)._load(identity, reference)


def read_workflow_task_result_page(workflow, run_id, task_id, reference, *, offset=0, limit=65536):
    """Read only the bounded serialized byte range of an authorized task result."""
    return _configured_store(workflow).read_page(workflow, run_id, task_id, reference, offset=offset, limit=limit)


def delete_workflow_run_results(workflow, run_id):
    """Clean up private task results before the caller removes authorized run history."""
    return _configured_store(workflow).delete_run_results(workflow, run_id)


def save_chat_analysis_result(
    user_id, conversation_id, message_id, result, *, settings=None,
    guard_token=None, require_analysis_guard=False,
):
    """Save for an authorized original chat owner and real assistant message."""
    identity = _chat_identity(user_id, conversation_id, message_id)
    guard_options = (
        {"guard_token": guard_token, "require_analysis_guard": require_analysis_guard}
        if guard_token is not None or require_analysis_guard else {}
    )
    return _configured_result_store(identity, settings=settings, for_write=True)._save(identity, result, **guard_options)


def load_chat_analysis_result(user_id, conversation_id, message_id, reference):
    """Load and verify a result after the caller authorizes context and sources."""
    identity = _chat_identity(user_id, conversation_id, message_id)
    return _configured_result_store(identity)._load(identity, reference)


def read_chat_analysis_result_page(
    user_id, conversation_id, message_id, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES,
):
    """Read bounded serialized bytes; the caller supplies complete-record paging."""
    identity = _chat_identity(user_id, conversation_id, message_id)
    return _configured_result_store(identity)._read_page(identity, reference, offset=offset, limit=limit)


def delete_chat_analysis_results(user_id, conversation_id, message_id=None):
    """Sweep private results before removing authorized, execution-fenced history."""
    scope = _chat_scope(user_id, conversation_id, message_id)
    return _configured_result_store(scope)._delete_conversation_results(scope)


def fence_chat_analysis_results(user_id, conversation_id, message_id):
    """Fence a real assistant attempt before removing its running/saved message."""
    identity = _chat_identity(user_id, conversation_id, message_id)
    return _configured_result_store(identity).fence_analysis_attempt(identity)


def prepare_chat_analysis_attempt(user_id, conversation_id, message_id, *, attempt_token, resume_message_id=None):
    """Register a currently authorized real assistant before any Analyze result writes."""
    identity = _chat_identity(user_id, conversation_id, message_id)
    parent = _chat_identity(user_id, conversation_id, resume_message_id) if resume_message_id else None
    return _configured_result_store(identity).prepare_analysis_attempt(
        identity, token=attempt_token, resume_from=parent,
    )


def cancel_chat_analysis_results(user_id, conversation_id, message_id, *, attempt_token=None, reason="cancelled"):
    """An authorized Stop fences writes, not the completed data an explicit retry needs."""
    identity = _chat_identity(user_id, conversation_id, message_id)
    return _configured_result_store(identity).cancel_analysis_attempt(identity, token=attempt_token, reason=reason)


def save_orchestration_analysis_result(
    user_id, conversation_id, run_id, step_id, result, settings=None, *,
    guard_token=None, require_analysis_guard=False,
):
    """Save for an authorized real run/step without requiring a terminal message."""
    identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
    guard_options = (
        {"guard_token": guard_token, "require_analysis_guard": require_analysis_guard}
        if guard_token is not None or require_analysis_guard else {}
    )
    return _configured_result_store(identity, settings=settings, for_write=True)._save(identity, result, **guard_options)


def load_orchestration_analysis_result(user_id, conversation_id, run_id, step_id, reference):
    """Load after the caller authorizes the current run, step, context, and sources."""
    identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
    return _configured_result_store(identity)._load(identity, reference)


def read_orchestration_analysis_result_page(
    user_id, conversation_id, run_id, step_id, reference, *, offset=0, limit=DEFAULT_PAGE_BYTES,
):
    """Read serialized byte transport, not semantic records or model-ready data."""
    identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
    return _configured_result_store(identity)._read_page(identity, reference, offset=offset, limit=limit)


def delete_orchestration_analysis_results(user_id, conversation_id, run_id=None):
    """Sweep private orchestration results before removing execution-fenced history."""
    scope = _orchestration_scope(user_id, conversation_id, run_id)
    return _configured_result_store(scope)._delete_conversation_results(scope)


def fence_orchestration_analysis_result(user_id, conversation_id, run_id, step_id):
    """Fence a planned Analyze step, including an initializer not yet committed."""
    identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
    return _configured_result_store(identity).fence_analysis_attempt(identity)


def cancel_orchestration_analysis_result(
    user_id, conversation_id, run_id, step_id, *, attempt_token=None, reason="cancelled",
):
    """Stop one real Analyze step while preserving its immutable completed units."""
    identity = _orchestration_identity(user_id, conversation_id, run_id, step_id)
    return _configured_result_store(identity).cancel_analysis_attempt(identity, token=attempt_token, reason=reason)
