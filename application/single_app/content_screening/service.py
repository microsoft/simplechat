# service.py
"""Revision-bound orchestration for private extraction, inspection, and release.

Application clients and document processors are resolved at the operation boundary
so importing the reusable framework does not initialize Flask or Azure resources.
"""

import json
import logging
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core.exceptions import AzureError

from content_screening.contracts import (
    AVAILABLE_STATES,
    SCREENING_FIELD,
    ContentUnit,
    DocumentHeldError,
    Finding,
    InspectionResult,
    ScreeningChecksRequiredError,
    ScreeningCitationsRequiredError,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningPolicyRequiredError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    hash_payload,
    metadata_fingerprint,
    normalize_units,
    subject_from_document,
)
from content_screening.extraction import (
    CONTENT_METADATA_FIELDS,
    TABLE_EXTENSIONS,
    ExtractionCapture,
    capture_extraction,
    capture_table_source,
    publication_context,
)
from content_screening.policies import compose_policy, default_policy, policy_is_active


LEASE_SECONDS = 1800
TERMINAL_SCAN_STATES = frozenset({"cleared", "approved_with_flags", "rejected", "deleted"})


def _now():
    return datetime.now(timezone.utc)


def _timestamp():
    return _now().isoformat()


def _repository(repository=None):
    if repository is not None:
        return repository
    # Resolve configured infrastructure only for an application operation.
    from content_screening.repository import get_repository

    return get_repository()


def _storage(storage=None):
    if storage is not None:
        return storage
    from content_screening.storage import ScreeningStorage

    return ScreeningStorage()


def _settings(settings=None):
    if settings is not None:
        return settings
    from functions_settings import get_settings

    return get_settings()


def _log(code, *, document_id=None, scan_id=None, error_type=None, level=logging.INFO):
    from functions_appinsights import log_event

    log_event(
        f"[CONTENT_SCREENING] {code}",
        extra={"document_id": document_id, "scan_id": scan_id, "error_type": error_type},
        level=level,
    )


def _read_scan(repository, scan_id):
    scan = repository.get_scan(scan_id)
    if not scan:
        raise ScreeningValidationError("The content scan was not found.", code="screening_not_found")
    return scan


def _save_scan(repository, scan, **updates):
    if not scan.get("_etag"):
        raise ScreeningConflictError()
    return repository.replace({**scan, **updates, "updated_at": _timestamp()}, scan["_etag"])


def initialize_screening_policy(*, repository=None):
    """Create the first empty baseline without overwriting a concurrent policy."""
    repository = _repository(repository)
    baseline = repository.get_policy("global", "global")
    if baseline is not None:
        return baseline
    policy = {**default_policy(), "enabled": True}
    try:
        return repository.save_policy("global", "global", policy, "system-content-screening")
    except ScreeningConflictError:
        baseline = repository.get_policy("global", "global")
        if baseline is None:
            raise
        return baseline


def get_effective_policy(subject, *, repository=None, require_active=True):
    repository = _repository(repository)
    baseline = repository.get_policy("global", "global")
    if baseline is None:
        raise ScreeningPolicyRequiredError()
    workspace = repository.get_policy(subject.scope_type, subject.scope_id)
    policy = compose_policy(
        baseline["policy"],
        workspace["policy"] if workspace else None,
    )
    if require_active and not policy_is_active(policy):
        raise ScreeningChecksRequiredError()
    return policy


def document_requires_screening(document, settings=None, *, repository=None):
    """Persisted enrollment always wins over the absence of checks for new uploads."""
    if not isinstance(document, dict):
        raise ScreeningValidationError("The document metadata is unavailable.")
    if SCREENING_FIELD in document:
        return True
    if _settings(settings).get("enable_content_screening") is not True:
        return False
    return policy_is_active(get_effective_policy(
        subject_from_document(document), repository=repository, require_active=False,
    ))


def validate_screening_configuration(settings=None, *, repository=None, check_storage=False,
                                     proposed_settings=False, allow_missing_policy=False):
    settings = _settings(settings)
    if settings.get("enable_content_screening") is not True:
        return
    if settings.get("enable_enhanced_citations") is not True:
        raise ScreeningCitationsRequiredError()

    repository = _repository(repository)
    baseline = repository.get_policy("global", "global")
    if baseline is None and not allow_missing_policy:
        raise ScreeningPolicyRequiredError()
    # Settings preflight may precede first activation; the write initializes the policy.
    effective = compose_policy(baseline["policy"] if baseline else default_policy())
    if effective.get("ai_checks"):
        from content_screening.model import validate_model_bindings

        validate_model_bindings(effective, settings=settings if proposed_settings is True else None)
    if check_storage:
        from config import build_enhanced_citations_blob_service_client
        from content_screening.storage import ScreeningStorage

        storage = ScreeningStorage(client=build_enhanced_citations_blob_service_client(settings))
        storage.validate_connection()


def initial_document_marker(document, settings=None):
    if not document_requires_screening(document, settings):
        return None
    subject = subject_from_document(document)
    return {
        "schema_version": 1, "state": "pending_scan", "source_revision": subject.source_revision,
        "scan_id": uuid.uuid4().hex, "content_fingerprint": None,
        "finding_count": 0, "review_required": False, "generation": 1,
        "origin_upload": True,
        "updated_at": _timestamp(),
    }


def _marker_for_scan(document, scan, state, **extra):
    previous = document.get(SCREENING_FIELD, {})
    if not isinstance(previous, dict):
        raise ScreeningConflictError()
    return {
        **previous,
        "schema_version": 1,
        "state": state,
        "source_revision": scan["subject"]["source_revision"],
        "scan_id": scan["id"],
        "content_fingerprint": scan.get("content_fingerprint"),
        "policy_fingerprint": scan["policy_fingerprint"],
        "review_required": bool(scan.get("review_required") or previous.get("review_required")),
        "review_id": scan["id"] if scan.get("review_required") or previous.get("review_required") else None,
        "finding_count": scan.get("finding_count", 0),
        "updated_at": _timestamp(),
        **extra,
    }


