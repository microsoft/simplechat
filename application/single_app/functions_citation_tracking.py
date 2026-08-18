# functions_citation_tracking.py
"""Track retrieved sources separately from explicitly cited references."""

import html
import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit


CITATION_TRACKING_VERSION = 1
USED_DOCUMENTS_TRACKING_VERSION = 1

_INLINE_DOCUMENT_CITATION_GROUP_PATTERN = re.compile(
    r"\[\s*#([^\]\r\n]+)\]",
    re.IGNORECASE,
)
_INLINE_DOCUMENT_SOURCE_PATTERN = re.compile(
    r"\(Source:\s*(.+?),\s*(Page(?:s)?|Sheet(?:s)?|Location):\s*(.*?)\)"
    r"(?=\s*(?:\[#|$|[.;,!? \n]))",
    re.IGNORECASE,
)
_HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?"
_MERGED_DOCUMENT_LIST_FIELDS = (
    "chunk_ids",
    "citation_ids",
    "page_numbers",
    "sheet_names",
)


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _append_unique(values: List[Any], value: Any) -> None:
    if value in (None, "") or value in values:
        return
    values.append(deepcopy(value))


def _append_unique_mapping(values: List[Dict[str, Any]], value: Dict[str, Any]) -> None:
    if not value or value in values:
        return
    values.append(deepcopy(value))


def _normalize_reference_id(value: Any) -> str:
    return str(value or "").strip().lstrip("#").strip()


def extract_explicit_document_citation_ids(content: Any) -> List[str]:
    """Return ordered, unique citation IDs from explicit ``[#id]`` groups."""
    citation_ids: List[str] = []
    for citation_group in _INLINE_DOCUMENT_CITATION_GROUP_PATTERN.findall(
        str(content or "")
    ):
        for raw_citation_id in re.split(r"[;,]", citation_group):
            citation_id = _normalize_reference_id(raw_citation_id)
            if citation_id and citation_id not in citation_ids:
                citation_ids.append(citation_id)
    return citation_ids


def _normalize_source_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip().lower()


def _extract_explicit_document_source_references(
    content: Any,
) -> List[Dict[str, str]]:
    references = []
    for file_name, location_label, location_value in (
        _INLINE_DOCUMENT_SOURCE_PATTERN.findall(str(content or ""))
    ):
        normalized_file_name = _normalize_source_text(file_name)
        normalized_location_label = (
            _normalize_source_text(location_label).rstrip("s")
        )
        normalized_location_value = _normalize_source_text(location_value)
        if (
            normalized_file_name
            and normalized_location_label
            and normalized_location_value
        ):
            references.append({
                "file_name": normalized_file_name,
                "location_label": normalized_location_label,
                "location_value": normalized_location_value,
            })
    return references


def _parse_numeric_location(value: Any) -> Optional[int]:
    normalized_value = _normalize_source_text(value)
    if not normalized_value or not normalized_value.isdigit():
        return None
    return int(normalized_value)


def _location_reference_matches(
    explicit_location: str,
    citation_location: Any,
) -> bool:
    normalized_citation_location = _normalize_source_text(citation_location)
    if not normalized_citation_location:
        return False
    if normalized_citation_location == explicit_location:
        return True

    explicit_tokens = [
        token.strip()
        for token in re.split(r"[,;]", explicit_location)
        if token.strip()
    ]
    if normalized_citation_location in explicit_tokens:
        return True

    citation_number = _parse_numeric_location(normalized_citation_location)
    if citation_number is None:
        return False

    for token in explicit_tokens:
        range_match = re.fullmatch(r"(\d+)\s*[-\u2013\u2014]\s*(\d+)", token)
        if not range_match:
            continue
        range_start, range_end = (
            int(range_match.group(1)),
            int(range_match.group(2)),
        )
        lower_bound = min(range_start, range_end)
        upper_bound = max(range_start, range_end)
        if lower_bound <= citation_number <= upper_bound:
            return True
    return False


