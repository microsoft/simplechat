# functions_accessibility.py

"""Native PDF and Office accessibility, structure, tag-tree, and annotation extraction.

Azure AI Document Intelligence and Azure AI Content Understanding operate on the rendered visual
surface of a document. While that produces rich Markdown and AI figure descriptions, it can mask
underlying accessibility defects (for example, OCR-ing an untagged PDF into clean headings or
describing a figure that lacks native alt text).

This module inspects the native file structures in-process using already-installed libraries
(`pypdf`, `PyMuPDF`/`fitz`, `defusedxml`, `olefile`) to produce:

1. A structured, bounded ``accessibility_metadata`` object stored on the parent Cosmos DB document
   record (document-level flags, language/title/viewer metadata, heading outline, figure/table/form/
   link inventories, compact semantic tag tree, and actionable accessibility issues).
2. Per-page / per-section / per-slide inline Markdown blocks (tag tree in reading order, native
   alt text & decorative status, and PDF/PPTX page/slide comments) merged directly into the
   corresponding Azure AI Search chunks (`chunk_text`) so zero structural data is lost.
"""

import os
import re
import zipfile
from collections import Counter

import fitz
import olefile
from defusedxml.ElementTree import ParseError as DefusedParseError
from defusedxml.ElementTree import fromstring as defused_fromstring
from pypdf import PdfReader

from functions_appinsights import log_event
from functions_document_style import (
    build_legacy_doc_style_inventory,
    build_pptx_style_inventory,
    build_word_style_inventory,
    extract_pdf_style_inventory,
    format_style_inventory_for_chat,
    safe_style_extraction,
)
from functions_office_media import (
    DOCX_MAIN_DOCUMENT_PART,
    DOCX_MAIN_DOCUMENT_RELS_PART,
    OFFICE_DOCUMENT_PART_MAX_BYTES,
    OFFICE_EMBEDDED_RELS_MAX_BYTES,
    OFFICE_ZIP_MAX_ENTRIES,
    _read_zip_entry_bounded,
    _xml_attr_by_local_name,
    _xml_local_name,
)


PDF_SEMANTIC_TAGS = {
    'Document', 'Part', 'Art', 'Sect', 'Div', 'BlockQuote', 'Caption',
    'TOC', 'TOCI', 'Index', 'NonStruct', 'Private',
    'H', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'Title',
    'P', 'L', 'LI', 'Lbl', 'LBody',
    'Table', 'TR', 'TH', 'TD', 'THead', 'TBody', 'TFoot',
    'Figure', 'Formula', 'Form', 'Link', 'Annot', 'Note', 'Reference',
    'BibEntry', 'Code', 'Quote',
}

PDF_HEADING_TAGS = {'H', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'Title'}

PDF_REVIEW_ANNOT_SUBTYPES = {
    'Text', 'FreeText', 'Highlight', 'Underline', 'StrikeOut',
    'Squiggly', 'Caret', 'Stamp',
}

GENERIC_LINK_TEXTS = {
    'click here', 'here', 'link', 'read more', 'more', 'learn more',
    'website', 'url', 'this link', 'page', 'go', 'info', 'details',
}

MAX_COSMOS_SEMANTIC_NODES = 600
MAX_COSMOS_HEADINGS = 200
MAX_COSMOS_FIGURES = 150
MAX_COSMOS_TABLES = 100
MAX_COSMOS_FORMS = 150
MAX_COSMOS_LINKS = 150
MAX_COSMOS_ISSUES = 100
MAX_PAGE_TAG_ITEMS = 120
WORD_CHUNK_MIN_BUCKET_WORDS = 200
WORD_CHUNK_BUCKET_DIVISOR = 12

_ARTIFACT_PATTERN = re.compile(rb'/Artifact\b')
_PPTX_SLIDE_XML_PATTERN = re.compile(r'^ppt/slides/slide(\d+)\.xml$', re.IGNORECASE)
_PPTX_SLIDE_RELS_XML_PATTERN = re.compile(r'^ppt/slides/_rels/slide(\d+)\.xml\.rels$', re.IGNORECASE)
_MANUAL_BULLET_PATTERN = re.compile(r'^\s*(?:[\u2022\u2023\u25E6\u2043\u2219\*\-\+]|(?:\d+|[a-zA-Z])[\.\)])\s+\S')


def _safe_deref(obj):
    """Dereference a pypdf IndirectObject safely."""
    try:
        while hasattr(obj, 'get_object'):
            next_obj = obj.get_object()
            if next_obj is obj or next_obj is None:
                break
            obj = next_obj
    except Exception:
        return None
    return obj


def _pdf_str(val):
    """Convert a pypdf string/NameObject/byte value to a clean Python str."""
    val = _safe_deref(val)
    if val is None:
        return ''
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    text = str(val).strip()
    if text.startswith('/'):
        text = text[1:]
    return text


def _pdf_bool(val):
    """Convert a pypdf boolean/NameObject value to bool."""
    val = _safe_deref(val)
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    text = str(val).strip().lower()
    return text in ('true', '/true', '1', 'yes')


def _clean_pdf_date(date_str):
    """Normalize a PDF date string like ``D:20250210143000Z`` into ISO-like form."""
    raw = str(date_str or '').strip()
    if not raw:
        return ''
    if raw.startswith('D:'):
        raw = raw[2:]
    match = re.match(r'^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?', raw)
    if not match:
        return raw
    year = match.group(1)
    month = match.group(2) or '01'
    day = match.group(3) or '01'
    hour = match.group(4)
    minute = match.group(5)
    second = match.group(6) or '00'
    if hour and minute:
        return f"{year}-{month}-{day}T{hour}:{minute}:{second}Z"
    return f"{year}-{month}-{day}"


def _build_pdf_page_id_map(reader):
    """Map pypdf page indirect object ids to 1-based page numbers."""
    page_map = {}
    try:
        for idx, page in enumerate(reader.pages, start=1):
            indirect_ref = getattr(page, 'indirect_reference', None)
            if indirect_ref is not None and hasattr(indirect_ref, 'idnum'):
                page_map[indirect_ref.idnum] = idx
            raw_obj = _safe_deref(page)
            if raw_obj is not None:
                page_map[id(raw_obj)] = idx
    except Exception:
        # Return partial page map if a malformed PDF page list raises during enumeration.
        pass
    return page_map


def _resolve_pdf_node_page(node_dict, page_map, inherited_page=None):
    """Resolve the 1-based page number from a StructElem's ``/Pg`` entry."""
    if not hasattr(node_dict, 'get'):
        return inherited_page
    raw_pg = node_dict.get('/Pg')
    if raw_pg is not None:
        if hasattr(raw_pg, 'idnum') and raw_pg.idnum in page_map:
            return page_map[raw_pg.idnum]
        deref_pg = _safe_deref(raw_pg)
        if deref_pg is not None and id(deref_pg) in page_map:
            return page_map[id(deref_pg)]
    return inherited_page


def _extract_struct_attr_dict(node_dict):
    """Extract accessibility attributes from a StructElem and its ``/A`` attribute dictionary."""
    attrs = {}
    if not hasattr(node_dict, 'get'):
        return attrs

    for key, out_key in (
        ('/Alt', 'alt'),
        ('/ActualText', 'actual_text'),
        ('/E', 'expansion'),
        ('/Lang', 'lang'),
        ('/T', 'title'),
    ):
        raw_val = node_dict.get(key)
        if raw_val is not None:
            str_val = _pdf_str(raw_val)
            if str_val:
                attrs[out_key] = str_val

    raw_a = _safe_deref(node_dict.get('/A'))
    a_dicts = []
    if isinstance(raw_a, list):
        for item in raw_a[:10]:
            deref_item = _safe_deref(item)
            if hasattr(deref_item, 'get'):
                a_dicts.append(deref_item)
    elif hasattr(raw_a, 'get'):
        a_dicts.append(raw_a)

    for a_dict in a_dicts:
        scope = _pdf_str(a_dict.get('/Scope'))
        if scope:
            attrs['scope'] = scope
        col_span = _safe_deref(a_dict.get('/ColSpan'))
        if isinstance(col_span, int) and col_span > 1:
            attrs['col_span'] = col_span
        row_span = _safe_deref(a_dict.get('/RowSpan'))
        if isinstance(row_span, int) and row_span > 1:
            attrs['row_span'] = row_span
        headers = _safe_deref(a_dict.get('/Headers'))
        if isinstance(headers, list) and headers:
            attrs['headers'] = [_pdf_str(h) for h in headers[:10] if _pdf_str(h)]
        bbox = _safe_deref(a_dict.get('/BBox'))
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                attrs['bbox'] = [round(float(x), 1) for x in bbox]
            except Exception:
                # Ignore non-numeric bounding box coordinates.
                pass

    return attrs


