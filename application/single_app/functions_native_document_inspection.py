# functions_native_document_inspection.py
"""Local, source-bound native PDF/PPTX inspection with bounded continuations."""

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from functions_accessibility import extract_office_accessibility_metadata, extract_pdf_accessibility_metadata
from native_document_evidence import NativeInspectionRequestError


NATIVE_DOCUMENT_INSPECTION_VERSION = "1.1"
NATIVE_DOCUMENT_MAX_BYTES = 64 * 1024 * 1024
NATIVE_DOCUMENT_SECTIONS = frozenset({"all", "properties", "structure", "objects", "artifacts", "content", "issues"})


def has_retained_native_source(document):
    return bool(
        document.get("blob_path") or document.get("archived_blob_path")
        or document.get("source_file_available") or document.get("enhanced_citations")
        or (document.get("content_screening") or {}).get("active_blob")
    )


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _native_records(metadata, details):
    records = [
        {"section": "properties", "id": f"property:{name}", "field": name, **field}
        for name, field in metadata.get("native_properties", {}).items()
    ]
    if metadata.get("native_catalog") is not None:
        records.append({"section": "properties", "id": "pdf:catalog", **metadata["native_catalog"]})
    nodes = {node["node_id"]: node for node in metadata.get("semantic_tag_tree", [])}
    for detail in details.values():
        nodes.update({node["node_id"]: node for node in detail.get("tag_nodes", [])})
    records.extend(
        {"section": "structure", "id": node["node_id"], **node}
        for node in sorted(nodes.values(), key=lambda node: int(node["node_id"].rsplit(":", 1)[-1]))
    )
    for detail in details.values():
        records.extend(
            {"section": "content", **record}
            for record in detail.get("native_annotations", {}).get("records", [])
        )
        for content in detail.get("native_content", {}).get("records", []):
            section = "artifacts" if content["kind"] == "artifact" else "objects" if (
                content["raster_placements"] or content["vector_paint_operations"]
            ) else "content"
            records.append({"section": section, **content})
        records.extend(
            {"section": "objects", **record} for record in detail.get("native_objects", {}).get("records", [])
        )
    records.extend(
        {"section": "issues", "id": f"issue:{index}", **issue}
        for index, issue in enumerate(metadata.get("issues", []))
    )
    return records


def inspect_native_document(document, source_bytes, extension, *, section="all", cursor=None,
                            page_size=100, max_bytes=14000, _audit_records=None):
    """The owner must authorize the active bytes before and after this pure local read."""
    if extension not in (".pdf", ".pptx") or not isinstance(source_bytes, bytes):
        raise ValueError("A supported native document and its source bytes are required.")
    if not source_bytes or len(source_bytes) > NATIVE_DOCUMENT_MAX_BYTES:
        raise ValueError("The native document exceeds its inspection byte limit or is empty.")
    section = "all" if section == "comments" else section
    if section not in NATIVE_DOCUMENT_SECTIONS:
        raise NativeInspectionRequestError("native_section_invalid", field="native_section")
    if type(page_size) is not int or not 1 <= page_size <= 200:
        raise NativeInspectionRequestError("native_page_size_invalid", field="native_page_size")
    if type(max_bytes) is not int or not 2048 <= max_bytes <= 65536:
        raise NativeInspectionRequestError("native_response_budget_invalid", field="max_bytes")
    digest = hashlib.sha256(source_bytes).hexdigest()
    identity = {
        "document_id": document["id"], "version": document.get("version"),
        "revision": document.get("_etag"), "source_sha256": digest,
        "schema_version": NATIVE_DOCUMENT_INSPECTION_VERSION, "section": section,
    }
    offset = fragment = 0
    if cursor:
        try:
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise ValueError("Invalid native cursor")
            value = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
            if type(value) is not dict or set(value) != {*identity, "offset", "fragment"}:
                raise ValueError("Invalid native cursor")
            offset, fragment = value["offset"], value["fragment"]
            if any(type(number) is not int or number < 0 for number in (offset, fragment)):
                raise ValueError("Invalid native cursor offset")
        except (ValueError, TypeError, UnicodeError) as error:
            raise NativeInspectionRequestError("native_cursor_invalid", field="native_cursor") from error
        for key, expected in identity.items():
            if value[key] != expected:
                raise NativeInspectionRequestError(
                    "native_cursor_source_changed", field="native_cursor",
                    rule=f"native_cursor_{key}_changed",
                )
    with tempfile.TemporaryDirectory(prefix="simplechat_native_inspection_") as folder:
        path = Path(folder) / ("source" + extension)
        path.write_bytes(source_bytes)
        metadata, details = (
            extract_pdf_accessibility_metadata(str(path)) if extension == ".pdf"
            else extract_office_accessibility_metadata(str(path), extension)
        )
    if metadata.get("native_inspection_status") == "inaccessible":
        raise ValueError("The native document could not be inspected.")
    if extension == ".pptx" and not metadata.get("native_package_verified"):
        raise ValueError("The source is not a supported native presentation package.")
    if metadata.get("source_sha256") != digest:
        raise ValueError("The native inspection does not match the authorized source bytes.")
    records = [
        record for record in _native_records(metadata, details)
        if section == "all" or record["section"] == section
    ]
    total = len(records)
    start_record, start_fragment = offset, fragment
    if offset > total or offset == total and fragment:
        raise NativeInspectionRequestError("native_cursor_out_of_range", field="native_cursor")
    returned, used = [], 0
    budget = max_bytes - 1536
    while offset < total and len(returned) < page_size:
        record = records[offset]
        encoded = _encoded(record)
        if returned and used + len(encoded) > budget:
            break
        if fragment or len(encoded) > budget:
            serialized = encoded.decode("utf-8")
            if fragment >= len(serialized):
                raise NativeInspectionRequestError("native_cursor_fragment_invalid", field="native_cursor")
            low, high, selected = 1, len(serialized) - fragment, None
            while low <= high:
                middle = (low + high) // 2
                candidate = {
                    "id": record["id"], "section": record["section"], "record_fragment": True,
                    "fragment_offset": fragment, "record_characters": len(serialized),
                    "record_json_fragment": serialized[fragment:fragment + middle],
                }
                if len(_encoded(candidate)) <= budget:
                    selected, low = candidate, middle + 1
                else:
                    high = middle - 1
            if selected is None:
                raise ValueError("The native record cannot fit the requested response budget.")
            returned.append(selected)
            if _audit_records is not None:
                _audit_records.append(record)
            fragment += len(selected["record_json_fragment"])
            if fragment == len(serialized):
                offset, fragment = offset + 1, 0
            break
        returned.append(record)
        if _audit_records is not None:
            _audit_records.append(record)
        used += len(encoded)
        offset += 1
    more = offset < total or bool(fragment)
    next_cursor = base64.urlsafe_b64encode(
        _encoded({**identity, "offset": offset, "fragment": fragment})
    ).decode("ascii").rstrip("=") if more else None
    complete = metadata.get("native_inspection_status") == "complete" and not metadata.get("native_parent_truncated")
    return {
        "metadata": metadata,
        "page": {
            "section": section, "records": returned, "total_records": total,
            "start_record": start_record, "fragment_offset": start_fragment,
            "source_sha256": digest, "schema_version": NATIVE_DOCUMENT_INSPECTION_VERSION,
            "inventory_complete": complete, "has_more": more, "next_cursor": next_cursor,
            "coverage": "supported native records only; not a rendered or conformance audit",
        },
    }
