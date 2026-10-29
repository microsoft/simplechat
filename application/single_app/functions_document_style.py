# functions_document_style.py
"""Font, size, colour, and layout (style) extraction for uploaded documents.

Accessibility review and house-style checks need visual formatting data that text extraction and
Azure AI services do not expose. This module reads it natively from each file format:

- PDF: PyMuPDF text spans (font, size, colour, flags), embedded-font status, page size, text margins.
- Word (.docx/.docm/.dotx): run properties resolved through the paragraph/character style chain,
  document defaults, and the theme; alignment, line spacing, and section page setup.
- PowerPoint (.pptx): run properties resolved through the shape, layout, master, and presentation
  defaults and the theme.

Every extractor aggregates into a ``StyleAccumulator`` so the stored result is bounded:

1. A ``style_inventory`` dict for the parent Cosmos ``accessibility_metadata`` record (font, size,
   and colour histograms, body font/size, minimum size, page setup, layout, and a capped list of
   outlier runs with their location).
2. A compact ``Formatting:`` line per page / slide / section that is merged inline into the matching
   Azure AI Search chunk so page-targeted questions get styling together with content.

Legacy binary ``.doc`` files are handled in ``functions_content.py`` (best effort) and feed the same
accumulator.
"""

import posixpath
import re
import zipfile
from collections import Counter

import fitz
from defusedxml.ElementTree import ParseError as DefusedParseError
from defusedxml.ElementTree import fromstring as defused_fromstring

from functions_appinsights import log_event
from functions_office_media import (
    OFFICE_DOCUMENT_PART_MAX_BYTES,
    OFFICE_EMBEDDED_RELS_MAX_BYTES,
    _read_zip_entry_bounded,
    _xml_attr_by_local_name,
    _xml_local_name,
)


STYLE_INVENTORY_SCHEMA_VERSION = '1.0'
MAX_STYLE_FONTS = 25
MAX_STYLE_SIZES = 40
MAX_STYLE_COLORS = 25
MAX_STYLE_OUTLIERS = 100
MAX_STYLE_PARAGRAPH_STYLES = 60
MAX_STYLE_TRACKED_RUNS = 20000
MAX_STYLE_PDF_PAGES = 300
MAX_STYLE_PAGE_SETUPS = 10
STYLE_SIZE_TOLERANCE_PT = 0.5
STYLE_SECTION_TOP_ITEMS = 3
STYLE_SNIPPET_CHARS = 60
STYLE_DEFAULT_WORD_FONT_SIZE_PT = 10.0
STYLE_DEFAULT_PPTX_FONT_SIZE_PT = 18.0

_PDF_SUBSET_PREFIX = re.compile(r'^[A-Z]{6}\+')
_FONT_STYLE_SUFFIX = re.compile(
    r'[-,]\s*(?:Bold|Italic|Oblique|Regular|Roman|Medium|Light|Black|Semibold|Condensed|MT|PSMT|PS)+$',
    re.IGNORECASE,
)
_HEX_COLOR_PATTERN = re.compile(r'^[0-9A-Fa-f]{6}$')

_THEME_COLOR_ALIASES = {
    'text1': 'dk1', 'dark1': 'dk1', 'tx1': 'dk1', 'dk1': 'dk1',
    'background1': 'lt1', 'light1': 'lt1', 'bg1': 'lt1', 'lt1': 'lt1',
    'text2': 'dk2', 'dark2': 'dk2', 'tx2': 'dk2', 'dk2': 'dk2',
    'background2': 'lt2', 'light2': 'lt2', 'bg2': 'lt2', 'lt2': 'lt2',
    'accent1': 'accent1', 'accent2': 'accent2', 'accent3': 'accent3',
    'accent4': 'accent4', 'accent5': 'accent5', 'accent6': 'accent6',
    'hyperlink': 'hlink', 'hlink': 'hlink',
    'followedhyperlink': 'folHlink', 'folhlink': 'folHlink',
}

_ALIGNMENT_LABELS = {
    'left': 'left', 'start': 'left',
    'right': 'right', 'end': 'right',
    'center': 'center',
    'both': 'justified', 'distribute': 'justified', 'justify': 'justified', 'thaidistribute': 'justified',
}


def normalize_font_family(name):
    """Return a font family key without PDF subset prefixes or weight/style suffixes."""
    cleaned = _PDF_SUBSET_PREFIX.sub('', str(name or '').strip())
    cleaned = _FONT_STYLE_SUFFIX.sub('', cleaned).strip()
    return cleaned


def _round_pt(value):
    """Round a point size to the nearest half point; return ``None`` when unknown."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    rounded = round(number * 2) / 2
    return int(rounded) if rounded == int(rounded) else rounded


def _format_pt(value):
    return f"{value}pt" if value is not None else 'unknown'


def _hex_color(raw_value):
    """Normalize a 6-digit hex string to ``#RRGGBB``; return ``None`` when it is not a colour."""
    candidate = str(raw_value or '').strip().lstrip('#')
    if _HEX_COLOR_PATTERN.match(candidate):
        return f"#{candidate.upper()}"
    return None


