# jobs.py
"""Durable, paged workspace scans with per-document holds and fenced leases.

Futures are not job state. A scheduler invocation performs a bounded slice and
leaves enumeration, retries, cancellation, and work-item outcomes in Cosmos.
Application authorization, logging, and scanning dependencies load on demand.
"""

import copy
import importlib
import logging
import re
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from content_screening.contracts import (
    AVAILABLE_STATES,
    HELD_STATES,
    SCREENING_FIELD,
    SCOPE_TYPES,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    document_is_available,
    hash_payload,
    metadata_fingerprint,
    normalize_identifier,
    normalize_units,
    subject_from_document,
)
from content_screening.repository import MAX_DOCUMENT_SELECTION, get_repository
from content_screening.permissions import ScreeningPermissionError, assert_scope_access


LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 30
MAX_ATTEMPTS = 3
ENUMERATION_PAGE_SIZE = 50
MAX_ENUMERATION_PAGES = 2
MAX_ITEMS_PER_RUN = 25
MAX_DISCOVERY_PAGES = 20
MAX_CONCURRENT_JOBS = 2
RUNNER_ADMISSION_ID = "screening-runner-admission"
COMPLETION_DISCOVERY_ID = "screening-completion-discovery"
PUBLICATION_DISCOVERY_ID = "screening-publication-discovery"
COMPLETED_SCAN_STATES = AVAILABLE_STATES | {"pending_review"}
SCOPE_ORDER = ("personal", "group", "public")
ITEM_STATUSES = ("queued", "running", "retry", "completed", "findings", "incomplete", "failed", "skipped")
FINISHED_JOB_STATUSES = frozenset({"completed", "completed_with_findings", "incomplete", "failed", "cancelled"})
PROCESSOR_CONTEXT = ContextVar("content_screening_job_processor", default=None)


class ScreeningJobStopped(ScreeningConflictError):
    code = "screening_job_stopped"


class _ScanLeaseBusy(ScreeningConflictError):
    code = "screening_busy"

    def __init__(self, expires_at):
        super().__init__("The active content scan has not released its lease.")
        self.expires_at = expires_at


def _now():
    return datetime.now(timezone.utc)


def _timestamp():
    return _now().isoformat()