def _walk_pdf_struct_tree(struct_root, page_map, max_visited=25000):
    """Walk ``/StructTreeRoot`` in reading order while coalescing unattributed kerning ``<Span>`` leaves.

    Preserves 100% of structural/semantic tags and any ``<Span>`` that carries accessibility
    attributes (``/Lang``, ``/Alt``, ``/ActualText``, ``/E``, ``/T``).
    """
    result = {
        'tag_counts': Counter(),
        'raw_node_count': 0,
        'coalesced_span_count': 0,
        'semantic_nodes': [],
        'per_page_nodes': {},
        'headings': [],
        'figures': [],
        'tables': [],
        'lists': {'list_count': 0, 'list_item_count': 0, 'has_labels': False},
        'links': [],
        'forms': [],
        'role_map': {},
    }

    root_obj = _safe_deref(struct_root)
    if not hasattr(root_obj, 'get'):
        return result

    role_map_obj = _safe_deref(root_obj.get('/RoleMap'))
    if hasattr(role_map_obj, 'items'):
        for custom_tag, std_tag in list(role_map_obj.items())[:200]:
            c_name = _pdf_str(custom_tag)
            s_name = _pdf_str(std_tag)
            if c_name and s_name:
                result['role_map'][c_name] = s_name

    visited_ids = set()

    def _inspect_table_subtree(table_dict, page_num, depth=0):
        """Summarize rows, TH header cells, TD data cells, and scopes inside a <Table> tag."""
        stats = {'row_count': 0, 'th_count': 0, 'td_count': 0, 'scopes': set(), 'has_headers_attr': False}
        stack = [(table_dict, depth)]
        seen_table_nodes = set()
        while stack and len(seen_table_nodes) < 2000:
            curr, d = stack.pop()
            curr = _safe_deref(curr)
            if curr is None or id(curr) in seen_table_nodes or d > 25:
                continue
            seen_table_nodes.add(id(curr))
            if isinstance(curr, list):
                for item in reversed(curr):
                    stack.append((item, d + 1))
                continue
            if not hasattr(curr, 'get'):
                continue
            raw_s = _pdf_str(curr.get('/S'))
            mapped_s = result['role_map'].get(raw_s, raw_s)
            if mapped_s == 'TR':
                stats['row_count'] += 1
            elif mapped_s == 'TH':
                stats['th_count'] += 1
                th_attrs = _extract_struct_attr_dict(curr)
                if th_attrs.get('scope'):
                    stats['scopes'].add(th_attrs['scope'])
            elif mapped_s == 'TD':
                stats['td_count'] += 1
                td_attrs = _extract_struct_attr_dict(curr)
                if td_attrs.get('headers'):
                    stats['has_headers_attr'] = True
            kids = curr.get('/K')
            if kids is not None:
                stack.append((kids, d + 1))
        return stats

    def _traverse(node, inherited_page=None, depth=0, parent_tag=''):
        if result['raw_node_count'] >= max_visited or depth > 64:
            return
        deref_node = _safe_deref(node)
        if deref_node is None:
            return

        if isinstance(deref_node, list):
            for child in deref_node:
                _traverse(child, inherited_page=inherited_page, depth=depth, parent_tag=parent_tag)
            return

        if isinstance(deref_node, int):
            # MCID leaf integer
            return

        if not hasattr(deref_node, 'get'):
            return

        node_id = id(deref_node)
        if node_id in visited_ids:
            return
        visited_ids.add(node_id)

        node_type = _pdf_str(deref_node.get('/Type'))
        raw_tag = _pdf_str(deref_node.get('/S'))
        if not raw_tag and node_type in ('MCR', 'OBJR'):
            return

        page_num = _resolve_pdf_node_page(deref_node, page_map, inherited_page=inherited_page)
        mapped_tag = result['role_map'].get(raw_tag, raw_tag)

        if raw_tag:
            result['raw_node_count'] += 1
            result['tag_counts'][mapped_tag] += 1

        attrs = _extract_struct_attr_dict(deref_node) if raw_tag else {}

        # Determine if this is an unattributed kerning <Span> leaf wrapper
        is_unattributed_span = (
            mapped_tag == 'Span'
            and not attrs.get('alt')
            and not attrs.get('actual_text')
            and not attrs.get('lang')
            and not attrs.get('expansion')
            and not attrs.get('title')
        )

        if is_unattributed_span:
            result['coalesced_span_count'] += 1
        elif raw_tag:
            node_entry = {
                'tag': mapped_tag,
                'raw_tag': raw_tag if raw_tag != mapped_tag else None,
                'page_number': page_num,
                'depth': depth,
            }
            for k in ('alt', 'actual_text', 'expansion', 'lang', 'title', 'scope', 'col_span', 'row_span', 'headers'):
                if k in attrs:
                    node_entry[k] = attrs[k]
            node_entry = {k: v for k, v in node_entry.items() if v is not None}

            result['semantic_nodes'].append(node_entry)
            if page_num is not None:
                result['per_page_nodes'].setdefault(page_num, []).append(node_entry)

            # Specialized inventories
            if mapped_tag in PDF_HEADING_TAGS:
                level = None
                if mapped_tag.startswith('H') and len(mapped_tag) == 2 and mapped_tag[1].isdigit():
                    level = int(mapped_tag[1])
                elif mapped_tag in ('H', 'Title'):
                    level = 1
                result['headings'].append({
                    'tag': mapped_tag,
                    'level': level,
                    'page_number': page_num,
                    'title': attrs.get('title') or attrs.get('actual_text') or attrs.get('alt') or '',
                })
            elif mapped_tag == 'Figure':
                alt_text = attrs.get('alt') or ''
                actual_text = attrs.get('actual_text') or ''
                result['figures'].append({
                    'page_number': page_num,
                    'alt_text': alt_text,
                    'actual_text': actual_text,
                    'has_alt': bool(alt_text.strip() or actual_text.strip()),
                    'bbox': attrs.get('bbox'),
                })
            elif mapped_tag == 'Table':
                t_stats = _inspect_table_subtree(deref_node, page_num, depth=depth)
                result['tables'].append({
                    'page_number': page_num,
                    'row_count': t_stats['row_count'],
                    'th_count': t_stats['th_count'],
                    'td_count': t_stats['td_count'],
                    'has_headers': t_stats['th_count'] > 0 or t_stats['has_headers_attr'],
                    'scopes': sorted(t_stats['scopes']),
                })
            elif mapped_tag == 'L':
                result['lists']['list_count'] += 1
            elif mapped_tag == 'LI':
                result['lists']['list_item_count'] += 1
            elif mapped_tag == 'Lbl':
                result['lists']['has_labels'] = True
            elif mapped_tag == 'Link':
                result['links'].append({
                    'page_number': page_num,
                    'alt_text': attrs.get('alt') or attrs.get('actual_text') or '',
                    'is_tagged': True,
                })
            elif mapped_tag == 'Form':
                result['forms'].append({
                    'page_number': page_num,
                    'alt_text': attrs.get('alt') or attrs.get('title') or '',
                    'is_tagged_form': True,
                })

        kids = deref_node.get('/K')
        if kids is not None:
            _traverse(kids, inherited_page=page_num, depth=depth + 1 if raw_tag else depth, parent_tag=mapped_tag or parent_tag)

    top_k = root_obj.get('/K')
    if top_k is not None:
        _traverse(top_k, inherited_page=None, depth=0, parent_tag='StructTreeRoot')

    return result


def extract_pdf_page_annotations(pdf_path):
    """Extract PDF review annotations/comments per page using PyMuPDF.

    Returns:
        dict: Mapping ``page_number (int) -> list[dict]`` of extracted annotations.
    """
    annotations_by_page = {}
    if not pdf_path or not os.path.exists(pdf_path):
        return annotations_by_page

    doc = None
    try:
        doc = fitz.open(pdf_path)
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            annots = page.annots()
            if not annots:
                continue

            page_items = []
            for annot in annots:
                try:
                    subtype = str(annot.type[1] or '').strip() if annot.type else ''
                except Exception:
                    subtype = ''
                if subtype not in PDF_REVIEW_ANNOT_SUBTYPES:
                    continue

                info = annot.info or {}
                content = str(info.get('content') or '').strip()
                author = str(info.get('title') or '').strip()
                subject = str(info.get('subject') or '').strip()
                created_date = _clean_pdf_date(info.get('creationDate') or info.get('modDate') or '')

                anchor_text = ''
                if subtype in ('Highlight', 'Underline', 'StrikeOut', 'Squiggly'):
                    try:
                        clip_rect = annot.rect
                        if clip_rect and not clip_rect.is_empty:
                            clipped = page.get_text('text', clip=clip_rect) or ''
                            anchor_text = re.sub(r'\s+', ' ', clipped).strip()[:300]
                    except Exception:
                        anchor_text = ''

                if not content and not anchor_text:
                    continue

                page_items.append({
                    'page_number': page_number,
                    'subtype': subtype,
                    'author': author,
                    'subject': subject,
                    'date': created_date,
                    'text': content or f"[{subtype} markup]",
                    'anchor_text': anchor_text,
                })

            if page_items:
                annotations_by_page[page_number] = page_items
    except Exception as exc:
        log_event(
            f"[DOCUMENT_METADATA] Failed to extract PDF page annotations: {type(exc).__name__}",
            level=20,
            debug_only=True,
        )
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                # Ignore errors when closing the PyMuPDF document handle.
                pass

    return annotations_by_page


def format_pdf_page_annotation_block(annotation, index=None, total=None):
    """Format a PDF page annotation/comment as an inline Markdown block."""
    if not isinstance(annotation, dict):
        return ''
    text = str(annotation.get('text') or '').strip()
    anchor_text = str(annotation.get('anchor_text') or '').strip()
    if not text and not anchor_text:
        return ''

    if index is not None and total is not None:
        number_label = f" {index} of {total}"
    elif index is not None:
        number_label = f" {index}"
    else:
        number_label = ''

    subtype = str(annotation.get('subtype') or 'Comment').strip()
    author = str(annotation.get('author') or '').strip()
    date_str = str(annotation.get('date') or '').strip()

    meta_parts = [f"({subtype})"] if subtype else []
    if author:
        meta_parts.append(f"by {author}")
    if date_str:
        meta_parts.append(f"[{date_str}]")
    meta_suffix = (' ' + ' '.join(meta_parts)) if meta_parts else ''
    anchor_suffix = f' on "{anchor_text}"' if anchor_text else ''

    return f"### Page comment{number_label}{meta_suffix}{anchor_suffix}\n{text}"