class StyleAccumulator:
    """Aggregate text runs into bounded font/size/colour statistics keyed by page/slide/word offset."""

    def __init__(self, location_key):
        self.location_key = location_key
        self.fonts = Counter()
        self.sizes = Counter()
        self.colors = Counter()
        self.total_chars = 0
        self.bold_chars = 0
        self.italic_chars = 0
        self.underline_chars = 0
        self.unresolved_font_chars = 0
        self.unresolved_size_chars = 0
        self.runs_dropped = 0
        self.alignment_paragraphs = Counter()
        self.line_spacing_paragraphs = Counter()
        self._sections = {}
        self._runs = {}

    def add(self, location, text, font=None, size_pt=None, color=None, bold=False, italic=False, underline=False):
        """Record one run of text. Whitespace-only runs are ignored."""
        stripped = str(text or '').strip()
        chars = len(re.sub(r'\s+', '', stripped))
        if not chars:
            return

        size = _round_pt(size_pt)
        font = str(font or '').strip() or None
        color = str(color or '').strip() or None

        self.total_chars += chars
        if font:
            self.fonts[font] += chars
        else:
            self.unresolved_font_chars += chars
        if size is not None:
            self.sizes[size] += chars
        else:
            self.unresolved_size_chars += chars
        if color:
            self.colors[color] += chars
        if bold:
            self.bold_chars += chars
        if italic:
            self.italic_chars += chars
        if underline:
            self.underline_chars += chars

        section = self._sections.setdefault(
            location, {'fonts': Counter(), 'sizes': Counter(), 'colors': Counter()}
        )
        if font:
            section['fonts'][font] += chars
        if size is not None:
            section['sizes'][size] += chars
        if color:
            section['colors'][color] += chars

        run_key = (location, font, size, color)
        entry = self._runs.get(run_key)
        if entry is not None:
            entry[0] += chars
        elif len(self._runs) < MAX_STYLE_TRACKED_RUNS:
            self._runs[run_key] = [chars, stripped[:STYLE_SNIPPET_CHARS]]
        else:
            self.runs_dropped += 1

    def add_paragraph_layout(self, alignment=None, line_spacing=None):
        if alignment:
            self.alignment_paragraphs[_ALIGNMENT_LABELS.get(str(alignment).lower(), str(alignment).lower())] += 1
        if line_spacing:
            self.line_spacing_paragraphs[line_spacing] += 1

    def section_summaries(self, key_fn=None):
        """Return ``{section_key: 'Formatting: ...'}``; ``key_fn`` can merge locations into buckets."""
        merged = {}
        for location, data in self._sections.items():
            key = key_fn(location) if key_fn else location
            target = merged.setdefault(key, {'fonts': Counter(), 'sizes': Counter(), 'colors': Counter()})
            target['fonts'].update(data['fonts'])
            target['sizes'].update(data['sizes'])
            target['colors'].update(data['colors'])

        summaries = {}
        for key, data in merged.items():
            line = format_section_formatting_line(data['fonts'], data['sizes'], data['colors'])
            if line:
                summaries[key] = line
        return summaries

    def _body_values(self):
        body_font = self.fonts.most_common(1)[0][0] if self.fonts else None
        body_size = self.sizes.most_common(1)[0][0] if self.sizes else None
        return body_font, body_size

    def build_inventory(self, coverage='full', notes=None, page_setup=None, extra=None):
        """Build the bounded ``style_inventory`` dict stored on the parent Cosmos record."""
        body_font, body_size = self._body_values()
        total = max(self.total_chars, 1)

        outlier_runs = []
        for (location, font, size, color), (chars, snippet) in self._runs.items():
            reasons = []
            if body_font and font and font != body_font:
                reasons.append('font_differs_from_body')
            if body_size is not None and size is not None and size < body_size - STYLE_SIZE_TOLERANCE_PT:
                reasons.append('smaller_than_body')
            if reasons:
                outlier_runs.append((chars, location, font, size, color, snippet, reasons))

        outlier_count = len(outlier_runs)
        truncated = outlier_count > MAX_STYLE_OUTLIERS
        outlier_runs.sort(key=lambda item: item[0], reverse=True)
        selected = sorted(
            outlier_runs[:MAX_STYLE_OUTLIERS],
            key=lambda item: (item[1] if isinstance(item[1], (int, float)) else 0),
        )
        outliers = [
            {
                self.location_key: location,
                'text': snippet,
                'font': font,
                'size_pt': size,
                'color': color,
                'chars': chars,
                'reasons': reasons,
            }
            for chars, location, font, size, color, snippet, reasons in selected
        ]

        notes = list(notes or [])
        if self.runs_dropped:
            notes.append(
                f"Outlier detection sampled the first {MAX_STYLE_TRACKED_RUNS} distinct run styles; "
                f"{self.runs_dropped} further run(s) are counted in the histograms only."
            )
        if self.unresolved_size_chars or self.unresolved_font_chars:
            coverage = 'partial'
            notes.append(
                f"{self.unresolved_font_chars} character(s) had no resolvable font and "
                f"{self.unresolved_size_chars} had no resolvable size."
            )

        inventory = {
            'schema_version': STYLE_INVENTORY_SCHEMA_VERSION,
            'coverage': coverage,
            'coverage_notes': notes,
            'total_text_chars': self.total_chars,
            'body_font': body_font,
            'body_size_pt': body_size,
            'min_size_pt': min(self.sizes) if self.sizes else None,
            'max_size_pt': max(self.sizes) if self.sizes else None,
            'font_count': len(self.fonts),
            'fonts': [
                {'name': name, 'chars': count, 'percent': round(100.0 * count / total, 1)}
                for name, count in self.fonts.most_common(MAX_STYLE_FONTS)
            ],
            'font_sizes': [
                {'size_pt': size, 'chars': count, 'percent': round(100.0 * count / total, 1)}
                for size, count in sorted(self.sizes.items())[:MAX_STYLE_SIZES]
            ],
            'colors': [
                {'color': color, 'chars': count, 'percent': round(100.0 * count / total, 1)}
                for color, count in self.colors.most_common(MAX_STYLE_COLORS)
            ],
            'emphasis': {
                'bold_chars': self.bold_chars,
                'italic_chars': self.italic_chars,
                'underline_chars': self.underline_chars,
            },
            'outlier_run_count': outlier_count,
            'outliers_truncated': truncated,
            'outliers': outliers,
        }
        if self.alignment_paragraphs or self.line_spacing_paragraphs:
            inventory['layout'] = {
                'alignment_paragraphs': dict(self.alignment_paragraphs),
                'line_spacing_paragraphs': dict(self.line_spacing_paragraphs.most_common(10)),
            }
        if page_setup:
            inventory['page_setup'] = page_setup
        if extra:
            inventory.update(extra)
        return inventory


