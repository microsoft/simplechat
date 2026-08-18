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
import struct
import zipfile
from io import BytesIO

from defusedxml.ElementTree import ParseError as DefusedParseError
from defusedxml.ElementTree import fromstring as defused_fromstring
from PIL import Image

from functions_emf_render import render_metafile_to_png


OFFICE_EMBEDDED_IMAGE_MEDIA_PREFIXES = ('word/media/', 'ppt/media/', 'xl/media/')
# Raster formats that both Document Intelligence and Content Understanding accept directly.
OFFICE_EMBEDDED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.heif', '.heic')
# Vector metafiles. Word stores pasted diagrams, SmartArt, and charts this way, so they are the most
# interesting figures in many documents. Neither analysis engine accepts them, so they are
# rasterized to PNG first when the platform can render them.
OFFICE_EMBEDDED_IMAGE_VECTOR_EXTENSIONS = ('.emf', '.wmf')
OFFICE_EMBEDDED_IMAGE_ALL_EXTENSIONS = (
    OFFICE_EMBEDDED_IMAGE_EXTENSIONS + OFFICE_EMBEDDED_IMAGE_VECTOR_EXTENSIONS
)
OFFICE_EMBEDDED_IMAGE_MIN_BYTES = 2048
# Rasterized metafiles are capped on the long edge to keep analysis payloads reasonable.
OFFICE_EMBEDDED_IMAGE_RENDER_MAX_PIXELS = 1600
# Uploaded Office files are untrusted, so refuse to decompress an oversized embedded image.
OFFICE_EMBEDDED_IMAGE_MAX_BYTES = 64 * 1024 * 1024
# Slide relationship parts are small XML documents; anything larger is not worth decompressing.
OFFICE_EMBEDDED_RELS_MAX_BYTES = 4 * 1024 * 1024
# A zip header can understate the uncompressed size, so entries are streamed in bounded chunks.
OFFICE_ZIP_READ_CHUNK_BYTES = 256 * 1024
# Caps on how much of a crafted archive is inspected at all.
OFFICE_ZIP_MAX_ENTRIES = 5000
OFFICE_ZIP_MAX_RELS_ENTRIES = 500
# Only the compression methods real OOXML packages use.
OFFICE_ZIP_ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
# Legacy .doc/.ppt are OLE compound documents, so their pictures are carved by signature instead.
OLE_COMPOUND_FILE_SIGNATURE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
OFFICE_BINARY_SCAN_MAX_BYTES = 256 * 1024 * 1024

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