def resolve_citation_location(
    page_number: Any = None,
    chunk_text: Any = None,
    sheet_name: Any = None,
    is_tabular: bool = False,
) -> tuple[str, str]:
    """Return a schema-, sheet-, or page-aware citation location."""
    if sheet_name not in (None, ""):
        return "Sheet", str(sheet_name)

    normalized_chunk_text = str(chunk_text or "").strip()
    if is_tabular and (
        normalized_chunk_text.startswith("Tabular workbook:")
        or normalized_chunk_text.startswith("Tabular data file:")
    ):
        return "Location", "Workbook Schema"

    return "Page", str(page_number or 1)


def _source_reference_matches_citation(
    source_reference: Mapping[str, str],
    citation: Mapping[str, Any],
) -> bool:
    citation_file_name = _normalize_source_text(
        citation.get("file_name")
        or citation.get("title")
    )
    if (
        not citation_file_name
        or citation_file_name != source_reference.get("file_name")
    ):
        return False

    explicit_label = source_reference.get("location_label")
    citation_label = _normalize_source_text(citation.get("location_label"))
    if not citation_label:
        citation_label = "sheet" if citation.get("sheet_name") else "page"
    citation_label = citation_label.rstrip("s")
    if explicit_label != "location" and citation_label != explicit_label:
        return False

    location_candidates = (
        citation.get("location_value"),
        citation.get("sheet_name"),
        citation.get("page_number"),
        citation.get("chunk_sequence"),
    )
    return any(
        _location_reference_matches(
            source_reference.get("location_value", ""),
            candidate,
        )
        for candidate in location_candidates
    )


def _trim_url_candidate(value: Any) -> str:
    candidate = html.unescape(str(value or "")).strip()
    while candidate and candidate[-1] in _TRAILING_URL_PUNCTUATION:
        candidate = candidate[:-1]
    while candidate.endswith(")") and candidate.count(")") > candidate.count("("):
        candidate = candidate[:-1]
    while candidate.endswith("]") and candidate.count("]") > candidate.count("["):
        candidate = candidate[:-1]
    return candidate


def normalize_http_url(value: Any) -> str:
    """Normalize an HTTP(S) URL for exact response-to-source matching."""
    candidate = _trim_url_candidate(value)
    if not candidate:
        return ""

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return ""

    hostname = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    path = parsed.path or ""
    if path == "/":
        path = ""

    return urlunsplit((scheme, hostname, path, parsed.query, ""))


def extract_explicit_web_urls(content: Any) -> List[str]:
    """Return ordered, unique normalized HTTP(S) URLs from final response text."""
    normalized_urls: List[str] = []
    for raw_url in _HTTP_URL_PATTERN.findall(str(content or "")):
        normalized_url = normalize_http_url(raw_url)
        if normalized_url and normalized_url not in normalized_urls:
            normalized_urls.append(normalized_url)
    return normalized_urls


def _get_document_citation_id(citation: Mapping[str, Any]) -> str:
    return _normalize_reference_id(
        citation.get("citation_id")
        or citation.get("id")
    )


def _get_web_citation_url(citation: Mapping[str, Any]) -> str:
    return normalize_http_url(
        citation.get("url")
        or citation.get("href")
        or citation.get("link")
    )


