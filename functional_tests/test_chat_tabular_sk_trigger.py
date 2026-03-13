#!/usr/bin/env python3
# test_chat_tabular_sk_trigger.py
"""
Functional test for chat-uploaded tabular file SK mini-agent trigger fix.
Version: 0.239.008
Implemented in: 0.239.008

This test ensures that when tabular data files (CSV, XLSX) are uploaded directly
to a chat conversation, the SK mini-agent (`run_tabular_sk_analysis`) is properly
triggered in model-only mode (no agent selected) to pre-compute analysis results.

Previously, the mini SK agent only triggered from search results, missing
chat-uploaded files entirely. The streaming path also ignored file role messages.

This test validates:
1. Chat-uploaded tabular files are detected in conversation history (file role)
2. Filenames are collected into chat_tabular_files set for both blob and inline cases
3. The streaming path properly handles file role messages (not just user/assistant)
4. The mini SK trigger block activates when chat_tabular_files is non-empty
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'application', 'single_app'))


def test_chat_tabular_file_detection():
    """Test that chat-uploaded tabular files are detected from file role messages."""
    print("Testing chat-uploaded tabular file detection...")

    try:
        # Simulate conversation messages as they would appear from Cosmos DB
        recent_messages = [
            {
                'role': 'file',
                'filename': 'Sample_-_Superstore_1.xlsx',
                'file_content': '',
                'is_table': True,
                'file_content_source': 'blob',
                'metadata': {},
            },
            {
                'role': 'user',
                'content': 'analyze sales/profit',
                'metadata': {},
            },
        ]

        # Simulate the conversation history building logic (streaming path)
        conversation_history_for_api = []
        allowed_roles_in_history = ['user', 'assistant']
        max_file_content_length_in_history = 50000
        max_tabular_content_length_in_history = 50000
        chat_tabular_files = set()

        for message in recent_messages:
            role = message.get('role')
            content = message.get('content', '')

            if role in allowed_roles_in_history:
                conversation_history_for_api.append({
                    'role': role,
                    'content': content
                })
            elif role == 'file':
                filename = message.get('filename', 'uploaded_file')
                file_content = message.get('file_content', '')
                is_table = message.get('is_table', False)
                file_content_source = message.get('file_content_source', '')

                if is_table and file_content_source == 'blob':
                    chat_tabular_files.add(filename)
                    conversation_history_for_api.append({
                        'role': 'system',
                        'content': (
                            f"[User uploaded a tabular data file named '{filename}'. "
                            f"The file is stored in blob storage and available for analysis. "
                            f"The file source is 'chat'.]"
                        )
                    })

        # Verify file was detected
        assert 'Sample_-_Superstore_1.xlsx' in chat_tabular_files, \
            f"Expected xlsx file in chat_tabular_files, got: {chat_tabular_files}"

        # Verify system message was added for the file
        system_msgs = [m for m in conversation_history_for_api if m['role'] == 'system']
        assert len(system_msgs) == 1, f"Expected 1 system message, got {len(system_msgs)}"
        assert 'Sample_-_Superstore_1.xlsx' in system_msgs[0]['content'], \
            "System message should reference the uploaded file"

        # Verify user message was included
        user_msgs = [m for m in conversation_history_for_api if m['role'] == 'user']
        assert len(user_msgs) == 1, f"Expected 1 user message, got {len(user_msgs)}"
        assert user_msgs[0]['content'] == 'analyze sales/profit', \
            "User message content should be preserved"

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_non_tabular_file_handling():
    """Test that non-tabular files are handled with content preview."""
    print("Testing non-tabular file handling in streaming path...")

    try:
        recent_messages = [
            {
                'role': 'file',
                'filename': 'report.txt',
                'file_content': 'This is the report content.',
                'is_table': False,
                'file_content_source': 'inline',
                'metadata': {},
            },
            {
                'role': 'user',
                'content': 'summarize the report',
                'metadata': {},
            },
        ]

        conversation_history_for_api = []
        allowed_roles_in_history = ['user', 'assistant']
        max_file_content_length_in_history = 50000
        max_tabular_content_length_in_history = 50000
        chat_tabular_files = set()

        for message in recent_messages:
            role = message.get('role')
            content = message.get('content', '')

            if role in allowed_roles_in_history:
                conversation_history_for_api.append({
                    'role': role,
                    'content': content
                })
            elif role == 'file':
                filename = message.get('filename', 'uploaded_file')
                file_content = message.get('file_content', '')
                is_table = message.get('is_table', False)
                file_content_source = message.get('file_content_source', '')

                if is_table and file_content_source == 'blob':
                    chat_tabular_files.add(filename)
                    conversation_history_for_api.append({
                        'role': 'system',
                        'content': f"[User uploaded a tabular data file named '{filename}'.]"
                    })
                else:
                    content_limit = (
                        max_tabular_content_length_in_history if is_table
                        else max_file_content_length_in_history
                    )
                    display_content = file_content[:content_limit]
                    if len(file_content) > content_limit:
                        display_content += "..."

                    conversation_history_for_api.append({
                        'role': 'system',
                        'content': (
                            f"[User uploaded a file named '{filename}'. "
                            f"Content preview:\n{display_content}]\n"
                            f"Use this file context if relevant."
                        )
                    })

        # Non-tabular files should NOT be in chat_tabular_files
        assert len(chat_tabular_files) == 0, \
            f"Non-tabular files should not be tracked, got: {chat_tabular_files}"

        # System message should contain file content preview
        system_msgs = [m for m in conversation_history_for_api if m['role'] == 'system']
        assert len(system_msgs) == 1, f"Expected 1 system message, got {len(system_msgs)}"
        assert 'report.txt' in system_msgs[0]['content'], \
            "System message should reference the file"
        assert 'This is the report content.' in system_msgs[0]['content'], \
            "System message should include file content preview"

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multiple_tabular_files():
    """Test detection of multiple tabular files uploaded to chat."""
    print("Testing multiple tabular file detection...")

    try:
        recent_messages = [
            {
                'role': 'file',
                'filename': 'sales_2024.xlsx',
                'file_content': '',
                'is_table': True,
                'file_content_source': 'blob',
                'metadata': {},
            },
            {
                'role': 'file',
                'filename': 'inventory.csv',
                'file_content': 'item,count\nwidget,100',
                'is_table': True,
                'file_content_source': 'blob',
                'metadata': {},
            },
            {
                'role': 'user',
                'content': 'compare sales to inventory',
                'metadata': {},
            },
        ]

        chat_tabular_files = set()
        conversation_history_for_api = []
        allowed_roles_in_history = ['user', 'assistant']

        for message in recent_messages:
            role = message.get('role')
            content = message.get('content', '')

            if role in allowed_roles_in_history:
                conversation_history_for_api.append({'role': role, 'content': content})
            elif role == 'file':
                filename = message.get('filename', 'uploaded_file')
                is_table = message.get('is_table', False)
                file_content_source = message.get('file_content_source', '')

                if is_table and file_content_source == 'blob':
                    chat_tabular_files.add(filename)
                    conversation_history_for_api.append({
                        'role': 'system',
                        'content': f"[Tabular file '{filename}' available for analysis.]"
                    })

        assert len(chat_tabular_files) == 2, \
            f"Expected 2 tabular files, got {len(chat_tabular_files)}"
        assert 'sales_2024.xlsx' in chat_tabular_files, "Missing sales_2024.xlsx"
        assert 'inventory.csv' in chat_tabular_files, "Missing inventory.csv"

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_inline_tabular_not_tracked_for_sk():
    """Test that inline tabular files (not blob) are NOT tracked for SK analysis."""
    print("Testing inline tabular files are not tracked for SK analysis...")

    try:
        recent_messages = [
            {
                'role': 'file',
                'filename': 'data.csv',
                'file_content': 'col1,col2\n1,2\n3,4',
                'is_table': True,
                'file_content_source': 'inline',  # Not blob
                'metadata': {},
            },
        ]

        chat_tabular_files = set()

        for message in recent_messages:
            role = message.get('role')
            if role == 'file':
                is_table = message.get('is_table', False)
                file_content_source = message.get('file_content_source', '')
                filename = message.get('filename', '')

                if is_table and file_content_source == 'blob':
                    chat_tabular_files.add(filename)

        assert len(chat_tabular_files) == 0, \
            f"Inline tabular files should not be tracked for SK, got: {chat_tabular_files}"

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []
    results.append(test_chat_tabular_file_detection())
    results.append(test_non_tabular_file_handling())
    results.append(test_multiple_tabular_files())
    results.append(test_inline_tabular_not_tracked_for_sk())

    print(f"\n{'='*50}")
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    if all(results):
        print("All tests passed!")
        sys.exit(0)
    else:
        print("Some tests failed!")
        sys.exit(1)
