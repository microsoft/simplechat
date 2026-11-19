# functions_pdf_native_evidence.py
"""Bounded PDF content identities using the reader's native text decoding."""

from pypdf.errors import PdfReadError

from functions_appinsights import log_event
from native_document_evidence import inaccessible_field, native_field


MAX_NATIVE_CONTENT_RECORDS = 4000
MAX_NATIVE_OPERATIONS = 200000
MAX_NATIVE_TEXT_CHARACTERS = 1000000


def dereference(value):
    return value.get_object() if hasattr(value, "get_object") else value


def stream_identity(reference, page_number):
    return f"xref:{reference.idnum}" if hasattr(reference, "idnum") else f"page:{page_number}"


def _annotation_field(annotation, name):
    if not hasattr(annotation, "get"):
        return inaccessible_field("annotation_object_unavailable")
    if name not in annotation:
        return native_field(annotation, name)
    try:
        value = dereference(annotation[name])
    except (PdfReadError, ValueError, TypeError, KeyError, RecursionError):
        return inaccessible_field("annotation_field_unresolved")
    if name != "/F" and not isinstance(value, str):
        return inaccessible_field("annotation_field_type_invalid")
    if isinstance(value, str) and len(value) > MAX_NATIVE_TEXT_CHARACTERS:
        return inaccessible_field("annotation_text_limit")
    return native_field({name: value}, name)


def inspect_pdf_annotations(reader):
    """Read native page annotations independently of semantic tags and content streams."""
    pages, count, characters = {}, 0, 0
    for number, page in enumerate(reader.pages, 1):
        records, limitations = [], []
        try:
            raw_references = page.get("/Annots")
            references = [] if raw_references is None else dereference(raw_references)
            if not isinstance(references, list):
                raise ValueError("annotation_array_invalid")
            for index, reference in enumerate(references):
                if count >= MAX_NATIVE_CONTENT_RECORDS:
                    limitations.append("annotation_record_limit")
                    break
                count += 1
                try:
                    annotation = dereference(reference)
                except (PdfReadError, ValueError, TypeError, KeyError, RecursionError):
                    annotation = None
                    limitations.append("annotation_object_unresolved")
                object_ref = (
                    stream_identity(reference, number) if hasattr(reference, "idnum")
                    else f"page:{number}:annotation:{index + 1}"
                )
                fields = {
                    field: _annotation_field(annotation, key)
                    for field, key in (
                        ("contents", "/Contents"), ("author", "/T"), ("subject", "/Subj"),
                        ("created", "/CreationDate"), ("modified", "/M"), ("name", "/NM"),
                        ("state", "/State"), ("state_model", "/StateModel"), ("flags", "/F"),
                        ("subtype", "/Subtype"),
                    )
                }
                for name, field in tuple(fields.items()):
                    value = field.get("value")
                    if not isinstance(value, str):
                        continue
                    if characters + len(value) > MAX_NATIVE_TEXT_CHARACTERS:
                        fields[name] = inaccessible_field("annotation_text_limit")
                    else:
                        characters += len(value)
                reply = native_field(annotation, "/IRT")
                if hasattr(annotation, "get") and "/IRT" in annotation:
                    target = annotation.get("/IRT")
                    reply = (
                        {"state": "present_value", "value": stream_identity(target, number)}
                        if hasattr(target, "idnum") else inaccessible_field("annotation_reply_reference_unresolved")
                    )
                fields["reply_to"] = reply
                records.append({
                    "id": f"pdf:p{number}:annotation:{object_ref}",
                    "kind": "annotation", "page_number": number, "object_ref": object_ref,
                    "native_fields": fields,
                })
            if any(
                field["state"] == "inaccessible" for record in records
                for field in record["native_fields"].values()
            ):
                limitations.append("annotation_fields_inaccessible")
        except (PdfReadError, ValueError, TypeError, KeyError, RecursionError) as error:
            limitations.append("annotation_array_unresolved")
            log_event(
                "[DOCUMENT_METADATA] PDF native annotations could not be fully inspected.",
                level=30, extra={"page_number": number, "error_type": type(error).__name__},
            )
        pages[number] = {
            "status": "partial" if limitations else "complete",
            "records": records, "limitations": list(dict.fromkeys(limitations)),
        }
    return pages


