#!/usr/bin/env python3
# test_conversation_export.py
"""
Functional test for conversation export enhancements.
Version: 0.239.029
Implemented in: 0.239.022 (base), 0.239.023 (PDF export), 0.239.025 (tag formatting fix), 0.239.028 (summary token budget fix)

This test ensures conversation export now includes normalized and raw citations,
processing thoughts, transcript-style Markdown appendices, deleted-message filtering,
optional summary-intro metadata, PDF export with chat-bubble styling, and properly
formatted tag/classification rendering.
"""

import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from route_backend_conversation_export import (  # noqa: E402
    _build_citation_counts,
    _build_pdf_html_body,
    _collect_raw_citation_buckets,
    _conversation_to_markdown,
    _conversation_to_pdf_bytes,
    _filter_messages_for_export,
    _format_tag,
    _normalize_citations,
    _normalize_content,
    _pdf_bubble_class,
    _safe_filename,
    _sanitize_conversation,
    _sanitize_message,
    _truncate_for_summary,
)


def test_filter_messages_for_export():
    """Test that deleted and inactive-thread messages are excluded."""
    print("🔍 Testing export message filtering...")

    messages = [
        {'id': 'm1', 'role': 'user', 'content': 'Keep me', 'metadata': {}},
        {'id': 'm2', 'role': 'assistant', 'content': 'Delete me', 'metadata': {'is_deleted': True}},
        {'id': 'm3', 'role': 'assistant', 'content': 'Inactive retry', 'metadata': {'thread_info': {'active_thread': False}}},
        {'id': 'm4', 'role': 'assistant', 'content': 'Active reply', 'metadata': {'thread_info': {'active_thread': True}}},
        {'id': 'm5', 'role': 'user', 'content': 'Legacy message', 'metadata': {'thread_info': {}}},
    ]

    filtered = _filter_messages_for_export(messages)
    filtered_ids = [message['id'] for message in filtered]

    assert filtered_ids == ['m1', 'm4', 'm5'], f"Unexpected filtered IDs: {filtered_ids}"

    print("✅ Export message filtering test passed!")
    return True


def test_sanitize_message_with_citations_and_thoughts():
    """Test that sanitized messages retain normalized/raw citations and thoughts."""
    print("🔍 Testing message sanitization with citations and thoughts...")

    assistant_message = {
        'id': 'assistant-1',
        'role': 'assistant',
        'content': [{'type': 'text', 'text': 'Answer with evidence.'}],
        'timestamp': '2026-03-06T12:00:02Z',
        'augmented': True,
        'hybrid_citations': [
            {
                'file_name': 'paper.pdf',
                'page_number': 4,
                'citation_id': 'doc-1_4',
                'chunk_id': 'chunk-1',
                'metadata_type': 'abstract',
                'metadata_content': 'Study abstract text.'
            }
        ],
        'web_search_citations': [
            {'title': 'Example Source', 'url': 'https://example.com/source'}
        ],
        'agent_citations': [
            {
                'tool_name': 'web_lookup',
                'function_name': 'azure_ai_foundry_web_search',
                'plugin_name': 'azure_ai_foundry',
                'function_arguments': {'query': 'test'},
                'function_result': {'answer': 'done'},
                'timestamp': '2026-03-06T12:00:01Z',
                'success': True
            }
        ],
        'metadata': {
            'reasoning_effort': 'medium',
            'token_usage': {
                'prompt_tokens': 10,
                'completion_tokens': 20,
                'total_tokens': 30
            }
        },
        'model_deployment_name': 'gpt-5-mini',
        'hybridsearch_query': 'refined search query'
    }
    thoughts = [
        {
            'step_index': 0,
            'step_type': 'search',
            'content': 'Searching documents...',
            'detail': 'query=refined search query',
            'duration_ms': 123,
            'timestamp': '2026-03-06T12:00:01Z'
        }
    ]

    sanitized = _sanitize_message(assistant_message, sequence_index=2, transcript_index=2, thoughts=thoughts)

    assert sanitized['content_text'] == 'Answer with evidence.', 'Content should normalize list-based text.'
    assert sanitized['label'] == 'Turn 2', 'Transcript messages should use turn labels.'
    assert sanitized['citation_counts']['document'] == 1, 'Document citation count should be preserved.'
    assert sanitized['citation_counts']['web'] == 1, 'Web citation count should be preserved.'
    assert sanitized['citation_counts']['agent_tool'] == 1, 'Agent citation count should be preserved.'
    assert len(sanitized['citations']) == 3, 'Normalized citations should include all raw buckets.'
    assert sanitized['hybrid_citations'][0]['file_name'] == 'paper.pdf', 'Raw hybrid citations should be preserved.'
    assert sanitized['thoughts'][0]['step_type'] == 'search', 'Thoughts should be attached to the message.'
    assert sanitized['details']['generation']['model_deployment'] == 'gpt-5-mini', 'Generation details should include the model.'

    print("✅ Message sanitization test passed!")
    return True


