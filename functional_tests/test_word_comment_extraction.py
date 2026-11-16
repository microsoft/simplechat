#!/usr/bin/env python3
# test_word_comment_extraction.py
"""
Functional test for Word document review comment extraction (.docx, .docm, .doc, .dotx).
Version: 0.261.390
Implemented in: 0.261.390

This test ensures that review comments (including author, initials, date, resolved status,
threaded replies, and anchored document text) are extracted from both OOXML Word archives
(.docx/.docm/.dotx) and legacy Word 97-2003 OLE binary documents (.doc), and that comments
merge into the document chunk containing their anchored text.
"""

import ast
import importlib.util
import logging
import os
import re
import struct
import sys
import tempfile
import types
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from functions_office_media import (  # noqa: E402
    extract_docx_comments,
    format_word_comment_block,
    format_word_comments_section,
    strip_appended_word_comments,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


WORDPROCESSING_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"


def _load_functions_content_module():
    """Load functions_content with lightweight stubs for config-heavy imports."""
    module_name = "functions_content_word_comments_test"
    spec = importlib.util.spec_from_file_location(module_name, str(APP_ROOT / "functions_content.py"))
    module = importlib.util.module_from_spec(spec)

    config_stub = types.ModuleType("config")
    config_stub.os = os
    config_stub.re = re
    config_stub.CLIENTS = {}
    config_stub.AZURE_ENVIRONMENT = "public"
    config_stub.WORD_CHUNK_SIZE = 400

    debug_stub = types.ModuleType("functions_debug")
    debug_stub.debug_print = lambda *args, **kwargs: None

    settings_stub = types.ModuleType("functions_settings")
    logging_stub = types.ModuleType("functions_logging")

    original_modules = {
        "config": sys.modules.get("config"),
        "functions_debug": sys.modules.get("functions_debug"),
        "functions_settings": sys.modules.get("functions_settings"),
        "functions_logging": sys.modules.get("functions_logging"),
    }

    sys.modules["config"] = config_stub
    sys.modules["functions_debug"] = debug_stub
    sys.modules["functions_settings"] = settings_stub
    sys.modules["functions_logging"] = logging_stub

    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for module_key, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_key, None)
            else:
                sys.modules[module_key] = original_module


FUNCTIONS_CONTENT = _load_functions_content_module()


def _load_document_functions(function_names):
    """Load selected functions from functions_documents.py in an isolated namespace."""
    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    namespace = {
        "os": os,
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "current_extraction": lambda *args, **kwargs: None,
        "ScreeningError": RuntimeError,
        "extract_word_comments": FUNCTIONS_CONTENT.extract_word_comments,
        "format_word_comment_block": format_word_comment_block,
        "get_chunk_size_cap": lambda settings=None, unit=None: 16384,
        "get_embedding_safe_chunk_characters": lambda settings=None: 20889,
        "OFFICE_IMAGE_MERGE_FALLBACK_CHAR_LIMIT": 20889,
        "OFFICE_IMAGE_MERGE_MIN_CHAR_LIMIT": 4000,
    }

    wanted = set(function_names)
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_documents.py", "exec"), namespace)
            found.add(node.name)

    missing = wanted - found
    if missing:
        raise AssertionError(f"Could not locate functions in functions_documents.py: {sorted(missing)}")
    return namespace


