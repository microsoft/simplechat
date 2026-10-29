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
# The main document part carries the body text used to locate images in reading order.
OFFICE_DOCUMENT_PART_MAX_BYTES = 64 * 1024 * 1024
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
            media_name = _normalize_office_media_target(relationship.attrib.get('Target'), 'ppt/media/')
            if not media_name:
                continue
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
        'total_body_words': 0,
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
        list: Dicts describing each extracted image, including ``name``, ``path``, ``width``,
        ``height``, ``source_format``, ``rasterized``, ``embedded_text``, and the position hints
        ``slide_number`` and ``word_offset`` used to place the image back into its origin chunk.
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
            'word_offset': None,
            'position_known': False,
            'source_format': source_format,
            'rasterized': True,
            'embedded_text': embedded_text,
        })

    return extracted_images


DOCX_MAIN_DOCUMENT_PART = 'word/document.xml'
DOCX_MAIN_DOCUMENT_RELS_PART = 'word/_rels/document.xml.rels'
DOCX_NS_WORDPROCESSING = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
DOCX_NS_DRAWING = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
DOCX_NS_RELATIONSHIPS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
DOCX_NS_VML = '{urn:schemas-microsoft-com:vml}'


def _normalize_office_media_target(target, media_prefix):
    """Resolve a relationship target to its package media path.

    Relationship targets are relative to the part that declares them, so Word writes
    ``media/image1.emf`` while PowerPoint writes ``../media/image1.png``. Both resolve to the same
    ``<prefix>/media/<file>`` location. Requiring a ``media`` parent segment also rejects unrelated
    targets such as hyperlinks.
    """
    normalized_target = str(target or '').replace('\\', '/')
    segments = [segment for segment in normalized_target.split('/') if segment not in ('', '.', '..')]
    if len(segments) < 2 or segments[-2].lower() != 'media':
        return ''
    return f'{media_prefix}{segments[-1]}'


def _build_docx_relationship_targets(archive):
    """Map relationship ids in the main document part to their ``word/media`` targets."""
    relationship_targets = {}

    rels_bytes = _read_zip_entry_bounded(
        archive, DOCX_MAIN_DOCUMENT_RELS_PART, OFFICE_EMBEDDED_RELS_MAX_BYTES
    )
    if rels_bytes is None:
        return relationship_targets

    try:
        rels_root = defused_fromstring(rels_bytes)
    except (DefusedParseError, ValueError):
        return relationship_targets

    for relationship in rels_root:
        relationship_id = str(relationship.attrib.get('Id') or '')
        if not relationship_id:
            continue
        if str(relationship.attrib.get('TargetMode') or '').lower() == 'external':
            continue
        media_name = _normalize_office_media_target(relationship.attrib.get('Target'), 'word/media/')
        if media_name:
            relationship_targets[relationship_id] = media_name

    return relationship_targets


def build_docx_image_word_offsets(archive):
    """Return ``(offsets, total_body_words)`` describing where each image sits in reading order.

    Word has no fixed pages until it is rendered, but the ingestion pipeline chunks Word content by
    word count, so an image's position in the document body maps onto a chunk. Walking
    ``document.xml`` in document order and counting the words that precede each image reference
    gives that position. The body total is returned as well so callers can place images
    proportionally, which stays stable when the extractor's word count differs from the raw body.
    """
    image_word_offsets = {}

    document_bytes = _read_zip_entry_bounded(
        archive, DOCX_MAIN_DOCUMENT_PART, OFFICE_DOCUMENT_PART_MAX_BYTES
    )
    if document_bytes is None:
        return image_word_offsets, 0

    try:
        document_root = defused_fromstring(document_bytes)
    except (DefusedParseError, ValueError):
        return image_word_offsets, 0

    relationship_targets = _build_docx_relationship_targets(archive)

    word_count = 0
    text_tag = f'{DOCX_NS_WORDPROCESSING}t'
    blip_tag = f'{DOCX_NS_DRAWING}blip'
    image_data_tag = f'{DOCX_NS_VML}imagedata'
    embed_attr = f'{DOCX_NS_RELATIONSHIPS}embed'
    id_attr = f'{DOCX_NS_RELATIONSHIPS}id'

    # iter() is a document-order traversal, which is the same order the text is extracted in.
    for element in document_root.iter():
        tag = element.tag
        if tag == text_tag:
            word_count += len(str(element.text or '').split())
            continue

        if not relationship_targets:
            continue

        relationship_id = ''
        if tag == blip_tag:
            relationship_id = str(element.attrib.get(embed_attr) or '')
        elif tag == image_data_tag:
            relationship_id = str(element.attrib.get(id_attr) or '')

        if not relationship_id:
            continue

        media_name = relationship_targets.get(relationship_id)
        if not media_name:
            continue

        # Keep the first occurrence so a repeated image maps to where it is first seen.
        image_word_offsets.setdefault(media_name, word_count)

    return image_word_offsets, word_count


