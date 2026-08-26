#!/usr/bin/env python3
# test_figure_chunk_association.py
"""
Functional test for keeping figures in the chunk they came from.
Version: 0.250.228
Implemented in: 0.250.228

This test ensures embedded Office images are merged into the chunk containing their surrounding
text instead of being appended as extra chunks past the end of the document, that no two chunks
share a page number (chunk ids are derived from it, so duplicates overwrite each other in the
search index), and that the Content Understanding path keeps attributing figures to their origin
page.
"""

import ast
import logging
import os
import sys
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from PIL import Image  # noqa: E402

from functions_office_media import build_docx_image_word_offsets  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


WORDPROCESSING_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def load_document_functions(function_names):
    """Exec selected pure functions from functions_documents.py in an isolated namespace.

    functions_documents imports the full Azure config at module load, so the placement and merge
    helpers are extracted and run against the real repository source instead.
    """
    source = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    namespace = {
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
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
        raise AssertionError(f"Could not locate functions in source: {sorted(missing)}")
    return namespace


def build_png_bytes(width, height, color):
    """Build PNG bytes large enough to clear the minimum-size filter."""
    buffer = BytesIO()
    image = Image.new("RGB", (width, height), color)
    for x in range(0, width, 3):
        for y in range(0, height, 3):
            image.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, ((x + y) * 13) % 256))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_docx_with_images_at(paragraph_indexes, total_paragraphs=60, words_per_paragraph=20):
    """Build a DOCX whose images sit at known paragraph positions. Returns (path, planted_offsets)."""
    body_parts = []
    planted_offsets = {}

    for paragraph_index in range(total_paragraphs):
        for image_number, target_index in enumerate(paragraph_indexes, start=1):
            if paragraph_index == target_index:
                relationship_id = f"rId{100 + image_number}"
                body_parts.append(
                    f'<w:p><w:r><w:drawing>'
                    f'<a:graphic><a:graphicData>'
                    f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                    f'<pic:blipFill><a:blip r:embed="{relationship_id}"/></pic:blipFill>'
                    f'</pic:pic></a:graphicData></a:graphic>'
                    f'</w:drawing></w:r></w:p>'
                )
                planted_offsets[f"image{image_number}.png"] = paragraph_index * words_per_paragraph

        words = " ".join(f"w{paragraph_index}x{word_index}" for word_index in range(words_per_paragraph))
        body_parts.append(f'<w:p><w:r><w:t>{words}</w:t></w:r></w:p>')

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORDPROCESSING_NS}" xmlns:r="{RELATIONSHIP_NS}" xmlns:a="{DRAWING_NS}">'
        '<w:body>' + "".join(body_parts) + '</w:body></w:document>'
    )

    relationship_entries = "".join(
        f'<Relationship Id="rId{100 + number}" Target="media/image{number}.png"/>'
        for number in range(1, len(paragraph_indexes) + 1)
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + relationship_entries +
        '</Relationships>'
    )

    handle = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    handle.close()
    with zipfile.ZipFile(handle.name, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", rels_xml)
        for number in range(1, len(paragraph_indexes) + 1):
            archive.writestr(f"word/media/image{number}.png", build_png_bytes(400, 300, (40 * number % 256, 90, 160)))

    return handle.name, planted_offsets


def test_docx_image_positions_are_detected():
    """Word images must resolve to the word offset where they appear in reading order."""
    print("Testing DOCX image position detection...")

    docx_path, planted = build_docx_with_images_at([6, 30, 54])
    try:
        with zipfile.ZipFile(docx_path) as archive:
            offsets, total_words = build_docx_image_word_offsets(archive)
    finally:
        os.remove(docx_path)

    if total_words != 1200:
        raise AssertionError(f"Expected 1200 body words, got {total_words}")

    for name, expected_offset in planted.items():
        actual = offsets.get(f"word/media/{name}")
        if actual != expected_offset:
            raise AssertionError(f"{name}: expected offset {expected_offset}, got {actual}")

    print("DOCX position detection test passed!")
    return True


def test_docx_images_merge_into_their_origin_chunk():
    """An image in the middle of a document must land in the middle chunk, not past the end."""
    print("Testing DOCX image chunk placement...")

    namespace = load_document_functions([
        "_resolve_embedded_image_chunk_index",
        "_merge_embedded_images_into_chunks",
        "_append_overflow_image_chunks",
    ])
    merge = namespace["_merge_embedded_images_into_chunks"]
    append_overflow = namespace["_append_overflow_image_chunks"]

    docx_path, _planted = build_docx_with_images_at([6, 30, 54])
    try:
        with zipfile.ZipFile(docx_path) as archive:
            offsets, total_words = build_docx_image_word_offsets(archive)
    finally:
        os.remove(docx_path)

    chunk_count = 3
    chunks = [{"page_number": index + 1, "content": f"body text {index + 1}"} for index in range(chunk_count)]

    image_blocks = [
        {
            "content": f"### Embedded image: image{number}.png\n\nA described figure.",
            "word_offset": offsets[f"word/media/image{number}.png"],
            "slide_number": None,
            "position_known": True,
        }
        for number in (1, 2, 3)
    ]

    merged, merged_count, overflow = merge(chunks, image_blocks, total_words, {})
    merged = append_overflow(merged, overflow)

    if merged_count != 3:
        raise AssertionError(f"Expected 3 merged images, got {merged_count}")
    if overflow:
        raise AssertionError(f"No image should have overflowed, got {len(overflow)}")

    # The core regression: no chunk beyond the document's real chunk count.
    if len(merged) != chunk_count:
        raise AssertionError(f"Expected {chunk_count} chunks after merge, got {len(merged)}")
    if max(chunk["page_number"] for chunk in merged) != chunk_count:
        raise AssertionError("Merging must not create page numbers past the end of the document.")

    # Each image belongs with the text it appeared next to.
    for index, number in enumerate((1, 2, 3)):
        if f"image{number}.png" not in merged[index]["content"]:
            raise AssertionError(
                f"image{number}.png should be in chunk {index + 1}: {merged[index]['content'][:120]!r}"
            )
        if not merged[index]["content"].startswith("body text"):
            raise AssertionError("Original chunk text must be preserved ahead of the image content.")

    print("DOCX chunk placement test passed!")
    return True


def test_pptx_images_map_to_their_slide_chunk():
    """PowerPoint images follow their slide, including when several slides share a chunk."""
    print("Testing PPTX slide chunk placement...")

    namespace = load_document_functions(["_resolve_embedded_image_chunk_index"])
    resolve = namespace["_resolve_embedded_image_chunk_index"]

    # One slide per chunk, the default.
    per_slide_chunks = [{"page_number": number, "content": f"slide {number}"} for number in range(1, 6)]
    index = resolve({"slide_number": 3, "word_offset": None}, per_slide_chunks, 0)
    if per_slide_chunks[index]["page_number"] != 3:
        raise AssertionError(f"Slide 3 should map to chunk 3, got {per_slide_chunks[index]['page_number']}")

    # Grouped slides: chunks start at slides 1, 3 and 5.
    grouped_chunks = [{"page_number": number, "content": f"slides {number}+"} for number in (1, 3, 5)]
    for slide_number, expected_page in ((1, 1), (2, 1), (3, 3), (4, 3), (5, 5), (6, 5)):
        index = resolve({"slide_number": slide_number, "word_offset": None}, grouped_chunks, 0)
        actual_page = grouped_chunks[index]["page_number"]
        if actual_page != expected_page:
            raise AssertionError(
                f"Slide {slide_number} should map to chunk {expected_page}, got {actual_page}"
            )

    print("PPTX slide placement test passed!")
    return True


def test_positionless_images_anchor_to_the_last_chunk():
    """Legacy binary Office files carry no position, so images must not invent a trailing page."""
    print("Testing positionless image fallback...")

    namespace = load_document_functions([
        "_resolve_embedded_image_chunk_index",
        "_merge_embedded_images_into_chunks",
        "_append_overflow_image_chunks",
    ])
    merge = namespace["_merge_embedded_images_into_chunks"]
    append_overflow = namespace["_append_overflow_image_chunks"]

    chunks = [{"page_number": number, "content": f"body {number}"} for number in (1, 2, 3)]
    image_blocks = [{
        "content": "### Embedded image: carved.emf\n\nA described figure.",
        "word_offset": None,
        "slide_number": None,
        "position_known": False,
    }]

    merged, merged_count, overflow = merge(chunks, image_blocks, 0, {})
    merged = append_overflow(merged, overflow)

    if merged_count != 1:
        raise AssertionError(f"Expected the image to merge, got {merged_count}")
    if len(merged) != 3:
        raise AssertionError(f"Expected no new chunk, got {len(merged)} chunks")
    if "carved.emf" not in merged[-1]["content"]:
        raise AssertionError("A positionless image should anchor to the final chunk.")

    print("Positionless fallback test passed!")
    return True


def test_oversized_image_content_spills_instead_of_bloating_a_chunk():
    """Merging must respect a size budget so a chunk cannot grow unbounded."""
    print("Testing chunk size budget...")

    namespace = load_document_functions([
        "_resolve_embedded_image_chunk_index",
        "_merge_embedded_images_into_chunks",
        "_append_overflow_image_chunks",
    ])
    merge = namespace["_merge_embedded_images_into_chunks"]
    append_overflow = namespace["_append_overflow_image_chunks"]

    chunks = [{"page_number": 1, "content": "body text"}]
    huge_content = "x" * 200000
    image_blocks = [{
        "content": huge_content,
        "word_offset": 0,
        "slide_number": None,
        "position_known": True,
    }]

    merged, merged_count, overflow = merge(chunks, image_blocks, 100, {})
    merged = append_overflow(merged, overflow)

    if merged_count != 0:
        raise AssertionError("Oversized image content must not be merged into the chunk.")
    if len(overflow) != 1:
        raise AssertionError(f"Oversized content should overflow, got {len(overflow)}")
    if len(merged) != 2 or merged[-1]["page_number"] != 2:
        raise AssertionError(f"Overflow should append exactly one trailing chunk: {merged}")
    if merged[0]["content"] != "body text":
        raise AssertionError("The origin chunk must be left untouched when content does not fit.")

    print("Chunk size budget test passed!")
    return True


def test_merged_chunks_never_share_a_page_number():
    """Chunk ids derive from page numbers, so duplicates would overwrite each other in the index."""
    print("Testing chunk page number uniqueness...")

    namespace = load_document_functions([
        "_resolve_embedded_image_chunk_index",
        "_merge_embedded_images_into_chunks",
        "_append_overflow_image_chunks",
        "_assert_unique_chunk_page_numbers",
    ])
    merge = namespace["_merge_embedded_images_into_chunks"]
    append_overflow = namespace["_append_overflow_image_chunks"]
    assert_unique = namespace["_assert_unique_chunk_page_numbers"]

    chunks = [{"page_number": number, "content": f"body {number}"} for number in range(1, 5)]
    image_blocks = [
        {
            "content": f"### Embedded image {number}\n\nDescription.",
            "word_offset": number * 100,
            "slide_number": None,
            "position_known": True,
        }
        for number in range(1, 8)
    ]

    merged, _merged_count, overflow = merge(chunks, image_blocks, 800, {})
    merged = append_overflow(merged, overflow)

    page_numbers = [chunk["page_number"] for chunk in merged]
    if len(page_numbers) != len(set(page_numbers)):
        raise AssertionError(f"Duplicate chunk page numbers would collide in the index: {page_numbers}")
    if not assert_unique(merged, "doc-1"):
        raise AssertionError("Uniqueness assertion reported duplicates.")

    print("Chunk uniqueness test passed!")
    return True


def test_content_understanding_figures_stay_on_their_page():
    """The PDF path already associates figures by span; keep that behavior locked down."""
    print("Testing Content Understanding page association...")

    from test_content_understanding_extraction_engine import load_content_understanding_module

    content_understanding, _ = load_content_understanding_module()

    page_one = "# Intro\n\nOpening text.\n\n"
    page_two = "## Architecture\n\nThe diagram shows the flow.\n\n"
    page_three = "## Appendix\n\nClosing notes.\n"
    markdown = page_one + page_two + page_three

    result = {
        "contents": [
            {
                "kind": "document",
                "markdown": markdown,
                "startPageNumber": 1,
                "pages": [
                    {"pageNumber": 1, "spans": [{"offset": 0, "length": len(page_one)}]},
                    {"pageNumber": 2, "spans": [{"offset": len(page_one), "length": len(page_two)}]},
                    {
                        "pageNumber": 3,
                        "spans": [{"offset": len(page_one) + len(page_two), "length": len(page_three)}],
                    },
                ],
                "figures": [
                    {
                        "id": "fig-1",
                        "kind": "chart",
                        "description": "A bar chart of quarterly revenue by region.",
                        "span": {"offset": len(page_one) + 10, "length": 8},
                    }
                ],
            }
        ]
    }

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    page_numbers = [page["page_number"] for page in pages]
    if page_numbers != [1, 2, 3]:
        raise AssertionError(f"Content Understanding must not add pages: {page_numbers}")

    carrying = [page["page_number"] for page in pages if "bar chart of quarterly revenue" in page["content"]]
    if carrying != [2]:
        raise AssertionError(f"Figure should stay on page 2, found on {carrying}")

    print("Content Understanding association test passed!")
    return True


def test_pipeline_merges_instead_of_appending():
    """The ingestion pipeline must no longer append embedded images past the document."""
    print("Testing pipeline merge wiring...")

    documents = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")

    for removed_marker in ("starting_page_number", "next_chunk_page_number"):
        if removed_marker in documents:
            raise AssertionError(f"Append-at-end logic still present: {removed_marker}")

    for required_marker in (
        "def _resolve_embedded_image_chunk_index",
        "def _merge_embedded_images_into_chunks",
        "def _append_overflow_image_chunks",
        "def _assert_unique_chunk_page_numbers",
        "_merge_embedded_images_into_chunks(",
        "office_embedded_image_merged",
    ):
        if required_marker not in documents:
            raise AssertionError(f"Missing merge wiring: {required_marker}")

    print("Pipeline merge wiring test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The app version must be at or beyond the version this fix shipped in."""
    print("Testing application version...")
    assert_app_version_at_least("0.250.228")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_docx_image_positions_are_detected,
        test_docx_images_merge_into_their_origin_chunk,
        test_pptx_images_map_to_their_slide_chunk,
        test_positionless_images_anchor_to_the_last_chunk,
        test_oversized_image_content_spills_instead_of_bloating_a_chunk,
        test_merged_chunks_never_share_a_page_number,
        test_content_understanding_figures_stay_on_their_page,
        test_pipeline_merges_instead_of_appending,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