def test_conversation_metadata_and_json_shape():
    """Test that conversation-level metadata captures counts for export JSON."""
    print("🔍 Testing conversation metadata and JSON shape...")

    messages = [
        {
            'id': 'u1',
            'role': 'user',
            'is_transcript_message': True,
            'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
            'thoughts': []
        },
        {
            'id': 'a1',
            'role': 'assistant',
            'is_transcript_message': True,
            'citation_counts': {'document': 1, 'web': 1, 'agent_tool': 0, 'legacy': 0, 'total': 2},
            'thoughts': [{'step_type': 'search'}]
        },
        {
            'id': 'f1',
            'role': 'file',
            'is_transcript_message': False,
            'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
            'thoughts': []
        }
    ]

    conversation = _sanitize_conversation(
        {
            'id': 'conv-123',
            'title': 'Export Test',
            'last_updated': '2026-03-06T12:00:00Z',
            'chat_type': 'personal',
            'tags': ['export', 'thoughts'],
            'context': ['workspace-a'],
            'classification': ['research'],
            'strict': False,
            'is_pinned': True,
            'scope_locked': True,
            'locked_contexts': ['workspace-a']
        },
        messages=messages,
        role_counts={'user': 1, 'assistant': 1, 'file': 1},
        citation_counts={'document': 1, 'web': 1, 'agent_tool': 0, 'legacy': 0, 'total': 2},
        thought_count=1
    )

    exported = [{'conversation': conversation, 'summary_intro': {'enabled': False, 'generated': False}, 'messages': messages}]
    parsed = json.loads(json.dumps(exported, indent=2, ensure_ascii=False, default=str))

    assert parsed[0]['conversation']['transcript_message_count'] == 2, 'Transcript count should exclude supplemental messages.'
    assert parsed[0]['conversation']['citation_counts']['total'] == 2, 'Conversation citation counts should be included.'
    assert parsed[0]['summary_intro']['enabled'] is False, 'Summary intro status should be included in JSON.'

    print("✅ Conversation metadata and JSON shape test passed!")
    return True


