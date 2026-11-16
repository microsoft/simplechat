#!/usr/bin/env python3
"""
Functional tests for Mermaid and TeX graphics in exports.
Version: 0.261.027
Implemented in: 0.261.027

This test ensures TeX math blocks are rendered to PNG server-side, and that
browser-rasterized Mermaid diagrams supplied as `visual_assets` are embedded into
Markdown, PDF, Word, PowerPoint and email exports. It also ensures a Mermaid fence
with no rasterized asset is left untouched, and that malformed assets are rejected
before anything reaches a generated document.
"""

import base64
import io
import os
import sys
import types
import zipfile
from typing import Any, Callable, Dict, List
from unittest import mock


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'application', 'single_app'))
sys.modules.setdefault(
    'olefile',
    types.SimpleNamespace(isOleFile=lambda *_args, **_kwargs: False, OleFileIO=None),
)

from functions_export_visuals import (  # noqa: E402
    EXPORT_VISUAL_KIND_DIAGRAM,
    normalize_visual_assets,
    normalize_visual_source,
    replace_inline_visual_blocks_with_export_html,
)
from functions_mermaid_export import extract_mermaid_sources  # noqa: E402
from functions_tex_export import replace_inline_tex_blocks_with_export_html  # noqa: E402


MERMAID_SOURCE = 'graph TD\n    A[Start] --> B[End]'
MERMAID_MARKDOWN = f'```mermaid\n{MERMAID_SOURCE}\n```'
SAMPLE_CHART_MARKDOWN = """```simplechart
{
    "version": 1,
    "kind": "bar",
    "title": "Quarterly Sales",
    "data": {
        "labels": ["Q1", "Q2"],
        "datasets": [{"label": "Revenue", "data": [12, 18]}]
    }
}
```"""


def _import_route_helpers():
    """Import the export route module, stubbing Cosmos when Azure config is absent."""
    try:
        import route_backend_conversation_export as route_module

        return route_module, None
    except Exception:
        pass

    try:
        import azure.cosmos as azure_cosmos_module

        os.environ.setdefault('AZURE_COSMOS_ENDPOINT', 'https://example.documents.azure.com:443/')
        os.environ.setdefault('AZURE_COSMOS_KEY', 'ZHVtbXkta2V5LWZvci1sb2NhbC10ZXN0aW5n')
        os.environ.setdefault('AZURE_COSMOS_AUTHENTICATION_TYPE', 'key')

        with mock.patch.object(azure_cosmos_module, 'CosmosClient', mock.MagicMock()):
            import route_backend_conversation_export as route_module

        return route_module, None
    except Exception as import_error:
        return None, import_error


ROUTE_MODULE, ROUTE_IMPORT_ERROR = _import_route_helpers()


def _route_helpers_available() -> bool:
    if ROUTE_MODULE is not None:
        return True

    print(f"Skipping route-dependent export assertion: {ROUTE_IMPORT_ERROR}")
    return False


def _build_png_data_uri(width: int = 64, height: int = 32) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (30, 90, 160)).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def _build_diagram_assets(content: str = MERMAID_MARKDOWN) -> List[Dict[str, Any]]:
    sources = extract_mermaid_sources(content)
    return normalize_visual_assets([
        {
            'kind': EXPORT_VISUAL_KIND_DIAGRAM,
            'source': source['source'],
            'data_uri': _build_png_data_uri(),
            'alt': source['alt'],
            'caption': source['caption'],
        }
        for source in sources
    ])


def _build_message(content: str) -> Dict[str, Any]:
    return {
        'role': 'assistant',
        'content': content,
        'timestamp': '2026-01-01T00:00:00Z',
    }


def _build_conversation_entry(content: str) -> Dict[str, Any]:
    return {
        'conversation': {
            'id': 'conversation-1',
            'title': 'Export Test',
            'last_updated': '2026-01-01T00:00:00Z',
            'chat_type': 'personal',
            'message_count': 1,
        },
        'messages': [{
            'role': 'assistant',
            'label': 'Assistant',
            'speaker_label': 'Assistant',
            'timestamp': '2026-01-01T00:00:00Z',
            'content_text': content,
            'is_transcript_message': True,
        }],
        'summary_intro': {},
    }


