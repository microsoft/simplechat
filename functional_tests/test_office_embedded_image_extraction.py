#!/usr/bin/env python3
# test_office_embedded_image_extraction.py
"""
Functional test for embedded image extraction from Office files.
Version: 0.250.218
Implemented in: 0.250.218

This test ensures that images embedded in DOCX and PPTX packages are pulled out for analysis,
that decorative assets are filtered, that duplicate images are analyzed only once, and that PPTX
images are attributed to the slide that references them.
"""

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

from functions_office_media import extract_office_embedded_images  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def build_png_bytes(width, height, color):
    """Build PNG bytes large enough to clear the minimum-size filter."""
    buffer = BytesIO()
    image = Image.new("RGB", (width, height), color)
    # Noise keeps the encoder from compressing the image below the byte-size floor.
    for x in range(0, width, 3):
        for y in range(0, height, 3):
            image.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, ((x + y) * 13) % 256))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_docx_package(path, media_entries):
    """Write a minimal DOCX-shaped OOXML package containing the given word/media entries."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        for media_name, media_bytes in media_entries.items():
            archive.writestr(f"word/media/{media_name}", media_bytes)


def build_pptx_package(path, media_entries, slide_media_map):
    """Write a minimal PPTX-shaped OOXML package with slide relationship files."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for media_name, media_bytes in media_entries.items():
            archive.writestr(f"ppt/media/{media_name}", media_bytes)
        for slide_number, media_name in slide_media_map.items():
            rels_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId2" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                f'Target="../media/{media_name}"/>'
                '</Relationships>'
            )
            archive.writestr(f"ppt/slides/_rels/slide{slide_number}.xml.rels", rels_xml)


def test_docx_images_are_extracted_and_filtered():
    """Large embedded images are extracted while icons and duplicates are skipped."""
    print("Testing DOCX embedded image extraction and filtering...")

    large_image = build_png_bytes(400, 300, (10, 120, 200))
    another_image = build_png_bytes(500, 380, (200, 60, 30))
    tiny_icon = build_png_bytes(24, 24, (0, 0, 0))

    with tempfile.TemporaryDirectory() as work_dir:
        docx_path = os.path.join(work_dir, "sample.docx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        build_docx_package(
            docx_path,
            {
                "image1.png": large_image,
                "image2.png": tiny_icon,
                "image3.png": another_image,
                # Byte-identical duplicate of image1, e.g. a header logo repeated in the document.
                "image4.png": large_image,
                # Vector formats are not accepted by either analysis engine.
                "image5.emf": b"\x01\x00\x00\x00" * 1024,
            },
        )

        extracted = extract_office_embedded_images(docx_path, output_dir, min_pixels=150, max_images=25)

    names = [item["name"] for item in extracted]
    if names != ["image1.png", "image3.png"]:
        raise AssertionError(f"Unexpected extracted images: {names}")

    if extracted[0]["width"] != 400 or extracted[0]["height"] != 300:
        raise AssertionError(f"Image dimensions were not reported correctly: {extracted[0]}")

    print("DOCX extraction and filtering test passed!")
    return True


def test_extraction_respects_max_images_cap():
    """The per-document cap limits how many embedded images are analyzed."""
    print("Testing embedded image per-document cap...")

    with tempfile.TemporaryDirectory() as work_dir:
        docx_path = os.path.join(work_dir, "many.docx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        media_entries = {
            f"image{index}.png": build_png_bytes(300, 300, (index * 20 % 256, 90, 140))
            for index in range(1, 8)
        }
        build_docx_package(docx_path, media_entries)

        capped = extract_office_embedded_images(docx_path, output_dir, min_pixels=150, max_images=3)
        disabled = extract_office_embedded_images(docx_path, output_dir, min_pixels=150, max_images=0)

    if len(capped) != 3:
        raise AssertionError(f"Expected the cap to limit extraction to 3 images, got {len(capped)}")
    if disabled:
        raise AssertionError(f"A cap of 0 should extract nothing, got {len(disabled)}")

    print("Per-document cap test passed!")
    return True


def test_pptx_images_map_to_their_slide():
    """PPTX images are attributed to the slide that references them."""
    print("Testing PPTX slide attribution...")

    first_image = build_png_bytes(320, 240, (12, 180, 90))
    second_image = build_png_bytes(360, 260, (180, 30, 120))

    with tempfile.TemporaryDirectory() as work_dir:
        pptx_path = os.path.join(work_dir, "deck.pptx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        build_pptx_package(
            pptx_path,
            {"image1.png": first_image, "image2.png": second_image},
            {1: "image1.png", 4: "image2.png"},
        )

        extracted = extract_office_embedded_images(pptx_path, output_dir, min_pixels=150, max_images=25)

    slide_numbers = {item["name"]: item["slide_number"] for item in extracted}
    if slide_numbers.get("image1.png") != 1:
        raise AssertionError(f"image1.png should map to slide 1: {slide_numbers}")
    if slide_numbers.get("image2.png") != 4:
        raise AssertionError(f"image2.png should map to slide 4: {slide_numbers}")

    print("PPTX slide attribution test passed!")
    return True


