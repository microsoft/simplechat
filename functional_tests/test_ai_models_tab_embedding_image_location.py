# test_ai_models_tab_embedding_image_location.py
#!/usr/bin/env python3
"""
Functional test for AI Models tab placement of embeddings and image generation sections.
Version: 0.260.015
Implemented in: 0.236.014

This test ensures embeddings and image generation settings stay in the AI Models
group and are not nested inside the legacy model modal.
"""

import os
import re
from test_support.templates import compose_if_admin_settings


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return compose_if_admin_settings(file_path, file.read())


def _modal_span(content, modal_marker):
    """Return the (start, end) character span of a modal by balancing its divs."""
    start = content.index(modal_marker)
    # Back up to the opening tag of the element carrying the id.
    start = content.rindex("<div", 0, start)
    depth = 0
    for match in re.finditer(r"<div\b|</div>", content[start:]):
        depth += 1 if match.group(0) == "<div" else -1
        if depth == 0:
            return start, start + match.end()
    raise AssertionError(f"Unbalanced markup for {modal_marker}")


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

    # These cards now live in their own tab panes, so plain document order no
    # longer says anything useful. What matters is that neither card sits
    # *inside* the legacy modal, where it would only be reachable through it.
    modal_start, modal_end = _modal_span(content, legacy_modal_marker)
    for name, marker in (("Embeddings", embeddings_marker), ("Image generation", image_marker)):
        index = content.index(marker)
        assert not (modal_start < index < modal_end), (
            f"{name} section should be outside the legacy model modal."
        )

    print("Embeddings and image generation sections are outside the legacy model modal.")


if __name__ == "__main__":
    test_ai_models_tab_embedding_image_location()