def test_tex_blocks_render_to_png_data_uris():
    """Fenced, dollar and bracket display math all become PNG-backed HTML."""
    print("Testing TeX block rendering...")

    tex_variants = [
        '```math\nE = mc^2\n```',
        '```latex\n\\frac{a}{b}\n```',
        '```tex\n\\sum_{i=1}^{n} i\n```',
        '$$\\int_0^1 x^2 dx$$',
        '\\[a^2 + b^2 = c^2\\]',
    ]

    for tex_markdown in tex_variants:
        rendered = replace_inline_tex_blocks_with_export_html(tex_markdown)
        assert 'export-inline-math' in rendered, tex_markdown
        assert 'data:image/png;base64,' in rendered, tex_markdown

    print("TeX block rendering passed!")


def test_tex_detection_ignores_currency_and_code_fences():
    """Prices and fenced code must never be mistaken for math."""
    print("Testing TeX false-positive guards...")

    unchanged_inputs = [
        'The unit costs $100 to $200 depending on volume.',
        '```python\nprice_label = "$$100"\n```',
        SAMPLE_CHART_MARKDOWN,
        MERMAID_MARKDOWN,
    ]

    for source in unchanged_inputs:
        assert replace_inline_tex_blocks_with_export_html(source) == source, source

    print("TeX false-positive guards passed!")


def test_unsupported_tex_is_left_unchanged():
    """Environments mathtext cannot parse keep their original markup."""
    print("Testing unsupported TeX fallback...")

    unsupported = '$$\\begin{align} a &= b \\\\ c &= d \\end{align}$$'
    assert replace_inline_tex_blocks_with_export_html(unsupported) == unsupported

    print("Unsupported TeX fallback passed!")


def test_mermaid_fence_survives_without_a_rasterized_asset():
    """A Mermaid fence stays a code block when the client sent no PNG for it."""
    print("Testing Mermaid degradation without assets...")

    rendered = replace_inline_visual_blocks_with_export_html(MERMAID_MARKDOWN)
    assert rendered == MERMAID_MARKDOWN, rendered

    print("Mermaid degradation passed!")


def test_mermaid_asset_replaces_matching_fence():
    """A rasterized diagram replaces the fence it was produced from."""
    print("Testing Mermaid asset substitution...")

    assets = _build_diagram_assets()
    assert len(assets) == 1, assets

    rendered = replace_inline_visual_blocks_with_export_html(MERMAID_MARKDOWN, assets)
    assert '```mermaid' not in rendered, rendered
    assert 'export-inline-diagram' in rendered, rendered
    assert 'data:image/png;base64,' in rendered, rendered

    print("Mermaid asset substitution passed!")


def test_mermaid_asset_for_a_different_diagram_is_not_substituted():
    """An asset only replaces the exact diagram source it was rendered from."""
    print("Testing Mermaid source matching...")

    mismatched_assets = normalize_visual_assets([{
        'kind': EXPORT_VISUAL_KIND_DIAGRAM,
        'source': 'sequenceDiagram\n    Alice->>Bob: Hi',
        'data_uri': _build_png_data_uri(),
    }])
    assert len(mismatched_assets) == 1, mismatched_assets

    rendered = replace_inline_visual_blocks_with_export_html(MERMAID_MARKDOWN, mismatched_assets)
    assert rendered == MERMAID_MARKDOWN, rendered

    print("Mermaid source matching passed!")


def test_client_source_normalization_matches_fence_normalization():
    """Indentation and trailing blank lines must not break asset matching."""
    print("Testing visual source normalization...")

    padded_source = '\n\ngraph TD\n    A[Start] --> B[End]   \n\n'
    assert normalize_visual_source(padded_source) == MERMAID_SOURCE

    assets = normalize_visual_assets([{
        'kind': EXPORT_VISUAL_KIND_DIAGRAM,
        'source': padded_source,
        'data_uri': _build_png_data_uri(),
    }])
    rendered = replace_inline_visual_blocks_with_export_html(MERMAID_MARKDOWN, assets)
    assert 'export-inline-diagram' in rendered, rendered

    print("Visual source normalization passed!")


