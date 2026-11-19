# test_native_document_fidelity.py
"""Native source fidelity regression tests.

Version: 0.261.443
Implemented in: 0.261.424
Source-bound PDF annotation and OBJR text fidelity added in: 0.261.439
Typed PDF /Lang, catalog-derived bookmark states and PowerPoint language facts added in: 0.261.443
Native field states, content bindings, object identities and audit claims must
survive the native parser, inventory and answer boundaries without source edits.
"""

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import fitz
import pytest
from xml.etree import ElementTree as ET
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject,
)


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from native_document_evidence import drawing_native_fields, native_field  # noqa: E402
from functions_accessibility import extract_office_accessibility_metadata, extract_pdf_accessibility_metadata  # noqa: E402
from functions_office_media import extract_docx_comments  # noqa: E402
from functions_native_document_inspection import inspect_native_document  # noqa: E402
from functions_native_audit import build_native_audit  # noqa: E402
from functions_pdf_native_evidence import pdf_content_references  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


SOURCE_HASHES = {
    "SC-C01-R2.docx": "75e845044b67321162dc129b815729afe852f2c0d16d3f96e43313de7da15aef",
    "SC-C02.docx": "63c70035291120c93dc45c39d5d4e0650937d6ba23fbea6fa8e4728ebbaa444e",
    "SC-C03.pdf": "0258e3da3b61af80b4a9a8e33b3f578f47720d73bb3b8447fb784f1fdb768b83",
    "SC-C04.pdf": "62e1cf1bba5311b6c23e698863694ee7ae8ab766473045484841ab5526f0aa52",
    "SC-C05.pdf": "1b64979dbea78bf0784197087cba1284f7f50130b785893eaed08cf7a81ac8f2",
    "SC-C08.xlsx": "b80d669665c0f7e7660b4e0aaf5b1787bbd2b12d59ecae7e5095036c53b1b1bd",
    "SC-C11.xlsx": "4c72d289d115c82d982e732affa93e83136500a2a333e788309a5068a5730bfd",
    "SC-C09-R3.pptx": "5876122268487481b0b2310cc3abe772f02cefddc672e9929bdcaea062f141ec",
    "SC-C10-R3.pptx": "f1cf32f964b278390ebac0e98deeda09f365ce2229b5e1f5adf75d4e5f8a9632",
}


@pytest.fixture
def native_source(tmp_path):
    def load(name):
        with zipfile.ZipFile(Path(__file__).parent / "fixtures" / "native_document_fidelity.zip") as archive:
            data = archive.read(name)
        digest = hashlib.sha256(data).hexdigest()
        assert digest == SOURCE_HASHES[name]
        path = tmp_path / name
        path.write_bytes(data)
        return path
    return load


@pytest.mark.parametrize("attributes,state,value", [
    ({}, "absent", None),
    ({"descr": ""}, "present_empty", ""),
    ({"descr": "  "}, "present_value", "  "),
    ({"descr": "Picture"}, "present_value", "Picture"),
    ({"descr": False}, "present_value", False),
    ({"descr": 0}, "present_value", 0),
    (None, "inaccessible", None),
    ({"descr": None}, "inaccessible", None),
])
def test_native_field_states_are_not_normalized(attributes, state, value):
    result = native_field(attributes, "descr")
    assert result["state"] == state
    assert result["value"] == value


def test_drawing_description_presence_and_decorative_marker_are_independent():
    absent = drawing_native_fields({}, {"val": "1"})
    empty = drawing_native_fields({"descr": "", "title": ""}, {"val": "0"})
    assert absent["description"]["state"] == "absent"
    assert absent["decorative"]["value"] == "1"
    assert empty["description"]["state"] == "present_empty"
    assert empty["title"]["state"] == "present_empty"
    assert empty["decorative"]["value"] == "0"