def extract_pdf_accessibility_metadata(pdf_path):
    """Extract comprehensive PDF accessibility, structure, tag tree, and comment metadata.

    Returns:
        tuple: ``(cosmos_accessibility_metadata, per_page_details)`` where:
            - ``cosmos_accessibility_metadata`` is a JSON-serializable dict for the parent Cosmos record.
            - ``per_page_details`` maps 1-based ``page_number -> dict`` with ``annotations``,
              ``tag_nodes``, ``artifact_count``, ``tabs_order``, ``untagged_images``, ``form_widgets``,
              and ``formatted_accessibility_block``.
    """
    cosmos_meta = {
        'format': 'pdf',
        'schema_version': '1.0',
        'is_tagged': False,
        'suspects': False,
        'has_struct_tree': False,
        'language': '',
        'title': '',
        'title_present': False,
        'display_doc_title': False,
        'has_bookmarks': False,
        'bookmark_count': 0,
        'bookmarks': [],
        'page_count': 0,
        'page_tabs_order': {'structure_order_pages': 0, 'non_structure_pages': []},
        'tag_counts': {},
        'raw_tag_node_count': 0,
        'coalesced_span_count': 0,
        'heading_outline': [],
        'figures_summary': {'total': 0, 'with_alt': 0, 'missing_alt': 0, 'untagged_images': 0, 'items': []},
        'tables_summary': {'total': 0, 'with_headers': 0, 'missing_headers': 0, 'items': []},
        'lists_summary': {'list_count': 0, 'list_item_count': 0, 'has_labels': False},
        'links_summary': {'tagged_links': 0, 'link_annotations': 0},
        'forms_summary': {'total_fields': 0, 'with_tooltip': 0, 'missing_tooltip': 0, 'items': []},
        'artifacts_summary': {'total_artifact_blocks': 0, 'pages_with_artifacts': []},
        'comments_summary': {'total_annotations': 0, 'pages_with_annotations': []},
        'semantic_tag_tree': [],
        'semantic_tag_tree_truncated': False,
        'issues': [],
    }
    per_page_details = {}

    if not pdf_path or not os.path.exists(pdf_path):
        return cosmos_meta, per_page_details

    annotations_by_page = extract_pdf_page_annotations(pdf_path)
    total_annots = sum(len(items) for items in annotations_by_page.values())
    cosmos_meta['comments_summary'] = {
        'total_annotations': total_annots,
        'pages_with_annotations': sorted(annotations_by_page.keys()),
    }

    # 1. Inspect via PyMuPDF for bookmarks, metadata title, and per-page image counts
    fitz_doc = None
    per_page_visual_images = {}
    pdf_page_style_lines = {}
    try:
        fitz_doc = fitz.open(pdf_path)
        cosmos_meta['page_count'] = len(fitz_doc)
        meta_dict = fitz_doc.metadata or {}
        title_val = str(meta_dict.get('title') or '').strip()
        if title_val:
            cosmos_meta['title'] = title_val
            cosmos_meta['title_present'] = True

        toc = fitz_doc.get_toc() or []
        cosmos_meta['bookmark_count'] = len(toc)
        cosmos_meta['has_bookmarks'] = len(toc) > 0
        cosmos_meta['bookmarks'] = [
            {'level': int(item[0]), 'title': str(item[1] or '').strip(), 'page_number': int(item[2])}
            for item in toc[:100]
            if len(item) >= 3
        ]

        for idx, page in enumerate(fitz_doc, start=1):
            try:
                imgs = page.get_images(full=False) or []
                per_page_visual_images[idx] = len(imgs)
            except Exception:
                per_page_visual_images[idx] = 0

        style_result = safe_style_extraction('pdf', lambda: extract_pdf_style_inventory(fitz_doc))
        if style_result:
            cosmos_meta['style_inventory'], pdf_page_style_lines = style_result
    except Exception as exc:
        log_event(
            f"[DOCUMENT_METADATA] PyMuPDF accessibility inspection warning: {type(exc).__name__}",
            level=20,
            debug_only=True,
        )
    finally:
        if fitz_doc is not None:
            try:
                fitz_doc.close()
            except Exception:
                # Ignore errors when closing the PyMuPDF document handle.
                pass

    # 2. Inspect Catalog, /MarkInfo, /StructTreeRoot, /AcroForm, and page dictionaries via pypdf
    try:
        reader = PdfReader(pdf_path)
        if not cosmos_meta['page_count']:
            cosmos_meta['page_count'] = len(reader.pages)

        if not cosmos_meta['title'] and getattr(reader, 'metadata', None):
            pypdf_title = _pdf_str(reader.metadata.get('/Title'))
            if pypdf_title:
                cosmos_meta['title'] = pypdf_title
                cosmos_meta['title_present'] = True

        root_catalog = _safe_deref(reader.trailer.get('/Root')) if reader.trailer else None
        if hasattr(root_catalog, 'get'):
            lang_val = _pdf_str(root_catalog.get('/Lang'))
            if lang_val:
                cosmos_meta['language'] = lang_val

            mark_info = _safe_deref(root_catalog.get('/MarkInfo'))
            if hasattr(mark_info, 'get'):
                cosmos_meta['is_tagged'] = _pdf_bool(mark_info.get('/Marked'))
                cosmos_meta['suspects'] = _pdf_bool(mark_info.get('/Suspects'))

            viewer_prefs = _safe_deref(root_catalog.get('/ViewerPreferences'))
            if hasattr(viewer_prefs, 'get'):
                cosmos_meta['display_doc_title'] = _pdf_bool(viewer_prefs.get('/DisplayDocTitle'))

            struct_root = _safe_deref(root_catalog.get('/StructTreeRoot'))
            if struct_root is not None:
                cosmos_meta['has_struct_tree'] = True

            # Inspect /AcroForm fields
            acro_form = _safe_deref(root_catalog.get('/AcroForm'))
            if hasattr(acro_form, 'get'):
                fields = _safe_deref(acro_form.get('/Fields'))
                if isinstance(fields, list):
                    for field_ref in fields[:MAX_COSMOS_FORMS]:
                        field_obj = _safe_deref(field_ref)
                        if not hasattr(field_obj, 'get'):
                            continue
                        field_name = _pdf_str(field_obj.get('/T'))
                        field_type = _pdf_str(field_obj.get('/FT'))
                        tooltip_tu = _pdf_str(field_obj.get('/TU'))
                        ff_flags = _safe_deref(field_obj.get('/Ff'))
                        is_required = bool(isinstance(ff_flags, int) and (ff_flags & 2))
                        has_tu = bool(tooltip_tu.strip())
                        cosmos_meta['forms_summary']['total_fields'] += 1
                        if has_tu:
                            cosmos_meta['forms_summary']['with_tooltip'] += 1
                        else:
                            cosmos_meta['forms_summary']['missing_tooltip'] += 1
                        cosmos_meta['forms_summary']['items'].append({
                            'field_name': field_name,
                            'field_type': field_type,
                            'tooltip_tu': tooltip_tu,
                            'has_tooltip': has_tu,
                            'is_required': is_required,
                        })
        else:
            struct_root = None

        page_map = _build_pdf_page_id_map(reader)

        # Inspect per-page /Tabs, /Artifact in content streams, and /Link or /Widget annotations
        structure_order_pages = 0
        non_structure_pages = []
        total_artifact_blocks = 0
        pages_with_artifacts = []
        link_annot_count = 0

        for page_idx, page in enumerate(reader.pages, start=1):
            page_obj = _safe_deref(page)
            tabs_val = _pdf_str(page_obj.get('/Tabs')) if hasattr(page_obj, 'get') else ''
            if tabs_val == 'S':
                structure_order_pages += 1
            else:
                non_structure_pages.append(page_idx)

            artifact_count = 0
            try:
                contents = page.get_contents()
                if contents is not None:
                    raw_bytes = contents.get_data() if hasattr(contents, 'get_data') else b''
                    artifact_count = len(_ARTIFACT_PATTERN.findall(raw_bytes))
            except Exception:
                artifact_count = 0

            if artifact_count > 0:
                total_artifact_blocks += artifact_count
                pages_with_artifacts.append(page_idx)

            page_widgets = []
            try:
                raw_annots = _safe_deref(page_obj.get('/Annots')) if hasattr(page_obj, 'get') else None
                if isinstance(raw_annots, list):
                    for annot_ref in raw_annots[:200]:
                        annot_obj = _safe_deref(annot_ref)
                        if not hasattr(annot_obj, 'get'):
                            continue
                        subtype = _pdf_str(annot_obj.get('/Subtype'))
                        if subtype == 'Link':
                            link_annot_count += 1
                        elif subtype == 'Widget':
                            w_name = _pdf_str(annot_obj.get('/T'))
                            w_tu = _pdf_str(annot_obj.get('/TU'))
                            page_widgets.append({
                                'field_name': w_name,
                                'tooltip_tu': w_tu,
                                'has_tooltip': bool(w_tu.strip()),
                            })
            except Exception:
                # Ignore malformed page /Annots entries and continue inspecting remaining pages.
                pass

            per_page_details[page_idx] = {
                'page_number': page_idx,
                'annotations': annotations_by_page.get(page_idx, []),
                'tabs_order': tabs_val or 'unset',
                'artifact_count': artifact_count,
                'visual_image_count': per_page_visual_images.get(page_idx, 0),
                'form_widgets': page_widgets,
                'tag_nodes': [],
                'formatting_line': pdf_page_style_lines.get(page_idx, ''),
                'formatted_accessibility_block': '',
            }

        cosmos_meta['page_tabs_order'] = {
            'structure_order_pages': structure_order_pages,
            'non_structure_pages': non_structure_pages[:100],
        }
        cosmos_meta['artifacts_summary'] = {
            'total_artifact_blocks': total_artifact_blocks,
            'pages_with_artifacts': pages_with_artifacts[:200],
        }
        cosmos_meta['links_summary']['link_annotations'] = link_annot_count

        # Walk /StructTreeRoot if present
        if struct_root is not None:
            tree_data = _walk_pdf_struct_tree(struct_root, page_map)
            cosmos_meta['tag_counts'] = dict(tree_data['tag_counts'])
            cosmos_meta['raw_tag_node_count'] = tree_data['raw_node_count']
            cosmos_meta['coalesced_span_count'] = tree_data['coalesced_span_count']
            cosmos_meta['heading_outline'] = tree_data['headings'][:MAX_COSMOS_HEADINGS]
            cosmos_meta['lists_summary'] = tree_data['lists']
            cosmos_meta['links_summary']['tagged_links'] = len(tree_data['links'])

            all_semantic = tree_data['semantic_nodes']
            cosmos_meta['semantic_tag_tree'] = all_semantic[:MAX_COSMOS_SEMANTIC_NODES]
            cosmos_meta['semantic_tag_tree_truncated'] = len(all_semantic) > MAX_COSMOS_SEMANTIC_NODES

            # Figures summary
            figs = tree_data['figures']
            with_alt = sum(1 for f in figs if f.get('has_alt'))
            missing_alt = len(figs) - with_alt
            total_visual_imgs = sum(per_page_visual_images.values())
            untagged_imgs = max(0, total_visual_imgs - len(figs)) if not cosmos_meta['is_tagged'] else 0
            cosmos_meta['figures_summary'] = {
                'total': len(figs),
                'with_alt': with_alt,
                'missing_alt': missing_alt,
                'untagged_images': untagged_imgs,
                'items': figs[:MAX_COSMOS_FIGURES],
            }

            # Tables summary
            tbls = tree_data['tables']
            tbl_with_hdr = sum(1 for t in tbls if t.get('has_headers'))
            cosmos_meta['tables_summary'] = {
                'total': len(tbls),
                'with_headers': tbl_with_hdr,
                'missing_headers': len(tbls) - tbl_with_hdr,
                'items': tbls[:MAX_COSMOS_TABLES],
            }

            # Attach per-page tag nodes to per_page_details
            for p_num, p_nodes in tree_data['per_page_nodes'].items():
                if p_num in per_page_details:
                    per_page_details[p_num]['tag_nodes'] = p_nodes
        else:
            total_visual_imgs = sum(per_page_visual_images.values())
            cosmos_meta['figures_summary']['untagged_images'] = total_visual_imgs

    except Exception as exc:
        log_event(
            f"[DOCUMENT_METADATA] pypdf accessibility extraction warning: {type(exc).__name__}",
            level=20,
            debug_only=True,
        )

    # 3. Synthesize actionable PDF accessibility issues
    issues = []
    if not cosmos_meta['is_tagged'] or not cosmos_meta['has_struct_tree']:
        issues.append({
            'code': 'PDF_UNTAGGED',
            'severity': 'high',
            'message': 'PDF is not tagged (/MarkInfo/Marked is false or /StructTreeRoot is missing); screen readers cannot determine reading order or semantic structure.',
        })
    if cosmos_meta['suspects']:
        issues.append({
            'code': 'PDF_TAG_SUSPECTS',
            'severity': 'medium',
            'message': 'PDF /MarkInfo/Suspects is true, indicating suspected tag order or structure inaccuracies.',
        })
    if not cosmos_meta['language']:
        issues.append({
            'code': 'PDF_MISSING_LANGUAGE',
            'severity': 'high',
            'message': 'Document catalog is missing primary language metadata (/Lang).',
        })
    if not cosmos_meta['title_present']:
        issues.append({
            'code': 'PDF_MISSING_TITLE',
            'severity': 'medium',
            'message': 'Document metadata is missing a Title (/Title).',
        })
    elif not cosmos_meta['display_doc_title']:
        issues.append({
            'code': 'PDF_DISPLAY_DOC_TITLE_DISABLED',
            'severity': 'low',
            'message': '/ViewerPreferences/DisplayDocTitle is not enabled; assistive technology may announce the file name instead of the document title.',
        })
    if cosmos_meta['page_count'] >= 5 and not cosmos_meta['has_bookmarks']:
        issues.append({
            'code': 'PDF_MISSING_BOOKMARKS',
            'severity': 'low',
            'message': f"Multi-page PDF ({cosmos_meta['page_count']} pages) has no bookmarks/outlines (/Outlines) for navigation.",
        })

    # Heading hierarchy checks
    headings = cosmos_meta['heading_outline']
    if cosmos_meta['has_struct_tree'] and not headings:
        issues.append({
            'code': 'PDF_NO_HEADINGS',
            'severity': 'medium',
            'message': 'Tagged PDF contains no heading tags (<H>, <H1>-<H6>).',
        })
    else:
        prev_level = 0
        skipped_pages = []
        for h in headings:
            lvl = h.get('level')
            if isinstance(lvl, int):
                if prev_level > 0 and lvl > prev_level + 1:
                    skipped_pages.append(f"H{prev_level}->H{lvl}" + (f" (p.{h.get('page_number')})" if h.get('page_number') else ''))
                prev_level = lvl
        if skipped_pages:
            issues.append({
                'code': 'PDF_SKIPPED_HEADING_LEVELS',
                'severity': 'medium',
                'message': f"Heading hierarchy skips levels: {', '.join(skipped_pages[:10])}.",
            })

    # Figures missing alt text
    if cosmos_meta['figures_summary']['missing_alt'] > 0:
        missing_pages = sorted({
            f.get('page_number') for f in cosmos_meta['figures_summary']['items']
            if not f.get('has_alt') and f.get('page_number') is not None
        })
        page_str = f" on page(s) {', '.join(str(p) for p in missing_pages[:20])}" if missing_pages else ''
        issues.append({
            'code': 'PDF_FIGURES_MISSING_ALT',
            'severity': 'high',
            'message': f"{cosmos_meta['figures_summary']['missing_alt']} tagged <Figure> element(s) are missing /Alt or /ActualText{page_str}.",
        })
    if cosmos_meta['figures_summary']['untagged_images'] > 0 and not cosmos_meta['is_tagged']:
        issues.append({
            'code': 'PDF_UNTAGGED_IMAGES',
            'severity': 'high',
            'message': f"{cosmos_meta['figures_summary']['untagged_images']} visual image(s) detected in an untagged PDF without <Figure> tags or /Alt text.",
        })

    # Tables missing headers
    if cosmos_meta['tables_summary']['missing_headers'] > 0:
        missing_tbl_pages = sorted({
            t.get('page_number') for t in cosmos_meta['tables_summary']['items']
            if not t.get('has_headers') and t.get('page_number') is not None
        })
        page_str = f" on page(s) {', '.join(str(p) for p in missing_tbl_pages[:20])}" if missing_tbl_pages else ''
        issues.append({
            'code': 'PDF_TABLES_MISSING_HEADERS',
            'severity': 'high',
            'message': f"{cosmos_meta['tables_summary']['missing_headers']} <Table> structure(s) have no <TH> header cells or /Headers mapping{page_str}.",
        })

    # Form fields missing /TU tooltip
    if cosmos_meta['forms_summary']['missing_tooltip'] > 0:
        issues.append({
            'code': 'PDF_FORMS_MISSING_TOOLTIP',
            'severity': 'high',
            'message': f"{cosmos_meta['forms_summary']['missing_tooltip']} interactive form field(s) are missing /TU accessible tooltip descriptions.",
        })

    non_embedded_fonts = (cosmos_meta.get('style_inventory') or {}).get('non_embedded_fonts') or []
    if non_embedded_fonts:
        issues.append({
            'code': 'PDF_FONTS_NOT_EMBEDDED',
            'severity': 'low',
            'message': (
                f"{len(non_embedded_fonts)} font(s) are not embedded ({', '.join(non_embedded_fonts[:8])}); "
                "assistive technology and PDF/UA require fonts to be embedded so text maps reliably to characters."
            ),
        })

    cosmos_meta['issues'] = issues[:MAX_COSMOS_ISSUES]

    # 4. Build per-page inline accessibility & tag-tree Markdown blocks
    for page_num, page_detail in per_page_details.items():
        page_detail['formatted_accessibility_block'] = format_pdf_page_accessibility_block(
            page_num, page_detail, cosmos_meta
        )

    return cosmos_meta, per_page_details


