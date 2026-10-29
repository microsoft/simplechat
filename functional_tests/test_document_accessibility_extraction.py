#!/usr/bin/env python3
# test_document_accessibility_extraction.py
"""
Functional test for PDF and Office document accessibility, tag-tree, and comment extraction.
Version: 0.261.391
Implemented in: 0.261.391

This test ensures that:
1. PDF accessibility metadata (/MarkInfo, /Lang, /ViewerPreferences, /StructTreeRoot semantic tags,
   attributed vs. unattributed <Span> nodes, <Figure /Alt>, <Table>/<TH /Scope>, /AcroForm /TU,
   /Artifact blocks, and /Annots page comments) is extracted into both the parent Cosmos metadata
   structure and per-page AI Search chunk blocks.
2. Office (.docx, .docm, .dotx, .pptx) native accessibility properties (heading hierarchy vs.
   pseudo-headings, structured vs. manual lists, table headers and merged cells, embedded object
   alt text and decorative flags, floating/overlapping placement, hidden text, color contrast,
   and slide comments/reading order) are extracted and merged inline into chunks.
3. Parent Cosmos accessibility_metadata is formatted cleanly for chat RAG metadata citations.
"""

import ast
import logging
import os
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from functions_accessibility import (  # noqa: E402
    build_word_chunk_accessibility_items,
    compute_wcag_contrast_ratio,
    extract_office_accessibility_metadata,
    extract_pdf_accessibility_metadata,
    extract_pdf_page_annotations,
    extract_pptx_comments,
    format_accessibility_metadata_for_chat,
    format_pdf_page_annotation_block,
    format_pptx_comment_block,
)
from functions_office_media import (  # noqa: E402
    extract_office_embedded_images,
    format_word_comment_block,
    strip_appended_word_comments,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _build_png_bytes(width=300, height=220, color=(30, 120, 200)):
    buffer = BytesIO()
    img = Image.new("RGB", (width, height), color)
    for x in range(0, width, 3):
        for y in range(0, height, 3):
            img.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, ((x + y) * 13) % 256))
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _load_document_enrichment_helpers():
    """Load the inline chunk enrichment helpers from functions_documents.py via AST."""
    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "_append_inline_page_supplements_with_budget",
        "_enrich_pdf_pages_with_comments_and_accessibility",
        "_enrich_pptx_slides_with_comments_and_accessibility",
        "_resolve_embedded_image_chunk_index",
        "_merge_embedded_images_into_chunks",
    }
    namespace = {
        "os": os,
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "get_embedding_safe_chunk_characters": lambda settings=None: 20889,
        "OFFICE_IMAGE_MERGE_FALLBACK_CHAR_LIMIT": 20889,
        "OFFICE_IMAGE_MERGE_MIN_CHAR_LIMIT": 4000,
        "format_pdf_page_annotation_block": format_pdf_page_annotation_block,
        "format_pptx_comment_block": format_pptx_comment_block,
    }
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_documents.py", "exec"), namespace)
    return namespace


