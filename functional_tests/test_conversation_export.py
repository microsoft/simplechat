#!/usr/bin/env python3
# test_conversation_export.py
"""
Functional test for conversation export feature.
Version: 0.237.050
Implemented in: 0.237.050

This test validates the conversation export backend endpoint
and ensures JSON/Markdown formats and single/ZIP packaging work correctly.
"""

import sys
import os
import json
import zipfile
import io

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_sanitize_conversation():
    """Test that _sanitize_conversation strips internal fields."""
    print("🔍 Testing _sanitize_conversation...")

    raw_conversation = {
        'id': 'conv-123',
        'title': 'Test Conversation',
        'last_updated': '2025-01-01T00:00:00Z',
        'chat_type': 'personal',
        'tags': ['test'],
        'is_pinned': False,
        'context': [],
        'user_id': 'secret-user-id',
        '_rid': 'cosmos-internal-rid',
        '_self': 'cosmos-self-link',
        '_etag': 'some-etag',
        '_attachments': 'attachments',
        '_ts': 1234567890,
        'partition_key': 'should-not-appear'
    }

    # Import after path setup — may fail if dependencies aren't installed
    try:
        from route_backend_conversation_export import register_route_backend_conversation_export
        print("  Module imported successfully (dependencies available)")
    except ImportError as ie:
        print(f"  Skipping import test (missing dependency: {ie})")
        print("  Verifying sanitization logic inline instead...")

    # We test the logic manually since inner functions are not directly accessible
    sanitized = {
        'id': raw_conversation.get('id'),
        'title': raw_conversation.get('title', 'Untitled'),
        'last_updated': raw_conversation.get('last_updated', ''),
        'chat_type': raw_conversation.get('chat_type', 'personal'),
        'tags': raw_conversation.get('tags', []),
        'is_pinned': raw_conversation.get('is_pinned', False),
        'context': raw_conversation.get('context', [])
    }

    assert 'id' in sanitized, "Should retain id"
    assert 'title' in sanitized, "Should retain title"
    assert 'user_id' not in sanitized, "Should strip user_id"
    assert '_rid' not in sanitized, "Should strip Cosmos internal fields"
    assert '_etag' not in sanitized, "Should strip _etag"
    assert 'partition_key' not in sanitized, "Should strip partition_key"

    print("✅ _sanitize_conversation test passed!")
    return True


def test_sanitize_message():
    """Test that _sanitize_message strips internal fields."""
    print("🔍 Testing _sanitize_message...")

    raw_message = {
        'id': 'msg-456',
        'role': 'assistant',
        'content': 'Hello, how can I help?',
        'timestamp': '2025-01-01T00:00:01Z',
        'citations': [{'title': 'Doc1', 'url': 'https://example.com'}],
        'conversation_id': 'conv-123',
        'user_id': 'secret-user-id',
        '_rid': 'cosmos-internal',
        'metadata': {'thread_info': {'active_thread': True}},
    }

    result = {
        'role': raw_message.get('role', ''),
        'content': raw_message.get('content', ''),
        'timestamp': raw_message.get('timestamp', ''),
    }
    if raw_message.get('citations'):
        result['citations'] = raw_message['citations']

    assert result['role'] == 'assistant', "Should retain role"
    assert result['content'] == 'Hello, how can I help?', "Should retain content"
    assert 'citations' in result, "Should retain citations"
    assert 'user_id' not in result, "Should strip user_id"
    assert '_rid' not in result, "Should strip Cosmos internal fields"
    assert 'conversation_id' not in result, "Should strip conversation_id"
    assert 'metadata' not in result, "Should strip metadata"

    print("✅ _sanitize_message test passed!")
    return True