def format_pdf_page_accessibility_block(page_number, page_detail, doc_a11y_meta=None):
    """Format a PDF page's exact tag tree, reading order, figures, tables, forms, and artifacts."""
    if not isinstance(page_detail, dict):
        return ''

    lines = [f"### Page Accessibility & Tag Structure (Page {page_number})"]

    if isinstance(doc_a11y_meta, dict) and page_number == 1:
        tagged_str = 'Yes' if doc_a11y_meta.get('is_tagged') else 'No (Untagged PDF)'
        lang_str = doc_a11y_meta.get('language') or 'Missing (/Lang not set)'
        title_str = doc_a11y_meta.get('title') or 'Missing (/Title not set)'
        disp_title = 'Yes' if doc_a11y_meta.get('display_doc_title') else 'No'
        lines.append(
            f"- Document Accessibility Status: Tagged={tagged_str}; Language={lang_str}; "
            f"Title={title_str} (DisplayDocTitle={disp_title}); "
            f"Bookmarks={doc_a11y_meta.get('bookmark_count', 0)}"
        )

    tabs_order = page_detail.get('tabs_order') or 'unset'
    artifact_count = page_detail.get('artifact_count', 0)
    visual_imgs = page_detail.get('visual_image_count', 0)
    lines.append(
        f"- Page {page_number} Properties: TabOrder=/{tabs_order}; "
        f"ArtifactBlocks={artifact_count}; VisualImages={visual_imgs}"
    )

    tag_nodes = page_detail.get('tag_nodes') or []
    if tag_nodes:
        sequence_tokens = []
        figure_notes = []
        for idx, node in enumerate(tag_nodes[:MAX_PAGE_TAG_ITEMS], start=1):
            tag_name = node.get('tag') or 'StructElem'
            extras = []
            if node.get('scope'):
                extras.append(f"scope={node['scope']}")
            if node.get('col_span'):
                extras.append(f"colspan={node['col_span']}")
            if node.get('row_span'):
                extras.append(f"rowspan={node['row_span']}")
            if node.get('lang'):
                extras.append(f"lang={node['lang']}")
            if node.get('alt'):
                alt_preview = str(node['alt']).replace('\n', ' ').strip()[:120]
                extras.append(f'alt="{alt_preview}"')
            elif tag_name == 'Figure':
                extras.append('alt=MISSING')
            if node.get('actual_text'):
                act_preview = str(node['actual_text']).replace('\n', ' ').strip()[:80]
                extras.append(f'actual="{act_preview}"')

            token = f"<{tag_name}" + (f" {' '.join(extras)}" if extras else '') + ">"
            sequence_tokens.append(token)
            if tag_name == 'Figure':
                alt_status = f'Alt="{node.get("alt")}"' if node.get('alt') else 'MISSING /Alt'
                figure_notes.append(f"Figure #{idx}: {alt_status}")

        if len(tag_nodes) > MAX_PAGE_TAG_ITEMS:
            sequence_tokens.append(f"... (+{len(tag_nodes) - MAX_PAGE_TAG_ITEMS} more tags)")

        lines.append(f"- Page {page_number} Tag Reading Order: {' -> '.join(sequence_tokens)}")
        if figure_notes:
            lines.append(f"- Page {page_number} Tagged Figures: {'; '.join(figure_notes)}")
    else:
        if isinstance(doc_a11y_meta, dict) and not doc_a11y_meta.get('is_tagged'):
            lines.append(f"- Page {page_number} Tag Reading Order: None (PDF is untagged)")

    widgets = page_detail.get('form_widgets') or []
    if widgets:
        w_parts = []
        for w in widgets[:25]:
            name = w.get('field_name') or 'unnamed_field'
            tu = f'TU="{w.get("tooltip_tu")}"' if w.get('has_tooltip') else 'MISSING /TU tooltip'
            w_parts.append(f"{name} ({tu})")
        lines.append(f"- Page {page_number} Form Fields: {'; '.join(w_parts)}")

    if page_detail.get('formatting_line'):
        lines.append(f"- Page {page_number} {page_detail['formatting_line']}")

    return '\n'.join(lines)


def _relative_luminance(hex_color):
    """Calculate WCAG 2.1 relative luminance for a 6-digit hex color string."""
    clean = str(hex_color or '').strip().lstrip('#')
    if len(clean) != 6 or not all(c in '0123456789abcdefABCDEF' for c in clean):
        return None
    r = int(clean[0:2], 16) / 255.0
    g = int(clean[2:4], 16) / 255.0
    b = int(clean[4:6], 16) / 255.0

    def _channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def compute_wcag_contrast_ratio(fg_hex, bg_hex):
    """Return WCAG contrast ratio between two 6-digit hex colors, or None if invalid."""
    lum1 = _relative_luminance(fg_hex)
    lum2 = _relative_luminance(bg_hex)
    if lum1 is None or lum2 is None:
        return None
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def _extract_ooxml_core_properties(archive):
    """Extract core metadata from ``docProps/core.xml``."""
    props = {
        'title': '',
        'authors': [],
        'subject': '',
        'keywords': [],
        'description': '',
        'language': '',
        'category': '',
    }
    core_bytes = _read_zip_entry_bounded(archive, 'docProps/core.xml', OFFICE_EMBEDDED_RELS_MAX_BYTES)
    if core_bytes is None:
        return props

    try:
        root = defused_fromstring(core_bytes)
    except (DefusedParseError, ValueError):
        return props

    for elem in root:
        local = _xml_local_name(elem.tag)
        text = str(elem.text or '').strip()
        if not text:
            continue
        if local == 'title':
            props['title'] = text
        elif local == 'creator':
            props['authors'] = [a.strip() for a in re.split(r'[;,]', text) if a.strip()]
        elif local == 'subject':
            props['subject'] = text
        elif local == 'keywords':
            props['keywords'] = [k.strip() for k in re.split(r'[;,]', text) if k.strip()]
        elif local == 'description':
            props['description'] = text
        elif local == 'language':
            props['language'] = text
        elif local == 'category':
            props['category'] = text

    return props


def _extract_word_default_language(archive):
    """Extract default proofing/document language from ``word/styles.xml`` or ``word/theme/theme1.xml``."""
    styles_bytes = _read_zip_entry_bounded(archive, 'word/styles.xml', OFFICE_DOCUMENT_PART_MAX_BYTES)
    if styles_bytes is not None:
        try:
            styles_root = defused_fromstring(styles_bytes)
            for elem in styles_root.iter():
                if _xml_local_name(elem.tag) == 'lang':
                    val = (
                        _xml_attr_by_local_name(elem, 'val')
                        or _xml_attr_by_local_name(elem, 'eastAsia')
                        or _xml_attr_by_local_name(elem, 'bidi')
                    )
                    if val:
                        return val.strip()
        except (DefusedParseError, ValueError):
            # Fall back to theme1.xml when styles.xml cannot be parsed.
            pass

    theme_bytes = _read_zip_entry_bounded(archive, 'word/theme/theme1.xml', OFFICE_EMBEDDED_RELS_MAX_BYTES)
    if theme_bytes is not None:
        try:
            theme_root = defused_fromstring(theme_bytes)
            for elem in theme_root.iter():
                if _xml_local_name(elem.tag) == 'fontScheme':
                    lang = _xml_attr_by_local_name(elem, 'lang')
                    if lang:
                        return lang.strip()
        except (DefusedParseError, ValueError):
            # Ignore malformed theme XML and return empty language fallback.
            pass

    return ''


def _build_word_Relationship_map(archive, rels_path=DOCX_MAIN_DOCUMENT_RELS_PART):
    """Return mapping of relationship Id -> dict(target, type, target_mode)."""
    rel_map = {}
    rels_bytes = _read_zip_entry_bounded(archive, rels_path, OFFICE_EMBEDDED_RELS_MAX_BYTES)
    if rels_bytes is None:
        return rel_map
    try:
        rels_root = defused_fromstring(rels_bytes)
    except (DefusedParseError, ValueError):
        return rel_map

    for rel in rels_root:
        r_id = str(rel.attrib.get('Id') or '').strip()
        if not r_id:
            continue
        rel_map[r_id] = {
            'target': str(rel.attrib.get('Target') or '').strip(),
            'type': str(rel.attrib.get('Type') or '').strip(),
            'target_mode': str(rel.attrib.get('TargetMode') or '').strip(),
        }
    return rel_map


def _inspect_drawing_element(drawing_elem, rel_map, word_offset=None, slide_number=None):
    """Extract accessibility metadata (alt text, title, decorative flag, placement, overlap) from an OOXML drawing/shape."""
    figures = []
    containers = []

    for child in drawing_elem.iter():
        local = _xml_local_name(child.tag)
        if local in ('inline', 'anchor'):
            containers.append((local, child))

    if not containers:
        containers = [('shape', drawing_elem)]

    for container_type, container in containers:
        placement = 'floating' if container_type == 'anchor' else 'inline'
        allow_overlap = _xml_attr_by_local_name(container, 'allowOverlap') in ('1', 'true')
        behind_doc = _xml_attr_by_local_name(container, 'behindDoc') in ('1', 'true')

        doc_pr = None
        is_decorative = False
        media_target = ''
        object_kind = 'image'

        for node in container.iter():
            n_local = _xml_local_name(node.tag)
            if n_local in ('docPr', 'cNvPr') and doc_pr is None:
                doc_pr = node
            elif n_local == 'decorative':
                val = _xml_attr_by_local_name(node, 'val').lower()
                if val in ('1', 'true', ''):
                    is_decorative = True
            elif n_local == 'blip':
                embed_id = _xml_attr_by_local_name(node, 'embed')
                if embed_id and embed_id in rel_map:
                    media_target = rel_map[embed_id].get('target', '')
            elif n_local == 'chart':
                object_kind = 'chart'
            elif n_local == 'relIds':
                object_kind = 'smartart'

        if doc_pr is None:
            continue

        descr = _xml_attr_by_local_name(doc_pr, 'descr').strip()
        title = _xml_attr_by_local_name(doc_pr, 'title').strip()
        name = _xml_attr_by_local_name(doc_pr, 'name').strip()
        hidden = _xml_attr_by_local_name(doc_pr, 'hidden') in ('1', 'true')

        has_alt = bool(descr or title or is_decorative)
        figures.append({
            'name': name or os.path.basename(media_target) or object_kind,
            'kind': object_kind,
            'media_target': media_target,
            'alt_text': descr,
            'title': title,
            'is_decorative': is_decorative,
            'has_alt': has_alt,
            'placement': placement,
            'allow_overlap': allow_overlap,
            'behind_doc': behind_doc,
            'hidden': hidden,
            'word_offset': word_offset,
            'slide_number': slide_number,
        })

    return figures