def _set_document_state(repository, scan, state, **updates):
    subject = Subject.from_dict(scan["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD)
    if not isinstance(marker, dict) or marker.get("scan_id") != scan["id"]:
        raise ScreeningConflictError()
    if marker.get("state") in {"deleting", "deleted", "rejected"} and state != marker["state"]:
        raise ScreeningConflictError("The document can no longer transition through this scan.")
    return repository.update_document(
        subject,
        {**updates, SCREENING_FIELD: _marker_for_scan(document, scan, state)},
        etag=document["_etag"],
    )


def begin_scan(subject, actor_id, *, repository=None, storage=None, job_id=None, scan_id=None,
               expected_document_etag=None, parent_scan_id=None):
    repository = _repository(repository)
    document = repository.read_document(subject)
    settings = _settings()
    if settings.get("enable_content_screening") is not True:
        raise ScreeningConfigurationError("Enable content screening before rescanning inspected content.")
    validate_screening_configuration(settings, repository=repository)
    policy = get_effective_policy(subject, repository=repository)
    marker = document.get(SCREENING_FIELD, {})
    if not isinstance(marker, dict):
        raise ScreeningConflictError()
    if marker.get("state") in {"deleting", "deleted", "rejected"}:
        raise DocumentHeldError("This document is no longer eligible for scanning.")
    if expected_document_etag is not None and (
        document.get("_etag") != expected_document_etag or marker.get("scan_id") != parent_scan_id
    ):
        raise ScreeningConflictError()
    scan_id = scan_id or uuid.uuid4().hex
    existing = repository.get_scan(scan_id)
    if existing:
        if (
            existing.get("subject") != subject.to_dict()
            or existing.get("actor_id") != actor_id
            or existing.get("policy_fingerprint") != hash_payload(policy)
        ):
            raise ScreeningConflictError()
        if marker.get("scan_id") == scan_id:
            return existing
        if (
            existing.get("state") != "pending_scan"
            or existing.get("admission_etag") != document.get("_etag")
            or existing.get("previous_marker", {}) != marker
        ):
            raise ScreeningConflictError()
        repository.update_document(subject, {
            SCREENING_FIELD: _marker_for_scan(
                document, existing, "pending_scan",
                generation=int(marker.get("generation", 0)) + 1,
            ),
            "status": "Content screening pending", "percentage_complete": 0,
        }, etag=document["_etag"])
        return existing

    scan = repository.create({
        "id": scan_id, "partition_key": scan_id, "kind": "scan",
        "scope_key": subject.scope_key, "scope_type": subject.scope_type,
        "scope_id": subject.scope_id, "document_id": subject.document_id,
        "subject": subject.to_dict(), "actor_id": actor_id, "job_id": job_id,
        "state": "pending_scan", "policy": policy, "policy_fingerprint": hash_payload(policy),
        "review_required": bool(
            marker.get("review_required") or marker.get("finding_count")
            or marker.get("state") in {"pending_review", "remediating"}
        ),
        "finding_count": marker.get("finding_count", 0),
        "metadata_generated": bool(marker.get("metadata_generated")),
        "trigger": "rescan",
        "content_fingerprint": None,
        "units_ref": None, "result_ref": None, "source_ref": None,
        "original_file_name": document.get("file_name") or "document",
        "previous_marker": marker,
        "admission_etag": document["_etag"],
        "previous_blob": {
            "container": document.get("blob_container"),
            "path": document.get("archived_blob_path") if document.get("is_current_version") is False else document.get("blob_path"),
        },
        "created_at": _timestamp(), "updated_at": _timestamp(),
    })
    repository.update_document(
        subject,
        {
            SCREENING_FIELD: _marker_for_scan(
                document, scan, "pending_scan",
                generation=int(marker.get("generation", 0)) + 1,
            ),
            "status": "Content screening pending", "percentage_complete": 0,
        },
        etag=document["_etag"],
    )
    if document.get("num_chunks") or document.get("number_of_pages"):
        from functions_documents import set_document_chunk_visibility

        set_document_chunk_visibility(document, active=False)
    _log("scan_held", document_id=subject.document_id, scan_id=scan_id)
    return scan


def _claim_scan(repository, scan):
    lease = scan.get("lease") or {}
    if not isinstance(lease, dict):
        raise ScreeningConflictError()
    if lease.get("expires_at"):
        try:
            expires = datetime.fromisoformat(lease["expires_at"])
        except (TypeError, ValueError) as error:
            raise ScreeningConflictError() from error
        if expires.tzinfo is None:
            raise ScreeningConflictError()
        if expires > _now():
            raise ScreeningConflictError("This document is already being inspected.", code="screening_busy")
    owner = uuid.uuid4().hex
    scan = _save_scan(repository, scan, lease={
        "owner": owner, "expires_at": (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
    })
    return scan, owner


def _renew_scan(repository, scan_id, owner):
    scan = _read_scan(repository, scan_id)
    if (scan.get("lease") or {}).get("owner") != owner:
        raise ScreeningConflictError()
    return _save_scan(repository, scan, lease={
        "owner": owner, "expires_at": (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
    })


def _release_lease(repository, scan_id, owner):
    scan = _read_scan(repository, scan_id)
    if (scan.get("lease") or {}).get("owner") == owner:
        return _save_scan(repository, scan, lease=None)
    raise ScreeningConflictError()


def _record_failure(repository, scan_id, code, *, owner=None, retry_publication=False):
    scan = _read_scan(repository, scan_id)
    if (
        scan.get("state") in TERMINAL_SCAN_STATES | {"deleting"}
        or owner is not None and (scan.get("lease") or {}).get("owner") != owner
    ):
        _log("stale_failure_ignored", scan_id=scan_id, error_type=code, level=logging.WARNING)
        return scan
    subject = Subject.from_dict(scan["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") != scan_id or marker.get("state") in {"deleting", "deleted", "rejected"}:
        _log("superseded_failure_ignored", scan_id=scan_id, error_type=code, level=logging.WARNING)
        return scan
    state = "publishing" if retry_publication else "scan_error"
    lease = (
        {"owner": owner, "expires_at": (_now() - timedelta(seconds=1)).isoformat()}
        if retry_publication else None
    )
    scan = _save_scan(repository, scan, state=state, error_code=code, lease=lease)
    _set_document_state(
        repository, scan, state,
        status="Reviewed content publication needs a retry" if retry_publication else "Content screening failed; retry is required",
    )
    _log("scan_failed", scan_id=scan_id, document_id=scan["document_id"], error_type=code, level=logging.ERROR)
    return scan


def _job_progress(repository, subject, checkpoint=None):
    from content_screening.jobs import (
        PROCESSOR_CONTEXT,
        ScreeningJobStopped,
        assert_scan_job_active,
        checkpoint_scan_job_item,
    )

    context = PROCESSOR_CONTEXT.get()
    if context is None:
        return True
    try:
        assert_scan_job_active(context["job_id"], subject, repository=repository)
        if checkpoint is not None:
            checkpoint_scan_job_item(context["job_id"], subject, checkpoint, repository=repository)
    except ScreeningJobStopped:
        return False
    return True


def _document_for_upload(document_id, user_id, group_id=None, public_workspace_id=None):
    # Document creation/authentication belongs to the existing intake route.
    from functions_documents import get_document_metadata

    document = get_document_metadata(document_id, user_id, group_id, public_workspace_id)
    if not document:
        raise ScreeningValidationError("The document was not found.")
    return document


def prepare_document_upload(document_id, user_id, temp_file_path, original_filename, group_id=None, public_workspace_id=None,
                            extraction_mode_override=None):
    settings = _settings()
    document = _document_for_upload(document_id, user_id, group_id, public_workspace_id)
    if not document_requires_screening(document, settings):
        return None
    if settings.get("enable_content_screening") is not True:
        raise DocumentHeldError("Enable content screening before replacing inspected content.")
    repository, storage = _repository(), _storage()
    subject = subject_from_document(document)
    marker = document.get(SCREENING_FIELD, {})
    scan_id = marker.get("scan_id") if marker.get("state") == "pending_scan" else None
    scan = begin_scan(subject, user_id, repository=repository, scan_id=scan_id)
    if not scan.get("source_ref"):
        source_ref = storage.write_source(subject, scan["id"], temp_file_path, original_filename)
        scan = _save_scan(
            repository, scan, source_ref=source_ref, original_file_name=original_filename, trigger="upload",
            extraction_mode_override=extraction_mode_override,
        )
    from content_screening.jobs import enqueue_document_scan

    enqueue_document_scan(subject, user_id, scan_id=scan["id"], repository=repository)
    return scan


def process_screened_upload(document_id, user_id, temp_file_path, original_filename, processor, group_id=None, public_workspace_id=None, extraction_mode_override=None):
    repository, storage = _repository(), _storage()
    document = _document_for_upload(document_id, user_id, group_id, public_workspace_id)
    marker = document.get(SCREENING_FIELD) or {}
    scan = repository.get_scan(marker["scan_id"]) if marker.get("scan_id") else None
    if not scan or not scan.get("source_ref"):
        scan = prepare_document_upload(
            document_id, user_id, temp_file_path, original_filename, group_id, public_workspace_id,
        )
    if scan is None:
        raise ScreeningConfigurationError()
    try:
        subject = Subject.from_dict(scan["subject"])
        from content_screening.jobs import enqueue_document_scan, run_scan_job

        if extraction_mode_override and scan.get("extraction_mode_override") != extraction_mode_override:
            scan = _save_scan(repository, scan, extraction_mode_override=extraction_mode_override)
        job = enqueue_document_scan(subject, user_id, scan_id=scan["id"], repository=repository)
        run_scan_job(job["id"], repository=repository)
        return _read_scan(repository, scan["id"])
    finally:
        if temp_file_path:
            Path(temp_file_path).unlink(missing_ok=True)


def _extract_and_inspect(scan, actor_id, source_path, processor, *, repository, storage, extraction_mode_override=None):
    subject = Subject.from_dict(scan["subject"])
    scan, owner = _claim_scan(repository, _read_scan(repository, scan["id"]))
    capture = ExtractionCapture(subject, scan["id"], scan["original_file_name"])
    last_heartbeat = _now()

    def heartbeat():
        nonlocal last_heartbeat
        if not _job_progress(repository, subject):
            capture.failure_code = "screening_cancelled"
            raise ScreeningError(code="screening_cancelled")
        if (_now() - last_heartbeat).total_seconds() >= 30:
            _renew_scan(repository, scan["id"], owner)
            last_heartbeat = _now()

    capture.heartbeat = heartbeat
    try:
        scan = _save_scan(repository, scan, state="extracting")
        _set_document_state(repository, scan, "pending_scan", status="Extracting private content for screening")
        if Path(source_path).suffix.lower() in TABLE_EXTENSIONS:
            capture_table_source(capture, source_path)
        elif Path(source_path).suffix.lower() in {".txt", ".md", ".log", ".xml", ".yaml", ".yml", ".json"}:
            text = Path(source_path).read_text(encoding="utf-8-sig")
            if Path(source_path).suffix.lower() == ".json":
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            capture.add_text(text)
            capture.preloaded_text = True
        with capture_extraction(capture):
            processor(
                document_id=subject.document_id,
                user_id=subject.scope_id if subject.scope_type == "personal" else actor_id,
                temp_file_path=str(source_path), original_filename=scan["original_file_name"],
                group_id=subject.scope_id if subject.scope_type == "group" else None,
                public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
                extraction_mode_override=extraction_mode_override,
            )
        units = capture.finish(repository.read_document(subject))
        _release_lease(repository, scan["id"], owner)
        return inspect_scan(
            scan["id"], units, actor_id, repository=repository, storage=storage,
        )
    except ScreeningError as error:
        _record_failure(repository, scan["id"], error.code, owner=owner)
        raise
    except (AzureError, OSError, UnicodeError, ValueError) as error:
        _record_failure(repository, scan["id"], "screening_extraction_failed", owner=owner)
        raise ScreeningError(code="screening_extraction_failed") from error


def _validate_result(result, units, policy):
    if not isinstance(result, InspectionResult):
        raise ScreeningError(code="screening_invalid_result")
    if result.content_fingerprint != content_fingerprint(units) or result.policy_fingerprint != hash_payload(policy):
        raise ScreeningConflictError()
    if result.status not in {"pass", "findings", "incomplete", "error"}:
        raise ScreeningError(code="screening_invalid_result")
    if result.status == "pass" and result.findings:
        raise ScreeningError(code="screening_invalid_result")
    if result.units_total != len(units) or not result.detectors:
        raise ScreeningError(code="screening_incomplete_coverage")
    if result.status in {"pass", "findings"}:
        for detector in result.detectors:
            if (
                detector.get("status") not in {"pass", "findings"}
                or detector.get("error_code")
                or detector.get("required_units", 0) <= 0
                or detector.get("completed_units") != detector.get("required_units")
                or detector.get("completed_windows") != detector.get("required_windows")
            ):
                raise ScreeningError(code="screening_incomplete_coverage")


def inspect_scan(scan_id, units, actor_id, *, repository=None, storage=None, engine=None, publish=True):
    repository, storage = _repository(repository), _storage(storage)
    units = normalize_units(units)
    scan = _read_scan(repository, scan_id)
    subject = Subject.from_dict(scan["subject"])
    fingerprint = content_fingerprint(units)
    if scan.get("content_fingerprint") not in (None, fingerprint):
        raise ScreeningConflictError("A source change requires a new scan.")
    previous = scan
    if not previous.get("result_ref"):
        previous_id = scan.get("parent_scan_id") or (scan.get("previous_marker") or {}).get("scan_id")
        previous = repository.get_scan(previous_id) if previous_id else None
    previous_units = None
    previous_result = None
    if previous and previous.get("units_ref") and previous.get("result_ref"):
        previous_units = {
            unit.unit_id: unit.to_dict()
            for unit in normalize_units(storage.read_json(previous["units_ref"], subject))
        }
        previous_result = storage.read_json(previous["result_ref"], subject)
    scan, owner = _claim_scan(repository, scan)
    try:
        units_ref = storage.write_json(subject, scan_id, f"units-{content_fingerprint(units)}", [
            unit.to_dict() for unit in units
        ])
        scan = _save_scan(
            repository, scan, state="scanning", units_ref=units_ref,
            content_fingerprint=content_fingerprint(units), units_total=len(units), error_code=None,
            coverage_complete=False, result_status=None,
        )
        _set_document_state(repository, scan, "scanning", status="Scanning extracted content")
        default_engine = engine is None
        if default_engine:
            from content_screening.engine import inspect_content

            engine = inspect_content
        last_heartbeat = _now()

        def progress(event):
            nonlocal last_heartbeat
            if not _job_progress(repository, subject):
                return False
            if (_now() - last_heartbeat).total_seconds() >= 30:
                _renew_scan(repository, scan_id, owner)
                checkpoint = {
                    "stage": "scanning", "content_fingerprint": content_fingerprint(units),
                    "policy_fingerprint": scan["policy_fingerprint"],
                }
                if isinstance(event, dict):
                    for source, target in (
                        ("required_units", "units_total"), ("completed_units", "units_completed"),
                        ("required_windows", "windows_total"), ("completed_windows", "windows_completed"),
                    ):
                        if type(event.get(source)) is int and event[source] >= 0:
                            checkpoint[target] = event[source]
                if not _job_progress(repository, subject, checkpoint):
                    return False
                last_heartbeat = _now()
            return True

        engine_options = {"on_progress": progress}
        if default_engine and scan["policy"].get("ai_checks"):
            from content_screening.checkpoints import ModelWindowCheckpoints
            from content_screening.model import evaluate_model_units

            def evaluate_checkpointed_model(content_units, check, *, on_progress=None):
                checkpoints = ModelWindowCheckpoints(
                    subject, scan_id, check, owner, repository=repository, storage=storage,
                )
                return evaluate_model_units(
                    content_units, check, on_progress=on_progress, checkpoint_store=checkpoints,
                )

            engine_options["model_evaluator"] = evaluate_checkpointed_model
        result = engine(subject, units, scan["policy"], **engine_options)
        _validate_result(result, units, scan["policy"])
        if previous_result and previous_units and scan.get("review_required"):
            current_units = {unit.unit_id: unit.to_dict() for unit in units}
            finding_ids = {finding.finding_id for finding in result.findings}
            for raw_finding in previous_result.get("findings", []):
                unit_id = raw_finding.get("unit_id")
                if current_units.get(unit_id) != previous_units.get(unit_id):
                    continue
                finding = Finding(**{
                    key: value for key, value in raw_finding.items()
                    if key in Finding.__dataclass_fields__
                })
                if finding.finding_id not in finding_ids:
                    result.findings.append(finding)
                    finding_ids.add(finding.finding_id)
            if result.findings and result.status == "pass":
                result.status = "findings"
        result_payload = result.to_dict()
        result_ref = storage.write_json(
            subject, scan_id, f"inspection-result-{hash_payload(result_payload)}", result_payload,
        )
        scan = _read_scan(repository, scan_id)
        if (scan.get("lease") or {}).get("owner") != owner:
            raise ScreeningConflictError()
        has_findings = bool(result.findings)
        current_document = repository.read_document(subject)
        current_marker = current_document.get(SCREENING_FIELD) or {}
        if current_marker.get("scan_id") != scan_id:
            raise ScreeningConflictError()
        review_required = bool(
            scan.get("review_required") or current_marker.get("review_required") or has_findings or not publish
        )
        state = (
            "scan_error" if result.status == "error" else
            "incomplete" if result.status == "incomplete" else
            "pending_review" if review_required else "ready_to_publish"
        )
        scan = _save_scan(
            repository, scan, state=state, result_ref=result_ref,
            result_status=result.status,
            coverage_complete=result.status in {"pass", "findings"},
            finding_count=len(result.findings),
            review_required=review_required,
            error_code=result.error_code,
            usage=result.usage,
            postprocess_pending=review_required,
            lease=None,
        )
        if state in {"scan_error", "incomplete"}:
            _set_document_state(repository, scan, state, status="Content screening incomplete; retry is required")
            return scan
        if review_required:
            _set_document_state(repository, scan, "pending_review", status="Content review required")
            from content_screening.reviews import ensure_review

            ensure_review(scan, actor_id, repository=repository)
            return _read_scan(repository, scan_id)
        return publish_scan(scan_id, actor_id, repository=repository, storage=storage)
    except ScreeningError as error:
        _record_failure(repository, scan_id, error.code, owner=owner)
        raise
    except (AzureError, OSError) as error:
        _record_failure(repository, scan_id, "screening_storage_failed", owner=owner)
        raise ScreeningError(code="screening_storage_failed") from error


def _validate_release(scan, actor_id, repository):
    scan_id = scan["id"]
    subject = Subject.from_dict(scan["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") != scan_id:
        raise ScreeningConflictError()
    if (
        scan.get("state") not in {"ready_to_publish", "pending_review", "publishing"}
        or not scan.get("coverage_complete")
        or scan.get("result_status") not in {"pass", "findings"}
    ):
        raise DocumentHeldError()
    current_policy = get_effective_policy(subject, repository=repository)
    if (
        hash_payload(current_policy) != scan["policy_fingerprint"]
        or hash_payload(scan["policy"]) != scan["policy_fingerprint"]
    ):
        raise ScreeningConflictError("The screening policy changed. Rescan before approval.")
    decision = scan.get("review_decision") or {}
    if (
        decision or scan.get("review_required") or marker.get("review_required")
        or scan.get("finding_count") or scan.get("state") == "pending_review"
    ):
        if (
            decision.get("action") not in {"approve_with_flags", "approve_clean"}
            or decision.get("actor_id") != actor_id
            or decision.get("content_fingerprint") != scan.get("content_fingerprint")
            or decision.get("policy_fingerprint") != scan["policy_fingerprint"]
            or decision.get("policy_snapshot_hash") != hash_payload(scan["policy"])
            or decision.get("scan_id") != scan_id
            or decision.get("source_revision") != subject.source_revision
            or not str(decision.get("reason", "")).strip()
            or not decision.get("decided_at")
            or decision.get("action") == "approve_with_flags" and decision.get("acknowledged_flags") is not True
        ):
            raise DocumentHeldError()
        if decision["action"] == "approve_clean" and scan.get("finding_count"):
            raise DocumentHeldError("Resolve the remaining findings or approve with flags.")
        from content_screening.permissions import assert_subject_access

        assert_subject_access(subject, actor_id, repository=repository, review=True)
    return decision


def finalize_publication_checkpoint(scan_id, *, repository=None):
    """Finish only a proven release whose final document write already committed."""
    repository = _repository(repository)
    scan = _read_scan(repository, scan_id)
    if scan.get("state") != "publishing":
        return None
    lease = scan.get("lease") or {}
    try:
        expires = datetime.fromisoformat(lease["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires.tzinfo is None or expires > _now():
        return None
    subject = Subject.from_dict(scan["subject"])
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") != scan_id or marker.get("state") not in AVAILABLE_STATES:
        return None
    actor_id = (scan.get("review_decision") or {}).get("actor_id") or scan["actor_id"]
    decision = _validate_release(scan, actor_id, repository)
    publication = scan.get("publication")
    expected_state = "approved_with_flags" if decision.get("action") == "approve_with_flags" or scan.get("finding_count") else "cleared"
    if (
        not isinstance(publication, dict) or marker.get("state") != expected_state
        or marker.get("review_required") is True
        or marker.get("source_revision") != subject.source_revision
        or marker.get("content_fingerprint") != scan.get("content_fingerprint")
        or marker.get("policy_fingerprint") != scan.get("policy_fingerprint")
        or marker.get("canonical_ref") != scan.get("units_ref")
        or marker.get("active_blob") != publication.get("active_blob")
        or publication.get("content_fingerprint") != scan.get("content_fingerprint")
        or publication.get("metadata_fingerprint") != metadata_fingerprint(document)
    ):
        raise ScreeningConflictError()
    job_id = marker.get("job_id") or scan.get("job_id")
    if job_id and not decision:
        job = repository.get(job_id, job_id)
        if not job or job.get("cancel_requested") or job.get("status") == "cancelled":
            raise ScreeningConflictError("The scan job was cancelled before release completed.")
    scan, owner = _claim_scan(repository, scan)
    scan = _save_scan(
        repository, scan, state=expected_state, lease=None,
        published_at=scan.get("published_at") or _timestamp(), postprocess_pending=True,
    )
    current = repository.read_document(subject)
    if current.get(SCREENING_FIELD) != marker or metadata_fingerprint(current) != publication["metadata_fingerprint"]:
        raise ScreeningConflictError()
    _log("publication_checkpoint_finalized", scan_id=scan_id, document_id=subject.document_id)
    return scan


def publish_scan(scan_id, actor_id, *, repository=None, storage=None, publisher=None):
    repository, storage = _repository(repository), _storage(storage)
    scan = _read_scan(repository, scan_id)
    subject = Subject.from_dict(scan["subject"])
    if scan["state"] in AVAILABLE_STATES:
        document = repository.read_document(subject)
        if (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan_id:
            raise ScreeningConflictError()
        return scan
    decision = _validate_release(scan, actor_id, repository)
    units = normalize_units(storage.read_json(scan["units_ref"], subject))
    if content_fingerprint(units) != scan["content_fingerprint"]:
        raise ScreeningConflictError()
    scan, owner = _claim_scan(repository, scan)
    try:
        scan = _save_scan(repository, scan, state="publishing")
        document = _set_document_state(repository, scan, "publishing", status="Publishing reviewed content")
        publication_generation = document[SCREENING_FIELD].get("generation")
        if publisher is None:
            from functions_documents import _publish_screened_document

            publisher = _publish_screened_document
        last_heartbeat = _now()

        def heartbeat():
            nonlocal last_heartbeat
            if not _job_progress(repository, subject):
                raise ScreeningError(code="screening_cancelled")
            if (_now() - last_heartbeat).total_seconds() >= 30:
                _renew_scan(repository, scan_id, owner)
                last_heartbeat = _now()

        with publication_context(subject, scan_id, heartbeat):
            updates = publisher(document, units, scan, actor_id, storage=storage)
        current = repository.read_document(subject)
        current_marker = current.get(SCREENING_FIELD) or {}
        latest_scan = _read_scan(repository, scan_id)
        try:
            lease_expiration = datetime.fromisoformat((latest_scan.get("lease") or {})["expires_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise ScreeningConflictError() from error
        if (
            current_marker.get("scan_id") != scan_id
            or current_marker.get("state") != "publishing"
            or current_marker.get("generation") != publication_generation
            or current_marker.get("content_fingerprint") != scan["content_fingerprint"]
            or (latest_scan.get("lease") or {}).get("owner") != owner
            or latest_scan.get("state") != "publishing"
            or lease_expiration.tzinfo is None or lease_expiration <= _now()
            or hash_payload(get_effective_policy(subject, repository=repository)) != scan["policy_fingerprint"]
        ):
            raise ScreeningConflictError()
        if decision:
            if latest_scan.get("review_decision") != decision:
                raise ScreeningConflictError()
            _validate_release(latest_scan, actor_id, repository)
        if not _job_progress(repository, subject):
            raise ScreeningError(code="screening_cancelled")
        state = "approved_with_flags" if decision.get("action") == "approve_with_flags" or scan.get("finding_count") else "cleared"
        marker = _marker_for_scan(
            current, scan, state,
            review_required=False,
            canonical_ref=scan["units_ref"],
            sanitized=bool(scan.get("sanitized")),
            active_blob={
                "container": updates.get("blob_container"), "path": updates.get("blob_path"),
                "etag": updates.get("blob_etag"), "content_hash": updates.get("blob_content_hash"),
            },
        )
        latest_scan = _read_scan(repository, scan_id)
        scan = _save_scan(repository, latest_scan, publication={
            "active_blob": marker["active_blob"],
            "metadata_fingerprint": metadata_fingerprint({**current, **updates}),
            "content_fingerprint": scan["content_fingerprint"],
        })
        repository.update_document(subject, {
            **updates, SCREENING_FIELD: marker, "status": "Processing complete",
            "percentage_complete": 100,
        }, etag=current["_etag"])
        scan = _read_scan(repository, scan_id)
        scan = _save_scan(
            repository, scan, state=state, published_at=_timestamp(), lease=None,
            postprocess_pending=True,
        )
        _log("content_published", document_id=subject.document_id, scan_id=scan_id)
    except ScreeningError as error:
        _record_failure(
            repository, scan_id, error.code, owner=owner,
            retry_publication=(
                error.code != "screening_cancelled"
                and not isinstance(error, (ScreeningConflictError, ScreeningValidationError, DocumentHeldError))
            ),
        )
        raise
    except (AzureError, OSError, RuntimeError) as error:
        _record_failure(repository, scan_id, "screening_publication_failed", owner=owner, retry_publication=True)
        raise ScreeningError(code="screening_publication_failed") from error
    return _after_publication(scan, actor_id, repository=repository)


def create_candidate_scan(scan_id, units, actor_id, *, repository=None, storage=None, run_inline=False):
    repository, storage = _repository(repository), _storage(storage)
    previous = _read_scan(repository, scan_id)
    subject = Subject.from_dict(previous["subject"])
    from content_screening.permissions import assert_subject_access

    document = assert_subject_access(subject, actor_id, repository=repository, review=True)
    if (
        (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan_id
        or previous.get("state") not in {"pending_review", "remediating"}
    ):
        raise ScreeningConflictError()
    units = normalize_units([
        unit for unit in normalize_units(units)
        if unit.locator.get("kind") != "metadata"
    ])
    candidate = begin_scan(
        subject, actor_id, repository=repository,
        expected_document_etag=document["_etag"], parent_scan_id=scan_id,
    )
    candidate = _save_scan(
        repository, candidate, source_ref=previous.get("source_ref"),
        original_file_name=previous["original_file_name"],
        parent_scan_id=scan_id, review_required=True, sanitized=True, trigger="remediation",
        units_ref=storage.write_json(
            subject, candidate["id"], f"units-{content_fingerprint(units)}",
            [unit.to_dict() for unit in units],
        ),
        content_fingerprint=content_fingerprint(units), units_total=len(units),
    )
    _set_document_state(repository, candidate, "pending_scan", status="Cleaned candidate queued for inspection")
    if run_inline:
        return inspect_scan(
            candidate["id"], units, actor_id, repository=repository, storage=storage, publish=False,
        )
    from content_screening.jobs import enqueue_document_scan

    enqueue_document_scan(subject, actor_id, scan_id=candidate["id"], repository=repository)
    return candidate


def scan_existing_document(subject, actor_id, job_id=None, *, repository=None, storage=None):
    repository, storage = _repository(repository), _storage(storage)
    if not isinstance(subject, Subject):
        subject = Subject.from_dict(subject)
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    pending = repository.get_scan(marker["scan_id"]) if marker.get("scan_id") else None
    if pending and pending.get("state") in {"publishing", "ready_to_publish"}:
        decision_actor = (pending.get("review_decision") or {}).get("actor_id") or actor_id
        return publish_scan(pending["id"], decision_actor, repository=repository, storage=storage)
    if pending and pending.get("policy_fingerprint") != hash_payload(get_effective_policy(subject, repository=repository)):
        if job_id is not None:
            raise ScreeningConflictError("The screening policy changed. Start a new scan job.")
        fresh = begin_scan(subject, actor_id, repository=repository, job_id=job_id)
        scan = _save_scan(
            repository, fresh, source_ref=pending.get("source_ref"),
            units_ref=pending.get("units_ref"), original_file_name=pending["original_file_name"],
            sanitized=bool(pending.get("sanitized")), parent_scan_id=pending["id"],
        )
        pending = scan
    if pending and pending.get("state") in {"pending_scan", "extracting", "scanning", "scan_error", "incomplete"}:
        scan = pending
    else:
        scan = begin_scan(subject, actor_id, repository=repository, job_id=job_id)
    if scan.get("units_ref"):
        units = normalize_units(storage.read_json(scan["units_ref"], subject))
        return inspect_scan(scan["id"], units, actor_id, repository=repository, storage=storage)
    if marker.get("canonical_ref"):
        units = normalize_units(storage.read_json(marker["canonical_ref"], subject))
        previous_scan_id = (scan.get("previous_marker") or {}).get("scan_id")
        previous_scan = repository.get_scan(previous_scan_id) if previous_scan_id else pending
        scan = _save_scan(
            repository, scan, sanitized=bool(marker.get("sanitized")),
            source_ref=previous_scan.get("source_ref") if previous_scan else None,
        )
        body = [unit for unit in units if unit.locator.get("kind") != "metadata"]
        for name in CONTENT_METADATA_FIELDS:
            value = document.get(name)
            if value not in (None, "", [], {}):
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                body.append(ContentUnit(f"metadata-{name}", text, {"kind": "metadata", "field": name}))
        return inspect_scan(scan["id"], body, actor_id, repository=repository, storage=storage)

    from functions_documents import (
        _get_screening_source_bytes,
        _get_screening_existing_chunks,
        _process_document_upload_background_impl,
    )

    if scan.get("source_ref"):
        source_bytes = storage.read_bytes(scan["source_ref"], subject)
    else:
        source_bytes = _get_screening_source_bytes(document)
    if source_bytes is not None:
        suffix = Path(scan["original_file_name"]).suffix or ".txt"
        with tempfile.TemporaryDirectory(prefix="simplechat-screening-") as directory:
            source_path = Path(directory) / f"source{suffix}"
            source_path.write_bytes(source_bytes)
            if not scan.get("source_ref"):
                scan = _save_scan(repository, scan, source_ref=storage.write_source(
                    subject, scan["id"], str(source_path), scan["original_file_name"],
                ))
            return _extract_and_inspect(
                scan, actor_id, str(source_path), _process_document_upload_background_impl,
                repository=repository, storage=storage,
                extraction_mode_override=scan.get("extraction_mode_override"),
            )
    if Path(scan["original_file_name"]).suffix.lower() in TABLE_EXTENSIONS:
        _record_failure(repository, scan["id"], "screening_table_source_missing")
        raise ScreeningError(code="screening_table_source_missing")
    chunks = _get_screening_existing_chunks(document)
    units = [
        ContentUnit(
            f"legacy-segment-{index}", chunk.get("chunk_text", ""),
            {"kind": "legacy_segment", "segment_number": index, "legacy_page_number": chunk.get("page_number")},
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    scan = _save_scan(repository, scan, coverage_source="indexed_snapshot", sanitized=True)
    return inspect_scan(scan["id"], units, actor_id, repository=repository, storage=storage)


def queue_metadata_rescan(document, updates, actor_id, *, repository=None):
    repository = _repository(repository)
    if "file_name" in updates and Path(str(updates["file_name"])).suffix.lower() != Path(document["file_name"]).suffix.lower():
        raise ScreeningValidationError("Renaming a screened file cannot change its source format.")
    subject = subject_from_document(document)
    marker = document.get(SCREENING_FIELD) or {}
    if (
        marker.get("state") == "pending_scan" and marker.get("origin_upload") is True
        and marker.get("scan_id") and repository.get_scan(marker["scan_id"]) is None
    ):
        repository.update_document(subject, updates, etag=document["_etag"])
        return None
    scan = begin_scan(
        subject, actor_id, repository=repository,
        expected_document_etag=document["_etag"],
        parent_scan_id=(document.get(SCREENING_FIELD) or {}).get("scan_id"),
    )
    scan = _save_scan(repository, scan, trigger="metadata")
    current = repository.read_document(subject)
    repository.update_document(subject, updates, etag=current["_etag"])
    from content_screening.jobs import enqueue_document_scan

    enqueue_document_scan(subject, actor_id, scan_id=scan["id"], repository=repository)
    return scan


def reprocess_document(subject, actor_id, extraction_mode, *, repository=None, storage=None):
    repository, storage = _repository(repository), _storage(storage)
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("sanitized"):
        raise ScreeningValidationError("A cleaned derivative must be edited through content review, not re-extracted from its original.")
    previous = repository.get_scan(marker["scan_id"]) if marker.get("scan_id") else None
    scan = begin_scan(subject, actor_id, repository=repository)
    from functions_documents import _get_screening_source_bytes, _process_document_upload_background_impl
    from content_screening.jobs import enqueue_document_scan

    if previous and previous.get("source_ref"):
        content = storage.read_bytes(previous["source_ref"], subject)
    else:
        content = _get_screening_source_bytes(document)
    if content is None:
        _record_failure(repository, scan["id"], "screening_source_missing")
        raise ScreeningError(code="screening_source_missing")
    suffix = Path(scan["original_file_name"]).suffix or ".pdf"
    with tempfile.TemporaryDirectory(prefix="simplechat-screening-") as directory:
        path = Path(directory) / f"source{suffix}"
        path.write_bytes(content)
        scan = _save_scan(
            repository, scan,
            source_ref=storage.write_source(subject, scan["id"], str(path), scan["original_file_name"]),
            extraction_mode_override=extraction_mode,
            trigger="reprocess",
        )
        job = enqueue_document_scan(subject, actor_id, scan_id=scan["id"], repository=repository)
        from content_screening.jobs import run_scan_job

        run_scan_job(job["id"], repository=repository)
        return _read_scan(repository, scan["id"])


def prepare_document_deletion(document, actor_id, *, repository=None, storage=None):
    """Revoke a screened document before removing private evidence and originals."""
    if SCREENING_FIELD not in document:
        return
    repository = _repository(repository)
    subject = subject_from_document(document)
    current = repository.read_document(subject)
    marker = current.get(SCREENING_FIELD)
    marker = marker if isinstance(marker, dict) else {}
    repository.update_document(subject, {
        SCREENING_FIELD: {
            **marker, "state": "deleting", "source_revision": subject.source_revision,
            "updated_at": _timestamp(),
        },
        "status": "Deleting screened document",
    }, etag=current["_etag"])
    continuation = None
    while True:
        page = repository.query(
            "scan", subject.scope_key, filters={"document_id": subject.document_id},
            continuation=continuation, page_size=100,
        )
        for scan in page["items"]:
            if scan.get("subject") != subject.to_dict():
                continue
            _save_scan(
                repository, scan, state="deleting", units_ref=None, result_ref=None,
                source_ref=None, review_decision=None, lease=None, deleted_by=actor_id,
                policy={}, previous_marker={}, original_file_name=None,
                deletion_started_at=scan.get("deletion_started_at") or _timestamp(),
            )
        continuation = page.get("continuation")
        if not continuation:
            break
    continuation = None
    while True:
        page = repository.query(
            "model_window", subject.scope_key, filters={"document_id": subject.document_id},
            continuation=continuation, page_size=100,
        )
        for window in page["items"]:
            if window.get("subject") == subject.to_dict():
                repository.replace({
                    **window, "result_ref": None, "payload_fingerprint": None,
                    "state": "deleted", "deleted_at": _timestamp(),
                }, window["_etag"])
        continuation = page.get("continuation")
        if not continuation:
            break
    storage = _storage(storage)
    storage.delete_revision(subject)


def delete_screened_document(scan_id, actor_id, *, repository=None, storage=None):
    """Delete an authorized review target without making it temporarily available."""
    repository = _repository(repository)
    scan = _read_scan(repository, scan_id)
    if scan.get("state") == "deleted":
        return scan
    subject = Subject.from_dict(scan["subject"])
    from content_screening.permissions import assert_scope_access

    assert_scope_access(actor_id, subject.scope_type, subject.scope_id, review=True)
    try:
        document = repository.read_document(subject)
    except ScreeningConflictError as error:
        if (
            error.code != "screening_source_missing"
            or scan.get("state") != "deleting"
            or not scan.get("deletion_started_at") or not scan.get("deleted_by")
        ):
            raise
        _storage(storage).delete_revision(subject)
        from functions_documents import delete_document_chunks

        delete_document_chunks(
            subject.document_id,
            group_id=subject.scope_id if subject.scope_type == "group" else None,
            public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
        )
        return _save_scan(repository, scan, state="deleted", deleted_at=_timestamp())
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") != scan_id:
        raise ScreeningConflictError()
    prepare_document_deletion(document, actor_id, repository=repository, storage=storage)
    from functions_documents import delete_document, delete_document_chunks

    scope = {
        "group_id": subject.scope_id if subject.scope_type == "group" else None,
        "public_workspace_id": subject.scope_id if subject.scope_type == "public" else None,
    }
    delete_document_chunks(subject.document_id, **scope)
    delete_document(
        subject.scope_id if subject.scope_type == "personal" else actor_id,
        subject.document_id, **scope,
    )
    scan = _read_scan(repository, scan_id)
    return _save_scan(repository, scan, state="deleted", deleted_at=_timestamp())


def _after_publication(scan, actor_id, *, repository):
    """Keep existing metadata/notification features behind the admission boundary."""
    subject = Subject.from_dict(scan["subject"])
    from content_screening.jobs import PROCESSOR_CONTEXT

    if PROCESSOR_CONTEXT.get() is not None:
        return _save_scan(repository, _read_scan(repository, scan["id"]), postprocess_pending=True)
    settings = _settings()
    document = repository.read_document(subject)
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") != scan["id"]:
        return scan
    if (scan.get("trigger") == "upload" or marker.get("origin_upload")) and not document.get("added_to_activity_log"):
        from functions_activity_logging import log_document_creation_transaction

        activity = log_document_creation_transaction(
            user_id=subject.scope_id if subject.scope_type == "personal" else actor_id,
            document_id=subject.document_id, workspace_type=subject.scope_type,
            file_name="Screened document",
            file_type=Path(document.get("file_name") or "").suffix,
            file_size=document.get("file_size"), page_count=document.get("number_of_pages"),
            embedding_tokens=document.get("embedding_tokens"),
            embedding_model=document.get("embedding_model_deployment_name"),
            version=document.get("version"),
            group_id=subject.scope_id if subject.scope_type == "group" else None,
            public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
            additional_metadata={"screening_scan_id": scan["id"]},
            idempotency_key=f"screened-document:{subject.key}",
        )
        if activity is not None:
            document = repository.update_document(
                subject, {"added_to_activity_log": True}, etag=document["_etag"],
            )
        scan = _save_scan(
            repository, _read_scan(repository, scan["id"]),
            activity_error=None if activity is not None else "activity_recording_pending",
        )
    if document.get("embedding_tokens") and not scan.get("embedding_usage_recorded"):
        from functions_activity_logging import log_token_usage

        usage = log_token_usage(
            user_id=subject.scope_id if subject.scope_type == "personal" else actor_id,
            token_type="embedding", total_tokens=document["embedding_tokens"],
            model=document.get("embedding_model_deployment_name") or "",
            workspace_type=subject.scope_type, document_id=subject.document_id,
            file_name="Screened document",
            group_id=subject.scope_id if subject.scope_type == "group" else None,
            public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
            additional_context={"screening_scan_id": scan["id"]},
            idempotency_key=f"screening-embedding:{scan['id']}",
        )
        scan = _save_scan(
            repository, _read_scan(repository, scan["id"]), embedding_usage_recorded=usage is not None,
            usage_error=None if usage is not None else "usage_recording_pending",
        )
    if document.get("created_from_chat_upload"):
        from functions_documents import sync_chat_upload_workspace_attachment_status

        if not sync_chat_upload_workspace_attachment_status(document):
            _log("attachment_status_update_pending", scan_id=scan["id"], level=logging.WARNING)
            scan = _save_scan(repository, _read_scan(repository, scan["id"]), attachment_sync_pending=True)
        elif scan.get("attachment_sync_pending"):
            scan = _save_scan(repository, _read_scan(repository, scan["id"]), attachment_sync_pending=False)
    if (
        settings.get("enable_content_screening") is True
        and settings.get("enable_extract_meta_data") is True
        and (scan.get("trigger") == "upload" or marker.get("origin_upload"))
        and not scan.get("metadata_generated")
    ):
        scan = _save_scan(repository, scan, metadata_generated=True)
        document = repository.update_document(subject, {
            SCREENING_FIELD: {**marker, "metadata_generated": True},
        }, etag=document["_etag"])
        from functions_documents import process_metadata_extraction_background

        process_metadata_extraction_background(
            subject.document_id,
            subject.scope_id if subject.scope_type == "personal" else actor_id,
            group_id=subject.scope_id if subject.scope_type == "group" else None,
            public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
        )
        document = repository.read_document(subject)
        if (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan["id"]:
            return scan
    if settings.get("enable_notifications") is True and not scan.get("completion_notified"):
        from functions_notifications import create_notification

        notification = create_notification(
            user_id=subject.scope_id if subject.scope_type == "personal" else None,
            group_id=subject.scope_id if subject.scope_type == "group" else None,
            public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
            notification_type="document_processing_complete",
            title="Document content is ready",
            message="Screening and any required review have completed.",
            link_url={"personal": "/workspace", "group": "/group_workspaces", "public": "/public_directory"}[subject.scope_type],
            link_context={
                "workspace_type": subject.scope_type, "document_id": subject.document_id,
                "group_id": subject.scope_id if subject.scope_type == "group" else None,
                "public_workspace_id": subject.scope_id if subject.scope_type == "public" else None,
            },
            metadata={"document_id": subject.document_id, "screening_scan_id": scan["id"]},
            idempotency_key=f"content-screening-ready:{scan['id']}",
        )
        current = _read_scan(repository, scan["id"])
        scan = _save_scan(
            repository, current, completion_notified=notification is not None,
            notification_error=None if notification is not None else "notification_delivery_pending",
        )
        if notification is None:
            _log("notification_delivery_pending", document_id=subject.document_id, scan_id=scan["id"], level=logging.WARNING)
    return scan


def reconcile_scan_completion(scan_id, *, repository=None):
    """Retry non-content completion work without starting another source scan."""
    repository = _repository(repository)
    scan = _read_scan(repository, scan_id)
    if scan.get("state") == "pending_review":
        from content_screening.reviews import ensure_review

        document = repository.read_document(Subject.from_dict(scan["subject"]))
        if (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan_id:
            return _save_scan(repository, scan, postprocess_pending=False)
        receipt = ensure_review(scan, scan["actor_id"], repository=repository)
        current = _read_scan(repository, scan_id)
        if current.get("state") != "pending_review" or current.get("subject") != scan.get("subject"):
            return current
        complete = (
            isinstance(receipt, dict) and receipt.get("notifications_complete") is True
            and bool(current.get("approval_id"))
            and current["approval_id"] == receipt.get("id")
        )
        return _save_scan(
            repository, current, postprocess_pending=not complete,
            review_notifications_complete=complete,
        )
    if scan.get("state") not in AVAILABLE_STATES:
        return scan
    scan = _after_publication(scan, scan["actor_id"], repository=repository)
    current = _read_scan(repository, scan_id)
    return _save_scan(repository, current, postprocess_pending=bool(
        current.get("notification_error") or current.get("activity_error")
        or current.get("usage_error") or current.get("attachment_sync_pending")
    ))