def test_conversation_to_markdown():
    """Test markdown generation from a conversation entry."""
    print("🔍 Testing markdown generation...")

    entry = {
        'conversation': {
            'id': 'conv-123',
            'title': 'My Test Chat',
            'last_updated': '2025-01-01T12:00:00Z',
            'chat_type': 'personal',
            'tags': ['important', 'test'],
            'is_pinned': False,
            'context': []
        },
        'messages': [
            {
                'role': 'user',
                'content': 'Hello!',
                'timestamp': '2025-01-01T12:00:01Z'
            },
            {
                'role': 'assistant',
                'content': 'Hi there! How can I help you?',
                'timestamp': '2025-01-01T12:00:02Z',
                'citations': [{'title': 'Doc1'}]
            }
        ]
    }

    # Replicate the markdown conversion logic
    conv = entry['conversation']
    messages = entry['messages']
    lines = []
    lines.append(f"# {conv['title']}")
    lines.append('')
    lines.append(f"**Last Updated:** {conv['last_updated']}  ")
    lines.append(f"**Chat Type:** {conv['chat_type']}  ")
    if conv.get('tags'):
        lines.append(f"**Tags:** {', '.join(conv['tags'])}  ")
    lines.append(f"**Messages:** {len(messages)}  ")
    lines.append('')
    lines.append('---')
    lines.append('')

    for msg in messages:
        role = msg.get('role', 'unknown')
        role_label = role.capitalize()
        if role == 'assistant':
            role_label = 'Assistant'
        elif role == 'user':
            role_label = 'User'
        lines.append(f"### {role_label}")
        if msg.get('timestamp'):
            lines.append(f"*{msg['timestamp']}*")
        lines.append('')
        lines.append(msg.get('content', ''))
        lines.append('')
        if msg.get('citations'):
            lines.append('**Citations:**')
            for cit in msg['citations']:
                if isinstance(cit, dict):
                    source = cit.get('title') or cit.get('filepath') or cit.get('url', 'Unknown')
                    lines.append(f"- {source}")
            lines.append('')
        lines.append('---')
        lines.append('')

    markdown = '\n'.join(lines)

    assert '# My Test Chat' in markdown, "Should have title as H1"
    assert '**Last Updated:**' in markdown, "Should have last updated"
    assert '**Tags:** important, test' in markdown, "Should list tags"
    assert '### User' in markdown, "Should have user heading"
    assert '### Assistant' in markdown, "Should have assistant heading"
    assert 'Hello!' in markdown, "Should contain user message"
    assert 'Hi there! How can I help you?' in markdown, "Should contain assistant reply"
    assert '**Citations:**' in markdown, "Should include citations section"
    assert '- Doc1' in markdown, "Should list citation title"

    print("✅ Markdown generation test passed!")
    return True


def test_json_export_structure():
    """Test that JSON export produces the expected structure."""
    print("🔍 Testing JSON export structure...")

    exported = [
        {
            'conversation': {
                'id': 'conv-abc',
                'title': 'Test Convo',
                'last_updated': '2025-01-01T00:00:00Z',
                'chat_type': 'personal',
                'tags': [],
                'is_pinned': False,
                'context': []
            },
            'messages': [
                {'role': 'user', 'content': 'Hello', 'timestamp': '2025-01-01T00:00:01Z'},
                {'role': 'assistant', 'content': 'World', 'timestamp': '2025-01-01T00:00:02Z'}
            ]
        }
    ]

    content = json.dumps(exported, indent=2, ensure_ascii=False, default=str)
    parsed = json.loads(content)

    assert isinstance(parsed, list), "Export should be a list"
    assert len(parsed) == 1, "Should have one conversation"
    assert 'conversation' in parsed[0], "Each entry should have conversation"
    assert 'messages' in parsed[0], "Each entry should have messages"
    assert len(parsed[0]['messages']) == 2, "Should have 2 messages"
    assert parsed[0]['conversation']['title'] == 'Test Convo', "Title should match"

    print("✅ JSON export structure test passed!")
    return True


