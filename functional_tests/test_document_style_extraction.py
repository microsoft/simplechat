#!/usr/bin/env python3
# test_document_style_extraction.py
"""
Functional test for font, size, colour, and layout (style) extraction.
Version: 0.261.392
Implemented in: 0.261.392

This test ensures that:
1. PDF text spans produce a bounded style_inventory (body font/size, outlier runs, non-embedded fonts)
   plus a per-page Formatting line.
2. Word (.docx) formatting is resolved through the style chain, document defaults, and the theme, and
   lands inline in word-offset chunk blocks.
3. PowerPoint (.pptx) formatting is resolved and merged into per-slide blocks.
4. Legacy .doc files yield best-effort direct run formatting from the CHPX bin table, FKP pages, and
   font table.
5. The chat context block carries the formatting summary and the pointer to the programmatic report.
"""

import os
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

import fitz


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from functions_accessibility import (  # noqa: E402
    build_word_chunk_accessibility_items,
    extract_office_accessibility_metadata,
    extract_pdf_accessibility_metadata,
    format_accessibility_metadata_for_chat,
    word_chunk_bucket_size,
)
from functions_document_style import (  # noqa: E402
    MAX_STYLE_OUTLIERS,
    StyleAccumulator,
    format_style_inventory_for_chat,
    safe_style_extraction,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_word_comment_extraction import (  # noqa: E402
    FUNCTIONS_CONTENT,
    _build_legacy_doc_streams_with_comment,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _build_styled_pdf(pdf_path):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "Quarterly policy overview body text", fontsize=12, fontname="helv")
    page.insert_text((72, 130), "More body text that dominates the page", fontsize=12, fontname="helv")
    page.insert_text((72, 160), "Tiny red footnote", fontsize=7, fontname="cour", color=(1, 0, 0))
    document.save(pdf_path)
    document.close()


def test_pdf_style_inventory():
    print("Testing PDF style inventory...")
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = os.path.join(temp_dir, "styled.pdf")
        _build_styled_pdf(pdf_path)
        meta, per_page = extract_pdf_accessibility_metadata(pdf_path)

    inventory = meta["style_inventory"]
    assert inventory["body_size_pt"] == 12
    assert inventory["min_size_pt"] == 7
    assert inventory["font_count"] == 2
    assert inventory["body_font"] and inventory["body_font"] != "Courier"
    assert any(color["color"] == "#FF0000" for color in inventory["colors"])

    outliers = inventory["outliers"]
    assert any(
        outlier["size_pt"] == 7 and "smaller_than_body" in outlier["reasons"] and outlier["page_number"] == 1
        for outlier in outliers
    ), outliers
    assert "non_embedded_fonts" in inventory
    assert any(issue["code"] == "PDF_FONTS_NOT_EMBEDDED" for issue in meta["issues"])

    page_one = per_page[1] if isinstance(per_page, dict) else per_page[0]
    assert "Formatting" in str(page_one), page_one

    chat_text = format_accessibility_metadata_for_chat(meta)
    assert "get_document_accessibility_report" in chat_text
    print("PDF style inventory test passed!")
    return True


def _build_styled_docx(docx_path):
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{W_NS}">'
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:asciiTheme="minorHAnsi"/><w:sz w:val="22"/>'
        '</w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:rFonts w:ascii="Georgia"/><w:b/><w:sz w:val="32"/><w:color w:val="1F3864"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Heading1"/>'
        '<w:rPr><w:sz w:val="26"/></w:rPr></w:style>'
        '</w:styles>'
    )
    theme_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<a:theme xmlns:a="{A_NS}"><a:themeElements><a:fontScheme name="t">'
        '<a:majorFont><a:latin typeface="Cambria"/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Calibri"/></a:minorFont>'
        '</a:fontScheme></a:themeElements></a:theme>'
    )
    body_paragraphs = "".join(
        f'<w:p><w:r><w:t>Body paragraph {index} with several ordinary words in it.</w:t></w:r></w:p>'
        for index in range(30)
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Inherited heading</w:t></w:r></w:p>'
        f'{body_paragraphs}'
        '<w:p><w:r><w:rPr><w:rFonts w:ascii="Courier New"/><w:sz w:val="14"/><w:color w:val="FF0000"/></w:rPr>'
        '<w:t>Tiny red courier fine print</w:t></w:r></w:p>'
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body></w:document>'
    )
    with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/styles.xml", styles_xml)
        archive.writestr("word/theme/theme1.xml", theme_xml)
        archive.writestr("word/document.xml", document_xml)