def _create_tagged_pdf_with_annotations(pdf_path):
    """Create a 1-page PDF with /StructTreeRoot tags, /MarkInfo, /Lang, /Artifact, and /Annots."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Quarterly Accessibility Report", fontsize=18)
    page.insert_text((72, 110), "Payment terms are 30 days net.", fontsize=12)

    # Add sticky note and highlight annotations
    text_annot = page.add_text_annot((72, 110), "Verify accessibility tag order on this section.")
    text_annot.set_info(title="Ada Lovelace", content="Verify accessibility tag order on this section.")
    text_annot.update()

    hl_annot = page.add_highlight_annot(fitz.Rect(70, 98, 260, 120))
    hl_annot.set_info(title="Grace Hopper", content="Highlight comment on payment terms.")
    hl_annot.update()

    doc.set_metadata({"title": "Q4 Accessibility Report", "author": "Paul"})
    doc.set_toc([[1, "Quarterly Accessibility Report", 1]])

    raw_bytes = doc.tobytes()
    doc.close()

    reader = PdfReader(BytesIO(raw_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_metadata({"/Title": "Q4 Accessibility Report", "/Author": "Paul"})
    writer.add_outline_item("Quarterly Accessibility Report", 0)

    page_ref = writer.pages[0].indirect_reference
    writer.pages[0][NameObject("/Tabs")] = NameObject("/S")

    # Inject an /Artifact marked-content sequence in page contents
    existing_stream = writer.pages[0].get_contents()
    stream_data = existing_stream.get_data() if existing_stream else b""
    artifact_stream = b"/Artifact BMC\nBT (Footer Page 1) Tj ET\nEMC\n" + stream_stream_bytes(stream_data)
    from pypdf.generic import DecodedStreamObject
    new_stream = DecodedStreamObject()
    new_stream.set_data(artifact_stream)
    writer.pages[0][NameObject("/Contents")] = writer._add_object(new_stream)

    # Build /StructTreeRoot with H1, H3 (skipped H2), P with unattributed Span + attributed Span (/Lang fr-FR),
    # Figure with /Alt, Figure without /Alt, and Table with TH (/Scope /Col) + TD
    h1_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/H1"),
        NameObject("/Pg"): page_ref,
        NameObject("/T"): TextStringObject("Quarterly Accessibility Report"),
    }))
    h3_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/H3"),
        NameObject("/Pg"): page_ref,
        NameObject("/T"): TextStringObject("Skipped Heading Level"),
    }))
    unattr_span = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Span"),
        NameObject("/Pg"): page_ref,
    }))
    attr_span = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Span"),
        NameObject("/Pg"): page_ref,
        NameObject("/Lang"): TextStringObject("fr-FR"),
        NameObject("/E"): TextStringObject("World Wide Web Consortium"),
    }))
    p_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/P"),
        NameObject("/Pg"): page_ref,
        NameObject("/K"): ArrayObject([unattr_span, attr_span]),
    }))
    fig_with_alt = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Figure"),
        NameObject("/Pg"): page_ref,
        NameObject("/Alt"): TextStringObject("Bar chart of quarterly accessibility compliance scores"),
    }))
    fig_missing_alt = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Figure"),
        NameObject("/Pg"): page_ref,
    }))
    th_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/TH"),
        NameObject("/Pg"): page_ref,
        NameObject("/A"): DictionaryObject({
            NameObject("/O"): NameObject("/Table"),
            NameObject("/Scope"): NameObject("/Col"),
        }),
    }))
    td_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/TD"),
        NameObject("/Pg"): page_ref,
    }))
    tr_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/TR"),
        NameObject("/Pg"): page_ref,
        NameObject("/K"): ArrayObject([th_elem, td_elem]),
    }))
    table_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Table"),
        NameObject("/Pg"): page_ref,
        NameObject("/K"): ArrayObject([tr_elem]),
    }))

    doc_elem = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Document"),
        NameObject("/Pg"): page_ref,
        NameObject("/K"): ArrayObject([h1_elem, h3_elem, p_elem, fig_with_alt, fig_missing_alt, table_elem]),
    }))

    struct_tree_root = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/StructTreeRoot"),
        NameObject("/K"): ArrayObject([doc_elem]),
    }))

    # Add an AcroForm field missing /TU tooltip
    form_field = writer._add_object(DictionaryObject({
        NameObject("/FT"): NameObject("/Tx"),
        NameObject("/T"): TextStringObject("ReviewerName"),
        NameObject("/Ff"): NumberObject(2),
    }))
    acro_form = writer._add_object(DictionaryObject({
        NameObject("/Fields"): ArrayObject([form_field]),
    }))

    writer._root_object[NameObject("/MarkInfo")] = DictionaryObject({
        NameObject("/Marked"): BooleanObject(True),
        NameObject("/Suspects"): BooleanObject(False),
    })
    writer._root_object[NameObject("/Lang")] = TextStringObject("en-US")
    writer._root_object[NameObject("/ViewerPreferences")] = DictionaryObject({
        NameObject("/DisplayDocTitle"): BooleanObject(True),
    })
    writer._root_object[NameObject("/StructTreeRoot")] = struct_tree_root
    writer._root_object[NameObject("/AcroForm")] = acro_form

    with open(pdf_path, "wb") as handle:
        writer.write(handle)


def stream_stream_bytes(data):
    return data if isinstance(data, bytes) else b""


def test_pdf_accessibility_and_annotation_extraction():
    """Validate PDF /StructTreeRoot, /MarkInfo, /Lang, /Artifact, /AcroForm, and /Annots extraction."""
    print("Testing PDF accessibility and page annotation extraction...")
    assert_app_version_at_least("0.261.391")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tagged_pdf_path = os.path.join(tmp_dir, "tagged_report.pdf")
        _create_tagged_pdf_with_annotations(tagged_pdf_path)

        cosmos_meta, per_page_details = extract_pdf_accessibility_metadata(tagged_pdf_path)
        page_annots = extract_pdf_page_annotations(tagged_pdf_path)

        assert cosmos_meta["is_tagged"] is True
        assert cosmos_meta["has_struct_tree"] is True
        assert cosmos_meta["language"] == "en-US"
        assert cosmos_meta["title"] == "Q4 Accessibility Report"
        assert cosmos_meta["display_doc_title"] is True
        assert cosmos_meta["has_bookmarks"] is True
        assert cosmos_meta["page_tabs_order"]["structure_order_pages"] == 1
        assert cosmos_meta["artifacts_summary"]["total_artifact_blocks"] >= 1

        # Verify unattributed <Span> was coalesced while attributed <Span /Lang (fr-FR)> was preserved
        assert cosmos_meta["coalesced_span_count"] == 1
        attributed_spans = [
            node for node in cosmos_meta["semantic_tag_tree"]
            if node.get("tag") == "Span"
        ]
        assert len(attributed_spans) == 1
        assert attributed_spans[0].get("lang") == "fr-FR"
        assert attributed_spans[0].get("expansion") == "World Wide Web Consortium"

        # Verify figure alt text summary
        assert cosmos_meta["figures_summary"]["total"] == 2
        assert cosmos_meta["figures_summary"]["with_alt"] == 1
        assert cosmos_meta["figures_summary"]["missing_alt"] == 1

        # Verify table TH and scope summary
        assert cosmos_meta["tables_summary"]["total"] == 1
        assert cosmos_meta["tables_summary"]["with_headers"] == 1
        assert cosmos_meta["tables_summary"]["items"][0]["scopes"] == ["Col"]

        # Verify AcroForm tooltip detection
        assert cosmos_meta["forms_summary"]["total_fields"] == 1
        assert cosmos_meta["forms_summary"]["missing_tooltip"] == 1

        # Verify actionable issues detected (skipped H1->H3, figure missing /Alt, form missing /TU)
        issue_codes = {issue["code"] for issue in cosmos_meta["issues"]}
        assert "PDF_SKIPPED_HEADING_LEVELS" in issue_codes
        assert "PDF_FIGURES_MISSING_ALT" in issue_codes
        assert "PDF_FORMS_MISSING_TOOLTIP" in issue_codes

        # Verify PDF page annotations & inline page enrichment
        assert 1 in page_annots
        assert len(page_annots[1]) == 2
        helpers = _load_document_enrichment_helpers()
        enriched_pages, annot_count = helpers["_enrich_pdf_pages_with_comments_and_accessibility"](
            [{"page_number": 1, "content": "# Quarterly Accessibility Report\nPayment terms are 30 days net."}],
            per_page_details,
            {},
        )
        assert annot_count == 2
        page_chunk_text = enriched_pages[0]["content"]
        assert "### Page comment 1 of 2" in page_chunk_text
        assert "Ada Lovelace" in page_chunk_text
        assert "### Page Accessibility & Tag Structure (Page 1)" in page_chunk_text
        assert "<Figure alt=\"Bar chart of quarterly accessibility compliance scores\">" in page_chunk_text
        assert "<Figure alt=MISSING>" in page_chunk_text
        assert "<TH scope=Col>" in page_chunk_text

        # Also test an untagged PDF
        untagged_path = os.path.join(tmp_dir, "untagged.pdf")
        raw_doc = fitz.open()
        p = raw_doc.new_page()
        p.insert_text((72, 72), "Untagged content")
        raw_doc.save(untagged_path)
        raw_doc.close()

        untagged_meta, _ = extract_pdf_accessibility_metadata(untagged_path)
        untagged_codes = {issue["code"] for issue in untagged_meta["issues"]}
        assert untagged_meta["is_tagged"] is False
        assert "PDF_UNTAGGED" in untagged_codes
        assert "PDF_MISSING_LANGUAGE" in untagged_codes
        assert "PDF_MISSING_TITLE" in untagged_codes

    print("PDF accessibility and annotation extraction test passed!")
    return True


def _build_test_docx_with_a11y_signals(docx_path):
    """Build a DOCX/DOCM archive containing rich accessibility signals and embedded images."""
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    wp_ns = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    pic_ns = "http://schemas.openxmlformats.org/drawingml/2006/picture"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    adec_ns = "http://schemas.microsoft.com/office/drawing/2017/decorative"

    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>Employee Handbook</dc:title>'
        '<dc:creator>Jane Doe</dc:creator>'
        '<dc:subject>Accessibility Policy</dc:subject>'
        '<cp:keywords>accessibility; handbook; policy</cp:keywords>'
        '</cp:coreProperties>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{w_ns}">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="en-US"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '</w:styles>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image2.png"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image3.png"/>'
        '<Relationship Id="rIdLink1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/policy" TargetMode="External"/>'
        '</Relationships>'
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{w_ns}" xmlns:wp="{wp_ns}" xmlns:a="{a_ns}" '
        f'xmlns:pic="{pic_ns}" xmlns:r="{r_ns}" xmlns:adec="{adec_ns}">'
        '<w:body>'
        # H1 heading
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>1. Introduction</w:t></w:r></w:p>'
        # Pseudo-heading (Normal style, all-bold, 16pt = 32 half-points)
        '<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr>'
        '<w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t>Important Notice Visual Heading</w:t></w:r></w:p>'
        # Skipped heading level (H3 after H1)
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>1.1.1 Detailed Scope</w:t></w:r></w:p>'
        # Manual bullet paragraph
        '<w:p><w:r><w:t>• Manually typed bullet item without list style</w:t></w:r></w:p>'
        # Hidden text and low-contrast text + generic hyperlink
        '<w:p>'
        '<w:r><w:rPr><w:vanish/></w:rPr><w:t>Internal draft secret note</w:t></w:r>'
        '<w:r><w:rPr><w:color w:val="CCCCCC"/><w:shd w:fill="FFFFFF"/></w:rPr><w:t>Low contrast gray text</w:t></w:r>'
        '<w:hyperlink r:id="rIdLink1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>'
        '</w:p>'
        # Image 1: inline with alt text
        '<w:p><w:r><w:drawing><wp:inline>'
        '<wp:docPr id="1" name="OrgChart" descr="Organizational hierarchy chart"/>'
        '<a:graphic><a:graphicData><pic:pic><pic:blipFill><a:blip r:embed="rId1"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>'
        '</wp:inline></w:drawing></w:r></w:p>'
        # Image 2: inline decorative
        '<w:p><w:r><w:drawing><wp:inline>'
        '<wp:docPr id="2" name="Divider"><a:extLst><a:ext uri="{C183D7F6}"><adec:decorative val="1"/></a:ext></a:extLst></wp:docPr>'
        '<a:graphic><a:graphicData><pic:pic><pic:blipFill><a:blip r:embed="rId2"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>'
        '</wp:inline></w:drawing></w:r></w:p>'
        # Image 3: floating anchor with overlap and missing alt text
        '<w:p><w:r><w:drawing><wp:anchor allowOverlap="1" behindDoc="1">'
        '<wp:docPr id="3" name="FloatingBadge"/>'
        '<a:graphic><a:graphicData><pic:pic><pic:blipFill><a:blip r:embed="rId3"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>'
        '</wp:anchor></w:drawing></w:r></w:p>'
        # Table without w:tblHeader and with w:gridSpan merged cell
        '<w:tbl>'
        '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>Merged Header</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl>'
        '</w:body></w:document>'
    )

    with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("word/styles.xml", styles_xml)
        zf.writestr("word/_rels/document.xml.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/media/image1.png", _build_png_bytes(320, 240, (20, 100, 180)))
        zf.writestr("word/media/image2.png", _build_png_bytes(340, 240, (90, 150, 60)))
        zf.writestr("word/media/image3.png", _build_png_bytes(360, 240, (180, 70, 40)))


def test_word_ooxml_accessibility_and_embedded_image_attributes():
    """Validate Word (.docx/.docm) accessibility extraction, native image attributes, and chunk blocks."""
    print("Testing Word OOXML accessibility and embedded image metadata...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        docm_path = os.path.join(tmp_dir, "policy.docm")
        img_out_dir = os.path.join(tmp_dir, "images")
        os.makedirs(img_out_dir, exist_ok=True)
        _build_test_docx_with_a11y_signals(docm_path)

        cosmos_meta, structural_events = extract_office_accessibility_metadata(docm_path, ".docm")
        assert cosmos_meta["format"] == "docm"
        assert cosmos_meta["title"] == "Employee Handbook"
        assert cosmos_meta["language"] == "en-US"
        assert cosmos_meta["subject"] == "Accessibility Policy"
        assert cosmos_meta["keywords"] == ["accessibility", "handbook", "policy"]

        # Headings & pseudo-headings
        assert len(cosmos_meta["heading_outline"]) == 2
        assert len(cosmos_meta["pseudo_headings"]) == 1
        assert "Important Notice Visual Heading" in cosmos_meta["pseudo_headings"][0]["text"]

        # Lists, tables, figures, links, formatting cues
        assert cosmos_meta["lists_summary"]["manual_bullet_paragraphs"] == 1
        assert cosmos_meta["tables_summary"]["total"] == 1
        assert cosmos_meta["tables_summary"]["missing_header_row"] == 1
        assert cosmos_meta["tables_summary"]["with_merged_cells"] == 1

        assert cosmos_meta["figures_summary"]["total"] == 3
        assert cosmos_meta["figures_summary"]["with_alt"] == 2  # 1 descr + 1 decorative
        assert cosmos_meta["figures_summary"]["decorative"] == 1
        assert cosmos_meta["figures_summary"]["missing_alt"] == 1
        assert cosmos_meta["figures_summary"]["floating_objects"] == 1
        assert cosmos_meta["figures_summary"]["overlapping_objects"] == 1

        assert cosmos_meta["links_summary"]["generic_link_text"] == 1
        assert cosmos_meta["formatting_and_layout"]["hidden_text_runs"] == 1
        assert cosmos_meta["formatting_and_layout"]["low_contrast_runs"] == 1
        assert compute_wcag_contrast_ratio("CCCCCC", "FFFFFF") < 2.0

        issue_codes = {issue["code"] for issue in cosmos_meta["issues"]}
        for expected_code in (
            "OFFICE_SKIPPED_HEADING_LEVELS",
            "OFFICE_PSEUDO_HEADINGS",
            "OFFICE_MANUAL_LISTS",
            "OFFICE_TABLES_MISSING_HEADER_ROW",
            "OFFICE_TABLES_MERGED_CELLS",
            "OFFICE_FIGURES_MISSING_ALT",
            "OFFICE_FLOATING_OBJECTS",
            "OFFICE_GENERIC_LINK_TEXT",
            "OFFICE_HIDDEN_TEXT",
            "OFFICE_LOW_COLOR_CONTRAST",
        ):
            assert expected_code in issue_codes, f"Expected {expected_code} in {issue_codes}"

        # Verify extract_office_embedded_images attaches native accessibility attributes
        extracted_imgs = extract_office_embedded_images(docm_path, img_out_dir, min_pixels=150, max_images=10)
        assert len(extracted_imgs) == 3
        by_name = {img["name"]: img for img in extracted_imgs}
        assert by_name["image1.png"]["alt_text"] == "Organizational hierarchy chart"
        assert by_name["image1.png"]["is_decorative"] is False
        assert by_name["image2.png"]["is_decorative"] is True
        assert by_name["image3.png"]["alt_text"] == ""
        assert by_name["image3.png"]["placement"] == "floating"
        assert by_name["image3.png"]["allow_overlap"] is True

        # Verify section accessibility blocks merge inline into Word chunks
        a11y_chunk_items = build_word_chunk_accessibility_items(cosmos_meta, structural_events)
        assert a11y_chunk_items
        helpers = _load_document_enrichment_helpers()
        merged_chunks, merged_cnt, overflow = helpers["_merge_embedded_images_into_chunks"](
            [{"page_number": 1, "content": "1. Introduction\nImportant Notice Visual Heading"}],
            a11y_chunk_items,
            cosmos_meta["total_body_words"],
            {},
        )
        assert merged_cnt >= 1
        assert not overflow
        assert "### Section Accessibility & Structure" in merged_chunks[0]["content"]
        assert "Pseudo-heading" in merged_chunks[0]["content"]

    print("Word OOXML accessibility and embedded image test passed!")
    return True


def _build_test_pptx_with_comments_and_a11y(pptx_path):
    """Build a 2-slide PPTX with slide comments, reading-order inversion, and figure/table checks."""
    p_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    slide1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{p_ns}" xmlns:a="{a_ns}" xmlns:r="{r_ns}">'
        '<p:cSld><p:spTree>'
        '<p:sp><p:nvSpPr><p:cNvPr id="1" name="Title 1"/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="100" y="100"/></a:xfrm></p:spPr>'
        '<p:txBody><a:p><a:r><a:t>Executive Summary</a:t></a:r></a:p></p:txBody></p:sp>'
        '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Chart 1" descr="Revenue trend chart"/></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="rIdImg1"/></p:blipFill></p:pic>'
        '</p:spTree></p:cSld></p:sld>'
    )
    # Slide 2: no title placeholder, Z-order bottom shape listed before top shape, image missing alt, table missing firstRow
    slide2_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{p_ns}" xmlns:a="{a_ns}" xmlns:r="{r_ns}">'
        '<p:cSld><p:spTree>'
        '<p:sp><p:nvSpPr><p:cNvPr id="10" name="Footer Callout"/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="100" y="5000"/></a:xfrm></p:spPr>'
        '<p:txBody><a:p><a:r><a:t>Read first by screen reader even though visually at bottom</a:t></a:r></a:p></p:txBody></p:sp>'
        '<p:sp><p:nvSpPr><p:cNvPr id="11" name="Visual Header"/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="100" y="200"/></a:xfrm></p:spPr>'
        '<p:txBody><a:p><a:r><a:t>Visually at top but second in Z-order</a:t></a:r></a:p></p:txBody></p:sp>'
        '<p:pic><p:nvPicPr><p:cNvPr id="12" name="Unlabeled Diagram"/></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="rIdImg2"/></p:blipFill></p:pic>'
        '<p:graphicFrame><a:graphic><a:graphicData><a:tbl firstRow="0">'
        '<a:tr><a:tc gridSpan="2"><a:txBody><a:p><a:r><a:t>Merged Slide Cell</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
        '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>'
        '</p:spTree></p:cSld></p:sld>'
    )
    slide1_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdImg1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>'
        '<Relationship Id="rIdCom1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="../comments/comment1.xml"/>'
        '</Relationships>'
    )
    comment_authors_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:cmAuthorLst xmlns:p="{p_ns}">'
        '<p:cmAuthor id="0" name="Clara Reviewer" initials="CR"/>'
        '</p:cmAuthorLst>'
    )
    comment1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:cmLst xmlns:p="{p_ns}">'
        '<p:cm authorId="0" dt="2025-03-01T10:15:00Z">'
        '<p:text>Please add contrast labels to the revenue bars on Slide 1.</p:text>'
        '</p:cm>'
        '</p:cmLst>'
    )

    with zipfile.ZipFile(pptx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("ppt/slides/slide1.xml", slide1_xml)
        zf.writestr("ppt/slides/slide2.xml", slide2_xml)
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", slide1_rels)
        zf.writestr("ppt/commentAuthors.xml", comment_authors_xml)
        zf.writestr("ppt/comments/comment1.xml", comment1_xml)
        zf.writestr("ppt/media/image1.png", _build_png_bytes(320, 240, (40, 120, 180)))


def test_pptx_accessibility_and_slide_comments():
    """Validate PowerPoint (.pptx) accessibility inspection, slide comments, and chat formatting."""
    print("Testing PowerPoint (.pptx) accessibility and slide comments...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        pptx_path = os.path.join(tmp_dir, "deck.pptx")
        _build_test_pptx_with_comments_and_a11y(pptx_path)

        comments_by_slide = extract_pptx_comments(pptx_path)
        assert 1 in comments_by_slide
        assert comments_by_slide[1][0]["author"] == "Clara Reviewer"
        assert "contrast labels" in comments_by_slide[1][0]["text"]

        cosmos_meta, per_slide_details = extract_office_accessibility_metadata(pptx_path, ".pptx")
        assert cosmos_meta["slide_count"] == 2
        assert cosmos_meta["slides_missing_titles"] == [2]
        assert cosmos_meta["slides_with_reading_order_warnings"] == [2]
        assert cosmos_meta["figures_summary"]["total"] == 2
        assert cosmos_meta["figures_summary"]["with_alt"] == 1
        assert cosmos_meta["figures_summary"]["missing_alt"] == 1
        assert cosmos_meta["tables_summary"]["missing_header_row"] == 1

        helpers = _load_document_enrichment_helpers()
        enriched_slides, slide_comment_count = helpers["_enrich_pptx_slides_with_comments_and_accessibility"](
            [
                {"page_number": 1, "content": "# Executive Summary"},
                {"page_number": 2, "content": "Unlabeled slide content"},
            ],
            per_slide_details,
            {},
        )
        assert slide_comment_count == 1
        assert "### Slide comment 1 of 1 by Clara Reviewer (CR)" in enriched_slides[0]["content"]
        assert "### Slide Accessibility & Structure (Slide 1)" in enriched_slides[0]["content"]
        assert "### Slide Accessibility & Structure (Slide 2)" in enriched_slides[1]["content"]
        assert "WARNING: Z-order differs from top-to-bottom visual placement" in enriched_slides[1]["content"]

        chat_summary = format_accessibility_metadata_for_chat(cosmos_meta)
        assert "Document Accessibility & Structure Summary (PPTX):" in chat_summary
        assert "PPTX_SLIDES_MISSING_TITLES" in chat_summary
        assert "PPTX_READING_ORDER_MISMATCH" in chat_summary

    print("PowerPoint accessibility and slide comments test passed!")
    return True


def test_get_document_metadata_for_citations_returns_accessibility_metadata():
    """Validate get_document_metadata_for_citations returns accessibility_metadata and summary from Cosmos."""
    print("Testing get_document_metadata_for_citations with accessibility_metadata...")
    from azure.cosmos._cosmos_responses import CosmosDict

    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target_fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "get_document_metadata_for_citations":
            target_fn = node
            break
    assert target_fn is not None

    stored_doc = CosmosDict({
        "id": "doc-a11y-1",
        "file_name": "audit.pdf",
        "title": "Audit Report",
        "authors": ["Paul"],
        "language": "en-US",
        "keywords": ["accessibility", "pdf"],
        "abstract": "Quarterly audit",
        "accessibility_metadata": {
            "format": "pdf",
            "is_tagged": False,
            "has_struct_tree": False,
            "language": "",
            "title": "Audit Report",
            "display_doc_title": False,
            "bookmark_count": 0,
            "issues": [
                {
                    "code": "PDF_UNTAGGED",
                    "severity": "high",
                    "message": "PDF is not tagged.",
                }
            ],
        },
    }, response_headers={})

    class _StubContainer:
        def get_item(self, item, partition_key):
            assert item == "doc-a11y-1"
            assert partition_key == "doc-a11y-1"
            return stored_doc

    stub_container = _StubContainer()
    stub_container.__dict__["read_" + "item"] = stub_container.get_item

    namespace = {
        "cosmos_public_documents_container": stub_container,
        "cosmos_group_documents_container": stub_container,
        "cosmos_user_documents_container": stub_container,
        "assert_document_available": lambda doc, *args, **kwargs: dict(doc),
        "format_accessibility_metadata_for_chat": format_accessibility_metadata_for_chat,
        "ScreeningError": RuntimeError,
    }
    exec(compile(ast.Module(body=[target_fn], type_ignores=[]), "functions_documents.py", "exec"), namespace)
    fn = namespace["get_document_metadata_for_citations"]

    result = fn("doc-a11y-1", user_id="user-1")
    assert result is not None
    assert result["file_name"] == "audit.pdf"
    assert result["title"] == "Audit Report"
    assert result["language"] == "en-US"
    assert result["accessibility_metadata"]["is_tagged"] is False
    assert "PDF_UNTAGGED" in result["accessibility_summary"]
    assert "Untagged PDF" in result["accessibility_summary"]

    print("get_document_metadata_for_citations accessibility test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_pdf_accessibility_and_annotation_extraction,
        test_word_ooxml_accessibility_and_embedded_image_attributes,
        test_pptx_accessibility_and_slide_comments,
        test_get_document_metadata_for_citations_returns_accessibility_metadata,
    ]
    results = [test() for test in tests]
    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
