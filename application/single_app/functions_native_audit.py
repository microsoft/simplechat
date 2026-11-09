# functions_native_audit.py
"""Native audit facts and deterministic claim validation, not prose-pattern matching."""

import hashlib
import json
from copy import deepcopy

from native_document_evidence import NATIVE_FIELD_STATES, inaccessible_field


NATIVE_AUDIT_VERSION = "native-audit-v1"
MAX_AUDIT_FACTS = 1000
MAX_AUDIT_BYTES = 100000


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def build_native_audit(payload):
    metadata = payload.get("accessibility_metadata") or {}
    if metadata.get("format") not in ("pdf", "pptx", "xlsx", "xlsm", "xls"):
        return None
    legacy = metadata.get("format") in ("pdf", "pptx") and metadata.get("schema_version") != "2.0"
    if not legacy and not metadata.get("native_properties") and not metadata.get("objects"):
        return None
    document = payload.get("document") or {}
    source_hash = metadata.get("source_sha256") or (metadata.get("inventory_storage") or {}).get("source_sha256")
    facts, identities, used = [], set(), 0
    omitted = False

    def add(identity, location, field, value, state="present_value", reason=None):
        nonlocal used, omitted
        if identity in identities:
            return
        key = hashlib.sha256(_encoded([document.get("id"), source_hash, identity]).encode()).hexdigest()[:24]
        fact = {
            "id": key, "location": f"{document.get('file_name') or 'Selected document'}; {location}",
            "field": field, "state": state, "value": value,
            "value_sha256": hashlib.sha256(_encoded(value).encode()).hexdigest(),
            "reason": reason,
        }
        size = len(_encoded(fact).encode())
        if len(facts) >= MAX_AUDIT_FACTS or used + size > MAX_AUDIT_BYTES:
            omitted = True
            return
        identities.add(identity)
        used += size
        facts.append(fact)

    def fields(identity, location, values):
        for name, value in values.items():
            if not isinstance(value, dict) or value.get("state") not in NATIVE_FIELD_STATES:
                value = inaccessible_field("legacy_native_state_unavailable")
            source_location = f"{location}; {value['source']}" if value.get("source") else location
            add(f"{identity}:{name}", source_location, name, value.get("value"), value["state"], value.get("reason"))

    if legacy:
        fields("legacy", "Native source not freshly inspected", {
            name: inaccessible_field("legacy_source_state_unavailable")
            for name in ("title", "author", "keywords", "attribute_presence", "content_bindings")
        })
        add("legacy_flags", "Stored legacy snapshot, not native-container verification", "stored_flags", {
            key: metadata[key] for key in ("is_tagged", "has_struct_tree") if key in metadata
        })
        return {
            "version": NATIVE_AUDIT_VERSION, "file_name": document.get("file_name"),
            "source_sha256": None, "facts": facts, "facts_omitted": False, "has_more": False,
            "limitations": [
                "The retained native source was not available for fresh inspection. Legacy normalized "
                "values do not establish native attribute presence, emptiness or text-to-tag bindings.",
            ],
        }
    fields("properties", "Native file properties", metadata.get("native_properties") or {})
    if metadata.get("format") == "pdf":
        add("catalog", "PDF catalog", "catalog_and_tagged_state", {
            **metadata.get("native_catalog", {}),
            "is_tagged": metadata.get("is_tagged"), "has_struct_tree": metadata.get("has_struct_tree"),
        })
        for order, node in enumerate(metadata.get("semantic_tag_tree", []), 1):
            identity = node.get("node_id") or f"structure:{order}"
            location = f"Page {node.get('page_number')}; {identity}"
            bound = node.get("bound_text") or inaccessible_field("no_direct_content_binding")
            add(identity, location, "logical_element", {
                "logical_order": order, "tag": node.get("tag"),
                "content_references": node.get("content_refs", []),
                "text": bound.get("value"), "text_state": bound["state"],
                **{key: node[key] for key in ("scope", "col_span", "row_span", "headers", "lang") if key in node},
            })
            fields(identity, location, node.get("native_fields") or {})
        for index, table in enumerate((metadata.get("tables_summary") or {}).get("items", [])):
            add(f"table:{index}", f"Page {table.get('page_number')}; table {index + 1}", "native_table", table)
        graphics = metadata.get("graphics_summary") or {}
        add("graphics", "Native content streams", "observed_graphics", {
            key: graphics.get(key) for key in ("raster_placements", "vector_groups", "coverage", "items_truncated")
        })
        for graphic in graphics.get("items", []):
            add(f"graphic:{graphic['id']}", f"Page {graphic['page_number']}; {graphic['id']}", "native_graphic", {
                key: graphic.get(key) for key in ("mcid", "stream_id", "tag", "raster_placements", "vector_paint_operations")
            })
        for index, artifact in enumerate((metadata.get("artifacts_summary") or {}).get("items", [])):
            identity = artifact.get("id") or f"artifact:{index}"
            location = f"Page {artifact.get('page_number')}; {identity}"
            add(identity, location, "artifact_text", artifact.get("text"), artifact.get("text_state", "inaccessible"))
            fields(identity, location, artifact.get("native_fields", {}))
        for record in metadata.get("unmarked_text", []):
            add(record["id"], f"Page {record['page_number']}; {record['id']}", "unmarked_text",
                record["text"], record["text_state"])
    objects = (metadata.get("objects_summary") or {}).get("items", metadata.get("objects") or [])
    page = (payload.get("native_inspection") or payload.get("excel_inspection") or {}).get("page") or {}
    if page.get("section") == "objects" and metadata.get("format") != "pdf":
        objects = [record for record in page.get("records", []) if not record.get("record_fragment")]
    for index, obj in enumerate(objects):
        identity = str(obj.get("id") or f"object:{index}")
        location = (
            f"{obj.get('sheet')}!{obj.get('cell')}" if obj.get("sheet")
            else f"Slide {obj.get('slide_number')}; object {obj.get('object_id')}"
        )
        identity = f"{location}:{identity}"
        add(identity, location, "native_object", {
            key: obj.get(key) for key in (
                "name", "kind", "type", "geometry", "source_part", "content_origin",
                "placeholder", "is_decorative", "control_representation", "control_type_state", "checked", "checked_state",
                "transform", "parent_id",
                "drawing_part", "object_id", "style_id", "feature_property_bag_part", "feature_bag_path",
            ) if key in obj
        })
        fields(identity, location, obj.get("native_fields") or {
            "description": inaccessible_field("legacy_native_state_unavailable"),
            "title": inaccessible_field("legacy_native_state_unavailable"),
        })
        for index, run in enumerate(obj.get("text_runs", [])):
            add(f"{identity}:run:{index}", location, "text_style", {
                "text": run["text"], "text_complete": run["text_complete"],
                "style": {key: field["value"] for key, field in run["native_fields"].items()},
                "style_field_states": {key: field["state"] for key, field in run["native_fields"].items()},
                "style_origins": run["style_origins"],
                "contrast": run.get("contrast"),
            })
    for sheet in metadata.get("sheets", []):
        add(f"sheet:{sheet['name']}", sheet["name"], "saved_layout_and_print", {
            key: sheet.get(key) for key in ("layout", "header_footer", "state")
        })
        for group in sheet.get("saved_styles", []):
            add(f"sheet:{sheet['name']}:style:{group['style_id']}", sheet["name"], "saved_cell_style", group)
    for cell in (payload.get("excel_inspection") or {}).get("cells", []):
        location = f"{cell['sheet']}!{cell['cell']}"
        add(f"saved-cell:{location}", location, "saved_cell_record", cell)
    style = payload.get("style_inventory") or metadata.get("style_inventory")
    if style:
        add("style_summary", "Native formatting inspection", "observed_style_summary", {
            key: style[key] for key in (
                "coverage", "coverage_notes", "body_font", "body_size_pt", "fonts", "font_sizes",
                "colors", "emphasis", "non_embedded_fonts",
            ) if key in style
        })
    for index, issue in enumerate(payload.get("issues", metadata.get("issues", []))):
        add(f"issue:{index}", "Native inspection issues", "reported_issue", issue)
    add(f"coverage:{page.get('section')}:{page.get('start_record')}:{page.get('fragment_offset')}",
        "Inspection coverage", "coverage", {
        "native_status": metadata.get("native_inspection_status", metadata.get("coverage")),
        "page_inventory_complete": page.get("inventory_complete"),
        "has_more": page.get("has_more"), "native_parent_truncated": bool(metadata.get("native_parent_truncated")),
        "semantic_tree_truncated": bool(metadata.get("semantic_tag_tree_truncated")),
        "scope": "Returned supported native evidence, not accessibility certification or a rendered audit.",
    })
    return {
        "version": NATIVE_AUDIT_VERSION, "file_name": document.get("file_name"),
        "source_sha256": source_hash, "facts": facts, "facts_omitted": omitted,
        "has_more": bool(page.get("has_more")), "next_cursor": page.get("next_cursor"),
    }