def _build_office_media_accessibility_map(archive):
    """Map ``word/media/*`` and ``ppt/media/*`` entries to their native OOXML accessibility properties."""
    media_a11y_map = {}

    def _inspect_containers(root_elem, rel_targets):
        if not rel_targets:
            return
        for elem in root_elem.iter():
            local = _xml_local_name(elem.tag)
            if local not in ('inline', 'anchor', 'pic', 'shape'):
                continue
            placement = 'floating' if local == 'anchor' else 'inline'
            allow_overlap = _xml_attr_by_local_name(elem, 'allowOverlap') in ('1', 'true')
            behind_doc = _xml_attr_by_local_name(elem, 'behindDoc') in ('1', 'true')

            descr = ''
            title = ''
            is_decorative = False
            rel_id = ''

            if local == 'shape':
                descr = _xml_attr_by_local_name(elem, 'alt').strip()
                title = _xml_attr_by_local_name(elem, 'title').strip()

            for sub in elem.iter():
                s_local = _xml_local_name(sub.tag)
                if s_local in ('docPr', 'cNvPr') and not (descr or title):
                    descr = _xml_attr_by_local_name(sub, 'descr').strip()
                    title = _xml_attr_by_local_name(sub, 'title').strip()
                elif s_local == 'decorative':
                    val = _xml_attr_by_local_name(sub, 'val').lower()
                    if val in ('1', 'true', ''):
                        is_decorative = True
                elif s_local == 'blip' and not rel_id:
                    rel_id = _xml_attr_by_local_name(sub, 'embed')
                elif s_local == 'imagedata' and not rel_id:
                    rel_id = _xml_attr_by_local_name(sub, 'id')
                    if not descr:
                        descr = _xml_attr_by_local_name(sub, 'title').strip()

            media_name = rel_targets.get(rel_id) if rel_id else ''
            if not media_name:
                continue

            media_a11y_map.setdefault(
                media_name,
                {
                    'alt_text': descr,
                    'title_text': title,
                    'is_decorative': is_decorative,
                    'placement': placement,
                    'allow_overlap': allow_overlap,
                    'behind_doc': behind_doc,
                },
            )

    # 1. Word main document part
    docx_rels = _build_docx_relationship_targets(archive)
    if docx_rels:
        doc_bytes = _read_zip_entry_bounded(
            archive, DOCX_MAIN_DOCUMENT_PART, OFFICE_DOCUMENT_PART_MAX_BYTES
        )
        if doc_bytes is not None:
            try:
                doc_root = defused_fromstring(doc_bytes)
                _inspect_containers(doc_root, docx_rels)
            except (DefusedParseError, ValueError):
                pass

    # 2. PowerPoint slide parts
    inspected_slides = 0
    for entry_name in archive.namelist():
        if inspected_slides >= OFFICE_ZIP_MAX_RELS_ENTRIES:
            break
        slide_match = _PPTX_SLIDE_RELS_PATTERN.match(entry_name)
        if not slide_match:
            continue
        inspected_slides += 1
        slide_num = int(slide_match.group(1))
        slide_xml_path = f"ppt/slides/slide{slide_num}.xml"

        rels_bytes = _read_zip_entry_bounded(archive, entry_name, OFFICE_EMBEDDED_RELS_MAX_BYTES)
        slide_bytes = _read_zip_entry_bounded(archive, slide_xml_path, OFFICE_DOCUMENT_PART_MAX_BYTES)
        if rels_bytes is None or slide_bytes is None:
            continue
        try:
            rels_root = defused_fromstring(rels_bytes)
            slide_root = defused_fromstring(slide_bytes)
        except (DefusedParseError, ValueError):
            continue

        slide_rels = {}
        for rel in rels_root:
            r_id = str(rel.attrib.get('Id') or '').strip()
            media_name = _normalize_office_media_target(rel.attrib.get('Target'), 'ppt/media/')
            if r_id and media_name:
                slide_rels[r_id] = media_name
        _inspect_containers(slide_root, slide_rels)

    return media_a11y_map


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
            media_word_offsets, total_body_words = build_docx_image_word_offsets(archive)
            media_a11y_map = _build_office_media_accessibility_map(archive)
            diagnostics['total_body_words'] = total_body_words

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
                a11y_info = media_a11y_map.get(media_name) or {}
                extracted_images.append({
                    'name': base_name,
                    'path': output_path,
                    'width': width,
                    'height': height,
                    'slide_number': media_slide_map.get(media_name),
                    'word_offset': media_word_offsets.get(media_name),
                    'position_known': media_name in media_word_offsets or media_name in media_slide_map,
                    'source_format': source_extension.lstrip('.'),
                    'rasterized': is_vector,
                    'embedded_text': embedded_text,
                    'alt_text': a11y_info.get('alt_text', ''),
                    'title_text': a11y_info.get('title_text', ''),
                    'is_decorative': bool(a11y_info.get('is_decorative', False)),
                    'placement': a11y_info.get('placement', 'inline'),
                    'allow_overlap': bool(a11y_info.get('allow_overlap', False)),
                    'behind_doc': bool(a11y_info.get('behind_doc', False)),
                })
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        return [], diagnostics

    return extracted_images, diagnostics