def _top_items(counter, formatter):
    return ', '.join(
        f"{formatter(key)} ({count})" for key, count in counter.most_common(STYLE_SECTION_TOP_ITEMS)
    )


def format_section_formatting_line(fonts, sizes, colors):
    """Format one compact ``Formatting:`` line for a page, slide, or section chunk."""
    parts = []
    if fonts:
        parts.append(f"Fonts={_top_items(fonts, str)}")
    if sizes:
        parts.append(f"Sizes={_top_items(sizes, _format_pt)}")
        parts.append(f"MinSize={_format_pt(min(sizes))}")
    if colors:
        parts.append(f"Colors={_top_items(colors, str)}")
    if not parts:
        return ''
    return 'Formatting (characters): ' + '; '.join(parts)


def format_style_inventory_for_chat(style_inventory):
    """Format ``style_inventory`` into concise chat-context lines (empty list when unavailable)."""
    if not isinstance(style_inventory, dict) or not style_inventory.get('total_text_chars'):
        return []

    lines = []
    fonts = style_inventory.get('fonts') or []
    font_preview = ', '.join(f"{f['name']} {f['percent']}%" for f in fonts[:5])
    sizes = style_inventory.get('font_sizes') or []
    size_preview = ', '.join(
        f"{_format_pt(s['size_pt'])} {s['percent']}%"
        for s in sorted(sizes, key=lambda item: item.get('chars', 0), reverse=True)[:5]
    )
    colors = style_inventory.get('colors') or []
    color_preview = ', '.join(f"{c['color']} {c['percent']}%" for c in colors[:5])

    lines.append(
        f"- Formatting & Style (coverage={style_inventory.get('coverage', 'unknown')}): "
        f"BodyFont={style_inventory.get('body_font') or 'unknown'}; "
        f"BodySize={_format_pt(style_inventory.get('body_size_pt'))}; "
        f"MinSize={_format_pt(style_inventory.get('min_size_pt'))}; "
        f"MaxSize={_format_pt(style_inventory.get('max_size_pt'))}; "
        f"DistinctFonts={style_inventory.get('font_count', 0)}"
    )
    if font_preview:
        lines.append(f"  * Fonts by share of text: {font_preview}")
    if size_preview:
        lines.append(f"  * Font sizes by share of text: {size_preview}")
    if color_preview:
        lines.append(f"  * Text colours by share of text: {color_preview}")

    layout = style_inventory.get('layout') or {}
    if layout.get('alignment_paragraphs'):
        align_str = ', '.join(f"{k}={v}" for k, v in layout['alignment_paragraphs'].items())
        lines.append(f"  * Paragraph alignment: {align_str}")

    page_setup = style_inventory.get('page_setup') or {}
    page_sizes = page_setup.get('page_sizes') or page_setup.get('sections') or []
    if page_sizes:
        first = page_sizes[0]
        lines.append(
            f"  * Page setup: {first.get('page_width_pt')}x{first.get('page_height_pt')}pt"
            + (f" ({first.get('pages')} page(s))" if first.get('pages') else '')
        )

    non_embedded = style_inventory.get('non_embedded_fonts') or []
    if non_embedded:
        lines.append(f"  * Fonts not embedded: {', '.join(non_embedded[:8])}")

    outlier_count = style_inventory.get('outlier_run_count', 0)
    if outlier_count:
        lines.append(
            f"  * Outlier text runs (different font than body or smaller than body size): {outlier_count}"
        )
    for note in (style_inventory.get('coverage_notes') or [])[:3]:
        lines.append(f"  * Note: {note}")
    lines.append(
        "  * The complete stored style inventory (all fonts, sizes, colours, outlier runs, page setup) "
        "is available through the Document Search action function get_document_accessibility_report."
    )
    return lines


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def extract_pdf_style_inventory(fitz_doc):
    """Aggregate PDF text-span styling. Returns ``(style_inventory, {page_number: formatting_line})``."""
    accumulator = StyleAccumulator('page_number')
    embedded_by_font = {}
    page_sizes = Counter()
    margins = {'left': None, 'right': None, 'top': None, 'bottom': None}
    notes = []
    coverage = 'full'
    pages_without_text = 0

    page_total = len(fitz_doc)
    pages_to_scan = min(page_total, MAX_STYLE_PDF_PAGES)
    if page_total > pages_to_scan:
        coverage = 'partial'
        notes.append(f"Only the first {pages_to_scan} of {page_total} pages were analysed for style.")

    for page_index in range(pages_to_scan):
        page = fitz_doc[page_index]
        page_number = page_index + 1
        rect = page.rect
        page_sizes[(round(rect.width), round(rect.height))] += 1

        try:
            for font_info in page.get_fonts(full=False) or []:
                family = normalize_font_family(font_info[3] if len(font_info) > 3 else '')
                if not family:
                    continue
                font_type = str(font_info[2] or '') if len(font_info) > 2 else ''
                is_embedded = str(font_info[1] or '').lower() not in ('', 'n/a') or font_type.lower() == 'type3'
                embedded_by_font[family] = embedded_by_font.get(family, False) or is_embedded
        except Exception:
            # Font listing is optional; span styling below is the primary signal.
            pass

        page_chars_before = accumulator.total_chars
        try:
            text_dict = page.get_text('dict') or {}
        except Exception:
            text_dict = {}

        page_min_x0 = page_min_y0 = None
        page_max_x1 = page_max_y1 = None
        for block in text_dict.get('blocks', []):
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    text = span.get('text')
                    if not text or not text.strip():
                        continue
                    raw_font = str(span.get('font') or '')
                    flags = int(span.get('flags') or 0)
                    lower_font = raw_font.lower()
                    accumulator.add(
                        page_number,
                        text,
                        font=normalize_font_family(raw_font),
                        size_pt=span.get('size'),
                        color=f"#{int(span.get('color') or 0) & 0xFFFFFF:06X}",
                        bold=bool(flags & 16) or 'bold' in lower_font,
                        italic=bool(flags & 2) or 'italic' in lower_font or 'oblique' in lower_font,
                    )
                    bbox = span.get('bbox')
                    if bbox and len(bbox) == 4:
                        x0, y0, x1, y1 = bbox
                        page_min_x0 = x0 if page_min_x0 is None else min(page_min_x0, x0)
                        page_min_y0 = y0 if page_min_y0 is None else min(page_min_y0, y0)
                        page_max_x1 = x1 if page_max_x1 is None else max(page_max_x1, x1)
                        page_max_y1 = y1 if page_max_y1 is None else max(page_max_y1, y1)

        if accumulator.total_chars == page_chars_before:
            pages_without_text += 1
            continue

        page_margins = {
            'left': page_min_x0,
            'right': (rect.width - page_max_x1) if page_max_x1 is not None else None,
            'top': page_min_y0,
            'bottom': (rect.height - page_max_y1) if page_max_y1 is not None else None,
        }
        for side, value in page_margins.items():
            if value is None:
                continue
            value = max(value, 0.0)
            margins[side] = value if margins[side] is None else min(margins[side], value)

    if pages_without_text:
        notes.append(
            f"{pages_without_text} page(s) have no extractable text (for example scanned images), "
            "so no font data exists for them."
        )
        if pages_without_text == pages_to_scan:
            coverage = 'partial'

    page_setup = {
        'page_sizes': [
            {'page_width_pt': width, 'page_height_pt': height, 'pages': count}
            for (width, height), count in page_sizes.most_common(MAX_STYLE_PAGE_SETUPS)
        ],
        'text_margins_pt': {
            f"{side}_min": (round(value, 1) if value is not None else None)
            for side, value in margins.items()
        },
    }

    inventory = accumulator.build_inventory(coverage=coverage, notes=notes, page_setup=page_setup)
    for font_entry in inventory['fonts']:
        font_entry['embedded'] = embedded_by_font.get(font_entry['name'])
    inventory['non_embedded_fonts'] = sorted(name for name, embedded in embedded_by_font.items() if not embedded)[:MAX_STYLE_FONTS]
    return inventory, accumulator.section_summaries()