def _expired(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.tzinfo is None or parsed <= _now()
    except (TypeError, ValueError):
        return True


def _log(code, *, job_id=None, error_type=None):
    # Logging configuration may import application settings; defer until use.
    from functions_appinsights import log_event

    log_event(
        f"[CONTENT_SCREENING] {code}",
        extra={"job_id": job_id, "error_type": error_type},
        level=logging.WARNING if error_type else logging.INFO,
        debug_only=not bool(error_type),
    )


def _repo(repository):
    return repository if repository is not None else get_repository()


def _actor(actor_id):
    return normalize_identifier(actor_id, "actor")


def _verified_admin(actor_id, requested=False):
    if requested is not True:
        return False
    # Request claims are server-authenticated; a JSON is_admin flag is not.
    from flask import has_request_context, session

    if not has_request_context():
        raise ScreeningPermissionError()
    user = session.get("user") or {}
    identity = user.get("oid") or user.get("id") or user.get("user_id")
    if identity != actor_id or "Admin" not in (user.get("roles") or []):
        raise ScreeningPermissionError()
    return True


def _authorize_scope(actor_id, scope_type, scope_id, *, admin_authorized=False):
    if not isinstance(scope_type, str) or scope_type not in SCOPE_TYPES:
        raise ScreeningValidationError("The screening scope is invalid.")
    if admin_authorized:
        return
    assert_scope_access(actor_id, scope_type, scope_id)


def _selection(value):
    if not isinstance(value, dict) or set(value) - {"scope_type", "scope_id", "document_ids", "all_workspaces"}:
        raise ScreeningValidationError("The scan selection is invalid.")
    if value.get("all_workspaces") is True:
        if any(value.get(key) is not None for key in ("scope_type", "scope_id", "document_ids")):
            raise ScreeningValidationError("An all-workspaces scan cannot contain a second selection.")
        return {"all_workspaces": True}
    if value.get("all_workspaces") is not None and type(value["all_workspaces"]) is not bool:
        raise ScreeningValidationError("The all-workspaces selection is invalid.")
    scope_type = value.get("scope_type")
    if not isinstance(scope_type, str) or scope_type not in SCOPE_TYPES:
        raise ScreeningValidationError("The screening scope is invalid.")
    result = {"scope_type": scope_type, "scope_id": normalize_identifier(value.get("scope_id"), "scope")}
    if "document_ids" in value:
        ids = value["document_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_DOCUMENT_SELECTION:
            raise ScreeningValidationError("The document selection is invalid.")
        result["document_ids"] = sorted({normalize_identifier(item, "document") for item in ids})
    return result


def _authorize_selection(actor_id, selection, *, admin_authorized=False):
    if selection.get("all_workspaces"):
        if not admin_authorized:
            raise ScreeningPermissionError()
        return
    _authorize_scope(actor_id, selection["scope_type"], selection["scope_id"], admin_authorized=admin_authorized)


def _configuration_snapshot(selection, repository):
    service = importlib.import_module("content_screening.service")
    settings = service._settings()
    if settings.get("enable_content_screening") is not True:
        raise ScreeningConfigurationError("Enable content screening before creating a scan job.")
    service.validate_screening_configuration(settings, repository=repository, check_storage=True)
    baseline = repository.get_policy("global", "global")
    workspace = None
    if not selection.get("all_workspaces"):
        workspace = repository.get_policy(selection["scope_type"], selection["scope_id"])
    return {
        "baseline": baseline.get("policy_fingerprint") or hash_payload(baseline["policy"]) if baseline else None,
        "workspace": workspace.get("policy_fingerprint") or hash_payload(workspace["policy"]) if workspace else None,
    }


def _screening_enabled():
    return importlib.import_module("content_screening.service")._settings().get("enable_content_screening") is True


def _assert_policy_snapshot(job, repository):
    baseline = repository.get_policy("global", "global")
    fingerprint = baseline.get("policy_fingerprint") or hash_payload(baseline["policy"]) if baseline else None
    if fingerprint != job["policy_snapshot"].get("baseline"):
        raise ScreeningConflictError(code="screening_job_policy_changed")
    selection = job["selection"]
    if not selection.get("all_workspaces"):
        workspace = repository.get_policy(selection["scope_type"], selection["scope_id"])
        fingerprint = workspace.get("policy_fingerprint") or hash_payload(workspace["policy"]) if workspace else None
        if fingerprint != job["policy_snapshot"].get("workspace"):
            raise ScreeningConflictError(code="screening_job_policy_changed")


def _assert_migration_open():
    configuration = importlib.import_module("config")
    fence = importlib.import_module("functions_data_management_search_write_fence")
    if not fence.inspect_data_management_search_write_gate(configuration.cosmos_settings_container)["available"]:
        raise ScreeningJobStopped(code="screening_migration_frozen")


def _job(repository, job_id):
    job_id = normalize_identifier(job_id, "job")
    job = repository.get(job_id, job_id)
    if not job or job.get("kind") != "job":
        raise ScreeningValidationError("The scan job was not found.", code="screening_not_found")
    return job


def _replace(repository, record, **updates):
    return repository.replace({**record, **updates, "updated_at": _timestamp()}, record.get("_etag"))


def _mutate_job(repository, job_id, mutation, *, owner=None):
    for _attempt in range(5):
        job = _job(repository, job_id)
        if owner is not None and (
            (job.get("lease") or {}).get("owner") != owner
            or _expired((job.get("lease") or {}).get("expires_at"))
        ):
            raise ScreeningJobStopped()
        updates = mutation(copy.deepcopy(job))
        if updates is None:
            return job
        try:
            return _replace(repository, job, **updates)
        except ScreeningConflictError:
            continue
    raise ScreeningJobStopped()


def _new_job(actor_id, selection, admin_authorized, policy_snapshot, *, job_id=None):
    timestamp = _timestamp()
    return {
        "id": job_id or f"job-{uuid.uuid4().hex}", "kind": "job",
        "scope_key": "global:all" if selection.get("all_workspaces") else f"{selection['scope_type']}:{selection['scope_id']}",
        "scope_type": selection.get("scope_type", "global"), "scope_id": selection.get("scope_id", "all"),
        "actor_id": actor_id, "selection": selection, "policy_snapshot": policy_snapshot,
        # Only create_scan_job mints this grant from verified request claims.
        "authorization": {"actor_id": actor_id, "kind": "admin" if admin_authorized else "scope", "issued_at": timestamp},
        "status": "queued", "cancel_requested": False, "lease": None,
        "enumeration": {
            "scope_index": 0, "continuation": None, "complete": False, "pages": 0,
            "unresolved_ids": list(selection.get("document_ids", [])),
        },
        "resume_generation": 0, "reset_pending": False,
        "counts": {**{status: 0 for status in ITEM_STATUSES}, "total": 0},
        "created_at": timestamp, "updated_at": timestamp,
    }


def create_scan_job(actor_id, selection, *, is_admin=False, repository=None):
    repository, actor_id, selection = _repo(repository), _actor(actor_id), _selection(selection)
    administrator = _verified_admin(actor_id, is_admin)
    _authorize_selection(actor_id, selection, admin_authorized=administrator)
    _assert_migration_open()
    snapshot = _configuration_snapshot(selection, repository)
    job = _new_job(actor_id, selection, administrator, snapshot)
    job["partition_key"] = job["id"]
    created = repository.create(job)
    _log("job_created", job_id=created["id"])
    return created


def _authorize_job(job, actor_id, *, administrator=False):
    _authorize_selection(actor_id, job["selection"], admin_authorized=administrator)


def get_scan_job(job_id, actor_id, *, is_admin=False, repository=None):
    repository, actor_id = _repo(repository), _actor(actor_id)
    job = _job(repository, job_id)
    _authorize_job(job, actor_id, administrator=_verified_admin(actor_id, is_admin))
    return job


def list_scan_jobs(actor_id, *, scope_type=None, scope_id=None, is_admin=False, continuation=None, page_size=50, repository=None):
    repository, actor_id = _repo(repository), _actor(actor_id)
    administrator = _verified_admin(actor_id, is_admin)
    scope_key, filters = None, {}
    if scope_type is not None or scope_id is not None:
        selection = _selection({"scope_type": scope_type, "scope_id": scope_id})
        _authorize_selection(actor_id, selection, admin_authorized=administrator)
        scope_key = f"{selection['scope_type']}:{selection['scope_id']}"
    elif not administrator:
        filters["actor_id"] = actor_id
    page = repository.query("job", scope_key, filters=filters, continuation=continuation, page_size=page_size)
    visible = []
    for job in page["items"]:
        try:
            _authorize_job(job, actor_id, administrator=administrator)
        except (PermissionError, LookupError):
            continue
        visible.append(job)
    return {"items": visible, "continuation": page["continuation"]}


def request_scan_job_action(job_id, actor_id, action, *, is_admin=False, repository=None):
    repository, actor_id = _repo(repository), _actor(actor_id)
    administrator = _verified_admin(actor_id, is_admin)
    if action not in {"cancel", "resume", "retry"}:
        raise ScreeningValidationError("The scan job action is invalid.")
    snapshot = None
    if action != "cancel":
        job = _job(repository, job_id)
        _authorize_job(job, actor_id, administrator=administrator)
        _assert_migration_open()
        snapshot = _configuration_snapshot(job["selection"], repository)

    def change(job):
        _authorize_job(job, actor_id, administrator=administrator)
        if action == "cancel":
            if job["status"] in {"completed", "completed_with_findings"}:
                return None
            return {
                "cancel_requested": True, "cancel_requested_at": _timestamp(),
                "cancel_complete": False, "cancel_continuation": None,
                "status": "running" if job.get("lease") and not _expired(job["lease"].get("expires_at")) else "queued",
            }
        if job.get("lease") and not _expired(job["lease"].get("expires_at")):
            raise ScreeningConflictError("The scan job is still running.")
        if job["status"] not in {"cancelled", "failed", "incomplete"}:
            raise ScreeningConflictError("The scan job cannot be resumed in its current state.")
        _assert_policy_snapshot(job, repository)
        if snapshot != job["policy_snapshot"]:
            raise ScreeningConflictError(code="screening_job_policy_changed")
        return {
            "status": "queued", "cancel_requested": False, "cancel_requested_at": None, "lease": None,
            "resume_generation": int(job.get("resume_generation", 0)) + 1, "reset_pending": True,
            "reset_continuation": None, "error_code": None, "cancel_complete": False,
            "work_continuation": None,
        }

    result = _mutate_job(repository, job_id, change)
    _log(f"job_{action}_requested", job_id=job_id)
    return result


def _item_id(job_id, subject):
    return f"item-{hash_payload([job_id, subject.key])}"


def scan_id_for_job(job_id, subject):
    return hash_payload(["job-scan", job_id, subject.key])


def _source_fingerprint(document):
    return hash_payload({
        key: document.get(key) for key in (
            "id", "version", "file_name", "blob_container", "blob_path", "archived_blob_path",
            "blob_etag", "source_etag", "file_size",
        )
    })


def _new_item(job, subject, *, scan_id=None, document=None):
    return {
        "id": _item_id(job["id"], subject), "partition_key": job["id"],
        "kind": "work_item", "job_id": job["id"], "subject": subject.to_dict(),
        "actor_id": job["actor_id"], "scan_id": scan_id or scan_id_for_job(job["id"], subject),
        "status": "queued", "attempts": 0, "lease": None,
        "resume_generation": job.get("resume_generation", 0),
        "checkpoint": {"stage": "queued"}, "started": False,
        "source_fingerprint": _source_fingerprint(document) if document is not None else None,
        "finding_count": 0,
    }


def _create_item(repository, job, subject, *, scan_id=None, document=None):
    record = _new_item(job, subject, scan_id=scan_id, document=document)
    try:
        return repository.create(record)
    except ScreeningConflictError:
        existing = repository.get(record["id"], job["id"])
        if (
            not existing or existing.get("subject") != subject.to_dict()
            or existing.get("job_id") != job["id"] or existing.get("scan_id") != record["scan_id"]
        ):
            raise
        return existing


def _verify_ingestion_job(job, subject, scan_id, actor_id):
    if (
        job.get("kind") != "job" or job.get("actor_id") != actor_id
        or job.get("ingestion_scan_id") != scan_id
        or job.get("selection") != {
            "scope_type": subject.scope_type, "scope_id": subject.scope_id,
            "document_ids": [subject.document_id],
        }
    ):
        raise ScreeningConflictError("The queued scan does not match this enrollment.")


def enqueue_document_scan(subject, actor_id, *, scan_id=None, repository=None):
    """Idempotently enroll an already-authorized ingestion/reprocessing scan.

    Internal upload/metadata adapters must stage and authorize the exact scan
    before calling this helper. It never grants workspace or evidence access,
    and must not be exposed as an alternative to role-checked create_scan_job.
    """
    repository, actor_id = _repo(repository), _actor(actor_id)
    subject = subject if isinstance(subject, Subject) else Subject.from_dict(subject)
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    scan_id = scan_id or marker.get("scan_id")
    scan = repository.get_scan(scan_id) if scan_id else None
    if (
        not scan or scan.get("subject") != subject.to_dict() or scan.get("actor_id") != actor_id
        or marker.get("scan_id") != scan_id
    ):
        raise ScreeningConflictError("Only the active authorized scan can be queued.")
    job_id = f"job-{hash_payload([subject.key, scan_id])}"
    existing = repository.get(job_id, job_id)
    if existing:
        _verify_ingestion_job(existing, subject, scan_id, actor_id)
        _create_item(repository, existing, subject, scan_id=scan_id, document=document)
        return existing
    selection = {"scope_type": subject.scope_type, "scope_id": subject.scope_id, "document_ids": [subject.document_id]}
    baseline = repository.get_policy("global", "global")
    workspace = repository.get_policy(subject.scope_type, subject.scope_id)
    snapshot = {
        "baseline": baseline.get("policy_fingerprint") or hash_payload(baseline["policy"]) if baseline else None,
        "workspace": workspace.get("policy_fingerprint") or hash_payload(workspace["policy"]) if workspace else None,
    }
    job = _new_job(actor_id, selection, False, snapshot, job_id=job_id)
    job.update({
        "partition_key": job_id, "ingestion_scan_id": scan_id,
        "counts": {**job["counts"], "queued": 1, "total": 1},
    })
    try:
        job = repository.create(job)
    except ScreeningConflictError:
        job = _job(repository, job_id)
    _verify_ingestion_job(job, subject, scan_id, actor_id)
    _create_item(repository, job, subject, scan_id=scan_id, document=document)
    return job


def _job_administrator(job):
    grant = job.get("authorization") or {}
    return grant.get("kind") == "admin" and grant.get("actor_id") == job.get("actor_id") and bool(grant.get("issued_at"))


def _assert_authority(job, subject=None, *, repository=None):
    if job.get("ingestion_scan_id"):
        # An upload adapter has already enrolled this exact scan. Background
        # ingestion is a system gate, not a grant of management/review rights.
        repository = _repo(repository)
        scan = repository.get_scan(job["ingestion_scan_id"])
        if not scan or scan.get("actor_id") != job["actor_id"]:
            raise ScreeningPermissionError()
        enrolled = Subject.from_dict(scan["subject"])
        selection = job["selection"]
        if (
            enrolled.scope_type != selection.get("scope_type")
            or enrolled.scope_id != selection.get("scope_id")
            or selection.get("document_ids") != [enrolled.document_id]
            or (subject is not None and subject != enrolled)
        ):
            raise ScreeningPermissionError()
        repository.read_document(enrolled)
        return
    else:
        administrator = _job_administrator(job)
    _authorize_selection(job["actor_id"], job["selection"], admin_authorized=administrator)
    if subject is not None:
        selection = job["selection"]
        if not selection.get("all_workspaces") and (
            subject.scope_type != selection["scope_type"] or subject.scope_id != selection["scope_id"]
            or ("document_ids" in selection and subject.document_id not in selection["document_ids"])
        ):
            raise ScreeningConflictError()
        _authorize_scope(job["actor_id"], subject.scope_type, subject.scope_id, admin_authorized=administrator)


def _assert_owned(repository, job_id, owner, *, allow_cancel=False):
    job = _job(repository, job_id)
    lease = job.get("lease") or {}
    if lease.get("owner") != owner or _expired(lease.get("expires_at")):
        raise ScreeningJobStopped()
    if lease.get("admitted"):
        _assert_admission(repository, job_id, owner)
    if job.get("cancel_requested") and not allow_cancel:
        raise ScreeningJobStopped(code="screening_job_cancelled")
    return job


def assert_scan_job_active(job_id, subject=None, *, repository=None):
    """Fence scanner side effects against cancellation, policy changes, and lease loss."""
    context = PROCESSOR_CONTEXT.get()
    repository = _repo(repository or (context or {}).get("repository"))
    job = _job(repository, job_id)
    lease = job.get("lease") or {}
    if (
        job.get("cancel_requested") or job.get("status") != "running" or _expired(lease.get("expires_at"))
        or (context and (context["job_id"] != job_id or lease.get("owner") != context["owner"]))
    ):
        raise ScreeningJobStopped()
    if lease.get("admitted"):
        _assert_admission(repository, job_id, lease["owner"])
    if subject is not None:
        subject = subject if isinstance(subject, Subject) else Subject.from_dict(subject)
    _assert_authority(job, subject, repository=repository)
    _assert_policy_snapshot(job, repository)
    _assert_migration_open()
    return job


def checkpoint_scan_job_item(job_id, subject, checkpoint, *, repository=None):
    """Persist bounded unit/window progress only for the active leased processor."""
    context = PROCESSOR_CONTEXT.get()
    if not context or context["job_id"] != job_id:
        raise ScreeningJobStopped()
    repository = _repo(repository if repository is not None else context["repository"])
    subject = subject if isinstance(subject, Subject) else Subject.from_dict(subject)
    allowed_counts = {"units_total", "units_completed", "windows_total", "windows_completed"}
    fingerprint_fields = {
        "last_unit_hash", "content_fingerprint", "policy_fingerprint", "publication_source_fingerprint",
    }
    allowed_fields = allowed_counts | {"stage"} | fingerprint_fields
    if not isinstance(checkpoint, dict) or set(checkpoint) - allowed_fields:
        raise ScreeningValidationError("The scan checkpoint is invalid.")
    for key, value in checkpoint.items():
        if key in allowed_counts and (type(value) is not int or not 0 <= value <= 1000000000):
            raise ScreeningValidationError("The scan checkpoint count is invalid.")
        if key in fingerprint_fields and (
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        ):
            raise ScreeningValidationError("The scan checkpoint fingerprint is invalid.")
    if "stage" in checkpoint and checkpoint["stage"] not in {"held", "extracting", "scanning", "publishing"}:
        raise ScreeningValidationError("The scan checkpoint stage is invalid.")
    for prefix in ("units", "windows"):
        if checkpoint.get(f"{prefix}_completed", 0) > checkpoint.get(f"{prefix}_total", 1000000000):
            raise ScreeningValidationError("The scan checkpoint coverage is invalid.")
    for _attempt in range(5):
        assert_scan_job_active(job_id, subject, repository=repository)
        item = repository.get(_item_id(job_id, subject), job_id)
        if not item or (item.get("lease") or {}).get("owner") != context["owner"]:
            raise ScreeningJobStopped()
        try:
            return _replace(repository, item, checkpoint={**item.get("checkpoint", {}), **checkpoint})
        except ScreeningConflictError:
            continue
    raise ScreeningJobStopped()


def _admission(repository, job_id, owner, *, renew=False):
    for _attempt in range(5):
        record = repository.get(RUNNER_ADMISSION_ID, RUNNER_ADMISSION_ID)
        slots = [slot for slot in (record or {}).get("slots", []) if not _expired(slot.get("expires_at"))]
        current = next((slot for slot in slots if slot.get("job_id") == job_id and slot.get("owner") == owner), None)
        if renew and current is None:
            raise ScreeningJobStopped()
        if current is None and len(slots) >= MAX_CONCURRENT_JOBS:
            return False
        slot = {
            "job_id": job_id, "owner": owner,
            "expires_at": (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        }
        slots = [entry for entry in slots if entry is not current] + [slot]
        try:
            if record is None:
                repository.create({
                    "id": RUNNER_ADMISSION_ID, "partition_key": RUNNER_ADMISSION_ID,
                    "kind": "checkpoint", "scope_key": "global:system", "slots": slots,
                })
            else:
                _replace(repository, record, slots=slots)
            return True
        except ScreeningConflictError:
            continue
    raise ScreeningJobStopped()


def _assert_admission(repository, job_id, owner):
    record = repository.get(RUNNER_ADMISSION_ID, RUNNER_ADMISSION_ID)
    if not record or not any(
        slot.get("job_id") == job_id and slot.get("owner") == owner and not _expired(slot.get("expires_at"))
        for slot in record.get("slots", [])
    ):
        raise ScreeningJobStopped()


def _release_admission(repository, job_id, owner):
    for _attempt in range(5):
        record = repository.get(RUNNER_ADMISSION_ID, RUNNER_ADMISSION_ID)
        if record is None:
            return
        remaining = [
            slot for slot in record.get("slots", [])
            if slot.get("job_id") != job_id or slot.get("owner") != owner
        ]
        if remaining == record.get("slots"):
            return
        try:
            _replace(repository, record, slots=remaining)
            return
        except ScreeningConflictError:
            continue


def _claim_job(repository, job):
    if job["status"] in FINISHED_JOB_STATUSES and not job.get("cancel_requested"):
        return None
    lease = job.get("lease") or {}
    if lease and not _expired(lease.get("expires_at")):
        return None
    owner = uuid.uuid4().hex
    try:
        claimed = _replace(
            repository, job, status="running",
            lease={"owner": owner, "expires_at": (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat()},
            heartbeat_at=_timestamp(),
        )
        if not _admission(repository, job["id"], owner):
            _mutate_job(repository, job["id"], lambda current: {"status": "queued", "lease": None}, owner=owner)
            return None
        claimed = _mutate_job(
            repository, job["id"],
            lambda current: {"lease": {**current["lease"], "admitted": True}},
            owner=owner,
        )
        return claimed, owner
    except ScreeningConflictError:
        return None


def _heartbeat(repository, job_id, owner, item_id=None):
    expires = (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat()
    _admission(repository, job_id, owner, renew=True)
    job = _mutate_job(
        repository, job_id,
        lambda current: {"lease": {"owner": owner, "expires_at": expires, "admitted": True}, "heartbeat_at": _timestamp()},
        owner=owner,
    )
    if item_id:
        for _attempt in range(5):
            item = repository.get(item_id, job_id)
            if not item or (item.get("lease") or {}).get("owner") != owner:
                raise ScreeningJobStopped()
            try:
                _replace(repository, item, lease={"owner": owner, "expires_at": expires}, heartbeat_at=_timestamp())
                break
            except ScreeningConflictError:
                continue
        else:
            raise ScreeningJobStopped()
    return job


class _Heartbeat:
    def __init__(self, repository, job_id, owner, item_id):
        self.repository, self.job_id, self.owner, self.item_id = repository, job_id, owner, item_id
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            try:
                job = _heartbeat(self.repository, self.job_id, self.owner, self.item_id)
                if job.get("cancel_requested"):
                    return
            except Exception:
                self.lost.set()
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join(timeout=HEARTBEAT_SECONDS + 1)


def _enumerate(repository, job, owner):
    for _page_index in range(MAX_ENUMERATION_PAGES):
        job = _assert_owned(repository, job["id"], owner)
        _assert_authority(job, repository=repository)
        progress = copy.deepcopy(job["enumeration"])
        if progress["complete"]:
            return job
        selection = job["selection"]
        scopes = SCOPE_ORDER if selection.get("all_workspaces") else (selection["scope_type"],)
        scope_type = scopes[progress["scope_index"]]
        page = repository.query_documents(
            scope_type, selection.get("scope_id"), document_ids=selection.get("document_ids"),
            continuation=progress["continuation"], page_size=ENUMERATION_PAGE_SIZE,
        )
        for document in page["items"]:
            _assert_owned(repository, job["id"], owner)
            subject = subject_from_document(document)
            if subject.scope_type != scope_type:
                raise ScreeningConflictError(code="screening_enumeration_scope_changed")
            _assert_authority(job, subject, repository=repository)
            _create_item(repository, job, subject, scan_id=job.get("ingestion_scan_id"), document=document)
            if subject.document_id in progress.get("unresolved_ids", []):
                progress["unresolved_ids"].remove(subject.document_id)
        progress["pages"] += 1
        progress["continuation"] = page["continuation"]
        if page["continuation"] is None:
            progress["scope_index"] += 1
            progress["complete"] = progress["scope_index"] >= len(scopes)
        if progress["complete"]:
            for document_id in progress.get("unresolved_ids", []):
                missing = Subject(selection["scope_type"], selection["scope_id"], document_id, "missing")
                item = _create_item(repository, job, missing)
                if item["status"] == "queued":
                    _replace(repository, item, status="skipped", error_code="screening_source_missing")
        job = _mutate_job(repository, job["id"], lambda current: {"enumeration": progress}, owner=owner)
        _heartbeat(repository, job["id"], owner)
    return job


def _reset_items(repository, job, owner):
    if not job.get("reset_pending"):
        return job
    page = repository.query(
        "work_item", filters={"job_id": job["id"]},
        continuation=job.get("reset_continuation"), page_size=ENUMERATION_PAGE_SIZE,
    )
    for item in page["items"]:
        if item["status"] not in {"failed", "incomplete", "retry"}:
            continue
        if int(item.get("resume_generation", 0)) >= job["resume_generation"]:
            continue
        _assert_owned(repository, job["id"], owner)
        _replace(
            repository, item, status="queued", attempts=0, lease=None, error_code=None,
            next_attempt_at=None, resume_generation=job["resume_generation"],
        )
    return _mutate_job(
        repository, job["id"],
        lambda current: {"reset_pending": page["continuation"] is not None, "reset_continuation": page["continuation"]},
        owner=owner,
    )


def _active_scan_lease(repository, item):
    subject = Subject.from_dict(item["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if not isinstance(marker, dict):
        raise ScreeningConflictError()
    scan_ids = [item["scan_id"]]
    if marker.get("scan_id") and marker["scan_id"] != item["scan_id"]:
        scan_ids.append(marker["scan_id"])
    for scan_id in scan_ids:
        scan = repository.get_scan(scan_id)
        if scan is None:
            continue
        if scan.get("subject") != item["subject"]:
            raise ScreeningConflictError()
        if scan.get("state") in {"cleared", "approved_with_flags", "pending_review", "rejected", "deleted"}:
            continue
        lease = scan.get("lease") or {}
        if lease and not _expired(lease.get("expires_at")):
            return lease["expires_at"]
    return None


def _defer_scan_lease(repository, job, item, owner, expires_at, *, claimed=False):
    _assert_owned(repository, job["id"], owner)
    updates = {
        "status": "queued", "error_code": None, "next_attempt_at": expires_at,
        "attempts": max(0, int(item.get("attempts", 0)) - int(claimed)),
    }
    if claimed:
        return _finish_item(
            repository, job["id"], item["id"], owner,
            checkpoint_stage="waiting_for_scan_lease", **updates,
        )
    if item.get("checkpoint", {}).get("stage") == "waiting_for_scan_lease" and item.get("next_attempt_at") == expires_at:
        return item
    return _replace(
        repository, item, **updates, lease=None,
        checkpoint={**item.get("checkpoint", {}), "stage": "waiting_for_scan_lease"},
    )


def _claim_item(repository, job, item, owner, *, completed=False):
    if item["status"] not in {"queued", "running", "retry"}:
        return None
    if not completed and item["status"] == "retry" and not _expired(item.get("next_attempt_at")):
        return None
    if item.get("lease") and not _expired(item["lease"].get("expires_at")):
        return None
    _assert_owned(repository, job["id"], owner)
    if not completed:
        _assert_authority(job, Subject.from_dict(item["subject"]), repository=repository)
    try:
        expires_at = _active_scan_lease(repository, item)
    except ScreeningConflictError:
        # Let the claimed item record a missing/replaced source explicitly.
        expires_at = None
    try:
        if expires_at is not None:
            _defer_scan_lease(repository, job, item, owner, expires_at)
            return None
        return _replace(
            repository, item, status="running", attempts=int(item.get("attempts", 0)) + int(not completed),
            lease={"owner": owner, "expires_at": (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat()},
            next_attempt_at=None,
            checkpoint={**item.get("checkpoint", {}), "stage": "claimed"},
        )
    except ScreeningConflictError:
        return None


def _publication_matches_document(scan, document):
    marker, publication = document.get(SCREENING_FIELD), scan.get("publication")
    if not isinstance(marker, dict) or not isinstance(publication, dict):
        return False
    active_blob = {
        "container": document.get("blob_container"), "path": document.get("blob_path"),
        "etag": document.get("blob_etag"), "content_hash": document.get("blob_content_hash"),
    }
    return bool(
        scan.get("units_ref")
        and all(isinstance(value, str) and value for value in active_blob.values())
        and scan["units_ref"] == marker.get("canonical_ref")
        and scan.get("content_fingerprint") == marker.get("content_fingerprint") == publication.get("content_fingerprint")
        and scan.get("policy_fingerprint") == marker.get("policy_fingerprint") == hash_payload(scan.get("policy"))
        and publication.get("metadata_fingerprint") == metadata_fingerprint(document)
        and publication.get("active_blob") == marker.get("active_blob") == active_blob
        and bool(scan.get("sanitized")) == bool(marker.get("sanitized"))
    )


def _resumable_publication(repository, job, item, document, scan):
    marker = document.get(SCREENING_FIELD) or {}
    if (
        not scan or scan.get("state") != "publishing" or not item.get("started")
        or scan.get("subject") != item["subject"] or scan.get("id") != item["scan_id"]
        or item.get("job_id") != job["id"] or marker.get("job_id") != job["id"]
        or marker.get("job_item_id") != item["id"] or marker.get("scan_id") != item["scan_id"]
        or marker.get("state") not in AVAILABLE_STATES | {"publishing"}
        or marker.get("state") in AVAILABLE_STATES and marker.get("review_required")
        or str(marker.get("source_revision", "")) != item["subject"]["source_revision"]
        or scan.get("coverage_complete") is not True or scan.get("result_status") not in {"pass", "findings"}
        or not scan.get("content_fingerprint")
        or (item.get("checkpoint") or {}).get("publication_source_fingerprint") != _source_fingerprint(document)
        or not _publication_matches_document(scan, document)
    ):
        return False
    service = importlib.import_module("content_screening.service")
    return hash_payload(service.get_effective_policy(
        Subject.from_dict(item["subject"]), repository=repository,
    )) == scan["policy_fingerprint"]


def _finalize_publishing_scan(repository, scan, *, item=None):
    if scan.get("state") != "publishing" or not _expired((scan.get("lease") or {}).get("expires_at")):
        return None
    service = importlib.import_module("content_screening.service")
    subject = Subject.from_dict(scan["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") == scan["id"] and marker.get("state") in AVAILABLE_STATES:
        if (
            scan.get("coverage_complete") is not True
            or scan.get("result_status") not in {"pass", "findings"}
            or not _publication_matches_document(scan, document)
        ):
            raise ScreeningConflictError(code="screening_publication_incomplete")
        expected_source = ((item or {}).get("checkpoint") or {}).get("publication_source_fingerprint")
        if expected_source is not None and expected_source != _source_fingerprint(document):
            raise ScreeningConflictError(code="screening_source_changed")
        units = normalize_units(service._storage().read_json(scan["units_ref"], subject))
        if content_fingerprint(units) != scan.get("content_fingerprint"):
            raise ScreeningConflictError()
    return service.finalize_publication_checkpoint(scan["id"], repository=repository)


def _hold_document(repository, job, item, owner, *, use_service=False):
    subject = Subject.from_dict(item["subject"])
    for _attempt in range(5):
        _assert_owned(repository, job["id"], owner)
        _assert_authority(job, subject, repository=repository)
        _assert_migration_open()
        expires_at = _active_scan_lease(repository, item)
        if expires_at is not None:
            raise _ScanLeaseBusy(expires_at)
        document = repository.read_document(subject)
        marker = document.get(SCREENING_FIELD, {})
        if (
            not isinstance(marker, dict)
            or SCREENING_FIELD in document and (
                not isinstance(marker.get("state"), str) or marker["state"] not in AVAILABLE_STATES | HELD_STATES
            )
            or marker.get("state") in {"rejected", "deleting", "deleted"}
        ):
            raise ScreeningConflictError(code="screening_source_unavailable")
        if (
            marker.get("scan_id") not in (None, item["scan_id"])
            and marker.get("state") in {"pending_scan", "scanning", "remediating", "publishing"}
        ):
            raise ScreeningConflictError(code="screening_scan_already_running")
        scan = repository.get_scan(item["scan_id"])
        if use_service and scan is None and item.get("started"):
            raise ScreeningConflictError(code="screening_scan_missing")
        if scan is not None and (
            scan.get("subject") != subject.to_dict()
            or scan.get("actor_id") != job["actor_id"]
            or scan.get("state") in {"rejected", "deleting", "deleted"}
        ):
            raise ScreeningConflictError(code="screening_source_unavailable")
        lease = (scan or {}).get("lease") or {}
        if scan and scan.get("state") not in COMPLETED_SCAN_STATES and lease and not _expired(lease.get("expires_at")):
            raise _ScanLeaseBusy(lease["expires_at"])
        if use_service and scan and scan.get("state") == "publishing":
            finalized = _finalize_publishing_scan(repository, scan, item=item)
            if finalized is not None:
                scan = finalized
            else:
                latest_scan = repository.get_scan(scan["id"])
                if latest_scan is None or latest_scan.get("_etag") != scan.get("_etag"):
                    continue
        if scan and scan.get("state") in COMPLETED_SCAN_STATES:
            if _completed_scan(repository, item):
                return item
            raise ScreeningConflictError(code="screening_completion_conflict")
        if scan and marker.get("scan_id") != item["scan_id"] and (
            scan.get("state") != "pending_scan"
            or scan.get("admission_etag") != document["_etag"]
            or scan.get("previous_marker", {}) != marker
        ):
            raise ScreeningConflictError()
        release_needs_recovery = bool(
            scan and scan.get("state") == "publishing" and marker.get("state") in AVAILABLE_STATES
        )
        source_changed = item.get("source_fingerprint") not in (None, _source_fingerprint(document))
        if (release_needs_recovery or source_changed) and not _resumable_publication(
            repository, job, item, document, scan,
        ):
            raise ScreeningConflictError(code="screening_source_changed")
        if use_service and (scan is None or marker.get("scan_id") != item["scan_id"]):
            service = importlib.import_module("content_screening.service")
            service.begin_scan(
                subject, job["actor_id"], repository=repository, job_id=job["id"], scan_id=item["scan_id"],
                expected_document_etag=document["_etag"], parent_scan_id=marker.get("scan_id"),
            )
            continue
        updated = {
            **marker, "schema_version": 1, "source_revision": subject.source_revision,
            "state": "pending_scan", "scan_id": item["scan_id"], "job_id": job["id"], "job_item_id": item["id"],
            "generation": int(marker.get("generation", 0)) + int(
                marker.get("scan_id") != item["scan_id"] or marker.get("state") in AVAILABLE_STATES
            ),
            "updated_at": _timestamp(),
            "review_required": bool(marker.get("review_required") or marker.get("finding_count") or marker.get("state") == "pending_review"),
        }
        try:
            repository.update_document(subject, {SCREENING_FIELD: updated}, etag=document["_etag"])
            current = repository.get(item["id"], job["id"])
            if (current.get("lease") or {}).get("owner") != owner:
                raise ScreeningJobStopped()
            return _replace(
                repository, current, started=True, started_at=current.get("started_at") or _timestamp(),
                checkpoint={**current.get("checkpoint", {}), "stage": "held", "scan_id": item["scan_id"]},
            )
        except ScreeningConflictError:
            continue
    raise ScreeningConflictError()


def _keep_held(repository, item, code):
    subject = Subject.from_dict(item["subject"])
    for _attempt in range(5):
        try:
            document = repository.read_document(subject)
            marker = document.get(SCREENING_FIELD) or {}
            if not isinstance(marker, dict) or marker.get("scan_id") != item["scan_id"]:
                return
            state = marker.get("state")
            if not isinstance(state, str) or state in {"pending_review", "remediating", "rejected", "deleting", "deleted"}:
                return
            repository.update_document(subject, {
                SCREENING_FIELD: {
                    **marker, "state": "incomplete", "error_code": code, "updated_at": _timestamp(),
                    "generation": int(marker.get("generation", 0)) + int(state in AVAILABLE_STATES),
                },
            }, etag=document["_etag"])
            return
        except ScreeningConflictError:
            continue


def _finish_item(repository, job_id, item_id, owner, **updates):
    _assert_owned(repository, job_id, owner, allow_cancel=True)
    checkpoint_stage = updates.pop("checkpoint_stage", updates["status"])
    for _attempt in range(5):
        current = repository.get(item_id, job_id)
        if not current or (current.get("lease") or {}).get("owner") != owner:
            raise ScreeningJobStopped()
        try:
            return _replace(
                repository, current, **updates, lease=None,
                checkpoint={**current.get("checkpoint", {}), "stage": checkpoint_stage},
            )
        except ScreeningConflictError:
            continue
    raise ScreeningJobStopped()


def _default_processor(subject, actor_id, *, job_id, repository, scan_id):
    service = importlib.import_module("content_screening.service")
    existing = repository.get_scan(scan_id)
    if existing and (
        existing.get("subject") != subject.to_dict() or existing.get("actor_id") != actor_id
    ):
        raise ScreeningConflictError()
    if existing and existing.get("state") in COMPLETED_SCAN_STATES:
        if _completed_scan(repository, {"scan_id": scan_id, "subject": subject.to_dict()}):
            return existing
        raise ScreeningConflictError(code="screening_completion_conflict")
    if existing is None:
        service.begin_scan(subject, actor_id, repository=repository, job_id=job_id, scan_id=scan_id)
    return service.scan_existing_document(subject, actor_id, job_id=job_id, repository=repository)


def _completed_scan(repository, item):
    scan = repository.get_scan(item["scan_id"])
    if not scan or scan.get("subject") != item["subject"]:
        return None
    subject = Subject.from_dict(item["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if (
        not isinstance(marker, dict) or marker.get("scan_id") != scan["id"]
        or marker.get("state") != scan.get("state")
        or scan.get("state") not in COMPLETED_SCAN_STATES
        or scan.get("coverage_complete") is not True
        or scan.get("result_status") not in {"pass", "findings"}
        or not scan.get("content_fingerprint")
        or scan["content_fingerprint"] != marker.get("content_fingerprint")
        or scan.get("policy_fingerprint") != marker.get("policy_fingerprint")
        or str(marker.get("source_revision", "")) != subject.source_revision
    ):
        return None
    if scan.get("state") == "pending_review" and marker.get("review_required"):
        return "findings"
    if (
        scan.get("state") in AVAILABLE_STATES and not marker.get("review_required")
        and document_is_available(document) and _publication_matches_document(scan, document)
    ):
        return "findings" if scan.get("finding_count") else "completed"
    return None


def _error_code(exc):
    code = exc.code if isinstance(exc, ScreeningError) else "screening_processing_failed"
    return code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code) else "screening_processing_failed"


def _process_item(repository, job, item, owner, processor, *, completion_only=False):
    subject = Subject.from_dict(item["subject"])
    try:
        completed = _completed_scan(repository, item)
        if completed:
            scan = repository.get_scan(item["scan_id"])
            _finish_item(
                repository, job["id"], item["id"], owner, status=completed, error_code=None,
                finding_count=_safe_count(scan.get("finding_count")), completed_at=_timestamp(),
            )
            return item["scan_id"]
        if completion_only:
            _finish_item(repository, job["id"], item["id"], owner, status="queued", error_code=None)
            return None
        _assert_authority(job, subject, repository=repository)
        _assert_policy_snapshot(job, repository)
        item = _hold_document(repository, job, item, owner, use_service=processor is None)
        context_token = PROCESSOR_CONTEXT.set({"job_id": job["id"], "owner": owner, "repository": repository})
        try:
            with _Heartbeat(repository, job["id"], owner, item["id"]) as heartbeat:
                assert_scan_job_active(job["id"], subject, repository=repository)
                result = (
                    processor(subject, job["actor_id"], job_id=job["id"])
                    if processor is not None
                    else _default_processor(
                        subject, job["actor_id"], job_id=job["id"], repository=repository, scan_id=item["scan_id"],
                    )
                )
                if heartbeat.lost.is_set():
                    raise ScreeningJobStopped()
                assert_scan_job_active(job["id"], subject, repository=repository)
        finally:
            PROCESSOR_CONTEXT.reset(context_token)
        state = result.get("state", result.get("status")) if isinstance(result, dict) else None
        document = repository.read_document(subject)
        marker = document.get(SCREENING_FIELD) or {}
        if marker.get("scan_id") != item["scan_id"]:
            raise ScreeningConflictError()
        if processor is None and state in {"pending_review", "findings", "approved_with_flags", "cleared", "pass", "completed"}:
            if not _completed_scan(repository, item):
                raise ScreeningError(code="screening_incomplete_coverage")
        finding_count = max(
            _safe_count(marker.get("finding_count")),
            _safe_count(result.get("finding_count")) if isinstance(result, dict) else 0,
        )
        if state in {"pending_review", "findings", "approved_with_flags"}:
            if document_is_available(document) and marker.get("state") != "approved_with_flags":
                raise ScreeningError(code="screening_findings_unheld")
            status = "findings"
        elif state in {"cleared", "pass", "completed"}:
            if not document_is_available(document) or marker.get("review_required") or finding_count:
                raise ScreeningError(code="screening_publication_incomplete")
            status = "completed"
        elif state == "incomplete":
            status = "incomplete"
            _keep_held(repository, item, "screening_incomplete")
        else:
            raise ScreeningError(code="screening_processing_failed")
        _finish_item(
            repository, job["id"], item["id"], owner, status=status,
            error_code="screening_incomplete" if status == "incomplete" else None,
            finding_count=finding_count, completed_at=_timestamp(),
        )
        return item["scan_id"] if status in {"completed", "findings"} else None
    except Exception as exc:
        code = _error_code(exc)
        current_job = _assert_owned(repository, job["id"], owner, allow_cancel=True)
        if code == "screening_busy" and not current_job.get("cancel_requested"):
            expires_at = exc.expires_at if isinstance(exc, _ScanLeaseBusy) else _active_scan_lease(repository, item)
            if expires_at is not None:
                _defer_scan_lease(repository, current_job, item, owner, expires_at, claimed=True)
                return
        _keep_held(repository, item, code)
        if current_job.get("cancel_requested") or isinstance(exc, ScreeningJobStopped):
            status = "incomplete"
        elif isinstance(exc, (PermissionError, LookupError)):
            status, code = "incomplete" if item.get("started") else "skipped", "screening_permission_revoked"
        elif isinstance(exc, ScreeningConflictError):
            status = "incomplete" if item.get("started") else "skipped"
        elif code == "screening_table_source_missing":
            status = "incomplete"
        elif int(item.get("attempts", 0)) >= MAX_ATTEMPTS:
            status = "failed"
        else:
            status = "retry"
        _finish_item(
            repository, job["id"], item["id"], owner, status=status, error_code=code,
            next_attempt_at=(_now() + timedelta(seconds=30 * max(1, item.get("attempts", 1)))).isoformat() if status == "retry" else None,
        )
        _log("job_item_incomplete", job_id=job["id"], error_type=type(exc).__name__)


def _reconcile_scan_completion(repository, scan_id):
    """Completion failures must not re-hold a released source or its child scan."""
    try:
        if PROCESSOR_CONTEXT.get() is not None:
            raise ScreeningJobStopped()
        scan = repository.get_scan(scan_id)
        if not scan or scan.get("state") not in COMPLETED_SCAN_STATES or not scan.get("postprocess_pending"):
            return False
        if not _completed_scan(repository, {"scan_id": scan_id, "subject": scan["subject"]}):
            document = repository.read_document(Subject.from_dict(scan["subject"]))
            marker = document.get(SCREENING_FIELD)
            successor = repository.get_scan(marker["scan_id"]) if isinstance(marker, dict) and marker.get("scan_id") else None
            inactive_review = (
                scan["state"] == "pending_review" and isinstance(marker, dict)
                and marker.get("scan_id") and marker["scan_id"] != scan_id
            )
            if not inactive_review and (
                scan["state"] not in AVAILABLE_STATES or not successor
                or successor.get("subject") != scan["subject"] or successor.get("trigger") != "metadata"
                or (successor.get("previous_marker") or {}).get("scan_id") != scan_id
            ):
                return False
            # A crash may leave the completed parent's acknowledgement pending
            # after metadata has already queued a new, independently held scan.
        if repository.count("work_item", filters={
            "scan_id": scan_id, "status": ["queued", "running", "retry"],
        }):
            return False
        service = importlib.import_module("content_screening.service")
        service.reconcile_scan_completion(scan_id, repository=repository)
        return True
    except Exception as exc:
        _log("scan_completion_pending", error_type=type(exc).__name__)
        return False


def _reconcile_finished_scan(repository, scan):
    items = repository.query("work_item", filters={"scan_id": scan["id"]}, page_size=1)
    for item in items["items"]:
        job = _job(repository, item["job_id"])
        if job["status"] in {"queued", "running"}:
            run_scan_job(item["job_id"], repository=repository, completion_only=True)
    _reconcile_scan_completion(repository, scan["id"])


def _save_discovery_cursor(repository, checkpoint_id, checkpoint, continuation):
    try:
        if checkpoint is None:
            repository.create({
                "id": checkpoint_id, "partition_key": checkpoint_id,
                "kind": "checkpoint", "scope_key": "global:system",
                "continuation": continuation,
            })
        else:
            _replace(repository, checkpoint, continuation=continuation)
    except ScreeningConflictError:
        # A competing scheduler can safely replay these idempotent callbacks.
        return


def _finalize_pending_publications_once(repository):
    checkpoint = repository.get(PUBLICATION_DISCOVERY_ID, PUBLICATION_DISCOVERY_ID)
    page = repository.query(
        "scan", filters={"state": "publishing"},
        continuation=(checkpoint or {}).get("continuation"), page_size=MAX_ITEMS_PER_RUN,
    )
    for scan in page["items"]:
        if not _expired((scan.get("lease") or {}).get("expires_at")):
            continue
        try:
            items = repository.query("work_item", filters={"scan_id": scan["id"]}, page_size=1)["items"]
            finalized = _finalize_publishing_scan(repository, scan, item=items[0] if items else None)
            if finalized is not None:
                _reconcile_finished_scan(repository, finalized)
        except Exception as exc:
            _log("scan_publication_pending", error_type=type(exc).__name__)
    _save_discovery_cursor(repository, PUBLICATION_DISCOVERY_ID, checkpoint, page["continuation"])


def _reconcile_pending_scans_once(repository):
    checkpoint = repository.get(COMPLETION_DISCOVERY_ID, COMPLETION_DISCOVERY_ID)
    page = repository.query(
        "scan", filters={"state": sorted(COMPLETED_SCAN_STATES), "postprocess_pending": True},
        continuation=(checkpoint or {}).get("continuation"), page_size=MAX_ITEMS_PER_RUN,
    )
    for scan in page["items"]:
        try:
            _reconcile_finished_scan(repository, scan)
        except Exception as exc:
            _log("scan_completion_pending", error_type=type(exc).__name__)
    _save_discovery_cursor(repository, COMPLETION_DISCOVERY_ID, checkpoint, page["continuation"])


def _safe_count(value):
    return value if type(value) is int and 0 <= value <= 1000000000 else 0


def _counts(repository, job):
    counts = {
        status: repository.count("work_item", filters={"job_id": job["id"], "status": status})
        for status in ITEM_STATUSES
    }
    counts["total"] = sum(counts.values())
    return counts


def _cancel_started_items(repository, job, owner):
    page = repository.query(
        "work_item", filters={"job_id": job["id"]},
        continuation=job.get("cancel_continuation"),
        page_size=ENUMERATION_PAGE_SIZE,
    )
    for item in page["items"]:
        if item["status"] not in {"running", "retry", "queued"}:
            continue
        if item["status"] == "queued" and not item.get("started"):
            continue
        if item.get("lease") and item["lease"].get("owner") != owner and not _expired(item["lease"].get("expires_at")):
            continue
        _assert_owned(repository, job["id"], owner, allow_cancel=True)
        _keep_held(repository, item, "screening_job_cancelled")
        _replace(repository, item, status="incomplete", error_code="screening_job_cancelled", lease=None)
    return _mutate_job(
        repository, job["id"],
        lambda current: {"cancel_continuation": page["continuation"], "cancel_complete": page["continuation"] is None},
        owner=owner,
    )


def _final_status(job, counts):
    if job.get("cancel_requested"):
        return "cancelled" if job.get("cancel_complete") else "queued"
    if job.get("reset_pending") or not job["enumeration"]["complete"] or any(counts[key] for key in ("queued", "running", "retry")):
        return "queued"
    if counts["failed"] and not any(counts[key] for key in ("completed", "findings", "incomplete", "skipped")):
        return "failed"
    if counts["failed"] or counts["incomplete"] or counts["skipped"]:
        return "incomplete"
    return "completed_with_findings" if counts["findings"] else "completed"


def _process_pending_items(repository, job, owner, processor, *, can_scan):
    processed, continuation = 0, job.get("work_continuation")
    for _page_index in range(MAX_DISCOVERY_PAGES):
        page = repository.query(
            "work_item", filters={"job_id": job["id"], "status": ["queued", "running", "retry"]},
            continuation=continuation, page_size=ENUMERATION_PAGE_SIZE,
        )
        stopped = False
        for index, candidate in enumerate(page["items"]):
            job = _assert_owned(repository, job["id"], owner)
            try:
                completed = bool(_completed_scan(repository, candidate))
            except ScreeningConflictError:
                completed = False
            if not can_scan and not completed:
                continue
            item = _claim_item(repository, job, candidate, owner, completed=completed)
            if item is None:
                continue
            scan_id = _process_item(
                repository, job, item, owner, processor, completion_only=not can_scan,
            )
            if scan_id:
                _reconcile_scan_completion(repository, scan_id)
            processed += 1
            job = _heartbeat(repository, job["id"], owner)
            if job.get("cancel_requested") or processed >= MAX_ITEMS_PER_RUN:
                stopped = True
                if index == len(page["items"]) - 1:
                    continuation = page["continuation"]
                break
        if not stopped:
            continuation = page["continuation"]
        job = _mutate_job(
            repository, job["id"], lambda current: {"work_continuation": continuation}, owner=owner,
        )
        if stopped or continuation is None:
            break
    return job


def run_scan_job(job_id, *, processor=None, repository=None, completion_only=False):
    repository = _repo(repository)
    job = _job(repository, job_id)
    can_scan = not completion_only and (processor is not None or _screening_enabled())
    claimed = _claim_job(repository, job)
    if claimed is None:
        return _job(repository, job_id)
    job, owner = claimed
    error_code = None
    try:
        _assert_migration_open()
        if job.get("cancel_requested"):
            job = _cancel_started_items(repository, job, owner)
        else:
            if can_scan:
                _assert_authority(job, repository=repository)
                _assert_policy_snapshot(job, repository)
                job = _reset_items(repository, job, owner)
            if not job.get("reset_pending"):
                if can_scan:
                    job = _enumerate(repository, job, owner)
                job = _process_pending_items(repository, job, owner, processor, can_scan=can_scan)
    except Exception as exc:
        error_code = _error_code(exc)
        _log("job_slice_stopped", job_id=job_id, error_type=type(exc).__name__)
    try:
        job = _assert_owned(repository, job_id, owner, allow_cancel=True)
        if job.get("cancel_requested") and not job.get("cancel_complete"):
            job = _cancel_started_items(repository, job, owner)
        counts = _counts(repository, job)
        status = _final_status(job, counts)
        if error_code and not job.get("cancel_requested"):
            status = "queued" if error_code == "screening_migration_frozen" else "incomplete"
        result = _mutate_job(
            repository, job_id,
            lambda current: {
                "counts": counts,
                "status": ("cancelled" if current.get("cancel_complete") else "queued") if current.get("cancel_requested") else status,
                "lease": None, "error_code": error_code, "heartbeat_at": _timestamp(),
            },
            owner=owner,
        )
        _release_admission(repository, job_id, owner)
        return result
    except ScreeningJobStopped:
        return _job(repository, job_id)


def check_due_scan_jobs_once(*, repository=None, max_jobs=2):
    """Discover queued/stale jobs across pages without loading their item arrays."""
    repository = _repo(repository)
    if type(max_jobs) is not int or not 1 <= max_jobs <= 10:
        raise ScreeningValidationError("The scheduler batch size is invalid.")
    _assert_migration_open()
    _finalize_pending_publications_once(repository)
    _reconcile_pending_scans_once(repository)
    can_scan = _screening_enabled()
    processed, continuation = [], None
    for _page_index in range(MAX_DISCOVERY_PAGES):
        page = repository.query(
            "job", filters={"status": ["queued", "running"]}, continuation=continuation,
            page_size=ENUMERATION_PAGE_SIZE,
        )
        for job in page["items"]:
            if not can_scan and not job.get("cancel_requested"):
                continue
            if job.get("lease") and not _expired(job["lease"].get("expires_at")):
                continue
            run_scan_job(job["id"], repository=repository)
            processed.append(job["id"])
            if len(processed) >= max_jobs:
                return processed
        continuation = page["continuation"]
        if continuation is None:
            break
    return processed
