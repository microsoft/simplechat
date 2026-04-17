#!/usr/bin/env python3
# test_collaboration_image_reference.py
"""
Functional test for collaboration image reference handling.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures collaborative image messages stay lightweight in storage and
resolve rendered image bytes through a collaboration-specific image endpoint
instead of copying raw base64 payloads into the collaboration message store.
"""

import os


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_repo_file(*relative_parts):
    with open(os.path.join(REPO_ROOT, *relative_parts), 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_collaboration_generated_images_use_references_instead_of_raw_payloads():
    """Validate the collaboration image reference design remains in place."""
    collaboration_models_source = read_repo_file('application', 'single_app', 'collaboration_models.py')
    collaboration_functions_source = read_repo_file('application', 'single_app', 'functions_collaboration.py')
    collaboration_route_source = read_repo_file('application', 'single_app', 'route_backend_collaboration.py')

    assert "content = '[Generated image]'" in collaboration_models_source
    assert "not legacy_image_url.startswith('data:image/')" in collaboration_models_source
    assert 'def build_collaboration_image_url(conversation_id, message_id):' in collaboration_functions_source
    assert "/api/collaboration/conversations/<conversation_id>/images/<message_id>" in collaboration_route_source
    assert "serialized_assistant_message.get('content') if serialized_assistant_message.get('role') == 'image'" in collaboration_route_source
    assert "collaboration_message['content'] = str((source_message_doc or {}).get('content') or '')" not in collaboration_functions_source


if __name__ == '__main__':
    test_collaboration_generated_images_use_references_instead_of_raw_payloads()
    print('Collaboration image reference checks passed.')