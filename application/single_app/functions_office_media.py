# functions_office_media.py

"""Embedded media extraction for OOXML Office files.

Neither Document Intelligence nor Content Understanding describes figures inside Word and
PowerPoint files. Pulling the embedded images out of the OOXML package lets the ingestion pipeline
analyze them individually with whichever engine backs the selected extraction mode.

This module deliberately keeps its imports light so it stays importable without Azure clients.
"""

import hashlib
import os
import re
import zipfile
from io import BytesIO

from defusedxml.ElementTree import ParseError as DefusedParseError
from defusedxml.ElementTree import fromstring as defused_fromstring
from PIL import Image


OFFICE_EMBEDDED_IMAGE_MEDIA_PREFIXES = ('word/media/', 'ppt/media/', 'xl/media/')
# Restricted to raster formats that both Document Intelligence and Content Understanding accept.
OFFICE_EMBEDDED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.heif', '.heic')
OFFICE_EMBEDDED_IMAGE_MIN_BYTES = 2048
# Uploaded Office files are untrusted, so refuse to decompress an oversized embedded image.
OFFICE_EMBEDDED_IMAGE_MAX_BYTES = 64 * 1024 * 1024
# Slide relationship parts are small XML documents; anything larger is not worth decompressing.
OFFICE_EMBEDDED_RELS_MAX_BYTES = 4 * 1024 * 1024

_OFFICE_MEDIA_INDEX_PATTERN = re.compile(r'(\d+)')
_PPTX_SLIDE_RELS_PATTERN = re.compile(r'^ppt/slides/_rels/slide(\d+)\.xml\.rels$', re.IGNORECASE)


def _safe_media_base_name(media_name):
    """Return a plain file name for a zip entry, defeating path traversal in crafted archives.

    Zip entries are untrusted input and may embed ``..`` or platform separators, so both separator
    styles are collapsed before taking the final component.
    """
    normalized_name = str(media_name or '').replace('\\', '/')
    base_name = normalized_name.rsplit('/', 1)[-1]
    base_name = os.path.basename(base_name)
    if base_name in ('', '.', '..'):
        return ''
    return base_name


def _office_media_sort_key(media_name):
    """Sort embedded media names naturally so image2 precedes image10."""
    base_name = media_name.rsplit('/', 1)[-1]
    match = _OFFICE_MEDIA_INDEX_PATTERN.search(base_name)
    return (int(match.group(1)) if match else 0, base_name)


def _build_pptx_media_slide_map(archive):
    """Map ``ppt/media/*`` entries to the slide numbers that reference them.

    Slide relationship parts come from an untrusted upload, so they get the same declared-size
    guard as media entries and are parsed with a hardened XML parser.
    """
    media_slide_map = {}

    for entry_name in archive.namelist():
        slide_match = _PPTX_SLIDE_RELS_PATTERN.match(entry_name)
        if not slide_match:
            continue

        slide_number = int(slide_match.group(1))
        try:
            entry_info = archive.getinfo(entry_name)
        except KeyError:
            continue

        # Check the declared size before decompressing so a zip bomb cannot exhaust memory.
        if entry_info.file_size > OFFICE_EMBEDDED_RELS_MAX_BYTES:
            continue

        try:
            rels_root = defused_fromstring(archive.read(entry_name))
        except (KeyError, DefusedParseError, ValueError, zipfile.BadZipFile):
            continue

        for relationship in rels_root:
            target = str(relationship.attrib.get('Target') or '').replace('\\', '/')
            if '/media/' not in target:
                continue
            media_name = 'ppt/media/' + target.rsplit('/media/', 1)[-1]
            # Keep the first slide that references the image so ordering stays stable.
            media_slide_map.setdefault(media_name, slide_number)

    return media_slide_map


def extract_office_embedded_images(file_path, output_dir, min_pixels=150, max_images=25):
    """Extract analyzable raster images embedded in an OOXML Office file.

    Args:
        file_path (str): Path to the DOCX/PPTX/XLSX file.
        output_dir (str): Directory that extracted images are written to.
        min_pixels (int): Minimum width and height required for an image to be analyzed.
        max_images (int): Maximum number of images to extract.

    Returns:
        list: Dicts with ``name``, ``path``, ``width``, ``height``, and ``slide_number`` keys.
    """
    if max_images <= 0:
        return []

    extracted_images = []
    seen_digests = set()

    try:
        with zipfile.ZipFile(file_path) as archive:
            media_slide_map = _build_pptx_media_slide_map(archive)

            candidate_names = [
                entry_name for entry_name in archive.namelist()
                if entry_name.lower().startswith(OFFICE_EMBEDDED_IMAGE_MEDIA_PREFIXES)
                and entry_name.lower().endswith(OFFICE_EMBEDDED_IMAGE_EXTENSIONS)
            ]

            for media_name in sorted(candidate_names, key=_office_media_sort_key):
                if len(extracted_images) >= max_images:
                    break

                base_name = _safe_media_base_name(media_name)
                if not base_name:
                    continue

                try:
                    entry_info = archive.getinfo(media_name)
                except KeyError:
                    continue

                # Check the declared size before decompressing so a zip bomb cannot exhaust memory.
                if entry_info.file_size > OFFICE_EMBEDDED_IMAGE_MAX_BYTES:
                    continue
                if entry_info.file_size < OFFICE_EMBEDDED_IMAGE_MIN_BYTES:
                    continue

                try:
                    image_bytes = archive.read(media_name)
                except (KeyError, zipfile.BadZipFile):
                    continue

                # Small assets are almost always icons, bullets, or spacer graphics.
                if len(image_bytes) < OFFICE_EMBEDDED_IMAGE_MIN_BYTES:
                    continue

                digest = hashlib.sha256(image_bytes).hexdigest()
                if digest in seen_digests:
                    continue

                try:
                    with Image.open(BytesIO(image_bytes)) as embedded_image:
                        width, height = embedded_image.size
                except Exception:
                    continue

                if width < min_pixels or height < min_pixels:
                    continue

                # The output name is generated rather than taken from the archive, so a crafted
                # entry name can never influence where the file is written.
                extension = os.path.splitext(base_name)[1].lower()
                if extension not in OFFICE_EMBEDDED_IMAGE_EXTENSIONS:
                    continue
                output_path = os.path.join(output_dir, f"{len(extracted_images) + 1:03d}{extension}")

                seen_digests.add(digest)

                try:
                    with open(output_path, 'wb') as output_file:
                        output_file.write(image_bytes)
                except OSError:
                    continue

                extracted_images.append({
                    'name': base_name,
                    'path': output_path,
                    'width': width,
                    'height': height,
                    'slide_number': media_slide_map.get(media_name),
                })
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        return []

    return extracted_images