def test_docx_style_inventory_and_chunk_blocks():
    print("Testing DOCX style inventory...")
    with tempfile.TemporaryDirectory() as temp_dir:
        docx_path = os.path.join(temp_dir, "styled.docx")
        _build_styled_docx(docx_path)
        meta, events = extract_office_accessibility_metadata(docx_path, ".docx")

    inventory = meta["style_inventory"]
    assert inventory["body_font"] == "Calibri", inventory["body_font"]
    assert inventory["body_size_pt"] == 11
    assert inventory["min_size_pt"] == 7
    font_names = {font["name"] for font in inventory["fonts"]}
    assert {"Calibri", "Georgia", "Courier New"} <= font_names, font_names

    heading_style = next(s for s in inventory["paragraph_styles"] if s["style_id"] == "Heading2")
    assert heading_style["font"] == "Georgia"
    assert heading_style["size_pt"] == 13
    assert heading_style["bold"] is True

    outlier = next(o for o in inventory["outliers"] if o["font"] == "Courier New")
    assert outlier["size_pt"] == 7 and outlier["color"] == "#FF0000"
    assert "smaller_than_body" in outlier["reasons"]
    assert inventory["page_setup"], inventory

    formatting_events = [event for event in events if event.get("kind") == "formatting"]
    assert formatting_events and all("word_offset" in event for event in formatting_events)
    items = build_word_chunk_accessibility_items(meta, events)
    assert any("Formatting" in item["content"] for item in items)

    assert word_chunk_bucket_size(0) >= 200
    print("DOCX style inventory test passed!")
    return True


