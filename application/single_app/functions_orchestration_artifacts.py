# functions_orchestration_artifacts.py
"""Private transport and strict generated-source dispatch for retained outputs.

The application owner registers an actor-scoped service factory at bootstrap.
This module never discovers clients, settings, credentials, or source paths.
The output row, not file-message metadata, authorizes visibility.
"""

import re
import uuid
from copy import deepcopy

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from content_screening.contracts import ScreeningError
from functions_generated_export_registry import GENERATED_FILE_EXPORT_REGISTRY
from functions_orchestration_output_store import (
    MAX_AUTOMATIC_ATTEMPTS,
    MAX_MANUAL_ATTEMPTS,
    OrchestrationOutputStore,
    OutputConflictError,
    OutputError,
    OutputStorageError,
    OutputUnavailableError,
    parse_time,
    safe_identity,
)
from functions_orchestration_result_contracts import ProducerIdentity, ResultContractError, canonical_digest


ORCHESTRATION_ARTIFACT_KIND = "orchestration_retained_output"
ORCHESTRATION_ARTIFACT_VERSION = 1
ORCHESTRATION_ARTIFACT_KEY_PREFIX = "orchestration-output:v1:"
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_OUTPUT_ID = re.compile(r"orender_[a-f0-9]{64}\Z")
_SOURCE_FIELDS = frozenset({
    "version", "kind", "producer", "output_id", "intent_id", "attempt_number",
    "source_digest", "spec_digest",
})
_service_factory = None


def _external_authority_failure(error, *, include_configuration):
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if any(
            kind.__module__ == "functions_orchestration_external_identity"
            for kind in type(current).__mro__
        ):
            # These types share a context-owning reader module. Resolve them only
            # for an already-raised identity-family exception, never at bootstrap.
            from functions_orchestration_external_identity import (
                ExternalIdentityCancelledError,
                ExternalIdentityServiceError,
            )

            if isinstance(current, ExternalIdentityCancelledError):
                return current, "output_cancelled", False
            if isinstance(current, ExternalIdentityServiceError):
                return current, current.code, current.retryable is True
        if include_configuration and any(
            kind.__module__ == "functions_orchestration_external_configuration"
            for kind in type(current).__mro__
        ):
            # Configuration metadata readers also depend on initialized owners.
            from functions_orchestration_external_configuration import (
                ExternalConfigurationCancelledError,
                ExternalConfigurationServiceError,
            )

            if isinstance(current, ExternalConfigurationCancelledError):
                return current, "output_cancelled", False
            if isinstance(current, ExternalConfigurationServiceError):
                return current, current.code, current.retryable is True
        current = current.__cause__
    return None


def external_identity_failure(error):
    """Preserve typed directory uncertainty, including an explicit wrapped cause."""
    return _external_authority_failure(error, include_configuration=False)


def external_authority_failure(error):
    """Preserve typed directory/configuration failures without eager owner imports."""
    return _external_authority_failure(error, include_configuration=True)


