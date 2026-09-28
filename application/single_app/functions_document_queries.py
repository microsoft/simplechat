# functions_document_queries.py
"""Pure standing-view and facet calculations shared by workspace document reads."""

from datetime import datetime, timedelta, timezone


DOCUMENT_PLACE_FILTERS = frozenset({
    "all", "recent", "shared", "processing", "errors", "untagged",
})
DOCUMENT_RECENT_DAYS = 30


def _document_processing_state(document_item):
    status_text = str(document_item.get("status") or "").lower()
    if "error" in status_text or "failed" in status_text:
        return "error"

    percentage = document_item.get("percentage_complete")
    if percentage is None:
        return "ready"
    try:
        return "ready" if float(percentage) >= 100 else "processing"
    except (TypeError, ValueError):
        return "ready"


def _parse_document_timestamp(document_item):
    """Prefer the Cosmos timestamp, with the legacy upload date as fallback."""
    raw_ts = document_item.get("_ts")
    if raw_ts is not None:
        try:
            return datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            pass

    raw_upload_date = document_item.get("upload_date")
    if not raw_upload_date:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_upload_date).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_document_facets(documents, owner_id, recent_days=DOCUMENT_RECENT_DAYS, *, owner_field="user_id"):
    """Count a complete, already-authorized and content-safe current-revision set."""
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    facets = {
        "total": 0,
        "untagged": 0,
        "processing": 0,
        "errors": 0,
        "recent": 0,
        "shared_with_me": 0,
        "by_tag": {},
        "by_classification": {},
    }
    for document_item in documents or []:
        facets["total"] += 1
        tags = [
            str(tag).strip()
            for tag in (document_item.get("tags") or [])
            if str(tag or "").strip()
        ]
        if tags:
            for tag in tags:
                facets["by_tag"][tag] = facets["by_tag"].get(tag, 0) + 1
        else:
            facets["untagged"] += 1

        state = _document_processing_state(document_item)
        if state == "processing":
            facets["processing"] += 1
        elif state == "error":
            facets["errors"] += 1

        classification = str(document_item.get("document_classification") or "").strip()
        if classification:
            facets["by_classification"][classification] = facets["by_classification"].get(classification, 0) + 1
        if document_item.get(owner_field) != owner_id:
            facets["shared_with_me"] += 1
        uploaded_at = _parse_document_timestamp(document_item)
        if uploaded_at and uploaded_at >= recent_cutoff:
            facets["recent"] += 1
    return facets


def filter_documents_by_place(
    documents, place, owner_id, recent_days=DOCUMENT_RECENT_DAYS, *, owner_field="user_id",
):
    """Filter the full safe set before paging, using the workspace's ownership field."""
    if place in ("", "all", None):
        return documents
    if place == "untagged":
        return [
            document_item for document_item in documents
            if not [tag for tag in (document_item.get("tags") or []) if str(tag or "").strip()]
        ]
    if place == "shared":
        return [document_item for document_item in documents if document_item.get(owner_field) != owner_id]
    if place in ("processing", "errors"):
        wanted_state = "processing" if place == "processing" else "error"
        return [
            document_item for document_item in documents
            if _document_processing_state(document_item) == wanted_state
        ]
    if place == "recent":
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        recent_documents = []
        for document_item in documents:
            uploaded_at = _parse_document_timestamp(document_item)
            if uploaded_at and uploaded_at >= recent_cutoff:
                recent_documents.append(document_item)
        return recent_documents
    return documents