DOCX_COMMENTS_PART = 'word/comments.xml'
DOCX_COMMENTS_EXTENDED_PART = 'word/commentsExtended.xml'
OFFICE_COMMENTS_PART_MAX_BYTES = 16 * 1024 * 1024
OFFICE_COMMENTS_MAX_COUNT = 2000
OFFICE_COMMENT_ANCHOR_MAX_CHARS = 300
WORD_COMMENTS_SECTION_HEADING = '### Document Comments'


def _xml_local_name(tag):
    """Return the namespace-free local name of an ElementTree tag."""
    if not isinstance(tag, str):
        return ''
    return tag.rsplit('}', 1)[-1]


def _xml_attr_by_local_name(element, *local_names):
    """Return the first matching attribute value by local name regardless of XML namespace."""
    if element is None or not getattr(element, 'attrib', None):
        return ''
    wanted = set(local_names)
    for name in local_names:
        if name in element.attrib:
            return str(element.attrib.get(name) or '')
    for attr_key, attr_value in element.attrib.items():
        if _xml_local_name(attr_key) in wanted:
            return str(attr_value or '')
    return ''


def _extract_docx_comment_paragraph_text(paragraph_elem):
    """Extract normalized plain text from a single OOXML comment paragraph."""
    fragments = []
    for node in paragraph_elem.iter():
        local_name = _xml_local_name(node.tag)
        if local_name in ('t', 'delText') and node.text:
            fragments.append(str(node.text))
        elif local_name == 'tab':
            fragments.append('\t')
        elif local_name in ('br', 'cr'):
            fragments.append('\n')

    raw_text = ''.join(fragments)
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in raw_text.splitlines()]
    return '\n'.join(line for line in lines if line).strip()