@pytest.mark.parametrize("name,nodes", [("SC-C03.pdf", 18), ("SC-C04.pdf", 17), ("SC-C05.pdf", 0)])
def test_pdf_native_metadata_graphics_and_artifact_associations(native_source, name, nodes):
    path = native_source(name)
    metadata, pages = extract_pdf_accessibility_metadata(str(path))
    assert metadata["native_inspection_status"] == "complete", pages
    assert metadata["native_properties"]["author"]["value"] == "Fictional Custodian " + path.stem
    assert metadata["native_properties"]["keywords"]["value"] == "cedar-native-" + path.stem + ", lantern-917"
    assert len(metadata["semantic_tag_tree"]) == nodes
    assert metadata["graphics_summary"]["raster_placements"] == 1
    assert metadata["graphics_summary"]["vector_groups"] == 1
    footer = metadata["artifacts_summary"]["items"][0]
    assert footer["text"].strip() == "CEDAR / SYNTHETIC / 1"
    assert footer["native_fields"]["type"]["value"] == "/Pagination"
    assert footer["native_fields"]["subtype"]["value"] == "/Footer"
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert after == SOURCE_HASHES[name]


def test_pdf_logical_order_is_bound_not_inferred_from_rendered_order(native_source):
    metadata, _ = extract_pdf_accessibility_metadata(str(native_source("SC-C04.pdf")))
    paragraphs = [node for node in metadata["semantic_tag_tree"] if node["tag"] == "P"]
    assert [node["content_refs"][0]["mcid"] for node in paragraphs] == [0, 1, 3, 2]
    assert paragraphs[2]["bound_text"]["value"].strip() == "Step 2: release the pilot."
    assert paragraphs[3]["bound_text"]["value"].strip() == "Step 1: approve the scope."
    assert any("Review meeting:" in record["text"] for record in metadata["unmarked_text"])
    figures = metadata["figures_summary"]["items"]
    assert figures[1]["native_fields"]["alt"]["state"] == "absent"
    assert figures[1]["vector_paint_operations"] == 2


def test_pdf_raw_marked_content_does_not_create_a_logical_tree(native_source):
    metadata, pages = extract_pdf_accessibility_metadata(str(native_source("SC-C05.pdf")))
    assert metadata["native_catalog"] == {"mark_info_state": "absent", "struct_tree_state": "absent"}
    assert not metadata["is_tagged"] and not metadata["has_struct_tree"]
    figures = [record for record in pages[1]["native_content"]["records"] if record.get("tag") == "/Figure"]
    assert [record["mcid"] for record in figures] == [10, 11]


def catalog_pdf(tmp_path, *, language=None, outline=(), empty_outline=False):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    if language is not None:
        writer.root_object[NameObject("/Lang")] = TextStringObject(language)
    if empty_outline:
        # What a producer leaves behind when every bookmark was deleted but the outline root was kept.
        writer.get_outline_root()
    last_top = None
    for title, page_number, nested in outline:
        if nested:
            writer.add_outline_item(title, page_number, parent=last_top)
        else:
            last_top = writer.add_outline_item(title, page_number)
    buffer = io.BytesIO()
    writer.write(buffer)
    writer.close()
    path = tmp_path / "catalog.pdf"
    path.write_bytes(buffer.getvalue())
    return path


def audit_for_pdf(path):
    data = path.read_bytes()
    document = {"id": "catalog", "file_name": path.name, "version": 1}
    records = []
    inspected = inspect_native_document(
        document, data, ".pdf", section="all", page_size=200, max_bytes=65536, _audit_records=records,
    )
    audit = build_native_audit({
        "document": document, "accessibility_metadata": inspected["metadata"],
        "native_inspection": {"page": inspected["page"]},
    }, _source_records=records)
    return inspected, {fact["field"]: fact for fact in audit["facts"] if fact["field"] in ("language", "bookmarks")}


def test_native_catalog_facts_version():
    assert_app_version_at_least("0.261.443")


@pytest.mark.parametrize("language,outline,language_state,bookmark_state", [
    ("en-US", [("Overview", 0, False), ("Details", 1, False), ("Scope", 1, True)], "present_value", "present_value"),
    (None, [], "absent", "absent"),
    ("", [], "present_empty", "absent"),
])
def test_pdf_language_and_bookmarks_reach_the_canonical_facts_with_exact_states(
    tmp_path, language, outline, language_state, bookmark_state,
):
    path = catalog_pdf(tmp_path, language=language, outline=outline)
    original = path.read_bytes()
    inspected, facts = audit_for_pdf(path)
    properties = inspected["metadata"]["native_properties"]
    assert properties["language"]["state"] == facts["language"]["state"] == language_state
    assert properties["language"]["source"] == "/Root/Lang"
    assert facts["language"]["value"] == (language if language_state != "absent" else None)
    assert properties["bookmarks"]["state"] == facts["bookmarks"]["state"] == bookmark_state
    assert facts["bookmarks"]["location"].endswith("/Root/Outlines")
    if bookmark_state == "present_value":
        value = facts["bookmarks"]["value"]
        assert value["count"] == 3 and value["entries_truncated"] is False
        assert [(entry["level"], entry["title"], entry["page_number"]) for entry in value["entries"]] == [
            (1, "Overview", 1), (1, "Details", 2), (2, "Scope", 2),
        ]
    else:
        assert facts["bookmarks"]["value"] is None
    assert path.read_bytes() == original