# ---------------------------------------------------------------------------
# Theme parsing (shared by Word and PowerPoint)
# ---------------------------------------------------------------------------

def _parse_theme(archive, theme_name_pattern):
    """Return ``{'fonts': {'major': name, 'minor': name}, 'colors': {'dk1': '#RRGGBB', ...}}``."""
    theme = {'fonts': {}, 'colors': {}}
    theme_part = None
    for name in archive.namelist():
        if re.match(theme_name_pattern, name, re.IGNORECASE):
            if theme_part is None or name < theme_part:
                theme_part = name
    if theme_part is None:
        return theme

    theme_bytes = _read_zip_entry_bounded(archive, theme_part, OFFICE_EMBEDDED_RELS_MAX_BYTES)
    if theme_bytes is None:
        return theme
    try:
        root = defused_fromstring(theme_bytes)
    except (DefusedParseError, ValueError):
        return theme

    for elem in root.iter():
        local = _xml_local_name(elem.tag)
        if local == 'clrScheme':
            for color_elem in elem:
                color_name = _xml_local_name(color_elem.tag)
                for inner in color_elem:
                    inner_local = _xml_local_name(inner.tag)
                    if inner_local == 'srgbClr':
                        value = _hex_color(_xml_attr_by_local_name(inner, 'val'))
                    elif inner_local == 'sysClr':
                        value = _hex_color(_xml_attr_by_local_name(inner, 'lastClr'))
                    else:
                        continue
                    if value:
                        theme['colors'][color_name] = value
        elif local in ('majorFont', 'minorFont'):
            for inner in elem:
                if _xml_local_name(inner.tag) == 'latin':
                    typeface = _xml_attr_by_local_name(inner, 'typeface').strip()
                    if typeface:
                        theme['fonts']['major' if local == 'majorFont' else 'minor'] = typeface
    return theme


def _theme_color(theme, theme_color_name):
    key = _THEME_COLOR_ALIASES.get(str(theme_color_name or '').strip().lower())
    return theme['colors'].get(key) if key else None


# ---------------------------------------------------------------------------
# Word (.docx/.docm/.dotx)
# ---------------------------------------------------------------------------

def _is_on(element):
    """Interpret an OOXML on/off element: present with no value or a truthy value means on."""
    return _xml_attr_by_local_name(element, 'val').strip().lower() not in ('0', 'false', 'off')


