# conversation_memory_storage.py
"""Bounded, conditional blob I/O below the application bootstrap boundary."""

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from azure.core import MatchConditions
from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)


class ConversationMemoryError(RuntimeError):
    """A safe, explicit conversation-memory failure."""


class MemoryUnavailableError(ConversationMemoryError):
    """Durable storage is unavailable."""


class MemoryConflictError(ConversationMemoryError):
    """An ETag or worker generation no longer matches."""


class MemoryNotFoundError(ConversationMemoryError):
    """The requested memory object does not exist."""


class MemoryAuthorizationError(ConversationMemoryError):
    """The exact conversation, actor, or publication was not authorized."""


class MemoryStateError(ConversationMemoryError):
    """The requested transition is not valid in the current state."""


class MemoryIncompleteCaptureError(MemoryStateError):
    """A reserved write has no durable final record and requires an explicit retry decision."""


class MemoryIntegrityError(ConversationMemoryError):
    """Stored evidence or its manifest failed validation."""


class MemoryLimitError(ConversationMemoryError):
    """An explicit bounded-I/O limit was exceeded."""


class MemoryCleanupError(ConversationMemoryError):
    """Cleanup did not complete and must be retried."""


@dataclass(frozen=True)
class BlobRecord:
    data: bytes
    etag: str


class MemoryBlobTransport(Protocol):
    def read(self, container: str, name: str, *, max_bytes: int) -> BlobRecord:
        ...

    def put(self, container: str, name: str, data: bytes, *, etag: str | None = None) -> str:
        """Create an immutable object, or replace exactly the supplied ETag."""
        ...

    def delete(self, container: str, name: str, *, etag: str) -> None:
        ...


class AzureMemoryBlobTransport:
    """Use an existing chat BlobServiceClient; never construct clients/settings."""

    def __init__(self, blob_service_client):
        if blob_service_client is None:
            raise MemoryUnavailableError("Conversation working memory requires chat blob storage.")
        self.client = blob_service_client

    def read(self, container: str, name: str, *, max_bytes: int) -> BlobRecord:
        blob = self.client.get_blob_client(container=container, blob=name)
        try:
            properties = blob.get_blob_properties()
            size = properties.size
            if size < 0 or size > max_bytes:
                raise MemoryLimitError("A conversation memory object exceeds the read limit.")
            data = bytearray()
            if size:
                download = blob.download_blob(
                    offset=0,
                    length=size,
                    etag=properties.etag,
                    match_condition=MatchConditions.IfNotModified,
                    max_concurrency=1,
                )
                for chunk in download.chunks():
                    if len(data) + len(chunk) > max_bytes:
                        raise MemoryLimitError("A conversation memory download exceeds the read limit.")
                    data.extend(chunk)
            if len(data) != size:
                raise MemoryIntegrityError("Conversation memory download was incomplete.")
            return BlobRecord(bytes(data), properties.etag)
        except ResourceNotFoundError as exc:
            if getattr(exc, "error_code", None) == "ContainerNotFound":
                raise MemoryUnavailableError("The configured chat-storage container is unavailable.") from exc
            raise MemoryNotFoundError("Conversation memory object was not found.") from exc
        except ResourceModifiedError as exc:
            raise MemoryConflictError("Conversation memory changed during the read.") from exc
        except (HttpResponseError, ServiceRequestError, ServiceResponseError) as exc:
            raise MemoryUnavailableError("Unable to read conversation working memory.") from exc

    def put(self, container: str, name: str, data: bytes, *, etag: str | None = None) -> str:
        blob = self.client.get_blob_client(container=container, blob=name)
        conditions = {}
        if etag is not None:
            conditions = {"etag": etag, "match_condition": MatchConditions.IfNotModified}
        try:
            result = blob.upload_blob(
                BytesIO(data),
                length=len(data),
                overwrite=etag is not None,
                max_concurrency=1,
                metadata={"conversation_memory": "v1"},
                **conditions,
            )
            return result["etag"]
        except (ResourceExistsError, ResourceModifiedError) as exc:
            raise MemoryConflictError("Conversation memory changed before the write.") from exc
        except ResourceNotFoundError as exc:
            if getattr(exc, "error_code", None) == "ContainerNotFound":
                raise MemoryUnavailableError("The configured chat-storage container is unavailable.") from exc
            if etag is not None:
                raise MemoryConflictError("Conversation memory was removed before the write.") from exc
            raise MemoryUnavailableError("The conversation memory container is unavailable.") from exc
        except (HttpResponseError, ServiceRequestError, ServiceResponseError) as exc:
            raise MemoryUnavailableError("Unable to persist conversation working memory.") from exc

    def delete(self, container: str, name: str, *, etag: str) -> None:
        blob = self.client.get_blob_client(container=container, blob=name)
        try:
            blob.delete_blob(
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
                delete_snapshots="include",
            )
        except ResourceNotFoundError as exc:
            if getattr(exc, "error_code", None) == "ContainerNotFound":
                raise MemoryUnavailableError("The configured chat-storage container is unavailable.") from exc
            raise MemoryNotFoundError("Conversation memory object was already removed.") from exc
        except ResourceModifiedError as exc:
            raise MemoryConflictError("Conversation memory changed before deletion.") from exc
        except (HttpResponseError, ServiceRequestError, ServiceResponseError) as exc:
            raise MemoryUnavailableError("Unable to delete conversation working memory.") from exc