def build_docx_comment_anchors_and_offsets(archive):
    """Return ``(comment_word_offsets, comment_anchors, total_body_words)`` from ``word/document.xml``.

    Walking ``word/document.xml`` in document order captures both the reading-order word offset
    where each comment is anchored and the highlighted text between ``w:commentRangeStart`` and
    ``w:commentRangeEnd``.
    """
    comment_word_offsets = {}
    completed_anchors = {}

    document_bytes = _read_zip_entry_bounded(
        archive, DOCX_MAIN_DOCUMENT_PART, OFFICE_DOCUMENT_PART_MAX_BYTES
    )
    if document_bytes is None:
        return comment_word_offsets, completed_anchors, 0

    try:
        document_root = defused_fromstring(document_bytes)
    except (DefusedParseError, ValueError):
        return comment_word_offsets, completed_anchors, 0

    word_count = 0
    active_ranges = {}
    active_range_lengths = {}

    for element in document_root.iter():
        local_name = _xml_local_name(element.tag)
        if local_name == 'commentRangeStart':
            comment_id = _xml_attr_by_local_name(element, 'id').strip()
            if comment_id:
                comment_word_offsets.setdefault(comment_id, word_count)
                if comment_id not in completed_anchors and comment_id not in active_ranges:
                    active_ranges[comment_id] = []
                    active_range_lengths[comment_id] = 0
            continue

        if local_name == 'commentRangeEnd':
            comment_id = _xml_attr_by_local_name(element, 'id').strip()
            if comment_id and comment_id in active_ranges:
                anchor_text = re.sub(r'\s+', ' ', ''.join(active_ranges.pop(comment_id))).strip()
                active_range_lengths.pop(comment_id, None)
                if anchor_text:
                    completed_anchors.setdefault(
                        comment_id, anchor_text[:OFFICE_COMMENT_ANCHOR_MAX_CHARS]
                    )
            continue

        if local_name == 'commentReference':
            comment_id = _xml_attr_by_local_name(element, 'id').strip()
            if comment_id:
                comment_word_offsets.setdefault(comment_id, word_count)
            continue

        if local_name in ('t', 'delText'):
            text_value = str(element.text or '')
            word_count += len(text_value.split())
            if active_ranges and text_value:
                for comment_id, parts in active_ranges.items():
                    current_len = active_range_lengths.get(comment_id, 0)
                    remaining = OFFICE_COMMENT_ANCHOR_MAX_CHARS - current_len
                    if remaining > 0:
                        snippet = text_value[:remaining]
                        parts.append(snippet)
                        active_range_lengths[comment_id] = current_len + len(snippet)
            continue

        if local_name in ('tab', 'br', 'cr') and active_ranges:
            for comment_id, parts in active_ranges.items():
                current_len = active_range_lengths.get(comment_id, 0)
                if current_len < OFFICE_COMMENT_ANCHOR_MAX_CHARS:
                    parts.append(' ')
                    active_range_lengths[comment_id] = current_len + 1

    for comment_id, parts in active_ranges.items():
        anchor_text = re.sub(r'\s+', ' ', ''.join(parts)).strip()
        if anchor_text:
            completed_anchors.setdefault(comment_id, anchor_text[:OFFICE_COMMENT_ANCHOR_MAX_CHARS])

    return comment_word_offsets, completed_anchors, word_count


def _parse_docx_comments_extended(archive):
    """Parse ``word/commentsExtended.xml`` for reply parent links and resolved state."""
    extended_by_para_id = {}
    extended_bytes = _read_zip_entry_bounded(
        archive, DOCX_COMMENTS_EXTENDED_PART, OFFICE_COMMENTS_PART_MAX_BYTES
    )
    if extended_bytes is None:
        return extended_by_para_id

    try:
        extended_root = defused_fromstring(extended_bytes)
    except (DefusedParseError, ValueError):
        return extended_by_para_id

    for elem in extended_root.iter():
        if _xml_local_name(elem.tag) != 'commentEx':
            continue
        para_id = _xml_attr_by_local_name(elem, 'paraId').strip()
        if not para_id:
            continue
        parent_para_id = _xml_attr_by_local_name(elem, 'paraIdParent').strip()
        done_raw = _xml_attr_by_local_name(elem, 'done').strip().lower()
        extended_by_para_id[para_id] = {
            'parent_para_id': parent_para_id or None,
            'done': done_raw in ('1', 'true', 'on'),
        }

    return extended_by_para_id