class _WordStyleResolver:
    """Resolve effective run and paragraph formatting from styles.xml, document defaults, and theme."""

    def __init__(self, archive):
        self.theme = _parse_theme(archive, r'^word/theme/theme\d+\.xml$')
        self.styles = {}
        self.default_run = {}
        self.default_paragraph = {}
        self.default_paragraph_style_id = None
        self._chain_cache = {}
        self._load_styles(archive)

    def _theme_font(self, theme_token):
        token = str(theme_token or '').lower()
        if token.startswith('major'):
            return self.theme['fonts'].get('major')
        if token.startswith('minor'):
            return self.theme['fonts'].get('minor')
        return None

    def parse_rpr(self, rpr_elem):
        props = {}
        if rpr_elem is None:
            return props
        for item in rpr_elem:
            local = _xml_local_name(item.tag)
            if local == 'rStyle':
                props['r_style'] = _xml_attr_by_local_name(item, 'val')
            elif local == 'rFonts':
                theme_token = _xml_attr_by_local_name(item, 'asciiTheme', 'hAnsiTheme')
                font = (self._theme_font(theme_token) if theme_token else '') or _xml_attr_by_local_name(
                    item, 'ascii', 'hAnsi'
                )
                if font:
                    props['font'] = font
            elif local == 'sz':
                raw = _xml_attr_by_local_name(item, 'val')
                if raw.isdigit() and int(raw) > 0:
                    props['size_pt'] = int(raw) / 2.0
            elif local == 'color':
                theme_name = _xml_attr_by_local_name(item, 'themeColor')
                raw = _xml_attr_by_local_name(item, 'val').strip()
                resolved = _theme_color(self.theme, theme_name) if theme_name else None
                if resolved:
                    props['color'] = resolved
                elif raw.lower() == 'auto':
                    props['color'] = 'auto'
                elif _hex_color(raw):
                    props['color'] = _hex_color(raw)
            elif local == 'b':
                props['bold'] = _is_on(item)
            elif local == 'i':
                props['italic'] = _is_on(item)
            elif local == 'u':
                props['underline'] = _xml_attr_by_local_name(item, 'val').strip().lower() not in ('none', '')
        return props

    @staticmethod
    def parse_ppr(ppr_elem):
        props = {}
        if ppr_elem is None:
            return props
        for item in ppr_elem:
            local = _xml_local_name(item.tag)
            if local == 'pStyle':
                props['p_style'] = _xml_attr_by_local_name(item, 'val')
            elif local == 'jc':
                props['alignment'] = _xml_attr_by_local_name(item, 'val').strip().lower()
            elif local == 'spacing':
                line = _xml_attr_by_local_name(item, 'line')
                rule = _xml_attr_by_local_name(item, 'lineRule').strip().lower() or 'auto'
                if line.isdigit() and int(line) > 0:
                    twips = int(line)
                    props['line_spacing'] = (
                        f"{round(twips / 240.0, 2)}x" if rule == 'auto' else f"{round(twips / 20.0, 1)}pt {rule}"
                    )
        return props

    def _load_styles(self, archive):
        styles_bytes = _read_zip_entry_bounded(archive, 'word/styles.xml', OFFICE_DOCUMENT_PART_MAX_BYTES)
        if styles_bytes is None:
            return
        try:
            root = defused_fromstring(styles_bytes)
        except (DefusedParseError, ValueError):
            return

        for elem in root:
            local = _xml_local_name(elem.tag)
            if local == 'docDefaults':
                for defaults in elem:
                    defaults_local = _xml_local_name(defaults.tag)
                    for child in defaults:
                        child_local = _xml_local_name(child.tag)
                        if defaults_local == 'rPrDefault' and child_local == 'rPr':
                            self.default_run = self.parse_rpr(child)
                        elif defaults_local == 'pPrDefault' and child_local == 'pPr':
                            self.default_paragraph = self.parse_ppr(child)
            elif local == 'style':
                style_id = _xml_attr_by_local_name(elem, 'styleId')
                if not style_id:
                    continue
                style = {
                    'type': _xml_attr_by_local_name(elem, 'type'),
                    'name': '',
                    'based_on': '',
                    'rpr': {},
                    'ppr': {},
                }
                for child in elem:
                    child_local = _xml_local_name(child.tag)
                    if child_local == 'name':
                        style['name'] = _xml_attr_by_local_name(child, 'val')
                    elif child_local == 'basedOn':
                        style['based_on'] = _xml_attr_by_local_name(child, 'val')
                    elif child_local == 'rPr':
                        style['rpr'] = self.parse_rpr(child)
                    elif child_local == 'pPr':
                        style['ppr'] = self.parse_ppr(child)
                self.styles[style_id] = style
                if (
                    style['type'] == 'paragraph'
                    and _xml_attr_by_local_name(elem, 'default').lower() in ('1', 'true')
                ):
                    self.default_paragraph_style_id = style_id

    def _chain(self, style_id):
        """Return style ids from the root of the ``basedOn`` chain down to ``style_id``."""
        if not style_id:
            return []
        cached = self._chain_cache.get(style_id)
        if cached is not None:
            return cached
        chain = []
        seen = set()
        current = style_id
        while current and current in self.styles and current not in seen and len(chain) < 20:
            seen.add(current)
            chain.append(current)
            current = self.styles[current]['based_on']
        chain.reverse()
        self._chain_cache[style_id] = chain
        return chain

    def resolve_run(self, paragraph_style_id, direct_rpr):
        effective = dict(self.default_run)
        effective_paragraph_style = paragraph_style_id or self.default_paragraph_style_id
        for style_id in self._chain(effective_paragraph_style):
            effective.update(self.styles[style_id]['rpr'])
        for style_id in self._chain(direct_rpr.get('r_style')):
            effective.update(self.styles[style_id]['rpr'])
        effective.update(direct_rpr)
        if not effective.get('font'):
            effective['font'] = self.theme['fonts'].get('minor')
        if not effective.get('size_pt'):
            effective['size_pt'] = STYLE_DEFAULT_WORD_FONT_SIZE_PT
        return effective

    def resolve_paragraph(self, paragraph_style_id, direct_ppr):
        effective = dict(self.default_paragraph)
        effective_style = paragraph_style_id or self.default_paragraph_style_id
        for style_id in self._chain(effective_style):
            effective.update(self.styles[style_id]['ppr'])
        effective.update({k: v for k, v in direct_ppr.items() if k != 'p_style'})
        return effective

    def style_display(self, style_id):
        style = self.styles.get(style_id) or {}
        return style.get('name') or style_id


def _iter_word_runs(paragraph_elem):
    """Yield ``w:r`` runs that belong to this paragraph (not to nested textbox paragraphs)."""
    stack = list(reversed(list(paragraph_elem)))
    while stack:
        node = stack.pop()
        local = _xml_local_name(node.tag)
        if local == 'p':
            continue
        if local == 'r':
            yield node
            continue
        stack.extend(reversed(list(node)))


def _word_run_text(run_elem):
    parts = []
    for node in run_elem:
        local = _xml_local_name(node.tag)
        if local == 't' and node.text:
            parts.append(str(node.text))
        elif local == 'tab':
            parts.append(' ')
    return ''.join(parts)


def _word_paragraph_word_count(paragraph_elem):
    text = ''.join(str(t.text) for t in paragraph_elem.iter() if _xml_local_name(t.tag) == 't' and t.text)
    return len(re.sub(r'\s+', ' ', text).strip().split()) if text.strip() else 0


