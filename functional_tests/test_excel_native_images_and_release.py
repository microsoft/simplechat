# test_excel_native_images_and_release.py
"""
Functional tests for Excel image anchors and release-safe metadata.
Version: 0.261.408
Implemented in: 0.261.408

Real OOXML drawings retain worksheet/cell locations through existing image
extraction. Cleared/sanitized source hashes cannot borrow original metadata.
"""

import ast
import io
from pathlib import Path
import random
import sys

from openpyxl import Workbook
from openpyxl.drawing.image import Image as WorkbookImage
from PIL import Image

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from content_screening.access import _with_current_excel_metadata, is_public_document_field  # noqa: E402
from content_screening.contracts import ContentUnit, ScreeningValidationError  # noqa: E402
from content_screening.publication import _tabular_publication_chunks  # noqa: E402
from functions_excel_accessibility import extract_excel_accessibility_metadata  # noqa: E402
from functions_office_media import extract_office_embedded_images_with_diagnostics  # noqa: E402
from test_tabular_enhanced_citations_schema_summary_fix import load_tabular_schema_helpers  # noqa: E402


def test_real_excel_image_keeps_sheet_anchor_alt_and_analysis_location(tmp_path):
    picture = tmp_path / "figure.png"
    pixels = random.Random(7).randbytes(200 * 200 * 3)
    Image.frombytes("RGB", (200, 200), pixels).save(picture)
    path = tmp_path / "images.xlsx"
    workbook = Workbook()
    workbook.active.title = "Figures"
    workbook.active.add_image(WorkbookImage(picture), "D9")
    workbook.save(path)
    metadata, _ = extract_excel_accessibility_metadata(path, ".xlsx")
    locations = metadata["image_locations"]
    assert len(locations) == 1
    output = tmp_path / "extracted"
    output.mkdir()
    images, diagnostics = extract_office_embedded_images_with_diagnostics(
        path, str(output), min_pixels=100, max_images=5, native_media_metadata=locations,
    )
    assert diagnostics["candidates"] == 1
    assert len(images) == 1
    assert images[0]["sheet_name"] == "Figures" and images[0]["cell"] == "D9"
    assert images[0]["is_decorative"] is None
    assert images[0]["position_known"] is True
    assert images[0]["placements"][0]["cell"] == "D9"


def test_original_excel_metadata_is_not_exposed_after_active_source_sanitization():
    metadata = {"format": "xlsx", "comments": [{"text": "original-private-canary"}],
                "inventory_storage": {"source_sha256": "a" * 64}}
    original = {"content_screening": {"active_blob": {"content_hash": "a" * 64}}}
    matching = _with_current_excel_metadata({"accessibility_metadata": metadata}, original)
    assert matching["accessibility_metadata"] == metadata
    sanitized = {"content_screening": {"active_blob": {"content_hash": "b" * 64}}}
    released = _with_current_excel_metadata({"accessibility_metadata": metadata}, sanitized)
    assert "accessibility_metadata" not in released
    assert released["native_inspection_status"] == "requires_active_source_inspection"
    assert not is_public_document_field("excel_native_inventory")


def test_duplicate_image_analysis_retains_each_excel_placement(tmp_path):
    picture = tmp_path / "duplicate.png"
    Image.frombytes("RGB", (200, 200), random.Random(11).randbytes(200 * 200 * 3)).save(picture)
    path = tmp_path / "duplicates.xlsx"
    workbook = Workbook()
    workbook.active.title = "Figures"
    workbook.active.add_image(WorkbookImage(picture), "D9")
    workbook.active.add_image(WorkbookImage(picture), "F12")
    workbook.save(path)
    metadata, _ = extract_excel_accessibility_metadata(path, ".xlsx")
    output = tmp_path / "extracted"
    output.mkdir()
    images, diagnostics = extract_office_embedded_images_with_diagnostics(
        path, str(output), min_pixels=100, max_images=5, native_media_metadata=metadata["image_locations"],
    )
    assert len(images) == 1 and diagnostics["skipped_reasons"]["duplicate_image"] == 1
    assert {item["cell"] for item in images[0]["placements"]} == {"D9", "F12"}