def build_cited_source_subsets(
    content: Any,
    hybrid_citations: Any = None,
    web_search_citations: Any = None,
) -> Dict[str, Any]:
    """Match explicit final-response references to returned source records."""
    document_citation_ids = set(extract_explicit_document_citation_ids(content))
    document_source_references = _extract_explicit_document_source_references(
        content
    )
    explicit_web_urls = set(extract_explicit_web_urls(content))

    hybrid_source_records = _as_dict_list(hybrid_citations)
    exact_document_citations = [
        citation
        for citation in hybrid_source_records
        if _get_document_citation_id(citation) in document_citation_ids
    ]
    unmatched_source_references = [
        source_reference
        for source_reference in document_source_references
        if not any(
            _source_reference_matches_citation(
                source_reference,
                exact_citation,
            )
            for exact_citation in exact_document_citations
        )
    ]

    cited_hybrid_citations: List[Dict[str, Any]] = []
    seen_document_citations = set()
    for citation in hybrid_source_records:
        citation_id = _get_document_citation_id(citation)
        matched_by_id = bool(
            citation_id
            and citation_id in document_citation_ids
        )
        matched_by_source = any(
            _source_reference_matches_citation(source_reference, citation)
            for source_reference in unmatched_source_references
        )
        if not matched_by_id and not matched_by_source:
            continue
        if matched_by_id:
            identity = (
                "citation_id",
                citation_id,
                str(citation.get("document_id") or ""),
                str(citation.get("chunk_id") or ""),
            )
        else:
            identity = (
                "source_location",
                _extract_document_id(citation),
                _normalize_source_text(
                    citation.get("file_name")
                    or citation.get("title")
                ),
                _normalize_source_text(
                    citation.get("location_value")
                    or citation.get("sheet_name")
                    or citation.get("page_number")
                    or citation.get("chunk_sequence")
                ),
            )
        if identity in seen_document_citations:
            continue
        seen_document_citations.add(identity)
        cited_hybrid_citations.append(citation)

    cited_web_search_citations: List[Dict[str, Any]] = []
    seen_web_urls = set()
    for citation in _as_dict_list(web_search_citations):
        normalized_url = _get_web_citation_url(citation)
        if (
            not normalized_url
            or normalized_url not in explicit_web_urls
            or normalized_url in seen_web_urls
        ):
            continue
        seen_web_urls.add(normalized_url)
        cited_web_search_citations.append(citation)

    return {
        "citation_tracking_version": CITATION_TRACKING_VERSION,
        "cited_hybrid_citations": cited_hybrid_citations,
        "cited_web_search_citations": cited_web_search_citations,
    }


def _message_has_citation_tracking(message: Mapping[str, Any]) -> bool:
    tracking_version = message.get("citation_tracking_version")
    if isinstance(tracking_version, int) and tracking_version >= 1:
        return True
    return (
        "cited_hybrid_citations" in message
        or "cited_web_search_citations" in message
    )


def get_message_source_citation_buckets(
    message: Optional[Mapping[str, Any]],
) -> Dict[str, List[Any]]:
    """Return complete stored source/execution buckets for audit and Sources UI."""
    safe_message = message if isinstance(message, Mapping) else {}

    def ensure_list(value: Any) -> List[Any]:
        if not value:
            return []
        return deepcopy(value) if isinstance(value, list) else [deepcopy(value)]

    return {
        "legacy": ensure_list(safe_message.get("citations")),
        "hybrid": ensure_list(safe_message.get("hybrid_citations")),
        "web": ensure_list(safe_message.get("web_search_citations")),
        "agent": ensure_list(safe_message.get("agent_citations")),
    }


def get_message_reference_citation_buckets(
    message: Optional[Mapping[str, Any]],
) -> Dict[str, List[Any]]:
    """Return exact references, with broad source fallback for legacy messages."""
    safe_message = message if isinstance(message, Mapping) else {}
    source_buckets = get_message_source_citation_buckets(safe_message)
    if not _message_has_citation_tracking(safe_message):
        return source_buckets

    referenced_agent_citations = []
    for citation in source_buckets["agent"]:
        if (
            isinstance(citation, Mapping)
            and str(citation.get("function_name") or "").strip().lower()
            == "azure_ai_foundry_web_search"
        ):
            continue
        referenced_agent_citations.append(deepcopy(citation))

    return {
        "legacy": source_buckets["legacy"],
        "hybrid": _as_dict_list(safe_message.get("cited_hybrid_citations")),
        "web": _as_dict_list(safe_message.get("cited_web_search_citations")),
        "agent": referenced_agent_citations,
    }


def _extract_document_id(citation: Mapping[str, Any]) -> str:
    document_id = str(citation.get("document_id") or "").strip()
    if document_id:
        return document_id

    citation_id = _get_document_citation_id(citation)
    if not citation_id:
        return ""
    if "_" in citation_id:
        return citation_id.rsplit("_", 1)[0]
    return citation_id