def _read_zip_entry_bounded(archive, entry_name, max_bytes):
    """Read a zip entry without trusting its declared uncompressed size.

    ``ZipInfo.file_size`` comes from the archive header and can be forged. CPython decompresses a
    chunk before truncating it to the declared size, so a 64 KB entry claiming to be 4 KB can still
    spike memory into the hundreds of megabytes. Streaming with a bounded per-chunk read keeps the
    decompressor's output capped, so the only safe limit is enforced here rather than from the header.

    Returns the entry bytes, or ``None`` when the entry is unreadable or exceeds ``max_bytes``.
    """
    try:
        entry_info = archive.getinfo(entry_name)
    except KeyError:
        return None

    if entry_info.compress_type not in OFFICE_ZIP_ALLOWED_COMPRESSION:
        return None

    # Cheap pre-filter for honest archives; never the only bound.
    if entry_info.file_size > max_bytes:
        return None

    chunks = []
    total_bytes = 0
    try:
        with archive.open(entry_name) as entry_file:
            while True:
                chunk = entry_file.read(OFFICE_ZIP_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    return None
                chunks.append(chunk)
    except (KeyError, ValueError, EOFError, zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError):
        return None

    return b''.join(chunks)


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
    inspected_rels = 0

    for entry_name in archive.namelist():
        if inspected_rels >= OFFICE_ZIP_MAX_RELS_ENTRIES:
            break

        slide_match = _PPTX_SLIDE_RELS_PATTERN.match(entry_name)
        if not slide_match:
            continue

        inspected_rels += 1
        slide_number = int(slide_match.group(1))

        rels_bytes = _read_zip_entry_bounded(archive, entry_name, OFFICE_EMBEDDED_RELS_MAX_BYTES)
        if rels_bytes is None:
            continue

        try:
            rels_root = defused_fromstring(rels_bytes)
        except (DefusedParseError, ValueError):
            continue

        for relationship in rels_root:
            target = str(relationship.attrib.get('Target') or '').replace('\\', '/')
            if '/media/' not in target:
                continue
            media_name = 'ppt/media/' + target.rsplit('/media/', 1)[-1]
            # Keep the first slide that references the image so ordering stays stable.
            media_slide_map.setdefault(media_name, slide_number)

    return media_slide_map


def _rasterize_vector_image(image_bytes):
    """Rasterize an EMF/WMF metafile to PNG bytes.

    Pillow only installs a metafile renderer on Windows, where it is backed by GDI, and this
    application runs in a Linux distroless container. Rendering therefore goes through the
    in-process metafile rasterizer, which behaves identically on every platform and needs no
    system packages.

    Returns ``(png_bytes, width, height, text, reason)`` where ``png_bytes`` is None on failure.
    """
    return render_metafile_to_png(image_bytes, max_pixels=OFFICE_EMBEDDED_IMAGE_RENDER_MAX_PIXELS)


def _new_diagnostics():
    return {
        'candidates': 0,
        'analyzed': 0,
        'skipped': 0,
        'skipped_reasons': {},
    }


def _record_skip(diagnostics, reason):
    diagnostics['skipped'] += 1
    diagnostics['skipped_reasons'][reason] = diagnostics['skipped_reasons'].get(reason, 0) + 1


def extract_office_embedded_images(file_path, output_dir, min_pixels=150, max_images=25):
    """Extract analyzable images embedded in an OOXML Office file.

    Args:
        file_path (str): Path to the DOCX/PPTX/XLSX file.
        output_dir (str): Directory that extracted images are written to.
        min_pixels (int): Minimum width and height required for an image to be analyzed.
        max_images (int): Maximum number of images to extract.

    Returns:
        list: Dicts with ``name``, ``path``, ``width``, ``height``, and ``slide_number`` keys.
    """
    extracted_images, _diagnostics = extract_office_embedded_images_with_diagnostics(
        file_path,
        output_dir,
        min_pixels=min_pixels,
        max_images=max_images,
    )
    return extracted_images


def _carve_metafiles_from_binary(data, max_metafiles):
    """Locate EMF and placeable WMF blobs inside a non-zip Office container.

    Legacy ``.doc`` and ``.ppt`` files are OLE compound documents rather than zip packages, so
    there is no ``word/media`` part to enumerate. Their pictures and embedded equation previews are
    still stored as intact metafile blobs, which can be located by signature and carved using the
    length recorded in the metafile's own header.

    Validation is deliberately strict -- record type, signature position, and a length that fits
    inside the remaining bytes -- so a coincidental byte sequence is not mistaken for an image.
    """
    carved = []
    offset = 0
    length = len(data)

    while offset < length and len(carved) < max_metafiles:
        emf_index = data.find(b' EMF', offset)
        wmf_index = data.find(b'\xd7\xcd\xc6\x9a', offset)

        candidates = [index for index in (emf_index, wmf_index) if index != -1]
        if not candidates:
            break
        next_index = min(candidates)

        if next_index == emf_index:
            record_start = emf_index - 40
            offset = emf_index + 4
            if record_start < 0 or record_start + 88 > length:
                continue
            record_type, _record_size = struct.unpack_from('<II', data, record_start)
            if record_type != 1:
                continue
            total_bytes = struct.unpack_from('<I', data, record_start + 48)[0]
            if not (88 <= total_bytes <= OFFICE_EMBEDDED_IMAGE_MAX_BYTES):
                continue
            if record_start + total_bytes > length:
                continue
            carved.append(('emf', data[record_start:record_start + total_bytes]))
            offset = record_start + total_bytes
        else:
            record_start = wmf_index
            offset = wmf_index + 4
            if record_start + 30 > length:
                continue
            # Placeable header is 22 bytes; the standard header's mtSize is measured in words.
            size_words = struct.unpack_from('<I', data, record_start + 28)[0]
            total_bytes = 22 + size_words * 2
            if not (30 <= total_bytes <= OFFICE_EMBEDDED_IMAGE_MAX_BYTES):
                continue
            if record_start + total_bytes > length:
                continue
            carved.append(('wmf', data[record_start:record_start + total_bytes]))
            offset = record_start + total_bytes

    return carved


def _extract_from_binary_office_file(file_path, output_dir, min_pixels, max_images, diagnostics):
    """Extract embedded metafiles from a legacy binary Office document."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size > OFFICE_BINARY_SCAN_MAX_BYTES:
            return []
        with open(file_path, 'rb') as handle:
            data = handle.read()
    except OSError:
        return []

    if not data.startswith(OLE_COMPOUND_FILE_SIGNATURE):
        return []

    carved = _carve_metafiles_from_binary(data, max_images * 4)
    diagnostics['candidates'] = len(carved)

    extracted_images = []
    seen_digests = set()

    for source_format, blob in carved:
        if len(extracted_images) >= max_images:
            _record_skip(diagnostics, 'per_document_cap_reached')
            continue

        if len(blob) < OFFICE_EMBEDDED_IMAGE_MIN_BYTES:
            _record_skip(diagnostics, 'below_minimum_bytes')
            continue

        digest = hashlib.sha256(blob).hexdigest()
        if digest in seen_digests:
            _record_skip(diagnostics, 'duplicate_image')
            continue

        png_bytes, width, height, embedded_text, reason = _rasterize_vector_image(blob)
        if png_bytes is None:
            _record_skip(diagnostics, reason or 'vector_not_rasterizable')
            continue

        if width < min_pixels or height < min_pixels:
            _record_skip(diagnostics, 'below_minimum_pixels')
            continue

        seen_digests.add(digest)
        output_path = os.path.join(output_dir, f"{len(extracted_images) + 1:03d}.png")
        try:
            with open(output_path, 'wb') as output_file:
                output_file.write(png_bytes)
        except OSError:
            _record_skip(diagnostics, 'write_failed')
            continue

        diagnostics['analyzed'] += 1
        extracted_images.append({
            'name': f"embedded_{len(extracted_images) + 1}.{source_format}",
            'path': output_path,
            'width': width,
            'height': height,
            'slide_number': None,
            'source_format': source_format,
            'rasterized': True,
            'embedded_text': embedded_text,
        })

    return extracted_images


def extract_office_embedded_images_with_diagnostics(file_path, output_dir, min_pixels=150, max_images=25):
    """Extract embedded images and report what was skipped and why.

    Without the diagnostics a document containing only unsupported figures is indistinguishable
    from a document containing no figures at all, which makes "were my images analyzed?"
    unanswerable from the workspace UI.

    Returns:
        tuple: ``(images, diagnostics)`` where diagnostics has ``candidates``, ``analyzed``,
        ``skipped``, and ``skipped_reasons``.
    """
    diagnostics = _new_diagnostics()

    if max_images <= 0:
        return [], diagnostics

    # Legacy .doc and .ppt are OLE compound documents, not zip packages.
    if not zipfile.is_zipfile(file_path):
        try:
            return _extract_from_binary_office_file(
                file_path, output_dir, min_pixels, max_images, diagnostics
            ), diagnostics
        except (OSError, ValueError, struct.error):
            return [], diagnostics

    extracted_images = []
    seen_digests = set()

    try:
        with zipfile.ZipFile(file_path) as archive:
            entry_names = archive.namelist()
            if len(entry_names) > OFFICE_ZIP_MAX_ENTRIES:
                # A real Office package never has this many parts; refuse to walk a crafted archive.
                return [], diagnostics

            media_slide_map = _build_pptx_media_slide_map(archive)

            candidate_names = [
                entry_name for entry_name in entry_names
                if entry_name.lower().startswith(OFFICE_EMBEDDED_IMAGE_MEDIA_PREFIXES)
                and entry_name.lower().endswith(OFFICE_EMBEDDED_IMAGE_ALL_EXTENSIONS)
            ]
            diagnostics['candidates'] = len(candidate_names)

            inspected_media = 0
            for media_name in sorted(candidate_names, key=_office_media_sort_key):
                if len(extracted_images) >= max_images:
                    _record_skip(diagnostics, 'per_document_cap_reached')
                    continue
                # Bound the work a malformed archive can cause, not just successful extractions.
                if inspected_media >= max_images * 10:
                    break
                inspected_media += 1

                base_name = _safe_media_base_name(media_name)
                if not base_name:
                    _record_skip(diagnostics, 'unsafe_entry_name')
                    continue

                image_bytes = _read_zip_entry_bounded(
                    archive,
                    media_name,
                    OFFICE_EMBEDDED_IMAGE_MAX_BYTES,
                )
                if image_bytes is None:
                    _record_skip(diagnostics, 'unreadable_or_oversized')
                    continue

                # Small assets are almost always icons, bullets, or spacer graphics.
                if len(image_bytes) < OFFICE_EMBEDDED_IMAGE_MIN_BYTES:
                    _record_skip(diagnostics, 'below_minimum_bytes')
                    continue

                digest = hashlib.sha256(image_bytes).hexdigest()
                if digest in seen_digests:
                    _record_skip(diagnostics, 'duplicate_image')
                    continue

                source_extension = os.path.splitext(base_name)[1].lower()
                is_vector = source_extension in OFFICE_EMBEDDED_IMAGE_VECTOR_EXTENSIONS
                embedded_text = ''

                if is_vector:
                    rasterized_bytes, width, height, embedded_text, rasterize_reason = _rasterize_vector_image(image_bytes)
                    if rasterized_bytes is None:
                        _record_skip(diagnostics, rasterize_reason or 'vector_not_rasterizable')
                        continue
                    image_bytes = rasterized_bytes
                    output_extension = '.png'
                else:
                    if source_extension not in OFFICE_EMBEDDED_IMAGE_EXTENSIONS:
                        _record_skip(diagnostics, 'unsupported_format')
                        continue
                    try:
                        with Image.open(BytesIO(image_bytes)) as embedded_image:
                            width, height = embedded_image.size
                    except Exception:
                        _record_skip(diagnostics, 'unreadable_image')
                        continue
                    output_extension = source_extension

                if width < min_pixels or height < min_pixels:
                    _record_skip(diagnostics, 'below_minimum_pixels')
                    continue

                # The output name is generated rather than taken from the archive, so a crafted
                # entry name can never influence where the file is written.
                output_path = os.path.join(output_dir, f"{len(extracted_images) + 1:03d}{output_extension}")

                seen_digests.add(digest)

                try:
                    with open(output_path, 'wb') as output_file:
                        output_file.write(image_bytes)
                except OSError:
                    _record_skip(diagnostics, 'write_failed')
                    continue

                diagnostics['analyzed'] += 1
                extracted_images.append({
                    'name': base_name,
                    'path': output_path,
                    'width': width,
                    'height': height,
                    'slide_number': media_slide_map.get(media_name),
                    'source_format': source_extension.lstrip('.'),
                    'rasterized': is_vector,
                    'embedded_text': embedded_text,
                })
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        return [], diagnostics

    return extracted_images, diagnostics
