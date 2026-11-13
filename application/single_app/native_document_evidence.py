# native_document_evidence.py
"""Bootstrap-free native field states; normalized display values are not source evidence."""

import json
import math
from collections.abc import Mapping


NATIVE_EVIDENCE_SCHEMA_VERSION = "1.0"
NATIVE_FIELD_STATES = frozenset({"absent", "present_empty", "present_value", "inaccessible"})
NATIVE_REPORT_COMMENT_FORMATS = frozenset({"docx", "docm", "dotx", "xlsx", "xlsm", "xls"})
NATIVE_INSPECTION_ERROR_MESSAGES = {
    "native_section_invalid": "The requested native inspection section is not supported for this file.",
    "native_page_size_invalid": "The native inspection page size must be between 1 and 200.",
    "native_response_budget_invalid": "The native inspection response budget is invalid.",
    "native_cursor_invalid": "The native inspection cursor is invalid or belongs to a different source or section.",
    "native_cursor_source_changed": "The native inspection cursor belongs to a different source or section.",
    "native_cursor_out_of_range": "The native inspection cursor is outside the inventory.",
    "native_cursor_fragment_invalid": "The native record continuation is invalid.",
    "native_comments_format_unsupported": (
        "The comments report section supports Word and Excel, not this file format. "
        "Use accessibility, style or issues for supported native metadata and a content reader "
        "for document or presentation reviewer context. This does not mean the source is missing."
    ),
}


class NativeInspectionRequestError(ValueError):
    """A stable request diagnostic, separate from source absence or parsing failure."""

    def __init__(self, code, *, field, rule=None):
        self.code = code
        self.argument_field = field
        self.validation_rule = rule
        self.public_message = NATIVE_INSPECTION_ERROR_MESSAGES[code]
        super().__init__(self.public_message)


def native_report_sections(source_format):
    sections = ["accessibility", "style", "issues"]
    if source_format in NATIVE_REPORT_COMMENT_FORMATS:
        sections.append("comments")
    return sections


def validate_native_report_sections(source_format, sections):
    requested = (
        [value.strip().lower() for value in sections.split(",")]
        if isinstance(sections, str) else [str(value or "").strip().lower() for value in sections or []]
    )
    if "comments" in requested and source_format not in NATIVE_REPORT_COMMENT_FORMATS:
        raise NativeInspectionRequestError(
            "native_comments_format_unsupported", field="sections",
            rule="native_comments_format_unsupported",
        )


def inaccessible_field(reason):
    return {"state": "inaccessible", "value": None, "reason": reason}


def native_field(attributes, name):
    """Inspect an actual native container, preserving false, zero and whitespace."""
    if not isinstance(attributes, Mapping):
        return inaccessible_field("container_unavailable")
    if name not in attributes:
        return {"state": "absent", "value": None}
    value = attributes[name]
    if value is None:
        return inaccessible_field("value_not_decoded")
    if not isinstance(value, (str, bool, int, float)):
        return inaccessible_field("unsupported_value_type")
    if isinstance(value, float) and not math.isfinite(value):
        return inaccessible_field("invalid_native_value")
    return {"state": "present_empty" if value == "" else "present_value", "value": value}


def drawing_native_fields(attributes, decorative=None):
    fields = {
        "description": native_field(attributes, "descr"),
        "title": native_field(attributes, "title"),
        "decorative": native_field(decorative, "val") if decorative is not None
        else {"state": "absent", "value": None},
    }
    return fields


def bound_native_metadata(metadata, max_bytes=450000):
    """Keep the parent a preview; truncation never certifies a complete native inventory."""
    while len(json.dumps(metadata, ensure_ascii=True).encode("utf-8")) > max_bytes:
        lists = []

        def find(value):
            if isinstance(value, dict):
                for child in value.values():
                    find(child)
            elif isinstance(value, list) and value:
                lists.append(value)
        find(metadata)
        metadata["native_parent_truncated"] = True
        metadata["native_parent_coverage"] = "partial; inspect source-backed native pages for full supported records"
        if lists:
            largest = max(lists, key=lambda value: len(json.dumps(value, ensure_ascii=True)))
            largest.pop()
            if "semantic_tag_tree" in metadata:
                metadata["semantic_tag_tree_truncated"] = True
        else:
            def bound_fields(value):
                if not isinstance(value, dict):
                    return
                if value.get("state") in NATIVE_FIELD_STATES and isinstance(value.get("value"), str):
                    if len(value["value"]) > 1000:
                        value.update(inaccessible_field("native_parent_byte_limit"))
                for key, child in list(value.items()):
                    if isinstance(child, str) and len(child) > 4000:
                        value[key] = child[:4000]
                        value[f"{key}_truncated"] = True
                    elif isinstance(child, dict):
                        bound_fields(child)
            before = len(json.dumps(metadata, ensure_ascii=True))
            bound_fields(metadata)
            if len(json.dumps(metadata, ensure_ascii=True)) >= before:
                raise ValueError("Native parent metadata exceeds its byte limit.")
    return metadata
