#!/usr/bin/env python3
"""
Functional test for latest-release documentation structure.
Version: 0.241.003
Implemented in: 0.241.002; 0.241.003

This test ensures the docs/latest-release landing page exposes current and
previous release sections, and that the current latest-feature guides exist as
individual markdown pages.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
LATEST_RELEASE_INDEX = REPO_ROOT / "docs" / "latest-release" / "index.md"
LATEST_RELEASE_DIR = REPO_ROOT / "docs" / "latest-release"

CURRENT_GUIDES = {
    "guided-tutorials.md": "Guided Tutorials",
    "background-chat.md": "Background Chat",
    "gpt-selection.md": "GPT Selection",
    "tabular-analysis.md": "Tabular Analysis",
    "citation-improvements.md": "Citation Improvements",
    "document-versioning.md": "Document Versioning",
    "summaries-and-export.md": "Summaries and Export",
    "agent-operations.md": "Agent Operations",
    "ai-transparency.md": "AI Transparency",
    "fact-memory.md": "Fact Memory",
    "deployment.md": "Deployment",
    "redis-and-key-vault.md": "Redis and Key Vault",
    "send-feedback.md": "Send Feedback",
    "support-menu.md": "Support Menu",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_latest_release_docs_structure() -> bool:
    print("Testing latest-release documentation structure...")

    config_content = read_text(CONFIG_FILE)
    index_content = read_text(LATEST_RELEASE_INDEX)

    assert 'VERSION = "0.241.003"' in config_content, "Config version marker is not current."

    required_index_markers = [
        'title: "Latest Release Highlights"',
        '## Current Release Features',
        '## Previous Release Features',
        '## Previous Release Bug Fixes',
        'v0.239.001',
        "{{ '/latest-release/guided-tutorials/' | relative_url }}",
        "{{ '/latest-release/background-chat/' | relative_url }}",
        "{{ '/latest-release/gpt-selection/' | relative_url }}",
        "{{ '/latest-release/tabular-analysis/' | relative_url }}",
        "{{ '/latest-release/citation-improvements/' | relative_url }}",
        "{{ '/latest-release/document-versioning/' | relative_url }}",
        "{{ '/latest-release/summaries-and-export/' | relative_url }}",
        "{{ '/latest-release/agent-operations/' | relative_url }}",
        "{{ '/latest-release/ai-transparency/' | relative_url }}",
        "{{ '/latest-release/fact-memory/' | relative_url }}",
        "{{ '/latest-release/deployment/' | relative_url }}",
        "{{ '/latest-release/redis-and-key-vault/' | relative_url }}",
        "{{ '/latest-release/send-feedback/' | relative_url }}",
        "{{ '/latest-release/support-menu/' | relative_url }}",
        "{{ '/latest-release/export-conversation/' | relative_url }}",
    ]
    missing_index_markers = [marker for marker in required_index_markers if marker not in index_content]
    assert not missing_index_markers, f"Missing latest-release index markers: {missing_index_markers}"

    for file_name, title in CURRENT_GUIDES.items():
        guide_path = LATEST_RELEASE_DIR / file_name
        assert guide_path.exists(), f"Missing latest-release guide: {file_name}"
        guide_content = read_text(guide_path)
        assert 'layout: page' in guide_content, f"Guide missing layout frontmatter: {file_name}"
        assert f'title: "{title}"' in guide_content, f"Guide missing title frontmatter: {file_name}"
        assert 'section: "Latest Release"' in guide_content, f"Guide missing Latest Release section marker: {file_name}"

    print("Latest-release documentation structure test passed!")
    return True


if __name__ == "__main__":
    success = test_latest_release_docs_structure()
    sys.exit(0 if success else 1)