def test_malformed_visual_assets_are_rejected():
    """Anything that is not a real PNG is dropped before it reaches a document."""
    print("Testing visual asset validation...")

    rejected_assets = [
        {'kind': 'diagram', 'source': 'graph TD', 'data_uri': 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='},
        {'kind': 'diagram', 'source': 'graph TD', 'data_uri': 'data:image/png;base64,bm90LWEtcG5n'},
        {'kind': 'diagram', 'source': 'graph TD', 'data_uri': 'javascript:alert(1)'},
        {'kind': 'diagram', 'source': 'graph TD', 'data_uri': 'https://example.com/diagram.png'},
        {'kind': 'script', 'source': 'graph TD', 'data_uri': _build_png_data_uri()},
        {'kind': 'diagram', 'source': '', 'data_uri': _build_png_data_uri()},
        {'kind': 'diagram', 'source': 'graph TD'},
        'not-a-dict',
        None,
    ]
    assert normalize_visual_assets(rejected_assets) == [], normalize_visual_assets(rejected_assets)
    assert normalize_visual_assets('not-a-list') == []
    assert normalize_visual_assets(None) == []

    print("Visual asset validation passed!")


def test_visual_asset_count_is_capped():
    """A caller cannot push an unbounded number of images into one export."""
    print("Testing visual asset count cap...")

    oversized_batch = [
        {
            'kind': EXPORT_VISUAL_KIND_DIAGRAM,
            'source': f'graph TD\n    A{index} --> B{index}',
            'data_uri': _build_png_data_uri(),
        }
        for index in range(12)
    ]
    assert len(normalize_visual_assets(oversized_batch, max_count=5)) == 5

    print("Visual asset count cap passed!")


def test_tex_fence_language_must_match_exactly():
    """A fence language that merely starts with math/latex/tex must not be consumed."""
    print("Testing TeX fence language matching...")

    lookalike_fences = [
        '```text\n2026-01-01 INFO Starting worker\n```',
        '```Text\nplain prose here\n```',
        '```mathematica\nPlot[x, {x, 0, 1}]\n```',
        '```texttt\nmonospace sample\n```',
        '```latexmk\nbuild config\n```',
    ]

    for fence in lookalike_fences:
        assert replace_inline_tex_blocks_with_export_html(fence) == fence, fence
        assert replace_inline_visual_blocks_with_export_html(fence) == fence, fence

    print("TeX fence language matching passed!")


def test_mermaid_fence_language_must_match_exactly():
    """A fence language that merely starts with mermaid must not be scanned."""
    print("Testing Mermaid fence language matching...")

    assert extract_mermaid_sources('```mermaidjs\ngraph TD\n    A --> B\n```') == []
    assert len(extract_mermaid_sources(MERMAID_MARKDOWN)) == 1

    print("Mermaid fence language matching passed!")


def test_oversized_tex_layout_is_rejected():
    """Spacing commands must not be able to demand an enormous raster."""
    print("Testing TeX layout size guard...")

    oversized_variants = [
        '$$\\hspace{20000} x$$',
        '$$\\hspace{100000} x$$',
        '```math\n\\hspace{500000} y\n```',
    ]

    for source in oversized_variants:
        assert replace_inline_tex_blocks_with_export_html(source) == source, source

    reasonable = replace_inline_tex_blocks_with_export_html('$$\\hspace{4} x$$')
    assert 'export-inline-math' in reasonable, reasonable

    print("TeX layout size guard passed!")


def test_markdown_export_embeds_mermaid_and_tex_images():
    """Conversation Markdown carries diagrams, formulas and charts as images."""
    print("Testing Markdown conversation export...")

    if not _route_helpers_available():
        return

    content = f'{MERMAID_MARKDOWN}\n\n$$E = mc^2$$\n\n{SAMPLE_CHART_MARKDOWN}'
    markdown_output = ROUTE_MODULE._conversation_to_markdown(
        _build_conversation_entry(content),
        visual_assets=_build_diagram_assets(content),
    )

    assert 'export-inline-diagram' in markdown_output, markdown_output[:400]
    assert 'export-inline-math' in markdown_output, markdown_output[:400]
    assert 'export-inline-chart' in markdown_output, markdown_output[:400]
    assert '```mermaid' not in markdown_output, markdown_output[:400]

    print("Markdown conversation export passed!")


def test_pdf_export_contains_rendered_mermaid_and_tex_images():
    """Conversation PDF embeds one image per rendered visual."""
    print("Testing PDF conversation export...")

    if not _route_helpers_available():
        return

    try:
        import fitz
    except ModuleNotFoundError as import_error:
        print(f"Skipping PDF export assertion: {import_error}")
        return

    content = f'{MERMAID_MARKDOWN}\n\n$$E = mc^2$$'
    pdf_bytes = ROUTE_MODULE._conversation_to_pdf_bytes(
        _build_conversation_entry(content),
        visual_assets=_build_diagram_assets(content),
    )

    document = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        image_count = sum(len(page.get_images(full=True)) for page in document)
    finally:
        document.close()

    assert image_count >= 2, image_count

    print("PDF conversation export passed!")


def test_word_message_export_embeds_mermaid_and_tex_media():
    """Word documents embed the diagram and formula as real media parts."""
    print("Testing Word message export...")

    if not _route_helpers_available():
        return

    content = f'{MERMAID_MARKDOWN}\n\n$$E = mc^2$$'
    document_bytes = ROUTE_MODULE._message_to_docx_bytes(
        _build_message(content),
        visual_assets=_build_diagram_assets(content),
    )

    with zipfile.ZipFile(io.BytesIO(document_bytes)) as archive:
        media_names = [name for name in archive.namelist() if name.startswith('word/media/')]

    assert len(media_names) >= 2, media_names

    print("Word message export passed!")


def test_powerpoint_appendix_extracts_mermaid_and_tex_images():
    """PowerPoint picks up the new visual kinds for its appendix slides."""
    print("Testing PowerPoint appendix extraction...")

    if not _route_helpers_available():
        return

    content = f'{MERMAID_MARKDOWN}\n\n$$E = mc^2$$'
    rendered_content = ROUTE_MODULE._render_message_export_content(
        _build_message(content),
        visual_assets=_build_diagram_assets(content),
    )
    appendix_assets = ROUTE_MODULE._extract_powerpoint_appendix_assets(rendered_content)

    assert len(appendix_assets['images']) >= 2, appendix_assets['images']
    for image_asset in appendix_assets['images']:
        assert image_asset['image_bytes'], image_asset

    print("PowerPoint appendix extraction passed!")


def test_email_draft_attaches_mermaid_and_tex_pngs():
    """Email drafts export the new visual kinds as downloadable PNG references."""
    print("Testing email draft export...")

    if not _route_helpers_available():
        return

    content = f'{MERMAID_MARKDOWN}\n\n$$E = mc^2$$'
    draft_payload = ROUTE_MODULE._message_to_email_draft_payload(
        message=_build_message(content),
        settings={},
        summary_model_deployment='',
        visual_assets=_build_diagram_assets(content),
    )

    attachment_types = {attachment['visual_type'] for attachment in draft_payload['attachments']}
    assert 'diagram' in attachment_types, draft_payload['attachments']
    assert 'math' in attachment_types, draft_payload['attachments']

    filenames = [attachment['filename'] for attachment in draft_payload['attachments']]
    assert any(name.startswith('message_diagram_') for name in filenames), filenames
    assert any(name.startswith('message_formula_') for name in filenames), filenames

    body = draft_payload['body']
    assert 'base64,' not in body, body[:400]
    assert '```mermaid' not in body, body[:400]
    for filename in filenames:
        assert filename in body, body[:400]

    print("Email draft export passed!")


def test_chart_export_markup_is_unchanged_by_the_shared_builder():
    """The shared wrapper builder must not alter existing chart output."""
    print("Testing chart export markup stability...")

    rendered = replace_inline_visual_blocks_with_export_html(SAMPLE_CHART_MARKDOWN)
    assert '<div class="export-inline-chart">' in rendered, rendered[:200]
    assert '<p class="export-inline-chart-caption">' in rendered, rendered[:400]
    assert 'alt="Quarterly Sales"' in rendered, rendered[:400]

    print("Chart export markup stability passed!")


if __name__ == "__main__":
    tests: List[Callable[[], None]] = [
        test_tex_blocks_render_to_png_data_uris,
        test_tex_detection_ignores_currency_and_code_fences,
        test_tex_fence_language_must_match_exactly,
        test_mermaid_fence_language_must_match_exactly,
        test_oversized_tex_layout_is_rejected,
        test_unsupported_tex_is_left_unchanged,
        test_mermaid_fence_survives_without_a_rasterized_asset,
        test_mermaid_asset_replaces_matching_fence,
        test_mermaid_asset_for_a_different_diagram_is_not_substituted,
        test_client_source_normalization_matches_fence_normalization,
        test_malformed_visual_assets_are_rejected,
        test_visual_asset_count_is_capped,
        test_markdown_export_embeds_mermaid_and_tex_images,
        test_pdf_export_contains_rendered_mermaid_and_tex_images,
        test_word_message_export_embeds_mermaid_and_tex_media,
        test_powerpoint_appendix_extracts_mermaid_and_tex_images,
        test_email_draft_attaches_mermaid_and_tex_pngs,
        test_chart_export_markup_is_unchanged_by_the_shared_builder,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