def output_storage_failure(error):
    """Recognize operational storage errors through explicit, known wrappers."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OutputStorageError):
            return current
        checkpoint_error = False
        if any(kind.__module__ == "functions_orchestration_checkpoints" for kind in type(current).__mro__):
            # Checkpoint contracts load schema/registry owners; resolve the actual
            # class only after a checkpoint-family error has already been raised.
            from functions_orchestration_checkpoints import CheckpointError

            checkpoint_error = isinstance(current, CheckpointError)
            if checkpoint_error and current.code == "checkpoint_storage_unavailable":
                return current
        if not checkpoint_error and not isinstance(current, (PermissionError, OutputError, ResultContractError)):
            return None
        current = current.__cause__
    return None


def _raise_typed_artifact_failure(error):
    authority = external_authority_failure(error)
    if authority is not None:
        raise authority[0]
    storage = output_storage_failure(error)
    if isinstance(storage, OutputStorageError):
        raise storage
    if storage is not None:
        raise OutputStorageError() from error


def orchestration_artifact_file_extensions(output_format):
    entry = next(
        (item for item in GENERATED_FILE_EXPORT_REGISTRY if item.format_id == output_format),
        None,
    )
    if entry is None:
        raise OutputError("output_format_invalid")
    return frozenset((entry.file_extension, *entry.aliases))


def configure_orchestration_artifact_service(factory):
    """Owner bootstrap hook; ``None`` deliberately restores fail-closed behavior."""
    if factory is not None and not callable(factory):
        raise OutputError("output_service_required")
    global _service_factory
    previous = _service_factory
    _service_factory = factory
    return previous


def is_orchestration_artifact_source(value):
    return type(value) is dict and value.get("kind") == ORCHESTRATION_ARTIFACT_KIND


def validate_orchestration_artifact_binding(value):
    if (
        type(value) is not dict or set(value) != _SOURCE_FIELDS
        or type(value["version"]) is not int or value["version"] != ORCHESTRATION_ARTIFACT_VERSION
        or value["kind"] != ORCHESTRATION_ARTIFACT_KIND
        or type(value["output_id"]) is not str or _OUTPUT_ID.fullmatch(value["output_id"]) is None
        or type(value["attempt_number"]) is not int
        or not 1 <= value["attempt_number"] <= MAX_AUTOMATIC_ATTEMPTS + MAX_MANUAL_ATTEMPTS
        or any(type(value[name]) is not str or _DIGEST.fullmatch(value[name]) is None for name in (
            "intent_id", "source_digest", "spec_digest",
        ))
    ):
        raise OutputUnavailableError("output_binding_invalid")
    try:
        producer = ProducerIdentity.from_dict(value["producer"])
        for field in ("user_id", "conversation_id", "run_id", "step_id"):
            safe_identity(getattr(producer, field))
    except ValueError as exc:
        raise OutputUnavailableError("output_binding_invalid") from exc
    if producer.capability_id != "render_file":
        raise OutputUnavailableError("output_binding_invalid")
    return deepcopy(value)


def binding_for_intent(record, intent):
    return validate_orchestration_artifact_binding({
        "version": ORCHESTRATION_ARTIFACT_VERSION, "kind": ORCHESTRATION_ARTIFACT_KIND,
        "producer": deepcopy(record["producer"]), "output_id": record["id"],
        "intent_id": intent["intent_id"], "attempt_number": intent["attempt_number"],
        "source_digest": record["identity"]["source_digest"],
        "spec_digest": record["identity"]["spec_digest"],
    })


def _artifact_address(record, intent_id, blob_container):
    key = f"{ORCHESTRATION_ARTIFACT_KEY_PREFIX}{record['id']}:{intent_id}"
    suffix = uuid.uuid5(
        uuid.NAMESPACE_URL, f"simplechat-generated-artifact:{record['conversation_id']}:{key}",
    ).hex
    message_id = f"{record['conversation_id']}_generated_file_{suffix}"
    return key, {
        "conversation_id": record["conversation_id"], "artifact_message_id": message_id,
        "file_name": record["file_name"], "blob_container": blob_container,
        "blob_path": (
            f"{record['user_id']}/{record['conversation_id']}/generated/"
            f"{message_id}/{record['file_name']}"
        ),
    }


def validate_orchestration_artifact_descriptor(record, descriptor, blob_container):
    identity_fields = {
        "attempt_number", "output_format", "profile", "media_type", "size_bytes",
        "content_sha256", "record_count", "character_count",
    }
    if (
        type(descriptor) is not dict
        or set(descriptor) != identity_fields | {"intent_id", "idempotency_key", "artifact"}
        or type(descriptor["attempt_number"]) is not int
        or not 1 <= descriptor["attempt_number"] <= record["attempt_count"]
        or descriptor["output_format"] != record["render_spec"]["output_format"]
        or descriptor["profile"] != record["render_spec"]["profile"]
        or type(descriptor["size_bytes"]) is not int
        or not 0 <= descriptor["size_bytes"] <= record["render_spec"]["max_output_bytes"]
        or type(descriptor["content_sha256"]) is not str
        or _DIGEST.fullmatch(descriptor["content_sha256"]) is None
        or descriptor["record_count"] != (
            record["source_ref"]["item_count"] if record["source_ref"]["kind"] == "records-v1" else 0
        )
        or descriptor["character_count"] != record["source_ref"]["character_count"]
    ):
        raise OutputUnavailableError("output_intent_invalid")
    identity = {name: descriptor[name] for name in identity_fields}
    intent_id = canonical_digest({"output_id": record["id"], **identity})
    key, address = _artifact_address(record, intent_id, blob_container)
    if (
        descriptor["intent_id"] != intent_id or descriptor["idempotency_key"] != key
        or descriptor["artifact"] != address
    ):
        raise OutputUnavailableError("output_intent_invalid")
    return deepcopy(descriptor)


def _conversation_service(user_id, conversation_id):
    try:
        service = _service_factory(user_id, conversation_id)
        if (
            service is None or service.store.user_id != user_id
            or service.store.conversation_id != conversation_id
        ):
            raise OutputUnavailableError("output_service_unavailable")
    except (ScreeningError, OutputError, OutputUnavailableError, OutputStorageError, OutputConflictError) as exc:
        _raise_typed_artifact_failure(exc)
        raise
    except (AzureError, TimeoutError, ConnectionError) as exc:
        _raise_typed_artifact_failure(exc)
        raise OutputStorageError() from exc
    except (PermissionError, LookupError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
        _raise_typed_artifact_failure(exc)
        raise OutputUnavailableError("output_service_unavailable") from exc
    except OSError as exc:
        _raise_typed_artifact_failure(exc)
        raise
    return service


def _bound_service(user_id, value):
    binding = validate_orchestration_artifact_binding(value)
    producer = binding["producer"]
    if user_id != producer["user_id"] or _service_factory is None:
        raise OutputUnavailableError("output_access_denied")
    return _conversation_service(user_id, producer["conversation_id"]), binding


def load_orchestration_output_history(user_id, conversation_id, run_id):
    """Read current public facts through the registered, conversation-bound owner."""
    for value in (user_id, conversation_id, run_id):
        safe_identity(value)
    if _service_factory is None:
        raise OutputError("output_service_required")
    service = _conversation_service(user_id, conversation_id)
    return {
        "outputs": service.list_public_outputs(run_id),
        "artifacts": service.committed_artifacts(run_id),
    }


def load_orchestration_artifact_binding(
    user_id, value, *, require_ready=True, for_publication=False,
):
    service, binding = _bound_service(user_id, value)
    try:
        return service.authorize_binding(
            binding, require_ready=require_ready, for_publication=for_publication,
        )
    except (ScreeningError, OutputError, OutputUnavailableError, OutputStorageError, OutputConflictError) as exc:
        _raise_typed_artifact_failure(exc)
        raise
    except (AzureError, TimeoutError, ConnectionError) as exc:
        _raise_typed_artifact_failure(exc)
        raise OutputStorageError() from exc
    except (PermissionError, LookupError, ValueError, TypeError, RuntimeError) as exc:
        _raise_typed_artifact_failure(exc)
        raise OutputUnavailableError("output_source_unavailable") from exc
    except (AttributeError, OSError) as exc:
        _raise_typed_artifact_failure(exc)
        raise


def authorize_orchestration_output_artifact(user_id, artifact, *, for_publication=False):
    metadata = artifact.get("metadata") or {}
    context = load_orchestration_artifact_binding(
        user_id, metadata.get("generated_artifact_source"), for_publication=for_publication,
    )
    assert_artifact_matches(artifact, context["binding"], context["descriptor"])
    return context


def invalidate_orchestration_artifact(user_id, artifact):
    """Persist a deletion fence before the existing user-facing delete removes bytes."""
    service, binding = _bound_service(
        user_id, (artifact.get("metadata") or {}).get("generated_artifact_source"),
    )
    return service.invalidate_artifact(binding, artifact)


def authorize_orchestration_artifact_cleanup(user_id, value):
    service, binding = _bound_service(user_id, value)
    return service.authorize_cleanup(binding)


def assert_artifact_matches(artifact, binding, descriptor):
    address = descriptor["artifact"]
    metadata = artifact.get("metadata") or {}
    if (
        artifact.get("id") != address["artifact_message_id"] or artifact.get("role") != "file"
        or artifact.get("filename") != address["file_name"]
        or artifact.get("file_content_source") != "blob"
        or any(artifact.get(name) != address[name] for name in (
            "conversation_id", "blob_container", "blob_path",
        ))
        or metadata.get("is_generated_chat_artifact") is not True
        or metadata.get("generated_artifact_source_required") is not True
        or metadata.get("generated_artifact_source") != binding
        or metadata.get("generated_artifact_size_bytes") != descriptor["size_bytes"]
        or metadata.get("generated_artifact_content_sha256") != descriptor["content_sha256"]
        or metadata.get("generated_artifact_output_format") != descriptor["output_format"]
        or metadata.get("generated_artifact_idempotency_key") != descriptor["idempotency_key"]
        or any(metadata.get(name) for name in (
            "analysis_result_required", "analysis_producer", "analysis_result_contexts",
            "generated_artifact_run_id", "generated_artifact_set_id", "generated_artifact_member_id",
        ))
    ):
        raise OutputUnavailableError("output_artifact_mismatch")


def committed_artifact_card(record):
    if record.get("state") != "completed" or not record.get("committed_intent"):
        raise OutputUnavailableError("output_not_committed")
    descriptor = record["committed_intent"]
    return {
        "capability": "render_file", "source_kind": ORCHESTRATION_ARTIFACT_KIND,
        "output_id": record["id"],
        "artifact_message_id": descriptor["artifact"]["artifact_message_id"],
        "conversation_id": record["conversation_id"], "storage_scope": "chat",
        "file_name": record["file_name"], "output_format": descriptor["output_format"],
        "profile": record["render_spec"]["profile"], "summary": "The requested file is ready.",
        "row_count": descriptor["record_count"], "character_count": descriptor["character_count"],
    }


class OrchestrationOutputCleanupService:
    """Deletion-only access to retained intents, never a source or download grant.

    The store's conversation reader must return the real record (including
    deletion markers) or raise CosmosResourceNotFoundError for a real 404.
    Missing conversations also require the retained run's deleted lifecycle
    guard through store.read_run_tombstone. Run/output/guard rows must survive.
    Initialized message/blob handles are supplied by the owning composition root.
    """

    def __init__(self, store, message_container, blob_service_client, *, blob_container):
        if (
            type(store) is not OrchestrationOutputStore
            or not all(callable(getattr(message_container, name, None)) for name in ("read_item", "delete_item"))
            or not callable(getattr(blob_service_client, "get_blob_client", None))
        ):
            raise OutputError("output_cleanup_service_required")
        self.store = store
        self.message_container = message_container
        self.blob_service_client = blob_service_client
        self.blob_container = safe_identity(blob_container)

    def _check(self, output_id, intent_id):
        record, descriptor = self.store.check_cleanup(output_id, intent_id)
        return record, validate_orchestration_artifact_descriptor(record, descriptor, self.blob_container)

    @staticmethod
    def _result(record, processed):
        return {
            "output_id": record["id"], "state": record["state"],
            "cleanup_status": "deferred" if record.get("cleanup_pending") else "complete",
            "cleanup_pending": bool(record.get("cleanup_pending")), "processed_intents": processed,
        }

    def cleanup(self, output_id):
        record = self.store.prepare_cleanup(output_id)
        if not record.get("cleanup_pending") or parse_time(record["cleanup_after"]) > self.store.clock():
            return self._result(record, 0)
        processed = 0
        try:
            for intent in record["intents"]:
                if intent == record.get("committed_intent") and not record.get("deleted_at"):
                    continue
                current, descriptor = self._check(output_id, intent["intent_id"])
                address = descriptor["artifact"]
                try:
                    message = self.message_container.read_item(
                        item=address["artifact_message_id"], partition_key=current["conversation_id"],
                    )
                except CosmosResourceNotFoundError:
                    message = None
                if message is not None:
                    assert_artifact_matches(message, binding_for_intent(current, descriptor), descriptor)
                self._check(output_id, intent["intent_id"])
                try:
                    self.blob_service_client.get_blob_client(
                        container=address["blob_container"], blob=address["blob_path"],
                    ).delete_blob(delete_snapshots="include")
                except ResourceNotFoundError:
                    pass
                if message is not None:
                    self._check(output_id, intent["intent_id"])
                    try:
                        self.message_container.delete_item(
                            item=address["artifact_message_id"], partition_key=current["conversation_id"],
                            etag=message["_etag"], match_condition=MatchConditions.IfNotModified,
                        )
                    except CosmosResourceNotFoundError:
                        pass
                processed += 1
        except AzureError as exc:
            if getattr(exc, "status_code", None) in (409, 412):
                raise OutputConflictError() from exc
            raise OutputStorageError() from exc
        except (TimeoutError, ConnectionError) as exc:
            raise OutputStorageError() from exc
        return self._result(self.store.finish_cleanup(
            output_id, generation=record.get("cleanup_generation", 0),
        ), processed)

    def tombstone(self, output_id):
        """Explicitly withdraw only this output under existing owner-deletion proof."""
        record = self.store.prepare_cleanup(output_id, tombstone=True)
        return self._result(record, 0)

    def enroll_run_cleanup(self, run_id):
        """Schedule the parent's exact durable deletion intent without transport I/O."""
        return self.store.enroll_run_cleanup(run_id)