def test_natural_sort_order_is_used():
    """Embedded media is ordered naturally so image2 precedes image10."""
    print("Testing embedded image ordering...")

    with tempfile.TemporaryDirectory() as work_dir:
        docx_path = os.path.join(work_dir, "ordered.docx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        media_entries = {
            f"image{index}.png": build_png_bytes(260, 260, (index * 17 % 256, 40, 200))
            for index in (1, 2, 10, 11)
        }
        build_docx_package(docx_path, media_entries)

        extracted = extract_office_embedded_images(docx_path, output_dir, min_pixels=150, max_images=25)

    names = [item["name"] for item in extracted]
    if names != ["image1.png", "image2.png", "image10.png", "image11.png"]:
        raise AssertionError(f"Embedded images were not ordered naturally: {names}")

    print("Ordering test passed!")
    return True


def test_non_ooxml_files_return_empty():
    """Legacy and corrupt files degrade to an empty result instead of raising."""
    print("Testing non-OOXML handling...")

    with tempfile.TemporaryDirectory() as work_dir:
        legacy_path = os.path.join(work_dir, "legacy.doc")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)
        with open(legacy_path, "wb") as legacy_file:
            legacy_file.write(b"\xd0\xcf\x11\xe0not a zip archive")

        if extract_office_embedded_images(legacy_path, output_dir):
            raise AssertionError("Legacy OLE files should yield no embedded images.")

        missing_path = os.path.join(work_dir, "does_not_exist.docx")
        if extract_office_embedded_images(missing_path, output_dir):
            raise AssertionError("Missing files should yield no embedded images.")

    print("Non-OOXML handling test passed!")
    return True


def test_pipeline_wires_embedded_image_analysis():
    """The ingestion pipeline must analyze embedded images with the active engine."""
    print("Testing embedded image pipeline wiring...")

    documents = (APP_ROOT / "functions_documents.py").read_text(encoding="utf-8")
    settings = (APP_ROOT / "functions_settings.py").read_text(encoding="utf-8")

    expectations = [
        (documents, "def _build_office_embedded_image_chunks", "embedded image chunk builder"),
        (documents, "def _analyze_single_embedded_image", "per-image analysis helper"),
        (documents, "analyze_image_with_content_understanding", "Content Understanding image analysis"),
        (documents, "extract_content_with_azure_di(image_path", "Document Intelligence image analysis"),
        (documents, "office_embedded_image_count", "embedded image count recorded on the document"),
        (settings, "def normalize_office_embedded_image_min_pixels", "minimum pixel normalizer"),
        (settings, "def normalize_office_embedded_image_max_per_document", "per-document cap normalizer"),
    ]

    for content, expected_text, description in expectations:
        if expected_text not in content:
            raise AssertionError(f"Missing {description}: {expected_text}")

    print("Pipeline wiring test passed!")
    return True


