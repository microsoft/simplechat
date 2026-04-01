#!/usr/bin/env python3
# test_per_message_export.py
"""
Functional tests for the per-message export feature and Word route regression fix.
Version: 0.239.128
Implemented in: 0.239.128

Covers:
 - Happy path: Word document built successfully from a valid message.
 - Markdown export logic: correct header, timestamp and content rendered.
 - Route regression: backend source defines POST /api/message/export-word.
 - Auth failure: unauthenticated caller receives 401.
 - Ownership failure: caller who does not own the conversation receives 403.
"""

import ast
import sys
import os
import io

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
)


# ---------------------------------------------------------------------------
# Helpers – replicate key logic from route_backend_conversation_export.py
# so the tests run without a live Flask + Cosmos DB environment.
# ---------------------------------------------------------------------------

def _normalize_content(content):
    """Replicate _normalize_content from route_backend_conversation_export."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get('type') == 'text':
                    parts.append(item.get('text', ''))
                elif item.get('type') == 'image_url':
                    parts.append('[Image]')
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return '\n'.join(parts)
    if isinstance(content, dict):
        if content.get('type') == 'text':
            return content.get('text', '')
        return str(content)
    return str(content) if content else ''


def _verify_ownership(conversation, requesting_user_id):
    """Return (ok, status_code, error_msg)."""
    if conversation is None:
        return False, 404, 'Conversation not found'
    if conversation.get('user_id') != requesting_user_id:
        return False, 403, 'Access denied'
    return True, 200, None


def _check_auth(user_id):
    """Simulate the authentication guard at the start of the endpoint."""
    if not user_id:
        return False, 401, 'User not authenticated'
    return True, 200, None


def _build_markdown_export(role, content, sender, timestamp):
    """Replicate the client-side Markdown export logic from chat-message-export.js."""
    lines = []
    lines.append(f"### {sender}")
    if timestamp:
        lines.append(f"*{timestamp}*")
    lines.append('')
    lines.append(content)
    lines.append('')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_word_export():
    """Happy path: Word document is built without error for a valid message."""
    print("🔍 Testing happy path – Word document generation...")

    try:
        from docx import Document as DocxDocument
        from docx.shared import Pt
    except ImportError as exc:
        print(f"  ⚠️  python-docx not installed, skipping Word generation check: {exc}")
        print("✅ test_happy_path_word_export skipped (dependency missing)")
        return True

    # Arrange
    requesting_user_id = 'user-alice'
    conversation = {'id': 'conv-001', 'user_id': 'user-alice'}
    message = {
        'id': 'msg-001',
        'role': 'assistant',
        'content': '**Hello**, world!\n\nThis is a test.',
        'timestamp': '2025-06-01T10:00:00Z',
        'citations': [
            {'title': 'Reference Doc', 'url': 'https://example.com/ref'}
        ]
    }

    # Auth check
    auth_ok, auth_status, auth_err = _check_auth(requesting_user_id)
    assert auth_ok, f"Auth should pass, got {auth_status}: {auth_err}"

    # Ownership check
    ok, status, err = _verify_ownership(conversation, requesting_user_id)
    assert ok, f"Ownership check should pass, got {status}: {err}"

    # Build Word document
    doc = DocxDocument()
    doc.add_heading('Message Export', level=1)

    role = message.get('role', 'unknown').capitalize()
    timestamp = message.get('timestamp', '')

    meta_para = doc.add_paragraph()
    meta_run = meta_para.add_run(f"Role: {role}")
    meta_run.bold = True
    if timestamp:
        meta_para.add_run(f"    {timestamp}")

    doc.add_paragraph('')

    content = _normalize_content(message.get('content', ''))

    # Add content as a paragraph (simplified – full logic tested in route unit)
    doc.add_paragraph(content)

    citations = message.get('citations', [])
    if citations:
        doc.add_heading('Citations', level=2)
        for cit in citations:
            source = cit.get('title') or cit.get('url', 'Unknown')
            doc.add_paragraph(source, style='List Bullet')

    # Serialise to buffer – if this raises, the test fails
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    docx_bytes = buffer.read()

    assert len(docx_bytes) > 0, "Generated docx should be non-empty"

    # Round-trip verify
    buffer.seek(0)
    loaded = DocxDocument(io.BytesIO(docx_bytes))
    headings = [p.text for p in loaded.paragraphs if p.style.name.startswith('Heading')]
    assert 'Message Export' in headings, "Document should have 'Message Export' heading"

    print("✅ test_happy_path_word_export passed!")
    return True


def test_happy_path_markdown_export():
    """Happy path: Markdown file content is correctly formatted."""
    print("🔍 Testing happy path – Markdown export...")

    role = 'assistant'
    content = 'Here is a **bold** answer.'
    sender = 'Assistant'
    timestamp = '2025-06-01T10:05:00Z'

    markdown = _build_markdown_export(role, content, sender, timestamp)

    assert '### Assistant' in markdown, "Should have role heading"
    assert f'*{timestamp}*' in markdown, "Should include timestamp"
    assert content in markdown, "Should include message content"
    # File should start with the heading line
    assert markdown.startswith('### Assistant'), "Heading should be first line"

    print("✅ test_happy_path_markdown_export passed!")
    return True


def test_export_word_route_definition_present():
    """Route regression: the backend must define POST /api/message/export-word."""
    print("🔍 Testing backend route definition for Word export...")

    route_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
        'route_backend_conversation_export.py'
    )

    with open(route_file, 'r', encoding='utf-8') as handle:
        source = handle.read()

    tree = ast.parse(source)
    register_func = next(
        (
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == 'register_route_backend_conversation_export'
        ),
        None
    )

    assert register_func is not None, 'register_route_backend_conversation_export should exist'

    export_route_found = False
    for node in register_func.body:
        if not isinstance(node, ast.FunctionDef):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue

            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr != 'route':
                continue

            if not decorator.args:
                continue

            route_arg = decorator.args[0]
            if not isinstance(route_arg, ast.Constant) or route_arg.value != '/api/message/export-word':
                continue

            methods_kw = next((keyword for keyword in decorator.keywords if keyword.arg == 'methods'), None)
            assert methods_kw is not None, 'Export Word route should declare allowed methods'
            assert isinstance(methods_kw.value, (ast.List, ast.Tuple)), 'Route methods should be a list or tuple'

            methods = [
                item.value for item in methods_kw.value.elts
                if isinstance(item, ast.Constant)
            ]
            assert 'POST' in methods, f'Expected POST method, found {methods}'
            assert node.name == 'api_export_message_word', f'Unexpected route handler name: {node.name}'
            export_route_found = True
            break

        if export_route_found:
            break

    assert export_route_found, 'Expected POST /api/message/export-word to be defined'

    print("✅ test_export_word_route_definition_present passed!")
    return True


def test_auth_failure_unauthenticated():
    """Auth failure: an unauthenticated caller (no user_id) should get 401."""
    print("🔍 Testing auth failure – unauthenticated request...")

    for bad_user_id in (None, '', False):
        ok, status, err = _check_auth(bad_user_id)
        assert not ok, f"Auth should fail for user_id={bad_user_id!r}"
        assert status == 401, f"Expected 401, got {status}"
        assert err == 'User not authenticated', f"Unexpected error message: {err}"

    print("✅ test_auth_failure_unauthenticated passed!")
    return True


def test_ownership_failure_wrong_user():
    """Ownership failure: user requesting another user's conversation gets 403."""
    print("🔍 Testing ownership failure – wrong user...")

    conversation = {'id': 'conv-bob', 'user_id': 'user-bob'}
    requesting_user = 'user-alice'

    ok, status, err = _verify_ownership(conversation, requesting_user)

    assert not ok, "Ownership check should fail"
    assert status == 403, f"Expected 403, got {status}"
    assert err == 'Access denied', f"Unexpected error message: {err}"

    print("✅ test_ownership_failure_wrong_user passed!")
    return True


