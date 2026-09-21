# functions_conversation_memory.py
"""Reusable conversation evidence and checkpoints, independent of config/settings.

All entry points require a server-resolved backing conversation and reauthorize
it through injected callbacks. Source text, output, and notes are untrusted data,
never instructions. Private staging is not a generic chat attachment.

Writes reserve deterministic object slots in an ETag-protected manifest before
uploading. Only a subsequent manifest commit makes those objects readable.
Deletion covers reserved slots as well as commits, and leaves empty fencing
objects so a delayed create-only upload cannot resurrect erased evidence.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import re
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4, uuid5

from conversation_memory_storage import (
    AzureMemoryBlobTransport,
    ConversationMemoryError,
    MemoryAuthorizationError,
    MemoryBlobTransport,
    MemoryCleanupError,
    MemoryConflictError,
    MemoryIncompleteCaptureError,
    MemoryIntegrityError,
    MemoryLimitError,
    MemoryNotFoundError,
    MemoryStateError,
    MemoryUnavailableError,
)


MEMORY_SCHEMA_VERSION = 1
MEMORY_BLOB_DIRECTORY = "_conversation_memory"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CHUNK_BYTES = 128 * 1024
MAX_CHECKPOINT_BYTES = 192 * 1024
MAX_RANGE_BYTES = 1024 * 1024
MAX_PAGE_SIZE = 32
MAX_APPROVAL_REFS = 32
_SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_SOURCE_ID = re.compile(r"s[0-9a-f]{16}\Z")
_SECRET_FIELDS = {
    "accesstoken", "refreshtoken", "idtoken", "authorization", "clientsecret",
    "password", "downloadurl", "microsoftgraphdownloadurl", "connectionstring",
}


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SCOPE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a valid server-resolved identifier.")
    return value


def _text(value: str, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > maximum:
        raise ValueError(f"{label} is missing or exceeds its limit.")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} contains control characters.")
    return value


def _integer(value: int, label: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label} is outside its supported range.")
    return value


def _approval_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("Approval references must be a sequence of identifiers.")
    result = []
    for value in values:
        if len(result) >= MAX_APPROVAL_REFS:
            raise MemoryLimitError("Too many approval references for one memory run.")
        result.append(_identifier(value, "Approval reference"))
    return tuple(dict.fromkeys(result))


def _json_bytes(value: Any, maximum: int = MAX_MANIFEST_BYTES, *, reject_secrets: bool = False) -> bytes:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > maximum:
            raise MemoryLimitError("Conversation memory JSON is too deeply nested or large.")
        if isinstance(item, str):
            if len(item) > maximum:
                raise MemoryLimitError("Conversation memory text exceeds the object limit.")
        elif isinstance(item, dict):
            if len(item) > maximum:
                raise MemoryLimitError("Conversation memory JSON exceeds the object limit.")
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("Conversation memory JSON keys must be strings.")
                normalized = re.sub(r"[^a-z]", "", key.lower())
                if reject_secrets and normalized in _SECRET_FIELDS:
                    raise ValueError("Credentials and secret download URLs cannot be checkpointed.")
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif isinstance(item, (list, tuple)):
            if len(item) > maximum:
                raise MemoryLimitError("Conversation memory JSON exceeds the object limit.")
            stack.extend((child, depth + 1) for child in item)
        elif item is None or type(item) in (bool, int):
            continue
        elif isinstance(item, float) and math.isfinite(item):
            continue
        else:
            raise ValueError("Conversation memory requires finite, JSON-serializable values.")
    encoded = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(value):
        encoded_part = part.encode("utf-8")
        if len(encoded) + len(encoded_part) > maximum:
            raise MemoryLimitError("Conversation memory object exceeds its size limit.")
        encoded.extend(encoded_part)
    return bytes(encoded)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise MemoryIntegrityError("Conversation memory timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise MemoryIntegrityError("Conversation memory timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MemoryContext:
    tenant_id: str
    principal_id: str
    conversation_id: str
    storage_owner: str
    container: str = "personal-chat"
    request_id: str | None = None

    def __post_init__(self):
        for name in ("tenant_id", "principal_id", "conversation_id", "storage_owner"):
            _identifier(getattr(self, name), name)
        if self.container not in {"personal-chat", "group-chat"}:
            raise ValueError("Conversation memory must use a configured chat container.")
        if self.request_id is not None:
            _identifier(self.request_id, "Logical request identifier")


@dataclass(frozen=True)
class EvidenceLocation:
    pages: tuple[int, ...] = ()
    slides: tuple[int, ...] = ()
    sheet: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None

    def __post_init__(self):
        for name in ("pages", "slides"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > 128:
                raise ValueError("Evidence locations require bounded immutable page/slide tuples.")
            for value in values:
                _integer(value, name, 1)
        if self.sheet is not None:
            _text(self.sheet, "Sheet name", 256)
        for start_name, end_name, minimum in (
            ("row_start", "row_end", 1),
            ("line_start", "line_end", 1),
            ("char_start", "char_end", 0),
        ):
            start, end = getattr(self, start_name), getattr(self, end_name)
            if (start is None) != (end is None):
                raise ValueError("Evidence ranges require both boundaries.")
            if start is not None:
                _integer(start, start_name, minimum)
                _integer(end, end_name, start)


@dataclass(frozen=True)
class EvidenceChunk:
    text: str
    locator: EvidenceLocation = EvidenceLocation()

    def __post_init__(self):
        if not isinstance(self.text, str) or not isinstance(self.locator, EvidenceLocation):
            raise ValueError("Evidence chunks require text and a typed evidence location.")
        if len(self.text) > MAX_CHUNK_BYTES or len(self.text.encode("utf-8")) > MAX_CHUNK_BYTES:
            raise MemoryLimitError("Split source evidence into smaller chunks before storing it.")


@dataclass(frozen=True)
class EvidenceSource:
    source_type: str
    source_id: str
    version: str
    display_name: str = ""
    canonical_url: str = ""
    original_sha256: str | None = None
    coverage_complete: bool = False

    def __post_init__(self):
        _identifier(self.source_type, "Source type")
        _text(self.source_id, "Source identifier", 1024)
        _text(self.version, "Source version", 512)
        _text(self.display_name, "Source display name", 512, allow_empty=True)
        _text(self.canonical_url, "Canonical source URL", 4096, allow_empty=True)
        if "://" in self.source_id:
            raise ValueError("Use an immutable source identifier, not a download URL.")
        if self.canonical_url:
            try:
                url = urlsplit(self.canonical_url)
                valid = (
                    url.scheme == "https" and url.hostname and not url.username
                    and not url.password and not url.query and not url.fragment
                )
            except ValueError as exc:
                raise ValueError("Canonical source URL is invalid.") from exc
            if not valid:
                raise ValueError("Canonical URLs must be HTTPS and omit credentials, queries, and fragments.")
        if self.original_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.original_sha256):
            raise ValueError("Original source hash must be a lowercase SHA-256 digest.")
        if type(self.coverage_complete) is not bool:
            raise ValueError("Source coverage must be explicitly complete or incomplete.")


@dataclass(frozen=True)
class WorkerClaim:
    run_id: str
    principal_id: str
    token: str
    generation: int
    expires_at: str


@dataclass(frozen=True)
class PublicationApprovalReference:
    """Safe source-decision provenance, not an authorization decision by itself."""

    source: str
    approval_id: str
    decision_event_id: str
    audit_id: str
    effective_duration: str
    acknowledged_at: str
    expires_at: str | None = None
    generation: int | None = None

    def __post_init__(self):
        for name in ("source", "approval_id", "decision_event_id", "audit_id"):
            _identifier(getattr(self, name), name)
        if self.effective_duration not in {"request", "today", "always"}:
            raise ValueError("Publication source references require an affirmative sharing duration.")
        acknowledged = _timestamp(self.acknowledged_at)
        if self.effective_duration == "today" and self.expires_at is None:
            raise ValueError("A daily publication reference requires its original expiry.")
        if self.expires_at is not None and _timestamp(self.expires_at) <= acknowledged:
            raise ValueError("Publication reference expiry must follow its acknowledgement.")
        if self.generation is not None:
            _integer(self.generation, "Source approval generation")


@dataclass(frozen=True)
class PublicationGrant:
    """Returned only by the injected, server-side approval authorizer."""

    tenant_id: str
    principal_id: str
    conversation_id: str
    run_id: str
    request_id: str
    content_revision: int
    approval_ids: tuple[str, ...]
    authorization_id: str
    audience_fingerprint: str
    approved_at: str
    expires_at: str | None = None
    source_approvals: tuple[PublicationApprovalReference, ...] = ()
    publication_request_id: str | None = None


@dataclass(frozen=True)
class RetainedMemoryBlob:
    """Server-only archive record. Never route these through generic downloads."""

    container: str
    blob_name: str
    data: bytes


def is_conversation_memory_blob_path(blob_path: str) -> bool:
    """Fail closed for internal memory paths in generic file/attachment handlers."""
    if not isinstance(blob_path, str):
        return False
    candidate = blob_path
    for _ in range(8):
        normalized = unquote(candidate).replace("\\", "/")
        if MEMORY_BLOB_DIRECTORY in normalized.casefold().split("/"):
            return True
        if normalized == candidate:
            return False
        candidate = normalized
    return True


def create_conversation_memory_store(
    get_blob_service_client: Callable[[], Any],
    *,
    authorize_access: Callable[[MemoryContext, str], bool],
    log_event: Callable[..., None],
    authorize_publish: Callable[[MemoryContext, dict, Any], PublicationGrant] | None = None,
) -> "ConversationMemoryStore":
    """The bootstrap owner supplies its initialized client factory and callbacks."""
    if not callable(get_blob_service_client):
        raise ValueError("An initialized chat-storage factory is required.")
    return ConversationMemoryStore(
        get_blob_service_client(),
        authorize_access=authorize_access,
        authorize_publish=authorize_publish,
        log_event=log_event,
    )


class ConversationMemoryStore:
    def __init__(
        self,
        blob_service_client=None,
        *,
        authorize_access: Callable[[MemoryContext, str], bool],
        log_event: Callable[..., None],
        authorize_publish: Callable[[MemoryContext, dict, Any], PublicationGrant] | None = None,
        transport: MemoryBlobTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        if not callable(authorize_access) or not callable(log_event):
            raise ValueError("Conversation authorization and logging callbacks are required.")
        if authorize_publish is not None and not callable(authorize_publish):
            raise ValueError("Publication authorization must be a server callback.")
        if transport is not None and blob_service_client is not None:
            raise ValueError("Supply a chat blob client or a transport, not both.")
        self.transport = transport if transport is not None else AzureMemoryBlobTransport(blob_service_client)
        self.authorize_access = authorize_access
        self.authorize_publish = authorize_publish
        self.log_event = log_event
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("The memory clock must return a timezone-aware datetime.")
        return now.astimezone(timezone.utc)

    def _log(self, event: str, ctx: MemoryContext, run_id: str | None = None):
        self.log_event(
            f"[SIMPLE_CHAT] Conversation working memory {event}",
            {"conversation_id": ctx.conversation_id, "principal_id": ctx.principal_id, "run_id": run_id},
        )

    def _authorize(self, ctx: MemoryContext, operation: str):
        if not isinstance(ctx, MemoryContext):
            raise MemoryAuthorizationError("An authorized backing conversation context is required.")
        if self.authorize_access(ctx, operation) is not True:
            self._log("access denied", ctx)
            raise MemoryAuthorizationError("Access to this conversation memory was not authorized.")

    @staticmethod
    def _binding(ctx: MemoryContext) -> dict:
        return {
            "tenant_id": ctx.tenant_id,
            "conversation_id": ctx.conversation_id,
            "storage_owner": ctx.storage_owner,
            "container": ctx.container,
        }

    @staticmethod
    def _prefix(ctx: MemoryContext) -> str:
        tenant = hashlib.sha256(ctx.tenant_id.encode("utf-8")).hexdigest()[:32]
        return f"{ctx.storage_owner}/{ctx.conversation_id}/{MEMORY_BLOB_DIRECTORY}/v1/{tenant}"

    def _root_path(self, ctx: MemoryContext) -> str:
        return f"{self._prefix(ctx)}/manifest.json"

    def _run_path(self, ctx: MemoryContext, run_id: str) -> str:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("A server-generated memory run identifier is required.")
        return f"{self._prefix(ctx)}/runs/{run_id}/manifest.json"

    def _key_path(self, ctx: MemoryContext, key_digest: str) -> str:
        if not isinstance(key_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", key_digest):
            raise MemoryIntegrityError("Invalid conversation memory lookup key.")
        return f"{self._prefix(ctx)}/keys/{key_digest}.json"

    def _slot_path(self, ctx: MemoryContext, run_id: str, kind: str, index: int) -> str:
        _integer(index, "Memory object index", 0, 2**63 - 1)
        self._run_path(ctx, run_id)
        if kind not in {"objects", "sources", "checkpoints"}:
            raise ValueError("Unknown memory object type.")
        return f"{self._prefix(ctx)}/runs/{run_id}/{kind}/{index:016x}.json"

    @staticmethod
    def _run_id(root: dict, sequence: int) -> str:
        return uuid5(UUID(root["namespace"]), f"run:{sequence}").hex

    def _read_json(self, ctx: MemoryContext, name: str) -> tuple[dict, str]:
        record = self.transport.read(ctx.container, name, max_bytes=MAX_MANIFEST_BYTES)
        if not record.data:
            raise MemoryStateError("This conversation memory object has been deleted.")
        try:
            value = json.loads(record.data)
        except (UnicodeError, ValueError) as exc:
            raise MemoryIntegrityError("Conversation memory JSON is invalid.") from exc
        if (
            not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != MEMORY_SCHEMA_VERSION
        ):
            raise MemoryIntegrityError("Unsupported conversation memory manifest version.")
        return value, record.etag

    def _put_json(self, ctx: MemoryContext, name: str, value: dict, etag: str | None = None) -> str:
        return self.transport.put(ctx.container, name, _json_bytes(value), etag=etag)

    def _read_root(self, ctx: MemoryContext, operation: str, *, writable: bool = False) -> tuple[dict, str]:
        self._authorize(ctx, operation)
        root, etag = self._read_json(ctx, self._root_path(ctx))
        if root.get("kind") != "conversation_memory" or root.get("binding") != self._binding(ctx):
            raise MemoryAuthorizationError("Memory belongs to a different backing conversation.")
        if (
            not isinstance(root.get("namespace"), str) or not _RUN_ID.fullmatch(root["namespace"])
            or type(root.get("run_count")) is not int or root["run_count"] < 0
            or type(root.get("generation")) is not int or root["generation"] < 0
            or root.get("state") not in {"active", "archiving", "archived", "restoring", "deleting"}
        ):
            raise MemoryIntegrityError("Conversation memory scope manifest is inconsistent.")
        if writable and root.get("state") != "active":
            raise MemoryStateError("Conversation memory is archived or being deleted.")
        if root.get("state") == "deleting" and operation != "delete":
            raise MemoryStateError("Conversation memory is being deleted.")
        pending_run = root.get("pending_run")
        if pending_run is not None:
            if not isinstance(pending_run, dict) or not pending_run.get("idempotency_key"):
                raise MemoryIntegrityError("The reserved keyed memory run is invalid.")
            self._check_run(ctx, root, pending_run, pending_run.get("run_id"))
            if (
                pending_run["object_count"] or pending_run["source_slots"] or pending_run["checkpoint_slots"]
                or pending_run["claim"] is not None or pending_run["publication"] is not None
            ):
                raise MemoryIntegrityError("A keyed run reservation must describe an empty initial run.")
        return root, etag

    def _check_run(self, ctx: MemoryContext, root: dict, run: dict, run_id: str):
        sequence = run.get("sequence")
        if (
            run.get("kind") != "memory_run" or run.get("run_id") != run_id
            or run.get("binding") != self._binding(ctx)
            or type(sequence) is not int or not 0 <= sequence < root["run_count"]
            or self._run_id(root, sequence) != run_id
        ):
            raise MemoryAuthorizationError("Memory run belongs to a different backing conversation.")
        counters = (
            "generation", "content_revision", "claim_generation", "source_slots", "committed_source_slots",
            "evidence_count", "captured_chunk_count", "captured_text_bytes", "object_count",
            "checkpoint_slots", "committed_checkpoint_slots", "checkpoint_count", "completed_units",
        )
        if any(type(run.get(key)) is not int or run[key] < 0 for key in counters):
            raise MemoryIntegrityError("Conversation memory counters are invalid.")
        if run.get("idempotency_key") is not None:
            self._key_path(ctx, run["idempotency_key"])
        if (
            not 0 <= run["evidence_count"] <= run["committed_source_slots"] <= run["source_slots"]
            or not 0 <= run["checkpoint_count"] <= run["committed_checkpoint_slots"] <= run["checkpoint_slots"]
            or run.get("status") not in {"queued", "running", "waiting", "failed", "completed", "canceled"}
            or not isinstance(run.get("principal_id"), str)
            or not _SCOPE_ID.fullmatch(run["principal_id"])
            or not isinstance(run.get("content_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", run["content_sha256"])
            or type(run.get("source_coverage_complete")) is not bool
        ):
            raise MemoryIntegrityError("Conversation memory run manifest is inconsistent.")
        pending = run.get("pending")
        if pending is not None:
            if not isinstance(pending, dict) or pending.get("kind") not in {"source", "checkpoint"}:
                raise MemoryIntegrityError("Conversation memory reservation is invalid.")
            counter = "source_slots" if pending["kind"] == "source" else "checkpoint_slots"
            if (
                type(pending.get("index")) is not int or pending["index"] != run[counter] - 1
                or type(pending.get("first_object")) is not int or pending["first_object"] < 0
                or type(pending.get("object_count")) is not int or pending["object_count"] < 0
                or pending["first_object"] + pending["object_count"] != run["object_count"]
                or not isinstance(pending.get("operation_id"), str)
                or not _RUN_ID.fullmatch(pending["operation_id"])
            ):
                raise MemoryIntegrityError("Conversation memory reservation does not match its inventory.")
        publication = run.get("publication")
        if publication is not None and (
            not isinstance(publication, dict)
            or publication.get("principal_id") != run["principal_id"]
            or publication.get("tenant_id") != ctx.tenant_id
            or publication.get("content_revision") != run["content_revision"]
            or publication.get("content_sha256") != run["content_sha256"]
            or publication.get("includes_all_retained_evidence") is not True
            or not publication.get("approval_ids")
            or (
                "capture_request_id" in publication
                and publication["capture_request_id"] != run["request_id"]
            )
        ):
            raise MemoryIntegrityError("Conversation memory publication does not match its capture actor or snapshot.")

    def _read_run(
        self, ctx: MemoryContext, run_id: str, operation: str, *, write: bool = False,
    ) -> tuple[dict, str]:
        root, _ = self._read_root(ctx, operation, writable=write)
        run, etag = self._read_json(ctx, self._run_path(ctx, run_id))
        self._check_run(ctx, root, run, run_id)
        owner = run.get("principal_id") == ctx.principal_id
        if not owner and (write or run.get("publication") is None):
            raise MemoryAuthorizationError("Unpublished conversation memory is private to its capture actor.")
        if write and (run.get("publication") is not None or run.get("archived") or run.get("deleting")):
            raise MemoryStateError("Published, archived, or deleted memory cannot be changed.")
        return run, etag

    def _replace_run(self, ctx: MemoryContext, run: dict, etag: str) -> str:
        run["generation"] += 1
        run["updated_at"] = self._now().isoformat()
        return self._put_json(ctx, self._run_path(ctx, run["run_id"]), run, etag)

    @staticmethod
    def _public_run(run: dict) -> dict:
        public = deepcopy(run)
        public.pop("claim", None)
        public.pop("binding", None)
        public.pop("idempotency_key", None)
        public["pending_operation"] = (public.pop("pending", None) or {}).get("kind")
        public["source_coverage_complete"] = public["source_coverage_complete"] and public["evidence_count"] > 0
        return public

    def _get_or_create_root(self, ctx: MemoryContext) -> tuple[dict, str]:
        try:
            root, etag = self._read_root(ctx, "create", writable=True)
        except MemoryNotFoundError:
            root = {
                "schema_version": MEMORY_SCHEMA_VERSION, "kind": "conversation_memory",
                "binding": self._binding(ctx), "namespace": uuid4().hex, "run_count": 0,
                "state": "active", "generation": 0,
            }
            try:
                etag = self._put_json(ctx, self._root_path(ctx), root)
            except MemoryConflictError:
                root, etag = self._read_root(ctx, "create", writable=True)
        return root, etag

    def _new_run(
        self, ctx: MemoryContext, root: dict, sequence: int, *,
        request_id: str, purpose: str, approval_ids: tuple[str, ...],
    ) -> dict:
        now = self._now().isoformat()
        return {
            "schema_version": MEMORY_SCHEMA_VERSION, "kind": "memory_run", "run_id": self._run_id(root, sequence),
            "sequence": sequence, "binding": self._binding(ctx), "principal_id": ctx.principal_id,
            "request_id": request_id, "purpose": purpose, "created_at": now, "updated_at": now,
            "capture_approval_ids": list(approval_ids), "publication": None, "status": "queued",
            "generation": 0, "content_revision": 0, "claim_generation": 0, "claim": None,
            "pending": None, "source_slots": 0, "committed_source_slots": 0, "evidence_count": 0,
            "captured_chunk_count": 0, "captured_text_bytes": 0,
            "source_coverage_complete": True,
            "object_count": 0, "checkpoint_slots": 0, "committed_checkpoint_slots": 0,
            "checkpoint_count": 0, "latest_checkpoint": None, "completed_units": 0,
            "total_units": None, "archived": False, "deleting": False,
            "content_sha256": hashlib.sha256(b"").hexdigest(),
        }

    def create_run(
        self, ctx: MemoryContext, *, request_id: str | None = None,
        purpose: str = "analysis", approval_ids: Iterable[str] = (),
    ) -> dict:
        self._authorize(ctx, "create")
        if ctx.request_id is not None and request_id is not None and request_id != ctx.request_id:
            raise MemoryAuthorizationError("The memory request does not match its server execution context.")
        request_id = _identifier(
            request_id if request_id is not None else ctx.request_id or uuid4().hex, "Request identifier",
        )
        _identifier(purpose, "Memory purpose")
        approvals = _approval_ids(approval_ids)
        root, etag = self._get_or_create_root(ctx)
        sequence = root["run_count"]
        run = self._new_run(ctx, root, sequence, request_id=request_id, purpose=purpose, approval_ids=approvals)
        run_id = run["run_id"]
        root["run_count"] += 1
        root["generation"] += 1
        self._put_json(ctx, self._root_path(ctx), root, etag)
        self._put_json(ctx, self._run_path(ctx, run_id), run)
        self._log("run created", ctx, run_id)
        return self._public_run(run)

    @staticmethod
    def _key_record(run: dict) -> dict:
        return {
            "schema_version": MEMORY_SCHEMA_VERSION, "kind": "memory_key",
            "key_digest": run["idempotency_key"], "run_id": run["run_id"],
            "binding": run["binding"], "principal_id": run["principal_id"],
            "request_id": run["request_id"], "purpose": run["purpose"],
        }

    def _finish_keyed_creation(self, ctx: MemoryContext, root: dict):
        pending_run = root["pending_run"]
        run_id = pending_run["run_id"]
        try:
            self._put_json(ctx, self._run_path(ctx, run_id), pending_run)
        except MemoryConflictError:
            current, _ = self._read_json(ctx, self._run_path(ctx, run_id))
            self._check_run(ctx, root, current, run_id)
            if self._key_record(current) != self._key_record(pending_run):
                raise MemoryIntegrityError("The reserved memory key points to a different run.")
        key_record = self._key_record(pending_run)
        key_path = self._key_path(ctx, pending_run["idempotency_key"])
        try:
            self._put_json(ctx, key_path, key_record)
        except MemoryConflictError:
            current_key, _ = self._read_json(ctx, key_path)
            if current_key != key_record:
                raise MemoryIntegrityError("The reserved memory lookup key is inconsistent.")
        for _ in range(8):
            current_root, etag = self._read_root(ctx, "create", writable=True)
            current_pending = current_root.get("pending_run")
            if current_pending is None or current_pending["run_id"] != run_id:
                return
            current_root.pop("pending_run", None)
            current_root["generation"] += 1
            try:
                self._put_json(ctx, self._root_path(ctx), current_root, etag)
                return
            except MemoryConflictError:
                continue
        raise MemoryConflictError("Keyed conversation memory creation is still being reconciled.")

    def get_or_create_manifest(
        self, ctx: MemoryContext, *, kind: str = "m365_request", key: str | None = None,
        approval_ids: Iterable[str] = (),
    ) -> dict:
        """Get one durable run per server principal/request/key, including after a creation crash.

        Use one request key across all source plugins for shared budget counters.
        Acquire its worker claim before reading and appending a budget checkpoint.
        File-staging keys should be server-computed hashes, not model arguments.
        """
        self._authorize(ctx, "create")
        if ctx.request_id is None:
            raise MemoryAuthorizationError("Keyed memory requires a server-bound logical request identifier.")
        _identifier(kind, "Memory kind")
        key = _identifier(key if key is not None else ctx.request_id, "Memory correlation key")
        approvals = _approval_ids(approval_ids)
        key_digest = hashlib.sha256(_json_bytes({
            "binding": self._binding(ctx), "principal_id": ctx.principal_id,
            "request_id": ctx.request_id, "kind": kind, "key": key,
        })).hexdigest()
        key_path = self._key_path(ctx, key_digest)
        for _ in range(16):
            root, etag = self._get_or_create_root(ctx)
            if root.get("pending_run") is not None:
                self._finish_keyed_creation(ctx, root)
                continue
            try:
                index, _ = self._read_json(ctx, key_path)
            except MemoryNotFoundError:
                run = self._new_run(
                    ctx, root, root["run_count"], request_id=ctx.request_id,
                    purpose=kind, approval_ids=approvals,
                )
                run["idempotency_key"] = key_digest
                root["run_count"] += 1
                root["generation"] += 1
                root["pending_run"] = run
                try:
                    self._put_json(ctx, self._root_path(ctx), root, etag)
                except MemoryConflictError:
                    continue
                self._finish_keyed_creation(ctx, root)
                self._log("request-keyed run created", ctx, run["run_id"])
                return self.read_manifest(ctx, run["run_id"])
            if (
                index.get("kind") != "memory_key" or index.get("key_digest") != key_digest
                or index.get("binding") != self._binding(ctx) or index.get("principal_id") != ctx.principal_id
                or index.get("request_id") != ctx.request_id or index.get("purpose") != kind
            ):
                raise MemoryAuthorizationError("The memory lookup key belongs to a different execution context.")
            run, _ = self._read_run(ctx, index.get("run_id"), "read")
            if run.get("idempotency_key") != key_digest or self._key_record(run) != index:
                raise MemoryIntegrityError("The memory lookup key does not match its reserved run.")
            return self._public_run(run)
        raise MemoryConflictError("Conversation memory creation is busy; retry the same logical request key.")

    def read_manifest(self, ctx: MemoryContext, run_id: str) -> dict:
        run, _ = self._read_run(ctx, run_id, "read")
        return self._public_run(run)

    def list_runs(self, ctx: MemoryContext, *, start: int = 0, count: int = MAX_PAGE_SIZE) -> dict:
        _integer(start, "Run offset")
        _integer(count, "Run page size", 1, MAX_PAGE_SIZE)
        try:
            root, _ = self._read_root(ctx, "read")
        except MemoryNotFoundError:
            return {"runs": [], "next_start": None}
        end = min(start + count, root["run_count"])
        runs = []
        for index in range(start, end):
            run_id = self._run_id(root, index)
            try:
                run, _ = self._read_json(ctx, self._run_path(ctx, run_id))
            except MemoryNotFoundError:
                continue
            self._check_run(ctx, root, run, run_id)
            if run["principal_id"] == ctx.principal_id or run.get("publication") is not None:
                runs.append(self._public_run(run))
        return {"runs": runs, "next_start": end if end < root["run_count"] else None}

    def claim(self, ctx: MemoryContext, run_id: str, *, lease_seconds: int = 300) -> WorkerClaim:
        _integer(lease_seconds, "Worker lease", 1, 3600)
        run, etag = self._read_run(ctx, run_id, "claim", write=True)
        if run["status"] not in {"queued", "running"}:
            raise MemoryStateError("Resume the nonterminal run before claiming it.")
        now = self._now()
        current = run.get("claim")
        if current is not None and _timestamp(current["expires_at"]) > now:
            raise MemoryConflictError("Another worker currently owns this memory run.")
        run["claim_generation"] += 1
        claim = WorkerClaim(
            run_id, ctx.principal_id, uuid4().hex, run["claim_generation"],
            (now + timedelta(seconds=lease_seconds)).isoformat(),
        )
        run["claim"] = asdict(claim)
        run["status"] = "running"
        self._replace_run(ctx, run, etag)
        return claim

    def _claimed(self, ctx: MemoryContext, claim: WorkerClaim) -> tuple[dict, str]:
        if not isinstance(claim, WorkerClaim):
            raise MemoryAuthorizationError("A server-issued worker claim is required.")
        run, etag = self._read_run(ctx, claim.run_id, "write", write=True)
        current = run.get("claim")
        if (
            current is None or run["status"] != "running" or claim.principal_id != ctx.principal_id
            or current["generation"] != claim.generation
            or not hmac.compare_digest(current["token"], claim.token)
            or _timestamp(current["expires_at"]) <= self._now()
        ):
            raise MemoryConflictError("The conversation memory worker lost its claim.")
        return run, etag

    def renew_claim(self, ctx: MemoryContext, claim: WorkerClaim, *, lease_seconds: int = 300) -> WorkerClaim:
        _integer(lease_seconds, "Worker lease", 1, 3600)
        run, etag = self._claimed(ctx, claim)
        expires = (self._now() + timedelta(seconds=lease_seconds)).isoformat()
        run["claim"]["expires_at"] = expires
        self._replace_run(ctx, run, etag)
        return WorkerClaim(claim.run_id, claim.principal_id, claim.token, claim.generation, expires)

    def release_claim(self, ctx: MemoryContext, claim: WorkerClaim, *, status: str = "waiting") -> dict:
        if status not in {"queued", "waiting", "failed", "completed"}:
            raise ValueError("Unknown memory worker release status.")
        run, etag = self._claimed(ctx, claim)
        if run["pending"] is not None and status != "failed":
            raise MemoryStateError("Recover or discard the pending operation before releasing the worker.")
        run["claim"] = None
        run["status"] = status
        self._replace_run(ctx, run, etag)
        if status == "failed":
            self._log("worker failed; pending evidence retained", ctx, claim.run_id)
        return self._public_run(run)

    @contextmanager
    def _writer(self, ctx: MemoryContext, run_id: str, claim: WorkerClaim | None):
        implicit = claim is None
        active = self.claim(ctx, run_id) if implicit else claim
        if not isinstance(active, WorkerClaim) or active.run_id != run_id:
            raise MemoryAuthorizationError("Worker claim belongs to another memory run.")
        succeeded = False
        try:
            yield active
            succeeded = True
        finally:
            if implicit:
                try:
                    self.release_claim(ctx, active, status="queued" if succeeded else "failed")
                except (MemoryConflictError, MemoryStateError):
                    if succeeded:
                        raise
                    self._log("failed operation lost its worker claim", ctx, run_id)

    def resume(self, ctx: MemoryContext, run_id: str) -> dict:
        run, etag = self._read_run(ctx, run_id, "resume", write=True)
        if run["status"] in {"completed", "canceled"}:
            raise MemoryStateError("A completed or canceled run cannot be resumed.")
        if run.get("claim") is not None and _timestamp(run["claim"]["expires_at"]) > self._now():
            raise MemoryConflictError("A live worker still owns this memory run.")
        run["claim"] = None
        run["claim_generation"] += 1
        run["status"] = "queued"
        self._replace_run(ctx, run, etag)
        return self._public_run(run)

    def cancel(self, ctx: MemoryContext, run_id: str) -> dict:
        run, etag = self._read_run(ctx, run_id, "cancel", write=True)
        run["claim"] = None
        run["claim_generation"] += 1
        run["status"] = "canceled"
        self._replace_run(ctx, run, etag)
        self._log("run canceled", ctx, run_id)
        return self._public_run(run)

    def complete_run(self, ctx: MemoryContext, run_id: str, *, claim: WorkerClaim | None = None) -> dict:
        run, _ = self._read_run(ctx, run_id, "write", write=True)
        if run["pending"] is not None:
            raise MemoryStateError("Recover or discard pending writes before completing the run.")
        active = self.claim(ctx, run_id) if claim is None else claim
        if not isinstance(active, WorkerClaim) or active.run_id != run_id:
            raise MemoryAuthorizationError("Worker claim belongs to another memory run.")
        return self.release_claim(ctx, active, status="completed")

    def _begin(self, ctx: MemoryContext, claim: WorkerClaim, kind: str, extra: dict | None = None) -> dict:
        run, etag = self._claimed(ctx, claim)
        if run["pending"] is not None:
            raise MemoryStateError("Recover the interrupted memory operation before starting another.")
        counter = "source_slots" if kind == "source" else "checkpoint_slots"
        index = run[counter]
        run[counter] += 1
        pending = {
            "kind": kind, "index": index, "operation_id": uuid4().hex,
            "first_object": run["object_count"], "object_count": 0,
        }
        if extra:
            pending.update(extra)
        run["pending"] = pending
        self._replace_run(ctx, run, etag)
        return deepcopy(pending)

    def _pending(self, ctx: MemoryContext, claim: WorkerClaim, operation_id: str) -> tuple[dict, str]:
        run, etag = self._claimed(ctx, claim)
        if run["pending"] is None or run["pending"]["operation_id"] != operation_id:
            raise MemoryConflictError("The pending memory operation changed.")
        return run, etag

    @staticmethod
    def _chunk_body(chunk: EvidenceChunk) -> dict:
        return {"text": chunk.text, "locator": asdict(chunk.locator)}

    def add_evidence(
        self, ctx: MemoryContext, run_id: str, *, source: EvidenceSource,
        chunks: Iterable[EvidenceChunk], claim: WorkerClaim | None = None,
    ) -> dict:
        return self._add_evidence(ctx, run_id, source=source, chunks=chunks, claim=claim)

    def _add_evidence(
        self, ctx: MemoryContext, run_id: str, *, source: EvidenceSource,
        chunks: Iterable[EvidenceChunk], claim: WorkerClaim | None = None, capture: dict | None = None,
        copied_from: dict | None = None, expected_source_sha256: str | None = None,
    ) -> dict:
        if not isinstance(source, EvidenceSource):
            raise ValueError("A typed, versioned evidence source is required.")
        with self._writer(ctx, run_id, claim) as active:
            pending = self._begin(ctx, active, "source")
            digest = hashlib.sha256()
            text_bytes = 0
            chunk_count = 0
            for chunk in chunks:
                if not isinstance(chunk, EvidenceChunk):
                    raise ValueError("Source extraction must yield typed evidence chunks.")
                body = self._chunk_body(chunk)
                encoded = _json_bytes(body, MAX_MANIFEST_BYTES - 2048)
                run, etag = self._pending(ctx, active, pending["operation_id"])
                if _timestamp(run["claim"]["expires_at"]) - self._now() < timedelta(seconds=60):
                    active = self.renew_claim(ctx, active)
                    run, etag = self._pending(ctx, active, pending["operation_id"])
                object_index = run["object_count"]
                run["object_count"] += 1
                run["pending"]["object_count"] += 1
                self._replace_run(ctx, run, etag)
                payload = {
                    "schema_version": MEMORY_SCHEMA_VERSION, "kind": "evidence_chunk",
                    "run_id": run_id, "operation_id": pending["operation_id"],
                    "source_index": pending["index"], "chunk_index": chunk_count,
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "trust": "untrusted_source_data", **body,
                }
                self._put_json(ctx, self._slot_path(ctx, run_id, "objects", object_index), payload)
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                text_bytes += len(chunk.text.encode("utf-8"))
                chunk_count += 1
            if not chunk_count:
                raise ValueError("A source must contain captured evidence; empty extraction is not evidence.")
            if expected_source_sha256 is not None and digest.hexdigest() != expected_source_sha256:
                raise MemoryIntegrityError("Copied evidence does not match the selected captured source hash.")
            run, _ = self._pending(ctx, active, pending["operation_id"])
            source_record = {
                "schema_version": MEMORY_SCHEMA_VERSION, "kind": "evidence_source",
                "run_id": run_id, "operation_id": pending["operation_id"], "index": pending["index"],
                "request_id": run["request_id"],
                "evidence_id": f"s{pending['index']:016x}", "source": asdict(source),
                "first_object": pending["first_object"], "chunk_count": chunk_count,
                "captured_text_bytes": text_bytes, "content_sha256": digest.hexdigest(),
                "capture": capture if capture is not None else {
                    "principal_id": ctx.principal_id, "tenant_id": ctx.tenant_id,
                    "captured_at": self._now().isoformat(),
                    "approval_ids": run["capture_approval_ids"],
                },
                "trust": "untrusted_source_data",
            }
            if copied_from is not None:
                source_record["copied_from"] = copied_from
            self._put_json(ctx, self._slot_path(ctx, run_id, "sources", pending["index"]), source_record)
            self._commit_pending(ctx, active, source_record)
            return self._public_source(source_record)

    def copy_evidence_to_run(
        self, ctx: MemoryContext, source_run_id: str, evidence_id: str, target_run_id: str, *,
        expected_content_revision: int, expected_source_sha256: str,
        expected_run_sha256: str, claim: WorkerClaim | None = None,
    ) -> dict:
        """Copy an authorized immutable capture into a separate same-conversation working run."""
        if source_run_id == target_run_id:
            raise MemoryStateError("Copy captured evidence into a distinct working run.")
        _integer(expected_content_revision, "Captured source revision")
        for digest in (expected_source_sha256, expected_run_sha256):
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Captured source hashes must be lowercase SHA-256 digests.")
        source_run, source = self._source(ctx, source_run_id, evidence_id)
        self._read_run(ctx, target_run_id, "write", write=True)
        if source_run["status"] != "completed" or source_run["pending"] is not None:
            raise MemoryStateError("Finish source capture before starting independent analysis.")
        expected_snapshot = (expected_content_revision, expected_run_sha256, expected_source_sha256)

        def snapshot(run, record):
            return run["content_revision"], run["content_sha256"], record["content_sha256"]

        if snapshot(source_run, source) != expected_snapshot:
            raise MemoryConflictError("The selected source snapshot changed before it could be copied.")

        def chunks():
            yield from self._iter_source_chunks(ctx, source_run_id, evidence_id)
            current_run, current_source = self._source(ctx, source_run_id, evidence_id)
            if current_run["status"] != "completed" or snapshot(current_run, current_source) != expected_snapshot:
                raise MemoryConflictError("The selected source snapshot changed while it was being copied.")

        return self._add_evidence(
            ctx, target_run_id, source=EvidenceSource(**source["source"]), chunks=chunks(), claim=claim,
            capture=deepcopy(source["capture"]), expected_source_sha256=expected_source_sha256,
            copied_from={
                "run_id": source_run_id, "evidence_id": evidence_id,
                "content_revision": expected_content_revision, "run_content_sha256": expected_run_sha256,
                "source_content_sha256": expected_source_sha256,
                "publication_authorization_id": (source_run["publication"] or {}).get("authorization_id"),
            },
        )

    def _commit_pending(self, ctx: MemoryContext, claim: WorkerClaim, record: dict):
        run, etag = self._pending(ctx, claim, record["operation_id"])
        pending = run["pending"]
        if record["run_id"] != run["run_id"] or record["index"] != pending["index"]:
            raise MemoryIntegrityError("Pending memory record does not match its reservation.")
        if pending["kind"] == "source":
            if record["kind"] != "evidence_source" or record["chunk_count"] != pending["object_count"]:
                raise MemoryIntegrityError("Captured source does not cover its reserved evidence objects.")
            run["committed_source_slots"] = run["source_slots"]
            run["evidence_count"] += 1
            run["captured_chunk_count"] += record["chunk_count"]
            run["captured_text_bytes"] += record["captured_text_bytes"]
            run["source_coverage_complete"] = (
                run["source_coverage_complete"] and record["source"]["coverage_complete"]
            )
        else:
            if record["kind"] != "memory_checkpoint":
                raise MemoryIntegrityError("Invalid checkpoint record.")
            run["committed_checkpoint_slots"] = run["checkpoint_slots"]
            run["checkpoint_count"] += 1
            run["latest_checkpoint"] = record["index"]
            run["completed_units"] = record["completed_units"]
            run["total_units"] = record["total_units"]
        run["content_revision"] += 1
        run["content_sha256"] = hashlib.sha256(
            run["content_sha256"].encode("ascii") + _json_bytes(record)
        ).hexdigest()
        run["pending"] = None
        self._replace_run(ctx, run, etag)

    @staticmethod
    def _public_source(record: dict) -> dict:
        result = deepcopy(record)
        result.pop("first_object", None)
        result.pop("operation_id", None)
        return result

    def _source(self, ctx: MemoryContext, run_id: str, evidence_id: str) -> tuple[dict, dict]:
        if not isinstance(evidence_id, str) or not _SOURCE_ID.fullmatch(evidence_id):
            raise ValueError("A server-generated evidence identifier is required.")
        run, _ = self._read_run(ctx, run_id, "read")
        index = int(evidence_id[1:], 16)
        if index >= run["committed_source_slots"]:
            raise MemoryNotFoundError("The source evidence has not been committed.")
        record, _ = self._read_json(ctx, self._slot_path(ctx, run_id, "sources", index))
        if record.get("kind") == "aborted_source":
            raise MemoryNotFoundError("This source capture was discarded.")
        if (
            record.get("kind") != "evidence_source" or record.get("run_id") != run_id
            or record.get("request_id") != run["request_id"]
            or record.get("index") != index or record.get("evidence_id") != evidence_id
            or type(record.get("first_object")) is not int or type(record.get("chunk_count")) is not int
            or record["first_object"] < 0
            or record["chunk_count"] < 1
            or record["first_object"] + record["chunk_count"] > run["object_count"]
            or not isinstance(record.get("content_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["content_sha256"])
        ):
            raise MemoryIntegrityError("The evidence source manifest is inconsistent.")
        return run, record

    def list_sources(self, ctx: MemoryContext, run_id: str, *, start: int = 0, count: int = MAX_PAGE_SIZE) -> dict:
        _integer(start, "Source offset")
        _integer(count, "Source page size", 1, MAX_PAGE_SIZE)
        run, _ = self._read_run(ctx, run_id, "read")
        end = min(start + count, run["committed_source_slots"])
        sources = []
        for index in range(start, end):
            record, _ = self._read_json(ctx, self._slot_path(ctx, run_id, "sources", index))
            if record.get("kind") == "aborted_source":
                continue
            _, record = self._source(ctx, run_id, f"s{index:016x}")
            sources.append(self._public_source(record))
        return {
            "sources": sources, "next_start": end if end < run["committed_source_slots"] else None,
            "evidence_count": run["evidence_count"],
        }

    def read_source_manifest(self, ctx: MemoryContext, run_id: str, evidence_id: str) -> dict:
        """Read authorized source provenance without downloading captured chunk text."""
        _, source = self._source(ctx, run_id, evidence_id)
        return self._public_source(source)

    def _read_chunk(self, ctx: MemoryContext, run_id: str, source: dict, index: int) -> dict:
        chunk, _ = self._read_json(
            ctx, self._slot_path(ctx, run_id, "objects", source["first_object"] + index)
        )
        body = {"text": chunk.get("text"), "locator": chunk.get("locator")}
        if not isinstance(body["text"], str) or not isinstance(body["locator"], dict):
            raise MemoryIntegrityError("Captured source text or its location is invalid.")
        try:
            location = dict(body["locator"])
            location["pages"] = tuple(location["pages"])
            location["slides"] = tuple(location["slides"])
            EvidenceChunk(body["text"], EvidenceLocation(**location))
        except (KeyError, TypeError, ValueError, MemoryLimitError) as exc:
            raise MemoryIntegrityError("Captured source text or its location is invalid.") from exc
        digest = hashlib.sha256(_json_bytes(body)).hexdigest()
        if (
            chunk.get("kind") != "evidence_chunk" or chunk.get("run_id") != run_id
            or chunk.get("operation_id") != source["operation_id"]
            or chunk.get("source_index") != source["index"] or chunk.get("chunk_index") != index
            or not isinstance(chunk.get("sha256"), str)
            or not hmac.compare_digest(digest, chunk["sha256"])
        ):
            raise MemoryIntegrityError("Captured evidence failed integrity validation.")
        chunk.pop("operation_id", None)
        return chunk

    def read_evidence_range(
        self, ctx: MemoryContext, run_id: str, evidence_id: str, *,
        start: int = 0, count: int = MAX_PAGE_SIZE,
    ) -> dict:
        _integer(start, "Evidence offset")
        _integer(count, "Evidence range size", 1, MAX_PAGE_SIZE)
        _, source = self._source(ctx, run_id, evidence_id)
        end = min(start + count, source["chunk_count"])
        response = {
            "run_id": run_id, "evidence_id": evidence_id, "source": self._public_source(source),
            "trust": "untrusted_source_data", "chunks": [], "next_start": None,
            "total_chunks": source["chunk_count"],
        }
        chunks = response["chunks"]
        total_bytes = len(_json_bytes(response, MAX_RANGE_BYTES)) + 64
        for index in range(start, end):
            chunk = self._read_chunk(ctx, run_id, source, index)
            size = len(_json_bytes(chunk)) + 1
            if total_bytes + size > MAX_RANGE_BYTES:
                break
            chunks.append(chunk)
            total_bytes += size
        next_start = start + len(chunks)
        response["next_start"] = next_start if next_start < source["chunk_count"] else None
        return response

    def append_checkpoint(
        self, ctx: MemoryContext, run_id: str, *, checkpoint: Mapping[str, Any],
        output: Any = None, note: str = "", completed_units: int = 0,
        total_units: int | None = None, claim: WorkerClaim | None = None,
    ) -> dict:
        if not isinstance(checkpoint, Mapping) or not isinstance(note, str):
            raise ValueError("Checkpoints require structured state and a text note.")
        if len(note) > 8192:
            raise MemoryLimitError("Split long analysis notes across checkpoints.")
        _integer(completed_units, "Completed units")
        if total_units is not None:
            _integer(total_units, "Total units", completed_units)
        state = json.loads(_json_bytes(dict(checkpoint), 32 * 1024, reject_secrets=True))
        captured_output = json.loads(_json_bytes(output, 128 * 1024, reject_secrets=True))
        with self._writer(ctx, run_id, claim) as active:
            run, _ = self._claimed(ctx, active)
            if completed_units < run["completed_units"]:
                raise ValueError("Committed analysis progress cannot move backwards.")
            pending = self._begin(ctx, active, "checkpoint")
            record = {
                "schema_version": MEMORY_SCHEMA_VERSION, "kind": "memory_checkpoint",
                "run_id": run_id, "operation_id": pending["operation_id"], "index": pending["index"],
                "checkpoint": state, "output": captured_output, "note": note, "trust": "untrusted_analysis_data",
                "completed_units": completed_units, "total_units": total_units,
                "created_at": self._now().isoformat(), "principal_id": ctx.principal_id,
            }
            record["sha256"] = self._checkpoint_hash(record)
            _json_bytes(record, MAX_CHECKPOINT_BYTES, reject_secrets=True)
            self._put_json(ctx, self._slot_path(ctx, run_id, "checkpoints", pending["index"]), record)
            self._commit_pending(ctx, active, record)
            return self._public_checkpoint(record)

    @staticmethod
    def _checkpoint_hash(record: dict) -> str:
        body = {key: value for key, value in record.items() if key != "sha256"}
        return hashlib.sha256(_json_bytes(body)).hexdigest()

    @staticmethod
    def _public_checkpoint(record: dict) -> dict:
        result = deepcopy(record)
        result.pop("operation_id", None)
        return result

    def read_checkpoint(self, ctx: MemoryContext, run_id: str, *, index: int | None = None) -> dict | None:
        run, _ = self._read_run(ctx, run_id, "read")
        if index is None:
            index = run["latest_checkpoint"]
        if index is None:
            return None
        _integer(index, "Checkpoint index")
        if index >= run["committed_checkpoint_slots"]:
            raise MemoryNotFoundError("This checkpoint has not been committed.")
        record, _ = self._read_json(ctx, self._slot_path(ctx, run_id, "checkpoints", index))
        if record.get("kind") == "aborted_checkpoint":
            raise MemoryNotFoundError("This checkpoint was discarded.")
        if record.get("kind") != "memory_checkpoint" or record.get("run_id") != run_id or record.get("index") != index:
            raise MemoryIntegrityError("Checkpoint does not match its memory run.")
        if record.get("sha256") != self._checkpoint_hash(record):
            raise MemoryIntegrityError("The retained analysis checkpoint failed integrity validation.")
        return self._public_checkpoint(record)

    def recover_pending(
        self, ctx: MemoryContext, run_id: str, *, discard: bool = False,
        claim: WorkerClaim | None = None,
    ) -> dict:
        """Recover a durable record after a commit crash, or explicitly discard an incomplete write."""
        if type(discard) is not bool:
            raise ValueError("Interrupted memory discard must be an explicit decision.")
        with self._writer(ctx, run_id, claim) as active:
            run, _ = self._claimed(ctx, active)
            pending = run["pending"]
            if pending is None:
                return self._public_run(run)
            kind = "sources" if pending["kind"] == "source" else "checkpoints"
            path = self._slot_path(ctx, run_id, kind, pending["index"])
            if discard:
                for offset in range(pending["object_count"]):
                    self._seal(ctx, self._slot_path(ctx, run_id, "objects", pending["first_object"] + offset))
                aborted = {
                    "schema_version": MEMORY_SCHEMA_VERSION, "kind": f"aborted_{pending['kind']}",
                    "run_id": run_id, "index": pending["index"], "operation_id": pending["operation_id"],
                }
                self._seal(ctx, path, replacement=_json_bytes(aborted))
                run, etag = self._pending(ctx, active, pending["operation_id"])
                counter = "committed_source_slots" if kind == "sources" else "committed_checkpoint_slots"
                run[counter] = pending["index"] + 1
                run["pending"] = None
                self._replace_run(ctx, run, etag)
                self._log("interrupted operation discarded", ctx, run_id)
            else:
                try:
                    record, _ = self._read_json(ctx, path)
                except MemoryNotFoundError as exc:
                    raise MemoryIncompleteCaptureError(
                        "The interrupted capture is incomplete; explicitly discard it and retry."
                    ) from exc
                expected_kind = "evidence_source" if pending["kind"] == "source" else "memory_checkpoint"
                if (
                    record.get("kind") != expected_kind or record.get("run_id") != run_id
                    or record.get("operation_id") != pending["operation_id"]
                    or record.get("index") != pending["index"]
                ):
                    raise MemoryIntegrityError("Interrupted memory record does not match its reservation.")
                if pending["kind"] == "source":
                    if (
                        record.get("chunk_count") != pending["object_count"]
                        or record.get("first_object") != pending["first_object"]
                    ):
                        raise MemoryIntegrityError("Interrupted source has incomplete evidence coverage.")
                    digest = hashlib.sha256()
                    for index in range(record["chunk_count"]):
                        chunk = self._read_chunk(ctx, run_id, record, index)
                        encoded = _json_bytes({"text": chunk["text"], "locator": chunk["locator"]})
                        digest.update(len(encoded).to_bytes(8, "big"))
                        digest.update(encoded)
                    if digest.hexdigest() != record["content_sha256"]:
                        raise MemoryIntegrityError("Interrupted source evidence failed hash validation.")
                elif record.get("sha256") != self._checkpoint_hash(record):
                    raise MemoryIntegrityError("Interrupted checkpoint failed integrity validation.")
                self._commit_pending(ctx, active, record)
            current, _ = self._claimed(ctx, active)
            return self._public_run(current)

    def publish(self, ctx: MemoryContext, run_id: str, *, grant_context: Any) -> dict:
        run, etag = self._read_run(ctx, run_id, "publish", write=True)
        if self.authorize_publish is None or grant_context is None or isinstance(grant_context, bool):
            raise MemoryAuthorizationError("Publication requires a server-side approval grant.")
        if run["status"] != "completed" or run["pending"] is not None or run["claim"] is not None:
            raise MemoryStateError("Complete the memory run before publishing its retained evidence.")
        self._validate_snapshot(ctx, run)
        grant = self.authorize_publish(ctx, self._public_run(run), grant_context)
        if not isinstance(grant, PublicationGrant):
            raise MemoryAuthorizationError("The publication authorizer did not issue a valid grant.")
        bindings = (
            (grant.tenant_id, ctx.tenant_id), (grant.principal_id, run["principal_id"]),
            (grant.conversation_id, ctx.conversation_id), (grant.run_id, run_id),
            (grant.request_id, run["request_id"]), (grant.content_revision, run["content_revision"]),
        )
        if type(grant.content_revision) is not int or any(actual != expected for actual, expected in bindings):
            raise MemoryAuthorizationError("The publication approval does not match this captured snapshot.")
        approvals = _approval_ids(grant.approval_ids)
        if not approvals:
            raise MemoryAuthorizationError("Publication requires persisted approval references.")
        _identifier(grant.authorization_id, "Publication authorization")
        _text(grant.audience_fingerprint, "Approved audience fingerprint", 256)
        now = self._now()
        if _timestamp(grant.approved_at) > now or (
            grant.expires_at is not None and _timestamp(grant.expires_at) <= now
        ):
            raise MemoryAuthorizationError("The publication approval is not currently valid.")
        publication_request_id = (
            grant.publication_request_id if grant.publication_request_id is not None else ctx.request_id
        )
        if publication_request_id is not None:
            _identifier(publication_request_id, "Publication request identifier")
            if ctx.request_id is not None and publication_request_id != ctx.request_id:
                raise MemoryAuthorizationError("The publication grant belongs to a different current request.")
        if not isinstance(grant.source_approvals, tuple) or len(grant.source_approvals) > MAX_APPROVAL_REFS:
            raise MemoryLimitError("Publication source approval provenance must be a bounded immutable tuple.")
        source_approvals = []
        seen_references = set()
        for reference in grant.source_approvals:
            if not isinstance(reference, PublicationApprovalReference):
                raise MemoryAuthorizationError("Publication provenance requires typed safe source references.")
            if reference.approval_id not in approvals:
                raise MemoryAuthorizationError("Source provenance is not linked to this publication's approval references.")
            if _timestamp(reference.acknowledged_at) > now or (
                reference.expires_at is not None and _timestamp(reference.expires_at) <= now
            ):
                raise MemoryAuthorizationError("A source publication reference is not currently valid.")
            identity = (reference.source, reference.approval_id, reference.decision_event_id, reference.audit_id)
            if identity in seen_references:
                raise MemoryAuthorizationError("Duplicate source publication references are not permitted.")
            seen_references.add(identity)
            source_approvals.append(asdict(reference))
        self._authorize(ctx, "publish")
        run["publication"] = {
            "principal_id": ctx.principal_id, "tenant_id": ctx.tenant_id,
            "approval_ids": list(approvals), "authorization_id": grant.authorization_id,
            "audience_fingerprint": grant.audience_fingerprint, "approved_at": grant.approved_at,
            "published_at": now.isoformat(), "content_revision": run["content_revision"],
            "content_sha256": run["content_sha256"], "includes_all_retained_evidence": True,
            "capture_request_id": run["request_id"], "publication_request_id": publication_request_id,
            "source_approvals": source_approvals,
        }
        self._replace_run(ctx, run, etag)
        self._log("snapshot published", ctx, run_id)
        return self._public_run(run)

    def _validate_snapshot(self, ctx: MemoryContext, run: dict):
        sources, chunks, text_bytes = 0, 0, 0
        coverage_complete = True
        for index in range(run["committed_source_slots"]):
            record, _ = self._read_json(ctx, self._slot_path(ctx, run["run_id"], "sources", index))
            if record.get("kind") == "aborted_source":
                continue
            _, source = self._source(ctx, run["run_id"], f"s{index:016x}")
            digest = hashlib.sha256()
            source_bytes = 0
            for chunk_index in range(source["chunk_count"]):
                chunk = self._read_chunk(ctx, run["run_id"], source, chunk_index)
                encoded = _json_bytes({"text": chunk["text"], "locator": chunk["locator"]})
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                source_bytes += len(chunk["text"].encode("utf-8"))
            if digest.hexdigest() != source["content_sha256"] or source_bytes != source["captured_text_bytes"]:
                raise MemoryIntegrityError("The evidence snapshot does not match its captured source hash.")
            sources += 1
            chunks += source["chunk_count"]
            text_bytes += source_bytes
            coverage_complete = coverage_complete and source["source"]["coverage_complete"]
        checkpoints = 0
        for index in range(run["committed_checkpoint_slots"]):
            record, _ = self._read_json(ctx, self._slot_path(ctx, run["run_id"], "checkpoints", index))
            if record.get("kind") == "aborted_checkpoint":
                continue
            self.read_checkpoint(ctx, run["run_id"], index=index)
            checkpoints += 1
        if (
            sources != run["evidence_count"] or chunks != run["captured_chunk_count"]
            or text_bytes != run["captured_text_bytes"] or checkpoints != run["checkpoint_count"]
            or coverage_complete != run["source_coverage_complete"]
        ):
            raise MemoryIntegrityError("The memory inventory does not cover its retained evidence and results.")

    def _seal(self, ctx: MemoryContext, path: str, *, replacement: bytes = b""):
        # An empty create-only fence prevents a delayed reserved upload from resurrecting data.
        for _ in range(8):
            try:
                record = self.transport.read(ctx.container, path, max_bytes=MAX_MANIFEST_BYTES)
            except MemoryNotFoundError:
                record = None
            if record is not None:
                if record.data == replacement:
                    return
                try:
                    self.transport.delete(ctx.container, path, etag=record.etag)
                except (MemoryNotFoundError, MemoryConflictError):
                    continue
            try:
                self.transport.put(ctx.container, path, replacement)
                return
            except MemoryConflictError:
                continue
        raise MemoryConflictError("A memory object could not be fenced against concurrent writers.")

    def delete_conversation_memory(self, ctx: MemoryContext) -> dict:
        """Erase exact reserved objects, preserving empty late-writer barriers, never listing a prefix."""
        self._authorize(ctx, "delete")
        try:
            root, etag = self._read_root(ctx, "delete")
        except MemoryNotFoundError:
            return {"complete": True, "erased_objects": 0, "empty_fences_retained": True}
        except MemoryStateError:
            record = self.transport.read(ctx.container, self._root_path(ctx), max_bytes=MAX_MANIFEST_BYTES)
            if not record.data:
                return {"complete": True, "erased_objects": 0, "empty_fences_retained": True}
            raise
        root["state"] = "deleting"
        root["generation"] += 1
        self._put_json(ctx, self._root_path(ctx), root, etag)
        erased = 0
        try:
            for sequence in range(root["run_count"]):
                run_id = self._run_id(root, sequence)
                path = self._run_path(ctx, run_id)
                try:
                    run, etag = self._read_json(ctx, path)
                except (MemoryNotFoundError, MemoryStateError):
                    pending_run = root.get("pending_run")
                    if pending_run is not None and pending_run["run_id"] == run_id:
                        self._seal(ctx, self._key_path(ctx, pending_run["idempotency_key"]))
                        erased += 1
                    self._seal(ctx, path)
                    continue
                self._check_run(ctx, root, run, run_id)
                run["deleting"] = True
                run["claim"] = None
                run["claim_generation"] += 1
                self._replace_run(ctx, run, etag)
                if run.get("idempotency_key") is not None:
                    self._seal(ctx, self._key_path(ctx, run["idempotency_key"]))
                    erased += 1
                for kind, count in (
                    ("objects", run["object_count"]), ("sources", run["source_slots"]),
                    ("checkpoints", run["checkpoint_slots"]),
                ):
                    for index in range(count):
                        self._seal(ctx, self._slot_path(ctx, run_id, kind, index))
                        erased += 1
                self._seal(ctx, path)
                erased += 1
            self._seal(ctx, self._root_path(ctx))
            erased += 1
        except ConversationMemoryError as exc:
            self._log("deletion incomplete; retry required", ctx)
            raise MemoryCleanupError("Conversation working memory cleanup is incomplete; retry deletion.") from exc
        self._log("evidence deleted", ctx)
        return {"complete": True, "erased_objects": erased, "empty_fences_retained": True}

    def archive_conversation_memory(self, ctx: MemoryContext) -> dict:
        return self._set_archive_state(ctx, archived=True)

    def restore_conversation_memory(self, ctx: MemoryContext) -> dict:
        """Restore retained history in place, not source permissions or delegated credentials."""
        return self._set_archive_state(ctx, archived=False)

    def _set_archive_state(self, ctx: MemoryContext, *, archived: bool) -> dict:
        operation = "archive" if archived else "restore"
        target_state = "archived" if archived else "active"
        transition_state = "archiving" if archived else "restoring"
        try:
            root, etag = self._read_root(ctx, operation)
        except MemoryNotFoundError:
            return {"state": "absent", "run_count": 0}
        if root["state"] == target_state:
            return {"state": target_state, "run_count": root["run_count"]}
        if root["state"] in {"archiving", "restoring"} and root["state"] != transition_state:
            raise MemoryConflictError("Finish the existing memory lifecycle transition before starting another.")
        token = uuid4().hex
        root["state"] = transition_state
        root["lifecycle_token"] = token
        root["generation"] += 1
        self._put_json(ctx, self._root_path(ctx), root, etag)
        for sequence in range(root["run_count"]):
            current_root, _ = self._read_root(ctx, operation)
            if current_root.get("lifecycle_token") != token or current_root["state"] != transition_state:
                raise MemoryConflictError("Another worker took over the memory lifecycle transition.")
            run_id = self._run_id(root, sequence)
            try:
                run, etag = self._read_json(ctx, self._run_path(ctx, run_id))
            except MemoryNotFoundError:
                continue
            self._check_run(ctx, root, run, run_id)
            run["archived"] = archived
            run["claim"] = None
            run["claim_generation"] += 1
            if run["status"] == "running":
                run["status"] = "waiting"
            self._replace_run(ctx, run, etag)
        root, etag = self._read_root(ctx, operation)
        if root.get("lifecycle_token") != token or root["state"] != transition_state:
            raise MemoryConflictError("Another worker took over the memory lifecycle transition.")
        root["state"] = target_state
        root.pop("lifecycle_token", None)
        root["generation"] += 1
        self._put_json(ctx, self._root_path(ctx), root, etag)
        return {"state": root["state"], "run_count": root["run_count"]}

    def iter_retained_blobs(self, ctx: MemoryContext) -> Iterator[RetainedMemoryBlob]:
        """Server-only backup hook; archive first. Includes actor-private retained evidence."""
        try:
            root, _ = self._read_root(ctx, "archive_export")
        except MemoryNotFoundError:
            return
        if root["state"] != "archived":
            raise MemoryStateError("Archive conversation memory before exporting its retained objects.")
        root_path = self._root_path(ctx)
        record = self.transport.read(ctx.container, root_path, max_bytes=MAX_MANIFEST_BYTES)
        yield RetainedMemoryBlob(ctx.container, root_path, record.data)
        for sequence in range(root["run_count"]):
            run_id = self._run_id(root, sequence)
            path = self._run_path(ctx, run_id)
            try:
                run, _ = self._read_json(ctx, path)
            except MemoryNotFoundError:
                continue
            self._check_run(ctx, root, run, run_id)
            yield RetainedMemoryBlob(ctx.container, path, _json_bytes(run))
            if run.get("idempotency_key") is not None:
                key_path = self._key_path(ctx, run["idempotency_key"])
                try:
                    key_record = self.transport.read(ctx.container, key_path, max_bytes=MAX_MANIFEST_BYTES)
                except MemoryNotFoundError:
                    if (root.get("pending_run") or {}).get("run_id") != run_id:
                        raise MemoryIntegrityError("A committed request-key lookup is missing from its archive.")
                else:
                    yield RetainedMemoryBlob(ctx.container, key_path, key_record.data)
            for kind, count in (
                ("objects", run["object_count"]), ("sources", run["source_slots"]),
                ("checkpoints", run["checkpoint_slots"]),
            ):
                for index in range(count):
                    self._authorize(ctx, "archive_export")
                    object_path = self._slot_path(ctx, run_id, kind, index)
                    try:
                        data = self.transport.read(ctx.container, object_path, max_bytes=MAX_MANIFEST_BYTES).data
                    except MemoryNotFoundError:
                        continue
                    yield RetainedMemoryBlob(ctx.container, object_path, data)

    def fork_published_run(
        self, source_ctx: MemoryContext, run_id: str, target_ctx: MemoryContext, *,
        request_id: str | None = None,
    ) -> dict:
        """Copy published bytes into independently owned, private target refs; never publish implicitly."""
        self._authorize(source_ctx, "fork_read")
        self._authorize(target_ctx, "fork_write")
        source_run, _ = self._read_run(source_ctx, run_id, "read")
        if source_run["publication"] is None:
            raise MemoryAuthorizationError("Only published evidence may leave its source conversation.")
        if source_ctx.tenant_id != target_ctx.tenant_id or source_ctx.conversation_id == target_ctx.conversation_id:
            raise MemoryAuthorizationError("Fork memory into a distinct authorized conversation in the same tenant.")
        target = self.create_run(target_ctx, request_id=request_id, purpose=source_run["purpose"])
        target_id = target["run_id"]
        claim = self.claim(target_ctx, target_id)
        for index in range(source_run["committed_source_slots"]):
            record, _ = self._read_json(source_ctx, self._slot_path(source_ctx, run_id, "sources", index))
            if record.get("kind") == "aborted_source":
                continue
            _, source = self._source(source_ctx, run_id, f"s{index:016x}")
            self._add_evidence(
                target_ctx, target_id, source=EvidenceSource(**source["source"]),
                chunks=self._iter_source_chunks(source_ctx, run_id, source["evidence_id"]),
                claim=claim, capture=source["capture"],
            )
            claim = self.renew_claim(target_ctx, claim)
        for index in range(source_run["committed_checkpoint_slots"]):
            record, _ = self._read_json(source_ctx, self._slot_path(source_ctx, run_id, "checkpoints", index))
            if record.get("kind") == "aborted_checkpoint":
                continue
            checkpoint = self.read_checkpoint(source_ctx, run_id, index=index)
            self.append_checkpoint(
                target_ctx, target_id, checkpoint=checkpoint["checkpoint"], output=checkpoint["output"],
                note=checkpoint["note"], completed_units=checkpoint["completed_units"],
                total_units=checkpoint["total_units"], claim=claim,
            )
            claim = self.renew_claim(target_ctx, claim)
        run, etag = self._claimed(target_ctx, claim)
        run["copied_from"] = {
            "conversation_id": source_ctx.conversation_id, "run_id": run_id,
            "publication_authorization_id": source_run["publication"]["authorization_id"],
        }
        self._replace_run(target_ctx, run, etag)
        return self.complete_run(target_ctx, target_id, claim=claim)

    def _iter_source_chunks(self, ctx: MemoryContext, run_id: str, evidence_id: str) -> Iterator[EvidenceChunk]:
        start = 0
        while True:
            page = self.read_evidence_range(ctx, run_id, evidence_id, start=start)
            for chunk in page["chunks"]:
                locator = dict(chunk["locator"])
                locator["pages"] = tuple(locator["pages"])
                locator["slides"] = tuple(locator["slides"])
                yield EvidenceChunk(chunk["text"], EvidenceLocation(**locator))
            if page["next_start"] is None:
                return
            start = page["next_start"]
