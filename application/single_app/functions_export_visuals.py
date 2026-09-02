# functions_export_visuals.py
"""Shared helpers for embedding rendered visual blocks into export documents.

This module is the single source of truth for the HTML wrapper markup used by every
inline export visual (charts, generated images, Mermaid diagrams and TeX formulas), and
for validating browser-rasterized PNG assets that arrive on export requests.
"""

import base64
import binascii
import io
from html import escape as escape_html
from typing import Any, Dict, List, Optional


EXPORT_VISUAL_KIND_CHART = 'chart'
EXPORT_VISUAL_KIND_IMAGE = 'image'
EXPORT_VISUAL_KIND_DIAGRAM = 'diagram'
EXPORT_VISUAL_KIND_MATH = 'math'

EXPORT_VISUAL_WRAPPER_CLASS_BY_KIND = {
    EXPORT_VISUAL_KIND_CHART: 'export-inline-chart',
    EXPORT_VISUAL_KIND_IMAGE: 'export-inline-image',
    EXPORT_VISUAL_KIND_DIAGRAM: 'export-inline-diagram',
    EXPORT_VISUAL_KIND_MATH: 'export-inline-math',
}
EXPORT_VISUAL_CAPTION_CLASS_BY_KIND = {
    kind: f'{wrapper_class}-caption'
    for kind, wrapper_class in EXPORT_VISUAL_WRAPPER_CLASS_BY_KIND.items()
}
EXPORT_VISUAL_KIND_BY_WRAPPER_CLASS = {
    wrapper_class: kind
    for kind, wrapper_class in EXPORT_VISUAL_WRAPPER_CLASS_BY_KIND.items()
}

EXPORT_VISUAL_WRAPPER_CLASSES = tuple(EXPORT_VISUAL_WRAPPER_CLASS_BY_KIND.values())
EXPORT_VISUAL_CAPTION_CLASSES = tuple(EXPORT_VISUAL_CAPTION_CLASS_BY_KIND.values())

EXPORT_VISUAL_PNG_DATA_URI_PREFIX = 'data:image/png;base64,'
EXPORT_VISUAL_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

EXPORT_VISUAL_ASSET_MAX_COUNT = 60
EXPORT_VISUAL_ASSET_MAX_BYTES = 4 * 1024 * 1024
EXPORT_VISUAL_ASSET_MAX_PIXELS = 40_000_000
EXPORT_VISUAL_ASSET_MAX_SOURCE_LENGTH = 20000
EXPORT_VISUAL_ASSET_MAX_TEXT_LENGTH = 240

EXPORT_VISUAL_ALT_TEXT_BY_KIND = {
    EXPORT_VISUAL_KIND_CHART: 'Chart',
    EXPORT_VISUAL_KIND_IMAGE: 'Image',
    EXPORT_VISUAL_KIND_DIAGRAM: 'Mermaid diagram',
    EXPORT_VISUAL_KIND_MATH: 'Formula',
}


def build_export_visual_html(
    kind: str,
    data_uri: str,
    alt_text: str = '',
    caption_text: str = '',
) -> str:
    """Build the wrapper markup that every export surface knows how to consume."""
    wrapper_class = EXPORT_VISUAL_WRAPPER_CLASS_BY_KIND.get(kind)
    if not wrapper_class or not str(data_uri or '').strip():
        return ''

    caption_class = EXPORT_VISUAL_CAPTION_CLASS_BY_KIND[kind]
    resolved_alt = str(alt_text or '').strip() or EXPORT_VISUAL_ALT_TEXT_BY_KIND.get(kind, 'Visual')
    caption_html = ''
    normalized_caption = str(caption_text or '').strip()
    if normalized_caption:
        caption_html = (
            f'<p class="{caption_class}">'
            f'<em>{escape_html(normalized_caption)}</em>'
            '</p>'
        )

    return (
        '\n\n'
        f'<div class="{wrapper_class}">'
        f'<p><img src="{escape_html(str(data_uri))}" alt="{escape_html(resolved_alt)}" /></p>'
        f'{caption_html}'
        '</div>'
        '\n\n'
    )


def normalize_visual_source(value: Any) -> str:
    """Normalize fence content so client-supplied assets match server-side blocks."""
    text = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def normalize_visual_assets(
    raw_assets: Any,
    max_count: int = EXPORT_VISUAL_ASSET_MAX_COUNT,
) -> List[Dict[str, Any]]:
    """Validate browser-rasterized export visuals, dropping anything unusable.

    Assets arrive from the browser and are embedded directly into generated documents,
    so each entry is decoded and confirmed to be a real PNG within size limits. A single
    malformed entry is skipped rather than raised so it cannot fail an entire export.
    """
    if not isinstance(raw_assets, list):
        return []

    normalized_assets: List[Dict[str, Any]] = []
    for raw_asset in raw_assets:
        if len(normalized_assets) >= max_count:
            break
        normalized_asset = _normalize_visual_asset(raw_asset)
        if normalized_asset:
            normalized_assets.append(normalized_asset)
    return normalized_assets


def build_visual_asset_map(
    visual_assets: Optional[List[Dict[str, Any]]],
    kind: str,
) -> Dict[str, Dict[str, Any]]:
    """Index validated assets of one kind by their normalized source text."""
    asset_map: Dict[str, Dict[str, Any]] = {}
    if not isinstance(visual_assets, list):
        return asset_map

    for asset in visual_assets:
        if not isinstance(asset, dict) or asset.get('kind') != kind:
            continue
        source_key = asset.get('normalized_source')
        if source_key and source_key not in asset_map:
            asset_map[source_key] = asset
    return asset_map