def _build_sample_docx_with_comments(total_paragraphs=60, words_per_paragraph=20):
    """Create a temporary .docx with comments, reply threading, and resolved status."""
    body_parts = []
    for paragraph_index in range(total_paragraphs):
        if paragraph_index == 5:
            body_parts.append(
                '<w:p>'
                '<w:r><w:t>Payment shall be due within </w:t></w:r>'
                '<w:commentRangeStart w:id="0"/>'
                '<w:commentRangeStart w:id="1"/>'
                '<w:r><w:t>30 calendar days</w:t></w:r>'
                '<w:commentRangeEnd w:id="1"/>'
                '<w:commentRangeEnd w:id="0"/>'
                '<w:r><w:commentReference w:id="0"/></w:r>'
                '<w:r><w:commentReference w:id="1"/></w:r>'
                '<w:r><w:t> of invoice receipt.</w:t></w:r>'
                '</w:p>'
            )
            continue
        if paragraph_index == 50:
            body_parts.append(
                '<w:p>'
                '<w:r><w:t>Governing law shall be </w:t></w:r>'
                '<w:commentRangeStart w:id="2"/>'
                '<w:r><w:t>the State of Washington</w:t></w:r>'
                '<w:commentRangeEnd w:id="2"/>'
                '<w:r><w:commentReference w:id="2"/></w:r>'
                '<w:r><w:t> for all disputes.</w:t></w:r>'
                '</w:p>'
            )
            continue

        words = " ".join(f"p{paragraph_index}w{w}" for w in range(words_per_paragraph))
        body_parts.append(f'<w:p><w:r><w:t>{words}</w:t></w:r></w:p>')

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORDPROCESSING_NS}">'
        '<w:body>' + "".join(body_parts) + '</w:body></w:document>'
    )

    comments_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:comments xmlns:w="{WORDPROCESSING_NS}" xmlns:w14="{W14_NS}">'
        '<w:comment w:id="0" w:author="Alice Reviewer" w:initials="AR" w:date="2025-02-10T14:00:00Z">'
        '<w:p w14:paraId="1111AAAA"><w:r><w:t>Please change payment terms to 60 days.</w:t></w:r></w:p>'
        '</w:comment>'
        '<w:comment w:id="1" w:author="Bob Author" w:initials="BA" w:date="2025-02-10T15:30:00Z">'
        '<w:p w14:paraId="2222BBBB"><w:r><w:t>Agreed, updating to 60 days in next draft.</w:t></w:r></w:p>'
        '</w:comment>'
        '<w:comment w:id="2" w:author="Carol Legal" w:initials="CL" w:date="2025-02-11T09:00:00Z">'
        '<w:p w14:paraId="3333CCCC"><w:r><w:t>Confirmed venue clause with legal counsel.</w:t></w:r></w:p>'
        '</w:comment>'
        '</w:comments>'
    )

    comments_extended_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w15:commentsEx xmlns:w15="{W15_NS}">'
        '<w15:commentEx w15:paraId="1111AAAA" w15:done="0"/>'
        '<w15:commentEx w15:paraId="2222BBBB" w15:paraIdParent="1111AAAA" w15:done="0"/>'
        '<w15:commentEx w15:paraId="3333CCCC" w15:done="1"/>'
        '</w15:commentsEx>'
    )

    handle = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    handle.close()
    with zipfile.ZipFile(handle.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/comments.xml", comments_xml)
        archive.writestr("word/commentsExtended.xml", comments_extended_xml)

    return handle.name


def _build_legacy_doc_streams_with_comment():
    """Construct an MS-DOC FIB + WordDocument + 1Table stream with an annotation subdocument."""
    body_text = "Contract body text before the review clause. Payment terms are net 30.\r"
    comment_text = "\x05Please verify if net 30 should be net 45 for enterprise customers.\r"
    full_text = body_text + comment_text

    text_offset = 1024
    encoded_text = full_text.encode("cp1252")

    # Build table stream containing:
    # 1. Clx with PlcPcd piece table covering full_text
    fc_compressed = 0x40000000 | (text_offset * 2)
    piece_descriptor = b"\x00\x00" + struct.pack("<I", fc_compressed) + b"\x00\x00"
    piece_table = struct.pack("<II", 0, len(full_text)) + piece_descriptor
    clx_bytes = b"\x02" + struct.pack("<I", len(piece_table)) + piece_table

    # 2. GrpXstAtnOwners with one author: "Paul Lizer"
    owner_name = "Paul Lizer"
    owner_utf16 = owner_name.encode("utf-16le")
    owners_bytes = struct.pack("<H", len(owner_name)) + owner_utf16

    # 3. PlcfandTxt: 2 CPs (0 to len(comment_text)) relative to ccpAtn start
    plcfand_txt_bytes = struct.pack("<II", 0, len(comment_text))

    # 4. PlcfandRef: 2 CPs (anchor_cp, len(body_text)) + one 30-byte ATRDPre10
    anchor_cp = body_text.index("net 30.") + len("net 30.")
    initials = "PL"
    initials_utf16 = initials.encode("utf-16le").ljust(18, b"\x00")
    atrd_pre10 = struct.pack("<H", len(initials)) + initials_utf16 + struct.pack("<HHHi", 0, 0, 0, 0)
    assert len(atrd_pre10) == 30
    plcfand_ref_bytes = struct.pack("<II", anchor_cp, len(body_text)) + atrd_pre10

    # 5. PlcfbkfAtn & PlcfbklAtn bookmarking "net 30"
    bkmk_start = body_text.index("net 30")
    bkmk_end = bkmk_start + len("net 30")
    plcfbkf_atn_bytes = struct.pack("<II", bkmk_start, bkmk_end) + struct.pack("<HH", 0, 0)
    plcfbkl_atn_bytes = struct.pack("<II", bkmk_end, bkmk_end + 1)

    table_stream = bytearray()
    fc_clx = len(table_stream)
    table_stream.extend(clx_bytes)
    lcb_clx = len(clx_bytes)

    fc_owners = len(table_stream)
    table_stream.extend(owners_bytes)
    lcb_owners = len(owners_bytes)

    fc_txt = len(table_stream)
    table_stream.extend(plcfand_txt_bytes)
    lcb_txt = len(plcfand_txt_bytes)

    fc_ref = len(table_stream)
    table_stream.extend(plcfand_ref_bytes)
    lcb_ref = len(plcfand_ref_bytes)

    fc_bkf = len(table_stream)
    table_stream.extend(plcfbkf_atn_bytes)
    lcb_bkf = len(plcfbkf_atn_bytes)

    fc_bkl = len(table_stream)
    table_stream.extend(plcfbkl_atn_bytes)
    lcb_bkl = len(plcfbkl_atn_bytes)

    # Build FIB in WordDocument stream
    word_stream = bytearray(text_offset + len(encoded_text))
    word_stream[text_offset:text_offset + len(encoded_text)] = encoded_text

    # FibBase: wIdent = 0xA5EC at 0x00, flags = 0x0200 (1Table) at 0x0A
    struct.pack_into("<H", word_stream, 0x00, 0xA5EC)
    struct.pack_into("<H", word_stream, 0x0A, 0x0200)
    csw = 14
    struct.pack_into("<H", word_stream, 0x20, csw)
    offset_cslw = 0x22 + (csw * 2)
    cslw = 22
    struct.pack_into("<H", word_stream, offset_cslw, cslw)
    offset_rg_lw = offset_cslw + 2

    # ccpText (index 3), ccpFtn (4), ccpHdr (5), ccpMcr (6), ccpAtn (7)
    struct.pack_into(
        "<8I",
        word_stream,
        offset_rg_lw + 12,
        len(body_text),
        0,
        0,
        0,
        len(comment_text),
        0,
        0,
        0,
    )

    offset_cb_fc_lcb = offset_rg_lw + (cslw * 4)
    cb_rg_fc_lcb = 44
    struct.pack_into("<H", word_stream, offset_cb_fc_lcb, cb_rg_fc_lcb)
    offset_fc_lcb = offset_cb_fc_lcb + 2

    def _write_fc_lcb(entry_index, fc_val, lcb_val):
        struct.pack_into("<II", word_stream, offset_fc_lcb + (entry_index * 8), fc_val, lcb_val)

    _write_fc_lcb(4, fc_ref, lcb_ref)
    _write_fc_lcb(5, fc_txt, lcb_txt)
    _write_fc_lcb(33, fc_clx, lcb_clx)
    _write_fc_lcb(36, fc_owners, lcb_owners)
    _write_fc_lcb(42, fc_bkf, lcb_bkf)
    _write_fc_lcb(43, fc_bkl, lcb_bkl)

    return bytes(word_stream), bytes(table_stream)


def test_docx_comment_extraction_with_anchors_and_replies():
    """Verify OOXML .docx comments extract author, date, anchor text, replies, and resolved state."""
    print("Testing OOXML .docx comment extraction...")
    docx_path = _build_sample_docx_with_comments()
    try:
        comments, total_words = extract_docx_comments(docx_path)
    finally:
        os.remove(docx_path)

    assert len(comments) == 2, f"Expected 2 top-level comment threads, got {len(comments)}"
    assert total_words > 1000, f"Expected >1000 body words, got {total_words}"

    first = comments[0]
    assert first["id"] == "0"
    assert first["author"] == "Alice Reviewer"
    assert first["initials"] == "AR"
    assert first["date"] == "2025-02-10T14:00:00Z"
    assert first["anchor_text"] == "30 calendar days"
    assert first["text"] == "Please change payment terms to 60 days."
    assert first["done"] is False
    assert first["position_known"] is True
    assert first["word_offset"] == 105
    assert len(first["replies"]) == 1
    assert first["replies"][0]["author"] == "Bob Author"
    assert first["replies"][0]["initials"] == "BA"
    assert first["replies"][0]["text"] == "Agreed, updating to 60 days in next draft."

    second = comments[1]
    assert second["id"] == "2"
    assert second["author"] == "Carol Legal"
    assert second["anchor_text"] == "the State of Washington"
    assert second["done"] is True
    assert second["position_known"] is True
    assert second["word_offset"] > 900

    formatted = format_word_comment_block(first, index=1, total=2)
    assert '### Document comment 1 of 2 by Alice Reviewer (AR) [2025-02-10T14:00:00Z] on "30 calendar days"' in formatted
    assert "- Reply by Bob Author (BA) [2025-02-10T15:30:00Z]: Agreed, updating to 60 days in next draft." in formatted

    second_formatted = format_word_comment_block(second, index=2, total=2)
    assert "(Resolved)" in second_formatted

    print("OOXML .docx comment extraction test passed!")
    return True


def test_docx_comments_merge_into_target_chunks():
    """Verify extracted Word comments merge into the chunk containing their anchored text."""
    print("Testing Word comment chunk placement...")
    namespace = _load_document_functions([
        "_build_word_comment_chunks",
        "_resolve_embedded_image_chunk_index",
        "_merge_embedded_images_into_chunks",
        "_append_overflow_image_chunks",
    ])
    build_comment_chunks = namespace["_build_word_comment_chunks"]
    merge_chunks = namespace["_merge_embedded_images_into_chunks"]
    append_overflow = namespace["_append_overflow_image_chunks"]

    docx_path = _build_sample_docx_with_comments()
    try:
        comment_blocks, comment_count, total_words = build_comment_chunks(docx_path, ".docx")
    finally:
        os.remove(docx_path)

    assert comment_count == 2, f"Expected 2 comment blocks, got {comment_count}"

    chunks = [
        {"page_number": 1, "content": "Early contract section covering payment terms."},
        {"page_number": 2, "content": "Middle contract section covering deliverables."},
        {"page_number": 3, "content": "Late contract section covering governing law."},
    ]

    merged, merged_count, overflow = merge_chunks(chunks, comment_blocks, total_words, {})
    merged = append_overflow(merged, overflow)

    assert merged_count == 2, f"Expected both comments to merge into chunks, got {merged_count}"
    assert not overflow, f"Expected no overflow comment blocks, got {len(overflow)}"
    assert len(merged) == 3, f"Expected 3 chunks after merging comments, got {len(merged)}"
    assert "Alice Reviewer" in merged[0]["content"], "First comment thread should land in chunk 1"
    assert "Bob Author" in merged[0]["content"], "Reply should stay with first comment thread in chunk 1"
    assert "Document comment" not in merged[1]["content"], "Middle chunk should not receive comments"
    assert "Carol Legal" in merged[2]["content"], "Second comment should land in chunk 3"

    print("Word comment chunk placement test passed!")
    return True


def test_extract_docx_text_includes_and_strips_comments():
    """Verify extract_docx_text appends the comments section and strip_appended_word_comments removes it cleanly."""
    print("Testing extract_docx_text comment inclusion...")
    docx_path = _build_sample_docx_with_comments(total_paragraphs=10, words_per_paragraph=5)
    try:
        full_text = FUNCTIONS_CONTENT.extract_docx_text(docx_path)
        body_only = FUNCTIONS_CONTENT.extract_docx_text(docx_path, include_comments=False)
    finally:
        os.remove(docx_path)

    assert "### Document Comments" in full_text
    assert "Alice Reviewer" in full_text
    assert "30 calendar days" in full_text
    assert "### Document Comments" not in body_only

    stripped = strip_appended_word_comments(full_text)
    assert stripped == body_only.rstrip()

    print("extract_docx_text comment inclusion test passed!")
    return True


def test_legacy_doc_fib_comment_extraction():
    """Verify legacy Word 97-2003 .doc FIB and table streams extract structured comments cleanly."""
    print("Testing legacy .doc FIB comment extraction...")
    word_stream, table_stream = _build_legacy_doc_streams_with_comment()

    fib = FUNCTIONS_CONTENT._parse_legacy_doc_fib(word_stream)
    assert fib is not None, "Expected valid FIB dictionary"
    assert fib["ccp_atn"] > 0, "Expected non-zero annotation subdocument length"
    assert fib["table_stream_name"] == "1Table"

    raw_full_text = FUNCTIONS_CONTENT._extract_legacy_doc_raw_text_from_table_stream(
        word_stream,
        table_stream,
        fc_clx=fib["fc_clx"],
        lcb_clx=fib["lcb_clx"],
    )
    comments, total_body_words = FUNCTIONS_CONTENT._extract_legacy_doc_comments_from_streams(
        table_stream,
        fib,
        raw_full_text,
    )

    assert len(comments) == 1, f"Expected 1 legacy .doc comment, got {len(comments)}"
    assert total_body_words == 12, f"Expected 12 body words, got {total_body_words}"

    comment = comments[0]
    assert comment["author"] == "Paul Lizer"
    assert comment["initials"] == "PL"
    assert comment["anchor_text"] == "net 30"
    assert "net 45 for enterprise customers" in comment["text"]
    assert comment["position_known"] is True
    assert comment["word_offset"] == 12

    section = format_word_comments_section(comments)
    assert '### Document comment 1 of 1 by Paul Lizer (PL) on "net 30"' in section
    assert "Please verify if net 30 should be net 45 for enterprise customers." in section

    assert_app_version_at_least("0.261.390")
    print("Legacy .doc FIB comment extraction test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_docx_comment_extraction_with_anchors_and_replies,
        test_docx_comments_merge_into_target_chunks,
        test_extract_docx_text_includes_and_strips_comments,
        test_legacy_doc_fib_comment_extraction,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