def native_audit_contract(inputs):
    """Only recognize actual native-reader invocation results, never document prose."""
    facts, citations, files, limitations = [], [], [], []
    seen, source_hashes = {}, {}
    for entry in inputs.values():
        value = entry.get("value")
        if not isinstance(value, dict):
            if value:
                return None
            continue
        if value.get("capability_id") not in (None, "action_invoke", "document_search"):
            return None
        if any(
            citation.get("function_name") not in (
                "get_document_accessibility_report", "search_documents", "retrieve_document_chunks", "summarize_document",
            ) for citation in value.get("citations", []) if isinstance(citation, dict)
        ):
            return None
        for citation in value.get("citations", []):
            if citation.get("function_name") != "get_document_accessibility_report":
                continue
            result = citation.get("function_result")
            if not isinstance(result, dict):
                continue
            audit = result.get("native_audit")
            if not isinstance(audit, dict) or audit.get("version") != NATIVE_AUDIT_VERSION:
                continue
            document_id = (result.get("document") or {}).get("id")
            source_hash = audit.get("source_sha256")
            if document_id in source_hashes and source_hashes[document_id] != source_hash:
                raise ValueError("The native source changed between retained inspections.")
            source_hashes[document_id] = source_hash
            if audit.get("facts_omitted"):
                limitations.append("The native fact handoff reached its limit; the returned facts are not exhaustive.")
            if audit.get("has_more"):
                limitations.append("A native inventory page has a continuation; only returned records are represented.")
            limitations.extend(audit.get("limitations") or [])
            files.append(str(audit.get("file_name") or "Selected document"))
            marker = result.get("citation")
            if isinstance(marker, str) and marker:
                citations.append(marker)
            for fact in audit.get("facts", []):
                if not isinstance(fact, dict) or set(fact) != {
                    "id", "location", "field", "state", "value", "value_sha256", "reason",
                }:
                    raise ValueError("The retained native audit fact contract is invalid.")
                if fact["state"] not in NATIVE_FIELD_STATES:
                    raise ValueError("The retained native audit state is invalid.")
                fact = deepcopy(fact)
                value_hash = hashlib.sha256(_encoded(fact["value"]).encode()).hexdigest()
                if value_hash != fact["value_sha256"]:
                    fact["state"], fact["value"] = "inaccessible", None
                    fact["reason"] = "transport_value_changed"
                    limitations.append("Some values were redacted or bounded during transport; they are not native blanks.")
                existing = seen.get(fact["id"])
                if existing is not None and existing != fact:
                    raise ValueError("The retained native audit facts conflict.")
                if existing is None:
                    seen[fact["id"]] = fact
                    facts.append(fact)
    if not facts:
        return None
    return {
        "facts": facts, "citations": list(dict.fromkeys(citations)), "files": list(dict.fromkeys(files)),
        "limitations": list(dict.fromkeys(limitations)),
        "fact_set_sha256": hashlib.sha256(_encoded(facts).encode()).hexdigest(),
    }


