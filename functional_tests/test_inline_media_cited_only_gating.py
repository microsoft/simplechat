#!/usr/bin/env python3
# test_inline_media_cited_only_gating.py
"""
Functional test for inline image and video galleries showing cited media only.
Version: 0.260.024
Implemented in: 0.260.024

Inline galleries used to render every workspace and web media result returned by
retrieval, so a search that surfaced five images produced five inline tiles even
when the response referenced none of them. The renderers now consume the cited
citation subsets that issue #1249 already persists on each assistant message,
while the Sources disclosure keeps the complete retrieved set.

This test ensures the browser helper resolves cited subsets with the same rules
as functions_citation_tracking.py, that chat-messages.js feeds those subsets to
both gallery renderers, and that the Sources panel still receives every
retrieved citation.

Refs microsoft/simplechat#1329
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_JS_DIR = os.path.join(
    REPO_ROOT, "application", "single_app", "static", "js", "chat"
)
CITATION_TRACKING_JS = os.path.join(CHAT_JS_DIR, "chat-citation-tracking.js")
CHAT_MESSAGES_JS = os.path.join(CHAT_JS_DIR, "chat-messages.js")
INLINE_IMAGES_JS = os.path.join(CHAT_JS_DIR, "chat-inline-images.js")
INLINE_VIDEOS_JS = os.path.join(CHAT_JS_DIR, "chat-inline-videos.js")

HYBRID_SOURCES = [
    {"citation_id": "doc-a_1", "file_name": "cited-photo.png"},
    {"citation_id": "doc-b_1", "file_name": "unreferenced-photo.png"},
]
WEB_SOURCES = [
    {"url": "https://example.com/cited.png", "title": "Cited"},
    {"url": "https://example.com/unreferenced.png", "title": "Unreferenced"},
]
CITED_HYBRID = [HYBRID_SOURCES[0]]
CITED_WEB = [WEB_SOURCES[0]]

NODE_DRIVER_SOURCE = """
import {
    messageHasCitationTracking,
    getCitedHybridCitations,
    getCitedWebCitations,
} from "./chat-citation-tracking.mjs";

const scenarios = JSON.parse(process.argv[2]);
const results = scenarios.map((scenario) => ({
    name: scenario.name,
    tracked: messageHasCitationTracking(scenario.message),
    hybrid: getCitedHybridCitations(scenario.message, scenario.hybridSources),
    web: getCitedWebCitations(scenario.message, scenario.webSources),
}));