def extract_docx_comments(file_path):
    """Extract structured review comments from an OOXML Word package (``.docx``, ``.docm``, ``.dotx``).

    Returns ``(comments, total_body_words)`` where ``comments`` is a list of top-level comment
    dicts (with nested ``replies`` when ``word/commentsExtended.xml`` links reply threads).
    """
    if not file_path or not zipfile.is_zipfile(file_path):
        return [], 0

    try:
        with zipfile.ZipFile(file_path) as archive:
            entry_names = archive.namelist()
            if len(entry_names) > OFFICE_ZIP_MAX_ENTRIES:
                return [], 0

            comment_word_offsets, comment_anchors, total_body_words = (
                build_docx_comment_anchors_and_offsets(archive)
            )
            if DOCX_COMMENTS_PART not in entry_names:
                return [], total_body_words

            comments_bytes = _read_zip_entry_bounded(
                archive, DOCX_COMMENTS_PART, OFFICE_COMMENTS_PART_MAX_BYTES
            )
            if comments_bytes is None:
                return [], total_body_words

            try:
                comments_root = defused_fromstring(comments_bytes)
            except (DefusedParseError, ValueError):
                return [], total_body_words

            extended_by_para_id = _parse_docx_comments_extended(archive)

            raw_comments = []
            comments_by_id = {}
            para_id_to_comment_id = {}

            for element in comments_root:
                if _xml_local_name(element.tag) != 'comment':
                    continue
                if len(raw_comments) >= OFFICE_COMMENTS_MAX_COUNT:
                    break

                comment_id = _xml_attr_by_local_name(element, 'id').strip()
                if not comment_id:
                    comment_id = str(len(raw_comments) + 1)

                author = _xml_attr_by_local_name(element, 'author').strip()
                initials = _xml_attr_by_local_name(element, 'initials').strip()
                date_str = _xml_attr_by_local_name(element, 'date').strip()

                paragraph_texts = []
                para_ids = []
                for child in element:
                    if _xml_local_name(child.tag) != 'p':
                        continue
                    para_id = _xml_attr_by_local_name(child, 'paraId').strip()
                    if para_id:
                        para_ids.append(para_id)
                        para_id_to_comment_id[para_id] = comment_id
                    paragraph_text = _extract_docx_comment_paragraph_text(child)
                    if paragraph_text:
                        paragraph_texts.append(paragraph_text)

                if not paragraph_texts:
                    fallback_text = _extract_docx_comment_paragraph_text(element)
                    if fallback_text:
                        paragraph_texts.append(fallback_text)

                comment_text = '\n'.join(paragraph_texts).strip()
                if not comment_text:
                    continue

                word_offset = comment_word_offsets.get(comment_id)
                comment_record = {
                    'id': comment_id,
                    'author': author,
                    'initials': initials,
                    'date': date_str,
                    'text': comment_text,
                    'anchor_text': comment_anchors.get(comment_id, ''),
                    'word_offset': word_offset,
                    'position_known': word_offset is not None,
                    'parent_id': None,
                    'done': False,
                    'replies': [],
                    '_para_ids': para_ids,
                }
                raw_comments.append(comment_record)
                comments_by_id[comment_id] = comment_record

            for comment_record in raw_comments:
                for para_id in comment_record.pop('_para_ids', []):
                    ext_info = extended_by_para_id.get(para_id)
                    if not ext_info:
                        continue
                    if ext_info.get('done'):
                        comment_record['done'] = True
                    parent_para_id = ext_info.get('parent_para_id')
                    if parent_para_id:
                        parent_comment_id = para_id_to_comment_id.get(parent_para_id)
                        if parent_comment_id and parent_comment_id != comment_record['id']:
                            comment_record['parent_id'] = parent_comment_id

            def _resolve_root_comment(record):
                visited = {record['id']}
                current = record
                while current.get('parent_id') and current['parent_id'] in comments_by_id:
                    parent_id = current['parent_id']
                    if parent_id in visited:
                        break
                    visited.add(parent_id)
                    current = comments_by_id[parent_id]
                return current

            top_level_comments = []
            for comment_record in raw_comments:
                root_comment = _resolve_root_comment(comment_record)
                if root_comment is comment_record:
                    top_level_comments.append(comment_record)
                else:
                    root_comment['replies'].append({
                        'id': comment_record['id'],
                        'author': comment_record['author'],
                        'initials': comment_record['initials'],
                        'date': comment_record['date'],
                        'text': comment_record['text'],
                        'done': comment_record['done'],
                    })
                    if root_comment.get('word_offset') is None and comment_record.get('word_offset') is not None:
                        root_comment['word_offset'] = comment_record['word_offset']
                        root_comment['position_known'] = True
                    if not root_comment.get('anchor_text') and comment_record.get('anchor_text'):
                        root_comment['anchor_text'] = comment_record['anchor_text']

            return top_level_comments, total_body_words
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        return [], 0