def extract_pptx_comments(file_path):
    """Extract classic and modern PowerPoint slide comments mapped by 1-based slide_number.

    Returns:
        dict: Mapping ``slide_number (int) -> list[dict]`` of slide comments.
    """
    comments_by_slide = {}
    if not file_path or not zipfile.is_zipfile(file_path):
        return comments_by_slide

    try:
        with zipfile.ZipFile(file_path) as archive:
            entry_names = archive.namelist()
            if len(entry_names) > OFFICE_ZIP_MAX_ENTRIES:
                return comments_by_slide

            # 1. Parse classic commentAuthors.xml if present
            authors_by_id = {}
            if 'ppt/commentAuthors.xml' in entry_names:
                auth_bytes = _read_zip_entry_bounded(
                    archive, 'ppt/commentAuthors.xml', OFFICE_EMBEDDED_RELS_MAX_BYTES
                )
                if auth_bytes:
                    try:
                        auth_root = defused_fromstring(auth_bytes)
                        for elem in auth_root.iter():
                            if _xml_local_name(elem.tag) == 'cmAuthor':
                                a_id = _xml_attr_by_local_name(elem, 'id')
                                a_name = _xml_attr_by_local_name(elem, 'name')
                                a_init = _xml_attr_by_local_name(elem, 'initials')
                                if a_id:
                                    authors_by_id[a_id] = {'name': a_name, 'initials': a_init}
                    except (DefusedParseError, ValueError):
                        # Ignore malformed commentAuthors.xml and continue with inline comment attributes.
                        pass

            # 2. Map slide_number -> comment XML paths from ppt/slides/_rels/slideN.xml.rels
            slide_comment_targets = {}
            for entry_name in entry_names:
                m = _PPTX_SLIDE_RELS_XML_PATTERN.match(entry_name)
                if not m:
                    continue
                slide_num = int(m.group(1))
                rels_bytes = _read_zip_entry_bounded(archive, entry_name, OFFICE_EMBEDDED_RELS_MAX_BYTES)
                if not rels_bytes:
                    continue
                try:
                    rels_root = defused_fromstring(rels_bytes)
                except (DefusedParseError, ValueError):
                    continue
                for rel in rels_root:
                    target = str(rel.attrib.get('Target') or '').replace('\\', '/')
                    if 'comment' not in target.lower():
                        continue
                    segments = [s for s in ('ppt/slides/' + target).split('/') if s not in ('', '.')]
                    resolved = []
                    for seg in segments:
                        if seg == '..':
                            if resolved:
                                resolved.pop()
                        else:
                            resolved.append(seg)
                    part_path = '/'.join(resolved)
                    if part_path in entry_names:
                        slide_comment_targets.setdefault(slide_num, []).append(part_path)

            # Fallback if comments are named ppt/comments/commentN.xml without rels
            if not slide_comment_targets:
                for entry_name in entry_names:
                    cm_match = re.match(r'^ppt/comments/(?:modern)?comment(\d+)\.xml$', entry_name, re.IGNORECASE)
                    if cm_match:
                        slide_comment_targets.setdefault(int(cm_match.group(1)), []).append(entry_name)

            # 3. Parse each slide's comment part(s)
            for slide_num, part_paths in sorted(slide_comment_targets.items()):
                slide_items = []
                for part_path in part_paths:
                    cm_bytes = _read_zip_entry_bounded(archive, part_path, OFFICE_EMBEDDED_RELS_MAX_BYTES)
                    if not cm_bytes:
                        continue
                    try:
                        cm_root = defused_fromstring(cm_bytes)
                    except (DefusedParseError, ValueError):
                        continue

                    for elem in cm_root.iter():
                        local = _xml_local_name(elem.tag)
                        if local not in ('cm', 'comment'):
                            continue
                        author_id = _xml_attr_by_local_name(elem, 'authorId')
                        author_info = authors_by_id.get(author_id, {})
                        author = _xml_attr_by_local_name(elem, 'author') or author_info.get('name') or ''
                        initials = _xml_attr_by_local_name(elem, 'initials') or author_info.get('initials') or ''
                        date_str = _xml_attr_by_local_name(elem, 'dt', 'created', 'date')
                        status = _xml_attr_by_local_name(elem, 'status')

                        text_fragments = []
                        for sub in elem.iter():
                            if _xml_local_name(sub.tag) in ('t', 'text') and sub.text:
                                text_fragments.append(str(sub.text).strip())
                        comment_text = ' '.join(t for t in text_fragments if t).strip()
                        if not comment_text:
                            continue

                        slide_items.append({
                            'slide_number': slide_num,
                            'author': author,
                            'initials': initials,
                            'date': date_str,
                            'done': status.lower() in ('resolved', 'done', 'closed') if status else False,
                            'text': comment_text,
                        })

                if slide_items:
                    comments_by_slide[slide_num] = slide_items
    except Exception:
        return comments_by_slide

    return comments_by_slide


def format_pptx_comment_block(comment, index=None, total=None):
    """Format a PowerPoint slide comment as an inline Markdown block."""
    if not isinstance(comment, dict):
        return ''
    text = str(comment.get('text') or '').strip()
    if not text:
        return ''

    if index is not None and total is not None:
        number_label = f" {index} of {total}"
    elif index is not None:
        number_label = f" {index}"
    else:
        number_label = ''

    author = str(comment.get('author') or '').strip()
    initials = str(comment.get('initials') or '').strip()
    date_str = str(comment.get('date') or '').strip()
    done = bool(comment.get('done'))

    meta_parts = []
    if author and initials and initials.lower() != author.lower():
        meta_parts.append(f"by {author} ({initials})")
    elif author:
        meta_parts.append(f"by {author}")
    elif initials:
        meta_parts.append(f"by {initials}")
    if date_str:
        meta_parts.append(f"[{date_str}]")
    if done:
        meta_parts.append("(Resolved)")

    meta_suffix = (' ' + ' '.join(meta_parts)) if meta_parts else ''
    return f"### Slide comment{number_label}{meta_suffix}\n{text}"


