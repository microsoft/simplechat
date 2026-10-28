# functions_evidence_status.py
"""Public, per-answer evidence status derived from authorized execution records."""


STATUS_SUGGESTIONS = {
    "partial": [
        "Check the source details for the unanswered part.",
        "Add a relevant document or select another authorized source for that part.",
    ],
    "missing": [
        "Add a document that addresses the question, or select another authorized source.",
        "Clarify the item or time range to search.",
    ],
    "unavailable": [
        "Use an available recovery action for the affected source, or select another authorized source.",
    ],
    "pending": ["Wait for the remaining source work before treating this answer as complete."],
}

STATUS_NOTICES = {
    "partial": "Partial document evidence",
    "missing": "No supporting document evidence returned",
    "unavailable": "Some sources could not be checked",
    "pending": "Evidence is still pending",
}


def append_export_evidence_notice(content, message):
    """Keep material source limitations when a rendered answer leaves the UI."""
    if not isinstance(content, str) or message.get("role") != "assistant" or content.strip() == "[masked]":
        return content
    metadata = message.get("metadata")
    status = metadata.get("evidence_status") if isinstance(metadata, dict) else None
    if not isinstance(status, dict) or status.get("version") != 1 or status.get("scope") != "returned_evidence":
        return content
    state = status.get("state")
    label = STATUS_NOTICES.get(state) if isinstance(state, str) else None
    notice = f"Evidence: {label}." if label else ""
    return f"{content}\n\n{notice}" if notice and notice not in content else content


def evidence_status_from_sources(sources, *, partial=False):
    """Aggregate known source outcomes without confusing an error with no matches."""
    if not sources:
        return None
    states = [source["state"] for source in sources]
    if all(state == "missing" for state in states):
        state = "missing"
    elif all(state == "complete" for state in states) and not partial:
        state = "complete"
    elif any(state in {"complete", "partial"} for state in states):
        state = "partial"
    elif "pending" in states:
        state = "pending"
    elif "unavailable" in states:
        state = "unavailable"
    else:
        state = "unknown"
    return {
        "version": 1,
        "scope": "returned_evidence",
        "state": state,
        "sources": sources[:100],
        "source_count": len(sources),
        "suggestions": list(STATUS_SUGGESTIONS.get(state, ())),
    }


def build_mixed_source_evidence_status(manifest, entries, envelopes, *, partial=False):
    """Project only source labels already authorized by the manifest owner."""
    if len(manifest) != len(entries):
        raise ValueError("Evidence status must match the complete selected-source ledger.")
    sources = []
    for index, (source, entry) in enumerate(zip(manifest, entries), start=1):
        authorized = source.get("authorization_status") == "authorized"
        row = {
            "name": str(source.get("display_name") or f"Selected source {index}")[:160]
            if authorized else f"Unavailable selected source {index}",
            "state": "unknown",
        }
        if authorized and isinstance(source.get("document_id"), str):
            row["document_id"] = source["document_id"]
        status = entry.get("status")
        if not authorized or status in {"failed", "skipped", "canceled"}:
            row["state"] = "unavailable"
        elif status == "pending":
            row["state"] = "pending"
        else:
            matches = [
                envelope for envelope in envelopes
                if envelope.get("document_id") == source.get("document_id")
            ]
            if len(matches) == 1:
                envelope = matches[0]
                coverage = envelope.get("coverage") or {}
                count = coverage.get("result_count")
                if type(count) is int and 0 <= count < 2 ** 53:
                    row["evidence_count"] = count
                if coverage.get("terminal") is True and type(count) is int and count == 0:
                    row["state"] = "missing"
                elif envelope.get("evidence") or type(count) is int and count > 0:
                    row["state"] = "partial" if status == "partial" else "complete"
        sources.append(row)
    return evidence_status_from_sources(sources, partial=partial)