def _get_document_tags(conversation: Mapping[str, Any]) -> List[Dict[str, Any]]:
    tags = conversation.get("tags")
    if not isinstance(tags, list):
        return []
    return [
        deepcopy(tag)
        for tag in tags
        if isinstance(tag, dict)
        and tag.get("category") == "document"
        and str(tag.get("document_id") or "").strip()
    ]


def _scope_from_citation(citation: Mapping[str, Any]) -> Dict[str, Any]:
    raw_scope = citation.get("scope")
    if isinstance(raw_scope, dict):
        scope_type = str(
            raw_scope.get("type")
            or raw_scope.get("scope")
            or ""
        ).strip()
        scope_id = str(
            raw_scope.get("id")
            or raw_scope.get("scope_id")
            or ""
        ).strip()
        if scope_type and scope_id:
            scope = {
                "type": scope_type,
                "id": scope_id,
            }
            scope_name = str(raw_scope.get("name") or "").strip()
            if scope_name:
                scope["name"] = scope_name
            return scope

    public_workspace_id = str(
        citation.get("public_workspace_id") or ""
    ).strip()
    if public_workspace_id:
        return {"type": "public", "id": public_workspace_id}

    group_id = str(citation.get("group_id") or "").strip()
    if group_id:
        return {"type": "group", "id": group_id}

    user_id = str(citation.get("user_id") or "").strip()
    if user_id:
        return {"type": "personal", "id": user_id}
    return {}


def _merge_document_record(
    target: Dict[str, Any],
    incoming: Mapping[str, Any],
) -> Dict[str, Any]:
    for field_name in _MERGED_DOCUMENT_LIST_FIELDS:
        target_values = target.setdefault(field_name, [])
        incoming_values = incoming.get(field_name)
        if not isinstance(incoming_values, list):
            continue
        for value in incoming_values:
            _append_unique(target_values, value)

    target_locations = target.setdefault("citation_locations", [])
    incoming_locations = incoming.get("citation_locations")
    if isinstance(incoming_locations, list):
        for location in incoming_locations:
            if isinstance(location, dict):
                _append_unique_mapping(target_locations, location)

    for field_name in (
        "title",
        "file_name",
        "classification",
        "scope",
    ):
        current_value = target.get(field_name)
        incoming_value = incoming.get(field_name)
        if current_value in (None, "", {}, "Unknown Document") and incoming_value not in (
            None,
            "",
            {},
        ):
            target[field_name] = deepcopy(incoming_value)
    return target


def build_used_documents(
    cited_hybrid_citations: Any,
    source_document_tags: Any = None,
) -> List[Dict[str, Any]]:
    """Collapse exact cited chunks into document-level used-document records."""
    tag_by_document_id = {
        str(tag.get("document_id") or "").strip(): tag
        for tag in _as_dict_list(source_document_tags)
        if str(tag.get("document_id") or "").strip()
    }
    documents_by_id: Dict[str, Dict[str, Any]] = {}

    for citation in _as_dict_list(cited_hybrid_citations):
        document_id = _extract_document_id(citation)
        if not document_id:
            continue

        document = documents_by_id.get(document_id)
        if document is None:
            source_tag = tag_by_document_id.get(document_id)
            document = deepcopy(source_tag) if source_tag else {
                "category": "document",
                "document_id": document_id,
            }
            document["category"] = "document"
            document["document_id"] = document_id
            document["chunk_ids"] = []
            document["citation_ids"] = []
            document["page_numbers"] = []
            document["sheet_names"] = []
            document["citation_locations"] = []
            documents_by_id[document_id] = document

        citation_id = _get_document_citation_id(citation)
        _append_unique(document["citation_ids"], citation_id)
        _append_unique(
            document["chunk_ids"],
            citation_id or citation.get("chunk_id"),
        )
        _append_unique(document["page_numbers"], citation.get("page_number"))
        _append_unique(document["sheet_names"], citation.get("sheet_name"))

        location = {
            key: deepcopy(citation.get(key))
            for key in (
                "citation_id",
                "chunk_id",
                "page_number",
                "sheet_name",
                "location_label",
                "location_value",
            )
            if citation.get(key) not in (None, "")
        }
        _append_unique_mapping(document["citation_locations"], location)

        incoming_metadata = {
            "title": citation.get("title") or citation.get("file_name"),
            "file_name": citation.get("file_name") or citation.get("title"),
            "classification": (
                citation.get("classification")
                or citation.get("document_classification")
            ),
            "scope": _scope_from_citation(citation),
        }
        _merge_document_record(document, incoming_metadata)

    return list(documents_by_id.values())