class OrchestrationArtifactTransport:
    """Adapter over the existing private uploader/open/delete operations.

    ``read_message(conversation_id, message_id)`` is a point read, never a search
    for a filename. ``open_stream(artifact, check=...)`` verifies the full blob.
    ``delete`` is the guarded staged-output cleanup helper, not a general delete.
    """

    def __init__(self, *, upload, read_message, open_stream, delete, blob_container):
        if not all(callable(value) for value in (upload, read_message, open_stream, delete)):
            raise OutputError("output_transport_required")
        self.upload = upload
        self.read_message = read_message
        self.open_stream = open_stream
        self.delete = delete
        self.blob_container = safe_identity(blob_container)

    def descriptor(self, record, rendered):
        descriptor = {
            "attempt_number": record["attempt_count"],
            "output_format": rendered.output_format, "profile": rendered.profile,
            "media_type": rendered.media_type, "size_bytes": rendered.size_bytes,
            "content_sha256": rendered.content_sha256, "record_count": rendered.record_count,
            "character_count": rendered.character_count,
        }
        intent_id = canonical_digest({"output_id": record["id"], **descriptor})
        key, address = _artifact_address(record, intent_id, self.blob_container)
        descriptor.update({
            "intent_id": intent_id, "idempotency_key": key,
            "artifact": address,
        })
        return self.validate_descriptor(record, descriptor)

    def validate_descriptor(self, record, descriptor):
        return validate_orchestration_artifact_descriptor(record, descriptor, self.blob_container)

    def _synthetic_message(self, record, descriptor):
        address = descriptor["artifact"]
        return {
            "id": address["artifact_message_id"], "conversation_id": record["conversation_id"],
            "role": "file", "filename": record["file_name"], "file_content_source": "blob",
            "blob_container": address["blob_container"], "blob_path": address["blob_path"],
            "metadata": {
                "is_generated_chat_artifact": True,
                "generated_artifact_source_required": True,
                "generated_artifact_source": binding_for_intent(record, descriptor),
                "generated_artifact_size_bytes": descriptor["size_bytes"],
                "generated_artifact_content_sha256": descriptor["content_sha256"],
                "generated_artifact_output_format": descriptor["output_format"],
                "generated_artifact_idempotency_key": descriptor["idempotency_key"],
            },
        }

    def stage(self, record, stream, *, check):
        descriptor = self.validate_descriptor(record, record["intent"])
        check()
        response = self.upload(
            record["user_id"], record["conversation_id"], record["file_name"],
            stream, descriptor["size_bytes"], capability="render_file",
            output_format=descriptor["output_format"], summary="The requested file is ready.",
            artifact_idempotency_key=descriptor["idempotency_key"],
            generated_artifact_source=binding_for_intent(record, descriptor),
            execution_check=check,
        )
        if (
            type(response) is not dict
            or response.get("conversation_id") != record["conversation_id"]
            or (response.get("message") or {}).get("id") != descriptor["artifact"]["artifact_message_id"]
        ):
            raise OutputError("output_transport_invalid")
        check()

    def message(self, record, *, committed=False):
        descriptor = record["committed_intent"] if committed else record["intent"]
        descriptor = self.validate_descriptor(record, descriptor)
        try:
            message = self.read_message(
                record["conversation_id"], descriptor["artifact"]["artifact_message_id"],
            )
        except (ResourceNotFoundError, CosmosResourceNotFoundError):
            return None
        if message is None:
            return None
        assert_artifact_matches(message, binding_for_intent(record, descriptor), descriptor)
        return message

    def reconcile(self, record, *, check, restore_message=False, committed=False, stage=None):
        """Verify durable bytes first; a blob-only upload can repair its own message."""
        descriptor = record["committed_intent"] if committed else record["intent"]
        if not descriptor:
            return False
        check()
        message = self.message(record, committed=committed)
        candidate = message or self._synthetic_message(record, descriptor)
        try:
            with self.open_stream(candidate, check=check) as stream:
                if message is None:
                    if not restore_message or committed:
                        return False
                    (self.stage if stage is None else stage)(record, stream, check=check)
                    message = self.message(record)
                    if message is None:
                        raise OutputError("output_artifact_missing")
        except (ResourceNotFoundError, CosmosResourceNotFoundError) as exc:
            if message is not None or committed:
                raise OutputUnavailableError("output_artifact_missing") from exc
            return False
        except OutputUnavailableError as exc:
            if exc.code == "output_artifact_missing" and message is None and not committed:
                return False
            raise
        check()
        return True

    def cleanup(self, record):
        for descriptor in record["intents"]:
            if descriptor == record.get("committed_intent") and not record.get("deleted_at"):
                continue
            descriptor = self.validate_descriptor(record, descriptor)
            self.delete(
                record["user_id"], record["conversation_id"],
                descriptor["artifact"]["artifact_message_id"],
                generated_artifact_source=binding_for_intent(record, descriptor),
            )
