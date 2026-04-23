#!/usr/bin/env python3
# test_inline_video_gallery_visualization.py
"""
Functional test for inline video gallery visualization support.
Version: 0.241.066
Implemented in: 0.241.066

This test ensures assistant agent citations can expose inline video galleries,
workflow mirroring treats direct video results as visualizations, and user-facing
citation labels stay readable for video results.
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


def test_video_gallery_citation_tool_labels_are_human_readable():
    gallery_label = build_agent_citation_tool_label(
        "ExternalMediaPlugin",
        "collect_videos",
        {"title": "Incident Clips"},
        {
            "success": True,
            "render_type": "inline_video_gallery",
            "video_gallery": {
                "title": "Incident Clips",
                "items": [{"video_url": "https://example.com/one.mp4"}],
            },
        },
    )
    assert gallery_label == "Video gallery: Incident Clips"

    video_label = build_agent_citation_tool_label(
        "ExternalMediaPlugin",
        "fetch_video",
        {},
        {
            "success": True,
            "title": "Loading Dock Camera",
            "video_url": "https://example.com/camera.mp4",
            "mime": "video/mp4",
        },
    )
    assert video_label == "Video: Loading Dock Camera"


def test_workflow_runner_treats_video_results_as_visualizations():
    video_gallery_citation = {
        "function_result": {
            "success": True,
            "render_type": "inline_video_gallery",
            "video_gallery": {
                "title": "Incident Clips",
                "items": [{"video_url": "https://example.com/one.mp4"}],
            },
        }
    }
    assert functions_workflow_runner._is_visualization_citation(video_gallery_citation) is True

    direct_video_citation = {
        "function_result": {
            "success": True,
            "title": "Loading Dock Camera",
            "video_url": "https://example.com/camera.mp4",
            "mime": "video/mp4",
        }
    }
    assert functions_workflow_runner._is_visualization_citation(direct_video_citation) is True


def test_chat_renderer_wires_inline_video_galleries():
    messages_js = read_text("application/single_app/static/js/chat/chat-messages.js")
    videos_js = read_text("application/single_app/static/js/chat/chat-inline-videos.js")
    chats_css = read_text("application/single_app/static/css/chats.css")
    workflow_runner_source = read_text("application/single_app/functions_workflow_runner.py")
    config_py = read_text("application/single_app/config.py")

    assert 'VERSION = "0.241.066"' in config_py
    assert "import { renderInlineVideoGalleries } from './chat-inline-videos.js';" in messages_js
    assert "await renderInlineVideoGalleries(" in messages_js
    assert 'const INLINE_VIDEO_GALLERY_RENDER_TYPE = "inline_video_gallery";' in videos_js
    assert "const MAX_INLINE_VIDEO_ITEMS = 5;" in videos_js
    assert '"Workspace videos"' in videos_js
    assert '"Linked videos"' in videos_js
    assert 'return "Workspace video";' in videos_js
    assert 'class="inline-video-gallery-info-btn"' in videos_js
    assert "function showInlineVideoDetailsModal(item)" in videos_js
    assert ".inline-video-gallery-card" in chats_css
    assert ".inline-video-gallery-item-video" in chats_css
    assert ".inline-video-modal-meta-row" in chats_css
    assert "max-height: 400px;" in chats_css
    assert "_contains_inline_video_result(function_result)" in workflow_runner_source
    assert "mime_type.startswith('video/')" in workflow_runner_source


if __name__ == "__main__":
    test_video_gallery_citation_tool_labels_are_human_readable()
    test_workflow_runner_treats_video_results_as_visualizations()
    test_chat_renderer_wires_inline_video_galleries()
    print("Inline video gallery visualization checks passed.")