# functions_mermaid_export.py
"""Helpers for embedding rasterized Mermaid diagrams into export documents.

Mermaid is a browser rendering library, so the PNG for a diagram is produced by the
client and sent along with the export request. This module matches those assets back to
the ```` ```mermaid ```` fences they came from. A fence with no matching asset is left
untouched, which keeps the current behaviour for any client that does not rasterize.

The substitution key is the normalized fence body rather than a hash, so a future
server-side renderer can supply the same asset shape without any protocol change.
"""

import re
from typing import Any, Dict, List, Optional

from functions_export_visuals import (
    EXPORT_VISUAL_KIND_DIAGRAM,
    build_export_visual_html,
    build_visual_asset_map,
    normalize_visual_source,
)


INLINE_MERMAID_BLOCK_LANGUAGE = 'mermaid'
INLINE_MERMAID_EXPORT_REGEX = re.compile(
    rf"```{re.escape(INLINE_MERMAID_BLOCK_LANGUAGE)}[ \t]*\r?\n([\s\S]*?)```",
    re.IGNORECASE,
)
MERMAID_FRONT_MATTER_REGEX = re.compile(r"\A---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|\Z)")
MERMAID_TITLE_REGEX = re.compile(r"^[ \t]*title[ \t:]+(.+?)[ \t]*$", re.MULTILINE | re.IGNORECASE)
MERMAID_COMMENT_LINE_REGEX = re.compile(r"^[ \t]*%%")

MERMAID_ALT_TEXT_MAX_LENGTH = 200
MERMAID_CAPTION_MAX_LENGTH = 200

MERMAID_DIAGRAM_TYPE_LABELS = {
    'architecture-beta': 'Architecture',
    'block-beta': 'Block',
    'c4component': 'C4 component',
    'c4container': 'C4 container',
    'c4context': 'C4 context',
    'c4dynamic': 'C4 dynamic',
    'classdiagram': 'Class',
    'classdiagram-v2': 'Class',
    'erdiagram': 'Entity relationship',
    'flowchart': 'Flowchart',
    'flowchart-v2': 'Flowchart',
    'gantt': 'Gantt',
    'gitgraph': 'Git graph',
    'graph': 'Flowchart',
    'journey': 'User journey',
    'kanban': 'Kanban',
    'mindmap': 'Mind map',
    'packet-beta': 'Packet',
    'pie': 'Pie',
    'quadrantchart': 'Quadrant',
    'radar-beta': 'Radar',
    'requirementdiagram': 'Requirement',
    'sankey-beta': 'Sankey',
    'sequencediagram': 'Sequence',
    'statediagram': 'State',
    'statediagram-v2': 'State',
    'timeline': 'Timeline',
    'treemap-beta': 'Treemap',
    'xychart-beta': 'XY chart',
    'zenuml': 'ZenUML',
}


def replace_inline_mermaid_blocks_with_export_html(
    content: str,
    visual_assets: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Swap Mermaid fences for PNG-backed HTML when a rasterized asset is available.

    ``visual_assets`` must already have passed through
    ``functions_export_visuals.normalize_visual_assets``; unvalidated input produces an
    empty asset map and leaves the content unchanged.
    """
    rendered_content = str(content or '')
    if not rendered_content or INLINE_MERMAID_EXPORT_REGEX.search(rendered_content) is None:
        return rendered_content

    asset_map = build_visual_asset_map(visual_assets, EXPORT_VISUAL_KIND_DIAGRAM)
    if not asset_map:
        return rendered_content

    def replace_match(match: re.Match) -> str:
        normalized_source = normalize_visual_source(match.group(1) or '')
        asset = asset_map.get(normalized_source)
        if not asset:
            return match.group(0)

        export_html = build_export_visual_html(
            EXPORT_VISUAL_KIND_DIAGRAM,
            asset.get('data_uri', ''),
            alt_text=asset.get('alt') or build_mermaid_alt_text(normalized_source),
            caption_text=asset.get('caption') or build_mermaid_caption_text(normalized_source),
        )
        return export_html or match.group(0)

    return INLINE_MERMAID_EXPORT_REGEX.sub(replace_match, rendered_content)


def extract_mermaid_sources(content: str) -> List[Dict[str, str]]:
    """Return the distinct Mermaid diagrams in content for the client to rasterize."""
    normalized_content = str(content or '')
    if not normalized_content or INLINE_MERMAID_EXPORT_REGEX.search(normalized_content) is None:
        return []

    sources: List[Dict[str, str]] = []
    seen_sources = set()

    for match in INLINE_MERMAID_EXPORT_REGEX.finditer(normalized_content):
        normalized_source = normalize_visual_source(match.group(1) or '')
        if not normalized_source or normalized_source in seen_sources:
            continue
        seen_sources.add(normalized_source)
        sources.append({
            'kind': EXPORT_VISUAL_KIND_DIAGRAM,
            'source': normalized_source,
            'alt': build_mermaid_alt_text(normalized_source),
            'caption': build_mermaid_caption_text(normalized_source),
        })

    return sources


def build_mermaid_alt_text(normalized_source: str) -> str:
    """Build accessible alt text from a diagram title or its declared type."""
    title = _extract_mermaid_title(normalized_source)
    if title:
        return title[:MERMAID_ALT_TEXT_MAX_LENGTH]

    type_label = MERMAID_DIAGRAM_TYPE_LABELS.get(_extract_mermaid_diagram_type(normalized_source))
    if type_label:
        return f'{type_label} diagram'
    return 'Mermaid diagram'


def build_mermaid_caption_text(normalized_source: str) -> str:
    """Return the diagram title as a caption, or an empty string when untitled."""
    return _extract_mermaid_title(normalized_source)[:MERMAID_CAPTION_MAX_LENGTH]


def _extract_mermaid_title(normalized_source: str) -> str:
    front_matter_match = MERMAID_FRONT_MATTER_REGEX.match(normalized_source)
    if front_matter_match:
        title_match = MERMAID_TITLE_REGEX.search(front_matter_match.group(1) or '')
        if title_match:
            return _clean_mermaid_text(title_match.group(1))

    body = _strip_mermaid_front_matter(normalized_source)
    title_match = MERMAID_TITLE_REGEX.search(body)
    if title_match:
        return _clean_mermaid_text(title_match.group(1))
    return ''


def _extract_mermaid_diagram_type(normalized_source: str) -> str:
    for line in _strip_mermaid_front_matter(normalized_source).split('\n'):
        candidate = line.strip()
        if not candidate or MERMAID_COMMENT_LINE_REGEX.match(line):
            continue
        first_token = re.split(r"[\s:;({]", candidate, maxsplit=1)[0]
        return first_token.strip().lower()
    return ''


def _strip_mermaid_front_matter(normalized_source: str) -> str:
    front_matter_match = MERMAID_FRONT_MATTER_REGEX.match(normalized_source)
    if not front_matter_match:
        return normalized_source
    return normalized_source[front_matter_match.end():]


def _clean_mermaid_text(value: Any) -> str:
    collapsed = ' '.join(str(value or '').split())
    return collapsed.strip('"\'')