def _build_styled_pptx(pptx_path):
    slide_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}"><p:cSld><p:spTree>'
        '<p:sp><p:nvSpPr><p:cNvPr id="1" name="Body"/><p:nvPr/></p:nvSpPr>'
        '<p:txBody><a:p><a:r><a:rPr sz="2000"><a:latin typeface="Arial"/>'
        '<a:solidFill><a:srgbClr val="333333"/></a:solidFill></a:rPr><a:t>Main bullet text here</a:t></a:r></a:p>'
        '<a:p><a:r><a:rPr sz="900"><a:latin typeface="Comic Sans MS"/></a:rPr><a:t>Tiny note</a:t></a:r></a:p>'
        '</p:txBody></p:sp>'
        '</p:spTree></p:cSld></p:sld>'
    )
    with zipfile.ZipFile(pptx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/slides/slide1.xml", slide_xml)


def test_pptx_style_inventory():
    print("Testing PPTX style inventory...")
    with tempfile.TemporaryDirectory() as temp_dir:
        pptx_path = os.path.join(temp_dir, "styled.pptx")
        _build_styled_pptx(pptx_path)
        meta, per_slide = extract_office_accessibility_metadata(pptx_path, ".pptx")

    inventory = meta["style_inventory"]
    assert inventory["min_size_pt"] == 9
    assert inventory["max_size_pt"] == 20
    assert {font["name"] for font in inventory["fonts"]} == {"Arial", "Comic Sans MS"}
    assert any(color["color"] == "#333333" for color in inventory["colors"])
    assert "Formatting" in str(per_slide[1] if isinstance(per_slide, dict) else per_slide[0])
    print("PPTX style inventory test passed!")
    return True


def test_accumulator_caps_and_chat_format():
    print("Testing style accumulator caps and chat formatting...")
    accumulator = StyleAccumulator("page")
    accumulator.add(1, "Body text that sets the baseline " * 200, font="Arial", size_pt=12, color="#000000")
    for index in range(MAX_STYLE_OUTLIERS + 50):
        accumulator.add(index + 2, f"Small {index}", font="Arial", size_pt=6 + (index % 3) * 0.5, color="#000000")
    inventory = accumulator.build_inventory()
    assert len(inventory["outliers"]) <= MAX_STYLE_OUTLIERS
    assert inventory["outliers_truncated"] is True
    assert inventory["outlier_run_count"] > MAX_STYLE_OUTLIERS

    accumulator.add(999, "No size known", font=None, size_pt=None)
    assert accumulator.build_inventory()["coverage"] == "partial"

    lines = format_style_inventory_for_chat(inventory)
    assert any("Arial" in line for line in lines)

    assert safe_style_extraction("test", lambda: 1 / 0) is None
    print("Accumulator test passed!")
    return True


def _build_legacy_doc_streams_with_formatting():
    """Extend the comment fixture with a font table, CHPX bin table, and one CHPX FKP page."""
    word_stream, table_stream = _build_legacy_doc_streams_with_comment()
    word_stream = bytearray(word_stream)
    table_stream = bytearray(table_stream)

    def ffn(name):
        encoded = name.encode("utf-16le") + b"\x00\x00"
        body = b"\x00" * 39 + encoded
        return bytes([len(body)]) + body

    font_table = struct.pack("<HH", 2, 0) + ffn("Times New Roman") + ffn("Arial")
    fc_fonts = len(table_stream)
    table_stream.extend(font_table)

    def sprm_u16(opcode, value):
        return struct.pack("<HH", opcode, value)

    run_one = sprm_u16(0x4A4F, 1) + sprm_u16(0x4A43, 24) + struct.pack("<HB", 0x0835, 1)
    run_two = sprm_u16(0x4A4F, 0) + sprm_u16(0x4A43, 20) + struct.pack("<HB", 0x2A42, 6)

    text_start = 1024
    split = text_start + 44
    text_end = text_start + 71 + 1 + 66
    page_offset = 1536
    word_stream.extend(b"\x00" * (page_offset + 512 - len(word_stream)))
    page = bytearray(512)
    struct.pack_into("<III", page, 0, text_start, split, text_end)
    for index, (chpx_offset, grpprl) in enumerate(((100, run_one), (140, run_two))):
        page[12 + index] = chpx_offset // 2
        page[chpx_offset] = len(grpprl)
        page[chpx_offset + 1:chpx_offset + 1 + len(grpprl)] = grpprl
    page[511] = 2
    word_stream[page_offset:page_offset + 512] = page

    bin_table = struct.pack("<II", text_start, text_end) + struct.pack("<I", page_offset // 512)
    fc_bin = len(table_stream)
    table_stream.extend(bin_table)

    offset_fc_lcb = 154
    struct.pack_into("<II", word_stream, offset_fc_lcb + 12 * 8, fc_bin, len(bin_table))
    struct.pack_into("<II", word_stream, offset_fc_lcb + 15 * 8, fc_fonts, len(font_table))
    return bytes(word_stream), bytes(table_stream)


class _FakeStream:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeOleFile:
    streams = {}

    def __init__(self, _path):
        pass

    def exists(self, name):
        return name in self.streams

    def openstream(self, name):
        return _FakeStream(self.streams[name])

    def close(self):
        pass


class _FakeOleModule:
    OleFileIO = _FakeOleFile

    @staticmethod
    def isOleFile(_path):
        return True


def test_legacy_doc_character_runs_best_effort():
    print("Testing legacy .doc best-effort formatting...")
    word_stream, table_stream = _build_legacy_doc_streams_with_formatting()
    _FakeOleFile.streams = {"WordDocument": word_stream, "1Table": table_stream}

    original_olefile = FUNCTIONS_CONTENT.olefile
    FUNCTIONS_CONTENT.olefile = _FakeOleModule
    try:
        result = FUNCTIONS_CONTENT.extract_legacy_doc_character_runs("synthetic.doc")
    finally:
        FUNCTIONS_CONTENT.olefile = original_olefile

    assert result is not None
    runs = result["runs"]
    assert len(runs) == 2, runs
    assert runs[0]["font"] == "Arial" and runs[0]["size_pt"] == 12 and runs[0]["bold"] is True
    assert runs[1]["font"] == "Times New Roman" and runs[1]["size_pt"] == 10
    assert runs[1]["color"] == "#FF0000"
    assert runs[1]["word_offset"] > runs[0]["word_offset"]
    assert result["total_body_words"] == 12
    assert any("best effort" in note for note in result["notes"])

    from functions_document_style import build_legacy_doc_style_inventory

    inventory, events = build_legacy_doc_style_inventory(runs, 200, result["notes"])
    assert inventory["coverage"] == "partial"
    assert inventory["body_font"] == "Arial"
    assert events and events[0]["kind"] == "formatting"
    print("Legacy .doc formatting test passed!")
    return True


def test_legacy_doc_unreadable_returns_none():
    print("Testing legacy .doc unreadable handling...")
    word_stream, table_stream = _build_legacy_doc_streams_with_comment()
    _FakeOleFile.streams = {"WordDocument": word_stream, "1Table": table_stream}
    original_olefile = FUNCTIONS_CONTENT.olefile
    FUNCTIONS_CONTENT.olefile = _FakeOleModule
    try:
        result = FUNCTIONS_CONTENT.extract_legacy_doc_character_runs("synthetic.doc")
    finally:
        FUNCTIONS_CONTENT.olefile = original_olefile
    assert result is not None and result["runs"] == []
    assert FUNCTIONS_CONTENT._parse_legacy_doc_chp_sprms(b"\x43") == {}
    assert FUNCTIONS_CONTENT._parse_legacy_doc_chp_sprms(b"\xff\xff\xff") == {}
    print("Legacy .doc unreadable test passed!")
    return True


def test_version_header():
    assert_app_version_at_least("0.261.392")
    return True


if __name__ == "__main__":
    tests = [
        test_pdf_style_inventory,
        test_docx_style_inventory_and_chunk_blocks,
        test_pptx_style_inventory,
        test_accumulator_caps_and_chat_format,
        test_legacy_doc_character_runs_best_effort,
        test_legacy_doc_unreadable_returns_none,
        test_version_header,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception:
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