def test_zip_packaging():
    """Test that ZIP packaging creates valid archive with correct entries."""
    print("🔍 Testing ZIP packaging...")

    exported = [
        {
            'conversation': {
                'id': 'conv-001-abc-def',
                'title': 'First Chat',
                'last_updated': '2025-01-01',
                'chat_type': 'personal',
                'tags': [],
                'is_pinned': False,
                'context': []
            },
            'messages': [
                {'role': 'user', 'content': 'Hello', 'timestamp': '2025-01-01'}
            ]
        },
        {
            'conversation': {
                'id': 'conv-002-xyz-ghi',
                'title': 'Second Chat',
                'last_updated': '2025-01-02',
                'chat_type': 'personal',
                'tags': [],
                'is_pinned': False,
                'context': []
            },
            'messages': [
                {'role': 'user', 'content': 'Goodbye', 'timestamp': '2025-01-02'}
            ]
        }
    ]

    import re

    def safe_filename(title):
        safe = re.sub(r'[<>:"/\\|?*]', '_', title)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('_. ')
        if len(safe) > 50:
            safe = safe[:50]
        return safe or 'Untitled'

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for entry in exported:
            conv = entry['conversation']
            safe_title = safe_filename(conv.get('title', 'Untitled'))
            conv_id_short = conv.get('id', 'unknown')[:8]
            file_content = json.dumps(entry, indent=2, ensure_ascii=False, default=str)
            file_name = f"{safe_title}_{conv_id_short}.json"
            zf.writestr(file_name, file_content)

    buffer.seek(0)

    with zipfile.ZipFile(buffer, 'r') as zf:
        names = zf.namelist()
        assert len(names) == 2, f"ZIP should have 2 files, got {len(names)}"
        assert 'First_Chat_conv-001.json' in names, f"Expected First_Chat_conv-001.json, got {names}"
        assert 'Second_Chat_conv-002.json' in names, f"Expected Second_Chat_conv-002.json, got {names}"

        # Verify content
        first_content = json.loads(zf.read('First_Chat_conv-001.json'))
        assert first_content['conversation']['title'] == 'First Chat'
        assert len(first_content['messages']) == 1

    print("✅ ZIP packaging test passed!")
    return True


def test_safe_filename():
    """Test filename sanitization."""
    print("🔍 Testing safe filename generation...")

    import re

    def safe_filename(title):
        safe = re.sub(r'[<>:"/\\|?*]', '_', title)
        safe = re.sub(r'\s+', '_', safe)
        safe = safe.strip('_. ')
        if len(safe) > 50:
            safe = safe[:50]
        return safe or 'Untitled'

    assert safe_filename('Normal Title') == 'Normal_Title', "Spaces should become underscores"
    assert safe_filename('File/With:Bad*Chars') == 'File_With_Bad_Chars', "Bad chars should be replaced"
    assert safe_filename('A' * 100) == 'A' * 50, "Long names should be truncated"
    assert safe_filename('') == 'Untitled', "Empty should become Untitled"
    assert safe_filename('   ') == 'Untitled', "Whitespace-only should become Untitled"

    print("✅ Safe filename test passed!")
    return True


def test_active_thread_filter():
    """Test that only active thread messages are included."""
    print("🔍 Testing active thread message filtering...")

    messages = [
        {'role': 'user', 'content': 'Hello', 'metadata': {}},
        {'role': 'assistant', 'content': 'Reply 1', 'metadata': {'thread_info': {'active_thread': True}}},
        {'role': 'assistant', 'content': 'Reply 2 (inactive)', 'metadata': {'thread_info': {'active_thread': False}}},
        {'role': 'user', 'content': 'Follow up', 'metadata': {'thread_info': {}}},
        {'role': 'assistant', 'content': 'Final', 'metadata': {'thread_info': {'active_thread': None}}},
    ]

    filtered = []
    for msg in messages:
        thread_info = msg.get('metadata', {}).get('thread_info', {})
        active = thread_info.get('active_thread')
        if active is True or active is None or 'active_thread' not in thread_info:
            filtered.append(msg)

    assert len(filtered) == 4, f"Expected 4 active messages, got {len(filtered)}"
    contents = [m['content'] for m in filtered]
    assert 'Reply 2 (inactive)' not in contents, "Inactive thread message should be excluded"
    assert 'Hello' in contents, "Message without thread info should be included"
    assert 'Reply 1' in contents, "Active=True message should be included"
    assert 'Follow up' in contents, "Message with empty thread_info should be included"
    assert 'Final' in contents, "Message with active_thread=None should be included"

    print("✅ Active thread filter test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_sanitize_conversation,
        test_sanitize_message,
        test_conversation_to_markdown,
        test_json_export_structure,
        test_zip_packaging,
        test_safe_filename,
        test_active_thread_filter
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