def test_pdf_language_and_bookmarks_survive_when_the_audit_reads_only_a_partial_page(tmp_path):
    path = catalog_pdf(tmp_path, language="fr-CA", outline=[("Intro", 0, False)])
    data = path.read_bytes()
    document = {"id": "catalog", "file_name": path.name, "version": 1}
    records = []
    inspected = inspect_native_document(
        document, data, ".pdf", section="all", page_size=1, max_bytes=2048, _audit_records=records,
    )
    assert inspected["page"]["has_more"] is True
    audit = build_native_audit({
        "document": document, "accessibility_metadata": inspected["metadata"],
        "native_inspection": {"page": inspected["page"]},
    }, _source_records=records)
    states = {fact["field"]: (fact["state"], fact["value"]) for fact in audit["facts"] if fact["field"] in ("language", "bookmarks")}
    assert states["language"] == ("present_value", "fr-CA")
    assert states["bookmarks"][0] == "present_value" and audit["facts_omitted"] is False


def test_unreadable_pdf_outline_is_inaccessible_not_absent(tmp_path, monkeypatch):
    path = catalog_pdf(tmp_path, language="en-US", outline=[("Intro", 0, False)])

    def unreadable(_path):
        raise RuntimeError("outline reader unavailable")

    monkeypatch.setattr(fitz, "open", unreadable)
    metadata, _ = extract_pdf_accessibility_metadata(str(path))
    assert metadata["native_properties"]["bookmarks"] == {
        "state": "inaccessible", "value": None, "reason": "outline_unavailable", "source": "/Root/Outlines",
    }
    assert metadata["native_properties"]["language"]["value"] == "en-US"


def raw_pdf(tmp_path, catalog_entry="", objects=None):
    """A minimal PDF written exactly as given, for catalog shapes a PDF writer never emits."""
    body = {
        1: f"<< /Type /Catalog /Pages 2 0 R {catalog_entry} >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
        **(objects or {}),
    }
    data, offsets = bytearray(b"%PDF-1.7\n"), {}
    for number in sorted(body):
        offsets[number] = len(data)
        data += f"{number} 0 obj\n{body[number]}\nendobj\n".encode()
    size, xref = max(body) + 1, len(data)
    data += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        data += (f"{offsets[number]:010d} 00000 n \n" if number in offsets else "0000000000 65535 f \n").encode()
    data += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path = tmp_path / "raw.pdf"
    path.write_bytes(bytes(data))
    return path


OUTLINES = "/Outlines 4 0 R"
EMPTY_OUTLINE = {"count": 0, "entries": [], "entries_truncated": False}
# Each case: catalog entry, extra objects, expected state, and the expected value or inaccessible reason.
OUTLINE_CATALOGS = {
    "no_outlines_key": ("", {}, "absent", None),
    "empty_outline_with_zero_count": (OUTLINES, {4: "<< /Type /Outlines /Count 0 >>"}, "present_empty", EMPTY_OUTLINE),
    "empty_outline_dictionary": (OUTLINES, {4: "<< >>"}, "present_empty", EMPTY_OUTLINE),
    "outline_with_one_item": (OUTLINES, {
        4: "<< /Type /Outlines /First 5 0 R /Last 5 0 R /Count 1 >>",
        5: "<< /Title (Intro) /Parent 4 0 R /Dest [3 0 R /Fit] >>",
    }, "present_value", {"count": 1, "entries": [{"level": 1, "title": "Intro", "page_number": 1}], "entries_truncated": False}),
    "count_without_a_first_item": (
        OUTLINES, {4: "<< /Type /Outlines /Count 3 >>"}, "inaccessible", "outline_container_inconsistent",
    ),
    "outline_is_a_number": ("/Outlines 5", {}, "inaccessible", "outline_container_unreadable"),
    "outline_is_an_array": ("/Outlines [1 2]", {}, "inaccessible", "outline_container_unreadable"),
    "outline_is_null": ("/Outlines null", {}, "inaccessible", "outline_container_unreadable"),
    "outline_reference_is_dangling": ("/Outlines 99 0 R", {}, "inaccessible", "outline_container_unreadable"),
    "first_item_is_dangling": (
        OUTLINES, {4: "<< /Type /Outlines /First 99 0 R /Count 1 >>"}, "inaccessible", "outline_first_item_unreadable",
    ),
    "first_item_is_not_a_dictionary": (
        OUTLINES, {4: "<< /Type /Outlines /First 7 /Count 1 >>"}, "inaccessible", "outline_first_item_unreadable",
    ),
}


