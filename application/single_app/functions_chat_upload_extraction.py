# functions_chat_upload_extraction.py
"""Describe what ingestion extracted from the workspace document behind a chat upload.

A file uploaded into a conversation is stored as a workspace document, so the chat message
itself carries no text. Opening the upload therefore has to read what ingestion produced for
that document: the indexed text that search and chat actually use, and the structured image
analysis that was saved on the document record but was never shown anywhere.

Everything here is pure so the route can stay thin and the shaping can be tested without
Cosmos DB, AI Search, or Azure credentials.
"""

WORKSPACE_UPLOAD_FILE_CONTENT_SOURCE = "workspace"
NO_EXTRACTED_CONTENT_MESSAGE = "No extracted content is available for this file yet."
STILL_PROCESSING_MESSAGE = "This file is still being processed. Try again when it finishes."


def _clean_text(value):
    return value.strip() if isinstance(value, str) else ""


def _clean_list(values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def summarize_vision_analysis(vision_analysis):
    """Return the displayable parts of a stored vision analysis, or None when it has none.

    An analysis that records an error is excluded, because its description is the error
    message rather than anything the model saw in the image.
    """
    if not isinstance(vision_analysis, dict) or vision_analysis.get("error"):
        return None

    summary = {
        "model": _clean_text(vision_analysis.get("model") or vision_analysis.get("model_name")),
        "description": _clean_text(vision_analysis.get("description")),
        "objects": _clean_list(vision_analysis.get("objects")),
        "text": _clean_text(vision_analysis.get("text")),
        "analysis": _clean_text(
            vision_analysis.get("analysis") or vision_analysis.get("contextual_analysis")
        ),
    }
    if not any(summary[key] for key in ("description", "objects", "text", "analysis")):
        return None
    return summary


def render_vision_analysis_text(summary):
    """Plain-text rendering for clients that can only show a text body."""
    if not summary:
        return ""

    lines = ["AI Vision Analysis"]
    if summary.get("model"):
        lines.append(f"Model: {summary['model']}")
    if summary.get("description"):
        lines.append(f"\nDescription: {summary['description']}")
    if summary.get("objects"):
        lines.append(f"\nObjects Detected: {', '.join(summary['objects'])}")
    if summary.get("text"):
        lines.append(f"\nVisible Text: {summary['text']}")
    if summary.get("analysis"):
        lines.append(f"\nContextual Analysis: {summary['analysis']}")
    return "\n".join(lines).strip()


def join_indexed_chunk_text(chunks):
    """Join the indexed text of ordered chunks, skipping empty ones."""
    parts = []
    for chunk in chunks or []:
        if not isinstance(chunk, dict):
            continue
        text = _clean_text(chunk.get("chunk_text"))
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _percentage_complete(document):
    try:
        return int(document.get("percentage_complete"))
    except (TypeError, ValueError):
        return None


def is_workspace_upload_processing(document):
    """Return whether the linked document has not finished ingestion yet."""
    percentage = _percentage_complete(document)
    if percentage is not None:
        return percentage < 100
    status = _clean_text(document.get("status")).lower()
    return bool(status) and not status.startswith("processing complete")


def build_workspace_upload_details(document, indexed_chunk_count):
    """Return the browser-safe extraction details of the document behind a chat upload.

    Only descriptive ingestion results are returned. Storage locations, scope identifiers and
    anything the screening subsystem manages stay on the server.
    """
    source = document if isinstance(document, dict) else {}
    try:
        number_of_pages = int(source.get("number_of_pages"))
    except (TypeError, ValueError):
        number_of_pages = None

    return {
        "document_id": _clean_text(source.get("id")),
        "title": _clean_text(source.get("title")),
        "abstract": _clean_text(source.get("abstract")),
        "keywords": _clean_list(source.get("keywords")),
        "status": _clean_text(source.get("status")),
        "percentage_complete": _percentage_complete(source),
        "number_of_pages": number_of_pages,
        "extraction_engine": _clean_text(source.get("extraction_engine")),
        "extraction_engine_reason": _clean_text(source.get("extraction_engine_reason")),
        "indexed_chunk_count": max(0, int(indexed_chunk_count or 0)),
        "vision_analysis": summarize_vision_analysis(source.get("vision_analysis")),
    }


def build_workspace_upload_file_content(filename, document, chunks):
    """Shape the file-content response for a chat upload backed by a workspace document.

    Returns ``(payload, status_code)``. ``file_content`` is always a readable body when the
    response succeeds, so a client that only renders text still has something to show: the
    indexed text when ingestion saved any, otherwise the stored image analysis.
    """
    ordered_chunks = [chunk for chunk in chunks or [] if isinstance(chunk, dict)]
    indexed_text = join_indexed_chunk_text(ordered_chunks)
    details = build_workspace_upload_details(document, len(ordered_chunks))
    body = indexed_text or render_vision_analysis_text(details["vision_analysis"])

    if not body:
        message = (
            STILL_PROCESSING_MESSAGE
            if is_workspace_upload_processing(document if isinstance(document, dict) else {})
            else NO_EXTRACTED_CONTENT_MESSAGE
        )
        return {"error": message, "workspace_document": details}, 404

    return {
        "file_content": body,
        "filename": filename,
        "is_table": False,
        "file_content_source": WORKSPACE_UPLOAD_FILE_CONTENT_SOURCE,
        "indexed_text_available": bool(indexed_text),
        "workspace_document": details,
    }, 200
