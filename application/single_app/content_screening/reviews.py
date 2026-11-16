# reviews.py
"""Revision-bound human review and canonical-unit remediation.

Review IDs are scan IDs. Browser evidence is inert text with Unicode code-point
offsets. Mutations require the scan ETag and per-edited-unit content_hash; source
paths, replacement subjects, verdicts and policy snapshots are never accepted.
Approval is an explicit, fingerprint-bound decision, not a generic approval flag.

Application services are resolved at operation boundaries to avoid import cycles
and keep local tests independent of Azure and Flask application initialization.
"""

import base64
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from werkzeug.utils import secure_filename

from content_screening.contracts import (
    AVAILABLE_STATES,
    SCREENING_FIELD,
    ContentUnit,
    DocumentHeldError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    hash_payload,
    normalize_identifier,
    normalize_units,
)
from content_screening.permissions import (
    ScreeningNotFoundError,
    ScreeningPermissionError,
    assert_review_metadata_access,
    assert_scope_access,
    assert_subject_access,
)


MAX_EDITS = 100
MAX_PAGE_SIZE = 100
MAX_PAGE_CHARACTERS = 128000
MAX_REASON_CHARACTERS = 2000
MUTABLE_STATES = frozenset({"pending_review", "scan_error", "incomplete"})
PENDING_STATES = frozenset({
    "pending_scan", "extracting", "scanning", "pending_review", "scan_error",
    "incomplete", "remediating", "publishing", "deleting",
})
SUPPLEMENT_KINDS = frozenset({
    "figure", "vision", "image", "embedded_image", "figure_caption", "supplement",
})
PHYSICAL_PAGE_KINDS = frozenset({"page", "physical_page", "pdf_page"})
LOCATOR_FIELDS = frozenset({
    "kind", "page_number", "page_numbers", "segment_number", "slide_number",
    "sheet_index", "sheet", "row", "column", "value_type", "start_time", "end_time",
    "paragraph", "section", "field",
})


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _repository(repository=None):
    if repository is not None:
        return repository
    from content_screening.repository import get_repository

    return get_repository()


def _storage(storage=None):
    if storage is not None:
        return storage
    from content_screening.storage import ScreeningStorage

    return ScreeningStorage()


def _read_scan(repository, scan_id):
    scan_id = normalize_identifier(scan_id, "scan_id")
    scan = repository.get_scan(scan_id)
    if not scan:
        raise ScreeningNotFoundError()
    if scan.get("id") != scan_id or scan.get("kind") != "scan":
        raise ScreeningConflictError()
    return scan


def _authorized_scan(scan_id, actor_id, repository, *, metadata_only=False):
    scan = _read_scan(repository, scan_id)
    subject = Subject.from_dict(scan.get("subject"))
    document = (
        assert_review_metadata_access(scan, actor_id, repository=repository)
        if metadata_only else assert_subject_access(subject, actor_id, repository=repository)
    )
    return scan, subject, document


def _recheck_read(scan, document, actor_id, repository):
    current_scan, _subject, current_document = _authorized_scan(scan["id"], actor_id, repository)
    if (
        not scan.get("_etag") or current_scan.get("_etag") != scan["_etag"]
        or current_scan.get("subject") != scan.get("subject")
        or current_scan.get("source_ref") != scan.get("source_ref")
        or current_scan.get("units_ref") != scan.get("units_ref")
        or current_scan.get("result_ref") != scan.get("result_ref")
        or current_scan.get("content_fingerprint") != scan.get("content_fingerprint")
        or current_scan.get("policy_fingerprint") != scan.get("policy_fingerprint")
        or current_scan.get("state") != scan.get("state")
        or not document.get("_etag") or current_document.get("_etag") != document["_etag"]
        or current_document.get(SCREENING_FIELD) != document.get(SCREENING_FIELD)
    ):
        raise ScreeningConflictError()
    return current_scan, current_document


def _require_current(scan, document, etag):
    marker = document.get(SCREENING_FIELD)
    if (
        not isinstance(etag, str) or not etag or etag != scan.get("_etag")
        or not isinstance(marker, dict) or marker.get("scan_id") != scan["id"]
        or str(marker.get("source_revision")) != scan["subject"]["source_revision"]
        or marker.get("content_fingerprint") != scan.get("content_fingerprint")
    ):
        raise ScreeningConflictError()