@pytest.mark.parametrize("name", sorted(OUTLINE_CATALOGS))
def test_pdf_bookmark_state_comes_from_the_catalog_outline_not_from_the_entry_count(tmp_path, name):
    entry, objects, state, expected = OUTLINE_CATALOGS[name]
    path = raw_pdf(tmp_path, entry, objects)
    original = path.read_bytes()
    inspected, facts = audit_for_pdf(path)
    field = inspected["metadata"]["native_properties"]["bookmarks"]
    assert field["state"] == facts["bookmarks"]["state"] == state
    assert field["source"] == "/Root/Outlines" and facts["bookmarks"]["location"].endswith("/Root/Outlines")
    if state == "inaccessible":
        assert field["value"] is None and field["reason"] == facts["bookmarks"]["reason"] == expected
    else:
        assert field["value"] == facts["bookmarks"]["value"] == expected
    assert path.read_bytes() == original


def test_a_writer_that_keeps_an_emptied_outline_root_is_reported_as_present_but_empty(tmp_path):
    path = catalog_pdf(tmp_path, language="en-US", empty_outline=True)
    original = path.read_bytes()
    inspected, facts = audit_for_pdf(path)
    field = inspected["metadata"]["native_properties"]["bookmarks"]
    assert field["state"] == facts["bookmarks"]["state"] == "present_empty"
    assert field["value"] == facts["bookmarks"]["value"] == EMPTY_OUTLINE
    assert path.read_bytes() == original


@pytest.mark.parametrize("name", ["no_outlines_key", "empty_outline_with_zero_count"])
def test_an_outline_reader_failure_does_not_change_what_the_catalog_already_establishes(tmp_path, monkeypatch, name):
    entry, objects, state, expected = OUTLINE_CATALOGS[name]
    path = raw_pdf(tmp_path, entry, objects)

    def unreadable(_path):
        raise RuntimeError("outline reader unavailable")

    monkeypatch.setattr(fitz, "open", unreadable)
    field = extract_pdf_accessibility_metadata(str(path))[0]["native_properties"]["bookmarks"]
    assert (field["state"], field["value"]) == (state, expected)


@pytest.mark.parametrize("name,reason,toc", [
    ("no_outlines_key", "outline_readers_disagree", [[1, "Phantom", 1]]),
    ("outline_with_one_item", "outline_unreadable", []),
])
def test_outline_readers_that_disagree_never_publish_absence_or_a_guess(tmp_path, monkeypatch, name, reason, toc):
    entry, objects, _, _ = OUTLINE_CATALOGS[name]
    path = raw_pdf(tmp_path, entry, objects)
    monkeypatch.setattr(fitz.Document, "get_toc", lambda self, *args, **kwargs: toc)
    field = extract_pdf_accessibility_metadata(str(path))[0]["native_properties"]["bookmarks"]
    assert field == {"state": "inaccessible", "value": None, "reason": reason, "source": "/Root/Outlines"}


def test_pdf_fixture_language_is_native_and_bookmarks_are_absent(native_source):
    path = native_source("SC-C03.pdf")
    inspected, facts = audit_for_pdf(path)
    assert facts["language"]["state"] == "present_value" and facts["language"]["value"] == "en-US"
    assert facts["bookmarks"]["state"] == "absent"
    assert not {"language", "bookmarks"} & set(inspected["metadata"]["native_catalog"])


