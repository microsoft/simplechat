#!/usr/bin/env python3
# test_inline_image_gallery_visualization.py
"""
Functional test for inline image gallery visualization support.
Version: 0.241.066
Implemented in: 0.241.057

This test ensures assistant agent citations can expose inline image galleries,
workflow mirroring treats them as visualizations, and user-facing citation
labels stay readable for image results.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


from functions_message_artifacts import build_agent_citation_tool_label
import functions_workflow_runner


def read_text(relative_path):
    with open(os.path.join(REPO_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def test_image_gallery_citation_tool_labels_are_human_readable():
    gallery_label = build_agent_citation_tool_label(
        "ExternalMediaPlugin",
        "collect_images",
        {"title": "Incident Photos"},
        {
            "success": True,
            "render_type": "inline_image_gallery",
            "image_gallery": {
                "title": "Incident Photos",
                "items": [{"image_url": "https://example.com/one.png"}],
            },
        },
    )
    assert gallery_label == "Image gallery: Incident Photos"

    image_label = build_agent_citation_tool_label(
        "ExternalMediaPlugin",
        "fetch_image",
        {},
        {
            "success": True,
            "title": "Loading Dock Camera",
            "image_url": "https://example.com/camera.png",
            "mime": "image/png",
        },
    )
    assert image_label == "Image: Loading Dock Camera"


def test_workflow_runner_treats_image_results_as_visualizations():
    image_gallery_citation = {
        "function_result": {
            "success": True,
            "render_type": "inline_image_gallery",
            "image_gallery": {
                "title": "Incident Photos",
                "items": [{"image_url": "https://example.com/one.png"}],
            },
        }
    }
    assert functions_workflow_runner._is_visualization_citation(image_gallery_citation) is True

    direct_image_citation = {
        "function_result": {
            "success": True,
            "title": "Loading Dock Camera",
            "image_url": "https://example.com/camera.png",
            "mime": "image/png",
        }
    }
    assert functions_workflow_runner._is_visualization_citation(direct_image_citation) is True


def test_chat_renderer_wires_inline_image_galleries():
    messages_js = read_text("application/single_app/static/js/chat/chat-messages.js")
    images_js = read_text("application/single_app/static/js/chat/chat-inline-images.js")
    chats_css = read_text("application/single_app/static/css/chats.css")
    config_py = read_text("application/single_app/config.py")

    assert 'VERSION = "0.241.066"' in config_py
    assert "import { renderInlineImageGalleries } from './chat-inline-images.js';" in messages_js
    assert "await renderInlineImageGalleries(" in messages_js
    assert "const MAX_INLINE_IMAGE_ITEMS = 5;" in images_js
    assert "parseDocIdAndPage" in images_js
    assert '"Workspace images"' in images_js
    assert '"Linked images"' in images_js
    assert 'return "Workspace image";' in images_js
    assert 'class="inline-image-gallery-info-btn"' in images_js
    assert 'function showInlineImageDetailsModal(item)' in images_js
    assert ".inline-image-gallery-card" in chats_css
    assert ".inline-image-gallery-info-btn" in chats_css
    assert ".inline-image-modal-meta-row" in chats_css
    assert "max-height: 400px;" in chats_css
    assert "object-fit: contain;" in chats_css
    assert "hybridCitations || []" in messages_js
    assert "webCitations || []" in messages_js


def test_workflow_created_conversations_keep_summary_citations():
    workflow_runner_source = read_text("application/single_app/functions_workflow_runner.py")

    assert "mirrored_agent_citations = raw_agent_citations or list(source_assistant_doc.get('agent_citations') or [])" in workflow_runner_source
    assert "'hybrid_citations': list(source_assistant_doc.get('hybrid_citations') or [])," in workflow_runner_source
    assert "'web_search_citations': list(source_assistant_doc.get('web_search_citations') or [])," in workflow_runner_source
    assert "'agent_citations': mirrored_agent_citations," in workflow_runner_source
    assert "'hybrid_citations': hybrid_citations," in workflow_runner_source
    assert "'web_search_citations': web_search_citations," in workflow_runner_source
    assert "_mirror_assistant_message_to_personal_conversation(" in workflow_runner_source


if __name__ == "__main__":
    test_image_gallery_citation_tool_labels_are_human_readable()
    test_workflow_runner_treats_image_results_as_visualizations()
    test_chat_renderer_wires_inline_image_galleries()
    test_workflow_created_conversations_keep_summary_citations()
    print("Inline image gallery visualization checks passed.")