def _replace_scan(repository, scan, **updates):
    if not scan.get("_etag"):
        raise ScreeningConflictError()
    return repository.replace(
        {**scan, **updates, "updated_at": _timestamp()}, scan["_etag"],
    )


def _mark_document(repository, subject, document, scan, state):
    marker = document.get(SCREENING_FIELD) or {}
    if marker.get("scan_id") != scan["id"]:
        raise ScreeningConflictError()
    return repository.update_document(subject, {
        SCREENING_FIELD: {
            **marker, "state": state, "review_required": True,
            "updated_at": _timestamp(),
        },
        "status": {
            "rejected": "Content review required",
            "scan_error": "Content review failed; retry is required",
        }.get(state, "Content review in progress"),
    }, etag=document["_etag"])


def _audit(repository, scan, actor_id, action):
    event_id = hash_payload({
        "scan_id": scan["id"], "actor_id": actor_id, "action": action,
        "etag": scan.get("_etag"),
    })
    repository.append_event(
        Subject.from_dict(scan["subject"]), action, actor_id,
        details={"state": scan["state"]}, scan_id=scan["id"], event_id=event_id,
    )


def ensure_review(scan, actor_id, *, repository=None):
    """Return approval metadata and an explicit, non-persisted notifications_complete flag."""
    from functions_approvals import create_content_screening_approval

    repository = _repository(repository)
    current = _read_scan(repository, scan["id"])
    if current.get("subject") != scan.get("subject"):
        raise ScreeningConflictError()
    approval = create_content_screening_approval(current, actor_id)
    if current.get("approval_id") != approval["id"]:
        _replace_scan(repository, current, approval_id=approval["id"], review_required=True)
    return {**approval, "notifications_complete": approval.get("notifications_complete") is True}


def _read_units(scan, subject, storage):
    if not scan.get("units_ref"):
        raise ScreeningError(code="screening_evidence_unavailable")
    units = normalize_units(storage.read_json(scan["units_ref"], subject))
    if content_fingerprint(units) != scan.get("content_fingerprint"):
        raise ScreeningConflictError()
    return units


def _read_result(scan, subject, storage):
    if not scan.get("result_ref"):
        return None
    result = storage.read_json(scan["result_ref"], subject)
    if (
        not isinstance(result, dict)
        or result.get("content_fingerprint") != scan.get("content_fingerprint")
        or result.get("policy_fingerprint") != scan.get("policy_fingerprint")
    ):
        raise ScreeningConflictError()
    return result


def _complete_result(scan, units, result):
    if (
        scan.get("coverage_complete") is not True
        or scan.get("result_status") not in {"pass", "findings"}
        or not isinstance(result, dict) or result.get("status") not in {"pass", "findings"}
        or result.get("error_code") or type(result.get("units_total")) is not int
        or result["units_total"] != len(units)
        or scan.get("policy_fingerprint") != hash_payload(scan.get("policy"))
        or not isinstance(result.get("findings"), list)
        or len(result["findings"]) != scan.get("finding_count")
        or not isinstance(result.get("detectors"), list) or not result["detectors"]
    ):
        return False
    for detector in result["detectors"]:
        if (
            not isinstance(detector, dict)
            or detector.get("status") not in {"pass", "findings"} or detector.get("error_code")
            or type(detector.get("required_units")) is not int
            or detector["required_units"] != len(units)
            or type(detector.get("completed_units")) is not int
            or detector.get("completed_units") != detector["required_units"]
            or type(detector.get("required_windows")) is not int
            or detector["required_windows"] < 0
            or type(detector.get("completed_windows")) is not int
            or detector.get("completed_windows") != detector["required_windows"]
        ):
            return False
    return not (result["status"] == "pass" and result["findings"])