def test_crafted_entry_names_cannot_escape_output_directory():
    """Zip entry names are untrusted, so extraction must never write outside the output directory."""
    print("Testing zip path traversal defenses...")

    payload = build_png_bytes(300, 300, (70, 140, 210))

    with tempfile.TemporaryDirectory() as work_dir:
        docx_path = os.path.join(work_dir, "crafted.docx")
        output_dir = os.path.join(work_dir, "nested", "out")
        os.makedirs(output_dir)
        sentinel_dir = os.path.join(work_dir, "nested")

        # Both separator styles, because zip entry names are not normalized by the format.
        with zipfile.ZipFile(docx_path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/media/..\\..\\..\\escaped_backslash.png", payload)
            archive.writestr("word/media/../../../escaped_forward.png", payload)
            archive.writestr("word/media/legit.png", payload)

        extracted = extract_office_embedded_images(docx_path, output_dir, min_pixels=150, max_images=25)

        for item in extracted:
            resolved = os.path.realpath(item["path"])
            if not resolved.startswith(os.path.realpath(output_dir) + os.sep):
                raise AssertionError(f"Extraction escaped the output directory: {resolved}")

        escaped = [
            name for name in os.listdir(sentinel_dir)
            if name.lower().startswith("escaped")
        ]
        if escaped:
            raise AssertionError(f"Files were written outside the output directory: {escaped}")

        stray = [
            name for name in os.listdir(work_dir)
            if name.lower().startswith("escaped")
        ]
        if stray:
            raise AssertionError(f"Files were written outside the output directory: {stray}")

    print("Zip path traversal test passed!")
    return True


def test_oversized_entries_are_skipped_without_decompressing():
    """An entry declaring an enormous decompressed size must be skipped."""
    print("Testing decompression bomb guard...")

    import functions_office_media

    with tempfile.TemporaryDirectory() as work_dir:
        docx_path = os.path.join(work_dir, "bomb.docx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        # Highly compressible payload that expands well past the per-image ceiling.
        bomb_payload = b"\x00" * (functions_office_media.OFFICE_EMBEDDED_IMAGE_MAX_BYTES + 1024)
        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/media/bomb.png", bomb_payload)
            archive.writestr("word/media/normal.png", build_png_bytes(300, 300, (20, 200, 160)))

        extracted = extract_office_embedded_images(docx_path, output_dir, min_pixels=150, max_images=25)

    names = [item["name"] for item in extracted]
    if "bomb.png" in names:
        raise AssertionError("An oversized embedded image should have been skipped.")
    if names != ["normal.png"]:
        raise AssertionError(f"Expected only the normal image to survive, got {names}")

    print("Decompression bomb guard test passed!")
    return True


def test_billion_laughs_rels_entry_is_rejected():
    """A slide relationship part with expanding entities must not be parsed."""
    print("Testing hardened slide relationship parsing...")

    payload = build_png_bytes(300, 300, (40, 90, 170))
    entity_bomb = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE Relationships ['
        '<!ENTITY a "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
        '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">'
        ']>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" Target="../media/image1.png"/>'
        '<Relationship Id="rId3" Target="&d;"/>'
        '</Relationships>'
    )

    with tempfile.TemporaryDirectory() as work_dir:
        pptx_path = os.path.join(work_dir, "bomb.pptx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        with zipfile.ZipFile(pptx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/media/image1.png", payload)
            archive.writestr("ppt/slides/_rels/slide1.xml.rels", entity_bomb)

        # Must not raise, must not hang, and must still extract the image itself.
        extracted = extract_office_embedded_images(pptx_path, output_dir, min_pixels=150, max_images=25)

    names = [item["name"] for item in extracted]
    if names != ["image1.png"]:
        raise AssertionError(f"Expected the image to still be extracted, got {names}")
    if extracted[0]["slide_number"] is not None:
        raise AssertionError("A rejected relationship part must not produce slide attribution.")

    print("Hardened relationship parsing test passed!")
    return True


def test_oversized_rels_entry_is_skipped():
    """A slide relationship part larger than the cap must be skipped without decompressing."""
    print("Testing slide relationship size cap...")

    import functions_office_media

    payload = build_png_bytes(300, 300, (150, 60, 60))
    oversized_rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" Target="../media/image1.png"/>'
        + '<!--' + 'x' * (functions_office_media.OFFICE_EMBEDDED_RELS_MAX_BYTES + 1024) + '-->'
        + '</Relationships>'
    )

    with tempfile.TemporaryDirectory() as work_dir:
        pptx_path = os.path.join(work_dir, "big_rels.pptx")
        output_dir = os.path.join(work_dir, "out")
        os.makedirs(output_dir)

        with zipfile.ZipFile(pptx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/media/image1.png", payload)
            archive.writestr("ppt/slides/_rels/slide1.xml.rels", oversized_rels)

        extracted = extract_office_embedded_images(pptx_path, output_dir, min_pixels=150, max_images=25)

    if len(extracted) != 1 or extracted[0]["slide_number"] is not None:
        raise AssertionError(
            f"Oversized relationship parts must be skipped without breaking extraction: {extracted}"
        )

    print("Slide relationship size cap test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The app version must be at or beyond the version this feature shipped in."""
    print("Testing application version...")
    assert_app_version_at_least("0.250.218")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_docx_images_are_extracted_and_filtered,
        test_extraction_respects_max_images_cap,
        test_pptx_images_map_to_their_slide,
        test_natural_sort_order_is_used,
        test_non_ooxml_files_return_empty,
        test_crafted_entry_names_cannot_escape_output_directory,
        test_oversized_entries_are_skipped_without_decompressing,
        test_billion_laughs_rels_entry_is_rejected,
        test_oversized_rels_entry_is_skipped,
        test_pipeline_wires_embedded_image_analysis,
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
