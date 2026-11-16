#!/usr/bin/env python3
# test_chat_default_system_prompt_chat_uploads_fix.py
"""
Functional test for preserving default_system_prompt when chat uploads are present.
Version: 0.261.054
Implemented in: 0.261.054

This test ensures that chat-uploaded image/file system messages and other augmentation
system messages in conversation_history_for_api do not suppress insertion of the
configured default_system_prompt in either standard or streaming chat routes (Refs #1855).
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'DEFAULT_SYSTEM_PROMPT_CHAT_UPLOADS_FIX.md',
)
IMPLEMENTED_IN = '0.261.054'


def _read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def _simulate_default_system_prompt_insertion(conversation_history_for_api, default_system_prompt):
    """Mirror the default_system_prompt insertion contract in route_backend_chats.py."""
    history = [dict(item) for item in conversation_history_for_api]
    refs = [f"existing:{idx}" for idx in range(len(history))]
    default_system_prompt = (default_system_prompt or '').strip()
    default_system_prompt_inserted = False

    if default_system_prompt:
        has_general_system_prompt = any(
            msg.get('role') == 'system'
            and str(msg.get('content') or '').strip() == default_system_prompt
            for msg in history
        )
        if not has_general_system_prompt:
            insert_idx = 0
            if (
                history
                and history[0].get('role') == 'system'
                and history[0].get('content', '').startswith('<Summary of previous conversation context>')
            ):
                insert_idx = 1
            history.insert(insert_idx, {
                'role': 'system',
                'content': default_system_prompt,
            })
            refs.insert(insert_idx, 'system:default_prompt')
            default_system_prompt_inserted = True

    return history, refs, default_system_prompt_inserted


def test_route_uses_exact_default_system_prompt_check_in_both_chat_paths():
    """Verify both standard and streaming chat paths check for default_system_prompt explicitly."""
    print('Testing route_backend_chats.py has_general_system_prompt contract...')
    assert_app_version_at_least(IMPLEMENTED_IN)

    route_source = _read_text(ROUTE_FILE)
    expected_snippet = (
        "has_general_system_prompt = any(\n"
        "                    msg.get('role') == 'system'\n"
        "                    and str(msg.get('content') or '').strip() == default_system_prompt\n"
        "                    for msg in conversation_history_for_api\n"
        "                )"
    )
    expected_streaming_snippet = (
        "has_general_system_prompt = any(\n"
        "                        msg.get('role') == 'system'\n"
        "                        and str(msg.get('content') or '').strip() == default_system_prompt\n"
        "                        for msg in conversation_history_for_api\n"
        "                    )"
    )
    legacy_snippet = '"retrieved document excerpts" in msg.get(\'content\', \'\')'

    assert expected_snippet in route_source, (
        'Standard chat path did not use exact default_system_prompt matching for has_general_system_prompt'
    )
    assert expected_streaming_snippet in route_source, (
        'Streaming chat path did not use exact default_system_prompt matching for has_general_system_prompt'
    )
    assert legacy_snippet not in route_source, (
        'Legacy exclusion-based has_general_system_prompt check should be removed from route_backend_chats.py'
    )
    assert os.path.exists(FIX_DOC), f'Expected fix documentation at {FIX_DOC}'
    print('route_backend_chats.py contract check passed!')
    return True


def test_default_system_prompt_inserted_when_chat_uploads_present():
    """Verify chat-uploaded image and file system messages do not suppress default_system_prompt."""
    print('Testing default_system_prompt insertion with chat-uploaded image/file messages...')
    default_prompt = 'You are an expert assistant. Always cite sources using [source_id].'

    # Case 1: Chat-uploaded image converted to role=='system'
    history_with_image = [
        {
            'role': 'system',
            'content': 'User uploaded an image with the following description:\n<image_description> sample.xml </image_description>',
        },
        {
            'role': 'user',
            'content': 'What is in this image and our workspace?',
        },
    ]
    updated_history, updated_refs, inserted = _simulate_default_system_prompt_insertion(
        history_with_image,
        default_prompt,
    )
    assert inserted is True
    assert updated_history[0] == {'role': 'system', 'content': default_prompt}
    assert updated_refs[0] == 'system:default_prompt'

    # Case 2: Summary at index 0 + chat-uploaded XML/file converted to role=='system'
    history_with_summary_and_file = [
        {
            'role': 'system',
            'content': '<Summary of previous conversation context>\nPrior context summary.',
        },
        {
            'role': 'system',
            'content': 'User uploaded a file named config.xml with the following content:\n<root></root>',
        },
        {
            'role': 'user',
            'content': 'Compare this XML file with the policy document.',
        },
    ]
    updated_history, updated_refs, inserted = _simulate_default_system_prompt_insertion(
        history_with_summary_and_file,
        default_prompt,
    )
    assert inserted is True
    assert updated_history[0]['content'].startswith('<Summary of previous conversation context>')
    assert updated_history[1] == {'role': 'system', 'content': default_prompt}
    assert updated_refs[1] == 'system:default_prompt'

    # Case 3: Already contains default_system_prompt (with surrounding whitespace) -> not duplicated
    history_already_has_default = [
        {
            'role': 'system',
            'content': f'  {default_prompt}\n',
        },
        {
            'role': 'system',
            'content': 'User uploaded an image with the following description: diagram',
        },
        {
            'role': 'user',
            'content': 'Explain the diagram.',
        },
    ]
    updated_history, _, inserted = _simulate_default_system_prompt_insertion(
        history_already_has_default,
        default_prompt,
    )
    assert inserted is False
    assert len(updated_history) == 3
    print('default_system_prompt insertion behavior checks passed!')
    return True


if __name__ == '__main__':
    tests = [
        test_route_uses_exact_default_system_prompt_check_in_both_chat_paths,
        test_default_system_prompt_inserted_when_chat_uploads_present,
    ]
    results = [test() for test in tests]
    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
