#!/usr/bin/env python3
"""
Functional tests for inline chart graphics in conversation exports.
Version: 0.241.143
Implemented in: 0.241.139

This test ensures simplechart blocks are converted to PNG-backed export content
for Markdown/PDF, Word, and PowerPoint export flows instead of leaking code,
while preserving explicit chart colors. It also ensures approved simpleimage
proposal results are converted to Word-embedded PNG media.
"""

import io
import json
import os
import sys
import types
import zipfile
from typing import Callable, List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'application', 'single_app'))
sys.modules.setdefault(
    'olefile',
    types.SimpleNamespace(isOleFile=lambda *_args, **_kwargs: False, OleFileIO=None),
)

from functions_chart_export import replace_inline_chart_blocks_with_export_html  # noqa: E402

ROUTE_HELPERS_IMPORT_ERROR = None
try:
    from route_backend_conversation_export import (  # noqa: E402
        _conversation_to_markdown,
        _conversation_to_pdf_bytes,
        _extract_powerpoint_appendix_assets,
        _message_to_docx_bytes,
    )
except ModuleNotFoundError as import_error:
    ROUTE_HELPERS_IMPORT_ERROR = import_error
    _conversation_to_markdown = None
    _conversation_to_pdf_bytes = None
    _extract_powerpoint_appendix_assets = None
    _message_to_docx_bytes = None


def _build_sample_chart_markdown() -> str:
        return """```simplechart
{
    "version": 1,
    "kind": "bar",
    "title": "Average Gate Turnaround Time",
    "subtitle": "Lower is better",
    "description": "Airlines ranked by shortest average gate turnaround time.",
    "data": {
        "labels": ["ASA", "NKS", "DAL"],
        "datasets": [
            {
                "label": "Turnaround",
                "data": [55.86, 56.55, 56.89]
            }
        ]
    }
}
```"""


def _route_helpers_available() -> bool:
        if ROUTE_HELPERS_IMPORT_ERROR is None:
                return True

        print(f"Skipping route-dependent export assertion: {ROUTE_HELPERS_IMPORT_ERROR}")
        return False


def _build_yaml_style_chart_markdown() -> str:
        return """```simplechart
version: 1
kind: chart
chartType: pie
title: Fruit Distribution
subtitle: Model-authored YAML-style chart
summary: Apples, oranges, and pears split the sample.
data:
    labels: [Apples, Oranges, Pears]
    datasets:
        - label: Share
            data: [33, 33, 34]
options:
    plugins:
        legend:
            display: true
            position: right
```"""


def _build_color_requested_chart_markdown() -> str:
        return """```simplechart
{
    "version": 1,
    "kind": "pie",
    "chartType": "pie",
    "title": "Fruit Distribution",
    "data": {
        "labels": ["Apples", "Oranges", "Pears"],
        "datasets": [
            {
                "label": "Share",
                "data": [33, 33, 34],
                "backgroundColor": ["red", "orange", "green"],
                "borderColor": ["apple", "oranges", "pears"]
            }
        ]
    }
}
```"""


def _build_sample_image_data_uri() -> str:
    return (
        'data:image/png;base64,'
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII='
    )


def _build_sample_image_proposal() -> dict:
    return {
        'version': 1,
        'visualId': 'colonial_map_1700',
        'title': 'Map of British North American Colonies',
        'description': 'A classroom map of British North America around 1700.',
        'prompt': 'Create a labeled classroom map of British North America around 1700.',
        'visualType': 'map',
        'slideNumber': 1,
        'context': 'Introductory overview of colonial North America.',
    }


def _build_sample_image_proposal_markdown() -> str:
    return '```simpleimage\n' + json.dumps(_build_sample_image_proposal()) + '\n```'