def native_audit_policy(contract):
    return (
        "This is a source-specific native audit. Return only one JSON object with the key "
        "\"native_claims\". Its value must be an object with exactly "
        "\"scope\":\"all_returned\" and \"fact_set_sha256\" copied from native_audit_contract.fact_set_sha256. "
        "This references the returned fact set, not the source-file hash. The server supplies each value and state. Do not infer "
        "text-to-tag bindings, replace missing fields with empty strings, reorder logical elements, "
        "or append free-text claims. The server validates these claims and renders the factual report."
    )


def validate_native_audit_claims(response, contract):
    value = json.loads(response)
    if type(value) is not dict or set(value) != {"native_claims"}:
        raise ValueError("Native audit output must contain only native_claims.")
    compact = {"scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"]}
    if value["native_claims"] not in (compact, [fact["id"] for fact in contract["facts"]]):
        raise ValueError("Native audit claims do not match the retained source facts.")
    return render_native_audit(contract)


def render_native_audit(contract):
    def cell(value):
        text = _encoded(value) if not isinstance(value, str) else value
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(
            "|", "\\|"
        ).replace("`", "\\`").replace("\r", "\\r").replace("\n", "\\n")
    lines = [
        "## Native file evidence",
        "These are the inspected source records. Absent, present-empty and inaccessible are different states. "
        "Graphics counts describe the returned native coverage, not a conformance certificate.",
        "| Location | Field | Source state | Exact value / supported record |",
        "| --- | --- | --- | --- |",
    ]
    for fact in contract["facts"]:
        lines.append("| " + " | ".join([
            cell(fact["location"]), cell(fact["field"]),
            cell(fact["state"] + (f" ({fact['reason']})" if fact.get("reason") else "")),
            cell(_encoded(fact["value"])),
        ]) + " |")
    lines.extend(contract["citations"])
    lines.extend(contract.get("limitations", []))
    return "\n\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:])