def _extract_word_ooxml_accessibility(file_path, file_ext):
    """Extract accessibility and structural metadata from a Word OOXML package (.docx, .docm, .dotx)."""
    cosmos_meta = {
        'format': file_ext.lstrip('.') or 'docx',
        'schema_version': '1.0',
        'language': '',
        'title': '',
        'title_present': False,
        'authors': [],
        'subject': '',
        'keywords': [],
        'total_body_words': 0,
        'style_counts': {},
        'heading_outline': [],
        'pseudo_headings': [],
        'lists_summary': {'structured_list_items': 0, 'manual_bullet_paragraphs': 0},
        'tables_summary': {
            'total': 0,
            'with_header_row': 0,
            'missing_header_row': 0,
            'with_merged_cells': 0,
            'nested_tables': 0,
            'items': [],
        },
        'figures_summary': {
            'total': 0,
            'with_alt': 0,
            'decorative': 0,
            'missing_alt': 0,
            'floating_objects': 0,
            'overlapping_objects': 0,
            'items': [],
        },
        'links_summary': {
            'total': 0,
            'with_screentip': 0,
            'generic_link_text': 0,
            'items': [],
        },
        'forms_summary': {'content_controls': 0, 'legacy_form_fields': 0, 'unlabeled_controls': 0},
        'formatting_and_layout': {
            'hidden_text_runs': 0,
            'hidden_text_samples': [],
            'textbox_count': 0,
            'low_contrast_runs': 0,
            'low_contrast_samples': [],
        },
        'issues': [],
    }
    structural_events = []

    with zipfile.ZipFile(file_path) as archive:
        entry_names = archive.namelist()
        if len(entry_names) > OFFICE_ZIP_MAX_ENTRIES:
            return cosmos_meta, structural_events

        core_props = _extract_ooxml_core_properties(archive)
        cosmos_meta['title'] = core_props['title']
        cosmos_meta['title_present'] = bool(core_props['title'])
        cosmos_meta['authors'] = core_props['authors']
        cosmos_meta['subject'] = core_props['subject']
        cosmos_meta['keywords'] = core_props['keywords']
        cosmos_meta['language'] = core_props['language'] or _extract_word_default_language(archive)

        rel_map = _build_word_Relationship_map(archive)
        doc_bytes = _read_zip_entry_bounded(archive, DOCX_MAIN_DOCUMENT_PART, OFFICE_DOCUMENT_PART_MAX_BYTES)
        if doc_bytes is None:
            return cosmos_meta, structural_events

        try:
            doc_root = defused_fromstring(doc_bytes)
        except (DefusedParseError, ValueError):
            return cosmos_meta, structural_events

        body_elem = None
        for child in doc_root:
            if _xml_local_name(child.tag) == 'body':
                body_elem = child
                break
        if body_elem is None:
            body_elem = doc_root

        word_count = 0
        style_counts = Counter()

        for elem in body_elem:
            local = _xml_local_name(elem.tag)
            if local == 'p':
                p_style = 'Normal'
                outline_lvl = None
                has_num_pr = False

                for p_child in elem:
                    if _xml_local_name(p_child.tag) == 'pPr':
                        for pr in p_child:
                            pr_local = _xml_local_name(pr.tag)
                            if pr_local == 'pStyle':
                                p_style = _xml_attr_by_local_name(pr, 'val') or 'Normal'
                            elif pr_local == 'outlineLvl':
                                raw_lvl = _xml_attr_by_local_name(pr, 'val')
                                if raw_lvl.isdigit():
                                    outline_lvl = int(raw_lvl) + 1
                            elif pr_local == 'numPr':
                                has_num_pr = True

                style_counts[p_style] += 1

                # Inspect runs, text, drawings, hyperlinks, hidden text, and colors
                para_text_parts = []
                bold_chars = 0
                total_chars = 0
                max_font_half_pts = 0

                for node in elem.iter():
                    n_local = _xml_local_name(node.tag)
                    if n_local == 't' and node.text:
                        para_text_parts.append(str(node.text))
                    elif n_local == 'r':
                        r_text = ''.join(
                            str(sub.text) for sub in node.iter()
                            if _xml_local_name(sub.tag) == 't' and sub.text
                        ).strip()
                        r_bold = False
                        r_vanish = False
                        r_color = ''
                        r_shd = ''
                        r_sz = 0
                        for sub in node:
                            if _xml_local_name(sub.tag) == 'rPr':
                                for rpr_item in sub:
                                    rpr_local = _xml_local_name(rpr_item.tag)
                                    if rpr_local == 'b':
                                        b_val = _xml_attr_by_local_name(rpr_item, 'val').lower()
                                        if b_val not in ('0', 'false'):
                                            r_bold = True
                                    elif rpr_local == 'vanish':
                                        v_val = _xml_attr_by_local_name(rpr_item, 'val').lower()
                                        if v_val not in ('0', 'false'):
                                            r_vanish = True
                                    elif rpr_local == 'color':
                                        r_color = _xml_attr_by_local_name(rpr_item, 'val')
                                    elif rpr_local == 'shd':
                                        r_shd = _xml_attr_by_local_name(rpr_item, 'fill')
                                    elif rpr_local == 'sz':
                                        sz_val = _xml_attr_by_local_name(rpr_item, 'val')
                                        if sz_val.isdigit():
                                            r_sz = int(sz_val)
                        if r_text:
                            total_chars += len(r_text)
                            if r_bold:
                                bold_chars += len(r_text)
                            if r_sz > max_font_half_pts:
                                max_font_half_pts = r_sz
                            if r_vanish:
                                cosmos_meta['formatting_and_layout']['hidden_text_runs'] += 1
                                if len(cosmos_meta['formatting_and_layout']['hidden_text_samples']) < 10:
                                    cosmos_meta['formatting_and_layout']['hidden_text_samples'].append(r_text[:100])
                            if r_color and r_color.lower() != 'auto':
                                bg_hex = r_shd if (r_shd and r_shd.lower() != 'auto') else 'FFFFFF'
                                ratio = compute_wcag_contrast_ratio(r_color, bg_hex)
                                min_ratio = 3.0 if r_sz >= 36 else 4.5
                                if ratio is not None and ratio < min_ratio:
                                    cosmos_meta['formatting_and_layout']['low_contrast_runs'] += 1
                                    if len(cosmos_meta['formatting_and_layout']['low_contrast_samples']) < 15:
                                        cosmos_meta['formatting_and_layout']['low_contrast_samples'].append({
                                            'text': r_text[:80],
                                            'foreground': f"#{r_color.lstrip('#')}",
                                            'background': f"#{bg_hex.lstrip('#')}",
                                            'contrast_ratio': ratio,
                                            'word_offset': word_count,
                                        })
                    elif n_local == 'drawing':
                        figs = _inspect_drawing_element(node, rel_map, word_offset=word_count)
                        for fig in figs:
                            cosmos_meta['figures_summary']['total'] += 1
                            if fig['is_decorative']:
                                cosmos_meta['figures_summary']['decorative'] += 1
                            if fig['has_alt']:
                                cosmos_meta['figures_summary']['with_alt'] += 1
                            else:
                                cosmos_meta['figures_summary']['missing_alt'] += 1
                            if fig['placement'] == 'floating':
                                cosmos_meta['figures_summary']['floating_objects'] += 1
                            if fig['allow_overlap']:
                                cosmos_meta['figures_summary']['overlapping_objects'] += 1
                            if len(cosmos_meta['figures_summary']['items']) < MAX_COSMOS_FIGURES:
                                cosmos_meta['figures_summary']['items'].append(fig)
                            structural_events.append({
                                'word_offset': word_count,
                                'kind': 'figure',
                                'summary': (
                                    f"Figure '{fig['name']}' ({fig['placement']}"
                                    + (", overlap-enabled" if fig['allow_overlap'] else "")
                                    + "): "
                                    + (
                                        "Decorative=true"
                                        if fig['is_decorative']
                                        else (f'Alt="{fig["alt_text"] or fig["title"]}"' if fig['has_alt'] else "MISSING Alt Text")
                                    )
                                ),
                            })
                    elif n_local == 'txbxContent':
                        cosmos_meta['formatting_and_layout']['textbox_count'] += 1
                    elif n_local == 'hyperlink':
                        r_id = _xml_attr_by_local_name(node, 'id')
                        tooltip = _xml_attr_by_local_name(node, 'tooltip').strip()
                        link_text = ''.join(
                            str(sub.text) for sub in node.iter()
                            if _xml_local_name(sub.tag) == 't' and sub.text
                        ).strip()
                        target_url = rel_map.get(r_id, {}).get('target', '') if r_id else ''
                        is_generic = (
                            link_text.lower() in GENERIC_LINK_TEXTS
                            or link_text.lower().startswith(('http://', 'https://'))
                        )
                        cosmos_meta['links_summary']['total'] += 1
                        if tooltip:
                            cosmos_meta['links_summary']['with_screentip'] += 1
                        if is_generic:
                            cosmos_meta['links_summary']['generic_link_text'] += 1
                        if len(cosmos_meta['links_summary']['items']) < MAX_COSMOS_LINKS:
                            cosmos_meta['links_summary']['items'].append({
                                'text': link_text[:120],
                                'target': target_url[:200],
                                'tooltip': tooltip[:120],
                                'is_generic_text': is_generic,
                                'word_offset': word_count,
                            })
                    elif n_local == 'sdt':
                        cosmos_meta['forms_summary']['content_controls'] += 1
                        has_label = False
                        for sub in node:
                            if _xml_local_name(sub.tag) == 'sdtPr':
                                for pr_sub in sub:
                                    if _xml_local_name(pr_sub.tag) in ('alias', 'tag') and _xml_attr_by_local_name(pr_sub, 'val'):
                                        has_label = True
                        if not has_label:
                            cosmos_meta['forms_summary']['unlabeled_controls'] += 1
                    elif n_local == 'ffData':
                        cosmos_meta['forms_summary']['legacy_form_fields'] += 1

                para_text = re.sub(r'\s+', ' ', ''.join(para_text_parts)).strip()
                para_words = len(para_text.split()) if para_text else 0

                # Classify heading vs pseudo-heading vs list
                heading_level = outline_lvl
                style_lower = p_style.lower()
                if heading_level is None and style_lower.startswith('heading'):
                    digits = ''.join(ch for ch in style_lower if ch.isdigit())
                    heading_level = int(digits) if digits else 1
                elif heading_level is None and style_lower == 'title':
                    heading_level = 1

                if heading_level is not None and para_text:
                    cosmos_meta['heading_outline'].append({
                        'level': heading_level,
                        'style': p_style,
                        'text': para_text[:160],
                        'word_offset': word_count,
                    })
                    structural_events.append({
                        'word_offset': word_count,
                        'kind': 'heading',
                        'summary': f"<H{heading_level} ({p_style})> {para_text[:100]}",
                    })
                elif para_text and not has_num_pr and 0 < len(para_text) <= 100:
                    is_all_bold = total_chars > 0 and bold_chars == total_chars
                    is_large_font = max_font_half_pts >= 28
                    if (is_all_bold or is_large_font) and style_lower in ('normal', 'bodytext', 'defaultparagraphfont'):
                        cosmos_meta['pseudo_headings'].append({
                            'text': para_text[:120],
                            'style': p_style,
                            'all_bold': is_all_bold,
                            'font_pt': max_font_half_pts / 2.0 if max_font_half_pts else None,
                            'word_offset': word_count,
                        })
                        structural_events.append({
                            'word_offset': word_count,
                            'kind': 'pseudo_heading',
                            'summary': f"Pseudo-heading (Normal style with visual bold/size instead of Heading style): \"{para_text[:80]}\"",
                        })

                if has_num_pr:
                    cosmos_meta['lists_summary']['structured_list_items'] += 1
                elif heading_level is None and para_text and _MANUAL_BULLET_PATTERN.match(para_text):
                    cosmos_meta['lists_summary']['manual_bullet_paragraphs'] += 1

                word_count += para_words

            elif local == 'tbl':
                row_count = 0
                has_tbl_header = False
                merged_cells = 0
                nested_tables = 0
                tbl_caption = ''
                tbl_descr = ''

                for t_child in elem:
                    tc_local = _xml_local_name(t_child.tag)
                    if tc_local == 'tblPr':
                        for pr in t_child:
                            pr_local = _xml_local_name(pr.tag)
                            if pr_local == 'tblCaption':
                                tbl_caption = _xml_attr_by_local_name(pr, 'val')
                            elif pr_local == 'tblDescription':
                                tbl_descr = _xml_attr_by_local_name(pr, 'val')
                    elif tc_local == 'tr':
                        row_count += 1
                        for tr_child in t_child:
                            trc_local = _xml_local_name(tr_child.tag)
                            if trc_local == 'trPr':
                                for pr in tr_child:
                                    if _xml_local_name(pr.tag) == 'tblHeader':
                                        val = _xml_attr_by_local_name(pr, 'val').lower()
                                        if val not in ('0', 'false'):
                                            has_tbl_header = True
                            elif trc_local == 'tc':
                                for tc_sub in tr_child:
                                    sub_local = _xml_local_name(tc_sub.tag)
                                    if sub_local == 'tcPr':
                                        for pr in tc_sub:
                                            if _xml_local_name(pr.tag) in ('gridSpan', 'vMerge'):
                                                merged_cells += 1
                                    elif sub_local == 'tbl':
                                        nested_tables += 1

                tbl_words = sum(
                    len(str(t.text or '').split())
                    for t in elem.iter()
                    if _xml_local_name(t.tag) == 't' and t.text
                )
                cosmos_meta['tables_summary']['total'] += 1
                if has_tbl_header:
                    cosmos_meta['tables_summary']['with_header_row'] += 1
                else:
                    cosmos_meta['tables_summary']['missing_header_row'] += 1
                if merged_cells > 0:
                    cosmos_meta['tables_summary']['with_merged_cells'] += 1
                if nested_tables > 0:
                    cosmos_meta['tables_summary']['nested_tables'] += nested_tables

                table_entry = {
                    'table_index': cosmos_meta['tables_summary']['total'],
                    'row_count': row_count,
                    'has_header_row': has_tbl_header,
                    'merged_cell_count': merged_cells,
                    'nested_table_count': nested_tables,
                    'caption': tbl_caption,
                    'description': tbl_descr,
                    'word_offset': word_count,
                }
                if len(cosmos_meta['tables_summary']['items']) < MAX_COSMOS_TABLES:
                    cosmos_meta['tables_summary']['items'].append(table_entry)

                structural_events.append({
                    'word_offset': word_count,
                    'kind': 'table',
                    'summary': (
                        f"Table #{table_entry['table_index']} ({row_count} rows): "
                        f"HeaderRow(w:tblHeader)={'Yes' if has_tbl_header else 'MISSING'}; "
                        f"MergedCells={merged_cells}; NestedTables={nested_tables}"
                    ),
                })
                word_count += tbl_words

        cosmos_meta['total_body_words'] = word_count
        cosmos_meta['style_counts'] = dict(style_counts)
        cosmos_meta['heading_outline'] = cosmos_meta['heading_outline'][:MAX_COSMOS_HEADINGS]
        cosmos_meta['pseudo_headings'] = cosmos_meta['pseudo_headings'][:50]

        word_style_result = safe_style_extraction(
            'word',
            lambda: build_word_style_inventory(
                archive, body_elem, style_counts, word_chunk_bucket_size(word_count)
            ),
        )
        if word_style_result:
            cosmos_meta['style_inventory'], formatting_events = word_style_result
            structural_events[:0] = formatting_events
    # Synthesize Word accessibility issues
    issues = []
    if not cosmos_meta['title_present']:
        issues.append({
            'code': 'OFFICE_MISSING_TITLE',
            'severity': 'medium',
            'message': 'Document core properties are missing a Title (dc:title).',
        })
    if not cosmos_meta['language']:
        issues.append({
            'code': 'OFFICE_MISSING_LANGUAGE',
            'severity': 'medium',
            'message': 'Document does not declare a primary proofing/content language.',
        })
    if not cosmos_meta['heading_outline'] and cosmos_meta['total_body_words'] > 100:
        issues.append({
            'code': 'OFFICE_NO_HEADINGS',
            'severity': 'high',
            'message': 'Document has no semantic Heading styles (Heading 1-6 / outlineLvl).',
        })
    else:
        prev_lvl = 0
        skips = []
        for h in cosmos_meta['heading_outline']:
            lvl = h.get('level')
            if isinstance(lvl, int):
                if prev_lvl > 0 and lvl > prev_lvl + 1:
                    skips.append(f"H{prev_lvl}->H{lvl} ('{h.get('text', '')[:40]}')")
                prev_lvl = lvl
        if skips:
            issues.append({
                'code': 'OFFICE_SKIPPED_HEADING_LEVELS',
                'severity': 'medium',
                'message': f"Heading hierarchy skips levels: {', '.join(skips[:8])}.",
            })

    if cosmos_meta['pseudo_headings']:
        samples = [f"\"{p['text'][:40]}\"" for p in cosmos_meta['pseudo_headings'][:5]]
        issues.append({
            'code': 'OFFICE_PSEUDO_HEADINGS',
            'severity': 'medium',
            'message': (
                f"{len(cosmos_meta['pseudo_headings'])} paragraph(s) use visual bold/font-size formatting on "
                f"Normal style instead of semantic Heading styles (e.g. {', '.join(samples)})."
            ),
        })
    if cosmos_meta['lists_summary']['manual_bullet_paragraphs'] > 0:
        issues.append({
            'code': 'OFFICE_MANUAL_LISTS',
            'severity': 'low',
            'message': f"{cosmos_meta['lists_summary']['manual_bullet_paragraphs']} paragraph(s) use manually typed bullet/number characters instead of structured list styles (w:numPr).",
        })
    if cosmos_meta['tables_summary']['missing_header_row'] > 0:
        issues.append({
            'code': 'OFFICE_TABLES_MISSING_HEADER_ROW',
            'severity': 'high',
            'message': f"{cosmos_meta['tables_summary']['missing_header_row']} of {cosmos_meta['tables_summary']['total']} table(s) do not have a designated repeat header row (w:tblHeader).",
        })
    if cosmos_meta['tables_summary']['with_merged_cells'] > 0:
        issues.append({
            'code': 'OFFICE_TABLES_MERGED_CELLS',
            'severity': 'medium',
            'message': f"{cosmos_meta['tables_summary']['with_merged_cells']} table(s) contain merged cells (w:gridSpan / w:vMerge) or nested tables that complicate screen-reader table navigation.",
        })
    if cosmos_meta['figures_summary']['missing_alt'] > 0:
        issues.append({
            'code': 'OFFICE_FIGURES_MISSING_ALT',
            'severity': 'high',
            'message': f"{cosmos_meta['figures_summary']['missing_alt']} embedded image(s)/object(s) are missing alternative text (wp:docPr/@descr) and are not marked decorative.",
        })
    if cosmos_meta['figures_summary']['floating_objects'] > 0:
        issues.append({
            'code': 'OFFICE_FLOATING_OBJECTS',
            'severity': 'medium',
            'message': (
                f"{cosmos_meta['figures_summary']['floating_objects']} object(s) use floating anchor placement (wp:anchor) "
                f"instead of inline placement ({cosmos_meta['figures_summary']['overlapping_objects']} allow overlap), "
                "which can cause reading-order and visual overlap issues."
            ),
        })
    if cosmos_meta['links_summary']['generic_link_text'] > 0:
        issues.append({
            'code': 'OFFICE_GENERIC_LINK_TEXT',
            'severity': 'low',
            'message': f"{cosmos_meta['links_summary']['generic_link_text']} hyperlink(s) use generic or raw-URL display text without descriptive context.",
        })
    if cosmos_meta['formatting_and_layout']['hidden_text_runs'] > 0:
        issues.append({
            'code': 'OFFICE_HIDDEN_TEXT',
            'severity': 'medium',
            'message': f"Document contains {cosmos_meta['formatting_and_layout']['hidden_text_runs']} hidden text run(s) (w:vanish).",
        })
    if cosmos_meta['formatting_and_layout']['low_contrast_runs'] > 0:
        issues.append({
            'code': 'OFFICE_LOW_COLOR_CONTRAST',
            'severity': 'high',
            'message': f"{cosmos_meta['formatting_and_layout']['low_contrast_runs']} text run(s) have explicit foreground/background hex colors below WCAG AA contrast thresholds.",
        })

    cosmos_meta['issues'] = issues[:MAX_COSMOS_ISSUES]
    return cosmos_meta, structural_events