def test_markdown_export_structure():
    """Test transcript-style Markdown with appendices, citations, and thoughts."""
    print("🔍 Testing Markdown export structure...")

    entry = {
        'conversation': {
            'id': 'conv-123',
            'title': 'My Exported Chat',
            'last_updated': '2026-03-06T12:00:00Z',
            'chat_type': 'personal',
            'tags': ['science'],
            'classification': ['research'],
            'context': ['workspace-a'],
            'strict': False,
            'is_pinned': False,
            'scope_locked': True,
            'locked_contexts': ['workspace-a'],
            'message_count': 3,
            'message_counts_by_role': {'user': 1, 'assistant': 1, 'file': 1},
            'citation_counts': {'document': 1, 'web': 1, 'agent_tool': 1, 'legacy': 0, 'total': 3},
            'thought_count': 1
        },
        'summary_intro': {
            'enabled': True,
            'generated': True,
            'model_deployment': 'gpt-5-mini',
            'generated_at': '2026-03-06T12:05:00Z',
            'content': 'A concise abstract.\n\n- Key point one\n- Key point two',
            'error': None
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
                'timestamp': '2026-03-06T12:00:01Z',
                'content': 'What did the paper conclude?',
                'content_text': 'What did the paper conclude?',
                'details': {'interaction_mode': {'workspace_search': {'search_enabled': True, 'document_scope': 'personal'}}},
                'citations': [],
                'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
                'thoughts': [],
                'legacy_citations': [],
                'hybrid_citations': [],
                'web_search_citations': [],
                'agent_citations': []
            },
            {
                'id': 'a1',
                'role': 'assistant',
                'speaker_label': 'Assistant',
                'label': 'Turn 2',
                'sequence_index': 2,
                'transcript_index': 2,
                'is_transcript_message': True,
                'timestamp': '2026-03-06T12:00:02Z',
                'content': 'The paper concluded the intervention improved outcomes.',
                'content_text': 'The paper concluded the intervention improved outcomes.',
                'details': {'generation': {'model_deployment': 'gpt-5-mini', 'citation_counts': {'document': 1, 'web': 1, 'agent_tool': 1, 'legacy': 0, 'total': 3}}},
                'citations': [
                    {'citation_type': 'document', 'label': 'paper.pdf — Page 4', 'citation_id': 'doc-1_4', 'page_number': 4, 'classification': 'research', 'metadata_type': 'abstract', 'metadata_content': 'Study abstract text.'},
                    {'citation_type': 'web', 'label': 'Example Source', 'title': 'Example Source', 'url': 'https://example.com/source'},
                    {'citation_type': 'agent_tool', 'label': 'web_lookup'}
                ],
                'citation_counts': {'document': 1, 'web': 1, 'agent_tool': 1, 'legacy': 0, 'total': 3},
                'thoughts': [{'step_type': 'search', 'content': 'Searching documents...', 'detail': 'query=paper outcome', 'duration_ms': 88, 'timestamp': '2026-03-06T12:00:01Z'}],
                'legacy_citations': [],
                'hybrid_citations': [{'file_name': 'paper.pdf'}],
                'web_search_citations': [{'title': 'Example Source', 'url': 'https://example.com/source'}],
                'agent_citations': [{'tool_name': 'web_lookup', 'function_name': 'azure_ai_foundry_web_search', 'plugin_name': 'azure_ai_foundry', 'function_arguments': {'query': 'paper outcome'}, 'function_result': {'answer': 'done'}, 'timestamp': '2026-03-06T12:00:01Z', 'success': True}]
            },
            {
                'id': 'f1',
                'role': 'file',
                'speaker_label': 'File',
                'label': 'Message 3',
                'sequence_index': 3,
                'transcript_index': None,
                'is_transcript_message': False,
                'timestamp': '2026-03-06T12:00:00Z',
                'content': 'paper.pdf',
                'content_text': 'paper.pdf',
                'details': {'message_context': {'filename': 'paper.pdf'}},
                'citations': [],
                'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
                'thoughts': [],
                'legacy_citations': [],
                'hybrid_citations': [],
                'web_search_citations': [],
                'agent_citations': []
            }
        ]
    }

    markdown = _conversation_to_markdown(entry)

    assert '# My Exported Chat' in markdown, 'Markdown should include the title heading.'
    assert '## Abstract' in markdown, 'Markdown should include the abstract section.'
    assert '## Transcript' in markdown, 'Markdown should include the transcript section.'
    assert '## Appendix B — Message Details' in markdown, 'Markdown should include the message-details appendix.'
    assert '## Appendix C — References' in markdown, 'Markdown should include the references appendix.'
    assert '## Appendix D — Processing Thoughts' in markdown, 'Markdown should include the thoughts appendix.'
    assert '## Appendix E — Supplemental Messages' in markdown, 'Markdown should include supplemental messages.'
    assert 'paper.pdf — Page 4' in markdown, 'Document citation labels should appear in references.'
    assert 'Example Source' in markdown, 'Web citations should appear in references.'
    assert 'Searching documents...' in markdown, 'Thought content should appear in the appendix.'

    print("✅ Markdown export structure test passed!")
    return True


