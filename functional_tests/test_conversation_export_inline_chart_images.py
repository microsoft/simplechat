#!/usr/bin/env python3
"""Focused regression tests for inline chart graphics in conversation exports."""

import io
import os
import sys
import zipfile

import fitz


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'application', 'single_app'))

from route_backend_conversation_export import (  # noqa: E402
    _conversation_to_markdown,
    _conversation_to_pdf_bytes,
    _message_to_docx_bytes,
)
from semantic_kernel_plugins.chart_plugin import ChartPlugin  # noqa: E402


def _build_sample_chart_markdown() -> str:
    plugin = ChartPlugin({'chart_capabilities': {'bar': True}})
    result = plugin.create_chart(
        chart_type='bar',
        chart_data_json='{"rows":[{"airline":"ASA","turnaround":55.86},{"airline":"NKS","turnaround":56.55},{"airline":"DAL","turnaround":56.89}],"xField":"airline","yFields":["turnaround"]}',
        title='Average Gate Turnaround Time',
        subtitle='Lower is better',
        description='Airlines ranked by shortest average gate turnaround time.',
    )
    assert result['success'] is True, result
    return result['chart_markdown']


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
    chart_markdown = _build_sample_chart_markdown()
    entry = _build_export_entry(chart_markdown)

    markdown = _conversation_to_markdown(entry)

    assert 'data:image/png;base64,' in markdown, markdown
    assert '```simplechart' not in markdown, markdown
    assert 'Average Gate Turnaround Time' in markdown, markdown


def test_pdf_export_contains_rendered_chart_image():
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