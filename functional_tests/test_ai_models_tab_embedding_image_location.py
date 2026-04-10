# test_ai_models_tab_embedding_image_location.py
#!/usr/bin/env python3
"""
Functional test for AI Models tab placement of embeddings and image generation sections.
Version: 0.236.014
Implemented in: 0.236.014

This test ensures embeddings and image generation settings remain on the AI Models tab
and are not nested inside the legacy model modal.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_ai_models_tab_embedding_image_location():
    """Verify embeddings and image generation sections are outside legacy modal markup."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    template_path = os.path.join(repo_root, 'application', 'single_app', 'templates', 'admin_settings.html')

    content = read_file_text(template_path)

    embeddings_marker = 'id="embeddings-configuration"'
    image_marker = 'id="image-generation-configuration"'
    legacy_modal_marker = 'id="legacyModelSettingsModal"'

    assert embeddings_marker in content, "Embeddings configuration section is missing."
    assert image_marker in content, "Image generation configuration section is missing."
    assert legacy_modal_marker in content, "Legacy model modal is missing."

    embeddings_index = content.index(embeddings_marker)
    image_index = content.index(image_marker)
    legacy_modal_index = content.index(legacy_modal_marker)

    assert embeddings_index < legacy_modal_index, "Embeddings section should be outside legacy modal."
    assert image_index < legacy_modal_index, "Image generation section should be outside legacy modal."

    print("✅ Embeddings and image generation sections are on the AI Models tab.")


if __name__ == "__main__":
    test_ai_models_tab_embedding_image_location()
