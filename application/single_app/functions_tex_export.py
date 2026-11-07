# functions_tex_export.py
"""Helpers for rendering inline TeX math blocks into export-friendly images.

Rendering uses matplotlib's ``mathtext`` engine, which parses a large subset of LaTeX
math in pure Python and needs no TeX installation and no subprocess. Constructs
``mathtext`` cannot parse, such as ``align``, ``matrix`` and ``cases`` environments, are
left in the content exactly as the model wrote them.
"""

import io
import re
from functools import lru_cache
from typing import Any, Optional

from functions_export_visuals import (
    EXPORT_VISUAL_ASSET_MAX_BYTES,
    EXPORT_VISUAL_KIND_MATH,
    build_export_visual_html,
    build_export_visual_png_data_uri,
)


INLINE_TEX_BLOCK_LANGUAGES = ('math', 'latex', 'tex')
INLINE_TEX_FENCE_REGEX = re.compile(
    rf"```(?:{'|'.join(INLINE_TEX_BLOCK_LANGUAGES)})[ \t]*\r?\n([\s\S]*?)```",
    re.IGNORECASE,
)
CODE_FENCE_REGEX = re.compile(r"```[\s\S]*?```")
DISPLAY_MATH_DOLLAR_REGEX = re.compile(r"\$\$([\s\S]+?)\$\$")
DISPLAY_MATH_BRACKET_REGEX = re.compile(r"\\\[([\s\S]+?)\\\]")
TEX_WRAPPER_STRIP_REGEX = re.compile(r"^(?:\$\$|\\\[|\\\(|\$)|(?:\$\$|\\\]|\\\)|\$)$")

EXPORT_TEX_DPI = 200
EXPORT_TEX_LAYOUT_DPI = 72
EXPORT_TEX_FONT_SIZE = 16
EXPORT_TEX_MAX_SOURCE_LENGTH = 2000
EXPORT_TEX_ALT_TEXT_MAX_LENGTH = 200
EXPORT_TEX_MAX_IMAGE_EDGE = 6000
EXPORT_TEX_MAX_IMAGE_PIXELS = 8_000_000


def replace_inline_tex_blocks_with_export_html(content: str) -> str:
    """Replace TeX math fences and display math with embeddable PNG-backed HTML."""
    rendered_content = str(content or '')
    if not rendered_content.strip():
        return rendered_content

    rendered_content = INLINE_TEX_FENCE_REGEX.sub(_replace_tex_fence_match, rendered_content)
    return _replace_display_math_outside_code_fences(rendered_content)


def extract_tex_sources(content: str) -> list:
    """Return the distinct normalized TeX sources found in content."""
    normalized_content = str(content or '')
    if not normalized_content.strip():
        return []

    sources = []
    seen_sources = set()

    def collect(raw_source: str):
        normalized_source = _normalize_tex_source(raw_source)
        if normalized_source and normalized_source not in seen_sources:
            seen_sources.add(normalized_source)
            sources.append(normalized_source)

    for match in INLINE_TEX_FENCE_REGEX.finditer(normalized_content):
        collect(match.group(1) or '')

    for segment in _iter_non_code_fence_segments(
        INLINE_TEX_FENCE_REGEX.sub('', normalized_content)
    ):
        for match in DISPLAY_MATH_DOLLAR_REGEX.finditer(segment):
            collect(match.group(1) or '')
        for match in DISPLAY_MATH_BRACKET_REGEX.finditer(segment):
            collect(match.group(1) or '')

    return sources


def _replace_display_math_outside_code_fences(content: str) -> str:
    rendered_parts = []
    last_index = 0

    for fence_match in CODE_FENCE_REGEX.finditer(content):
        rendered_parts.append(_replace_display_math(content[last_index:fence_match.start()]))
        rendered_parts.append(fence_match.group(0))
        last_index = fence_match.end()

    rendered_parts.append(_replace_display_math(content[last_index:]))
    return ''.join(rendered_parts)


def _iter_non_code_fence_segments(content: str):
    last_index = 0
    for fence_match in CODE_FENCE_REGEX.finditer(content):
        yield content[last_index:fence_match.start()]
        last_index = fence_match.end()
    yield content[last_index:]


