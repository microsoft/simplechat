# test_native_document_fidelity.py
"""Native source fidelity regression tests.

Version: 0.261.424
Implemented in: 0.261.424
Native field states, content bindings, object identities and audit claims must
survive the native parser, inventory and answer boundaries without source edits.
"""

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest
from xml.etree import ElementTree as ET
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from native_document_evidence import drawing_native_fields, native_field  # noqa: E402
from functions_accessibility import extract_office_accessibility_metadata, extract_pdf_accessibility_metadata  # noqa: E402
from functions_office_media import extract_docx_comments  # noqa: E402


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