@pytest.mark.parametrize("core_language,state,value", [
    ("<dc:language>fr-CA</dc:language>", "present_value", "fr-CA"),
    ("<dc:language></dc:language>", "present_empty", ""),
    ("", "absent", None),
])
def test_pptx_language_is_the_typed_core_property_not_a_display_alias(native_source, tmp_path, core_language, state, value):
    source = native_source("SC-C09-R3.pptx")
    with zipfile.ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    core = parts["docProps/core.xml"].decode("utf-8")
    assert "dc:language" not in core
    parts["docProps/core.xml"] = core.replace("</cp:coreProperties>", core_language + "</cp:coreProperties>").encode("utf-8")
    path = tmp_path / "language.pptx"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    data = path.read_bytes()
    document = {"id": "deck", "file_name": path.name, "version": 1}
    records = []
    inspected = inspect_native_document(
        document, data, ".pptx", section="all", page_size=200, max_bytes=65536, _audit_records=records,
    )
    audit = build_native_audit({
        "document": document, "accessibility_metadata": inspected["metadata"],
        "native_inspection": {"page": inspected["page"]},
    }, _source_records=records)
    fact = next(item for item in audit["facts"] if item["field"] == "language")
    assert (fact["state"], fact["value"]) == (state, value)
    assert fact["location"].endswith("docProps/core.xml:language")


@pytest.mark.parametrize("tagged", [False, True])
def test_pdf_annotations_keep_exact_contents_reply_and_absent_state_without_requiring_tags(tmp_path, tagged):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    text = " Reconcile 240 water kits with CSV availability 210; requested 300. "
    root = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/Contents"): TextStringObject(text), NameObject("/T"): TextStringObject("Reviewer"),
        NameObject("/F"): NumberObject(0),
    })
    root_ref = writer._add_object(root)
    reply_ref = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/Contents"): TextStringObject(""), NameObject("/IRT"): root_ref,
    }))
    absent_ref = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
    }))
    page[NameObject("/Annots")] = ArrayObject([root_ref, reply_ref, absent_ref])
    if tagged:
        tree = DictionaryObject({NameObject("/Type"): NameObject("/StructTreeRoot")})
        tree_ref = writer._add_object(tree)
        element = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/StructElem"), NameObject("/S"): NameObject("/Annot"),
            NameObject("/P"): tree_ref, NameObject("/Pg"): page.indirect_reference,
            NameObject("/K"): DictionaryObject({
                NameObject("/Type"): NameObject("/OBJR"), NameObject("/Obj"): root_ref,
            }),
        }))
        tree[NameObject("/K")] = ArrayObject([element])
        writer.root_object[NameObject("/StructTreeRoot")] = tree_ref
        writer.root_object[NameObject("/MarkInfo")] = DictionaryObject({
            NameObject("/Marked"): BooleanObject(True),
        })
    buffer = io.BytesIO()
    writer.write(buffer)
    writer.close()
    original = buffer.getvalue()
    path = tmp_path / "review.pdf"
    path.write_bytes(original)
    metadata, pages = extract_pdf_accessibility_metadata(str(path))
    annotations = pages[1]["native_annotations"]["records"]
    assert pages[1]["native_annotations"]["status"] == "complete"
    assert annotations[0]["native_fields"]["contents"] == {"state": "present_value", "value": text}
    assert annotations[0]["native_fields"]["state"]["state"] == "absent"
    assert annotations[0]["native_fields"]["state_model"]["state"] == "absent"
    assert annotations[0]["native_fields"]["flags"]["value"] == 0
    assert annotations[1]["native_fields"]["contents"]["state"] == "present_empty"
    assert annotations[1]["native_fields"]["reply_to"]["value"] == f"xref:{root_ref.idnum}"
    assert annotations[2]["native_fields"]["contents"]["state"] == "absent"
    if tagged:
        node = next(item for item in metadata["semantic_tag_tree"] if item["tag"] == "Annot")
        assert node["bound_text"] == {"state": "present_value", "value": text}
        assert node["binding_status"] == "bound"
    records = []
    document = {"id": "review", "file_name": "review.pdf", "version": 1}
    inspected = inspect_native_document(
        document, original, ".pdf", section="all", page_size=200, max_bytes=65536, _audit_records=records,
    )
    audit = build_native_audit({
        "document": document, "accessibility_metadata": inspected["metadata"],
        "native_inspection": {"page": inspected["page"]},
    }, _source_records=records)
    assert any(fact["field"] == "contents" and fact["value"] == text for fact in audit["facts"])
    assert sum(record.get("kind") == "annotation" for record in records) == 3
    assert path.read_bytes() == original