def pdf_content_references(kids, page_number, page_map, *, annotation_budget=None):
    """Keep content references, not descendants' unrelated semantic elements."""
    references = []
    if annotation_budget is None:
        annotation_budget = {"remaining": MAX_NATIVE_TEXT_CHARACTERS}
    stack = [(kids, page_number)]
    while stack and len(references) < MAX_NATIVE_CONTENT_RECORDS:
        value, page = stack.pop()
        value = dereference(value)
        if isinstance(value, list):
            stack.extend((child, page) for child in reversed(value))
        elif isinstance(value, int):
            references.append({"page_number": page, "stream_id": f"page:{page}", "mcid": int(value)})
        elif hasattr(value, "get"):
            pg = value.get("/Pg")
            page = page_map.get(getattr(pg, "idnum", None), page)
            kind = str(value.get("/Type") or "")
            if kind == "/MCR" and isinstance(value.get("/MCID"), int):
                references.append({
                    "page_number": page, "stream_id": stream_identity(value.get("/Stm"), page),
                    "mcid": int(value["/MCID"]),
                })
            elif kind == "/OBJR":
                try:
                    annotation = dereference(value.get("/Obj"))
                    text = _annotation_field(annotation, "/Contents")
                except (PdfReadError, ValueError, TypeError, KeyError, RecursionError):
                    text = inaccessible_field("annotation_object_unresolved")
                if isinstance(text.get("value"), str):
                    length = len(text["value"])
                    if length > annotation_budget["remaining"]:
                        text = inaccessible_field("annotation_reference_text_limit")
                    else:
                        annotation_budget["remaining"] -= length
                references.append({
                    "page_number": page, "object_ref": stream_identity(value.get("/Obj"), page),
                    "annotation_contents": text,
                })
            elif str(value.get("/S") or "") == "/Span" and not any(
                key in value for key in ("/Alt", "/ActualText", "/Lang", "/E", "/T")
            ):
                stack.append((value.get("/K"), page))
    return references