def _retryable_publication(scan):
    if scan.get("state") != "publishing":
        return False
    decision = scan.get("review_decision") or {}
    if (
        decision.get("action") not in {"approve_with_flags", "approve_clean"}
        or decision.get("scan_id") != scan.get("id")
        or decision.get("source_revision") != scan["subject"]["source_revision"]
        or decision.get("content_fingerprint") != scan.get("content_fingerprint")
        or decision.get("policy_fingerprint") != scan.get("policy_fingerprint")
        or decision.get("policy_snapshot_hash") != hash_payload(scan.get("policy"))
        or not isinstance(decision.get("reason"), str) or not decision["reason"].strip()
        or decision["action"] == "approve_with_flags" and decision.get("acknowledged_flags") is not True
    ):
        return False
    lease = scan.get("lease") or {}
    try:
        expires = datetime.fromisoformat(lease["expires_at"]) if lease.get("expires_at") else (
            datetime.fromisoformat(scan.get("review_operation_started_at") or decision["decided_at"])
            + timedelta(seconds=60)
        )
        return expires.tzinfo is not None and expires <= datetime.now(timezone.utc)
    except (ValueError, TypeError, KeyError):
        return False


def _hold_failed_review(repository, scan_id, operation_id):
    """A failed UI operation remains held, without disturbing another scan/worker."""
    try:
        scan = _read_scan(repository, scan_id)
        # Expired publication leases still belong to the service's exact-decision retry flow.
        if (
            scan.get("review_operation_id") != operation_id
            or scan.get("state") not in {"remediating", "publishing"} or scan.get("lease")
        ):
            return
        subject = Subject.from_dict(scan["subject"])
        document = repository.read_document(subject)
        if (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan_id:
            return
        scan = _replace_scan(
            repository, scan, state="scan_error", error_code="screening_review_action_failed",
        )
        _mark_document(repository, subject, document, scan, "scan_error")
    except Exception:
        # The existing hold is authoritative even if a secondary status write fails.
        return


def _attachment_name(value, kind):
    name = secure_filename(value if isinstance(value, str) else "")[:180] or "document"
    return f"{kind}-{name}"


def _clean_attachment_available(scan, document):
    marker = document.get(SCREENING_FIELD) if isinstance(document, dict) else None
    active_blob = marker.get("active_blob") if isinstance(marker, dict) else None
    return bool(
        isinstance(marker, dict) and scan.get("state") in AVAILABLE_STATES
        and marker.get("state") == scan["state"] and marker.get("scan_id") == scan["id"]
        and str(marker.get("source_revision")) == scan["subject"]["source_revision"]
        and scan.get("content_fingerprint") and scan.get("policy_fingerprint")
        and marker.get("content_fingerprint") == scan.get("content_fingerprint")
        and marker.get("policy_fingerprint") == scan.get("policy_fingerprint")
        and scan.get("units_ref") and marker.get("canonical_ref") == scan["units_ref"]
        and (
            scan.get("sanitized") is True and marker.get("sanitized") is True
            or not scan.get("source_ref")
        )
        and isinstance(active_blob, dict)
        and all(active_blob.get(key) for key in ("container", "path", "etag", "content_hash"))
        and (scan.get("publication") or {}).get("active_blob") == active_blob
    )


def _review_attachments(scan, document):
    downloads = {"original": None, "clean": None}
    if not isinstance(document, dict) or scan.get("state") in {"deleting", "deleted"}:
        return downloads
    base = f"/api/content-screening/reviews/{quote(scan['id'], safe='')}/downloads"
    if isinstance(scan.get("source_ref"), dict) and scan["source_ref"]:
        downloads["original"] = {
            "url": f"{base}/original",
            "file_name": _attachment_name(scan.get("original_file_name"), "original"),
        }
    if _clean_attachment_available(scan, document):
        downloads["clean"] = {
            "url": f"{base}/clean",
            "file_name": _attachment_name(document.get("file_name"), "clean"),
        }
    return downloads


def review_summary(scan, document=None, *, actor_id=None):
    """Allowlist metadata; never return policy values, storage references or evidence."""
    marker = document.get(SCREENING_FIELD) if isinstance(document, dict) else None
    current = isinstance(marker, dict) and marker.get("scan_id") == scan["id"]
    state = scan.get("state")
    evidence = {
        "units_available": bool(document and scan.get("units_ref") and scan.get("content_fingerprint")),
        "findings_available": bool(document and scan.get("result_ref")),
    }
    if state in {"deleting", "deleted"}:
        evidence = {"units_available": False, "findings_available": False}
    actions = []
    if current and state in MUTABLE_STATES:
        actions = ["reject", "delete"]
        if evidence["units_available"]:
            actions = ["preview", "remediate", *actions]
        if (
            state == "pending_review" and scan.get("coverage_complete") is True
            and scan.get("result_status") in {"pass", "findings"}
            and evidence["units_available"] and evidence["findings_available"]
        ):
            actions.append("approve_with_flags")
            if scan.get("parent_scan_id") and scan.get("sanitized") and not scan.get("finding_count"):
                actions.append("approve_clean")
    elif (current and state in {"rejected", "deleting"}) or (document is None and state == "deleting"):
        actions = ["delete"]
    decision = scan.get("review_decision") or {}
    if current and actor_id == decision.get("actor_id") and _retryable_publication(scan):
        actions = ["retry_publication"]
    downloads = _review_attachments(scan, document)
    actions.extend(f"download_{kind}" for kind, value in downloads.items() if value)
    coverage_mode = (
        "indexed_snapshot" if scan.get("coverage_source") == "indexed_snapshot" else
        "cleaned_candidate" if scan.get("parent_scan_id") else
        "extracted_content" if scan.get("source_ref") else "canonical_content"
    )
    return {
        "id": scan["id"], "subject": Subject.from_dict(scan["subject"]).to_dict(),
        "state": "scanning" if state == "extracting" else state, "etag": scan.get("_etag"),
        "content_fingerprint": scan.get("content_fingerprint"),
        "policy_fingerprint": scan.get("policy_fingerprint"),
        "outcome": scan.get("result_status"),
        "coverage": {
            "complete": scan.get("coverage_complete") is True,
            "units_total": _safe_count(scan.get("units_total")),
            "status": scan.get("result_status"),
        },
        "coverage_mode": coverage_mode,
        "finding_count": _safe_count(scan.get("finding_count")),
        "review_required": scan.get("review_required") is True,
        "candidate_of": scan.get("parent_scan_id"),
        "original_retained": downloads["original"] is not None,
        "sanitized": scan.get("sanitized") is True,
        "allowed_actions": actions, "downloads": downloads, "evidence": evidence,
        "warning": "Approved with flags. Review the recorded findings before use."
        if state == "approved_with_flags" else None,
        "decision": {
            key: decision.get(key) for key in ("action", "actor_id", "reason", "decided_at")
        } if decision else None,
        "created_at": scan.get("created_at"), "updated_at": scan.get("updated_at"),
    }


def _safe_count(value):
    return value if type(value) is int and value >= 0 else 0


def _page_size(value):
    if type(value) is not int or not 1 <= value <= MAX_PAGE_SIZE:
        raise ScreeningValidationError()
    return value


def get_review(scan_id, actor_id, *, repository=None):
    repository = _repository(repository)
    scan, _subject, document = _authorized_scan(scan_id, actor_id, repository, metadata_only=True)
    return review_summary(scan, document, actor_id=actor_id)


def read_review_attachment(scan_id, actor_id, kind, *, repository=None, storage=None):
    """Read an exact reviewer original or the exact currently released derivative."""
    if not isinstance(kind, str) or kind not in {"original", "clean"}:
        raise ScreeningValidationError()
    repository = _repository(repository)
    scan, subject, document = _authorized_scan(scan_id, actor_id, repository)
    attachment = _review_attachments(scan, document)[kind]
    if attachment is None:
        raise ScreeningNotFoundError(code="screening_attachment_unavailable")
    if kind == "original":
        content = _storage(storage).read_bytes(scan["source_ref"], subject)
    else:
        # The ordinary active-blob boundary validates the manifest, hash and revision.
        from content_screening.access import read_available_document_bytes

        fresh, content = read_available_document_bytes(
            document, user_id=actor_id,
            group_id=subject.scope_id if subject.scope_type == "group" else None,
            public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
            purpose="download",
        )
        if (
            fresh.get("_etag") != document.get("_etag")
            or fresh.get(SCREENING_FIELD) != document.get(SCREENING_FIELD)
            or not _clean_attachment_available(scan, fresh)
        ):
            raise ScreeningConflictError()
    if not isinstance(content, bytes):
        raise ScreeningConflictError()
    current_scan, current_document = _recheck_read(scan, document, actor_id, repository)
    if _review_attachments(current_scan, current_document)[kind] != attachment:
        raise ScreeningConflictError()
    return content, attachment["file_name"]


def list_reviews(actor_id, *, scope_type=None, scope_id=None, state="pending",
                 continuation=None, page_size=50, repository=None):
    repository = _repository(repository)
    _page_size(page_size)
    scope_key = None
    if scope_type is not None or scope_id is not None:
        assert_scope_access(actor_id, scope_type, scope_id)
        scope_key = f"{scope_type}:{scope_id}"
    if state not in {"pending", "all", "resolved", *MUTABLE_STATES, *AVAILABLE_STATES, "rejected"}:
        raise ScreeningValidationError()
    page = repository.query(
        "scan", scope_key, filters={"review_required": True},
        continuation=continuation, page_size=page_size,
    )
    items = []
    for candidate in page["items"]:
        try:
            scan, _subject, document = _authorized_scan(
                candidate["id"], actor_id, repository, metadata_only=True,
            )
        except (ScreeningPermissionError, ScreeningNotFoundError, ScreeningConflictError):
            continue
        scan_state = scan.get("state")
        if (
            state == "pending" and scan_state not in PENDING_STATES
            or state == "resolved" and scan_state in PENDING_STATES
            or state not in {"pending", "resolved", "all"} and scan_state != state
        ):
            continue
        summary = review_summary(scan, document, actor_id=actor_id)
        if state == "pending" and document is not None and (document.get(SCREENING_FIELD) or {}).get("scan_id") != scan["id"]:
            continue
        # Queues omit decisions and review reasons as well as all evidence.
        summary.pop("decision", None)
        items.append(summary)
    return {"items": items, "continuation": page.get("continuation")}


def _cursor(scan, kind, index, offset=0):
    value = [scan["id"], scan.get("content_fingerprint"), kind, index, offset]
    return base64.urlsafe_b64encode(json.dumps(value).encode("utf-8")).decode("ascii")


def _read_cursor(value, scan, kind):
    if not value:
        return 0, 0
    if not isinstance(value, str) or len(value) > 2048:
        raise ScreeningValidationError()
    try:
        decoded = json.loads(base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ScreeningValidationError() from error
    if (
        not isinstance(decoded, list) or len(decoded) != 5
        or decoded[:3] != [scan["id"], scan.get("content_fingerprint"), kind]
        or any(type(number) is not int or number < 0 for number in decoded[3:])
    ):
        raise ScreeningConflictError()
    return decoded[3], decoded[4]


def _unit_payload(unit, start=0, end=None):
    end = len(unit.text) if end is None else end
    return {
        **unit.to_dict(),
        "text": unit.text[start:end],
        "locator": {
            key: value for key, value in unit.locator.items() if key in LOCATOR_FIELDS
        },
        "text_offset": start, "text_total": len(unit.text),
    }


def _unit_page(units, scan, continuation=None, page_size=25):
    index, offset = _read_cursor(continuation, scan, "units")
    if index > len(units) or index == len(units) and offset:
        raise ScreeningValidationError()
    items = []
    budget = MAX_PAGE_CHARACTERS
    while index < len(units) and len(items) < page_size and budget > 0:
        unit = units[index]
        if offset > len(unit.text):
            raise ScreeningValidationError()
        end = min(len(unit.text), offset + budget)
        items.append(_unit_payload(unit, offset, end))
        budget -= end - offset
        if end < len(unit.text):
            offset = end
            break
        index, offset = index + 1, 0
    return {
        "items": items, "total": len(units),
        "continuation": _cursor(scan, "units", index, offset) if index < len(units) else None,
    }


def get_review_units(scan_id, actor_id, *, continuation=None, page_size=25,
                     repository=None, storage=None):
    _page_size(page_size)
    repository = _repository(repository)
    scan, subject, document = _authorized_scan(scan_id, actor_id, repository)
    if not review_summary(scan, document)["evidence"]["units_available"]:
        raise ScreeningNotFoundError(code="screening_evidence_unavailable")
    units = _read_units(scan, subject, _storage(storage))
    _recheck_read(scan, document, actor_id, repository)
    return _unit_page(units, scan, continuation, page_size)


def get_review_findings(scan_id, actor_id, *, continuation=None, page_size=25,
                        repository=None, storage=None):
    _page_size(page_size)
    repository = _repository(repository)
    scan, subject, document = _authorized_scan(scan_id, actor_id, repository)
    if not review_summary(scan, document)["evidence"]["findings_available"]:
        raise ScreeningNotFoundError(code="screening_evidence_unavailable")
    result = _read_result(scan, subject, _storage(storage))
    _recheck_read(scan, document, actor_id, repository)
    findings = (result or {}).get("findings") or []
    if not isinstance(findings, list):
        raise ScreeningConflictError()
    index, offset = _read_cursor(continuation, scan, "findings")
    if offset or index > len(findings):
        raise ScreeningValidationError()
    items = []
    for finding in findings[index:index + page_size]:
        if not isinstance(finding, dict):
            raise ScreeningConflictError()
        item = {
            key: finding.get(key) for key in (
                "finding_id", "rule_id", "unit_id", "category", "severity",
                "start", "end", "source", "confidence",
            )
        }
        item["reason"] = str(finding.get("reason") or "")[:2000]
        item["evidence"] = str(finding.get("evidence") or "")[:4000]
        item["evidence_truncated"] = len(str(finding.get("evidence") or "")) > 4000
        items.append(item)
    end = index + len(items)
    return {
        "items": items, "total": len(findings),
        "continuation": _cursor(scan, "findings", end) if end < len(findings) else None,
    }


def _table_identity(locator):
    if locator.get("kind") not in {"table_cell", "table_formula"}:
        return None
    values = tuple(locator.get(key) for key in ("sheet_index", "row", "column"))
    if (
        any(type(value) is not int for value in values)
        or values[0] < 0 or values[1] < 1 or values[2] < 1
    ):
        raise ScreeningValidationError()
    return values


def apply_edits(units, edits):
    """Apply a bounded edit set against original hashes and original offsets."""
    units = normalize_units(units)
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_EDITS:
        raise ScreeningValidationError()
    by_id = {unit.unit_id: unit for unit in units}
    operations = {}
    removed = set()
    pages = set()
    sheets = set()
    cells = set()
    warnings = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise ScreeningValidationError()
        action = edit.get("action")
        if not isinstance(action, str):
            raise ScreeningValidationError()
        fields = {
            "remove_unit": {"action", "unit_id", "content_hash"},
            "remove_span": {"action", "unit_id", "content_hash", "start", "end"},
            "replace_cell": {"action", "unit_id", "content_hash", "text"},
        }.get(action)
        if fields is None or set(edit) != fields:
            raise ScreeningValidationError()
        unit = by_id.get(edit["unit_id"]) if isinstance(edit["unit_id"], str) else None
        if unit is None or edit["content_hash"] != unit.content_hash:
            raise ScreeningConflictError()
        previous = operations.setdefault(unit.unit_id, [])
        if previous and (action != "remove_span" or previous[0]["action"] != "remove_span"):
            raise ScreeningValidationError()
        previous.append(edit)
        if action == "remove_unit":
            removed.add(unit.unit_id)
            page = unit.locator.get("page_number")
            if type(page) is int and page > 0 and unit.locator.get("kind") in PHYSICAL_PAGE_KINDS:
                pages.add(page)
            if unit.locator.get("kind") == "table_sheet":
                sheet = unit.locator.get("sheet_index")
                if type(sheet) is not int or sheet < 0:
                    raise ScreeningValidationError()
                sheets.add(sheet)
            if unit.locator.get("kind") == "table_cell":
                cells.add(_table_identity(unit.locator))
        elif action == "remove_span":
            start, end = edit["start"], edit["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(unit.text):
                raise ScreeningValidationError()
            if unit.locator.get("kind") in {"table_formula", "table_sheet"}:
                raise ScreeningValidationError()
            if unit.locator.get("kind") == "table_cell":
                cells.add(_table_identity(unit.locator))
        else:
            if unit.locator.get("kind") != "table_cell":
                raise ScreeningValidationError()
            if not isinstance(edit["text"], str) or len(edit["text"]) > MAX_PAGE_CHARACTERS:
                raise ScreeningValidationError()
            cells.add(_table_identity(unit.locator))

    for unit in units:
        locator = unit.locator
        linked_pages = locator.get("page_numbers") or []
        if not isinstance(linked_pages, list):
            linked_pages = []
        if (
            locator.get("page_number") in pages or any(page in pages for page in linked_pages)
            or locator.get("sheet_index") in sheets
            or locator.get("kind") == "table_formula" and _table_identity(locator) in cells
        ):
            removed.add(unit.unit_id)
        if locator.get("kind") in SUPPLEMENT_KINDS and not locator.get("page_number"):
            removed.add(unit.unit_id)
            if "Unlocated figure and image supplements are excluded from the cleaned candidate." not in warnings:
                warnings.append("Unlocated figure and image supplements are excluded from the cleaned candidate.")
        if locator.get("kind") == "metadata":
            removed.add(unit.unit_id)
            if "Derived metadata will be rebuilt from the cleaned candidate." not in warnings:
                warnings.append("Derived metadata will be rebuilt from the cleaned candidate.")
    if pages:
        warnings.append("All source units linked to each removed physical page are excluded.")
    if cells:
        warnings.append("Formulas linked to edited or removed cells are excluded; replacements are text values.")
    candidate = []
    for unit in units:
        if unit.unit_id in removed:
            continue
        edits_for_unit = operations.get(unit.unit_id) or []
        text = unit.text
        locator = copy.deepcopy(unit.locator)
        if edits_for_unit and edits_for_unit[0]["action"] == "replace_cell":
            text = edits_for_unit[0]["text"]
            locator["value_type"] = "text"
        elif edits_for_unit:
            spans = sorted((edit["start"], edit["end"]) for edit in edits_for_unit)
            if any(current[0] < previous[1] for previous, current in zip(spans, spans[1:])):
                raise ScreeningValidationError()
            for start, end in reversed(spans):
                text = text[:start] + text[end:]
            if locator.get("kind") == "table_cell":
                locator["value_type"] = "text"
        candidate.append(ContentUnit(unit.unit_id, text, locator, unit.normalization_version))
    normalize_units(candidate)
    return candidate, sorted(removed), warnings


def preview_remediation(scan_id, actor_id, etag, edits, *, repository=None, storage=None):
    repository = _repository(repository)
    scan, subject, document = _authorized_scan(scan_id, actor_id, repository)
    _require_current(scan, document, etag)
    if scan.get("state") not in MUTABLE_STATES:
        raise ScreeningConflictError()
    units = _read_units(scan, subject, _storage(storage))
    candidate, removed, warnings = apply_edits(units, edits)
    original = {unit.unit_id: unit for unit in units}
    changed = [
        unit for unit in candidate if unit.to_dict() != original[unit.unit_id].to_dict()
    ]
    page = _unit_page(changed, {**scan, "content_fingerprint": content_fingerprint(candidate)})
    edited_ids = {edit["unit_id"] for edit in edits}
    removed.sort(key=lambda unit_id: (unit_id not in edited_ids, unit_id))
    truncated = page["continuation"] is not None or len(removed) > MAX_PAGE_SIZE
    if truncated:
        warnings.append("This preview is partial. Inspect the fully rescanned candidate before approving it.")
    _recheck_read(scan, document, actor_id, repository)
    return {
        "units": page["items"], "total_units": len(candidate),
        "preview_truncated": truncated,
        "content_fingerprint": content_fingerprint(candidate),
        "removed_unit_ids": removed[:MAX_PAGE_SIZE], "removed_unit_count": len(removed),
        "warnings": warnings,
    }


def remediate_review(scan_id, actor_id, etag, edits, *, repository=None, storage=None):
    from content_screening.service import create_candidate_scan
    from functions_approvals import resolve_content_screening_approval

    repository, storage = _repository(repository), _storage(storage)
    scan, subject, document = _authorized_scan(scan_id, actor_id, repository)
    _require_current(scan, document, etag)
    if scan.get("state") not in MUTABLE_STATES:
        raise ScreeningConflictError()
    units = _read_units(scan, subject, storage)
    candidate, _removed, _warnings = apply_edits(units, edits)
    scan = _replace_scan(
        repository, scan, state="remediating", review_decision=None,
        review_operation_id=uuid.uuid4().hex, review_operation_started_at=_timestamp(),
    )
    try:
        _mark_document(repository, subject, document, scan, "remediating")
        _audit(repository, scan, actor_id, "remediate")
        assert_subject_access(subject, actor_id, repository=repository)
        result = create_candidate_scan(
            scan_id, candidate, actor_id, repository=repository, storage=storage,
        )
    except Exception:
        _hold_failed_review(repository, scan_id, scan["review_operation_id"])
        raise
    if (
        result.get("parent_scan_id") != scan_id or result.get("review_required") is not True
        or result.get("state") in AVAILABLE_STATES
    ):
        raise ScreeningConflictError()
    resolve_content_screening_approval(scan, actor_id, "remediate")
    return get_review(result["id"], actor_id, repository=repository)


def decide_review(scan_id, actor_id, etag, action, reason, *, acknowledge_flags=False,
                  repository=None, storage=None):
    if not isinstance(action, str) or action not in {
        "approve_with_flags", "approve_clean", "reject", "delete", "retry_publication",
    }:
        raise ScreeningValidationError()
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_CHARACTERS:
        raise ScreeningValidationError()
    if type(acknowledge_flags) is not bool:
        raise ScreeningValidationError()
    if action == "approve_with_flags" and acknowledge_flags is not True:
        raise ScreeningValidationError(code="screening_acknowledgement_required")
    from content_screening.service import (
        delete_screened_document,
        get_effective_policy,
        publish_scan,
    )
    from functions_approvals import resolve_content_screening_approval

    repository = _repository(repository)
    scan, subject, document = _authorized_scan(
        scan_id, actor_id, repository, metadata_only=action == "delete",
    )
    if document is None:
        if action != "delete" or not isinstance(etag, str) or not etag or etag != scan.get("_etag"):
            raise ScreeningConflictError()
        result = delete_screened_document(scan_id, actor_id, repository=repository, storage=storage)
        resolve_content_screening_approval(result, actor_id, "delete")
        return review_summary(result)
    _require_current(scan, document, etag)
    retry = action == "retry_publication"
    if retry:
        if not _retryable_publication(scan) or (scan.get("review_decision") or {}).get("actor_id") != actor_id:
            raise ScreeningConflictError()
    elif scan.get("state") not in MUTABLE_STATES and not (
        action == "delete" and scan.get("state") in {"rejected", "deleting"}
    ):
        raise ScreeningConflictError()
    if action.startswith("approve") or retry:
        if not retry and scan.get("state") != "pending_review":
            raise DocumentHeldError()
        storage = _storage(storage)
        units = _read_units(scan, subject, storage)
        result = _read_result(scan, subject, storage)
        if not _complete_result(scan, units, result):
            raise DocumentHeldError()
        if hash_payload(get_effective_policy(subject, repository=repository)) != scan["policy_fingerprint"]:
            raise ScreeningConflictError()
        release_action = scan["review_decision"]["action"] if retry else action
        if release_action == "approve_clean" and (
            result["status"] != "pass" or result["findings"]
            or not scan.get("parent_scan_id") or scan.get("sanitized") is not True
        ):
            raise DocumentHeldError()
    decision = copy.deepcopy(scan["review_decision"]) if retry else {
        "scan_id": scan_id, "source_revision": subject.source_revision,
        "content_fingerprint": scan.get("content_fingerprint"),
        "policy_fingerprint": scan.get("policy_fingerprint"),
        "policy_snapshot_hash": hash_payload(scan.get("policy")),
        "actor_id": actor_id, "action": action, "reason": reason.strip(),
        "decided_at": _timestamp(), "acknowledged_flags": acknowledge_flags,
    }
    state = "rejected" if action == "reject" else "deleting" if action == "delete" else "publishing"
    scan = _replace_scan(
        repository, scan, state=state, review_decision=decision,
        review_operation_id=uuid.uuid4().hex, review_operation_started_at=_timestamp(),
    )
    try:
        _mark_document(repository, subject, document, scan, state)
        _audit(repository, scan, actor_id, action)
        assert_subject_access(subject, actor_id, repository=repository)
        if action.startswith("approve") or retry:
            result = publish_scan(scan_id, actor_id, repository=repository, storage=storage)
        elif action == "delete":
            result = delete_screened_document(scan_id, actor_id, repository=repository, storage=storage)
        else:
            result = scan
    except Exception:
        _hold_failed_review(repository, scan_id, scan["review_operation_id"])
        raise
    resolve_content_screening_approval(result, actor_id, decision["action"])
    if action == "delete":
        return review_summary(result)
    return get_review(scan_id, actor_id, repository=repository)