def test_ownership_failure_missing_conversation():
    """Ownership failure: conversation not found should return 404."""
    print("🔍 Testing ownership failure – conversation not found...")

    ok, status, err = _verify_ownership(None, 'user-alice')

    assert not ok, "Ownership check should fail for missing conversation"
    assert status == 404, f"Expected 404, got {status}"
    assert err == 'Conversation not found', f"Unexpected error message: {err}"

    print("✅ test_ownership_failure_missing_conversation passed!")
    return True


def test_normalize_content_variants():
    """Content normalisation handles strings, lists, and dicts correctly."""
    print("🔍 Testing content normalisation...")

    # Plain string – unchanged
    assert _normalize_content('hello') == 'hello'

    # List of text parts
    result = _normalize_content([
        {'type': 'text', 'text': 'Part 1'},
        {'type': 'text', 'text': 'Part 2'},
    ])
    assert result == 'Part 1\nPart 2', f"Unexpected: {result!r}"

    # Image entry in list
    result = _normalize_content([
        {'type': 'text', 'text': 'Before image'},
        {'type': 'image_url', 'image_url': {'url': 'https://example.com/img.png'}},
    ])
    assert '[Image]' in result, "Image entries should render as [Image]"

    # Dict with type=text
    assert _normalize_content({'type': 'text', 'text': 'Hi'}) == 'Hi'

    # None / empty
    assert _normalize_content(None) == ''
    assert _normalize_content('') == ''

    print("✅ test_normalize_content_variants passed!")
    return True


def test_markdown_export_no_timestamp():
    """Markdown export omits the timestamp line when timestamp is empty."""
    print("🔍 Testing Markdown export without timestamp...")

    markdown = _build_markdown_export('user', 'Hello!', 'User', '')

    assert '### User' in markdown
    assert 'Hello!' in markdown
    # No italicised timestamp line should be present
    lines = markdown.splitlines()
    italic_lines = [line for line in lines if line.startswith('*') and line.endswith('*')]
    assert not italic_lines, f"Should be no timestamp lines, found: {italic_lines}"

    print("✅ test_markdown_export_no_timestamp passed!")
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_happy_path_word_export,
        test_happy_path_markdown_export,
        test_export_word_route_definition_present,
        test_auth_failure_unauthenticated,
        test_ownership_failure_wrong_user,
        test_ownership_failure_missing_conversation,
        test_normalize_content_variants,
        test_markdown_export_no_timestamp,
    ]
    results = []

    for test_fn in tests:
        print(f"\n🧪 Running {test_fn.__name__}...")
        try:
            results.append(test_fn())
        except Exception as exc:
            print(f"❌ {test_fn.__name__} failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    passed = sum(1 for r in results if r)
    print(f"\n📊 Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