def decode_export_visual_png(data_uri: Any) -> Optional[bytes]:
    """Decode and validate a base64 PNG data URI, returning None when unusable."""
    candidate = str(data_uri or '').strip()
    if not candidate.startswith(EXPORT_VISUAL_PNG_DATA_URI_PREFIX):
        return None

    encoded_payload = candidate[len(EXPORT_VISUAL_PNG_DATA_URI_PREFIX):]
    if not encoded_payload or len(encoded_payload) > _max_encoded_payload_length():
        return None

    try:
        image_bytes = base64.b64decode(encoded_payload, validate=True)
    except (ValueError, TypeError, binascii.Error):
        return None

    if not image_bytes or len(image_bytes) > EXPORT_VISUAL_ASSET_MAX_BYTES:
        return None
    if not image_bytes.startswith(EXPORT_VISUAL_PNG_MAGIC):
        return None
    if not _png_bytes_are_valid(image_bytes):
        return None
    return image_bytes


def build_export_visual_png_data_uri(image_bytes: bytes) -> str:
    """Re-encode validated PNG bytes so untrusted text is never echoed back."""
    encoded_payload = base64.b64encode(image_bytes).decode('ascii')
    return f'{EXPORT_VISUAL_PNG_DATA_URI_PREFIX}{encoded_payload}'


def find_export_visual_wrapper(image_node: Any) -> Any:
    """Return the export visual wrapper element enclosing an image node, if any."""
    if image_node is None or not hasattr(image_node, 'find_parent'):
        return None

    for wrapper_class in EXPORT_VISUAL_WRAPPER_CLASSES:
        wrapper = image_node.find_parent(class_=wrapper_class)
        if wrapper is not None:
            return wrapper
    return None


def find_export_visual_caption_node(wrapper: Any) -> Any:
    """Return the caption element inside an export visual wrapper, if any."""
    if wrapper is None or not hasattr(wrapper, 'find'):
        return None

    for caption_class in EXPORT_VISUAL_CAPTION_CLASSES:
        caption_node = wrapper.find(class_=caption_class)
        if caption_node is not None:
            return caption_node
    return None


def get_export_visual_kind(wrapper: Any) -> str:
    """Return the visual kind a wrapper element represents."""
    if wrapper is None or not hasattr(wrapper, 'get'):
        return ''

    class_names = wrapper.get('class') or []
    if isinstance(class_names, str):
        class_names = [class_names]
    for class_name in class_names:
        kind = EXPORT_VISUAL_KIND_BY_WRAPPER_CLASS.get(class_name)
        if kind:
            return kind
    return ''


def is_export_visual_caption_class(class_names: Any) -> bool:
    """Return True when an element carries any export visual caption class."""
    if isinstance(class_names, str):
        class_names = [class_names]
    if not class_names:
        return False
    return any(class_name in EXPORT_VISUAL_CAPTION_CLASSES for class_name in class_names)


def replace_inline_visual_blocks_with_export_html(
    content: Any,
    visual_assets: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Convert every supported inline visual block into embeddable PNG-backed HTML.

    TeX runs first, while the content still has intact code fences, so display math
    detection can skip fenced blocks and never touch a chart payload or a Mermaid source.

    The renderer modules are imported inside this function because each of them imports
    this module for the shared wrapper markup, so a module-level import here would create
    an import cycle.
    """
    from functions_chart_export import replace_inline_chart_blocks_with_export_html
    from functions_mermaid_export import replace_inline_mermaid_blocks_with_export_html
    from functions_tex_export import replace_inline_tex_blocks_with_export_html

    rendered_content = str(content or '')
    if not rendered_content.strip():
        return rendered_content

    rendered_content = replace_inline_tex_blocks_with_export_html(rendered_content)
    rendered_content = replace_inline_chart_blocks_with_export_html(rendered_content)
    return replace_inline_mermaid_blocks_with_export_html(rendered_content, visual_assets)


def _normalize_visual_asset(raw_asset: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_asset, dict):
        return None

    kind = str(raw_asset.get('kind') or '').strip().lower()
    if kind not in EXPORT_VISUAL_WRAPPER_CLASS_BY_KIND:
        return None

    raw_source = raw_asset.get('source')
    if not isinstance(raw_source, str) or len(raw_source) > EXPORT_VISUAL_ASSET_MAX_SOURCE_LENGTH:
        return None

    normalized_source = normalize_visual_source(raw_source)
    if not normalized_source:
        return None

    image_bytes = decode_export_visual_png(raw_asset.get('data_uri'))
    if not image_bytes:
        return None

    return {
        'kind': kind,
        'source': raw_source,
        'normalized_source': normalized_source,
        'data_uri': build_export_visual_png_data_uri(image_bytes),
        'image_bytes': image_bytes,
        'alt': _clean_visual_asset_text(raw_asset.get('alt')),
        'caption': _clean_visual_asset_text(raw_asset.get('caption')),
    }


def _clean_visual_asset_text(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    collapsed = ' '.join(value.split())
    return collapsed[:EXPORT_VISUAL_ASSET_MAX_TEXT_LENGTH]


def _max_encoded_payload_length() -> int:
    return ((EXPORT_VISUAL_ASSET_MAX_BYTES + 2) // 3) * 4 + 4


def _png_bytes_are_valid(image_bytes: bytes) -> bool:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as probe:
            if probe.format != 'PNG':
                return False
            width, height = probe.size
            if width <= 0 or height <= 0:
                return False
            if width * height > EXPORT_VISUAL_ASSET_MAX_PIXELS:
                return False
            probe.verify()
    except Exception:
        return False
    return True