def test_safe_filename_and_zip_packaging():
    """Test filename sanitization and ZIP naming consistency."""
    print("🔍 Testing safe filename and ZIP packaging...")

    assert _safe_filename('Normal Title') == 'Normal_Title', 'Spaces should become underscores.'
    assert _safe_filename('File/With:Bad*Chars') == 'File_With_Bad_Chars', 'Unsafe characters should be replaced.'
    assert _safe_filename('A' * 100) == 'A' * 50, 'Long names should be truncated.'
    assert _safe_filename('') == 'Untitled', 'Empty titles should use Untitled.'

    exported = [
        {'conversation': {'id': 'conv-001-extra', 'title': 'First Chat'}, 'messages': []},
        {'conversation': {'id': 'conv-002-extra', 'title': 'Second Chat'}, 'messages': []}
    ]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for entry in exported:
            conversation = entry['conversation']
            safe_title = _safe_filename(conversation.get('title', 'Untitled'))
            conversation_id_short = conversation.get('id', 'unknown')[:8]
            archive.writestr(f"{safe_title}_{conversation_id_short}.json", json.dumps(entry))

    buffer.seek(0)
    with zipfile.ZipFile(buffer, 'r') as archive:
        names = archive.namelist()
        assert 'First_Chat_conv-001.json' in names, f"Unexpected ZIP entries: {names}"
        assert 'Second_Chat_conv-002.json' in names, f"Unexpected ZIP entries: {names}"

    print("✅ Safe filename and ZIP packaging test passed!")
    return True


def test_content_and_citation_helpers():
    """Test content normalization, citation normalization, and summary truncation helpers."""
    print("🔍 Testing helper utilities...")

    content_text = _normalize_content([
        {'type': 'text', 'text': 'Line one'},
        {'type': 'image_url', 'image_url': {'url': 'https://example.com/image.png'}},
        {'type': 'text', 'text': 'Line two'}
    ])
    assert content_text == 'Line one\n[Image]\nLine two', 'Content normalization should flatten list-based content.'

    raw_buckets = _collect_raw_citation_buckets({
        'citations': [{'title': 'Legacy'}],
        'hybrid_citations': [{'file_name': 'doc.pdf', 'page_number': 2}],
        'web_search_citations': [{'title': 'Web', 'url': 'https://example.com'}],
        'agent_citations': [{'tool_name': 'lookup'}]
    })
    normalized = _normalize_citations(raw_buckets)
    counts = _build_citation_counts(normalized)

    assert counts == {'document': 1, 'web': 1, 'agent_tool': 1, 'legacy': 1, 'total': 4}, f"Unexpected citation counts: {counts}"

    truncated = _truncate_for_summary('A' * 70000)
    assert '[... transcript truncated for export summary generation ...]' in truncated, 'Summary truncation marker should be inserted for long transcripts.'
    assert len(truncated) < 70000, 'Truncated summary source should be shorter than the original transcript.'

    print("✅ Helper utilities test passed!")
    return True


def test_pdf_export_generation():
    """Test PDF export generates valid HTML body and PDF bytes."""
    print("🔍 Testing PDF export generation...")

    entry = {
        'conversation': {
            'id': 'conv-pdf-001',
            'title': 'PDF Export Test',
            'last_updated': '2026-03-06T14:00:00Z',
            'chat_type': 'personal',
            'tags': ['pdf', 'test'],
            'classification': [],
            'context': [],
            'strict': False,
            'is_pinned': False,
            'scope_locked': False,
            'locked_contexts': [],
            'message_count': 2,
            'message_counts_by_role': {'user': 1, 'assistant': 1},
            'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
            'thought_count': 0
        },
        'summary_intro': {
            'enabled': False,
            'generated': False,
            'model_deployment': None,
            'generated_at': None,
            'content': '',
            'error': None
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
                'timestamp': '2026-03-06T14:00:01Z',
                'content': 'Hello, can you help me?',
                'content_text': 'Hello, can you help me?',
                'details': {},
                'citations': [],
                'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
                'thoughts': [],
                'legacy_citations': [],
                'hybrid_citations': [],
                'web_search_citations': [],
                'agent_citations': []
            },
            {
                'id': 'a1',
                'role': 'assistant',
                'speaker_label': 'Assistant',
                'label': 'Turn 2',
                'sequence_index': 2,
                'transcript_index': 2,
                'is_transcript_message': True,
                'timestamp': '2026-03-06T14:00:02Z',
                'content': 'Of course! How can I assist you today?',
                'content_text': 'Of course! How can I assist you today?',
                'details': {},
                'citations': [],
                'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
                'thoughts': [],
                'legacy_citations': [],
                'hybrid_citations': [],
                'web_search_citations': [],
                'agent_citations': []
            }
        ]
    }

    # Test HTML body generation
    html_body = _build_pdf_html_body(entry)
    assert '<h1>PDF Export Test</h1>' in html_body, 'HTML should contain the conversation title.'
    assert 'user-bubble' in html_body, 'HTML should contain user bubble CSS class.'
    assert 'assistant-bubble' in html_body, 'HTML should contain assistant bubble CSS class.'
    assert 'Transcript' in html_body, 'HTML should contain Transcript section.'
    assert 'Appendix A' in html_body, 'HTML should contain Appendix A.'
    assert 'Hello, can you help me?' in html_body, 'HTML should contain user message content.'
    assert 'Of course! How can I assist you today?' in html_body, 'HTML should contain assistant message content.'

    # Test bubble class helper
    assert _pdf_bubble_class('user') == 'user-bubble', 'User role should map to user-bubble.'
    assert _pdf_bubble_class('assistant') == 'assistant-bubble', 'Assistant role should map to assistant-bubble.'
    assert _pdf_bubble_class('system') == 'system-bubble', 'System role should map to system-bubble.'
    assert _pdf_bubble_class('file') == 'file-bubble', 'File role should map to file-bubble.'
    assert _pdf_bubble_class('unknown') == 'other-bubble', 'Unknown roles should map to other-bubble.'

    # Test PDF bytes generation
    pdf_bytes = _conversation_to_pdf_bytes(entry)
    assert isinstance(pdf_bytes, bytes), 'PDF output should be bytes.'
    assert pdf_bytes[:5] == b'%PDF-', f'PDF should start with %PDF- header, got: {pdf_bytes[:10]}'
    assert len(pdf_bytes) > 100, 'PDF should have a reasonable size.'

    print("✅ PDF export generation test passed!")
    return True