def _format_comment_author_header(comment):
    """Build a readable ``by Author (Initials) [Date]`` suffix for a comment or reply."""
    author = str(comment.get('author') or '').strip()
    initials = str(comment.get('initials') or '').strip()
    date_str = str(comment.get('date') or '').strip()
    done = bool(comment.get('done'))

    author_part = ''
    if author and initials and initials.lower() != author.lower():
        author_part = f"by {author} ({initials})"
    elif author:
        author_part = f"by {author}"
    elif initials:
        author_part = f"by {initials}"

    meta_parts = []
    if author_part:
        meta_parts.append(author_part)
    if date_str:
        meta_parts.append(f"[{date_str}]")
    if done:
        meta_parts.append("(Resolved)")

    return (' ' + ' '.join(meta_parts)) if meta_parts else ''


def format_word_comment_block(comment, index=None, total=None):
    """Format a single Word comment (and any replies) as a self-contained Markdown block."""
    if not isinstance(comment, dict):
        return ''
    comment_text = str(comment.get('text') or '').strip()
    if not comment_text:
        return ''

    if index is not None and total is not None:
        number_label = f" {index} of {total}"
    elif index is not None:
        number_label = f" {index}"
    else:
        comment_id = str(comment.get('id') or '').strip()
        number_label = f" {comment_id}" if comment_id else ''

    author_suffix = _format_comment_author_header(comment)
    anchor_text = str(comment.get('anchor_text') or '').strip()
    anchor_suffix = f' on "{anchor_text}"' if anchor_text else ''

    lines = [
        f"### Document comment{number_label}{author_suffix}{anchor_suffix}",
        comment_text,
    ]

    for reply in comment.get('replies') or []:
        reply_text = str(reply.get('text') or '').strip()
        if not reply_text:
            continue
        reply_meta = _format_comment_author_header(reply)
        lines.append(f"- Reply{reply_meta}: {reply_text}")

    return '\n'.join(lines)


def format_word_comments_section(comments):
    """Format a list of Word comments into a trailing document section."""
    if not comments:
        return ''
    total = len(comments)
    blocks = []
    for idx, comment in enumerate(comments, start=1):
        block = format_word_comment_block(comment, index=idx, total=total)
        if block:
            blocks.append(block)
    if not blocks:
        return ''
    return f"{WORD_COMMENTS_SECTION_HEADING}\n\n" + "\n\n".join(blocks)


def strip_appended_word_comments(text):
    """Remove a trailing ``WORD_COMMENTS_SECTION_HEADING`` section when chunking separately."""
    if not text:
        return ''
    marker = f"\n\n{WORD_COMMENTS_SECTION_HEADING}\n\n"
    if marker in text:
        return text.split(marker, 1)[0].rstrip()
    if text.startswith(f"{WORD_COMMENTS_SECTION_HEADING}\n\n"):
        return ''
    return text