def test_repeated_objr_bindings_share_a_text_budget_without_truncating_native_values():
    annotation = DictionaryObject({NameObject("/Contents"): TextStringObject("verified")})
    reference = DictionaryObject({
        NameObject("/Type"): NameObject("/OBJR"), NameObject("/Obj"): annotation,
    })
    budget = {"remaining": 8}
    first = pdf_content_references(reference, 1, {}, annotation_budget=budget)
    second = pdf_content_references(reference, 1, {}, annotation_budget=budget)
    assert first[0]["annotation_contents"] == {"state": "present_value", "value": "verified"}
    assert second[0]["annotation_contents"] == {
        "state": "inaccessible", "value": None, "reason": "annotation_reference_text_limit",
    }
    assert annotation["/Contents"] == "verified"


@pytest.mark.parametrize("name", ["SC-C08.xlsx", "SC-C11.xlsx"])
def test_excel_optional_attributes_and_real_checkbox_are_distinct(native_source, name):
    metadata, _ = extract_office_accessibility_metadata(str(native_source(name)), ".xlsx")
    objects = metadata["objects"]
    chart = next(record for record in objects if record["type"] == "chart")
    image = next(record for record in objects if record["type"] == "image")
    assert chart["native_fields"]["description"]["state"] == "absent"
    assert chart["native_fields"]["title"]["state"] == "absent"
    if name == "SC-C08.xlsx":
        assert image["native_fields"]["description"] == {"state": "present_value", "value": "Picture"}
        assert metadata["forms_summary"]["controls_inspected"] == 0
    else:
        assert image["native_fields"]["description"]["state"] == "absent"
        assert image["is_decorative"] is True
        controls = [record for record in objects if record.get("control_representation") == "in_cell"]
        assert len(controls) == 1
        control = controls[0]
        assert control["cell"] == "D3" and control["sheet"] == "Budget"
        assert control["type"] == "checkbox" and control["checked"] is True
        assert control["feature_bag_path"] == [2, 1, 0]
        assert metadata["forms_summary"]["controls_inspected"] == 1


@pytest.mark.parametrize("name", ["SC-C09-R3.pptx", "SC-C10-R3.pptx"])
def test_pptx_complete_supported_objects_styles_and_placeholder_origin(native_source, name):
    metadata, slides = extract_office_accessibility_metadata(str(native_source(name)), ".pptx")
    assert metadata["native_inspection_status"] == "complete"
    assert metadata["objects_summary"]["total"] == 8
    objects = slides[1]["native_objects"]["records"]
    ellipse = next(obj for obj in objects if obj["object_id"] == "7")
    assert ellipse["geometry"] == "ellipse" and ellipse["is_decorative"] is True
    assert ellipse["native_fields"]["description"]["state"] == "absent"
    assert ellipse["text"] == ""
    footer = next(obj for obj in objects if obj["object_id"] == "8")
    number = next(obj for obj in objects if obj["object_id"] == "9")
    assert footer["content_origin"] == number["content_origin"] == "slide_local"
    assert footer["source_part"] == "ppt/slides/slide1.xml"
    assert footer["placeholder"]["type"] == "ftr"
    assert number["placeholder"]["type"] == "sldNum"
    picture = next(obj for obj in objects if obj["kind"] == "picture")
    assert picture["native_fields"]["title"]["state"] == "absent"
    if "C10" in name:
        assert picture["native_fields"]["description"]["state"] == "present_empty"
        meeting = next(obj for obj in objects if obj["object_id"] == "6")
        run = meeting["text_runs"][0]
        assert run["style"] == {"font": "Arial", "size_pt": 18, "color": "#E8E8E8", "bold": False}
        assert run["contrast"]["background"] == "#FCFAF6"
        assert run["contrast"]["ratio"] == 1.18
        assert run["contrast"]["low_contrast"] is True
    else:
        assert picture["native_fields"]["description"]["value"] == "Two cedar delivery sites joined by a teal route."
    heading = next(obj for obj in objects if obj["object_id"] == "2")
    assert heading["text_runs"][0]["style"]["bold"] is True