def test_image_analysis_uses_existing_gate_and_keeps_generated_content_separate():
    tree = ast.parse((APP / "functions_documents.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_enrich_excel_image_inventory")
    calls = []

    def build(*args, **kwargs):
        calls.append(kwargs)
        return ([{"content": "The figure contains a delivery schedule.", "sheet_name": "Figures",
                  "cell": "D9", "media_part": "xl/media/image1.png", "placements": [{"sheet_name": "Figures", "cell": "D9"}]}],
                1, "configured-engine", 0)

    namespace = {"_build_office_embedded_image_chunks": build}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "excel_image_enrichment", "exec"), namespace)
    metadata, evidence, records = {"coverage_notes": [], "image_locations": {"xl/media/image1.png": {"sheet_name": "Figures"}}}, [], []
    enrich = namespace[node.name]
    enrich("file.xlsx", {"enable_office_embedded_image_analysis": False}, lambda **kwargs: None, metadata, evidence,
           lambda section, record: records.append((section, record)))
    assert not calls and metadata["image_analysis_summary"]["status"] == "disabled"
    enrich("file.xlsx", {"enable_office_embedded_image_analysis": True}, lambda **kwargs: None, metadata, evidence,
           lambda section, record: records.append((section, record)))
    assert len(calls) == 1 and calls[0]["native_media_metadata"] == metadata["image_locations"]
    assert records[0][0] == "image_analyses"
    assert records[0][1]["source_kind"] == "configured_image_analysis_not_saved_alt_text"
    assert records[0][1]["cell"] == "D9"
    assert "delivery schedule" in evidence[0]["content"]


def test_reviewed_native_publication_is_bounded_and_every_fragment_is_findable():
    units = [
        ContentUnit("sheet", "Data", {"kind": "table_sheet", "sheet_index": 1}),
        ContentUnit("native-1", "reviewer feedback " * 80000, {"kind": "excel_native"}),
        ContentUnit("native-2", "additional feedback " * 80000, {"kind": "excel_native"}),
    ]
    chunks = _tabular_publication_chunks(
        units, "review.xlsx", 1024, include_native=True,
        schema_text="Table: Data!A2:D9; header_row=2; Columns: Site, Cap, Delivered, Accepted",
    )
    native = [chunk for chunk in chunks if chunk["unit_id"].startswith("native-")]
    assert len(native) > 1
    assert sum(len(chunk["chunk_text"]) for chunk in native) <= 1000000
    assert all(chunk["chunk_text"].startswith("### Excel native inspection\n") for chunk in native)
    assert all(len(chunk["chunk_text"]) <= 1024 for chunk in chunks)
    assert [chunk["chunk_sequence"] for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert chunks[0]["chunk_text"].startswith("Table: Data!A2:D9; header_row=2;")
    assert units[1].text == "reviewer feedback " * 80000

    sanitized = _tabular_publication_chunks(units, "review.xlsx", 1024, include_native=False)
    assert all(chunk["unit_id"] == "table-schema" for chunk in sanitized)


def test_native_publication_rejects_chunk_sizes_that_cannot_identify_evidence():
    units = [ContentUnit("native", "feedback", {"kind": "excel_native"})]
    try:
        _tabular_publication_chunks(units, "review.xlsx", 8, include_native=True)
    except ScreeningValidationError:
        return
    raise AssertionError("Native publication must not emit unidentifiable evidence fragments.")


def test_reviewed_workbook_schema_uses_active_bytes_and_actual_table_header():
    workbook = Workbook()
    workbook.active.title = "Budget"
    workbook.active.append(["Delivery review"])
    workbook.active.append(["Site", "Cap"])
    workbook.active.append(["South", 15000])
    source = io.BytesIO()
    workbook.save(source)
    source.seek(0)
    helpers, _ = load_tabular_schema_helpers()
    schema = helpers["_build_tabular_schema_summary"](source, "active-source.xlsx", ".xlsx")
    units = [
        ContentUnit("sheet", "Budget", {"kind": "table_sheet", "sheet_index": 1}),
        ContentUnit("original-native", "original-private-canary", {"kind": "excel_native"}),
    ]
    chunks = _tabular_publication_chunks(
        units, "active-source.xlsx", 1024, include_native=False, schema_text=schema,
    )
    text = "\n".join(chunk["chunk_text"] for chunk in chunks)
    assert "header_row=2;" in text
    assert "Columns (2): Site, Cap" in text
    assert "original-private-canary" not in text