def _extract_pptx_accessibility(file_path):
    """Extract accessibility and structural metadata from a PowerPoint (.pptx) package."""
    cosmos_meta = {
        'format': 'pptx',
        'schema_version': '1.0',
        'language': '',
        'title': '',
        'title_present': False,
        'authors': [],
        'subject': '',
        'keywords': [],
        'slide_count': 0,
        'slides_missing_titles': [],
        'slides_with_reading_order_warnings': [],
        'figures_summary': {
            'total': 0,
            'with_alt': 0,
            'decorative': 0,
            'missing_alt': 0,
            'overlapping_shapes': 0,
            'items': [],
        },
        'tables_summary': {
            'total': 0,
            'with_header_row': 0,
            'missing_header_row': 0,
            'with_merged_cells': 0,
            'items': [],
        },
        'comments_summary': {'total_comments': 0, 'slides_with_comments': []},
        'issues': [],
    }
    per_slide_details = {}

    if not file_path or not zipfile.is_zipfile(file_path):
        return cosmos_meta, per_slide_details

    comments_by_slide = extract_pptx_comments(file_path)
    cosmos_meta['comments_summary'] = {
        'total_comments': sum(len(v) for v in comments_by_slide.values()),
        'slides_with_comments': sorted(comments_by_slide.keys()),
    }

    with zipfile.ZipFile(file_path) as archive:
        entry_names = archive.namelist()
        if len(entry_names) > OFFICE_ZIP_MAX_ENTRIES:
            return cosmos_meta, per_slide_details

        core_props = _extract_ooxml_core_properties(archive)
        cosmos_meta['title'] = core_props['title']
        cosmos_meta['title_present'] = bool(core_props['title'])
        cosmos_meta['authors'] = core_props['authors']
        cosmos_meta['subject'] = core_props['subject']
        cosmos_meta['keywords'] = core_props['keywords']
        cosmos_meta['language'] = core_props['language']

        slide_entries = []
        for name in entry_names:
            m = _PPTX_SLIDE_XML_PATTERN.match(name)
            if m:
                slide_entries.append((int(m.group(1)), name))
        slide_entries.sort(key=lambda item: item[0])
        cosmos_meta['slide_count'] = len(slide_entries)

        for slide_num, slide_path in slide_entries:
            slide_bytes = _read_zip_entry_bounded(archive, slide_path, OFFICE_DOCUMENT_PART_MAX_BYTES)
            if slide_bytes is None:
                continue
            try:
                slide_root = defused_fromstring(slide_bytes)
            except (DefusedParseError, ValueError):
                continue

            rels_path = f"ppt/slides/_rels/slide{slide_num}.xml.rels"
            rel_map = _build_word_Relationship_map(archive, rels_path=rels_path)

            slide_title = ''
            z_order_shapes = []
            slide_figures = []
            slide_tables = []

            for elem in slide_root.iter():
                local = _xml_local_name(elem.tag)
                if local == 'lang' and not cosmos_meta['language']:
                    lang_val = _xml_attr_by_local_name(elem, 'val')
                    if lang_val:
                        cosmos_meta['language'] = lang_val

                if local == 'sp':
                    is_title_ph = False
                    shape_name = ''
                    y_pos = None
                    for sub in elem.iter():
                        s_local = _xml_local_name(sub.tag)
                        if s_local == 'cNvPr' and not shape_name:
                            shape_name = _xml_attr_by_local_name(sub, 'name')
                        elif s_local == 'ph':
                            ph_type = _xml_attr_by_local_name(sub, 'type').lower()
                            if ph_type in ('title', 'ctrtitle'):
                                is_title_ph = True
                        elif s_local == 'off' and y_pos is None:
                            raw_y = _xml_attr_by_local_name(sub, 'y')
                            if raw_y.lstrip('-').isdigit():
                                y_pos = int(raw_y)
                    shape_text = ' '.join(
                        str(t.text).strip() for t in elem.iter()
                        if _xml_local_name(t.tag) == 't' and t.text and str(t.text).strip()
                    ).strip()
                    if is_title_ph and shape_text and not slide_title:
                        slide_title = shape_text[:160]
                    if shape_text:
                        z_order_shapes.append({'name': shape_name or 'Shape', 'text': shape_text[:80], 'y': y_pos})

                elif local in ('pic', 'graphicFrame'):
                    figs = _inspect_drawing_element(elem, rel_map, slide_number=slide_num)
                    for fig in figs:
                        cosmos_meta['figures_summary']['total'] += 1
                        if fig['is_decorative']:
                            cosmos_meta['figures_summary']['decorative'] += 1
                        if fig['has_alt']:
                            cosmos_meta['figures_summary']['with_alt'] += 1
                        else:
                            cosmos_meta['figures_summary']['missing_alt'] += 1
                        if len(cosmos_meta['figures_summary']['items']) < MAX_COSMOS_FIGURES:
                            cosmos_meta['figures_summary']['items'].append(fig)
                        slide_figures.append(fig)

                elif local == 'tbl':
                    first_row_hdr = _xml_attr_by_local_name(elem, 'firstRow') in ('1', 'true')
                    row_cnt = 0
                    merged_cnt = 0
                    for sub in elem:
                        if _xml_local_name(sub.tag) == 'tr':
                            row_cnt += 1
                            for tc in sub:
                                if _xml_local_name(tc.tag) == 'tc':
                                    if (
                                        _xml_attr_by_local_name(tc, 'gridSpan') not in ('', '1')
                                        or _xml_attr_by_local_name(tc, 'rowSpan') not in ('', '1')
                                        or _xml_attr_by_local_name(tc, 'hMerge') in ('1', 'true')
                                        or _xml_attr_by_local_name(tc, 'vMerge') in ('1', 'true')
                                    ):
                                        merged_cnt += 1
                    cosmos_meta['tables_summary']['total'] += 1
                    if first_row_hdr:
                        cosmos_meta['tables_summary']['with_header_row'] += 1
                    else:
                        cosmos_meta['tables_summary']['missing_header_row'] += 1
                    if merged_cnt > 0:
                        cosmos_meta['tables_summary']['with_merged_cells'] += 1
                    t_item = {
                        'slide_number': slide_num,
                        'row_count': row_cnt,
                        'has_header_row': first_row_hdr,
                        'merged_cell_count': merged_cnt,
                    }
                    slide_tables.append(t_item)
                    if len(cosmos_meta['tables_summary']['items']) < MAX_COSMOS_TABLES:
                        cosmos_meta['tables_summary']['items'].append(t_item)

            if not slide_title:
                cosmos_meta['slides_missing_titles'].append(slide_num)

            # Check if visual top-to-bottom order differs significantly from XML Z-order
            positioned = [s for s in z_order_shapes if isinstance(s.get('y'), int)]
            reading_order_warning = False
            if len(positioned) >= 2:
                y_values = [s['y'] for s in positioned]
                if y_values != sorted(y_values):
                    reading_order_warning = True
                    cosmos_meta['slides_with_reading_order_warnings'].append(slide_num)

            block_lines = [f"### Slide Accessibility & Structure (Slide {slide_num})"]
            block_lines.append(
                f"- Slide Title: {slide_title if slide_title else 'MISSING (No title placeholder text)'}"
            )
            if z_order_shapes:
                order_preview = ' -> '.join(
                    f"{s['name']}(\"{s['text'][:35]}\")" for s in z_order_shapes[:10]
                )
                block_lines.append(
                    f"- Screen Reader Shape Order (Z-Order): {order_preview}"
                    + (" [WARNING: Z-order differs from top-to-bottom visual placement]" if reading_order_warning else "")
                )
            if slide_figures:
                f_parts = []
                for f in slide_figures[:15]:
                    status = (
                        'Decorative=true'
                        if f['is_decorative']
                        else (f'Alt="{f["alt_text"] or f["title"]}"' if f['has_alt'] else 'MISSING Alt Text')
                    )
                    f_parts.append(f"{f['name']} ({status})")
                block_lines.append(f"- Slide Figures/Objects: {'; '.join(f_parts)}")
            if slide_tables:
                t_parts = [
                    f"Table ({t['row_count']} rows, HeaderRow={'Yes' if t['has_header_row'] else 'MISSING'}, MergedCells={t['merged_cell_count']})"
                    for t in slide_tables
                ]
                block_lines.append(f"- Slide Tables: {'; '.join(t_parts)}")

            per_slide_details[slide_num] = {
                'slide_number': slide_num,
                'slide_title': slide_title,
                'comments': comments_by_slide.get(slide_num, []),
                'formatted_accessibility_block': '\n'.join(block_lines),
            }

        pptx_style_result = safe_style_extraction(
            'pptx', lambda: build_pptx_style_inventory(archive, slide_entries)
        )
        if pptx_style_result:
            cosmos_meta['style_inventory'], slide_style_lines = pptx_style_result
            for slide_num, style_line in slide_style_lines.items():
                slide_detail = per_slide_details.get(slide_num)
                if slide_detail:
                    slide_detail['formatted_accessibility_block'] += f"\n- {style_line}"
    issues = []
    if not cosmos_meta['title_present']:
        issues.append({
            'code': 'PPTX_MISSING_TITLE',
            'severity': 'medium',
            'message': 'Presentation core properties are missing a Title (dc:title).',
        })
    if cosmos_meta['slides_missing_titles']:
        issues.append({
            'code': 'PPTX_SLIDES_MISSING_TITLES',
            'severity': 'high',
            'message': f"Slide(s) {', '.join(str(s) for s in cosmos_meta['slides_missing_titles'][:25])} are missing slide title placeholders.",
        })
    if cosmos_meta['slides_with_reading_order_warnings']:
        issues.append({
            'code': 'PPTX_READING_ORDER_MISMATCH',
            'severity': 'medium',
            'message': f"Slide(s) {', '.join(str(s) for s in cosmos_meta['slides_with_reading_order_warnings'][:25])} have shape Z-order that differs from top-to-bottom visual order.",
        })
    if cosmos_meta['figures_summary']['missing_alt'] > 0:
        issues.append({
            'code': 'PPTX_FIGURES_MISSING_ALT',
            'severity': 'high',
            'message': f"{cosmos_meta['figures_summary']['missing_alt']} slide visual object(s) are missing alternative text and are not marked decorative.",
        })
    if cosmos_meta['tables_summary']['missing_header_row'] > 0:
        issues.append({
            'code': 'PPTX_TABLES_MISSING_HEADER',
            'severity': 'medium',
            'message': f"{cosmos_meta['tables_summary']['missing_header_row']} slide table(s) do not have firstRow header formatting enabled.",
        })

    cosmos_meta['issues'] = issues[:MAX_COSMOS_ISSUES]
    return cosmos_meta, per_slide_details