@pytest.mark.parametrize("change", ["unchecked", "bad_mapper", "bad_reference"])
def test_excel_checkbox_state_and_invalid_mapping_are_not_boolean_inference(native_source, change):
    path = native_source("SC-C11.xlsx")
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    if change == "unchecked":
        root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
        cell = next(node for node in root.iter() if node.tag.endswith("}c") and node.get("r") == "D3")
        next(node for node in cell if node.tag.endswith("}v")).text = "0"
        parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    elif change == "bad_mapper":
        root = ET.fromstring(parts["xl/styles.xml"])
        next(node for node in root.iter() if node.tag.endswith("}xfComplement")).set("i", "99999")
        parts["xl/styles.xml"] = ET.tostring(root)
    else:
        root = ET.fromstring(parts["xl/featurePropertyBag/featurePropertyBag.xml"])
        controls = next(node for node in root if node.get("type") == "XFControls")
        controls[0].text = "99999"
        parts["xl/featurePropertyBag/featurePropertyBag.xml"] = ET.tostring(root)
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    metadata, _ = extract_office_accessibility_metadata(str(path), ".xlsx")
    controls = [record for record in metadata["objects"] if record.get("control_representation") == "in_cell"]
    assert len(controls) == 1 and controls[0]["cell"] == "D3"
    if change == "unchecked":
        assert controls[0]["checked"] is False
        assert controls[0]["checked_state"] == "present_value"
    else:
        assert controls[0]["control_type_state"] == "inaccessible"
        assert controls[0]["type"] == "unsupported_in_cell_control"
        assert controls[0]["checked"] is None and controls[0]["checked_state"] == "inaccessible"
        assert controls[0]["saved_value"] is True


def test_literal_artifact_word_is_not_a_native_artifact(native_source, tmp_path):
    source = native_source("SC-C03.pdf")
    writer = PdfWriter(clone_from=str(source))
    data = writer.pages[0].get_contents().get_data()
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf (Literal /Artifact text) Tj ET\n" + data)
    writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "literal-artifact.pdf"
    with path.open("wb") as target:
        writer.write(target)
    metadata, _ = extract_pdf_accessibility_metadata(str(path))
    assert metadata["artifacts_summary"]["total_artifact_blocks"] == 1
    assert any("Literal /Artifact text" in record["text"] for record in metadata["unmarked_text"])


def test_reused_mcids_are_bound_in_page_scope(tmp_path):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    elements = []
    for text in ("First page", "Second page"):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(("/P <</MCID 0>> BDC BT /F1 12 Tf (" + text + ") Tj ET EMC").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
        elements.append(writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/StructElem"), NameObject("/S"): NameObject("/P"),
            NameObject("/Pg"): page.indirect_reference, NameObject("/K"): NumberObject(0),
        })))
    writer._root_object[NameObject("/StructTreeRoot")] = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructTreeRoot"), NameObject("/K"): ArrayObject(elements),
    }))
    writer._root_object[NameObject("/MarkInfo")] = DictionaryObject({NameObject("/Marked"): BooleanObject(True)})
    path = tmp_path / "page-scoped-mcids.pdf"
    with path.open("wb") as target:
        writer.write(target)
    metadata, _ = extract_pdf_accessibility_metadata(str(path))
    nodes = metadata["semantic_tag_tree"]
    assert [node["content_refs"][0]["mcid"] for node in nodes] == [0, 0]
    assert [node["bound_text"]["value"].strip() for node in nodes] == ["First page", "Second page"]


@pytest.mark.parametrize("name", ["SC-C01-R2.docx", "SC-C02.docx"])
def test_valid_word_comment_controls_remain_unchanged(native_source, name):
    path = native_source(name)
    data = path.read_bytes()
    comments, body_words = extract_docx_comments(io.BytesIO(data), strict=True)
    assert body_words > 0
    if "C02" in name:
        assert comments == []
    else:
        assert len(comments) == 3
        assert sum(len(comment["replies"]) for comment in comments) == 1
        retention = next(comment for comment in comments if "30 days" in comment["text"])
        assert retention["done"] is True and retention["resolution_available"] is True
        launch = next(comment for comment in comments if "MAPLE-472" in comment["text"])
        assert launch["anchor_text"] == "The pilot will launch on 15 December 2026."
        assert "accessibility review" in launch["replies"][0]["text"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == SOURCE_HASHES[name]