def test_tag_formatting():
    """Test that dict-style tags and classifications render as readable strings."""
    print("🔍 Testing tag/classification formatting...")

    # Category/value tag
    assert _format_tag({'category': 'model', 'value': 'gpt-5'}) == 'model: gpt-5'

    # Participant tag with name
    assert _format_tag({'category': 'participant', 'name': 'Alice', 'user_id': 'u1'}) == 'participant: Alice'

    # Participant tag with email fallback
    assert _format_tag({'category': 'participant', 'email': 'bob@test.com'}) == 'participant: bob@test.com'

    # Document tag with title
    assert _format_tag({'category': 'document', 'title': 'Study.pdf', 'document_id': 'd1'}) == 'document: Study.pdf'

    # Document tag with only document_id
    assert _format_tag({'category': 'document', 'document_id': 'd1'}) == 'document: d1'

    # Plain string tag (older data)
    assert _format_tag('science') == 'science'

    # Category only (no value)
    assert _format_tag({'category': 'semantic'}) == 'semantic'

    # Verify Markdown export uses formatted tags
    entry = {
        'conversation': {
            'id': 'conv-tags-001',
            'title': 'Tag Format Test',
            'last_updated': '2026-03-08T00:00:00Z',
            'chat_type': 'personal',
            'tags': [
                {'category': 'model', 'value': 'gpt-5'},
                {'category': 'semantic', 'value': 'cubesats'}
            ],
            'classification': [],
            'context': [],
            'strict': False,
            'is_pinned': False,
            'scope_locked': False,
            'locked_contexts': [],
            'message_count': 0,
            'message_counts_by_role': {},
            'citation_counts': {'document': 0, 'web': 0, 'agent_tool': 0, 'legacy': 0, 'total': 0},
            'thought_count': 0
        },
        'summary_intro': {'enabled': False, 'generated': False},
        'messages': []
    }

    md = _conversation_to_markdown(entry)
    assert 'model: gpt-5' in md, f'Markdown should contain formatted tag, got: {md[:500]}'
    assert "{'category'" not in md, 'Markdown should not contain raw dict strings'

    html = _build_pdf_html_body(entry)
    assert 'model: gpt-5' in html, f'PDF HTML should contain formatted tag'
    assert "{'category'" not in html, 'PDF HTML should not contain raw dict strings'

    print("✅ Tag formatting test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_filter_messages_for_export,
        test_sanitize_message_with_citations_and_thoughts,
        test_conversation_metadata_and_json_shape,
        test_markdown_export_structure,
        test_safe_filename_and_zip_packaging,
        test_content_and_citation_helpers,
        test_pdf_export_generation,
        test_tag_formatting,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"❌ {test.__name__} failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