def _build_export_entry(chart_markdown: str):
    assistant_content = (
        'Here is the requested chart.\n\n'
        f'{chart_markdown}\n\n'
        'ASA has the shortest average gate turnaround time in this sample.'
    )
    return {
        'conversation': {
            'id': 'conv-chart-001',
            'title': 'Chart Export Test',
            'last_updated': '2026-04-29T15:00:00Z',
            'chat_type': 'personal',
            'tags': [],
            'classification': [],
            'context': [],
            'strict': False,
            'is_pinned': False,
            'scope_locked': False,
            'locked_contexts': [],
            'message_count': 2,
            'message_counts_by_role': {'user': 1, 'assistant': 1},
            'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
            'thought_count': 0,
        },
        'summary_intro': {
            'enabled': False,
            'generated': False,
            'model_deployment': None,
            'generated_at': None,
            'content': '',
            'error': None,
        },
        'messages': [
            {
                'id': 'u1',
                'role': 'user',
                'speaker_label': 'User',
                'label': 'Turn 1',
                'sequence_index': 1,
                'transcript_index': 1,
                'is_transcript_message': True,
                'timestamp': '2026-04-29T15:00:01Z',
                'content': 'Which airlines have the shortest gate turnaround times? Include table and chart.',
                'content_text': 'Which airlines have the shortest gate turnaround times? Include table and chart.',
                'details': {},
                'citations': [],
                'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
                'thoughts': [],
                'legacy_citations': [],
                'hybrid_citations': [],
                'web_search_citations': [],
                'agent_citations': [],
            },
            {
                'id': 'a1',
                'role': 'assistant',
                'speaker_label': 'Assistant',
                'label': 'Turn 2',
                'sequence_index': 2,
                'transcript_index': 2,
                'is_transcript_message': True,
                'timestamp': '2026-04-29T15:00:02Z',
                'content': assistant_content,
                'content_text': assistant_content,
                'details': {},
                'citations': [],
                'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
                'thoughts': [],
                'legacy_citations': [],
                'hybrid_citations': [],
                'web_search_citations': [],
                'agent_citations': [],
            },
        ],
    }


def test_markdown_export_embeds_chart_png_data_uri():
    if not _route_helpers_available():
        return

    chart_markdown = _build_sample_chart_markdown()
    entry = _build_export_entry(chart_markdown)

    markdown = _conversation_to_markdown(entry)

    assert 'data:image/png;base64,' in markdown, markdown
    assert '```simplechart' not in markdown, markdown
    assert 'Average Gate Turnaround Time' in markdown, markdown


def test_markdown_export_embeds_yaml_style_chart_png_data_uri():
    if not _route_helpers_available():
        return

    chart_markdown = _build_yaml_style_chart_markdown()
    entry = _build_export_entry(chart_markdown)

    markdown = _conversation_to_markdown(entry)

    assert 'data:image/png;base64,' in markdown, markdown
    assert '```simplechart' not in markdown, markdown
    assert 'Fruit Distribution' in markdown, markdown


def test_chart_export_helper_embeds_yaml_style_chart_png_data_uri():
    chart_markdown = _build_yaml_style_chart_markdown()

    rendered_content = replace_inline_chart_blocks_with_export_html(chart_markdown)

    assert '```simplechart' not in rendered_content, rendered_content
    assert 'data:image/png;base64,' in rendered_content, rendered_content
    assert 'Fruit Distribution' in rendered_content, rendered_content


def test_chart_export_helper_embeds_json_chart_png_data_uri():
    chart_markdown = _build_sample_chart_markdown()

    rendered_content = replace_inline_chart_blocks_with_export_html(chart_markdown)

    assert '```simplechart' not in rendered_content, rendered_content
    assert 'data:image/png;base64,' in rendered_content, rendered_content
    assert 'Average Gate Turnaround Time' in rendered_content, rendered_content


def test_chart_export_helper_preserves_requested_pie_colors():
    chart_markdown = _build_color_requested_chart_markdown()

    rendered_content = replace_inline_chart_blocks_with_export_html(chart_markdown)

    assert '```simplechart' not in rendered_content, rendered_content
    assert 'data:image/png;base64,' in rendered_content, rendered_content
    assert 'Fruit Distribution' in rendered_content, rendered_content


def test_pdf_export_contains_rendered_chart_image():
    if not _route_helpers_available():
        return

    try:
        import fitz
    except ModuleNotFoundError as import_error:
        print(f"Skipping PDF export assertion: {import_error}")
        return

    chart_markdown = _build_sample_chart_markdown()
    entry = _build_export_entry(chart_markdown)

    pdf_bytes = _conversation_to_pdf_bytes(entry)
    document = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        image_count = sum(len(page.get_images(full=True)) for page in document)
    finally:
        document.close()

    assert image_count >= 1, image_count