def _replace_display_math(segment: str) -> str:
    if not segment or ('$$' not in segment and '\\[' not in segment):
        return segment

    rendered_segment = DISPLAY_MATH_DOLLAR_REGEX.sub(_replace_tex_match, segment)
    return DISPLAY_MATH_BRACKET_REGEX.sub(_replace_tex_match, rendered_segment)


def _replace_tex_fence_match(match: re.Match) -> str:
    export_html = _build_export_tex_html(match.group(1) or '')
    return export_html or match.group(0)


def _replace_tex_match(match: re.Match) -> str:
    export_html = _build_export_tex_html(match.group(1) or '')
    return export_html or match.group(0)


def _build_export_tex_html(tex_source: str) -> str:
    normalized_source = _normalize_tex_source(tex_source)
    if not normalized_source:
        return ''

    image_data_uri = _render_tex_to_data_uri(normalized_source)
    if not image_data_uri:
        return ''

    return build_export_visual_html(
        EXPORT_VISUAL_KIND_MATH,
        image_data_uri,
        alt_text=_build_tex_alt_text(normalized_source),
    )


def _normalize_tex_source(tex_source: str) -> str:
    collapsed_source = ' '.join(str(tex_source or '').split())
    if not collapsed_source:
        return ''

    previous_source = None
    while previous_source != collapsed_source:
        previous_source = collapsed_source
        collapsed_source = TEX_WRAPPER_STRIP_REGEX.sub('', collapsed_source).strip()

    if len(collapsed_source) > EXPORT_TEX_MAX_SOURCE_LENGTH:
        return ''
    return collapsed_source


def _build_tex_alt_text(normalized_source: str) -> str:
    return f'Formula: {normalized_source[:EXPORT_TEX_ALT_TEXT_MAX_LENGTH]}'


@lru_cache(maxsize=128)
def _render_tex_to_data_uri(normalized_source: str) -> str:
    image_bytes = _render_tex_to_png_bytes(normalized_source)
    if not image_bytes:
        return ''
    return build_export_visual_png_data_uri(image_bytes)


def _render_tex_to_png_bytes(normalized_source: str) -> Optional[bytes]:
    """Render a math expression to PNG bytes, returning None when unsupported."""
    try:
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
    except Exception:
        return None

    math_expression = f'${normalized_source}$'
    font_properties = FontProperties(size=EXPORT_TEX_FONT_SIZE)
    if not _tex_layout_is_within_budget(math_expression, font_properties):
        return None

    buffer = io.BytesIO()
    try:
        mathtext.math_to_image(
            math_expression,
            buffer,
            prop=font_properties,
            dpi=EXPORT_TEX_DPI,
            format='png',
        )
    except Exception:
        return None

    buffer.seek(0)
    image_bytes = buffer.read()
    if not image_bytes or len(image_bytes) > EXPORT_VISUAL_ASSET_MAX_BYTES:
        return None
    return image_bytes


def _tex_layout_is_within_budget(math_expression: str, font_properties: Any) -> bool:
    """Reject expressions whose raster would be oversized before it is allocated.

    Spacing commands such as ``\\hspace`` let a short expression lay out to an
    arbitrarily wide box, and math_to_image sizes its figure from that layout, so the
    input length limit alone does not bound the rendered image.
    """
    try:
        from matplotlib.mathtext import MathTextParser

        layout = MathTextParser('path').parse(
            math_expression,
            dpi=EXPORT_TEX_LAYOUT_DPI,
            prop=font_properties,
        )
    except Exception:
        return False

    render_scale = EXPORT_TEX_DPI / EXPORT_TEX_LAYOUT_DPI
    try:
        width = float(layout[0]) * render_scale
        height = float(layout[1]) * render_scale
    except (IndexError, TypeError, ValueError):
        return False

    if width <= 0 or height <= 0:
        return False
    if width > EXPORT_TEX_MAX_IMAGE_EDGE or height > EXPORT_TEX_MAX_IMAGE_EDGE:
        return False
    return (width * height) <= EXPORT_TEX_MAX_IMAGE_PIXELS
