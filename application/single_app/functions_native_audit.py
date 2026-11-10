# functions_native_audit.py
"""Native audit facts and deterministic claim validation, not prose-pattern matching."""

import hashlib
import json
import re
from copy import deepcopy

from native_document_evidence import NATIVE_FIELD_STATES, inaccessible_field


NATIVE_AUDIT_VERSION = "native-audit-v1"
NATIVE_AUDIT_ANSWER_VERSION = "native-audit-answer-v2"
MAX_AUDIT_FACTS = 1000
MAX_AUDIT_BYTES = 100000


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def sanitize_native_audit_transport(value, sanitize):
    """Keep bounded typed facts independent of citation-wrapper depth, never of redaction."""
    required = {"version", "file_name", "source_sha256", "facts", "facts_omitted", "has_more"}
    if (
        type(value) is not dict or not required <= set(value)
        or set(value) - required - {"next_cursor", "limitations"}
        or value["version"] != NATIVE_AUDIT_VERSION
        or type(value["facts"]) is not list or len(value["facts"]) > MAX_AUDIT_FACTS
        or type(value["facts_omitted"]) is not bool or type(value["has_more"]) is not bool
    ):
        return None
    for fact in value["facts"]:
        if (
            type(fact) is not dict
            or set(fact) != {"id", "location", "field", "state", "value", "value_sha256", "reason"}
            or type(fact["id"]) is not str or re.fullmatch(r"[0-9a-f]{24}", fact["id"]) is None
            or type(fact["value_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", fact["value_sha256"]) is None
            or type(fact["location"]) is not str or type(fact["field"]) is not str
            or type(fact["state"]) is not str or fact["state"] not in NATIVE_FIELD_STATES
            or fact["reason"] is not None and type(fact["reason"]) is not str
        ):
            return None
    try:
        if len(_encoded(value).encode("utf-8")) > MAX_AUDIT_BYTES + 8192:
            return None
    except (ValueError, TypeError, RecursionError):
        return None
    result = {key: sanitize(item) for key, item in value.items() if key != "facts"}
    result["facts"] = [
        {key: sanitize(item) for key, item in fact.items()}
        for fact in value["facts"]
    ]
    return result


def build_native_audit(payload, *, _source_records=None):
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
    if _source_records is not None and metadata.get("format") != "pdf":
        objects = [
            record for record in _source_records
            if page.get("section") == "objects" or record.get("inventory_section") == "objects"
            or metadata.get("format") == "pptx" and record.get("section") == "objects"
        ]
    elif page.get("section") == "objects" and metadata.get("format") != "pdf":
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
    if payload.get("excel_inspection") and page.get("section") == "all":
        records = _source_records if _source_records is not None else page.get("records", [])
        for index, record in enumerate(records, page.get("start_record", 0)):
            section = record.get("inventory_section")
            if record.get("record_fragment") or section == "objects":
                continue
            location = "; ".join(str(part) for part in (
                record.get("sheet"), record.get("cell"), record.get("name"), section,
            ) if part)
            add(f"excel-inventory:{index}", location or "Workbook native inventory",
                f"saved_{section}_record", record)
        add("excel-inventory-counts", "Supported workbook inventory", "inventory_section_counts",
            page.get("section_counts") or {})
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


def _native_page_chain_complete(pages):
    """Prove contiguous returned records, including fragments; a last page alone is insufficient."""
    if not pages:
        return False
    expected_offset = expected_fragment = 0
    total = pages[0].get("total_records")
    if type(total) is not int or total < 0:
        return False
    if any(
        type(page.get("start_record")) is not int or page["start_record"] < 0
        or type(page.get("fragment_offset", 0)) is not int or page.get("fragment_offset", 0) < 0
        for page in pages
    ):
        return False
    unique = {_encoded(page): page for page in pages}
    ordered = sorted(unique.values(), key=lambda page: (
        page.get("start_record", -1), page.get("fragment_offset", 0),
    ))
    for page in ordered:
        if (
            page.get("total_records") != total
            or page.get("start_record") != expected_offset
            or page.get("fragment_offset", 0) != expected_fragment
            or type(page.get("records")) is not list
        ):
            return False
        for record in page["records"]:
            if not isinstance(record, dict):
                return False
            if record.get("record_fragment"):
                piece, length = record.get("record_json_fragment"), record.get("record_characters")
                if (
                    not isinstance(piece, str) or not piece or type(length) is not int
                    or record.get("fragment_offset") != expected_fragment
                    or expected_fragment + len(piece) > length
                ):
                    return False
                expected_fragment += len(piece)
                if expected_fragment == length:
                    expected_offset, expected_fragment = expected_offset + 1, 0
            else:
                if expected_fragment:
                    return False
                expected_offset += 1
        if page.get("has_more") is not (expected_offset < total or bool(expected_fragment)):
            return False
    return expected_offset == total and expected_fragment == 0


def native_audit_contract(inputs):
    """Only recognize actual native-reader invocation results, never document prose."""
    facts, citations, files, limitations = [], [], [], []
    seen, source_hashes, inventory_pages, inventory_files, unfinished = {}, {}, {}, {}, set()
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
            page = (result.get("native_inspection") or result.get("excel_inspection") or {}).get("page")
            section = page.get("section") if isinstance(page, dict) else None
            inventory_key = (document_id, source_hash, section)
            if isinstance(page, dict):
                inventory_pages.setdefault(inventory_key, []).append(page)
                inventory_files[inventory_key] = str(audit.get("file_name") or "Selected document")
            if audit.get("has_more"):
                unfinished.add(inventory_key)
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
    complete_chains = {key: _native_page_chain_complete(pages) for key, pages in inventory_pages.items()}
    if any(not complete_chains.get(key, False) for key in unfinished):
        limitations.append("A native inventory page has a continuation; only returned records are represented.")
    return {
        "facts": facts, "citations": list(dict.fromkeys(citations)), "files": list(dict.fromkeys(files)),
        "limitations": list(dict.fromkeys(limitations)),
        "fact_set_sha256": hashlib.sha256(_encoded(facts).encode()).hexdigest(),
        "inventory_coverage": [{
            "file_name": inventory_files[key], "section": key[2],
            "returned_chain_complete": complete_chains[key],
            "inventory_complete": all(page.get("inventory_complete") is True for page in pages),
            "total_records": pages[0].get("total_records"),
        } for key, pages in inventory_pages.items()],
    }


def native_audit_policy(contract):
    return (
        "This is a source-specific native audit. Return one JSON object with exactly the keys "
        "\"native_claims\" and \"answer\". native_claims must be an object with exactly "
        "\"scope\":\"all_returned\" and \"fact_set_sha256\" copied from native_audit_contract.fact_set_sha256. "
        "This references the returned fact set, not the source-file hash. answer must be a nonempty "
        "Markdown string answering every requested question with supported findings or a precise "
        "explanation of what is not in the supplied data or cannot be inspected. Missing facts and "
        "unsupported checks are normal answer content, not execution errors. Keep useful findings. "
        "Lead with direct answers and organize findings by the requested checks, not just a raw inventory. "
        "The native_audit_contract facts are authoritative for native values, field states, object "
        "identity, text bindings and logical order; action-model notes cannot override them. "
        "Do not replace absent or inaccessible fields with stored blanks, infer rendered compliance, "
        "or invent source assertions or citations. Copy supplied citations verbatim where used. "
        "The server appends its immutable factual evidence table; do not copy that table into answer. "
        "The checker evaluates the rendered customer answer, not this JSON transport format."
    )


def _unique_native_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Native audit output contains a duplicate key.")
        value[key] = item
    return value


def decode_native_audit_answer(response, contract, *, require_answer=False):
    """Validate immutable fact references separately from the checked explanation."""
    value = json.loads(response, object_pairs_hook=_unique_native_object)
    if type(value) is not dict or set(value) not in (
        {"native_claims"}, {"native_claims", "answer"},
    ):
        raise ValueError("Native audit output must contain native_claims and its answer.")
    if require_answer and "answer" not in value:
        raise ValueError("Native audit output omitted the requested customer answer.")
    compact = {"scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"]}
    if value["native_claims"] not in (compact, [fact["id"] for fact in contract["facts"]]):
        raise ValueError("Native audit claims do not match the retained source facts.")
    rendered = render_native_audit(contract)
    if "answer" in value:
        answer = value["answer"]
        if type(answer) is not str or not answer.strip():
            raise ValueError("Native audit answer must be nonempty Markdown.")
        allowed = set(re.findall(r"\[#[^\]\r\n]+\]", "\n".join(contract["citations"])))
        if set(re.findall(r"\[#[^\]\r\n]+\]", answer)) - allowed:
            raise ValueError("Native audit answer contains an unknown citation.")
        rendered = f"{answer.rstrip()}\n\n{rendered}"
    return value, rendered


def validate_native_audit_claims(response, contract):
    return decode_native_audit_answer(response, contract)[1]


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
    for coverage in contract.get("inventory_coverage", []):
        lines.append("| " + " | ".join([
            cell(coverage["file_name"]), "inventory_coverage", "present_value", cell(_encoded(coverage)),
        ]) + " |")
    lines.extend(contract["citations"])
    lines.extend(contract.get("limitations", []))
    return "\n\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:])