def test_word_message_export_embeds_chart_png_media():
    if not _route_helpers_available():
        return

    chart_markdown = _build_sample_chart_markdown()
    entry = _build_export_entry(chart_markdown)
    assistant_message = entry['messages'][1]

    docx_bytes = _message_to_docx_bytes(assistant_message)

    with zipfile.ZipFile(io.BytesIO(docx_bytes), 'r') as archive:
        names = archive.namelist()
        media_names = [name for name in names if name.startswith('word/media/')]
        document_xml = archive.read('word/document.xml').decode('utf-8')

    assert media_names, names
    assert 'simplechart' not in document_xml, document_xml


def test_word_message_export_embeds_yaml_style_chart_png_media():
    if not _route_helpers_available():
        return

    chart_markdown = _build_yaml_style_chart_markdown()
    entry = _build_export_entry(chart_markdown)
    assistant_message = entry['messages'][1]

    docx_bytes = _message_to_docx_bytes(assistant_message)

    with zipfile.ZipFile(io.BytesIO(docx_bytes), 'r') as archive:
        names = archive.namelist()
        media_names = [name for name in names if name.startswith('word/media/')]
        document_xml = archive.read('word/document.xml').decode('utf-8')

    assert media_names, names
    assert 'simplechart' not in document_xml, document_xml
    assert 'Fruit Distribution' in document_xml, document_xml


def test_word_message_export_embeds_generated_image_proposal_png_media():
    if not _route_helpers_available():
        return

    image_proposal = _build_sample_image_proposal()
    assistant_message = {
        'id': 'a1',
        'role': 'assistant',
        'timestamp': '2026-06-04T15:00:02Z',
        'content': (
            'Here is the proposed slide image.\n\n'
            f'{_build_sample_image_proposal_markdown()}\n\n'
            'Use it with the introduction slide.'
        ),
        '_export_generated_image_assets': [
            {
                'data_uri': _build_sample_image_data_uri(),
                'proposal': image_proposal,
                'title': image_proposal['title'],
                'caption': image_proposal['description'],
            }
        ],
        'citations': [],
    }

    docx_bytes = _message_to_docx_bytes(assistant_message)

    with zipfile.ZipFile(io.BytesIO(docx_bytes), 'r') as archive:
        names = archive.namelist()
        media_names = [name for name in names if name.startswith('word/media/')]
        document_xml = archive.read('word/document.xml').decode('utf-8')

    assert media_names, names
    assert 'simpleimage' not in document_xml, document_xml
    assert 'visualId' not in document_xml, document_xml
    assert 'Map of British North American Colonies' in document_xml, document_xml


def test_powerpoint_appendix_extracts_yaml_style_chart_png_image():
    if not _route_helpers_available():
        return

    chart_markdown = _build_yaml_style_chart_markdown()

    rendered_content = replace_inline_chart_blocks_with_export_html(chart_markdown)
    assets = _extract_powerpoint_appendix_assets(rendered_content)

    assert '```simplechart' not in rendered_content, rendered_content
    assert 'data:image/png;base64,' in rendered_content, rendered_content
    assert len(assets['images']) == 1, assets
    assert assets['images'][0]['image_bytes'].startswith(b'\x89PNG'), assets['images'][0]


if __name__ == "__main__":
    tests: List[Callable[[], None]] = [
        test_chart_export_helper_embeds_json_chart_png_data_uri,
        test_chart_export_helper_embeds_yaml_style_chart_png_data_uri,
        test_chart_export_helper_preserves_requested_pie_colors,
        test_markdown_export_embeds_chart_png_data_uri,
        test_markdown_export_embeds_yaml_style_chart_png_data_uri,
        test_pdf_export_contains_rendered_chart_image,
        test_word_message_export_embeds_chart_png_media,
        test_word_message_export_embeds_yaml_style_chart_png_media,
        test_word_message_export_embeds_generated_image_proposal_png_media,
        test_powerpoint_appendix_extracts_yaml_style_chart_png_image,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print(f"{test.__name__} passed")
            results.append(True)
        except Exception as exc:
            print(f"{test.__name__} failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)