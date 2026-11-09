# native_document_evidence.py
"""Bootstrap-free native field states; normalized display values are not source evidence."""

import json
import math
from collections.abc import Mapping


NATIVE_EVIDENCE_SCHEMA_VERSION = "1.0"
NATIVE_FIELD_STATES = frozenset({"absent", "present_empty", "present_value", "inaccessible"})


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