process.stdout.write(JSON.stringify(results));
"""


def read_text(absolute_path):
    with open(absolute_path, "r", encoding="utf-8") as handle:
        return handle.read()


def run_citation_tracking_helper(scenarios):
    """Execute the real browser helper under Node and return its results."""
    node_executable = shutil.which("node")
    if not node_executable:
        return None

    with tempfile.TemporaryDirectory() as work_dir:
        # The helper is an ES module in a directory without a package.json, so
        # Node needs the .mjs extension to load the source unmodified.
        module_copy = os.path.join(work_dir, "chat-citation-tracking.mjs")
        with open(module_copy, "w", encoding="utf-8") as handle:
            handle.write(read_text(CITATION_TRACKING_JS))

        driver_path = os.path.join(work_dir, "driver.mjs")
        with open(driver_path, "w", encoding="utf-8") as handle:
            handle.write(NODE_DRIVER_SOURCE)

        completed = subprocess.run(
            [node_executable, driver_path, json.dumps(scenarios)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    if completed.returncode != 0:
        raise AssertionError(
            f"Node helper execution failed ({completed.returncode}): {completed.stderr.strip()}"
        )

    return {result["name"]: result for result in json.loads(completed.stdout)}


def test_citation_tracking_helper_resolves_cited_subsets():
    """Verify the browser helper matches the server tracking-detection rules."""
    print("Testing chat-citation-tracking.js resolution rules...")

    scenarios = [
        {
            "name": "legacy_untracked",
            "message": {"id": "m1", "role": "assistant"},
            "hybridSources": HYBRID_SOURCES,
            "webSources": WEB_SOURCES,
        },
        {
            "name": "tracked_with_citations",
            "message": {
                "id": "m2",
                "citation_tracking_version": 1,
                "cited_hybrid_citations": CITED_HYBRID,
                "cited_web_search_citations": CITED_WEB,
            },
            "hybridSources": HYBRID_SOURCES,
            "webSources": WEB_SOURCES,
        },
        {
            "name": "tracked_without_citations",
            "message": {
                "id": "m3",
                "citation_tracking_version": 1,
                "cited_hybrid_citations": [],
                "cited_web_search_citations": [],
            },
            "hybridSources": HYBRID_SOURCES,
            "webSources": WEB_SOURCES,
        },
        {
            "name": "tracked_by_key_presence_only",
            "message": {"id": "m4", "cited_hybrid_citations": CITED_HYBRID},
            "hybridSources": HYBRID_SOURCES,
            "webSources": WEB_SOURCES,
        },
        {
            "name": "missing_message",
            "message": None,
            "hybridSources": HYBRID_SOURCES,
            "webSources": WEB_SOURCES,
        },
        {
            "name": "malformed_values",
            "message": {
                "id": "m6",
                "citation_tracking_version": "not-a-version",
                "cited_hybrid_citations": "not-an-array",
            },
            "hybridSources": "not-an-array",
            "webSources": None,
        },
    ]

    results = run_citation_tracking_helper(scenarios)
    if results is None:
        print("Node is unavailable; skipping helper execution checks.")
        return True

    legacy = results["legacy_untracked"]
    assert legacy["tracked"] is False
    assert legacy["hybrid"] == HYBRID_SOURCES, "Legacy messages keep the full source set."
    assert legacy["web"] == WEB_SOURCES, "Legacy messages keep the full web source set."

    tracked = results["tracked_with_citations"]
    assert tracked["tracked"] is True
    assert tracked["hybrid"] == CITED_HYBRID, "Tracked messages expose only cited documents."
    assert tracked["web"] == CITED_WEB, "Tracked messages expose only cited web results."

    empty = results["tracked_without_citations"]
    assert empty["tracked"] is True
    assert empty["hybrid"] == [], "A tracked message that cited nothing renders nothing."
    assert empty["web"] == [], "A tracked message that cited nothing renders nothing."

    key_only = results["tracked_by_key_presence_only"]
    assert key_only["tracked"] is True, "A cited_* key alone marks the message as tracked."
    assert key_only["hybrid"] == CITED_HYBRID
    assert key_only["web"] == [], "A tracked message without cited web results yields none."

    missing = results["missing_message"]
    assert missing["tracked"] is False
    assert missing["hybrid"] == HYBRID_SOURCES
    assert missing["web"] == WEB_SOURCES

    malformed = results["malformed_values"]
    assert malformed["tracked"] is True, "A cited_* key marks tracking even with a bad version."
    assert malformed["hybrid"] == [], "Non-array cited values normalize to an empty list."
    assert malformed["web"] == []

    print("Citation tracking helper resolution rules passed.")
    return True


def test_inline_galleries_consume_cited_subsets():
    """Verify chat-messages.js feeds cited subsets to both gallery renderers."""
    print("Testing inline gallery wiring in chat-messages.js...")

    messages_source = read_text(CHAT_MESSAGES_JS)

    assert (
        "import { getCitedHybridCitations, getCitedWebCitations } from './chat-citation-tracking.js';"
        in messages_source
    )
    assert (
        "const citedHybridCitations = getCitedHybridCitations(fullMessageObject, hybridCitations);"
        in messages_source
    )
    assert (
        "const citedWebCitations = getCitedWebCitations(fullMessageObject, webCitations);"
        in messages_source
    )

    video_call = messages_source.split("await renderInlineVideoGalleries(")[1].split(");")[0]
    image_call = messages_source.split("await renderInlineImageGalleries(")[1].split(");")[0]
    for renderer_name, call_arguments in (
        ("renderInlineVideoGalleries", video_call),
        ("renderInlineImageGalleries", image_call),
    ):
        assert "citedHybridCitations" in call_arguments, (
            f"{renderer_name} must receive the cited document subset."
        )
        assert "citedWebCitations" in call_arguments, (
            f"{renderer_name} must receive the cited web subset."
        )
        assert "hybridCitations || []" not in call_arguments, (
            f"{renderer_name} must not receive the full retrieved document set."
        )
        assert "webCitations || []" not in call_arguments, (
            f"{renderer_name} must not receive the full retrieved web set."
        )
        assert "agentCitations || []" in call_arguments, (
            f"{renderer_name} must still receive executed agent citations."
        )

    print("Inline gallery wiring passed.")
    return True


def test_sources_disclosure_keeps_full_retrieved_sets():
    """Verify the Sources panel still lists every retrieved citation."""
    print("Testing Sources disclosure retains retrieved citations...")

    messages_source = read_text(CHAT_MESSAGES_JS)

    citations_call = messages_source.split("const citationsButtonsHtml = createCitationsHtml(")[1]
    citations_call = citations_call.split(");")[0]
    assert "hybridCitations," in citations_call, "Sources keeps the full document set."
    assert "webCitations," in citations_call, "Sources keeps the full web set."
    assert "citedHybridCitations" not in citations_call
    assert "citedWebCitations" not in citations_call

    print("Sources disclosure checks passed.")
    return True


def test_gallery_renderers_declare_cited_inputs():
    """Verify both renderers name their inputs as cited subsets."""
    print("Testing gallery renderer signatures...")

    images_source = read_text(INLINE_IMAGES_JS)
    videos_source = read_text(INLINE_VIDEOS_JS)

    assert "export async function renderInlineImageGalleries(\n    messageElement,\n    citedHybridCitations = [],\n    citedWebCitations = [],\n    agentCitations = [],\n" in images_source
    assert "export async function renderInlineVideoGalleries(\n    messageElement,\n    citedHybridCitations = [],\n    citedWebCitations = [],\n    agentCitations = [],\n" in videos_source

    assert "function extractWorkspaceCitationImageItems(citedHybridCitations = []" in images_source
    assert "function extractLinkedImageItems(citedWebCitations = []" in images_source
    assert "function extractWorkspaceCitationVideoItems(citedHybridCitations = []" in videos_source
    assert "function extractLinkedVideoItems(citedWebCitations = []" in videos_source

    assert '"Image links cited in this response."' in images_source
    assert '"Video links cited in this response."' in videos_source
    assert "returned with this response" not in images_source
    assert "returned with this response" not in videos_source

    print("Gallery renderer signature checks passed.")
    return True


def test_version_is_available():
    """Verify the application includes the inline media gating version."""
    assert_app_version_at_least("0.260.024")
    return True


if __name__ == "__main__":
    tests = [
        test_citation_tracking_helper_resolves_cited_subsets,
        test_inline_galleries_consume_cited_subsets,
        test_sources_disclosure_keeps_full_retrieved_sets,
        test_gallery_renderers_declare_cited_inputs,
        test_version_is_available,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