def _extract_word_page_setup(body_elem):
    setups = {}
    for elem in body_elem.iter():
        if _xml_local_name(elem.tag) != 'sectPr':
            continue
        width = height = None
        orientation = ''
        margins = {}
        for child in elem:
            child_local = _xml_local_name(child.tag)
            if child_local == 'pgSz':
                w_raw = _xml_attr_by_local_name(child, 'w')
                h_raw = _xml_attr_by_local_name(child, 'h')
                width = round(int(w_raw) / 20.0, 1) if w_raw.isdigit() else None
                height = round(int(h_raw) / 20.0, 1) if h_raw.isdigit() else None
                orientation = _xml_attr_by_local_name(child, 'orient') or (
                    'landscape' if width and height and width > height else 'portrait'
                )
            elif child_local == 'pgMar':
                for side in ('top', 'bottom', 'left', 'right'):
                    raw = _xml_attr_by_local_name(child, side)
                    if raw.lstrip('-').isdigit():
                        margins[side] = round(int(raw) / 20.0, 1)
        key = (width, height, orientation, tuple(sorted(margins.items())))
        setups[key] = setups.get(key, 0) + 1

    return {
        'sections': [
            {
                'page_width_pt': width,
                'page_height_pt': height,
                'orientation': orientation,
                'margins_pt': dict(margin_items),
                'pages': None,
                'section_count': count,
            }
            for (width, height, orientation, margin_items), count in list(setups.items())[:MAX_STYLE_PAGE_SETUPS]
        ]
    }