def _extract_legacy_doc_accessibility(file_path):
    """Extract basic metadata and accessibility signals from a legacy binary .doc OLE file."""
    cosmos_meta = {
        'format': 'doc',
        'schema_version': '1.0',
        'language': '',
        'title': '',
        'title_present': False,
        'authors': [],
        'subject': '',
        'keywords': [],
        'issues': [],
    }
    if not file_path or not os.path.exists(file_path):
        return cosmos_meta, []

    try:
        if olefile.isOleFile(file_path):
            with olefile.OleFileIO(file_path) as ole:
                meta = ole.get_metadata()
                title = meta.title.decode('utf-8', errors='replace').strip() if isinstance(meta.title, bytes) else str(meta.title or '').strip()
                author = meta.author.decode('utf-8', errors='replace').strip() if isinstance(meta.author, bytes) else str(meta.author or '').strip()
                subject = meta.subject.decode('utf-8', errors='replace').strip() if isinstance(meta.subject, bytes) else str(meta.subject or '').strip()
                keywords = meta.keywords.decode('utf-8', errors='replace').strip() if isinstance(meta.keywords, bytes) else str(meta.keywords or '').strip()
                cosmos_meta['title'] = title
                cosmos_meta['title_present'] = bool(title)
                if author:
                    cosmos_meta['authors'] = [a.strip() for a in re.split(r'[;,]', author) if a.strip()]
                cosmos_meta['subject'] = subject
                if keywords:
                    cosmos_meta['keywords'] = [k.strip() for k in re.split(r'[;,]', keywords) if k.strip()]
    except Exception:
        # Ignore unreadable OLE metadata streams and continue with structural heuristics.
        pass

    if not cosmos_meta['title_present']:
        cosmos_meta['issues'].append({
            'code': 'DOC_MISSING_TITLE',
            'severity': 'medium',
            'message': 'Legacy Word (.doc) SummaryInformation is missing a document Title.',
        })
    cosmos_meta['issues'].append({
        'code': 'DOC_LEGACY_BINARY_FORMAT',
        'severity': 'low',
        'message': 'Legacy binary Word 97-2003 (.doc) format lacks modern OOXML accessibility attributes (such as adec:decorative); consider converting to .docx for full accessibility tagging.',
    })

    def _legacy_doc_style():
        from functions_content import extract_legacy_doc_character_runs

        character_runs = extract_legacy_doc_character_runs(file_path)
        if not character_runs or not character_runs['runs']:
            return None
        total_words = character_runs['total_body_words']
        return total_words, build_legacy_doc_style_inventory(
            character_runs['runs'],
            word_chunk_bucket_size(total_words),
            character_runs['notes'],
        )

    style_outcome = safe_style_extraction('doc', _legacy_doc_style)
    if not style_outcome:
        return cosmos_meta, []
    total_words, (style_inventory, formatting_events) = style_outcome
    cosmos_meta['total_body_words'] = total_words
    cosmos_meta['style_inventory'] = style_inventory
    return cosmos_meta, formatting_events


def extract_office_accessibility_metadata(file_path, file_ext=None):
    """Dispatch Office accessibility extraction for .docx, .docm, .dotx, .pptx, and .doc."""
    ext = (file_ext or os.path.splitext(str(file_path or ''))[1]).lower().strip()
    try:
        if ext in ('.docx', '.docm', '.dotx'):
            return _extract_word_ooxml_accessibility(file_path, ext)
        if ext == '.pptx':
            return _extract_pptx_accessibility(file_path)
        if ext == '.doc':
            return _extract_legacy_doc_accessibility(file_path)
    except Exception as exc:
        log_event(
            f"[DOCUMENT_METADATA] Office accessibility extraction failed for {ext}: {type(exc).__name__}",
            level=30,
            debug_only=True,
        )
    return {'format': ext.lstrip('.'), 'schema_version': '1.0', 'issues': []}, []


def word_chunk_bucket_size(total_body_words):
    """Return the word-offset span that groups Word structural events into one chunk block."""
    total_words = max(total_body_words or 1, 1)
    return max(WORD_CHUNK_MIN_BUCKET_WORDS, total_words // WORD_CHUNK_BUCKET_DIVISOR)


def build_word_chunk_accessibility_items(cosmos_meta, structural_events):
    """Build position-anchored structural/accessibility blocks for Word chunks (using ``word_offset``).

    These items use the exact same ``{'content': ..., 'word_offset': ..., 'position_known': True}``
    contract as ``_build_word_comment_chunks`` so ``_merge_embedded_images_into_chunks`` places each
    structural summary inline in its matching AI Search chunk!
    """
    if not isinstance(cosmos_meta, dict) or not structural_events:
        return []

    grouped_by_bucket = {}
    # Group events into word spans so each chunk gets a single clean structural block
    bucket_size = word_chunk_bucket_size(cosmos_meta.get('total_body_words'))

    for ev in structural_events:
        offset = ev.get('word_offset') or 0
        bucket_idx = offset // bucket_size
        bucket_offset = bucket_idx * bucket_size
        grouped_by_bucket.setdefault(bucket_offset, []).append(ev.get('summary') or '')

    chunk_items = []
    for bucket_offset, summaries in sorted(grouped_by_bucket.items()):
        clean_summaries = [s for s in summaries if s][:20]
        if not clean_summaries:
            continue
        lines = ["### Section Accessibility & Structure"]
        for s in clean_summaries:
            lines.append(f"- {s}")
        chunk_items.append({
            'content': '\n'.join(lines),
            'word_offset': bucket_offset,
            'slide_number': None,
            'position_known': True,
        })

    return chunk_items


def format_accessibility_metadata_for_chat(accessibility_metadata):
    """Format parent Cosmos ``accessibility_metadata`` into a concise text block for chat RAG."""
    if not isinstance(accessibility_metadata, dict) or not accessibility_metadata:
        return ''

    fmt = str(accessibility_metadata.get('format') or '').upper()
    lines = [f"Document Accessibility & Structure Summary ({fmt or 'Document'}):"]

    if fmt == 'PDF':
        is_tagged = 'Yes' if accessibility_metadata.get('is_tagged') else 'No (Untagged PDF)'
        has_tree = 'Yes' if accessibility_metadata.get('has_struct_tree') else 'No'
        suspects = 'Yes' if accessibility_metadata.get('suspects') else 'No'
        lang = accessibility_metadata.get('language') or 'Missing (/Lang not set)'
        title = accessibility_metadata.get('title') or 'Missing (/Title not set)'
        disp_title = 'Yes' if accessibility_metadata.get('display_doc_title') else 'No'
        bookmarks = accessibility_metadata.get('bookmark_count', 0)
        lines.append(
            f"- Core PDF Accessibility: Tagged={is_tagged}; StructTreeRoot={has_tree}; "
            f"Suspects={suspects}; Language={lang}; Title=\"{title}\" (DisplayDocTitle={disp_title}); "
            f"Bookmarks={bookmarks}"
        )
        tabs = accessibility_metadata.get('page_tabs_order') or {}
        lines.append(
            f"- Page Tab Order (/Tabs /S): {tabs.get('structure_order_pages', 0)} page(s) set to Structure order; "
            f"{len(tabs.get('non_structure_pages') or [])} page(s) unset/non-structure."
        )
        tag_counts = accessibility_metadata.get('tag_counts') or {}
        if tag_counts:
            counts_str = ', '.join(f"{k}={v}" for k, v in sorted(tag_counts.items()))
            lines.append(f"- PDF Tag Counts: {counts_str}")
        artifacts = accessibility_metadata.get('artifacts_summary') or {}
        lines.append(
            f"- Artifacts (/Artifact): {artifacts.get('total_artifact_blocks', 0)} marked-content block(s) "
            f"across {len(artifacts.get('pages_with_artifacts') or [])} page(s)."
        )
    else:
        lang = accessibility_metadata.get('language') or 'Missing'
        title = accessibility_metadata.get('title') or 'Missing'
        lines.append(f"- Core Document Properties: Language={lang}; Title=\"{title}\"")
        style_counts = accessibility_metadata.get('style_counts') or {}
        if style_counts:
            counts_str = ', '.join(f"{k}={v}" for k, v in list(style_counts.items())[:15])
            lines.append(f"- Paragraph Styles Used: {counts_str}")
        if accessibility_metadata.get('slide_count'):
            lines.append(
                f"- Slides: {accessibility_metadata.get('slide_count')} total; "
                f"Missing Titles on slide(s): {accessibility_metadata.get('slides_missing_titles') or 'None'}; "
                f"Reading-Order Warnings on slide(s): {accessibility_metadata.get('slides_with_reading_order_warnings') or 'None'}"
            )

    headings = accessibility_metadata.get('heading_outline') or []
    if headings:
        h_preview = '; '.join(
            f"H{h.get('level') or '?'}: \"{str(h.get('text') or h.get('title') or '')[:50]}\""
            + (f" (p.{h['page_number']})" if h.get('page_number') else '')
            for h in headings[:20]
        )
        lines.append(f"- Heading Outline ({len(headings)} headings): {h_preview}")

    pseudo = accessibility_metadata.get('pseudo_headings') or []
    if pseudo:
        p_preview = ', '.join(f"\"{p.get('text', '')[:45]}\"" for p in pseudo[:8])
        lines.append(f"- Pseudo-Headings Detected ({len(pseudo)}): {p_preview}")

    figs = accessibility_metadata.get('figures_summary') or {}
    if figs:
        lines.append(
            f"- Figures/Embedded Objects: Total={figs.get('total', 0)}, "
            f"WithAlt={figs.get('with_alt', 0)}, Decorative={figs.get('decorative', 0)}, "
            f"MissingAlt={figs.get('missing_alt', 0)}, UntaggedImages={figs.get('untagged_images', 0)}, "
            f"Floating={figs.get('floating_objects', 0)}"
        )

    tbls = accessibility_metadata.get('tables_summary') or {}
    if tbls:
        with_hdr = tbls.get('with_headers', tbls.get('with_header_row', 0))
        miss_hdr = tbls.get('missing_headers', tbls.get('missing_header_row', 0))
        lines.append(
            f"- Tables: Total={tbls.get('total', 0)}, WithHeaders={with_hdr}, "
            f"MissingHeaders={miss_hdr}, WithMergedCells={tbls.get('with_merged_cells', 0)}"
        )

    forms = accessibility_metadata.get('forms_summary') or {}
    if forms.get('total_fields') or forms.get('content_controls') or forms.get('legacy_form_fields'):
        lines.append(
            f"- Forms/Controls: PDF_Fields={forms.get('total_fields', 0)} "
            f"(MissingTooltip={forms.get('missing_tooltip', 0)}), "
            f"Word_ContentControls={forms.get('content_controls', 0)} "
            f"(Unlabeled={forms.get('unlabeled_controls', 0)})"
        )

    fmt_layout = accessibility_metadata.get('formatting_and_layout') or {}
    if fmt_layout:
        lines.append(
            f"- Formatting & Layout Cues: HiddenTextRuns={fmt_layout.get('hidden_text_runs', 0)}, "
            f"TextBoxes={fmt_layout.get('textbox_count', 0)}, "
            f"LowContrastRuns={fmt_layout.get('low_contrast_runs', 0)}"
        )

    lines.extend(format_style_inventory_for_chat(accessibility_metadata.get('style_inventory')))

    issues = accessibility_metadata.get('issues') or []
    if issues:
        lines.append(f"- Detected Accessibility Issues ({len(issues)}):")
        for issue in issues[:25]:
            lines.append(f"  * [{str(issue.get('severity') or 'info').upper()}] {issue.get('code')}: {issue.get('message')}")
    else:
        lines.append("- Detected Accessibility Issues: None flagged by structural parser.")

    return '\n'.join(lines)