def merge_used_documents(
    existing_documents: Any,
    incoming_documents: Any,
) -> List[Dict[str, Any]]:
    """Merge exact used-document aggregates without losing cited locations."""
    merged_by_id: Dict[str, Dict[str, Any]] = {}
    for document in [
        *_as_dict_list(existing_documents),
        *_as_dict_list(incoming_documents),
    ]:
        document_id = str(document.get("document_id") or "").strip()
        if not document_id:
            continue
        if document_id not in merged_by_id:
            merged_by_id[document_id] = deepcopy(document)
            continue
        _merge_document_record(merged_by_id[document_id], document)
    return list(merged_by_id.values())


def initialize_conversation_used_document_tracking(
    conversation: Dict[str, Any],
) -> bool:
    """Snapshot legacy document tags before the first strictly tracked turn."""
    if not isinstance(conversation, dict):
        return False
    tracking_version = conversation.get("used_documents_tracking_version")
    if isinstance(tracking_version, int) and tracking_version >= 1:
        return False

    conversation["used_documents_tracking_version"] = (
        USED_DOCUMENTS_TRACKING_VERSION
    )
    conversation["legacy_used_documents"] = _get_document_tags(conversation)
    conversation["used_documents"] = []
    return True


def merge_cited_documents_into_conversation(
    conversation: Dict[str, Any],
    cited_hybrid_citations: Any,
) -> List[Dict[str, Any]]:
    """Merge one finalized assistant response into exact conversation usage."""
    initialize_conversation_used_document_tracking(conversation)
    source_document_tags = _get_document_tags(conversation)
    incoming_documents = build_used_documents(
        cited_hybrid_citations,
        source_document_tags=source_document_tags,
    )
    conversation["used_documents"] = merge_used_documents(
        conversation.get("used_documents"),
        incoming_documents,
    )
    return deepcopy(conversation["used_documents"])


def _message_is_active_assistant(message: Mapping[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    metadata = message.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    if metadata.get("is_deleted") is True:
        return False
    if metadata.get("is_generated_chat_artifact") is True:
        return False
    thread_info = metadata.get("thread_info")
    thread_info = thread_info if isinstance(thread_info, Mapping) else {}
    return thread_info.get("active_thread") is not False


def rebuild_conversation_used_documents(
    conversation: Dict[str, Any],
    messages: Iterable[Mapping[str, Any]],
    rebuild_legacy: bool = False,
) -> List[Dict[str, Any]]:
    """Rebuild exact usage after a retry, switch, deletion, or fork mutation."""
    initialize_conversation_used_document_tracking(conversation)
    cited_hybrid_citations: List[Dict[str, Any]] = []
    legacy_hybrid_citations: List[Dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, Mapping) or not _message_is_active_assistant(message):
            continue
        if _message_has_citation_tracking(message):
            cited_hybrid_citations.extend(
                _as_dict_list(message.get("cited_hybrid_citations"))
            )
        elif rebuild_legacy:
            legacy_hybrid_citations.extend(
                _as_dict_list(message.get("hybrid_citations"))
            )

    source_document_tags = _get_document_tags(conversation)
    conversation["used_documents"] = build_used_documents(
        cited_hybrid_citations,
        source_document_tags=source_document_tags,
    )
    if rebuild_legacy:
        conversation["legacy_used_documents"] = build_used_documents(
            legacy_hybrid_citations,
            source_document_tags=source_document_tags,
        )
    return deepcopy(conversation["used_documents"])