def inspect_pdf_content(reader):
    pages = {}
    operations = 0
    characters = 0
    record_count = 0
    for number, page in enumerate(reader.pages, 1):
        records, markers, forms, pending, do_calls = [], [], [], set(), []
        status = "complete"
        notes = []
        resources = [dereference(page.get("/Resources")) or {}]

        def append_record(kind, **values):
            nonlocal record_count
            if record_count >= MAX_NATIVE_CONTENT_RECORDS:
                raise ValueError("native_content_record_limit")
            record_count += 1
            record = {
                "id": f"pdf:p{number}:content:{len(records) + 1}",
                "page_number": number, "stream_id": forms[-1]["stream"] if forms else f"page:{number}",
                "kind": kind, "text": "", "text_state": "present_empty",
                "raster_placements": 0, "vector_paint_operations": 0, **values,
            }
            records.append(record)
            return len(records) - 1

        def before(operator, operands, cm, tm):
            nonlocal operations
            operations += 1
            if operations > MAX_NATIVE_OPERATIONS or len(markers) + len(forms) > 64:
                raise ValueError("native_content_operation_limit")
            if operator in (b"BDC", b"BMC"):
                tag = str(operands[0]) if operands else ""
                properties = operands[1] if len(operands) > 1 else {}
                if isinstance(properties, str):
                    named = dereference(resources[-1].get("/Properties")) or {}
                    properties = dereference(named.get(properties))
                properties = dereference(properties)
                if not hasattr(properties, "get"):
                    properties = None
                mcid = properties.get("/MCID") if properties is not None else None
                index = append_record(
                    "artifact" if tag == "/Artifact" else "marked_content", tag=tag,
                    mcid=int(mcid) if isinstance(mcid, int) else None,
                    native_fields={
                        "type": native_field(properties, "/Type"),
                        "subtype": native_field(properties, "/Subtype"),
                    },
                )
                markers.append(index)
            elif operator == b"EMC":
                if not markers:
                    raise ValueError("unbalanced_marked_content")
                markers.pop()
            elif operator in (b"Tj", b"TJ", b"'", b'"'):
                if markers:
                    index = markers[-1]
                elif len(pending) == 1 and records[next(iter(pending))]["kind"] == "unmarked_text":
                    index = next(iter(pending))
                else:
                    index = append_record("unmarked_text")
                pending.add(index)
            elif operator == b"Do" and operands:
                objects = dereference(resources[-1].get("/XObject")) or {}
                reference = objects.get(operands[0])
                obj = dereference(reference)
                if not hasattr(obj, "get"):
                    raise ValueError("unavailable_xobject")
                is_form = str(obj.get("/Subtype")) == "/Form"
                do_calls.append(is_form)
                if str(obj.get("/Subtype")) == "/Image":
                    index = markers[-1] if markers else append_record("unmarked_graphic")
                    records[index]["raster_placements"] += 1
                    records[index].setdefault("raster_object_refs", []).append(stream_identity(reference, number))
                elif is_form:
                    forms.append({"stream": stream_identity(reference, number), "markers": len(markers)})
                    resources.append(dereference(obj.get("/Resources")) or resources[-1])
            elif operator in (b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"):
                index = markers[-1] if markers else append_record("unmarked_graphic")
                records[index]["vector_paint_operations"] += 1

        def after(operator, operands, cm, tm):
            if operator == b"Do" and do_calls:
                if do_calls.pop():
                    frame = forms.pop()
                    if len(markers) != frame["markers"]:
                        raise ValueError("unbalanced_form_marked_content")
                    resources.pop()

        def text(value, cm, tm, font, size):
            nonlocal characters, status
            if not value:
                return
            characters += len(value)
            if characters > MAX_NATIVE_TEXT_CHARACTERS:
                raise ValueError("native_content_text_limit")
            if len(pending) == 1:
                record = records[next(iter(pending))]
                record["text"] += value
                record["text_state"] = "present_value" if record["text"] else "present_empty"
            elif pending:
                status = "partial"
                if "ambiguous_text_callback" not in notes:
                    notes.append("ambiguous_text_callback")
                for index in pending:
                    records[index]["text_state"] = "inaccessible"
                    records[index]["text_reason"] = "ambiguous_text_callback"
            pending.clear()

        try:
            page.extract_text(visitor_operand_before=before, visitor_operand_after=after, visitor_text=text)
            if markers or forms or pending or do_calls:
                raise ValueError("incomplete_content_binding")
        except (PdfReadError, ValueError, TypeError, KeyError, IndexError, RecursionError, NotImplementedError) as error:
            status = "partial"
            notes.append(type(error).__name__)
            for record in records:
                record["text_state"] = "inaccessible"
                record["text_reason"] = "content_inspection_incomplete"
            log_event(
                "[DOCUMENT_METADATA] PDF native content inspection incomplete.",
                level=30, extra={"page_number": number, "error_type": type(error).__name__},
            )
        pages[number] = {"status": status, "records": records, "limitations": notes}
        if operations > MAX_NATIVE_OPERATIONS or record_count >= MAX_NATIVE_CONTENT_RECORDS:
            break
    return pages


def bind_pdf_node(node, content):
    matches = []
    texts = []
    for reference in node.get("content_refs", []):
        if "object_ref" in reference:
            field = reference.get("annotation_contents") or inaccessible_field("object_reference_text_unresolved")
            if field["state"] not in ("present_value", "present_empty"):
                node["binding_status"] = field["state"]
                node["bound_text"] = field
                return
            texts.append(str(field["value"]))
            continue
        page = content.get(reference.get("page_number"), {})
        candidates = [
            record for record in page.get("records", [])
            if reference.get("mcid") is not None
            and record.get("mcid") == reference["mcid"]
            and record["stream_id"] == reference["stream_id"]
        ]
        if len(candidates) != 1 or page.get("status") != "complete":
            node["binding_status"] = "inaccessible"
            node["bound_text"] = inaccessible_field("content_reference_unresolved")
            return
        matches.append(candidates[0])
        texts.append(candidates[0]["text"])
    if matches or texts:
        node["content_ids"] = [record["id"] for record in matches]
        node["binding_status"] = "bound"
        value = "".join(texts)
        node["bound_text"] = native_field({"text": value}, "text")
        node["raster_placements"] = sum(record["raster_placements"] for record in matches)
        node["vector_paint_operations"] = sum(record["vector_paint_operations"] for record in matches)
    else:
        node["binding_status"] = "no_direct_content_reference"