def build_word_style_inventory(archive, body_elem, style_counts, bucket_size):
    """Resolve and aggregate run formatting for a Word body.

    Returns ``(style_inventory, structural_events)`` where ``structural_events`` carry one
    ``Formatting:`` summary per word-offset bucket so it lands in the matching search chunk.
    """
    resolver = _WordStyleResolver(archive)
    accumulator = StyleAccumulator('word_offset')
    word_offset = 0

    def process_paragraph(paragraph_elem, location):
        ppr_elem = next((c for c in paragraph_elem if _xml_local_name(c.tag) == 'pPr'), None)
        direct_ppr = resolver.parse_ppr(ppr_elem)
        paragraph_style_id = direct_ppr.get('p_style')
        had_text = False
        for run_elem in _iter_word_runs(paragraph_elem):
            text = _word_run_text(run_elem)
            if not text.strip():
                continue
            had_text = True
            rpr_elem = next((c for c in run_elem if _xml_local_name(c.tag) == 'rPr'), None)
            effective = resolver.resolve_run(paragraph_style_id, resolver.parse_rpr(rpr_elem))
            accumulator.add(
                location,
                text,
                font=effective.get('font'),
                size_pt=effective.get('size_pt'),
                color=effective.get('color'),
                bold=bool(effective.get('bold')),
                italic=bool(effective.get('italic')),
                underline=bool(effective.get('underline')),
            )
        if had_text:
            layout = resolver.resolve_paragraph(paragraph_style_id, direct_ppr)
            accumulator.add_paragraph_layout(
                alignment=layout.get('alignment') or 'left',
                line_spacing=layout.get('line_spacing'),
            )

    for element in body_elem:
        local = _xml_local_name(element.tag)
        if local == 'p':
            for paragraph_elem in element.iter():
                if _xml_local_name(paragraph_elem.tag) == 'p':
                    process_paragraph(paragraph_elem, word_offset)
            word_offset += _word_paragraph_word_count(element)
        elif local == 'tbl':
            table_offset = word_offset
            for paragraph_elem in element.iter():
                if _xml_local_name(paragraph_elem.tag) == 'p':
                    process_paragraph(paragraph_elem, table_offset)
            word_offset += sum(
                len(str(t.text or '').split())
                for t in element.iter()
                if _xml_local_name(t.tag) == 't' and t.text
            )

    paragraph_styles = []
    for style_id, count in list((style_counts or {}).items())[:MAX_STYLE_PARAGRAPH_STYLES]:
        style = resolver.styles.get(style_id)
        if not style:
            continue
        run_props = resolver.resolve_run(style_id, {})
        para_props = resolver.resolve_paragraph(style_id, {})
        paragraph_styles.append({
            'style_id': style_id,
            'name': resolver.style_display(style_id),
            'paragraphs': count,
            'font': run_props.get('font'),
            'size_pt': run_props.get('size_pt'),
            'color': run_props.get('color'),
            'bold': bool(run_props.get('bold')),
            'italic': bool(run_props.get('italic')),
            'alignment': para_props.get('alignment') or 'left',
            'line_spacing': para_props.get('line_spacing'),
        })

    notes = [
        'Formatting is resolved from direct run properties, paragraph and character styles, document '
        'defaults, and the theme. Table styles and theme colour tint/shade adjustments are not applied.',
        'Word documents have no fixed pages; locations are word offsets into the body text.',
    ]
    inventory = accumulator.build_inventory(
        coverage='full',
        notes=notes,
        page_setup=_extract_word_page_setup(body_elem),
        extra={'paragraph_styles': paragraph_styles},
    )

    bucket_size = max(int(bucket_size or 1), 1)
    summaries = accumulator.section_summaries(key_fn=lambda offset: (int(offset) // bucket_size) * bucket_size)
    events = [
        {'word_offset': bucket_offset, 'kind': 'formatting', 'summary': line}
        for bucket_offset, line in sorted(summaries.items())
    ]
    return inventory, events


def build_legacy_doc_style_inventory(character_runs, bucket_size, notes=None):
    """Aggregate best-effort legacy .doc character runs into ``(style_inventory, structural_events)``."""
    accumulator = StyleAccumulator('word_offset')
    for run in character_runs or []:
        accumulator.add(
            run.get('word_offset') or 0,
            run.get('text'),
            font=run.get('font'),
            size_pt=run.get('size_pt'),
            color=run.get('color'),
            bold=bool(run.get('bold')),
            italic=bool(run.get('italic')),
            underline=bool(run.get('underline')),
        )

    inventory = accumulator.build_inventory(coverage='partial', notes=list(notes or []))
    bucket_size = max(int(bucket_size or 1), 1)
    summaries = accumulator.section_summaries(key_fn=lambda offset: (int(offset) // bucket_size) * bucket_size)
    events = [
        {'word_offset': bucket_offset, 'kind': 'formatting', 'summary': line}
        for bucket_offset, line in sorted(summaries.items())
    ]
    return inventory, events


# ---------------------------------------------------------------------------
# PowerPoint (.pptx)
# ---------------------------------------------------------------------------

def _resolve_package_path(base_part, target):
    target = str(target or '').strip()
    if not target or '://' in target:
        return ''
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _read_rels_targets(archive, part_name, relationship_suffix):
    """Return the first relationship target (resolved to a package path) whose type ends with a suffix."""
    rels_name = posixpath.join(posixpath.dirname(part_name), '_rels', posixpath.basename(part_name) + '.rels')
    rels_bytes = _read_zip_entry_bounded(archive, rels_name, OFFICE_EMBEDDED_RELS_MAX_BYTES)
    if rels_bytes is None:
        return ''
    try:
        rels_root = defused_fromstring(rels_bytes)
    except (DefusedParseError, ValueError):
        return ''
    for rel in rels_root:
        if str(rel.attrib.get('Type') or '').endswith(relationship_suffix):
            return _resolve_package_path(part_name, rel.attrib.get('Target'))
    return ''


def _parse_dml_run_props(elem, theme):
    """Parse an ``a:rPr`` / ``a:defRPr`` element into style properties."""
    props = {}
    if elem is None:
        return props
    sz = _xml_attr_by_local_name(elem, 'sz')
    if sz.isdigit() and int(sz) > 0:
        props['size_pt'] = int(sz) / 100.0
    for attr_name, key in (('b', 'bold'), ('i', 'italic')):
        raw = _xml_attr_by_local_name(elem, attr_name).strip().lower()
        if raw:
            props[key] = raw in ('1', 'true')
    underline = _xml_attr_by_local_name(elem, 'u').strip().lower()
    if underline:
        props['underline'] = underline != 'none'

    for child in elem:
        child_local = _xml_local_name(child.tag)
        if child_local == 'latin':
            typeface = _xml_attr_by_local_name(child, 'typeface').strip()
            if typeface == '+mj-lt':
                typeface = theme['fonts'].get('major', '')
            elif typeface == '+mn-lt':
                typeface = theme['fonts'].get('minor', '')
            if typeface and not typeface.startswith('+'):
                props['font'] = typeface
        elif child_local == 'solidFill':
            for color_elem in child:
                color_local = _xml_local_name(color_elem.tag)
                if color_local == 'srgbClr':
                    resolved = _hex_color(_xml_attr_by_local_name(color_elem, 'val'))
                elif color_local == 'schemeClr':
                    resolved = _theme_color(theme, _xml_attr_by_local_name(color_elem, 'val'))
                else:
                    resolved = None
                if resolved:
                    props['color'] = resolved
    return props


def _parse_dml_level_styles(container, theme):
    """Parse ``lvlNpPr/defRPr`` entries (from ``a:lstStyle`` or ``p:txStyles`` children) by level 1-9."""
    levels = {}
    if container is None:
        return levels
    for child in container:
        match = re.match(r'^lvl(\d)pPr$', _xml_local_name(child.tag))
        if not match:
            continue
        for sub in child:
            if _xml_local_name(sub.tag) == 'defRPr':
                levels[int(match.group(1))] = _parse_dml_run_props(sub, theme)
    return levels


def _placeholder_info(sp_elem):
    for node in sp_elem.iter():
        if _xml_local_name(node.tag) == 'ph':
            return _xml_attr_by_local_name(node, 'type').strip().lower(), _xml_attr_by_local_name(node, 'idx').strip()
    return None


def _collect_placeholder_styles(root, theme):
    placeholders = []
    for sp_elem in root.iter():
        if _xml_local_name(sp_elem.tag) != 'sp':
            continue
        info = _placeholder_info(sp_elem)
        if info is None:
            continue
        lst_style = None
        for tx_body in sp_elem:
            if _xml_local_name(tx_body.tag) == 'txBody':
                for inner in tx_body:
                    if _xml_local_name(inner.tag) == 'lstStyle':
                        lst_style = inner
        placeholders.append({'type': info[0], 'idx': info[1], 'levels': _parse_dml_level_styles(lst_style, theme)})
    return placeholders


def _find_placeholder(placeholders, ph_type, ph_idx, is_master=False):
    if is_master:
        wanted_type = ph_type if ph_type in ('title', 'ctrtitle') else 'body'
        if wanted_type == 'ctrtitle':
            wanted_type = 'title'
        for item in placeholders:
            item_type = 'title' if item['type'] == 'ctrtitle' else item['type']
            if item_type == wanted_type:
                return item
        return None
    if ph_idx:
        for item in placeholders:
            if item['idx'] == ph_idx:
                return item
    for item in placeholders:
        if item['type'] and item['type'] == ph_type:
            return item
    return None


def _txstyle_kind(ph_info):
    if ph_info is None:
        return 'other'
    ph_type = ph_info[0]
    if ph_type in ('title', 'ctrtitle'):
        return 'title'
    if ph_type in ('dt', 'ftr', 'sldnum', 'hdr'):
        return 'other'
    return 'body'


def build_pptx_style_inventory(archive, slide_entries):
    """Resolve and aggregate run formatting across slides.

    Returns ``(style_inventory, {slide_number: formatting_line})``.
    """
    theme = _parse_theme(archive, r'^ppt/theme/theme\d+\.xml$')
    accumulator = StyleAccumulator('slide_number')

    default_levels = {}
    presentation_bytes = _read_zip_entry_bounded(archive, 'ppt/presentation.xml', OFFICE_EMBEDDED_RELS_MAX_BYTES)
    if presentation_bytes is not None:
        try:
            presentation_root = defused_fromstring(presentation_bytes)
            for elem in presentation_root:
                if _xml_local_name(elem.tag) == 'defaultTextStyle':
                    default_levels = _parse_dml_level_styles(elem, theme)
        except (DefusedParseError, ValueError):
            default_levels = {}

    master_cache = {}
    layout_cache = {}

    def load_master(master_path):
        if not master_path:
            return {'tx_styles': {}, 'placeholders': []}
        if master_path in master_cache:
            return master_cache[master_path]
        data = {'tx_styles': {}, 'placeholders': []}
        master_bytes = _read_zip_entry_bounded(archive, master_path, OFFICE_DOCUMENT_PART_MAX_BYTES)
        if master_bytes is not None:
            try:
                master_root = defused_fromstring(master_bytes)
                data['placeholders'] = _collect_placeholder_styles(master_root, theme)
                for elem in master_root.iter():
                    if _xml_local_name(elem.tag) == 'txStyles':
                        for style_elem in elem:
                            style_local = _xml_local_name(style_elem.tag)
                            kind = {'titleStyle': 'title', 'bodyStyle': 'body', 'otherStyle': 'other'}.get(style_local)
                            if kind:
                                data['tx_styles'][kind] = _parse_dml_level_styles(style_elem, theme)
            except (DefusedParseError, ValueError):
                pass
        master_cache[master_path] = data
        return data

    def load_layout(layout_path):
        if not layout_path:
            return {'placeholders': [], 'master_path': ''}
        if layout_path in layout_cache:
            return layout_cache[layout_path]
        data = {'placeholders': [], 'master_path': _read_rels_targets(archive, layout_path, '/slideMaster')}
        layout_bytes = _read_zip_entry_bounded(archive, layout_path, OFFICE_DOCUMENT_PART_MAX_BYTES)
        if layout_bytes is not None:
            try:
                data['placeholders'] = _collect_placeholder_styles(defused_fromstring(layout_bytes), theme)
            except (DefusedParseError, ValueError):
                pass
        layout_cache[layout_path] = data
        return data

    for slide_number, slide_path in slide_entries:
        slide_bytes = _read_zip_entry_bounded(archive, slide_path, OFFICE_DOCUMENT_PART_MAX_BYTES)
        if slide_bytes is None:
            continue
        try:
            slide_root = defused_fromstring(slide_bytes)
        except (DefusedParseError, ValueError):
            continue

        layout = load_layout(_read_rels_targets(archive, slide_path, '/slideLayout'))
        master = load_master(layout['master_path'])

        text_containers = []
        for elem in slide_root.iter():
            local = _xml_local_name(elem.tag)
            if local == 'sp':
                text_containers.append((elem, _placeholder_info(elem)))
            elif local == 'tbl':
                text_containers.append((elem, None))

        for container, ph_info in text_containers:
            shape_levels = {}
            if _xml_local_name(container.tag) == 'sp':
                for tx_body in container:
                    if _xml_local_name(tx_body.tag) == 'txBody':
                        for inner in tx_body:
                            if _xml_local_name(inner.tag) == 'lstStyle':
                                shape_levels = _parse_dml_level_styles(inner, theme)

            layout_ph = _find_placeholder(layout['placeholders'], ph_info[0], ph_info[1]) if ph_info else None
            master_ph = _find_placeholder(master['placeholders'], ph_info[0], ph_info[1], is_master=True) if ph_info else None
            tx_style = master['tx_styles'].get(_txstyle_kind(ph_info), {})

            for paragraph in container.iter():
                if _xml_local_name(paragraph.tag) != 'p':
                    continue
                level = 1
                for child in paragraph:
                    if _xml_local_name(child.tag) == 'pPr':
                        lvl_raw = _xml_attr_by_local_name(child, 'lvl')
                        if lvl_raw.isdigit():
                            level = min(int(lvl_raw) + 1, 9)
                base = {}
                for source in (
                    default_levels,
                    tx_style,
                    master_ph['levels'] if master_ph else {},
                    layout_ph['levels'] if layout_ph else {},
                    shape_levels,
                ):
                    base.update(source.get(level, {}))

                for run in paragraph:
                    if _xml_local_name(run.tag) != 'r':
                        continue
                    text = ''.join(
                        str(t.text) for t in run if _xml_local_name(t.tag) == 't' and t.text
                    )
                    if not text.strip():
                        continue
                    r_pr = next((c for c in run if _xml_local_name(c.tag) == 'rPr'), None)
                    effective = dict(base)
                    effective.update(_parse_dml_run_props(r_pr, theme))
                    accumulator.add(
                        slide_number,
                        text,
                        font=effective.get('font') or theme['fonts'].get('minor'),
                        size_pt=effective.get('size_pt') or STYLE_DEFAULT_PPTX_FONT_SIZE_PT,
                        color=effective.get('color'),
                        bold=bool(effective.get('bold')),
                        italic=bool(effective.get('italic')),
                        underline=bool(effective.get('underline')),
                    )

    notes = [
        'Formatting is resolved from run properties, shape list styles, layout and master placeholders, '
        'master text styles, presentation defaults, and the theme. Table styles, colour-map remapping, '
        'and theme colour tint/shade adjustments are not applied; text with no explicit size is '
        f'assumed to be {STYLE_DEFAULT_PPTX_FONT_SIZE_PT:g}pt (the PowerPoint default).',
    ]
    inventory = accumulator.build_inventory(coverage='full', notes=notes)
    return inventory, accumulator.section_summaries()


def safe_style_extraction(label, extractor):
    """Run a style extractor and keep the rest of metadata extraction intact if it fails."""
    try:
        return extractor()
    except Exception as exc:
        log_event(
            f"[DOCUMENT_METADATA] Style extraction failed for {label}: {type(exc).__name__}",
            level=30,
            debug_only=True,
        )
        return None
